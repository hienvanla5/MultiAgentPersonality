"""Huấn Luyện Viên Kỷ Luật — biến lộ trình thành lịch tuần khả thi."""

from __future__ import annotations

from ..llm import LLM
from ..models import (
    ModuleSlice,
    ScheduleTask,
    StudyPlan,
    TaskType,
    UserProfile,
    WeekAllocation,
    WeeklySchedule,
)
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


# --- Lịch nhiều tuần (thuần logic, không gọi LLM) ---


def allocate_modules(
    study_plan: StudyPlan, hours_per_week: int, weeks: int
) -> list[WeekAllocation]:
    """Chia module vào từng tuần theo số giờ, giữ nguyên thứ tự học.

    Module dài hơn quỹ thời gian một tuần sẽ bị cắt qua nhiều tuần.
    """
    capacity = max(1, int(hours_per_week))
    queue: list[list] = [
        [m.title, max(1, int(m.duration_hours)), m.order]
        for m in sorted(study_plan.modules, key=lambda m: m.order)
    ]

    allocations: list[WeekAllocation] = []
    index = 0
    for week in range(1, max(1, int(weeks)) + 1):
        remaining = capacity
        items: list[ModuleSlice] = []
        while remaining > 0 and index < len(queue):
            title, hours, order = queue[index]
            take = min(hours, remaining)
            items.append(ModuleSlice(module_title=title, hours=take, order=order))
            hours -= take
            remaining -= take
            if hours <= 0:
                index += 1
            else:
                queue[index][1] = hours
        allocations.append(
            WeekAllocation(week=week, items=items, total_hours=capacity - remaining)
        )
    return allocations


def _session_start_min(profile: UserProfile) -> int:
    if profile.energy_windows:
        start = to_minutes(profile.energy_windows[0].start)
        if start >= 0:
            return start
    return DEFAULT_START_MIN


def week_from_allocation(
    allocation: WeekAllocation,
    profile: UserProfile,
    busy: dict[str, list[tuple[int, int]]] | None = None,
) -> WeeklySchedule:
    """Sinh lịch một tuần từ phân bổ module, không gọi LLM.

    Buổi học được rải đều các ngày; nếu một ngày có nhiều buổi thì giờ bắt đầu
    được đẩy lùi để không chồng lên nhau.
    """
    start_min = _session_start_min(profile)

    sessions: list[tuple[str, int]] = []
    for item in allocation.items:
        total = item.hours * 60
        while total > 0:
            duration = 90 if total >= 90 else total
            sessions.append((item.module_title, duration))
            total -= duration

    tasks: list[ScheduleTask] = []
    for index, (title, duration) in enumerate(sessions):
        day = WEEKDAY_NAMES[index % len(WEEKDAY_NAMES)]
        slot = index // len(WEEKDAY_NAMES)  # buổi thứ mấy trong cùng một ngày
        tasks.append(
            ScheduleTask(
                title=f"{title} (buổi {index + 1})",
                task_type=TaskType.STUDY,
                day=day,
                start=to_hhmm(start_min + slot * 120),
                duration_min=duration,
                module_ref=title,
            )
        )

    tasks = _normalize_tasks(tasks, allocation.week, busy)
    tasks = _trim_to_budget(tasks, profile.hours_per_week, 1.0)
    total_hours = round(sum(t.duration_min for t in tasks) / 60)
    modules = ", ".join(allocation.module_titles) or "không có module"
    return WeeklySchedule(
        week=allocation.week,
        tasks=tasks,
        total_hours=total_hours,
        summary=f"Tuần {allocation.week}: {len(tasks)} buổi, {total_hours} giờ — {modules}.",
    )


def build_program(
    llm: LLM,
    study_plan: StudyPlan,
    profile: UserProfile,
    tone: str,
    *,
    weeks: int = 4,
    busy: dict[str, list[tuple[int, int]]] | None = None,
    detailed_weeks: int = 1,
) -> list[WeeklySchedule]:
    """Sinh lịch nhiều tuần.

    `detailed_weeks` tuần đầu do LLM lập chi tiết; các tuần còn lại sinh thuần
    logic để tránh gọi LLM hàng chục lần cho một lộ trình 24 tuần.
    """
    weeks = max(1, int(weeks))
    allocations = allocate_modules(study_plan, profile.hours_per_week, weeks)

    program: list[WeeklySchedule] = []
    for allocation in allocations:
        if allocation.week <= max(0, int(detailed_weeks)):
            program.append(
                build_week(
                    llm, study_plan, profile, tone, week=allocation.week, busy=busy
                )
            )
        else:
            program.append(week_from_allocation(allocation, profile, busy))
    return program