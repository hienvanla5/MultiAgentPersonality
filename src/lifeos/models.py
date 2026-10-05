"""Schema dữ liệu dùng chung cho toàn hệ thống (Pydantic v2)."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class CommunicationStyle(str, Enum):
    DIRECT = "direct"    # thẳng thắn
    GENTLE = "gentle"    # nhẹ nhàng
    BALANCED = "balanced"  # cân bằng


class StrictnessLevel(str, Enum):
    LENIENT = "lenient"    # dễ tính
    MODERATE = "moderate"  # vừa phải
    STRICT = "strict"      # nghiêm khắc


class TaskType(str, Enum):
    STUDY = "study"
    REVIEW = "review"          # ôn tập
    PROJECT = "project"
    INTERVIEW_PREP = "interview_prep"
    REST = "rest"
    OTHER = "other"


class TaskStatus(str, Enum):
    PLANNED = "planned"
    DONE = "done"
    MISSED = "missed"
    MOVED = "moved"


class GoalStatus(str, Enum):
    ACTIVE = "active"
    PAUSED = "paused"
    DONE = "done"


class EnergyWindow(BaseModel):
    """Khoảng thời gian người dùng tỉnh táo/năng lượng cao trong ngày."""

    label: str = "Buổi tối"
    start: str = "20:00"  # HH:MM
    end: str = "22:00"    # HH:MM


class UserProfile(BaseModel):
    """Hồ sơ người dùng — nguồn cho tone adapter và lập kế hoạch cá nhân hóa."""

    name: str = "bạn"
    goal_summary: str = ""
    current_skills: list[str] = Field(default_factory=list)
    hours_per_week: int = 10
    energy_windows: list[EnergyWindow] = Field(default_factory=list)
    communication_style: CommunicationStyle = CommunicationStyle.BALANCED
    strictness: StrictnessLevel = StrictnessLevel.MODERATE
    notes: str = ""


class Goal(BaseModel):
    description: str
    deadline_months: int = 6
    status: GoalStatus = GoalStatus.ACTIVE
    constraints: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=datetime.now)


class SkillGap(BaseModel):
    skill: str
    priority: int = Field(default=2, ge=1, le=3)  # 1 = cao nhất
    rationale: str = ""
    resources: list[str] = Field(default_factory=list)


class StudyModule(BaseModel):
    title: str
    duration_hours: int = 10
    order: int = 0
    depends_on: list[int] = Field(default_factory=list)
    skills_covered: list[str] = Field(default_factory=list)


class StudyPlan(BaseModel):
    modules: list[StudyModule] = Field(default_factory=list)
    total_weeks: int = 1
    overview: str = ""


class ScheduleTask(BaseModel):
    id: str = ""
    title: str
    task_type: TaskType = TaskType.STUDY
    day: str = "Mon"          # Mon..Sun
    start: str = "20:00"      # HH:MM
    duration_min: int = 60
    module_ref: Optional[str] = None
    status: TaskStatus = TaskStatus.PLANNED
    notes: str = ""


class WeeklySchedule(BaseModel):
    week: int = 1
    tasks: list[ScheduleTask] = Field(default_factory=list)
    total_hours: int = 0
    summary: str = ""


class AgentMessage(BaseModel):
    persona: str
    role: str = ""
    content: str
    tone: str = ""
    timestamp: datetime = Field(default_factory=datetime.now)


class Roundtable(BaseModel):
    topic: str = ""
    turns: list[AgentMessage] = Field(default_factory=list)
    synthesis: Optional[AgentMessage] = None


class AdjustmentEvent(BaseModel):
    reason: str
    old_week: int = 0
    new_week: int = 0
    message: str = ""
    created_at: datetime = Field(default_factory=datetime.now)


class LifeOSPlan(BaseModel):
    """Toàn bộ đầu ra khi hệ thống lập kế hoạch cho một mục tiêu."""

    goal: Optional[Goal] = None
    gaps: list[SkillGap] = Field(default_factory=list)
    study_plan: Optional[StudyPlan] = None
    first_week: Optional[WeeklySchedule] = None
    roundtable: Optional[Roundtable] = None