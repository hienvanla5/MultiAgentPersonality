"""Test Contract Net Protocol."""

from __future__ import annotations

from lifeos.acl import MessageBus, Performative
from lifeos.agents.autonomy import AutonomousAgent, Task
from lifeos.agents.contract_net import ContractNet, summarize


def _task(
    task_id: str = "t1",
    skill: str = "planning",
    effort: float = 0.3,
    priority: int = 2,
) -> Task:
    return Task(
        id=task_id, description=f"việc {task_id}", skill=skill,
        effort=effort, priority=priority,
    )


def _agent(key: str = "tutor", skills=("planning",), capacity: float = 1.0):
    return AutonomousAgent(key, skills=list(skills), capacity=capacity)


# --- pha 1 & 2: công bố và bỏ thầu ---


def test_run_awards_to_capable_agent():
    cn = ContractNet()
    result = cn.run(_task(), [_agent()])
    assert result.assigned is True
    assert result.awarded_to == "tutor"
    assert result.bid_count == 1


def test_announcement_is_broadcast_to_all_candidates():
    bus = MessageBus()
    cn = ContractNet(bus)
    cn.run(_task(), [_agent("tutor"), _agent("critic"), _agent("nudger")])

    announces = [
        m for m in bus.messages if m.performative == Performative.REQUEST
    ]
    assert len(announces) == 3
    assert {m.receiver for m in announces} == {"tutor", "critic", "nudger"}
    assert all(m.sender == "orchestrator" for m in announces)


def test_announcement_carries_task_metadata_and_protocol():
    bus = MessageBus()
    ContractNet(bus).run(_task("t-42"), [_agent()])
    announce = bus.messages[0]
    assert announce.metadata["task_id"] == "t-42"
    assert announce.protocol == "contract-net"


def test_bidders_reply_with_propose():
    bus = MessageBus()
    ContractNet(bus).run(_task(), [_agent("tutor"), _agent("critic")])
    proposes = [m for m in bus.messages if m.performative == Performative.PROPOSE]
    assert len(proposes) == 2
    assert {m.sender for m in proposes} == {"tutor", "critic"}


def test_incapable_agent_refuses_with_reason_in_message():
    bus = MessageBus()
    cn = ContractNet(bus)
    result = cn.run(_task(skill="coding"), [_agent("tutor", skills=("planning",))])

    refusals = [m for m in bus.messages if m.performative == Performative.REFUSE]
    assert len(refusals) == 1
    assert "chuyên môn" in refusals[0].content
    assert result.assigned is False
    assert len(result.refusals) == 1


# --- pha 3: trao thầu ---


def test_award_message_goes_to_winner_only():
    bus = MessageBus()
    cn = ContractNet(bus)
    # tutor còn trống nhiều hơn critic -> tutor thắng
    busy = _agent("critic")
    busy.accept(_task("pre", effort=0.7))
    result = cn.run(_task(), [_agent("tutor"), busy])

    awards = [
        m for m in bus.messages if m.performative == Performative.ACCEPT_PROPOSAL
    ]
    assert len(awards) == 1
    assert awards[0].metadata["winner"] == result.awarded_to
    assert awards[0].sender == "orchestrator"


def test_losers_receive_reject_proposal():
    bus = MessageBus()
    cn = ContractNet(bus)
    cn.run(_task(), [_agent("tutor"), _agent("critic")])

    rejects = [
        m for m in bus.messages if m.performative == Performative.REJECT_PROPOSAL
    ]
    assert len(rejects) == 1
    assert "đã giao cho" in rejects[0].content


def test_winner_gets_accept_and_losers_get_reject():
    bus = MessageBus()
    result = ContractNet(bus).run(_task(), [_agent("a"), _agent("b")])
    winner = result.awarded_to
    losers = [k for k in ("a", "b") if k != winner]

    assert any(
        m.performative == Performative.ACCEPT_PROPOSAL and m.receiver == winner
        for m in bus.messages
    )
    assert any(
        m.performative == Performative.REJECT_PROPOSAL and m.receiver == losers[0]
        for m in bus.messages
    )


def test_winner_load_increases_after_award():
    cn = ContractNet()
    agent = _agent()
    cn.run(_task(effort=0.4), [agent])
    assert agent.state.load == 0.4
    assert agent.state.completed == 0


def test_award_is_deterministic_for_identical_agents():
    """Cùng đầu vào phải cho cùng người thắng, không phụ thuộc thứ tự duyệt."""
    first = ContractNet().run(_task(), [_agent("a"), _agent("b")])
    second = ContractNet().run(_task(), [_agent("b"), _agent("a")])
    assert first.awarded_to == second.awarded_to


# --- không có người nhận ---


def test_no_candidates_gives_reason():
    result = ContractNet().run(_task(), [])
    assert result.assigned is False
    assert "không có agent nào" in result.reason


def test_all_refuse_gives_aggregated_reason():
    result = ContractNet().run(_task(skill="coding"), [_agent("tutor")])
    assert result.assigned is False
    assert "tất cả đều từ chối" in result.reason
    assert "tutor" in result.reason


def test_bus_records_inform_when_nobody_takes_task():
    bus = MessageBus()
    ContractNet(bus).run(_task(skill="coding"), [_agent("tutor")])
    informs = [m for m in bus.messages if m.performative == Performative.INFORM]
    assert len(informs) == 1
    assert "Không ai nhận" in informs[0].content


# --- conversation ---


def test_all_messages_share_one_conversation():
    bus = MessageBus()
    cn = ContractNet(bus)
    result = cn.run(_task(), [_agent("tutor"), _agent("critic")])
    thread = bus.conversation(result.conversation_id)
    # 1 công bố x 2 agent + 2 phản hồi + 1 trao thầu + 1 từ chối
    assert len(thread) == 6


def test_separate_tasks_have_separate_conversations():
    bus = MessageBus()
    cn = ContractNet(bus)
    first = cn.run(_task("a"), [_agent()])
    second = cn.run(_task("b"), [_agent()])
    assert first.conversation_id != second.conversation_id


# --- run_all ---


def test_run_all_assigns_urgent_tasks_first():
    cn = ContractNet()
    agent = _agent(capacity=0.5)
    results = cn.run_all(
        [_task("low", effort=0.4, priority=3), _task("high", effort=0.4, priority=1)],
        [agent],
    )
    assert results[0].task.id == "high"
    assert results[0].assigned is True


def test_run_all_does_not_overload_a_single_agent():
    """Agent đã nhận việc thì nhiệm vụ sau phải bị từ chối vì hết năng lực."""
    cn = ContractNet()
    agent = _agent(capacity=0.5)
    results = cn.run_all(
        [_task("a", effort=0.5), _task("b", effort=0.5)], [agent]
    )
    assert results[0].assigned is True
    assert results[1].assigned is False
    assert agent.state.load == 0.5


def test_run_all_spreads_work_across_agents():
    cn = ContractNet()
    agents = [_agent("a", capacity=0.5), _agent("b", capacity=0.5)]
    results = cn.run_all(
        [_task("t1", effort=0.5), _task("t2", effort=0.5)], agents
    )
    assert all(r.assigned for r in results)
    assert {r.awarded_to for r in results} == {"a", "b"}


def test_run_all_empty_task_list():
    assert ContractNet().run_all([], [_agent()]) == []


# --- song song ---


def test_parallel_bidding_gives_same_winner_as_sequential():
    agents_seq = [_agent("a"), _agent("b"), _agent("c")]
    agents_par = [_agent("a"), _agent("b"), _agent("c")]
    sequential = ContractNet().run(_task(), agents_seq, parallel=False)
    concurrent = ContractNet().run(_task(), agents_par, parallel=True)
    assert sequential.awarded_to == concurrent.awarded_to
    assert sequential.bid_count == concurrent.bid_count


def test_parallel_bidding_collects_all_bids():
    agents = [_agent(k) for k in ("a", "b", "c", "d")]
    result = ContractNet().run(_task(), agents, parallel=True)
    assert result.bid_count == 4


def test_parallel_bidding_handles_mixed_refusals():
    agents = [
        _agent("a", skills=("planning",)),
        _agent("b", skills=("coding",)),
        _agent("c", skills=("planning",)),
    ]
    result = ContractNet().run(_task(skill="planning"), agents, parallel=True)
    assert result.bid_count == 2
    assert len(result.refusals) == 1
    assert result.awarded_to in {"a", "c"}


# --- summarize ---


def test_summarize_empty():
    assert "Không có nhiệm vụ" in summarize([])


def test_summarize_counts_and_lists():
    cn = ContractNet()
    results = cn.run_all([_task("a"), _task("b", skill="coding")], [_agent()])
    text = summarize(results)
    assert "1/2" in text
    assert "✓ a" in text
    assert "✗ b" in text
