"""Giáo Viên (chế độ gia sư) — giải thích và kiểm tra hiểu biết."""

from __future__ import annotations

from ..llm import LLM
from ..models import QuizResult
from .base import say, structured
from .schemas import Quiz, QuizSet


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


def quiz_set(llm: LLM, topic: str, tone: str, count: int = 3) -> list[Quiz]:
    """Tạo nhiều câu hỏi trắc nghiệm cho cùng một chủ đề."""
    count = max(1, int(count))
    prompt = (
        f"Tạo {count} câu hỏi trắc nghiệm KHÁC NHAU để kiểm tra hiểu biết về: {topic}\n\n"
        f"Mỗi câu gồm: question, options (4 lựa chọn), answer_index (0-3), explanation. "
        f"Trả về đúng {count} câu trong trường `questions`."
    )
    result = structured(llm, "tutor", tone, prompt, QuizSet)
    questions = list(getattr(result, "questions", []) or [])
    return questions[:count]


def grade(answers: list[int], questions: list[Quiz]) -> QuizResult:
    """Chấm điểm bài kiểm tra.

    `answers[i]` là chỉ số người dùng chọn cho `questions[i]`; -1 nghĩa là bỏ trống.
    """
    correct = 0
    weak: list[str] = []
    detail: list[str] = []

    for index, question in enumerate(questions):
        chosen = answers[index] if index < len(answers) else -1
        is_right = chosen == question.answer_index
        if is_right:
            correct += 1
        else:
            # Chủ đề yếu suy ra từ nội dung câu hỏi bị làm sai.
            weak.append(question.question)
        label = "Đúng" if is_right else "Sai"
        detail.append(
            f"Câu {index + 1}: {label} — bạn chọn {chosen}, "
            f"đáp án đúng là {question.answer_index}."
        )

    return QuizResult(
        total=len(questions),
        correct=correct,
        weak_topics=weak,
        detail=detail,
    )


def follow_up_topics(result: QuizResult, limit: int = 3) -> list[str]:
    """Gợi ý các chủ đề cần ôn lại dựa trên câu trả lời sai."""
    return result.weak_topics[: max(0, limit)]
