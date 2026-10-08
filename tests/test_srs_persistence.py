"""Test lưu thẻ ôn tập cách quãng (SRS) xuống SQLite.

Trước đây thẻ chỉ sống trong phiên làm việc: mở lại trang là mất sạch, nên vòng
ôn tập cách quãng không bao giờ tích luỹ được. Các test ở đây khoá lại hành vi
đó — thẻ phải sống qua ranh giới tiến trình.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from lifeos import persistence, srs
from lifeos.memory import Store
from lifeos.memory.store import GLOBAL_PLAN_ID
from lifeos.models import ReviewCard


def _store(tmp_path) -> Store:
    return Store(f"sqlite:///{tmp_path / 'cards.db'}")


TODAY = date(2026, 3, 10)


# --- tầng Store: ghi và đọc thô ---


def test_save_and_load_cards_roundtrip(tmp_path):
    store = _store(tmp_path)
    card = srs.new_card("Học SQL", module_ref="SQL nền tảng", today=TODAY)
    store.save_cards(7, [card.model_dump(mode="json")])

    rows = store.load_cards(7)
    assert len(rows) == 1
    assert rows[0]["topic"] == "Học SQL"
    assert rows[0]["module_ref"] == "SQL nền tảng"
    assert rows[0]["due_date"] == TODAY.isoformat()


def test_save_cards_is_idempotent(tmp_path):
    """Bấm "lưu" nhiều lần không được tạo thẻ trùng."""
    store = _store(tmp_path)
    card = srs.new_card("SQL", today=TODAY).model_dump(mode="json")
    store.save_cards(1, [card])
    store.save_cards(1, [card])
    store.save_cards(1, [card])
    assert store.count_cards(1) == 1


def test_save_cards_updates_existing_card(tmp_path):
    """Lần lưu sau phải ghi đè tiến độ ôn, không tạo bản ghi mới."""
    store = _store(tmp_path)
    card = srs.new_card("SQL", today=TODAY)
    store.save_cards(1, [card.model_dump(mode="json")])

    card.repetitions = 3
    card.interval_days = 15
    store.save_cards(1, [card.model_dump(mode="json")])

    assert store.count_cards(1) == 1
    assert store.load_cards(1)[0]["repetitions"] == 3
    assert store.load_cards(1)[0]["interval_days"] == 15


def test_same_topic_in_different_plans_is_separate(tmp_path):
    """Cùng chủ đề nhưng khác kế hoạch là hai thẻ độc lập."""
    store = _store(tmp_path)
    card = srs.new_card("SQL", today=TODAY).model_dump(mode="json")
    store.save_cards(1, [card])
    store.save_cards(2, [card])
    assert store.count_cards(1) == 1
    assert store.count_cards(2) == 1
    assert store.count_cards() == 2


def test_save_cards_skips_blank_topic(tmp_path):
    """Thẻ không có chủ đề thì không có khoá để ghi đè -> phải bỏ qua."""
    store = _store(tmp_path)
    written = store.save_cards(1, [{"topic": "   "}, {"topic": ""}])
    assert written == 0
    assert store.count_cards() == 0


def test_save_empty_card_list_is_noop(tmp_path):
    store = _store(tmp_path)
    assert store.save_cards(1, []) == 0
    assert store.count_cards() == 0


def test_global_plan_id_is_separate_scope(tmp_path):
    store = _store(tmp_path)
    store.save_cards(GLOBAL_PLAN_ID, [{"topic": "chung"}])
    store.save_cards(5, [{"topic": "riêng"}])
    assert store.count_cards(GLOBAL_PLAN_ID) == 1
    assert store.count_cards(5) == 1


# --- truy vấn thẻ đến hạn ---


def test_due_cards_returns_only_due(tmp_path):
    store = _store(tmp_path)
    due = srs.new_card("quá hạn", today=TODAY - timedelta(days=3))
    future = srs.new_card("còn xa", today=TODAY + timedelta(days=10))
    store.save_cards(1, [c.model_dump(mode="json") for c in (due, future)])

    rows = store.due_cards(1, today=TODAY.isoformat())
    assert [r["topic"] for r in rows] == ["quá hạn"]


def test_due_cards_includes_card_due_exactly_today(tmp_path):
    store = _store(tmp_path)
    store.save_cards(1, [{"topic": "hôm nay", "due_date": TODAY.isoformat()}])
    rows = store.due_cards(1, today=TODAY.isoformat())
    assert len(rows) == 1


def test_due_cards_sorted_most_overdue_first(tmp_path):
    store = _store(tmp_path)
    cards = [
        {"topic": "mới quá hạn", "due_date": (TODAY - timedelta(days=1)).isoformat()},
        {"topic": "quá hạn lâu", "due_date": (TODAY - timedelta(days=30)).isoformat()},
        {"topic": "quá hạn vừa", "due_date": (TODAY - timedelta(days=7)).isoformat()},
    ]
    store.save_cards(1, cards)
    rows = store.due_cards(1, today=TODAY.isoformat())
    assert [r["topic"] for r in rows] == [
        "quá hạn lâu",
        "quá hạn vừa",
        "mới quá hạn",
    ]


def test_due_cards_scoped_by_plan(tmp_path):
    store = _store(tmp_path)
    store.save_cards(1, [{"topic": "a", "due_date": TODAY.isoformat()}])
    store.save_cards(2, [{"topic": "b", "due_date": TODAY.isoformat()}])
    assert [r["topic"] for r in store.due_cards(1, today=TODAY.isoformat())] == ["a"]
    assert len(store.due_cards(today=TODAY.isoformat())) == 2


def test_due_cards_empty_store(tmp_path):
    assert _store(tmp_path).due_cards(1, today=TODAY.isoformat()) == []


# --- get_card / delete_cards ---


def test_get_card_returns_matching_card(tmp_path):
    store = _store(tmp_path)
    store.save_cards(1, [{"topic": "SQL", "ease": 2.8}])
    row = store.get_card(1, "SQL")
    assert row is not None
    assert row["ease"] == 2.8


def test_get_card_missing_returns_none(tmp_path):
    assert _store(tmp_path).get_card(1, "không có") is None


def test_get_card_wrong_plan_returns_none(tmp_path):
    store = _store(tmp_path)
    store.save_cards(1, [{"topic": "SQL"}])
    assert store.get_card(2, "SQL") is None


def test_delete_cards_removes_only_that_plan(tmp_path):
    store = _store(tmp_path)
    store.save_cards(1, [{"topic": "a"}, {"topic": "b"}])
    store.save_cards(2, [{"topic": "c"}])

    assert store.delete_cards(1) == 2
    assert store.count_cards(1) == 0
    assert store.count_cards(2) == 1


def test_delete_cards_empty_returns_zero(tmp_path):
    assert _store(tmp_path).delete_cards(99) == 0


# --- chuẩn hoá ngày ---


@pytest.mark.parametrize(
    "value,expected",
    [
        (date(2026, 3, 10), "2026-03-10"),
        ("2026-03-10", "2026-03-10"),
        ("2026-03-10T08:00:00", "2026-03-10"),
        ("  2026-03-10  ", "2026-03-10"),
    ],
)
def test_date_normalisation(tmp_path, value, expected):
    store = _store(tmp_path)
    store.save_cards(1, [{"topic": "t", "due_date": value}])
    assert store.load_cards(1)[0]["due_date"] == expected


def test_unparseable_due_date_falls_back_to_today(tmp_path):
    """Ngày hỏng thì thẻ hiện ra ngay để ôn, còn hơn làm hỏng cả lượt lưu."""
    store = _store(tmp_path)
    store.save_cards(1, [{"topic": "t", "due_date": "không phải ngày"}])
    assert store.load_cards(1)[0]["due_date"] == date.today().isoformat()


def test_missing_due_date_falls_back_to_today(tmp_path):
    store = _store(tmp_path)
    store.save_cards(1, [{"topic": "t"}])
    assert store.load_cards(1)[0]["due_date"] == date.today().isoformat()


def test_last_reviewed_null_stays_null(tmp_path):
    store = _store(tmp_path)
    store.save_cards(1, [{"topic": "t", "last_reviewed": None}])
    assert store.load_cards(1)[0]["last_reviewed"] is None


# --- tầng persistence: chuyển đổi Pydantic ---


def test_save_and_load_review_cards_pydantic(tmp_path):
    store = _store(tmp_path)
    cards = [
        srs.new_card("SQL", today=TODAY),
        srs.new_card("pandas", module_ref="Python", today=TODAY),
    ]
    assert persistence.save_review_cards(store, 3, cards) == 2

    loaded = persistence.load_review_cards(store, 3)
    assert {c.topic for c in loaded} == {"SQL", "pandas"}
    assert all(isinstance(c, ReviewCard) for c in loaded)
    assert all(c.due_date == TODAY for c in loaded)


def test_load_review_cards_empty(tmp_path):
    assert persistence.load_review_cards(_store(tmp_path), 1) == []


def test_save_cards_skips_uncoercible_card(tmp_path):
    """Một thẻ hỏng không được làm mất tiến độ của các thẻ còn lại."""
    store = _store(tmp_path)
    written = store.save_cards(
        1,
        [
            {"topic": "tốt", "ease": 2.5},
            {"topic": "hỏng", "ease": "không phải số"},
            {"topic": "cũng tốt", "ease": 2.1},
        ],
    )
    assert written == 2
    assert [r["topic"] for r in store.load_cards(1)] == ["cũng tốt", "tốt"]


def test_save_cards_skips_bad_interval(tmp_path):
    store = _store(tmp_path)
    assert store.save_cards(1, [{"topic": "t", "interval_days": "mười"}]) == 0
    assert store.count_cards(1) == 0


def test_load_review_cards_skips_corrupt_row(tmp_path):
    """Bản ghi hỏng sẵn trong DB phải bị bỏ qua, không làm sập lượt đọc.

    Ghi thẳng qua ORM để tạo dữ liệu sai mà `save_cards` không cho phép.
    """
    from lifeos.memory.store import ReviewCardRecord

    store = _store(tmp_path)
    persistence.save_review_cards(store, 1, [srs.new_card("tốt", today=TODAY)])
    with store.session() as s:
        s.add(
            ReviewCardRecord(
                plan_id=1,
                topic="hỏng",
                due_date="không-phải-ngày",
                ease=2.5,
                interval_days=1,
                repetitions=0,
                lapses=0,
                updated_at="",
            )
        )
        s.commit()

    loaded = persistence.load_review_cards(store, 1)
    assert [c.topic for c in loaded] == ["tốt"]


def test_due_review_cards_filters_by_date(tmp_path):
    store = _store(tmp_path)
    persistence.save_review_cards(
        store,
        1,
        [
            srs.new_card("quá hạn", today=TODAY - timedelta(days=2)),
            srs.new_card("tương lai", today=TODAY + timedelta(days=5)),
        ],
    )
    due = persistence.due_review_cards(store, 1, today=TODAY)
    assert [c.topic for c in due] == ["quá hạn"]


# --- review_and_save: chấm và lưu ngay ---


def test_review_and_save_updates_schedule(tmp_path):
    store = _store(tmp_path)
    persistence.save_review_cards(store, 1, [srs.new_card("SQL", today=TODAY)])

    updated = persistence.review_and_save(store, 1, "SQL", quality=5, today=TODAY)
    assert updated is not None
    assert updated.repetitions == 1
    assert updated.interval_days == 1
    assert updated.last_reviewed == TODAY
    assert updated.due_date == TODAY + timedelta(days=1)

    # Đã ghi xuống DB, không chỉ nằm trong bộ nhớ
    reloaded = persistence.load_review_cards(store, 1)[0]
    assert reloaded.repetitions == 1
    assert reloaded.due_date == TODAY + timedelta(days=1)


def test_review_and_save_forgotten_card_resets(tmp_path):
    store = _store(tmp_path)
    card = srs.new_card("SQL", today=TODAY)
    card.repetitions = 4
    card.interval_days = 30
    persistence.save_review_cards(store, 1, [card])

    updated = persistence.review_and_save(store, 1, "SQL", quality=0, today=TODAY)
    assert updated.repetitions == 0
    assert updated.interval_days == 1
    assert updated.lapses == 1


def test_review_and_save_missing_card_returns_none(tmp_path):
    assert persistence.review_and_save(_store(tmp_path), 1, "không có", 5) is None


def test_review_and_save_does_not_touch_other_plans(tmp_path):
    store = _store(tmp_path)
    persistence.save_review_cards(store, 1, [srs.new_card("SQL", today=TODAY)])
    persistence.save_review_cards(store, 2, [srs.new_card("SQL", today=TODAY)])

    persistence.review_and_save(store, 1, "SQL", quality=5, today=TODAY)
    assert persistence.load_review_cards(store, 2)[0].repetitions == 0


def test_review_and_save_repeated_reviews_accumulate(tmp_path):
    """Ôn nhiều lần phải giãn khoảng cách ra — đây là điểm cốt lõi của SRS.

    SM-2 tính khoảng cách mới bằng `ease` **cũ** rồi mới cập nhật `ease`, nên
    bước thứ ba là `round(6 x 2.7) = 16` chứ không phải 15.
    """
    store = _store(tmp_path)
    persistence.save_review_cards(store, 1, [srs.new_card("SQL", today=TODAY)])

    intervals = []
    day = TODAY
    for _ in range(3):
        card = persistence.review_and_save(store, 1, "SQL", quality=5, today=day)
        intervals.append(card.interval_days)
        day = card.due_date

    assert intervals == [1, 6, 16]
    assert intervals == sorted(intervals)


# --- sống qua ranh giới tiến trình ---


def test_cards_survive_new_store_instance(tmp_path):
    """Mở lại "ứng dụng" (Store mới trên cùng file) vẫn phải thấy thẻ."""
    url = f"sqlite:///{tmp_path / 'persist.db'}"
    first = Store(url)
    persistence.save_review_cards(first, 1, [srs.new_card("SQL", today=TODAY)])

    second = Store(url)
    loaded = persistence.load_review_cards(second, 1)
    assert len(loaded) == 1
    assert loaded[0].topic == "SQL"
    assert loaded[0].due_date == TODAY


def test_progress_survives_new_store_instance(tmp_path):
    """Tiến độ ôn (số lần lặp, khoảng cách) cũng phải bền vững."""
    url = f"sqlite:///{tmp_path / 'persist.db'}"
    first = Store(url)
    persistence.save_review_cards(first, 1, [srs.new_card("SQL", today=TODAY)])
    persistence.review_and_save(first, 1, "SQL", quality=5, today=TODAY)

    second = Store(url)
    card = persistence.load_review_cards(second, 1)[0]
    assert card.repetitions == 1
    assert card.interval_days == 1
    assert card.last_reviewed == TODAY


def test_cards_from_plan_can_be_persisted(tmp_path, fake_llm, profile):
    """Tích hợp: sinh thẻ từ kế hoạch thật rồi lưu và đọc lại."""
    from lifeos.graph import create_plan

    store = _store(tmp_path)
    plan = create_plan(profile, llm=fake_llm)
    cards = srs.cards_from_plan(plan, today=TODAY)
    assert cards, "kế hoạch phải sinh ra được thẻ ôn tập"

    persistence.save_review_cards(store, 1, cards)
    loaded = persistence.load_review_cards(store, 1)
    assert {c.topic for c in loaded} == {c.topic for c in cards}
