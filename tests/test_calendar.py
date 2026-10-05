"""Test công cụ lịch: parse ICS, khoảng bận, dịch giờ."""

from __future__ import annotations

from datetime import datetime

from lifeos.tools.calendar import (
    BusySlot,
    busy_windows_by_weekday,
    find_conflicts,
    parse_ics,
    shift_off_busy,
    suggest_next_slot,
    to_hhmm,
    to_minutes,
)

ICS_SAMPLE = """BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//LifeOS//Test//EN
BEGIN:VEVENT
DTSTART:20260105T090000
DTEND:20260105T110000
SUMMARY:Hop nhom
END:VEVENT
END:VCALENDAR
"""


def test_parse_ics_reads_events(tmp_path):
    path = tmp_path / "cal.ics"
    path.write_text(ICS_SAMPLE, encoding="utf-8")
    slots = parse_ics(str(path))
    assert len(slots) == 1
    assert slots[0].duration_min == 120


def test_busy_windows_by_weekday_maps_to_weekday_name():
    slots = [BusySlot(datetime(2026, 1, 5, 9, 0), datetime(2026, 1, 5, 11, 0))]
    windows = busy_windows_by_weekday(slots)
    # 2026-01-05 là thứ Hai
    assert windows["Mon"] == [(540, 660)]


def test_minute_conversions():
    assert to_minutes("20:30") == 1230
    assert to_hhmm(1230) == "20:30"
    assert to_minutes("khong-phai-gio") == -1


def test_shift_off_busy_moves_past_window():
    busy = {"Mon": [(1200, 1260)]}
    assert shift_off_busy("Mon", 1200, 60, busy) == 1260
    # Ngày không có khoảng bận thì giữ nguyên
    assert shift_off_busy("Tue", 1200, 60, busy) == 1200


def test_find_conflicts_and_suggest_next_slot():
    busy = [BusySlot(datetime(2026, 1, 5, 20, 0), datetime(2026, 1, 5, 21, 0))]
    candidate = BusySlot(datetime(2026, 1, 5, 20, 30), datetime(2026, 1, 5, 21, 30))
    assert find_conflicts(candidate, busy)
    moved = suggest_next_slot(candidate, busy)
    assert not find_conflicts(moved, busy)