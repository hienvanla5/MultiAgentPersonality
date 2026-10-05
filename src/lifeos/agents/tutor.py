"""Giáo Viên (chế độ gia sư) — giải thích và kiểm tra hiểu biết."""

from __future__ import annotations

from ..llm import LLM
from .base import say, structured
from .schemas import Quiz


def explain(llm: LLM, topic: str, tone: str) -> str:
    """Giải thích một chủ đề theo phong cách Feynman."""
    prompt = (
        f"Giải thích chủ đề sau cho một người đang chuyển ngành, "
        f"theo phong cách Feynman (đơn giản, có ví dụ, tránh thuật ngữ rườm rà):\n\n"
        f"{topic}\n\nTối đa 200 từ."
    )
    return say(llm, "tutor", tone, prompt)


def quiz(llm: LLM, topic: str, tone: str) -> Quiz:
    """Tạo một câu hỏi trắc nghiệm để tự kiểm tra."""
    prompt = (
        f"Tạo 1 câu hỏi trắc nghiệm để kiểm tra hiểu biết về: {topic}\n\n"
        "Gồm: question, options (4 lựa chọn), answer_index (0-3), explanation."
    )
    result = structured(llm, "tutor", tone, prompt, Quiz)
    return result