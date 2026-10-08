"""Test lịch nhiều tuần: phân bổ module và sinh lịch không gọi LLM."""

from __future__ import annotations

from itertools import pairwise

from lifeos.agents import scheduler
from lifeos.models import ModuleSlice, StudyModule, StudyPlan, WeekAllocation
from lifeos.tools.calendar import to_minutes


def _plan(*modules: tuple[str, int]) -> StudyPlan:
    return StudyPlan(
        modules=[
            StudyModule(title=title, duration_hours=hours, order=index)
            for index, (title, hours) in enumerate(modules)
        ],
        total_weeks=24,
    )


# --- allocate_modules ---


def test_allocation_splits_long_module_across_weeks():
    allocs = scheduler.allocate_modules(_plan(("SQL", 25)), hours_per_week=10, weeks=3)
    assert [a.total_hours for a in allocs] == [10, 10, 5]
    assert all(a.items[0].module_title == "SQL" for a in allocs)


def test_allocation_fills_week_then_moves_on():
    allocs = scheduler.allocate_modules(
        _plan(("SQL", 6), ("Python", 6)), hours_per_week=10, weeks=2
    )
    # Tuần 1: hết SQL (6h) rồi lấp thêm 4h Python
    assert allocs[0].module_titles == ["SQL", "Python"]
    assert allocs[0].items[0] == ModuleSlice(
        module_title="SQL", hours=6, order=0
    )
    assert allocs[0].total_hours == 10
    # Tuần 2: phần Python còn lại
    assert allocs[1].module_titles == ["Python"]
    assert allocs[1].total_hours == 2


def test_allocation_does_not_start_module_early():
    allocs = scheduler.allocate_modules(
        _plan(("SQL", 10), ("Python", 10)), hours_per_week=10, weeks=2
    )
    assert allocs[0].module_titles == ["SQL"]
    assert allocs[1].module_titles == ["Python"]


def test_allocation_never_exceeds_capacity():
    allocs = scheduler.allocate_modules(
        _plan(("SQL", 40), ("Python", 40)), hours_per_week=8, weeks=12
    )
    assert all(a.total_hours <= 8 for a in allocs)


def test_allocation_preserves_total_hours():
    allocs = scheduler.allocate_modules(
        _plan(("SQL", 20), ("Python", 25)), hours_per_week=10, weeks=10
    )
    assert sum(a.total_hours for a in allocs) == 45


def test_allocation_empty_plan_gives_empty_weeks():
    allocs = scheduler.allocate_modules(StudyPlan(), hours_per_week=10, weeks=3)
    assert len(allocs) == 3
    assert all(a.total_hours == 0 and a.items == [] for a in allocs)


def test_allocation_caps_at_requested_weeks():
    allocs = scheduler.allocate_modules(_plan(("SQL", 100)), hours_per_week=10, weeks=2)
    assert len(allocs) == 2


# --- week_from_allocation ---


def _allocation(week: int, *items: tuple[str, int]) -> WeekAllocation:
    slices = [ModuleSlice(module_title=t, hours=h) for t, h in items]
    return WeekAllocation(week=week, items=slices, total_hours=sum(h for _, h in items))


def test_week_from_allocation_assigns_ids_and_budget(profile):
    week = scheduler.week_from_allocation(_allocation(3, ("SQL", 6)), profile)
    assert week.week == 3
    assert week.total_hours <= profile.hours_per_week
    assert all(t.id.startswith("w3-") for t in week.tasks)


def test_week_from_allocation_uses_energy_window_start(profile):
    week = scheduler.week_from_allocation(_allocation(1, ("SQL", 3)), profile)
    assert all(t.start == "20:00" for t in week.tasks)


def test_week_from_allocation_has_no_self_overlap(profile):
    # 14 giờ -> hơn 7 buổi nên phải có ngày chứa nhiều buổi
    week = scheduler.week_from_allocation(_allocation(1, ("SQL", 14)), profile)
    by_day: dict[str, list[tuple[int, int]]] = {}
    for task in week.tasks:
        start = to_minutes(task.start)
        by_day.setdefault(task.day, []).append((start, start + task.duration_min))

    for day, spans in by_day.items():
        spans.sort()
        for (_, end), (next_start, _) in pairwise(spans):
            assert end <= next_start, f"chồng giờ trong ngày {day}"


def test_week_from_allocation_summary_lists_modules(profile):
    week = scheduler.week_from_allocation(_allocation(2, ("SQL", 3), ("Python", 3)), profile)
    assert "SQL" in week.summary and "Python" in week.summary
    assert "Tuần 2" in week.summary


def test_week_from_allocation_avoids_busy_window(profile):
    busy = {"Mon": [(1200, 1260)]}  # 20:00-21:00
    week = scheduler.week_from_allocation(_allocation(1, ("SQL", 3)), profile, busy)
    monday = [t for t in week.tasks if t.day == "Mon"]
    assert monday
    assert to_minutes(monday[0].start) >= 1260


# --- build_program ---


def test_build_program_returns_sequential_weeks(fake_llm, profile):
    program = scheduler.build_program(
        fake_llm, _plan(("SQL", 20)), profile, "tone", weeks=4
    )
    assert [w.week for w in program] == [1, 2, 3, 4]


def test_build_program_uses_llm_only_for_detailed_weeks(fake_llm, profile):
    scheduler.build_program(
        fake_llm, _plan(("SQL", 40)), profile, "tone", weeks=6, detailed_weeks=1
    )
    assert fake_llm.count("WeeklySchedule") == 1


def test_build_program_all_detailed_when_requested(fake_llm, profile):
    scheduler.build_program(
        fake_llm, _plan(("SQL", 40)), profile, "tone", weeks=3, detailed_weeks=3
    )
    assert fake_llm.count("WeeklySchedule") == 3


def test_build_program_every_week_within_budget(fake_llm, profile):
    program = scheduler.build_program(
        fake_llm, _plan(("SQL", 40), ("Python", 30)), profile, "tone", weeks=8
    )
    assert all(w.total_hours <= profile.hours_per_week for w in program)


# --- load_factor lan ra toàn chương trình ---


def test_allocation_applies_load_factor():
    full = scheduler.allocate_modules(_plan(("SQL", 80)), 10, 4, 1.0)
    reduced = scheduler.allocate_modules(_plan(("SQL", 80)), 10, 4, 0.8)
    assert [a.total_hours for a in full] == [10, 10, 10, 10]
    assert [a.total_hours for a in reduced] == [8, 8, 8, 8]


def test_allocation_load_factor_never_drops_below_one_hour():
    allocs = scheduler.allocate_modules(_plan(("SQL", 80)), 1, 3, 0.5)
    assert all(a.total_hours >= 1 for a in allocs)


def test_week_from_allocation_respects_load_factor(profile):
    week = scheduler.week_from_allocation(
        _allocation(2, ("SQL", 10)), profile, load_factor=0.8
    )
    assert week.total_hours <= 8


def test_build_program_applies_load_factor_to_all_weeks(fake_llm, profile):
    program = scheduler.build_program(
        fake_llm, _plan(("SQL", 80)), profile, "tone", weeks=5, load_factor=0.8
    )
    assert all(w.total_hours <= 8 for w in program)
