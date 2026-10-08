"""Test thương lượng nhiều vòng (T3).

Trước đây Contract Net chỉ chạy đúng một vòng: công bố một lần, ai từ chối thì
thôi. Nếu cả nhóm cùng từ chối vì nhiệm vụ đòi hỏi nhiều công sức hơn phần năng
lực còn trống thì nhiệm vụ bị bỏ rơi, dù chỉ cần chia nhỏ phạm vi là giải được.
"""

from __future__ import annotations

import pytest

from lifeos.acl import MessageBus
from lifeos.agents.autonomy import AutonomousAgent, Task
from lifeos.agents.contract_net import (
    MAX_ROUNDS,
    MIN_SLICE_EFFORT,
    ContractNet,
    ContractNetResult,
    RoundRecord,
    summarize,
)
from lifeos.agents.team import build_roster, decompose, self_organize


def _agent(key: str, skills: list[str], capacity: float = 1.0) -> AutonomousAgent:
    return AutonomousAgent(key, skills=skills, capacity=capacity)


def _task(effort: float = 0.3, skill: str = "scheduling", task_id: str = "t") -> Task:
    return Task(id=task_id, description="việc", skill=skill, effort=effort)


# --- hành vi một vòng vẫn giữ nguyên ---


def test_single_round_when_bid_succeeds_first_time():
    net = ContractNet()
    result = net.run(_task(0.3), [_agent("scheduler", ["scheduling"])])
    assert result.assigned is True
    assert result.round_count == 1
    assert result.negotiated is False


def test_max_rounds_one_disables_renegotiation():
    """Đặt `max_rounds=1` để tắt hẳn thương lượng nhiều vòng."""
    net = ContractNet()
    agent = _agent("scheduler", ["scheduling"], capacity=0.5)
    result = net.run(_task(0.9, task_id="big"), [agent], max_rounds=1)
    assert result.assigned is False
    assert result.round_count == 1
    assert result.remaining_effort == 0.9


# --- công bố lại khi công sức vượt năng lực ---


def test_renegotiates_when_task_exceeds_capacity():
    """Công sức vượt năng lực -> vòng 2 chia nhỏ cho vừa và giao được."""
    net = ContractNet()
    agent = _agent("scheduler", ["scheduling"], capacity=0.5)
    result = net.run(_task(0.9, task_id="big"), [agent])

    assert result.assigned is True
    assert result.round_count == 2
    assert result.negotiated is True
    assert result.awarded_to == "scheduler"


def test_partial_assignment_is_recorded_honestly():
    """Chỉ giao được một phần thì phải nói rõ phần còn lại, không im lặng."""
    net = ContractNet()
    agent = _agent("scheduler", ["scheduling"], capacity=0.5)
    result = net.run(_task(0.9, task_id="big"), [agent])

    assert result.partial is True
    assert result.original_effort == 0.9
    assert result.agreed_effort == 0.5
    assert result.remaining_effort == pytest.approx(0.4)


def test_full_assignment_is_not_marked_partial():
    net = ContractNet()
    result = net.run(_task(0.3), [_agent("scheduler", ["scheduling"])])
    assert result.partial is False
    assert result.remaining_effort == 0.0


def test_first_round_failure_is_recorded():
    """Vòng thất bại phải nằm trong bản ghi, không bị nuốt."""
    net = ContractNet()
    agent = _agent("scheduler", ["scheduling"], capacity=0.5)
    result = net.run(_task(0.9, task_id="big"), [agent])

    first = result.rounds[0]
    assert first.round == 1
    assert first.ok is False
    assert first.refusals
    assert first.relaxation == ""


def test_second_round_records_what_was_relaxed():
    net = ContractNet()
    agent = _agent("scheduler", ["scheduling"], capacity=0.5)
    result = net.run(_task(0.9, task_id="big"), [agent])

    second = result.rounds[1]
    assert second.round == 2
    assert second.ok is True
    assert "chia nhỏ" in second.relaxation
    assert "0.90" in second.relaxation
    assert "0.50" in second.relaxation


def test_rounds_share_one_conversation():
    """Các vòng là một cuộc thương lượng, không phải nhiều cuộc rời rạc."""
    bus = MessageBus()
    net = ContractNet(bus)
    agent = _agent("scheduler", ["scheduling"], capacity=0.5)
    result = net.run(_task(0.9, task_id="big"), [agent])

    assert result.round_count == 2
    messages = bus.conversation(result.conversation_id)
    assert len(messages) == len(bus)
    # Bản ghi phải cho thấy cả hai vòng
    assert any(m.metadata.get("round") == 1 for m in messages)
    assert any(m.metadata.get("round") == 2 for m in messages)


def test_second_round_announcement_mentions_the_round():
    bus = MessageBus()
    net = ContractNet(bus)
    agent = _agent("scheduler", ["scheduling"], capacity=0.5)
    net.run(_task(0.9, task_id="big"), [agent])

    requests = [m for m in bus.messages if m.performative.value == "request"]
    assert len(requests) == 2
    assert "[vòng 2]" in requests[1].content


def test_agent_load_never_exceeds_capacity():
    """Bất biến an toàn: dù chia nhỏ thế nào, agent cũng không bị quá tải."""
    net = ContractNet()
    agent = _agent("scheduler", ["scheduling"], capacity=0.5)
    net.run(_task(0.9, task_id="big"), [agent])
    assert agent.state.load <= agent.state.capacity
    assert agent.state.load == pytest.approx(0.5)


# --- không nới được thì dừng ---


def test_no_relaxation_when_skill_missing():
    """Không ai có chuyên môn thì nới công sức cũng vô ích -> dừng ở vòng 1."""
    net = ContractNet()
    result = net.run(_task(0.9, skill="ky-nang-la"), [_agent("scheduler", ["scheduling"])])
    assert result.assigned is False
    assert result.round_count == 1
    assert result.remaining_effort == 0.9


def test_no_relaxation_when_everyone_is_full():
    """Cả nhóm kín lịch là vấn đề thời điểm, không phải phạm vi -> dừng."""
    net = ContractNet()
    agent = _agent("scheduler", ["scheduling"], capacity=0.5)
    agent.accept(_task(0.5, task_id="other"))
    result = net.run(_task(0.9, task_id="big"), [agent])

    assert result.assigned is False
    assert result.round_count == 1


def test_no_relaxation_when_effort_already_fits():
    """Công sức đã vừa mà vẫn thất bại thì nới tiếp không giải quyết được gì."""
    net = ContractNet()
    result = net.run(_task(0.2, skill="ky-nang-la"), [_agent("x", ["ky-nang-la"])])
    assert result.round_count == 1


def test_stops_before_min_slice_effort():
    """Năng lực còn quá ít thì chia nhỏ không còn ý nghĩa."""
    net = ContractNet()
    agent = _agent("scheduler", ["scheduling"], capacity=1.0)
    # Giữ gần hết năng lực, chỉ còn 0.05 < MIN_SLICE_EFFORT
    agent.accept(_task(0.95, task_id="other"))
    assert agent.state.available == pytest.approx(0.05)

    result = net.run(_task(0.9, task_id="big"), [agent])
    assert result.assigned is False
    assert result.round_count == 1
    assert MIN_SLICE_EFFORT == 0.1


def test_no_candidates_at_all():
    net = ContractNet()
    result = net.run(_task(0.3), [])
    assert result.assigned is False
    assert "không có agent nào" in result.reason


def test_all_agents_refuse_on_skill():
    net = ContractNet()
    agents = [_agent("a", ["x"]), _agent("b", ["y"])]
    result = net.run(_task(0.3, skill="z"), agents)
    assert result.assigned is False
    assert len(result.refusals) == 2
    assert result.round_count == 1


# --- run_all ---


def test_run_all_uses_multi_round():
    net = ContractNet()
    agent = _agent("scheduler", ["scheduling"], capacity=0.5)
    results = net.run_all([_task(0.9, task_id="big")], [agent])
    assert results[0].round_count == 2
    assert results[0].partial is True


def test_run_all_respects_max_rounds():
    net = ContractNet()
    agent = _agent("scheduler", ["scheduling"], capacity=0.5)
    results = net.run_all([_task(0.9, task_id="big")], [agent], max_rounds=1)
    assert results[0].assigned is False


def test_run_all_partial_does_not_overload_later_tasks():
    """Sau khi chia nhỏ, năng lực đã dùng hết nên nhiệm vụ sau vẫn phải chờ."""
    net = ContractNet()
    agent = _agent("scheduler", ["scheduling"], capacity=0.5)
    results = net.run_all(
        [
            Task(id="t1", description="a", skill="scheduling", effort=0.5, priority=1),
            Task(id="t2", description="b", skill="scheduling", effort=0.5, priority=2),
        ],
        [agent],
    )
    assert results[0].assigned is True
    assert results[1].assigned is False
    assert agent.state.load <= agent.state.capacity


# --- tất định ---


def test_negotiation_is_deterministic():
    def once():
        net = ContractNet()
        agent = _agent("scheduler", ["scheduling"], capacity=0.5)
        r = net.run(_task(0.9, task_id="big"), [agent])
        return (r.awarded_to, r.round_count, r.agreed_effort, r.remaining_effort)

    assert once() == once()


def test_parallel_bidding_matches_sequential_in_multi_round():
    def run(parallel: bool):
        net = ContractNet()
        agents = [
            _agent("career", ["gap-analysis"], capacity=0.4),
            _agent("tutor", ["curriculum"], capacity=0.4),
        ]
        return net.run(_task(0.9, skill="gap-analysis", task_id="big"), agents, parallel=parallel)

    sequential = run(False)
    concurrent = run(True)
    assert sequential.awarded_to == concurrent.awarded_to
    assert sequential.round_count == concurrent.round_count
    assert sequential.agreed_effort == concurrent.agreed_effort


# --- summarize ---


def test_summarize_mentions_renegotiation():
    net = ContractNet()
    agent = _agent("scheduler", ["scheduling"], capacity=0.5)
    text = summarize(net.run_all([_task(0.9, task_id="big")], [agent]))
    assert "công bố lại" in text
    assert "chưa ai nhận" in text


def test_summarize_plain_case_has_no_renegotiation_note():
    net = ContractNet()
    text = summarize(net.run_all([_task(0.3)], [_agent("scheduler", ["scheduling"])]))
    assert "công bố lại" not in text
    assert "✓ t → scheduler" in text


def test_summarize_empty():
    assert "Không có nhiệm vụ" in summarize([])


# --- tích hợp với tự tổ chức nhóm ---


def test_self_organize_reports_partial_tasks():
    """Nhóm thiếu năng lực thì kế hoạch phải nói rõ phần chưa làm được."""
    plan = self_organize("mục tiêu")
    assert plan.fully_staffed is True
    # Với năng lực mặc định thì không có gì bị cắt
    assert plan.partial == []
    assert plan.remaining_effort == 0.0
    assert plan.fully_covered is True


def test_team_plan_flags_partial_when_capacity_is_tight():
    from lifeos.agents.team import GoalBreakdown, TeamPlan

    net = ContractNet()
    agent = _agent("scheduler", ["scheduling"], capacity=0.3)
    breakdown = GoalBreakdown(
        goal="g",
        tasks=[Task(id="t", description="việc", skill="scheduling", effort=0.9)],
    )
    results = net.run_all(breakdown.tasks, [agent])
    plan = TeamPlan(breakdown=breakdown, members=["scheduler"], results=results)

    assert plan.fully_staffed is True  # đã giao, chỉ là giao một phần
    assert plan.fully_covered is False
    assert plan.partial == ["t"]
    assert plan.remaining_effort == pytest.approx(0.6)
    assert "chỉ 0.30/0.90" in plan.summary()


def test_team_plan_summary_marks_rounds():
    from lifeos.agents.team import GoalBreakdown, TeamPlan

    net = ContractNet()
    agent = _agent("scheduler", ["scheduling"], capacity=0.3)
    breakdown = GoalBreakdown(
        goal="g",
        tasks=[Task(id="t", description="việc", skill="scheduling", effort=0.9)],
    )
    plan = TeamPlan(
        breakdown=breakdown,
        members=["scheduler"],
        results=net.run_all(breakdown.tasks, [agent]),
    )
    assert "[2 vòng]" in plan.summary()


def test_roster_capacity_still_limits_total_work():
    """Bất biến gốc vẫn giữ: tổng tải không vượt năng lực của nhóm."""
    from lifeos.agents.team import GoalBreakdown

    agent = _agent("scheduler", ["scheduling"], capacity=0.5)
    breakdown = GoalBreakdown(
        goal="g",
        tasks=[
            Task(id="t1", description="a", skill="scheduling", effort=0.6),
            Task(id="t2", description="b", skill="scheduling", effort=0.6),
        ],
    )
    net = ContractNet()
    net.run_all(breakdown.tasks, [agent])
    assert agent.state.load <= agent.state.capacity


def test_max_rounds_default_is_reasonable():
    assert MAX_ROUNDS >= 2
