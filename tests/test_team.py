"""Test tự tổ chức nhóm: phân rã mục tiêu và tự chọn thành viên."""

from __future__ import annotations

from lifeos.agents.autonomy import AutonomousAgent
from lifeos.agents.team import (
    AGENT_SKILLS,
    GoalBreakdown,
    build_roster,
    decompose,
    self_organize,
)


# --- decompose ---


def test_decompose_creates_tasks():
    breakdown = decompose("Chuyển sang Data Analyst")
    assert breakdown.goal == "Chuyển sang Data Analyst"
    assert len(breakdown.tasks) >= 4
    assert all(task.id and task.description for task in breakdown.tasks)


def test_decompose_is_deterministic():
    first = decompose("mục tiêu X")
    second = decompose("mục tiêu X")
    assert [t.id for t in first.tasks] == [t.id for t in second.tasks]


def test_decompose_task_ids_are_unique():
    tasks = decompose("mục tiêu").tasks
    assert len({t.id for t in tasks}) == len(tasks)


def test_decompose_embeds_goal_in_analysis_task():
    breakdown = decompose("trở thành DevOps")
    analysis = next(t for t in breakdown.tasks if t.id == "gap-analysis")
    assert "trở thành DevOps" in analysis.description


def test_decompose_handles_blank_goal():
    breakdown = decompose("   ")
    assert breakdown.goal == "Mục tiêu cá nhân"
    assert breakdown.tasks


def test_skills_needed_is_deduplicated_and_ordered():
    breakdown = decompose("mục tiêu")
    skills = breakdown.skills_needed
    assert len(skills) == len(set(skills))
    assert skills


def test_every_task_skill_exists_in_roster():
    """Không được đòi một kỹ năng mà không agent nào có."""
    available = {s for skills in AGENT_SKILLS.values() for s in skills}
    for task in decompose("mục tiêu").tasks:
        assert task.skill in available, f"kỹ năng lạ: {task.skill}"


# --- build_roster ---


def test_roster_excludes_agents_without_matching_skill():
    breakdown = GoalBreakdown(
        goal="g",
        tasks=[_task("t", skill="scheduling")],
    )
    members, excluded = build_roster(breakdown)
    assert [a.key for a in members] == ["scheduler"]
    assert "tutor" in excluded
    assert "career" in excluded


def test_roster_never_includes_orchestrator():
    breakdown = decompose("mục tiêu")
    members, _ = build_roster(breakdown)
    assert "orchestrator" not in [a.key for a in members]


def test_roster_for_full_goal_includes_all_specialists():
    members, excluded = build_roster(decompose("mục tiêu"))
    keys = {a.key for a in members}
    assert {"career", "tutor", "scheduler", "critic", "nudger"} <= keys
    assert excluded == []


def test_roster_accepts_extra_agent():
    """Thêm agent mới vào roster là đủ để nó được dùng — không sửa đồ thị."""
    breakdown = GoalBreakdown(
        goal="g",
        tasks=[_task("t", skill="interview-prep")],
    )
    members, _ = build_roster(
        breakdown, extra_agents={"interviewer": ["interview-prep"]}
    )
    assert [a.key for a in members] == ["interviewer"]


def test_roster_gives_agents_their_declared_skills():
    members, _ = build_roster(decompose("mục tiêu"))
    scheduler = next(a for a in members if a.key == "scheduler")
    assert scheduler.state.skills == AGENT_SKILLS["scheduler"]


def test_roster_empty_when_no_task_matches():
    breakdown = GoalBreakdown(goal="g", tasks=[_task("t", skill="không-có-ai")])
    members, excluded = build_roster(breakdown)
    assert members == []
    assert "tutor" in excluded


# --- self_organize ---


def test_self_organize_assigns_all_tasks():
    plan = self_organize("Chuyển sang Data Analyst")
    assert plan.fully_staffed is True
    assert plan.assigned_count == len(plan.results)


def test_self_organize_members_are_the_expected_specialists():
    plan = self_organize("mục tiêu")
    assert set(plan.members) == {"career", "tutor", "scheduler", "critic", "nudger"}


def test_self_organize_uses_contract_net_so_tasks_have_owners():
    plan = self_organize("mục tiêu")
    owners = {r.awarded_to for r in plan.results}
    assert owners <= set(plan.members)
    assert "gap-analysis" in {r.task.id for r in plan.results}


def test_self_organize_parallel_matches_sequential():
    sequential = self_organize("mục tiêu", parallel=False)
    concurrent = self_organize("mục tiêu", parallel=True)
    assert sequential.assigned_count == concurrent.assigned_count
    assert [r.awarded_to for r in sequential.results] == [
        r.awarded_to for r in concurrent.results
    ]


def test_self_organize_with_extra_agent_uses_it():
    plan = self_organize(
        "mục tiêu", extra_agents={"interviewer": ["interview-prep"]}
    )
    # Không có nhiệm vụ nào cần interview-prep nên vẫn bị loại
    assert "interviewer" in plan.excluded


def test_self_organize_excludes_irrelevant_agents():
    plan = self_organize("mục tiêu")
    assert plan.excluded == []


# --- TeamPlan ---


def test_summary_lists_members_and_assignments():
    plan = self_organize("Chuyển sang Data Analyst")
    text = plan.summary()
    assert "Chuyển sang Data Analyst" in text
    assert "Nhóm tự lập" in text
    assert "5/5" in text


def test_summary_marks_unassigned_tasks():
    plan = self_organize("mục tiêu")
    plan.results[0].awarded_to = None
    plan.results[0].reason = "thử nghiệm"
    text = plan.summary()
    assert "✗" in text
    assert plan.unassigned == [plan.results[0].task.id]


def test_fully_staffed_false_when_a_task_unassigned():
    plan = self_organize("mục tiêu")
    plan.results[0].awarded_to = None
    assert plan.fully_staffed is False


def test_fully_staffed_false_for_empty_results():
    assert GoalBreakdown(goal="g").tasks == []
    from lifeos.agents.team import TeamPlan

    assert TeamPlan(breakdown=GoalBreakdown(goal="g")).fully_staffed is False


# --- khả năng mở rộng: nhóm co giãn ---


def test_smaller_goal_yields_smaller_team():
    """Mục tiêu chỉ cần xếp lịch thì nhóm chỉ có một người."""
    breakdown = GoalBreakdown(goal="g", tasks=[_task("t", skill="scheduling")])
    members, excluded = build_roster(breakdown)
    assert len(members) == 1
    assert len(excluded) == 4


def test_roster_capacity_limits_concurrent_work():
    """Một agent năng lực nhỏ không thể nhận trọn vẹn mọi việc.

    Từ T3, thương lượng nhiều vòng chia nhỏ phạm vi cho vừa năng lực nên nhiệm
    vụ thứ hai **được giao một phần** thay vì bị bỏ rơi. Bất biến an toàn vẫn
    giữ nguyên: agent không bao giờ bị quá tải, và phần chưa làm được ghi rõ ra.
    """
    breakdown = GoalBreakdown(
        goal="g",
        tasks=[
            _task("t1", skill="scheduling", effort=0.6),
            _task("t2", skill="scheduling", effort=0.6),
        ],
    )
    members, _ = build_roster(breakdown)
    assert len(members) == 1

    from lifeos.agents.contract_net import ContractNet

    results = ContractNet().run_all(breakdown.tasks, members)
    assert results[0].assigned is True
    assert results[0].partial is False

    # Nhiệm vụ thứ hai chỉ còn 0.4 năng lực -> giao một phần, không bỏ rơi
    assert results[1].assigned is True
    assert results[1].partial is True
    assert results[1].agreed_effort == 0.4
    assert results[1].remaining_effort == 0.2

    # Bất biến: không agent nào bị giao quá năng lực
    assert members[0].state.load <= members[0].state.capacity
    assert members[0].state.load == 0.6 + 0.4


def test_roster_capacity_refuses_when_nothing_is_left():
    """Hết sạch năng lực thì nhiệm vụ phải chịu cảnh không ai nhận."""
    breakdown = GoalBreakdown(
        goal="g",
        tasks=[
            _task("t1", skill="scheduling", effort=1.0),
            _task("t2", skill="scheduling", effort=0.6),
        ],
    )
    members, _ = build_roster(breakdown)
    from lifeos.agents.contract_net import ContractNet

    results = ContractNet().run_all(breakdown.tasks, members)
    assert results[0].assigned is True
    assert results[1].assigned is False
    assert results[1].remaining_effort == 0.6
    assert members[0].state.load <= members[0].state.capacity


def _task(task_id: str, skill: str, effort: float = 0.3, priority: int = 2):
    from lifeos.agents.autonomy import Task

    return Task(
        id=task_id, description=f"việc {task_id}", skill=skill,
        effort=effort, priority=priority,
    )


def test_roster_returns_autonomous_agents_with_state():
    members, _ = build_roster(decompose("mục tiêu"))
    assert all(isinstance(a, AutonomousAgent) for a in members)
    assert all(a.state.load == 0.0 for a in members)