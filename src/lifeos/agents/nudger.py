"""Người Động Viên — giữ động lực, đặc biệt khi lệch kế hoạch."""

from __future__ import annotations

from ..llm import LLM
from ..models import UserProfile
from .base import say


def encourage(llm: LLM, context: str, profile: UserProfile, tone: str) -> str:
    """Viết lời động viên ngắn dựa trên bối cảnh."""
    prompt = f"""Bối cảnh: {context}

Người dùng tên {profile.name}, mục tiêu: {profile.goal_summary or 'đang xây dựng'}.
Hãy viết 2-3 câu động viên chân thành, ghi nhận nỗ lực, không tạo cảm giác tội lỗi.
Nếu họ vừa lệch kế hoạch, hãy bình thường hoá việc đó và chỉ ra bước nhỏ tiếp theo."""
    return say(llm, "nudger", tone, prompt)
