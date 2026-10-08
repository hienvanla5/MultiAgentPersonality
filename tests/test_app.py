"""Test giao diện Streamlit bằng AppTest (chạy offline với LLM giả)."""

from __future__ import annotations

import pathlib

from streamlit.testing.v1 import AppTest

APP_PATH = str(pathlib.Path(__file__).resolve().parents[1] / "app.py")


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

    downloads = [d for d in app.get("download_button")]
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