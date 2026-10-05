"""Test tích hợp đồ thị LangGraph: lập kế hoạch, vòng giảm tải, điều chỉnh."""

from __future__ import annotations

from lifeos.graph import adjust_plan, create_plan
from lifeos.memory import Store, VectorMemory


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