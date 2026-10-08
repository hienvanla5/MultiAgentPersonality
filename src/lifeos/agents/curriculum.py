"""Giáo Viên — biến khoảng trống kỹ năng thành lộ trình học."""

from __future__ import annotations

from ..llm import LLM
from ..models import Goal, SkillGap, StudyPlan, UserProfile
from .base import structured


def build_study_plan(
    llm: LLM,
    goal: Goal,
    gaps: list[SkillGap],
    profile: UserProfile,
    tone: str,
) -> StudyPlan:
    """Sinh lộ trình học tuần tự, đảm bảo không vượt quỹ thời gian."""
    gap_lines = "\n".join(
        f"- {g.skill} (ưu tiên {g.priority}): {g.rationale}" for g in gaps
    ) or "- (không có khoảng trống rõ ràng)"
    total_hours = profile.hours_per_week * goal.deadline_months * 4
    prompt = f"""Thiết kế lộ trình học cho mục tiêu sau.

Mục tiêu: {goal.description}
Thời hạn: {goal.deadline_months} tháng
Quỹ thời gian: {profile.hours_per_week} giờ/tuần (~{total_hours} giờ cho cả lộ trình)
Khoảng trống cần lấp:
{gap_lines}

Hãy tạo lộ trình gồm các module học tuần tự. Mỗi module gồm:
title, duration_hours (số giờ cần), order (thứ tự, bắt đầu từ 0),
depends_on (danh sách order của các module phải học trước),
skills_covered (các kỹ năng module này giải quyết).
Tổng duration_hours không được vượt quá {total_hours} giờ.
Đặt total_weeks và overview (mô tả ngắn định hướng lộ trình).
Sắp module theo thứ tự học hợp lý: nền tảng trước, chuyên sâu sau."""

    plan = structured(llm, "tutor", tone, prompt, StudyPlan)
    modules = list(getattr(plan, "modules", []) or [])
    modules.sort(key=lambda m: m.order)
    for i, m in enumerate(modules):
        m.order = i
    plan.modules = modules
    if not plan.total_weeks:
        plan.total_weeks = max(1, goal.deadline_months * 4)
    return plan
