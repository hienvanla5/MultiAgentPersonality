"""Phát hiện mục tiêu mơ hồ và sinh câu hỏi làm rõ (tối đa 3 câu)."""

from __future__ import annotations

_TIME_HINTS = ("tháng", "tuần", "năm", "deadline", "trong vòng", "quý")
_HOURS_HINTS = ("giờ", "tiếng", "full-time", "part-time", "rảnh", "buổi")


def clarifying_questions(goal_summary: str) -> list[str]:
    """Trả về danh sách câu hỏi làm rõ nếu mục tiêu còn mơ hồ."""
    text = (goal_summary or "").strip().lower()
    questions: list[str] = []

    if len(text.split()) < 4:
        questions.append(
            "Bạn muốn đạt được kết quả cụ thể nào, và 'thành công' "
            "trông như thế nào với bạn?"
        )
    if not any(hint in text for hint in _TIME_HINTS):
        questions.append("Bạn muốn đạt mục tiêu này trong bao lâu (ví dụ 6 tháng)?")
    if not any(hint in text for hint in _HOURS_HINTS):
        questions.append("Mỗi tuần bạn dành được bao nhiêu giờ cho việc này?")

    return questions[:3]


def needs_clarification(goal_summary: str) -> bool:
    return bool(clarifying_questions(goal_summary))
