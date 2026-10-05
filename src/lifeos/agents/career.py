"""Chiến Lược Gia — phân tích khoảng trống kỹ năng."""

from __future__ import annotations

from ..llm import LLM
from ..models import Goal, SkillGap, UserProfile
from .base import structured
from .schemas import GapList


def analyze_gaps(
    llm: LLM, goal: Goal, profile: UserProfile, tone: str
) -> list[SkillGap]:
    """Trả về danh sách khoảng trống kỹ năng, sắp theo ưu tiên tăng dần."""
    skills = ", ".join(profile.current_skills) or "chưa khai báo"
    constraints = "; ".join(goal.constraints) or "không có"
    prompt = f"""Phân tích khoảng trống kỹ năng cho mục tiêu sau.

Mục tiêu: {goal.description}
Thời hạn: {goal.deadline_months} tháng
Kỹ năng hiện có: {skills}
Quỹ thời gian: {profile.hours_per_week} giờ/tuần
Ràng buộc: {constraints}

Hãy liệt kê tối đa 6 khoảng trống kỹ năng quan trọng nhất cần lấp.
Mỗi khoảng trống gồm: skill (tên ngắn), priority (1 = quan trọng nhất, 3 = thấp nhất),
rationale (vì sao cần, gắn với thị trường tuyển dụng), resources (1-3 nguồn học gợi ý).
Không liệt kê kỹ năng người dùng đã có."""

    result = structured(llm, "career", tone, prompt, GapList)
    gaps = list(getattr(result, "gaps", []) or [])
    gaps.sort(key=lambda g: g.priority)
    return gaps