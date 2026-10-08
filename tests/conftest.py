"""Fixture và LLM giả dùng chung cho test."""

from __future__ import annotations

import pytest

from lifeos.agents.schemas import (
    Critique,
    DecomposedTask,
    GapList,
    Quiz,
    QuizSet,
    Synthesis,
    TaskBreakdown,
)
from lifeos.models import (
    CommunicationStyle,
    EnergyWindow,
    ScheduleTask,
    SkillGap,
    StrictnessLevel,
    StudyModule,
    StudyPlan,
    UserProfile,
    WeeklySchedule,
)


class FakeLLM:
    """LLM giả tất định: không gọi mạng, kiểm soát được hành vi quá tải."""

    def __init__(self, overload_times: int = 1) -> None:
        self.calls: list[str] = []
        self.overload_remaining = overload_times

    def structured(self, system_prompt: str, user_prompt: str, schema):
        self.calls.append(schema.__name__)

        if schema is GapList:
            return GapList(
                gaps=[
                    SkillGap(skill="SQL", priority=1, rationale="cần cho JD"),
                    SkillGap(skill="Thống kê", priority=2, rationale="cần cho A/B test"),
                ]
            )
        if schema is StudyPlan:
            return StudyPlan(
                modules=[StudyModule(title="SQL nền tảng", duration_hours=20, order=0)],
                total_weeks=24,
                overview="ok",
            )
        if schema is WeeklySchedule:
            return WeeklySchedule(
                tasks=[
                    ScheduleTask(
                        title="Học SQL", day="Mon", start="20:00", duration_min=120
                    ),
                    ScheduleTask(
                        title="Ôn tập", day="Sat", start="09:00", duration_min=90
                    ),
                ]
            )
        if schema is Critique:
            if self.overload_remaining > 0:
                self.overload_remaining -= 1
                return Critique(
                    overload=True, risks=["quá tải"], summary="Kế hoạch quá tải."
                )
            return Critique(overload=False, summary="Kế hoạch ổn.")
        if schema is Synthesis:
            return Synthesis(headline="Kết luận", message="Tổng hợp kế hoạch.")
        if schema is Quiz:
            return Quiz(
                question="q", options=["a", "b"], answer_index=0, explanation="e"
            )
        if schema is QuizSet:
            return QuizSet(
                questions=[
                    Quiz(
                        question=f"q{i}",
                        options=["a", "b"],
                        answer_index=0,
                        explanation="e",
                    )
                    for i in range(1, 4)
                ]
            )
        if schema is TaskBreakdown:
            return TaskBreakdown(
                tasks=[
                    DecomposedTask(
                        id="doc-jd",
                        description="Đọc tin tuyển dụng",
                        skill="gap-analysis",
                        priority=1,
                        effort=0.3,
                    ),
                    DecomposedTask(
                        id="lo-trinh",
                        description="Xếp lộ trình học",
                        skill="curriculum",
                        priority=1,
                        effort=0.4,
                    ),
                    DecomposedTask(
                        id="lich-tuan",
                        description="Chia buổi tối",
                        skill="scheduling",
                        priority=2,
                        effort=0.4,
                    ),
                    DecomposedTask(
                        id="giu-dong-luc",
                        description="Viết lời nhắc",
                        skill="motivation",
                        priority=3,
                        effort=0.1,
                    ),
                ]
            )
        raise AssertionError(f"FakeLLM không hỗ trợ schema {schema.__name__}")

    def text(self, system_prompt: str, user_prompt: str) -> str:
        self.calls.append("text")
        return "Cố lên!"

    def count(self, name: str) -> int:
        return sum(1 for call in self.calls if call == name)


@pytest.fixture
def fake_llm() -> FakeLLM:
    return FakeLLM()


@pytest.fixture
def fake_llm_cls():
    return FakeLLM


@pytest.fixture
def profile() -> UserProfile:
    return UserProfile(
        name="Minh",
        goal_summary="Chuyển sang Data Analyst trong 6 tháng, vẫn đi làm full-time",
        current_skills=["Excel"],
        hours_per_week=10,
        energy_windows=[EnergyWindow(label="Tối", start="20:00", end="22:00")],
        communication_style=CommunicationStyle.DIRECT,
        strictness=StrictnessLevel.STRICT,
    )