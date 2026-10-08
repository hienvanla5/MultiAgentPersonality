"""Công cụ lịch: đọc/ghi ICS, xử lý xung đột theo khung giờ trong tuần."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path
from uuid import uuid4

from icalendar import Calendar, Event

from ..models import TaskStatus, WeeklySchedule

WEEKDAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


@dataclass
class BusySlot:
    start: datetime
    end: datetime

    @property
    def duration_min(self) -> int:
        return int((self.end - self.start).total_seconds() // 60)


def parse_ics(path: str) -> list[BusySlot]:
    """Đọc file ICS và trả về các khoảng thời gian bận (VEVENT)."""
    with open(path, "rb") as f:
        cal = Calendar.from_ical(f.read())

    slots: list[BusySlot] = []
    for component in cal.walk("VEVENT"):
        start = component.get("DTSTART")
        end = component.get("DTEND")
        if start is None or end is None:
            continue
        slots.append(BusySlot(start=start.dt, end=end.dt))
    return slots


def is_overlap(a: BusySlot, b: BusySlot) -> bool:
    return a.start < b.end and b.start < a.end


def find_conflicts(candidate: BusySlot, busy_slots: list[BusySlot]) -> list[BusySlot]:
    return [s for s in busy_slots if is_overlap(candidate, s)]


def suggest_next_slot(
    candidate: BusySlot, busy_slots: list[BusySlot], step_min: int = 30
) -> BusySlot:
    """Dịch candidate tới lui để tránh xung đột (naive, chỉ dịch tới)."""
    duration = candidate.duration_min
    start = candidate.start
    while any(
        is_overlap(BusySlot(start, start + timedelta(minutes=duration)), s)
        for s in busy_slots
    ):
        start = start + timedelta(minutes=step_min)
    return BusySlot(start=start, end=start + timedelta(minutes=duration))


# --- Tiện ích theo phút trong ngày (dùng cho scheduler) ---


def to_minutes(hhmm: str) -> int:
    """'20:30' -> 1230. Trả về -1 nếu không parse được."""
    try:
        hh, mm = hhmm.strip().split(":")
        return int(hh) * 60 + int(mm)
    except (ValueError, AttributeError):
        return -1


def to_hhmm(minutes: int) -> str:
    minutes = max(0, min(minutes, 24 * 60 - 1))
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def busy_windows_by_weekday(slots: list[BusySlot]) -> dict[str, list[tuple[int, int]]]:
    """Gom các khoảng bận thành {tên thứ: [(start_min, end_min), ...]}."""
    out: dict[str, list[tuple[int, int]]] = {}
    for s in slots:
        day = WEEKDAY_NAMES[s.start.weekday()]
        start_min = s.start.hour * 60 + s.start.minute
        end_min = s.end.hour * 60 + s.end.minute
        out.setdefault(day, []).append((start_min, end_min))
    return out


def shift_off_busy(
    day: str,
    start_min: int,
    duration_min: int,
    busy: dict[str, list[tuple[int, int]]] | None,
    step_min: int = 30,
) -> int:
    """Tìm giờ bắt đầu sớm nhất (>= start_min) không chồng khoảng bận nào.

    Dịch dần theo step_min cho tới khi hết chồng lấn. Có chốt an toàn để
    không lặp vô hạn nếu dữ liệu bận không hợp lệ.
    """
    windows = (busy or {}).get(day, [])
    if not windows:
        return start_min

    guard = 0
    while any(
        start_min < b_end and b_start < start_min + duration_min
        for b_start, b_end in windows
    ):
        start_min += step_min
        guard += 1
        if guard > 96:  # 96 * 30 phút = 48 giờ, thoát an toàn
            break
    return start_min


# --- Xuất lịch ra định dạng ICS ---


def week_monday(week: int, start_date: date | None = None) -> date:
    """Ngày thứ Hai của tuần thứ `week` (tuần 1 bắt đầu từ `start_date`)."""
    base = start_date or date.today()
    base_monday = base - timedelta(days=base.weekday())
    return base_monday + timedelta(weeks=max(0, week - 1))


def task_datetimes(
    task, week: int, start_date: date | None = None
) -> tuple[datetime, datetime]:
    """Thời điểm bắt đầu/kết thúc thực tế của một buổi học."""
    day_index = WEEKDAY_NAMES.index(task.day) if task.day in WEEKDAY_NAMES else 0
    day = week_monday(week, start_date) + timedelta(days=day_index)

    start_min = to_minutes(task.start)
    if start_min < 0:
        start_min = 20 * 60

    start = datetime.combine(day, time(hour=start_min // 60, minute=start_min % 60))
    return start, start + timedelta(minutes=max(15, task.duration_min))


def tasks_to_ics(
    weeks: list[WeeklySchedule],
    *,
    start_date: date | None = None,
    calendar_name: str = "Life OS",
) -> str:
    """Chuyển lịch nhiều tuần thành chuỗi ICS để import vào Google Calendar.

    Buổi đã hoàn thành được đánh dấu `STATUS:CONFIRMED`, buổi bị trượt là
    `STATUS:CANCELLED` để nhìn rõ trên lịch.
    """
    cal = Calendar()
    cal.add("prodid", "-//Life OS//Multi-Agent Personality//VI")
    cal.add("version", "2.0")
    cal.add("x-wr-calname", calendar_name)

    for week in weeks:
        for task in week.tasks:
            start, end = task_datetimes(task, week.week, start_date)
            event = Event()
            event.add("summary", task.title)
            event.add("dtstart", start)
            event.add("dtend", end)
            event.add("dtstamp", datetime.now())
            event.add("uid", f"{task.id or uuid4().hex}@lifeos")
            event.add(
                "status",
                "CANCELLED" if task.status == TaskStatus.MISSED else "CONFIRMED",
            )
            description = [f"Tuần {week.week}", f"Loại: {task.task_type.value}"]
            if task.module_ref:
                description.append(f"Module: {task.module_ref}")
            if task.notes:
                description.append(task.notes)
            event.add("description", "\n".join(description))
            cal.add_component(event)

    return cal.to_ical().decode("utf-8")


def write_ics(
    weeks: list[WeeklySchedule],
    path: str | Path,
    *,
    start_date: date | None = None,
    calendar_name: str = "Life OS",
) -> Path:
    """Ghi lịch ra file .ics và trả về đường dẫn.

    Ghi ở chế độ nhị phân vì `to_ical()` đã trả về đúng chuẩn CRLF của RFC 5545;
    ghi dạng text trên Windows sẽ đổi `\\n` thành `\\r\\n` và làm hỏng file.
    """
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    content = tasks_to_ics(
        weeks, start_date=start_date, calendar_name=calendar_name
    )
    target.write_bytes(content.encode("utf-8"))
    return target
