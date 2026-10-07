"""Schema dữ liệu dùng chung cho toàn hệ thống (Pydantic v2)."""

from __future__ import annotations

from datetime import date, datetime
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


class ModuleSlice(BaseModel):
    """Một phần số giờ của module được phân bổ vào một tuần."""

    module_title: str
    hours: int = 1
    order: int = 0


class WeekAllocation(BaseModel):
    """Phân bổ module cho một tuần — thuần logic, không gọi LLM."""

    week: int = 1
    items: list[ModuleSlice] = Field(default_factory=list)
    total_hours: int = 0

    @property
    def module_titles(self) -> list[str]:
        titles: list[str] = []
        for item in self.items:
            if item.module_title not in titles:
                titles.append(item.module_title)
        return titles


class ReviewCard(BaseModel):
    """Thẻ ôn tập cách quãng (SRS)."""

    topic: str
    module_ref: Optional[str] = None
    ease: float = 2.5
    interval_days: int = 1
    repetitions: int = 0
    due_date: date = Field(default_factory=date.today)
    last_reviewed: Optional[date] = None
    lapses: int = 0


class WeekProgress(BaseModel):
    """Tiến độ của một tuần."""

    week: int = 1
    total: int = 0
    done: int = 0
    missed: int = 0
    planned: int = 0
    hours_done: int = 0
    hours_planned: int = 0

    @property
    def pct(self) -> int:
        return round(100 * self.done / self.total) if self.total else 0


class ProgramProgress(BaseModel):
    """Tiến độ toàn chương trình."""

    weeks: list[WeekProgress] = Field(default_factory=list)
    overall_pct: int = 0
    hours_done: int = 0
    hours_planned: int = 0
    current_week: int = 1
    streak: int = 0
    missed: int = 0
    on_track: bool = True
    note: str = ""


class QuizResult(BaseModel):
    """Kết quả một lượt kiểm tra hiểu biết."""

    total: int = 0
    correct: int = 0
    weak_topics: list[str] = Field(default_factory=list)
    detail: list[str] = Field(default_factory=list)

    @property
    def score_pct(self) -> int:
        return round(100 * self.correct / self.total) if self.total else 0


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
    weeks: list[WeeklySchedule] = Field(default_factory=list)
    roundtable: Optional[Roundtable] = None