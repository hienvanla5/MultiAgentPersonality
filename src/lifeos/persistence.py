"""Lưu và khôi phục kế hoạch giữa các phiên làm việc."""

from __future__ import annotations

from datetime import datetime
from functools import lru_cache
from typing import Optional

from pydantic import BaseModel

from .config import get_settings
from .memory import Store
from .models import LifeOSPlan


class PlanSummary(BaseModel):
    """Thông tin ngắn gọn về một kế hoạch đã lưu."""

    id: int
    goal_summary: str = ""
    created_at: str = ""
    weeks: int = 0
    progress_pct: int = 0


@lru_cache
def default_store() -> Store:
    """Store dùng file SQLite trong `data/` (tạo thư mục nếu chưa có)."""
    settings = get_settings()
    settings.db_file.parent.mkdir(parents=True, exist_ok=True)
    return Store(settings.db_url)


def save_plan(store: Store, plan: LifeOSPlan) -> int:
    """Lưu kế hoạch, trả về id."""
    goal_text = plan.goal.description if plan.goal else ""
    now = datetime.now().isoformat(timespec="seconds")
    return store.save_plan(goal_text, plan.model_dump(mode="json"), now)


def load_plan(store: Store, plan_id: int) -> Optional[LifeOSPlan]:
    """Khôi phục kế hoạch theo id. Trả về None nếu không tìm thấy."""
    payload = store.get_plan(plan_id)
    if payload is None:
        return None
    return LifeOSPlan.model_validate(payload)


def update_plan(store: Store, plan_id: int, plan: LifeOSPlan) -> bool:
    """Ghi lại kế hoạch sau khi người dùng cập nhật tiến độ."""
    return store.update_plan(plan_id, plan.model_dump(mode="json"))


def list_plans(store: Store, limit: int = 20) -> list[PlanSummary]:
    """Liệt kê kế hoạch đã lưu kèm tiến độ tóm tắt."""
    from .progress import program_progress

    summaries: list[PlanSummary] = []
    for row in store.list_plans(limit):
        weeks = 0
        pct = 0
        payload = store.get_plan(row["id"])
        if payload is not None:
            try:
                plan = LifeOSPlan.model_validate(payload)
            except Exception:  # noqa: BLE001 - bản ghi cũ/hỏng thì bỏ qua
                plan = None
            if plan is not None:
                weeks = len(plan.weeks)
                pct = program_progress(plan).overall_pct
        summaries.append(
            PlanSummary(
                id=row["id"],
                goal_summary=row["goal_summary"],
                created_at=row["created_at"],
                weeks=weeks,
                progress_pct=pct,
            )
        )
    return summaries