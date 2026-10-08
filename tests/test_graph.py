"""Test tích hợp đồ thị LangGraph: lập kế hoạch, vòng giảm tải, điều chỉnh."""

from __future__ import annotations

from lifeos.graph import REDUCED_LOAD_FACTOR, adjust_plan, create_plan
from lifeos.memory import Store, VectorMemory
from lifeos.models import LifeOSPlan


def test_create_plan_full_pipeline(fake_llm, profile):
    plan = create_plan(profile, llm=fake_llm)

    assert plan.goal is not None
    assert plan.goal.description == profile.goal_summary
    assert plan.gaps and plan.gaps[0].skill == "SQL"
    assert plan.study_plan is not None
    assert plan.first_week is not None
    assert plan.roundtable is not None
    assert len(plan.roundtable.turns) == 2
    assert plan.roundtable.synthesis is not None
    assert plan.roundtable.synthesis.content


def test_overload_triggers_exactly_one_replan(fake_llm, profile):
    create_plan(profile, llm=fake_llm)
    # Lần 1: quá tải -> giảm tải -> lần 2: ổn -> dừng
    assert fake_llm.count("WeeklySchedule") == 2
    assert fake_llm.count("Critique") == 2


def test_roundtable_both_personas_speak_when_run_in_parallel(fake_llm, profile):
    """Phản Biện và Động Viên chạy song song nhưng vẫn phải đủ cả hai lượt."""
    plan = create_plan(profile, llm=fake_llm)

    personas = [turn.persona for turn in plan.roundtable.turns]
    assert personas == ["Người Phản Biện", "Người Động Viên"]
    assert all(turn.content for turn in plan.roundtable.turns)
    # Động Viên dùng đường văn bản tự do
    assert fake_llm.count("text") >= 1


def test_roundtable_survives_critic_failure(profile, fake_llm_cls):
    """Phản Biện lỗi thì vẫn phải ra kế hoạch, không sập cả luồng."""

    class BrokenCritic(fake_llm_cls):
        def structured(self, system_prompt, user_prompt, schema):
            if schema.__name__ == "Critique":
                raise RuntimeError("dịch vụ phản biện chết")
            return super().structured(system_prompt, user_prompt, schema)

    plan = create_plan(profile, llm=BrokenCritic())

    assert plan.roundtable is not None
    assert len(plan.roundtable.turns) == 2
    assert "Không lấy được phản biện" in plan.roundtable.turns[0].content


def test_no_replan_when_not_overloaded(fake_llm_cls, profile):
    llm = fake_llm_cls(overload_times=0)
    create_plan(profile, llm=llm)
    assert llm.count("WeeklySchedule") == 1
    assert llm.count("Critique") == 1


def test_week_respects_hour_budget(fake_llm, profile):
    profile.hours_per_week = 3
    plan = create_plan(profile, llm=fake_llm)
    assert plan.first_week.total_hours <= profile.hours_per_week


def test_plan_is_persisted_to_store(fake_llm, profile, tmp_path):
    store = Store(f"sqlite:///{tmp_path / 'plan.db'}")
    plan = create_plan(profile, llm=fake_llm, store=store)

    saved = store.latest_plan(profile.goal_summary)
    assert saved is not None
    assert saved["goal"]["description"] == profile.goal_summary
    assert plan.goal is not None


def test_adjust_plan_moves_to_next_week(fake_llm, profile):
    plan = create_plan(profile, llm=fake_llm)
    new_plan, event = adjust_plan(
        plan,
        profile,
        "Trượt 2 buổi vì deadline gấp",
        missed=["Học SQL"],
        llm=fake_llm,
    )

    assert event.reason == "Trượt 2 buổi vì deadline gấp"
    assert event.old_week == 1
    assert event.new_week == 2
    assert new_plan.first_week is not None
    assert new_plan.first_week.week == 2
    assert new_plan.roundtable is not None
    assert new_plan.roundtable.synthesis is not None
    # Kế hoạch gốc không bị sửa tại chỗ
    assert plan.first_week is not None
    assert plan.first_week.week == 1


def test_adjust_persists_event_and_message(fake_llm, profile, tmp_path):
    store = Store(f"sqlite:///{tmp_path / 'events.db'}")
    plan = create_plan(profile, llm=fake_llm)
    _, event = adjust_plan(
        plan, profile, "Bận đột xuất ở công ty", llm=fake_llm, store=store
    )
    assert event.message


def test_vector_memory_records_plan(fake_llm, profile, tmp_path):
    memory = VectorMemory(str(tmp_path / "chroma"))
    create_plan(profile, llm=fake_llm, memory=memory)

    assert memory.count() == 1
    hits = memory.search("Data Analyst", k=1)
    assert hits
    assert hits[0]["metadata"]["kind"] == "plan"


def test_tutor_quiz_and_explain(fake_llm):
    from lifeos.agents import tutor

    quiz = tutor.quiz(fake_llm, "SQL JOIN", "tone")
    assert quiz.question
    assert len(quiz.options) >= 2
    assert 0 <= quiz.answer_index < len(quiz.options)
    assert tutor.explain(fake_llm, "SQL JOIN", "tone")


def test_plan_contains_multi_week_program(fake_llm, profile):
    plan = create_plan(profile, llm=fake_llm)

    assert plan.weeks, "kế hoạch phải có lịch nhiều tuần"
    assert [w.week for w in plan.weeks] == list(range(1, len(plan.weeks) + 1))
    assert plan.first_week is not None
    assert plan.weeks[0].week == plan.first_week.week
    assert all(w.total_hours <= profile.hours_per_week for w in plan.weeks)
    assert all(t.id for w in plan.weeks for t in w.tasks)


def test_reduced_load_propagates_to_whole_program(fake_llm, profile):
    """Hội đồng kết luận quá tải thì giảm tải phải áp cho mọi tuần, không chỉ tuần 1."""
    fake_llm.overload_times = 1
    plan = create_plan(profile, llm=fake_llm)

    reduced_budget = int(profile.hours_per_week * REDUCED_LOAD_FACTOR)
    assert len(plan.weeks) > 1
    for week in plan.weeks[1:]:
        assert week.total_hours <= reduced_budget, (
            f"tuần {week.week} vẫn {week.total_hours}h, vượt mức giảm tải "
            f"{reduced_budget}h"
        )


def test_program_weeks_limit_is_respected(fake_llm, profile):
    plan = create_plan(profile, llm=fake_llm, program_weeks=3)
    assert len(plan.weeks) == 3


# --- học từ quá khứ (reflection) ---


def _past_plan_with_misses(count: int, misses: int) -> LifeOSPlan:
    from lifeos.models import (
        ScheduleTask,
        TaskStatus,
        TaskType,
        WeeklySchedule,
    )

    tasks = [
        ScheduleTask(
            id=f"p{i}",
            title=f"việc {i}",
            task_type=TaskType.STUDY,
            day="Mon",
            start="20:00",
            duration_min=60,
            status=TaskStatus.MISSED if i < misses else TaskStatus.DONE,
        )
        for i in range(count)
    ]
    week = WeeklySchedule(week=1, tasks=tasks, total_hours=count)
    return LifeOSPlan(weeks=[week], first_week=week)


def test_plan_records_reflection_when_past_plans_given(fake_llm, profile):
    plan = create_plan(
        profile, llm=fake_llm, past_plans=[_past_plan_with_misses(4, 0)]
    )
    assert plan.reflection is not None
    assert plan.reflection.stats.plans == 1


def test_no_reflection_when_no_history(fake_llm, profile):
    plan = create_plan(profile, llm=fake_llm)
    assert plan.reflection is None


def test_poor_history_reduces_planned_load(fake_llm_cls, profile):
    """Trượt nhiều ở quá khứ thì kế hoạch mới phải nhẹ hơn.

    Dùng hai LLM độc lập: bộ đếm "quá tải" của FakeLLM bị tiêu thụ sau lần gọi
    đầu, nên dùng chung một instance sẽ so sánh nhầm nguyên nhân.
    """
    baseline = create_plan(profile, llm=fake_llm_cls())
    adapted = create_plan(
        profile,
        llm=fake_llm_cls(),
        past_plans=[_past_plan_with_misses(4, 4)],
    )

    baseline_peak = max(w.total_hours for w in baseline.weeks)
    adapted_peak = max(w.total_hours for w in adapted.weeks)
    assert adapted_peak < baseline_peak
    assert adapted.reflection.stats.suggested_load_factor < 1.0


def test_good_history_keeps_full_load(fake_llm_cls, profile):
    baseline = create_plan(profile, llm=fake_llm_cls())
    adapted = create_plan(
        profile,
        llm=fake_llm_cls(),
        past_plans=[_past_plan_with_misses(4, 0)],
    )
    assert max(w.total_hours for w in adapted.weeks) == max(
        w.total_hours for w in baseline.weeks
    )
    assert adapted.reflection.stats.suggested_load_factor == 1.0


def test_reduce_load_multiplies_instead_of_overwriting(fake_llm, profile):
    """Giảm tải phải NHÂN vào mức hiện tại, không gán đè thành 0.8.

    Lịch sử toàn trượt -> mức tải ban đầu 0.75. Hội đồng kết luận quá tải nên
    giảm tiếp: đúng phải là 0.75 x 0.8 = 0.6 (trần 6h với 10h/tuần). Nếu code
    gán đè thành 0.8 thì trần sẽ là 8h — tức là vô tình làm kế hoạch NẶNG hơn
    mức mà lịch sử đã chỉ ra là quá sức.
    """
    plan = create_plan(
        profile, llm=fake_llm, past_plans=[_past_plan_with_misses(4, 4)]
    )
    reduced_ceiling = int(profile.hours_per_week * 0.75 * 0.8)
    overwrite_ceiling = int(profile.hours_per_week * 0.8)

    peak = max(w.total_hours for w in plan.weeks)
    assert peak <= reduced_ceiling, (
        f"trần {peak}h vượt mức nhân đúng ({reduced_ceiling}h) — "
        f"có thể load_factor đang bị gán đè thành {overwrite_ceiling}h"
    )
    assert reduced_ceiling < overwrite_ceiling
