"""Lưu và khôi phục kế hoạch giữa các phiên làm việc."""

from __future__ import annotations

from datetime import date, datetime
from functools import lru_cache

from pydantic import BaseModel

from .config import get_settings
from .memory import Store
from .models import LifeOSPlan, ReviewCard


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


def load_plan(store: Store, plan_id: int) -> LifeOSPlan | None:
    """Khôi phục kế hoạch theo id. Trả về None nếu không tìm thấy."""
    payload = store.get_plan(plan_id)
    if payload is None:
        return None
    return LifeOSPlan.model_validate(payload)


def update_plan(store: Store, plan_id: int, plan: LifeOSPlan) -> bool:
    """Ghi lại kế hoạch sau khi người dùng cập nhật tiến độ."""
    return store.update_plan(plan_id, plan.model_dump(mode="json"))


# --- thẻ ôn tập cách quãng (SRS) ---


def save_review_cards(
    store: Store, plan_id: int, cards: list[ReviewCard]
) -> int:
    """Lưu thẻ ôn tập xuống SQLite, ghi đè theo khoá (plan_id, topic).

    Không có bước này thì thẻ chỉ sống trong phiên làm việc và mất khi tải lại
    trang — nghĩa là vòng ôn tập cách quãng không bao giờ tích luỹ được.
    """
    now = datetime.now().isoformat(timespec="seconds")
    return store.save_cards(
        plan_id, [c.model_dump(mode="json") for c in cards], updated_at=now
    )


def load_review_cards(store: Store, plan_id: int) -> list[ReviewCard]:
    """Đọc thẻ ôn tập của một kế hoạch. Bỏ qua bản ghi không đọc được."""
    cards: list[ReviewCard] = []
    for row in store.load_cards(plan_id):
        try:
            cards.append(ReviewCard.model_validate(row))
        except Exception:  # noqa: BLE001 - bản ghi hỏng không chặn phần còn lại
            continue
    return cards


def due_review_cards(
    store: Store, plan_id: int, today: date | None = None
) -> list[ReviewCard]:
    """Thẻ đã đến hạn ôn của một kế hoạch."""
    day = (today or date.today()).isoformat()
    cards: list[ReviewCard] = []
    for row in store.due_cards(plan_id, today=day):
        try:
            cards.append(ReviewCard.model_validate(row))
        except Exception:  # noqa: BLE001 - bỏ qua bản ghi hỏng
            continue
    return cards


def review_and_save(
    store: Store,
    plan_id: int,
    topic: str,
    quality: int,
    today: date | None = None,
) -> ReviewCard | None:
    """Chấm một thẻ rồi lưu ngay. Trả về None nếu không tìm thấy thẻ.

    Lịch ôn mới được tính bằng `srs.review` rồi ghi đè xuống DB, nên lần mở sau
    sẽ thấy đúng ngày đến hạn mới.
    """
    from .srs import review as srs_review

    row = store.get_card(plan_id, topic)
    if row is None:
        return None
    try:
        card = ReviewCard.model_validate(row)
    except Exception:  # noqa: BLE001 - bản ghi hỏng coi như không có thẻ
        return None

    updated = srs_review(card, quality, today=today)
    save_review_cards(store, plan_id, [updated])
    return updated


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


def recent_plans(store: Store, limit: int = 5) -> list[LifeOSPlan]:
    """Lấy các kế hoạch gần đây để suy ngẫm.

    Bản ghi hỏng bị bỏ qua thay vì làm sập cả quá trình lập kế hoạch mới.
    """
    plans: list[LifeOSPlan] = []
    for row in store.list_plans(limit):
        payload = store.get_plan(row["id"])
        if payload is None:
            continue
        try:
            plans.append(LifeOSPlan.model_validate(payload))
        except Exception:  # noqa: BLE001 - bỏ qua bản ghi không đọc được
            continue
    return plans
