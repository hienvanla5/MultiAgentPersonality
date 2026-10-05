"""Công cụ lịch: đọc ICS và xử lý xung đột theo khung giờ trong tuần."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from icalendar import Calendar

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
