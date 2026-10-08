"""Test ôn tập cách quãng (SM-2)."""

from __future__ import annotations

from datetime import date, timedelta

from lifeos import srs
from lifeos.models import (
    LifeOSPlan,
    ScheduleTask,
    StudyModule,
    StudyPlan,
    TaskStatus,
    TaskType,
)

TODAY = date(2026, 3, 9)


# --- new_card ---


def test_new_card_due_immediately():
    card = srs.new_card("SQL", today=TODAY)
    assert card.due_date == TODAY
    assert card.repetitions == 0
    assert card.ease == 2.5
    assert card.lapses == 0


def test_new_card_defaults_to_today():
    assert srs.new_card("SQL").due_date == date.today()


# --- review: chuỗi trả lời đúng ---


def test_first_correct_review_schedules_tomorrow():
    card = srs.review(srs.new_card("SQL", today=TODAY), 4, today=TODAY)
    assert card.repetitions == 1
    assert card.interval_days == 1
    assert card.due_date == TODAY + timedelta(days=1)
    assert card.last_reviewed == TODAY


def test_second_correct_review_schedules_six_days():
    card = srs.new_card("SQL", today=TODAY)
    srs.review(card, 4, today=TODAY)
    srs.review(card, 4, today=TODAY + timedelta(days=1))
    assert card.repetitions == 2
    assert card.interval_days == 6


def test_third_review_multiplies_by_ease():
    card = srs.new_card("SQL", today=TODAY)
    srs.review(card, 5, today=TODAY)
    srs.review(card, 5, today=TODAY + timedelta(days=1))
    ease_before = card.ease
    srs.review(card, 5, today=TODAY + timedelta(days=7))
    assert card.interval_days == round(6 * ease_before)


def test_intervals_grow_monotonically():
    card = srs.new_card("SQL", today=TODAY)
    day = TODAY
    intervals = []
    for _ in range(6):
        srs.review(card, 5, today=day)
        intervals.append(card.interval_days)
        day = card.due_date
    assert intervals == sorted(intervals)
    assert intervals[-1] > intervals[0]


# --- review: quên ---


def test_forgetting_resets_repetitions_and_counts_lapse():
    card = srs.new_card("SQL", today=TODAY)
    srs.review(card, 5, today=TODAY)
    srs.review(card, 5, today=TODAY + timedelta(days=1))
    assert card.repetitions == 2

    srs.review(card, 1, today=TODAY + timedelta(days=7))
    assert card.repetitions == 0
    assert card.interval_days == 1
    assert card.lapses == 1
    assert card.due_date == TODAY + timedelta(days=8)


def test_forgetting_lowers_ease_but_never_below_minimum():
    card = srs.new_card("SQL", today=TODAY)
    for _ in range(30):
        srs.review(card, 0, today=TODAY)
    assert card.ease >= srs.MIN_EASE
    assert card.ease == srs.MIN_EASE


def test_quality_two_is_treated_as_failure():
    card = srs.new_card("SQL", today=TODAY)
    srs.review(card, 2, today=TODAY)
    assert card.repetitions == 0
    assert card.lapses == 1


def test_quality_three_is_pass():
    card = srs.new_card("SQL", today=TODAY)
    srs.review(card, 3, today=TODAY)
    assert card.repetitions == 1
    assert card.lapses == 0


# --- review: biên ---


def test_quality_clamped_to_valid_range():
    low = srs.new_card("SQL", today=TODAY)
    srs.review(low, -5, today=TODAY)
    assert low.lapses == 1

    high = srs.new_card("SQL", today=TODAY)
    srs.review(high, 99, today=TODAY)
    assert high.repetitions == 1


def test_ease_never_exceeds_maximum():
    card = srs.new_card("SQL", today=TODAY)
    for _ in range(20):
        srs.review(card, 5, today=TODAY)
    assert card.ease <= srs.MAX_EASE


def test_interval_capped_at_maximum():
    card = srs.new_card("SQL", today=TODAY)
    day = TODAY
    for _ in range(40):
        srs.review(card, 5, today=day)
        day = card.due_date
    assert card.interval_days <= srs.MAX_INTERVAL_DAYS


def test_review_returns_same_object_mutated():
    card = srs.new_card("SQL", today=TODAY)
    assert srs.review(card, 4, today=TODAY) is card


def test_due_date_always_after_review_date():
    card = srs.new_card("SQL", today=TODAY)
    day = TODAY
    for quality in [5, 5, 1, 4, 0, 5, 5, 5]:
        srs.review(card, quality, today=day)
        assert card.due_date > day
        day = card.due_date


# --- due_cards ---


def test_due_cards_filters_and_sorts_by_due_date():
    a = srs.new_card("A", today=TODAY)
    b = srs.new_card("B", today=TODAY)
    c = srs.new_card("C", today=TODAY)

    a.due_date = TODAY
    b.due_date = TODAY - timedelta(days=3)  # quá hạn lâu nhất
    c.due_date = TODAY + timedelta(days=5)  # chưa đến hạn

    due = srs.due_cards([a, b, c], today=TODAY)
    assert [card.topic for card in due] == ["B", "A"]


def test_due_cards_includes_card_due_today():
    card = srs.new_card("A", today=TODAY)
    assert srs.due_cards([card], today=TODAY) == [card]


def test_due_cards_empty():
    assert srs.due_cards([], today=TODAY) == []


# --- cards_from_plan ---


def test_cards_from_plan_uses_module_titles_in_order():
    plan = LifeOSPlan(
        study_plan=StudyPlan(
            modules=[
                StudyModule(title="Nâng cao", order=1),
                StudyModule(title="SQL cơ bản", order=0),
            ]
        )
    )
    cards = srs.cards_from_plan(plan, today=TODAY)
    assert [c.topic for c in cards] == ["SQL cơ bản", "Nâng cao"]
    assert all(c.module_ref == c.topic for c in cards)


def test_cards_from_plan_without_study_plan():
    assert srs.cards_from_plan(LifeOSPlan(), today=TODAY) == []


# --- cards_from_tasks ---


def _task(title: str, status: TaskStatus, module_ref: str | None = None) -> ScheduleTask:
    return ScheduleTask(
        id=title,
        title=title,
        task_type=TaskType.STUDY,
        module_ref=module_ref,
        status=status,
    )


def test_cards_from_tasks_only_completed():
    tasks = [
        _task("a", TaskStatus.DONE, module_ref="SQL"),
        _task("b", TaskStatus.PLANNED, module_ref="Python"),
        _task("c", TaskStatus.MISSED, module_ref="Excel"),
    ]
    cards = srs.cards_from_tasks(tasks, today=TODAY)
    assert [c.topic for c in cards] == ["SQL"]


def test_cards_from_tasks_deduplicates_by_module():
    tasks = [
        _task("a", TaskStatus.DONE, module_ref="SQL"),
        _task("b", TaskStatus.DONE, module_ref="SQL"),
    ]
    assert len(srs.cards_from_tasks(tasks, today=TODAY)) == 1


def test_cards_from_tasks_falls_back_to_title():
    cards = srs.cards_from_tasks([_task("Học JOIN", TaskStatus.DONE)], today=TODAY)
    assert cards[0].topic == "Học JOIN"


def test_cards_from_tasks_empty_when_nothing_done():
    assert srs.cards_from_tasks([_task("a", TaskStatus.PLANNED)], today=TODAY) == []


# --- summarize ---


def test_summarize_without_cards():
    assert "Chưa có thẻ" in srs.summarize([], today=TODAY)


def test_summarize_counts_due_cards():
    a = srs.new_card("A", today=TODAY)
    b = srs.new_card("B", today=TODAY)
    b.due_date = TODAY + timedelta(days=4)
    text = srs.summarize([a, b], today=TODAY)
    assert "2 thẻ" in text and "1 thẻ đến hạn" in text


def test_summarize_when_nothing_due_mentions_next_date():
    card = srs.new_card("A", today=TODAY)
    card.due_date = TODAY + timedelta(days=9)
    text = srs.summarize([card], today=TODAY)
    assert "không có thẻ nào đến hạn" in text
    assert (TODAY + timedelta(days=9)).isoformat() in text
