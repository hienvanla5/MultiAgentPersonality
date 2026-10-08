"""Các schema bao (wrapper) cho đầu ra có cấu trúc của agent."""

from __future__ import annotations

from pydantic import BaseModel, Field

from ..models import SkillGap


class GapList(BaseModel):
    gaps: list[SkillGap] = Field(default_factory=list)


class Critique(BaseModel):
    risks: list[str] = Field(default_factory=list)
    overload: bool = False
    suggestions: list[str] = Field(default_factory=list)
    summary: str = ""


class Synthesis(BaseModel):
    headline: str = ""
    key_points: list[str] = Field(default_factory=list)
    next_actions: list[str] = Field(default_factory=list)
    message: str = ""


class Quiz(BaseModel):
    question: str = ""
    options: list[str] = Field(default_factory=list)
    answer_index: int = 0
    explanation: str = ""


class QuizSet(BaseModel):
    """Nhiều câu hỏi trắc nghiệm cho một chủ đề."""

    questions: list[Quiz] = Field(default_factory=list)


class DecomposedTask(BaseModel):
    """Một nhiệm vụ do LLM đề xuất, ở dạng **thô**.

    Cố ý không ràng buộc `priority`/`effort` ở đây. `autonomy.Task` yêu cầu
    `1 <= priority <= 3` và `0 < effort <= 1`; nếu áp ràng buộc đó lên schema
    gửi cho LLM thì một giá trị hơi lệch cũng làm hỏng cả lần gọi có cấu trúc.
    Thà nhận giá trị thô rồi kẹp lại ở `team._normalize_tasks`.
    """

    id: str = ""
    description: str = ""
    skill: str = ""
    priority: int = 2
    effort: float = 0.3


class TaskBreakdown(BaseModel):
    """Kết quả phân rã mục tiêu thành nhiệm vụ do LLM sinh."""

    tasks: list[DecomposedTask] = Field(default_factory=list)