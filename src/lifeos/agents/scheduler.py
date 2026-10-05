"""Huấn Luyện Viên Kỷ Luật — biến lộ trình thành lịch tuần khả thi."""

from __future__ import annotations

from ..llm import LLM
from ..models import ScheduleTask, StudyPlan, UserProfile, WeeklySchedule
from ..tools.calendar import WEEKDAY_NAMES, shift_off_busy, to_hhmm, to_minutes
from .base import structured

DEFAULT_START_MIN = 20 * 60  # 20:00


def _energy_text(profile: UserProfile) -> str:
    if not profile.energy_windows:
        return "chưa khai báo (mặc định buổi tối 20:00-22:00)"
    return "; ".join(
        f"{w.label} {w.start}-{w.end}" for w in profile.energy_windows
    )


def _modules_text(plan: StudyPlan) -> str:
    lines = [f"- {m.title} ({m.duration_hours}h)" for m in plan.modules]
    return "\n".join(lines) or "- (chưa có module)"


def _normalize_tasks(
    tasks: list[ScheduleTask],
    week: int,
    busy: dict[str, list[tuple[int, int]]] | None,
) -> list[ScheduleTask]:
    """Chuẩn hoá ngày/giờ, tránh khoảng bận, sắp theo trình tự thời gian."""
    cleaned: list[ScheduleTask] = []
    for i, task in enumerate(tasks):
        day = task.day if task.day in WEEKDAY_NAMES else "Mon"
        duration = max(15, int(task.duration_min or 60))
        start = to_minutes(task.start)
        if start < 0:
            start = DEFAULT_START_MIN
        start = shift_off_busy(day, start, duration, busy)
        task.day = day
        task.duration_min = duration
        task.start = to_hhmm(start)
        cleaned.append(task)

    cleaned.sort(key=lambda t: (WEEKDAY_NAMES.index(t.day), to_minutes(t.start)))
    for i, task in enumerate(cleaned):
        task.id = f"w{week}-t{i + 1}"
    return cleaned


def _trim_to_budget(
    tasks: list[ScheduleTask], hours_per_week: int, load_factor: float
) -> list[ScheduleTask]:
    """Bỏ bớt task nếu tổng thời lượng vượt ngân sách tuần."""
    budget_min = int(max(1, hours_per_week) * load_factor * 60)
    kept: list[ScheduleTask] = []
    used = 0
    for task in tasks:
        if used + task.duration_min <= budget_min:
            kept.append(task)
            used += task.duration_min
    return kept


def build_week(
    llm: LLM,
    study_plan: StudyPlan,
    profile: UserProfile,
    tone: str,
    *,
    week: int = 1,
    busy: dict[str, list[tuple[int, int]]] | None = None,
    load_factor: float = 1.0,
    note: str = "",
) -> WeeklySchedule:
    """Sinh lịch cho một tuần, luôn nằm trong ngân sách giờ/tuần."""
    budget_hours = max(1, int(profile.hours_per_week * load_factor))
    prompt = f"""Lập lịch cho TUẦN {week}.

Lộ trình học:
{_modules_text(study_plan)}

Ngân sách thời gian: tối đa {budget_hours} giờ trong tuần (KHÔNG được vượt).
Khung giờ năng lượng cao: {_energy_text(profile)}"""
    if load_factor < 1.0:
        prompt += (
            "\nGIẢM TẢI: kế hoạch trước bị đánh giá quá tải. "
            "Hãy giảm số buổi và rút ngắn mỗi buổi."
        )
    if note:
        prompt += f"\nGhi chú thêm: {note}"
    prompt += (
        "\n\nMỗi task gồm: title, task_type "
        "(study/review/project/interview_prep/rest/other), "
        "day (Mon..Sun), start (HH:MM), duration_min, module_ref (tên module liên quan)."
        "\nChỉ dùng các ngày Mon..Sun. Đặt các buổi học vào khung giờ năng lượng cao."
        "\nSắp xếp hợp lý: học kiến thức mới, xen kẽ buổi ôn tập và buổi dự án."
    )

    schedule = structured(llm, "scheduler", tone, prompt, WeeklySchedule)

    tasks = _normalize_tasks(list(getattr(schedule, "tasks", []) or []), week, busy)
    tasks = _trim_to_budget(tasks, profile.hours_per_week, load_factor)

    schedule.week = week
    schedule.tasks = tasks
    schedule.total_hours = round(sum(t.duration_min for t in tasks) / 60)
    if not schedule.summary:
        schedule.summary = (
            f"Tuần {week}: {len(tasks)} buổi, tổng {schedule.total_hours} giờ."
        )
    return schedule