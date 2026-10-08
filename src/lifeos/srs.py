"""Ôn tập cách quãng (spaced repetition, biến thể SM-2).

Logic thuần, không gọi LLM: dễ kiểm thử và tất định.
"""

from __future__ import annotations

from datetime import date, timedelta

from .models import LifeOSPlan, ReviewCard, ScheduleTask, StudyPlan

# Chất lượng trả lời theo thang SM-2 (0..5).
QUALITY_MIN = 0
QUALITY_MAX = 5
# Dưới ngưỡng này coi như quên -> phải học lại.
QUALITY_PASS = 3
MIN_EASE = 1.3
MAX_EASE = 3.0
MAX_INTERVAL_DAYS = 180


def new_card(topic: str, module_ref: str | None = None, today: date | None = None) -> ReviewCard:
    """Tạo thẻ ôn tập mới, đến hạn ngay trong ngày."""
    return ReviewCard(
        topic=topic,
        module_ref=module_ref,
        ease=2.5,
        interval_days=0,
        repetitions=0,
        due_date=today or date.today(),
    )


def review(card: ReviewCard, quality: int, today: date | None = None) -> ReviewCard:
    """Cập nhật thẻ sau một lần trả lời. Trả về chính `card` đã sửa.

    `quality` theo thang SM-2: 0 = quên hoàn toàn, 5 = nhớ hoàn hảo.
    """
    now = today or date.today()
    q = max(QUALITY_MIN, min(QUALITY_MAX, int(quality)))
    card.last_reviewed = now

    if q < QUALITY_PASS:
        # Quên -> quay lại đầu chu kỳ, ôn lại vào ngày mai.
        card.repetitions = 0
        card.interval_days = 1
        card.lapses += 1
        card.ease = max(MIN_EASE, card.ease - 0.2)
    else:
        card.repetitions += 1
        if card.repetitions == 1:
            card.interval_days = 1
        elif card.repetitions == 2:
            card.interval_days = 6
        else:
            card.interval_days = min(
                MAX_INTERVAL_DAYS, round(card.interval_days * card.ease)
            )
        # Hệ số dễ điều chỉnh theo chất lượng (công thức SM-2).
        card.ease = max(
            MIN_EASE,
            min(
                MAX_EASE,
                card.ease + (0.1 - (5 - q) * (0.08 + (5 - q) * 0.02)),
            ),
        )

    card.due_date = now + timedelta(days=max(1, card.interval_days))
    return card


def due_cards(cards: list[ReviewCard], today: date | None = None) -> list[ReviewCard]:
    """Các thẻ đã đến hạn, thẻ quá hạn lâu nhất lên trước."""
    now = today or date.today()
    return sorted(
        (c for c in cards if c.due_date <= now),
        key=lambda c: c.due_date,
    )


def cards_from_plan(plan: LifeOSPlan, today: date | None = None) -> list[ReviewCard]:
    """Sinh thẻ ôn tập từ các module trong lộ trình học."""
    study_plan: StudyPlan | None = plan.study_plan
    if study_plan is None:
        return []
    return [
        new_card(module.title, module_ref=module.title, today=today)
        for module in sorted(study_plan.modules, key=lambda m: m.order)
    ]


def cards_from_tasks(
    tasks: list[ScheduleTask], today: date | None = None
) -> list[ReviewCard]:
    """Sinh thẻ ôn tập từ các buổi học đã hoàn thành.

    Chỉ những buổi đã học xong mới đáng đưa vào vòng ôn tập.
    """
    from .models import TaskStatus

    seen: list[str] = []
    cards: list[ReviewCard] = []
    for task in tasks:
        if task.status != TaskStatus.DONE:
            continue
        topic = task.module_ref or task.title
        if topic in seen:
            continue
        seen.append(topic)
        cards.append(new_card(topic, module_ref=task.module_ref, today=today))
    return cards


def summarize(cards: list[ReviewCard], today: date | None = None) -> str:
    """Mô tả ngắn tình trạng vòng ôn tập."""
    if not cards:
        return "Chưa có thẻ ôn tập nào."
    now = today or date.today()
    due = due_cards(cards, now)
    if not due:
        soonest = min(c.due_date for c in cards)
        return (
            f"{len(cards)} thẻ, không có thẻ nào đến hạn. "
            f"Thẻ gần nhất vào {soonest.isoformat()}."
        )
    return f"{len(cards)} thẻ, {len(due)} thẻ đến hạn ôn hôm nay."
