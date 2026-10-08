"""Test theo dõi tiến độ (logic thuần, không gọi LLM)."""

from __future__ import annotations

from lifeos import progress
from lifeos.models import (
    LifeOSPlan,
    ScheduleTask,
    TaskStatus,
    TaskType,
    WeeklySchedule,
)


def _task(
    task_id: str,
    status: TaskStatus = TaskStatus.PLANNED,
    duration: int = 60,
    title: str = "Học SQL",
) -> ScheduleTask:
    return ScheduleTask(
        id=task_id,
        title=title,
        task_type=TaskType.STUDY,
        day="Mon",
        start="20:00",
        duration_min=duration,
        status=status,
    )


def _week(number: int, *tasks: ScheduleTask) -> WeeklySchedule:
    return WeeklySchedule(
        week=number,
        tasks=list(tasks),
        total_hours=round(sum(t.duration_min for t in tasks) / 60),
    )


def _plan(*weeks: WeeklySchedule) -> LifeOSPlan:
    return LifeOSPlan(
        weeks=list(weeks), first_week=weeks[0] if weeks else None
    )


# --- all_weeks / find_task ---


def test_all_weeks_prefers_weeks_list():
    plan = _plan(_week(1, _task("a")), _week(2, _task("b")))
    assert [w.week for w in progress.all_weeks(plan)] == [1, 2]


def test_all_weeks_falls_back_to_first_week():
    plan = LifeOSPlan(first_week=_week(1, _task("a")))
    assert [w.week for w in progress.all_weeks(plan)] == [1]


def test_all_weeks_empty_plan():
    assert progress.all_weeks(LifeOSPlan()) == []


def test_find_task_across_weeks():
    plan = _plan(_week(1, _task("a")), _week(2, _task("b")))
    assert progress.find_task(plan, "b") is not None
    assert progress.find_task(plan, "b").id == "b"
    assert progress.find_task(plan, "zzz") is None


# --- mark ---


def test_mark_task_updates_status():
    plan = _plan(_week(1, _task("a")))
    assert progress.mark_task(plan, "a", TaskStatus.DONE) is True
    assert progress.find_task(plan, "a").status == TaskStatus.DONE


def test_mark_task_unknown_id_returns_false():
    plan = _plan(_week(1, _task("a")))
    assert progress.mark_task(plan, "khong-ton-tai", TaskStatus.DONE) is False


def test_mark_week_marks_all_tasks_in_that_week_only():
    plan = _plan(
        _week(1, _task("a"), _task("b")),
        _week(2, _task("c")),
    )
    assert progress.mark_week(plan, 1, TaskStatus.DONE) == 2
    assert progress.find_task(plan, "a").status == TaskStatus.DONE
    assert progress.find_task(plan, "b").status == TaskStatus.DONE
    assert progress.find_task(plan, "c").status == TaskStatus.PLANNED


def test_missed_task_titles():
    plan = _plan(
        _week(1, _task("a", TaskStatus.MISSED, title="SQL"), _task("b", TaskStatus.DONE)),
        _week(2, _task("c", TaskStatus.MISSED, title="Python")),
    )
    assert progress.missed_task_titles(plan) == ["SQL", "Python"]


# --- week_progress ---


def test_week_progress_counts():
    week = _week(
        1,
        _task("a", TaskStatus.DONE, duration=60),
        _task("b", TaskStatus.DONE, duration=90),
        _task("c", TaskStatus.MISSED),
        _task("d"),
    )
    wp = progress.week_progress(week)
    assert (wp.total, wp.done, wp.missed, wp.planned) == (4, 2, 1, 1)
    assert wp.pct == 50
    assert wp.hours_done == 2  # 150 phút -> làm tròn 2


def test_week_progress_empty_week_pct_zero():
    assert progress.week_progress(_week(1)).pct == 0


# --- program_progress ---


def test_program_progress_all_planned():
    plan = _plan(_week(1, _task("a")), _week(2, _task("b")))
    pp = progress.program_progress(plan)
    assert pp.overall_pct == 0
    assert pp.current_week == 1
    assert pp.on_track is True
    assert pp.streak == 0


def test_program_progress_full_completion():
    plan = _plan(
        _week(1, _task("a", TaskStatus.DONE)),
        _week(2, _task("b", TaskStatus.DONE)),
    )
    pp = progress.program_progress(plan)
    assert pp.overall_pct == 100
    assert pp.streak == 2
    assert pp.on_track is True
    assert pp.current_week == 2  # xong hết -> tuần cuối


def test_program_progress_current_week_is_first_incomplete():
    plan = _plan(
        _week(1, _task("a", TaskStatus.DONE)),
        _week(2, _task("b")),
        _week(3, _task("c")),
    )
    assert progress.program_progress(plan).current_week == 2


def test_program_progress_streak_stops_at_first_gap():
    plan = _plan(
        _week(1, _task("a", TaskStatus.DONE)),
        _week(2, _task("b", TaskStatus.MISSED)),
        _week(3, _task("c", TaskStatus.DONE)),
    )
    assert progress.program_progress(plan).streak == 1


def test_program_progress_off_track_when_missed_up_to_current():
    plan = _plan(
        _week(1, _task("a", TaskStatus.MISSED)),
        _week(2, _task("b")),
    )
    pp = progress.program_progress(plan)
    assert pp.on_track is False
    assert pp.missed == 1
    assert "Chệch tiến độ" in pp.note


def test_program_progress_ignores_missed_beyond_current_week():
    # Tuần 1 chưa xong -> tuần hiện tại là 1; trượt ở tuần 5 chưa tính là chệch
    plan = _plan(
        _week(1, _task("a")),
        _week(2, _task("b")),
        _week(5, _task("e", TaskStatus.MISSED)),
    )
    pp = progress.program_progress(plan)
    assert pp.current_week == 1
    assert pp.on_track is True
    assert pp.missed == 0


def test_program_progress_hours():
    plan = _plan(
        _week(1, _task("a", TaskStatus.DONE, duration=120)),
        _week(2, _task("b", duration=60)),
    )
    pp = progress.program_progress(plan)
    assert pp.hours_done == 2
    assert pp.hours_planned == 3


def test_program_progress_empty_plan():
    pp = progress.program_progress(LifeOSPlan())
    assert pp.overall_pct == 0
    assert pp.on_track is True
    assert pp.note


# --- next_tasks ---


def test_next_tasks_returns_pending_in_order():
    plan = _plan(
        _week(1, _task("a", TaskStatus.DONE), _task("b", title="Kế tiếp")),
        _week(2, _task("c", title="Sau đó")),
    )
    titles = [t.title for t in progress.next_tasks(plan, limit=2)]
    assert titles == ["Kế tiếp", "Sau đó"]


def test_next_tasks_limit_zero():
    plan = _plan(_week(1, _task("a")))
    assert progress.next_tasks(plan, limit=0) == []
