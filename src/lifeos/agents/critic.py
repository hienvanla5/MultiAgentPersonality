"""Người Phản Biện — soi rủi ro và quá tải của kế hoạch."""

from __future__ import annotations

from ..llm import LLM
from ..models import UserProfile
from .base import structured
from .schemas import Critique


def critique(
    llm: LLM, plan_summary: str, profile: UserProfile, tone: str
) -> Critique:
    """Phản biện kế hoạch; đặt overload=True nếu vượt quỹ thời gian."""
    prompt = f"""Hãy phản biện kế hoạch dưới đây.

{plan_summary}

Quỹ thời gian thực tế của người dùng: {profile.hours_per_week} giờ/tuần.
Ràng buộc khác: {profile.notes or 'không'}

Hãy tìm: rủi ro (risks), giả định sai, và các điểm quá tải.
Đặt overload = true nếu kế hoạch vượt quá quỹ thời gian hoặc quá dày để duy trì.
Đưa ra suggestions (cách sửa cụ thể) và summary (1-2 câu kết luận).
Phản biện ý tưởng, không phản biện con người."""

    result = structured(llm, "critic", tone, prompt, Critique)
    return result
