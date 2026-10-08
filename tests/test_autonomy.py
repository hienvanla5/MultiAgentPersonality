"""Test agent tự trị: trạng thái nội bộ và quyền tự quyết định."""

from __future__ import annotations

from lifeos.agents.autonomy import (
    AutonomousAgent,
    Bid,
    Refusal,
    Task,
)


def _task(
    task_id: str = "t1",
    skill: str = "planning",
    effort: float = 0.3,
    priority: int = 2,
) -> Task:
    return Task(
        id=task_id,
        description=f"việc {task_id}",
        skill=skill,
        effort=effort,
        priority=priority,
    )


# --- Task ---


def test_urgency_mapping():
    assert _task(priority=1).urgency == 1.0
    assert _task(priority=2).urgency == 0.6
    assert _task(priority=3).urgency == 0.3


def test_effort_must_be_positive():
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        Task(id="x", description="y", effort=0.0)


# --- trạng thái nội bộ ---


def test_agent_starts_free_with_default_capacity():
    agent = AutonomousAgent("tutor", skills=["planning"])
    assert agent.state.load == 0.0
    assert agent.state.available == 1.0
    assert agent.state.is_free is True
    assert agent.state.completed == 0


def test_agent_exposes_persona_name_and_role():
    agent = AutonomousAgent("tutor", skills=["planning"])
    assert agent.name == "Giáo Viên"
    assert agent.role


def test_available_shrinks_after_accept():
    agent = AutonomousAgent("tutor", skills=["planning"])
    agent.accept(_task(effort=0.4))
    assert agent.state.load == 0.4
    assert round(agent.state.available, 4) == 0.6


def test_load_never_exceeds_capacity():
    agent = AutonomousAgent("tutor", skills=["planning"])
    agent.accept(_task("a", effort=0.8))
    agent.accept(_task("b", effort=0.8))
    assert agent.state.load == agent.state.capacity


def test_history_records_lifecycle():
    agent = AutonomousAgent("tutor", skills=["planning"])
    task = _task()
    agent.accept(task)
    agent.finish(task)
    assert any("nhận" in note for note in agent.state.history)
    assert any("xong" in note for note in agent.state.history)


# --- can_handle ---


def test_can_handle_true_for_matching_skill():
    agent = AutonomousAgent("tutor", skills=["planning"])
    assert agent.can_handle(_task(skill="planning")) is True


def test_can_handle_false_for_unknown_skill():
    agent = AutonomousAgent("tutor", skills=["planning"])
    assert agent.can_handle(_task(skill="coding")) is False


def test_can_handle_true_when_task_has_no_skill_requirement():
    agent = AutonomousAgent("tutor", skills=["planning"])
    assert agent.can_handle(_task(skill="")) is True


def test_can_handle_false_when_full():
    agent = AutonomousAgent("tutor", skills=["planning"])
    agent.accept(_task("a", effort=1.0))
    assert agent.state.is_free is False
    assert agent.can_handle(_task("b", effort=0.1)) is False


def test_can_handle_false_when_effort_exceeds_available():
    agent = AutonomousAgent("tutor", skills=["planning"])
    agent.accept(_task("a", effort=0.7))
    assert agent.can_handle(_task("b", effort=0.5)) is False
    assert agent.can_handle(_task("c", effort=0.2)) is True


# --- assess: tự đánh giá ---


def test_assess_returns_bid_when_capable():
    agent = AutonomousAgent("tutor", skills=["planning"])
    result = agent.assess(_task(skill="planning"))
    assert isinstance(result, Bid)
    assert result.agent == "tutor"
    assert 0.0 <= result.confidence <= 1.0
    assert 0.0 <= result.cost <= 1.0


def test_assess_refuses_wrong_skill_with_reason():
    agent = AutonomousAgent("tutor", skills=["planning"])
    result = agent.assess(_task(skill="coding"))
    assert isinstance(result, Refusal)
    assert "chuyên môn" in result.reason


def test_assess_refuses_when_out_of_capacity():
    agent = AutonomousAgent("tutor", skills=["planning"])
    agent.accept(_task("a", effort=1.0))
    result = agent.assess(_task("b", skill="planning", effort=0.1))
    assert isinstance(result, Refusal)
    assert "năng lực" in result.reason


def test_assess_refuses_when_effort_too_large_and_explains():
    agent = AutonomousAgent("tutor", skills=["planning"])
    agent.accept(_task("a", effort=0.8))
    result = agent.assess(_task("b", skill="planning", effort=0.5))
    assert isinstance(result, Refusal)
    assert "0.50" in result.reason or "0.5" in result.reason


def test_refusal_increments_counter():
    agent = AutonomousAgent("tutor", skills=["planning"])
    agent.assess(_task(skill="coding"))
    agent.assess(_task(skill="coding"))
    assert agent.state.refused == 2


def test_assess_does_not_change_load():
    agent = AutonomousAgent("tutor", skills=["planning"])
    agent.assess(_task(skill="planning"))
    assert agent.state.load == 0.0


def test_confidence_higher_for_idle_agent():
    idle = AutonomousAgent("tutor", skills=["planning"])
    busy = AutonomousAgent("critic", skills=["planning"])
    busy.accept(_task("a", effort=0.7))

    idle_bid = idle.assess(_task("x", skill="planning", effort=0.2))
    busy_bid = busy.assess(_task("y", skill="planning", effort=0.2))
    assert idle_bid.confidence > busy_bid.confidence


def test_confidence_grows_with_trust():
    agent = AutonomousAgent("tutor", skills=["planning"])
    before = agent.assess(_task("x", skill="planning")).confidence
    for i in range(4):
        task = _task(f"done-{i}", effort=0.1)
        agent.accept(task)
        agent.finish(task)
    after = agent.assess(_task("y", skill="planning")).confidence
    assert after > before


# --- Bid.score ---


def test_bid_score_prefers_confident_and_cheap():
    strong = Bid(agent="a", task_id="t", confidence=0.9, cost=0.1)
    weak = Bid(agent="b", task_id="t", confidence=0.3, cost=0.9)
    assert strong.score > weak.score


# --- vòng đời ---


def test_finish_frees_capacity_and_counts_completion():
    agent = AutonomousAgent("tutor", skills=["planning"])
    task = _task(effort=0.5)
    agent.accept(task)
    agent.finish(task)
    assert agent.state.load == 0.0
    assert agent.state.completed == 1


def test_finish_failure_lowers_trust():
    agent = AutonomousAgent("tutor", skills=["planning"])
    task = _task(effort=0.3)
    agent.accept(task)
    before = agent.state.trust
    agent.finish(task, success=False)
    assert agent.state.trust < before
    assert agent.state.completed == 0


def test_trust_is_clamped_to_one():
    agent = AutonomousAgent("tutor", skills=["planning"])
    for i in range(20):
        task = _task(f"t{i}", effort=0.1)
        agent.accept(task)
        agent.finish(task)
    assert agent.state.trust == 1.0


def test_trust_never_negative():
    agent = AutonomousAgent("tutor", skills=["planning"])
    for i in range(20):
        task = _task(f"t{i}", effort=0.1)
        agent.accept(task)
        agent.finish(task, success=False)
    assert agent.state.trust == 0.0


def test_release_returns_capacity_without_counting_done():
    agent = AutonomousAgent("tutor", skills=["planning"])
    task = _task(effort=0.6)
    agent.accept(task)
    agent.release(task)
    assert agent.state.load == 0.0
    assert agent.state.completed == 0
    assert agent.state.trust == 0.5


def test_agent_can_be_reused_after_finishing():
    agent = AutonomousAgent("tutor", skills=["planning"])
    first = _task("a", effort=1.0)
    agent.accept(first)
    assert agent.can_handle(_task("b", effort=0.5)) is False
    agent.finish(first)
    assert agent.can_handle(_task("b", effort=0.5)) is True


def test_agent_with_zero_capacity_refuses_everything():
    agent = AutonomousAgent("tutor", skills=["planning"], capacity=0.0)
    assert agent.can_handle(_task(effort=0.1)) is False
    assert isinstance(agent.assess(_task(effort=0.1)), Refusal)
