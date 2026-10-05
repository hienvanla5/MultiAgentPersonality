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