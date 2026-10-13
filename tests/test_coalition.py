"""Test liên minh agent cho việc lớn (T8).

Trước đây một nhiệm vụ luôn chỉ có đúng một agent nhận. Khi việc lớn hơn năng
lực của từng người, bộ điều phối chỉ biết **cắt bớt phạm vi** cho vừa một người
rồi báo phần còn lại là "chưa ai nhận" — dù cộng năng lực cả nhóm lại thì thừa
sức làm trọn.

Ở đây kiểm tra cơ chế liên minh: công bố lại nhiệm vụ với "nhận một phần cũng
được", để nhiều agent cùng bỏ thầu phần mình làm được, rồi ghép các phần đó
thành một liên minh phủ trọn nhiệm vụ.
"""

from __future__ import annotations

import pytest

from lifeos.acl import MessageBus
from lifeos.agents.autonomy import AutonomousAgent, Bid, Task
from lifeos.agents.contract_net import (
    MIN_SLICE_EFFORT,
    ContractNet,
    can_form_coalition,
    plan_award,
    share_of,
    summarize,
)


def _agent(key: str, skills: list[str], capacity: float = 1.0) -> AutonomousAgent:
    return AutonomousAgent(key, skills=skills, capacity=capacity)


def _task(effort: float = 0.3, skill: str = "scheduling", task_id: str = "t") -> Task:
    return Task(id=task_id, description="việc", skill=skill, effort=effort)


def _three_halves() -> list[AutonomousAgent]:
    """Ba agent cùng chuyên môn, mỗi người chỉ còn 0.40 năng lực."""
    return [_agent(key, ["scheduling"], capacity=0.4) for key in ("a", "b", "c")]


# --- phủ được việc mà một người không làm nổi ---


def test_coalition_covers_what_no_single_agent_could():
    """0.90 công sức + ba người 0.40 -> liên minh phủ trọn, không cắt bớt gì."""
    net = ContractNet()
    result = net.run(_task(0.9, task_id="big"), _three_halves())

    assert result.assigned is True
    assert result.is_coalition is True
    assert len(result.coalition) == 3
    assert result.agreed_effort == pytest.approx(0.9)
    assert result.remaining_effort == 0.0
    assert result.partial is False
    assert result.round_count == 2


def test_coalition_splits_effort_without_overloading_anyone():
    """Phần mỗi người nhận không vượt năng lực còn trống của chính người đó."""
    net = ContractNet()
    agents = _three_halves()
    result = net.run(_task(0.9, task_id="big"), agents)

    for share in result.coalition:
        assert share.effort <= 0.4 + 1e-9
    for agent in agents:
        assert agent.state.load <= agent.state.capacity
    assert sum(agent.state.load for agent in agents) == pytest.approx(0.9)


def test_coalition_preferred_over_shrinking_scope():
    """Hai người 0.50 làm việc 0.90 -> phủ trọn, thay vì cắt còn 0.50."""
    net = ContractNet()
    agents = [_agent(key, ["scheduling"], capacity=0.5) for key in ("a", "b")]
    result = net.run(_task(0.9, task_id="big"), agents)

    assert result.is_coalition is True
    assert result.members == ["a", "b"]
    assert result.partial is False
    assert result.remaining_effort == 0.0


def test_partial_coalition_is_reported_honestly():
    """Hai người 0.30 làm việc 0.90 -> phủ 0.60 và nói rõ 0.30 còn thiếu."""
    net = ContractNet()
    agents = [_agent(key, ["scheduling"], capacity=0.3) for key in ("a", "b")]
    result = net.run(_task(0.9, task_id="big"), agents)

    assert result.is_coalition is True
    assert result.agreed_effort == pytest.approx(0.6)
    assert result.remaining_effort == pytest.approx(0.3)
    assert result.partial is True


# --- giữ nguyên hành vi cũ ---


def test_single_agent_still_wins_alone():
    """Một người đủ sức thì nhận trọn — không chia việc vu vơ."""
    net = ContractNet()
    result = net.run(_task(0.3), [_agent("scheduler", ["scheduling"])])

    assert result.is_coalition is False
    assert result.coalition == []
    assert result.awarded_to == "scheduler"
    assert result.members == ["scheduler"]
    assert result.round_count == 1


def test_one_agent_cannot_form_a_coalition_with_itself():
    """Một mình thì không có liên minh: quay về đường chia nhỏ phạm vi như cũ."""
    net = ContractNet()
    agent = _agent("scheduler", ["scheduling"], capacity=0.5)
    result = net.run(_task(0.9, task_id="big"), [agent])

    assert result.is_coalition is False
    assert result.partial is True
    assert result.agreed_effort == 0.5
    assert "chia nhỏ" in result.rounds[1].relaxation


def test_max_rounds_one_disables_coalition():
    """Liên minh cần vòng 2, nên `max_rounds=1` phải tắt được nó."""
    net = ContractNet()
    result = net.run(_task(0.9, task_id="big"), _three_halves(), max_rounds=1)

    assert result.assigned is False
    assert result.is_coalition is False
    assert result.round_count == 1


def test_no_coalition_when_nobody_has_the_skill():
    """Không ai có chuyên môn thì ghép liên minh cũng vô ích -> dừng ở vòng 1."""
    net = ContractNet()
    agents = [_agent(key, ["khac"], capacity=0.4) for key in ("a", "b", "c")]
    result = net.run(_task(0.9, skill="scheduling", task_id="big"), agents)

    assert result.assigned is False
    assert result.round_count == 1
    assert len(result.refusals) == 3


def test_coalition_respects_skill_boundaries():
    """Chỉ agent đúng chuyên môn được vào liên minh, người khác không nhận gì."""
    net = ContractNet()
    insiders = [_agent(key, ["scheduling"], capacity=0.5) for key in ("a", "b")]
    outsider = _agent("ngoai", ["khac"], capacity=1.0)
    result = net.run(_task(0.9, skill="scheduling", task_id="big"), [*insiders, outsider])

    assert result.is_coalition is True
    assert set(result.members) == {"a", "b"}
    assert outsider.state.load == 0.0


def test_coalition_is_deterministic():
    """Cùng đầu vào -> cùng thành viên, cùng thứ tự, cùng phần."""

    def once() -> list[tuple[str, float]]:
        net = ContractNet()
        result = net.run(_task(0.9, task_id="big"), _three_halves())
        return [(share.agent, share.effort) for share in result.coalition]

    assert once() == once()


def test_parallel_bidding_matches_sequential_for_coalition():
    """Bỏ thầu song song và tuần tự phải ghép ra cùng một liên minh."""

    def run(parallel: bool):
        net = ContractNet()
        result = net.run(
            _task(0.9, task_id="big"), _three_halves(), parallel=parallel
        )
        return [(share.agent, round(share.effort, 6)) for share in result.coalition]

    assert run(True) == run(False)


# --- bản ghi và tương thích ngược ---


def test_coalition_round_is_recorded_in_acl():
    """Mỗi thành viên phải nhận một ACCEPT_PROPOSAL riêng, kèm phần của mình."""
    bus = MessageBus()
    net = ContractNet(bus)
    result = net.run(_task(0.9, task_id="big"), _three_halves())

    accepts = [m for m in bus.messages if m.performative.value == "accept-proposal"]
    assert len(accepts) == 3
    assert {m.receiver for m in accepts} == {"a", "b", "c"}
    for message in accepts:
        assert message.metadata["share"] > 0
        assert message.metadata["winner"] == result.awarded_to

    # Vòng liên minh phải nằm trong cùng cuộc hội thoại với vòng 1.
    # `broadcast` gửi một tin cho MỖI người nhận, nên 3 agent x 2 vòng = 6 tin.
    requests = [m for m in bus.messages if m.performative.value == "request"]
    assert len(requests) == 6
    round1 = [m for m in requests if m.metadata.get("round") == 1]
    round2 = [m for m in requests if m.metadata.get("round") == 2]
    assert len(round1) == 3
    assert len(round2) == 3
    # Vòng 1 không cho nhận một phần; vòng 2 thì có.
    assert all(m.metadata.get("allow_partial") is False for m in round1)
    assert all(m.metadata.get("allow_partial") is True for m in round2)
    assert "[vòng 2]" in round2[0].content
    assert "nhận một phần cũng được" in round2[0].content
    assert len(bus.conversation(result.conversation_id)) == len(bus)


def test_coalition_round_allows_partial_bids():
    """Vòng liên minh phải nói rõ là nhận một phần cũng được."""
    net = ContractNet()
    result = net.run(_task(0.9, task_id="big"), _three_halves())

    assert "lập liên minh" in result.rounds[1].relaxation
    assert result.rounds[0].ok is False
    assert result.rounds[1].is_coalition is True


def test_bid_without_share_counts_as_full():
    """Giá thầu không nêu `share` (dựng tay) được coi là nhận trọn."""
    task = _task(0.5)
    legacy = Bid(agent="a", task_id="t")

    assert share_of(legacy, task) == pytest.approx(0.5)
    lead, shares = plan_award(task, [legacy])
    assert lead == "a"
    assert shares == []


def test_plan_award_returns_none_without_bids():
    lead, shares = plan_award(_task(0.5), [])
    assert lead is None
    assert shares == []


# --- các hàm dùng chung ---


def test_can_form_coalition_needs_two_people():
    task = _task(0.9)
    assert can_form_coalition(task, _three_halves()) is True
    assert can_form_coalition(task, [_agent("a", ["scheduling"], capacity=0.4)]) is False


def test_can_form_coalition_false_when_one_agent_fits():
    """Một người đủ sức nhận trọn thì không cần liên minh."""
    task = _task(0.3)
    agents = [_agent("a", ["scheduling"], capacity=1.0), _agent("b", ["scheduling"])]
    assert can_form_coalition(task, agents) is False


def test_can_form_coalition_false_when_skill_missing():
    task = _task(0.9, skill="scheduling")
    agents = [_agent(key, ["khac"], capacity=0.4) for key in ("a", "b")]
    assert can_form_coalition(task, agents) is False


def test_min_slice_effort_threshold_is_respected():
    """Phần quá nhỏ không đáng nhận, kể cả trong liên minh."""
    task = _task(1.0)
    agents = [_agent("a", ["scheduling"], capacity=0.5), _agent("b", ["scheduling"], capacity=0.5)]
    net = ContractNet()
    result = net.run(task, agents)

    assert result.is_coalition is True
    assert all(share.effort >= MIN_SLICE_EFFORT - 1e-9 for share in result.coalition)


def test_summarize_mentions_coalition():
    net = ContractNet()
    text = summarize(net.run_all([_task(0.9, task_id="big")], _three_halves()))

    assert "liên minh" in text
    assert "do liên minh nhận" in text
    assert "a 0.40" in text


# --- báo cáo trong kế hoạch nhóm ---


def _plan_with(agents: list[AutonomousAgent]):
    from lifeos.agents.team import GoalBreakdown, TeamPlan

    net = ContractNet()
    breakdown = GoalBreakdown(
        goal="g",
        tasks=[Task(id="t", description="việc", skill="scheduling", effort=0.9)],
    )
    return TeamPlan(
        breakdown=breakdown,
        members=[agent.key for agent in agents],
        results=net.run_all(breakdown.tasks, agents),
    )


def test_team_plan_reports_coalitions():
    """Kế hoạch nhóm phải nêu tên liên minh, không chỉ trưởng nhóm."""
    plan = _plan_with(_three_halves())

    assert plan.coalitions == ["t"]
    assert plan.coalition_members == 3
    assert plan.fully_covered is True
    assert plan.remaining_effort == 0.0

    text = plan.summary()
    assert "liên minh" in text
    assert "a 0.40" in text
    assert "c 0.10" in text


def test_team_plan_without_coalition_reports_none():
    """Đường đi thường gặp không được sinh ra báo cáo liên minh rỗng."""
    plan = _plan_with([_agent("scheduler", ["scheduling"], capacity=1.0)])

    assert plan.coalitions == []
    assert plan.coalition_members == 0
    assert "liên minh" not in plan.summary()


def test_team_plan_fully_covered_thanks_to_coalition():
    """Điểm mấu chốt: nhóm thiếu năng lực cá nhân vẫn phủ trọn nhờ liên minh."""
    from lifeos.agents.team import GoalBreakdown, TeamPlan

    task = Task(id="t", description="việc", skill="scheduling", effort=0.9)
    breakdown = GoalBreakdown(goal="g", tasks=[task])

    alone = TeamPlan(
        breakdown=breakdown,
        members=["a"],
        results=ContractNet().run_all([task], [_agent("a", ["scheduling"], capacity=0.4)]),
    )
    assert alone.fully_covered is False  # một mình thì phải cắt bớt phạm vi
    assert alone.partial == ["t"]

    together = _plan_with(_three_halves())
    assert together.fully_covered is True  # ba người thì không phải cắt gì
    assert together.partial == []
