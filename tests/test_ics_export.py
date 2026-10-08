"""Test xuất lịch ra ICS."""

from __future__ import annotations

from datetime import date, datetime

from icalendar import Calendar

from lifeos.models import (
    ScheduleTask,
    TaskStatus,
    TaskType,
    WeeklySchedule,
)
from lifeos.tools import calendar


def _task(
    task_id: str,
    day: str = "Mon",
    start: str = "20:00",
    duration: int = 90,
    status: TaskStatus = TaskStatus.PLANNED,
    title: str = "Học SQL",
) -> ScheduleTask:
    return ScheduleTask(
        id=task_id,
        title=title,
        task_type=TaskType.STUDY,
        day=day,
        start=start,
        duration_min=duration,
        module_ref="SQL",
        status=status,
    )


def _week(number: int, *tasks: ScheduleTask) -> WeeklySchedule:
    return WeeklySchedule(week=number, tasks=list(tasks), total_hours=2)


# --- week_monday ---


def test_week_monday_week_one_is_monday_of_start_date():
    # 2026-03-11 là thứ Tư -> thứ Hai của tuần đó là 2026-03-09
    monday = calendar.week_monday(1, date(2026, 3, 11))
    assert monday == date(2026, 3, 9)
    assert monday.weekday() == 0


def test_week_monday_advances_by_seven_days():
    start = date(2026, 3, 9)
    assert calendar.week_monday(2, start) == date(2026, 3, 16)
    assert calendar.week_monday(4, start) == date(2026, 3, 30)


def test_week_monday_handles_week_zero_and_negative():
    start = date(2026, 3, 9)
    assert calendar.week_monday(0, start) == start
    assert calendar.week_monday(-3, start) == start


# --- task_datetimes ---


def test_task_datetimes_places_task_on_correct_weekday():
    start, end = calendar.task_datetimes(
        _task("t1", day="Wed"), week=2, start_date=date(2026, 3, 9)
    )
    assert start.date() == date(2026, 3, 18)  # thứ Tư tuần 2
    assert start.hour == 20 and start.minute == 0
    assert end == datetime(2026, 3, 18, 21, 30)


def test_task_datetimes_every_weekday_lands_on_that_day():
    base = date(2026, 3, 9)
    for offset, day in enumerate(calendar.WEEKDAY_NAMES):
        start, _ = calendar.task_datetimes(
            _task(f"t{offset}", day=day), week=1, start_date=base
        )
        assert start.weekday() == offset


def test_task_datetimes_unknown_day_falls_back_to_monday():
    start, _ = calendar.task_datetimes(
        _task("t1", day="Nope"), week=1, start_date=date(2026, 3, 9)
    )
    assert start.weekday() == 0


def test_task_datetimes_invalid_start_falls_back_to_evening():
    start, _ = calendar.task_datetimes(
        _task("t1", start="khong-hop-le"), week=1, start_date=date(2026, 3, 9)
    )
    assert start.hour == 20


def test_task_datetimes_enforces_minimum_duration():
    start, end = calendar.task_datetimes(
        _task("t1", duration=1), week=1, start_date=date(2026, 3, 9)
    )
    assert (end - start).total_seconds() == 15 * 60


# --- tasks_to_ics ---


def test_tasks_to_ics_is_parseable_and_has_events():
    ics = calendar.tasks_to_ics(
        [_week(1, _task("w1-t1"), _task("w1-t2", day="Thu"))],
        start_date=date(2026, 3, 9),
    )
    cal = Calendar.from_ical(ics)
    events = list(cal.walk("VEVENT"))
    assert len(events) == 2


def test_tasks_to_ics_summary_and_uid():
    ics = calendar.tasks_to_ics(
        [_week(1, _task("w1-t1", title="Học JOIN"))], start_date=date(2026, 3, 9)
    )
    event = next(iter(Calendar.from_ical(ics).walk("VEVENT")))
    assert str(event["SUMMARY"]) == "Học JOIN"
    assert "w1-t1@lifeos" in str(event["UID"])


def test_tasks_to_ics_marks_missed_as_cancelled():
    ics = calendar.tasks_to_ics(
        [
            _week(
                1,
                _task("a", status=TaskStatus.MISSED),
                _task("b", status=TaskStatus.DONE),
            )
        ],
        start_date=date(2026, 3, 9),
    )
    statuses = {
        str(e["UID"]).split("@")[0]: str(e["STATUS"])
        for e in Calendar.from_ical(ics).walk("VEVENT")
    }
    assert statuses["a"] == "CANCELLED"
    assert statuses["b"] == "CONFIRMED"


def test_tasks_to_ics_description_includes_week_and_module():
    ics = calendar.tasks_to_ics(
        [_week(3, _task("w3-t1"))], start_date=date(2026, 3, 9)
    )
    event = next(iter(Calendar.from_ical(ics).walk("VEVENT")))
    description = str(event["DESCRIPTION"])
    assert "Tuần 3" in description
    assert "SQL" in description


def test_tasks_to_ics_handles_missing_id_with_generated_uid():
    ics = calendar.tasks_to_ics(
        [_week(1, _task(""))], start_date=date(2026, 3, 9)
    )
    event = next(iter(Calendar.from_ical(ics).walk("VEVENT")))
    assert str(event["UID"]).endswith("@lifeos")


def test_tasks_to_ics_empty_weeks_has_no_events():
    ics = calendar.tasks_to_ics([], start_date=date(2026, 3, 9))
    assert list(Calendar.from_ical(ics).walk("VEVENT")) == []


def test_tasks_to_ics_spans_multiple_weeks():
    ics = calendar.tasks_to_ics(
        [_week(1, _task("a")), _week(2, _task("b"))],
        start_date=date(2026, 3, 9),
    )
    starts = sorted(
        e["DTSTART"].dt for e in Calendar.from_ical(ics).walk("VEVENT")
    )
    assert starts[0].date() == date(2026, 3, 9)
    assert starts[1].date() == date(2026, 3, 16)


# --- write_ics ---


def test_write_ics_creates_file(tmp_path):
    target = tmp_path / "lich.ics"
    result = calendar.write_ics(
        [_week(1, _task("a"))], target, start_date=date(2026, 3, 9)
    )
    assert result == target
    assert target.exists()
    assert len(list(Calendar.from_ical(target.read_bytes()).walk("VEVENT"))) == 1


def test_write_ics_creates_parent_directory(tmp_path):
    target = tmp_path / "sau" / "con" / "lich.ics"
    calendar.write_ics([_week(1, _task("a"))], target)
    assert target.exists()


def test_write_ics_roundtrips_via_parse_ics(tmp_path):
    """File xuất ra phải đọc lại được bằng chính bộ đọc ICS của dự án."""
    target = calendar.write_ics(
        [_week(1, _task("a", day="Tue", start="19:00", duration=60))],
        tmp_path / "lich.ics",
        start_date=date(2026, 3, 9),
    )
    slots = calendar.parse_ics(str(target))
    assert slots
    assert slots[0].start.hour == 19
