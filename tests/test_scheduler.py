"""Test Huấn Luyện Viên Kỷ Luật: ngân sách giờ, tránh khoảng bận, chuẩn hoá."""

from __future__ import annotations

from lifeos.agents import scheduler
from lifeos.models import StudyModule, StudyPlan


def _plan() -> StudyPlan:
    return StudyPlan(modules=[StudyModule(title="SQL nền tảng", duration_hours=10)])


def test_week_trimmed_to_hour_budget(fake_llm, profile):
    profile.hours_per_week = 2
    week = scheduler.build_week(fake_llm, _plan(), profile, "tone")
    # FakeLLM trả 120 + 90 phút; ngân sách 2 giờ = 120 phút
    assert len(week.tasks) == 1
    assert week.total_hours == 2


def test_week_ids_and_chronological_order(fake_llm, profile):
    week = scheduler.build_week(fake_llm, _plan(), profile, "tone")
    assert [t.id for t in week.tasks] == ["w1-t1", "w1-t2"]
    assert [t.day for t in week.tasks] == ["Mon", "Sat"]


def test_week_avoids_busy_window(fake_llm, profile):
    busy = {"Mon": [(1200, 1260)]}  # 20:00-21:00
    week = scheduler.build_week(fake_llm, _plan(), profile, "tone", busy=busy)
    monday = next(t for t in week.tasks if t.day == "Mon")
    assert monday.start == "21:00"


def test_load_factor_reduces_budget(fake_llm, profile):
    profile.hours_per_week = 4
    week = scheduler.build_week(fake_llm, _plan(), profile, "tone", load_factor=0.5)
    # Ngân sách 4 * 0.5 * 60 = 120 phút -> chỉ giữ buổi 120 phút
    assert week.total_hours == 2


def test_summary_is_filled(fake_llm, profile):
    week = scheduler.build_week(fake_llm, _plan(), profile, "tone")
    assert "Tuần 1" in week.summary