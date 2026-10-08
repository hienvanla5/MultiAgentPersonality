"""Test giao diện Streamlit bằng AppTest (chạy offline với LLM giả)."""

from __future__ import annotations

import pathlib

import pytest
from streamlit.testing.v1 import AppTest

from lifeos import persistence
from lifeos.config import get_settings
from lifeos.memory import Store

APP_PATH = str(pathlib.Path(__file__).resolve().parents[1] / "app.py")


@pytest.fixture(autouse=True)
def app_store(tmp_path, monkeypatch) -> Store:
    """Chuyển `persistence.default_store` sang DB tạm.

    Ứng dụng giờ ghi kế hoạch và thẻ ôn tập xuống SQLite; nếu không chặn, mỗi
    lượt chạy test sẽ đổ rác vào `data/lifeos.db` thật của người dùng.
    """
    store = Store(f"sqlite:///{tmp_path / 'app-test.db'}")
    monkeypatch.setattr(persistence, "default_store", lambda: store)
    return store


def _run_offline_app() -> AppTest:
    app = AppTest.from_file(APP_PATH, default_timeout=180)
    app.run()
    # Bật chế độ LLM giả để không cần API key
    app.checkbox[0].set_value(True)
    return app


def test_app_boots_without_exception():
    app = _run_offline_app()
    assert not app.exception
    assert app.button  # có nút "Lập kế hoạch"


def test_app_renders_plan_after_click():
    app = _run_offline_app()
    app.button[0].click().run()

    assert not app.exception

    subheaders = " | ".join(item.value for item in app.subheader)
    assert "Khoảng trống kỹ năng" in subheaders
    assert "Lộ trình học" in subheaders
    assert "Lịch tuần" in subheaders
    assert "Hội đồng persona" in subheaders

    # Có bảng dữ liệu: gap, module, lịch tuần
    assert len(app.dataframe) >= 3

    # Có hội đồng nhiều giọng
    chat_text = " ".join(item.value for item in app.markdown)
    assert "Người Phản Biện" in chat_text
    assert "Người Động Viên" in chat_text


def test_app_adjust_flow_moves_to_next_week():
    app = _run_offline_app()
    app.button[0].click().run()
    assert not app.exception

    # Nút "Điều chỉnh kế hoạch" xuất hiện sau khi có kế hoạch
    adjust_buttons = [b for b in app.button if "Điều chỉnh" in b.label]
    assert adjust_buttons

    adjust_buttons[0].click().run()
    assert not app.exception

    success_text = " ".join(item.value for item in app.success)
    assert "Đã điều chỉnh" in success_text
    assert "tuần 1 → tuần 2" in success_text


def test_app_renders_new_sections():
    app = _run_offline_app()
    app.button[0].click().run()
    assert not app.exception

    subheaders = " | ".join(item.value for item in app.subheader)
    assert "Lịch nhiều tuần" in subheaders
    assert "Tiến độ" in subheaders
    assert "Ôn tập cách quãng" in subheaders
    assert "Kiểm tra hiểu biết" in subheaders


def test_app_offers_ics_download():
    app = _run_offline_app()
    app.button[0].click().run()
    assert not app.exception

    downloads = list(app.get("download_button"))
    assert downloads, "phải có nút tải lịch .ics"
    assert downloads[0].label.startswith("⬇️ Tải lịch .ics")


def test_app_marking_progress_updates_report():
    app = _run_offline_app()
    app.button[0].click().run()
    assert not app.exception

    # Tick buổi đầu tiên của tuần 1 rồi lưu
    app.checkbox[0].set_value(True)
    save_buttons = [b for b in app.button if "Lưu tiến độ" in b.label]
    assert save_buttons
    save_buttons[0].click().run()

    assert not app.exception
    success_text = " ".join(item.value for item in app.success)
    assert "Đã ghi nhận" in success_text

    metrics = {m.label: m.value for m in app.metric}
    assert metrics.get("Hoàn thành") not in (None, "0%")


def test_app_renders_self_organization_section():
    app = _run_offline_app()
    app.button[0].click().run()
    assert not app.exception

    subheaders = " | ".join(item.value for item in app.subheader)
    assert "Tự tổ chức nhóm" in subheaders


def test_app_team_self_organization_runs():
    app = _run_offline_app()
    app.button[0].click().run()

    team_buttons = [b for b in app.button if "tự tổ chức nhóm" in b.label]
    assert team_buttons, "phải có nút chạy tự tổ chức nhóm"
    team_buttons[0].click().run()

    assert not app.exception
    success_text = " ".join(item.value for item in app.success)
    assert "Đã giao đủ" in success_text


def test_app_shows_acl_transcript_after_team_run():
    app = _run_offline_app()
    app.button[0].click().run()

    team_buttons = [b for b in app.button if "tự tổ chức nhóm" in b.label]
    team_buttons[0].click().run()
    assert not app.exception

    text = " ".join(item.value for item in app.text)
    assert "[request]" in text
    assert "orchestrator" in text


# --- T1: thẻ ôn tập được lưu xuống SQLite ---


def test_app_persists_review_cards_after_planning(app_store):
    app = _run_offline_app()
    app.button[0].click().run()
    assert not app.exception

    assert app_store.count_cards() > 0, "thẻ ôn tập phải được ghi xuống SQLite"
    plan_id = app.session_state["plan_id"]
    assert plan_id is not None
    assert app_store.count_cards(plan_id) > 0


def test_app_review_section_says_cards_are_saved(app_store):
    app = _run_offline_app()
    app.button[0].click().run()
    assert not app.exception

    captions = " ".join(c.value for c in app.caption)
    assert "lưu trong SQLite" in captions


def test_app_recording_a_review_updates_sqlite(app_store):
    app = _run_offline_app()
    app.button[0].click().run()

    review_buttons = [b for b in app.button if "Ghi nhận lượt ôn" in b.label]
    assert review_buttons, "phải có nút ghi nhận lượt ôn"
    review_buttons[0].click().run()
    assert not app.exception

    plan_id = app.session_state["plan_id"]
    cards = persistence.load_review_cards(app_store, plan_id)
    assert any(c.repetitions > 0 for c in cards), "lượt ôn phải được ghi lại"


def test_app_loads_existing_cards_instead_of_regenerating(app_store):
    """Mở lại ứng dụng phải đọc thẻ cũ, không tạo lại từ đầu (mất tiến độ)."""
    app = _run_offline_app()
    app.button[0].click().run()
    plan_id = app.session_state["plan_id"]

    # Đẩy một thẻ lên chu kỳ xa để nhận ra nếu bị ghi đè
    cards = persistence.load_review_cards(app_store, plan_id)
    target = cards[0].topic
    persistence.review_and_save(app_store, plan_id, target, quality=5)
    persistence.review_and_save(app_store, plan_id, target, quality=5)
    advanced = {c.topic: c.repetitions for c in persistence.load_review_cards(app_store, plan_id)}

    # Chạy lại ứng dụng với cùng session (không bấm Lập kế hoạch lại)
    app.run()
    assert not app.exception
    after = {c.topic: c.repetitions for c in persistence.load_review_cards(app_store, plan_id)}
    assert after == advanced
    assert after[target] == 2


def test_app_shows_saved_plans_selector(app_store):
    """Sau khi lưu kế hoạch, thanh bên phải có mục mở lại."""
    app = _run_offline_app()
    app.button[0].click().run()
    assert not app.exception

    subheaders = " ".join(item.value for item in app.sidebar.subheader)
    assert "Kế hoạch đã lưu" in subheaders


def test_app_sidebar_reports_no_saved_plans_when_empty(app_store):
    app = _run_offline_app()
    assert not app.exception
    captions = " ".join(c.value for c in app.sidebar.caption)
    assert "Chưa có kế hoạch nào" in captions


def _saved_plan_box(app: AppTest):
    """Tìm ô chọn "Mở lại" — thanh bên còn nhiều selectbox khác (phong cách...)."""
    for box in app.sidebar.selectbox:
        if box.label == "Mở lại":
            return box
    return None


def test_app_saved_plan_button_hidden_until_a_plan_is_chosen(app_store):
    """Mặc định là "—" nên chưa hiện nút tải; tránh tải nhầm kế hoạch."""
    app = _run_offline_app()
    app.button[0].click().run()
    # `render_saved_plans` đọc DB ở đầu mỗi lượt chạy, còn kế hoạch được lưu ở
    # cuối lượt — nên phải chạy thêm một lượt mới thấy kế hoạch vừa tạo.
    app.run()
    assert not app.exception

    box = _saved_plan_box(app)
    assert box is not None, "phải có ô chọn kế hoạch đã lưu"
    assert box.value == "—"

    labels = [b.label for b in app.sidebar.button]
    assert not any("Tải kế hoạch này" in label for label in labels)


def test_app_sidebar_selector_appears_after_planning(app_store):
    """Sau khi lập kế hoạch, thanh bên phải liệt kê được kế hoạch đó."""
    app = _run_offline_app()
    app.button[0].click().run()
    app.run()

    box = _saved_plan_box(app)
    assert box is not None
    plan_id = app.session_state["plan_id"]
    assert any(o.startswith(f"#{plan_id}") for o in box.options)


def test_app_can_reload_a_saved_plan(app_store):
    """Tải lại kế hoạch cũ phải khôi phục đúng `plan_id` và giữ thẻ ôn tập."""
    app = _run_offline_app()
    app.button[0].click().run()
    plan_id = app.session_state["plan_id"]
    assert app_store.count_cards(plan_id) > 0

    # Phiên mới hoàn toàn: mất session_state, chỉ còn DB
    fresh = _run_offline_app()
    fresh.checkbox[0].set_value(True)
    fresh.run()
    assert "plan" not in fresh.session_state

    box = _saved_plan_box(fresh)
    assert box is not None
    target = next(o for o in box.options if o.startswith(f"#{plan_id}"))
    box.select(target).run()

    load_buttons = [b for b in fresh.sidebar.button if "Tải kế hoạch này" in b.label]
    assert load_buttons, "chọn kế hoạch rồi phải hiện nút tải"
    load_buttons[0].click().run()
    assert not fresh.exception

    assert fresh.session_state["plan_id"] == plan_id
    assert "Khoảng trống kỹ năng" in " ".join(
        item.value for item in fresh.subheader
    )


def test_app_reloaded_plan_keeps_review_progress(app_store):
    """Mở lại kế hoạch cũ không được xoá tiến độ ôn đã tích luỹ."""
    app = _run_offline_app()
    app.button[0].click().run()
    plan_id = app.session_state["plan_id"]

    topic = persistence.load_review_cards(app_store, plan_id)[0].topic
    persistence.review_and_save(app_store, plan_id, topic, quality=5)

    fresh = _run_offline_app()
    fresh.checkbox[0].set_value(True)
    fresh.run()
    box = _saved_plan_box(fresh)
    box.select(next(o for o in box.options if o.startswith(f"#{plan_id}"))).run()
    next(b for b in fresh.sidebar.button if "Tải kế hoạch này" in b.label).click().run()

    cards = {
        c.topic: c.repetitions
        for c in persistence.load_review_cards(app_store, plan_id)
    }
    assert cards[topic] == 1


# --- Google Calendar (T5) ---


@pytest.fixture(autouse=True)
def _clear_settings_cache():
    """`get_settings` được `lru_cache`; xoá cache để test đổi được cấu hình.

    Không xoá thì giá trị đã cache (kể cả bản đã bị monkeypatch) sẽ rò sang
    các test khác.
    """
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _button(app, label: str):
    """Tìm nút theo nhãn, không phụ thuộc thứ tự."""
    matches = [b for b in app.button if label in b.label]
    assert matches, f"không thấy nút '{label}'"
    return matches[0]


def _plan_app(monkeypatch, client_id: str = "") -> AppTest:
    monkeypatch.setenv("GOOGLE_CLIENT_ID", client_id)
    get_settings.cache_clear()
    app = _run_offline_app()
    app.button[0].click().run()
    return app


def test_app_google_calendar_section_renders(monkeypatch):
    app = _plan_app(monkeypatch)
    assert not app.exception
    assert _button(app, "Xem trước payload")
    assert _button(app, "Đồng bộ ngay")


def test_app_google_sync_disabled_without_client_id(monkeypatch):
    """Chưa cấu hình thì không được để người dùng bấm đồng bộ rồi lỗi."""
    app = _plan_app(monkeypatch, client_id="")
    assert _button(app, "Đồng bộ ngay").disabled is True


def test_app_google_sync_enabled_with_client_id(monkeypatch):
    app = _plan_app(monkeypatch, client_id="test.apps.googleusercontent.com")
    assert _button(app, "Đồng bộ ngay").disabled is False


def test_app_google_preview_lists_events_without_network(monkeypatch):
    """Xem trước phải hoạt động khi chưa cấu hình và không chạm mạng."""
    app = _plan_app(monkeypatch, client_id="")
    before = len(app.dataframe)

    _button(app, "Xem trước payload").click().run()

    assert not app.exception
    assert len(app.dataframe) > before
    text = " ".join(item.value for item in app.caption)
    assert "Chạy khô" in text


def test_app_google_missing_config_shows_guidance(monkeypatch):
    app = _plan_app(monkeypatch, client_id="")
    info = " ".join(item.value for item in app.info)
    assert "GOOGLE_CLIENT_ID" in info


def test_app_google_configured_shows_redirect_uri(monkeypatch):
    app = _plan_app(monkeypatch, client_id="test.apps.googleusercontent.com")
    text = " ".join(item.value for item in app.markdown)
    assert "http://localhost:" in text
