"""Theo dõi tiến độ trên lịch nhiều tuần.

Toàn bộ module này là logic thuần: không gọi LLM, dễ kiểm thử và tất định.
"""

from __future__ import annotations

from typing import Optional

from .models import (
    LifeOSPlan,
    ProgramProgress,
    ScheduleTask,
    TaskStatus,
    WeekProgress,
    WeeklySchedule,
)


def all_weeks(plan: LifeOSPlan) -> list[WeeklySchedule]:
    """Danh sách tuần của kế hoạch (ưu tiên `weeks`, lùi về `first_week`)."""
    if plan.weeks:
        return list(plan.weeks)
    if plan.first_week is not None:
        return [plan.first_week]
    return []


def find_task(plan: LifeOSPlan, task_id: str) -> Optional[ScheduleTask]:
    """Tìm một buổi học theo id."""
    for week in all_weeks(plan):
        for task in week.tasks:
            if task.id == task_id:
                return task
    return None


def mark_task(plan: LifeOSPlan, task_id: str, status: TaskStatus) -> bool:
    """Đánh dấu trạng thái một buổi học. Trả về True nếu tìm thấy.

    Lưu ý: hàm này sửa trực tiếp trên `plan` (thao tác cập nhật trạng thái).
    """
    task = find_task(plan, task_id)
    if task is None:
        return False
    task.status = status
    return True


def mark_week(plan: LifeOSPlan, week: int, status: TaskStatus) -> int:
    """Đánh dấu cả một tuần. Trả về số buổi được cập nhật."""
    count = 0
    for schedule in all_weeks(plan):
        if schedule.week != week:
            continue
        for task in schedule.tasks:
            task.status = status
            count += 1
    return count


def missed_task_titles(plan: LifeOSPlan) -> list[str]:
    """Tiêu đề các buổi đã bị trượt — dùng làm đầu vào cho luồng điều chỉnh."""
    return [
        task.title
        for week in all_weeks(plan)
        for task in week.tasks
        if task.status == TaskStatus.MISSED
    ]


def week_progress(schedule: WeeklySchedule) -> WeekProgress:
    """Tính tiến độ của một tuần."""
    tasks = schedule.tasks
    hours_planned = schedule.total_hours or round(
        sum(t.duration_min for t in tasks) / 60
    )
    return WeekProgress(
        week=schedule.week,
        total=len(tasks),
        done=sum(1 for t in tasks if t.status == TaskStatus.DONE),
        missed=sum(1 for t in tasks if t.status == TaskStatus.MISSED),
        planned=sum(1 for t in tasks if t.status == TaskStatus.PLANNED),
        hours_done=round(
            sum(t.duration_min for t in tasks if t.status == TaskStatus.DONE) / 60
        ),
        hours_planned=hours_planned,
    )


def program_progress(plan: LifeOSPlan) -> ProgramProgress:
    """Tính tiến độ toàn chương trình, tuần hiện tại và trạng thái đúng tiến độ."""
    weeks = all_weeks(plan)
    progresses = [week_progress(w) for w in weeks]

    total = sum(p.total for p in progresses)
    done = sum(p.done for p in progresses)
    hours_done = sum(p.hours_done for p in progresses)
    hours_planned = sum(p.hours_planned for p in progresses)

    # Tuần hiện tại: tuần đầu tiên chưa hoàn thành; nếu xong hết thì là tuần cuối.
    current = weeks[-1].week if weeks else 1
    for p in progresses:
        if p.total and p.done < p.total:
            current = p.week
            break

    # Chuỗi tuần hoàn thành liên tiếp tính từ tuần 1.
    streak = 0
    for p in progresses:
        if p.total and p.done == p.total:
            streak += 1
        else:
            break

    # Đúng tiến độ nếu không có buổi nào bị trượt tính tới tuần hiện tại.
    relevant = [p for p in progresses if p.week <= current]
    missed = sum(p.missed for p in relevant)
    on_track = missed == 0

    if not weeks:
        note = "Kế hoạch chưa có lịch."
    elif not total:
        note = "Chưa có buổi học nào để theo dõi."
    elif on_track and done == 0:
        note = f"Bắt đầu ở tuần {current}. Chưa đánh dấu buổi nào."
    elif on_track:
        note = f"Đang đúng tiến độ, ở tuần {current}."
    else:
        note = f"Chệch tiến độ: {missed} buổi bị trượt tính tới tuần {current}."

    return ProgramProgress(
        weeks=progresses,
        overall_pct=round(100 * done / total) if total else 0,
        hours_done=hours_done,
        hours_planned=hours_planned,
        current_week=current,
        streak=streak,
        missed=missed,
        on_track=on_track,
        note=note,
    )


def next_tasks(plan: LifeOSPlan, limit: int = 3) -> list[ScheduleTask]:
    """Các buổi sắp tới cần làm (theo thứ tự tuần rồi tới ngày)."""
    pending = [
        task
        for week in all_weeks(plan)
        for task in week.tasks
        if task.status == TaskStatus.PLANNED
    ]
    return pending[: max(0, limit)]