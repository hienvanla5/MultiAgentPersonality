"""Test đồng bộ Google Calendar qua OAuth (T5).

Trước đây chỉ có `.ics` để người dùng tự import tay: không có OAuth, không gọi
Google Calendar API, và `google-api-python-client` cũng không có trong
`pyproject.toml`.

Toàn bộ test ở đây chạy **không cần mạng và không cần credentials thật**: phần
gọi HTTP đi qua `FakeTransport`, còn luồng chuyển hướng thì dùng một HTTP server
thật trên cổng localhost (đúng thứ `wait_for_code` phục vụ).
"""

from __future__ import annotations

import base64
import hashlib
import json
import socket
import threading
import time
import urllib.parse
import urllib.request
from datetime import date

import pytest

from lifeos.models import ScheduleTask, TaskStatus, WeeklySchedule
from lifeos.tools.google_calendar import (
    CALENDAR_API,
    DEFAULT_TIME_ZONE,
    EVENT_KEY_PROPERTY,
    SCOPES,
    TOKEN_ENDPOINT,
    GoogleCalendarClient,
    GoogleCalendarError,
    OAuthConfig,
    OAuthSession,
    TokenSet,
    UrllibTransport,
    authorization_url,
    event_key,
    events_from_weeks,
    load_token,
    pkce_pair,
    save_token,
    token_from_response,
    wait_for_code,
)

MONDAY = date(2025, 1, 6)  # thứ Hai


# --- hạ tầng giả ---


class FakeTransport:
    """Transport giả: ghi lại lời gọi và trả phản hồi do hàm `handler` quyết định."""

    def __init__(self, handler=None) -> None:
        self.calls: list[dict] = []
        self.handler = handler or (lambda **_kw: {})

    def request(
        self,
        method,
        url,
        *,
        headers=None,
        json_body=None,
        form=None,
        timeout=30.0,
    ):
        call = {
            "method": method,
            "url": url,
            "headers": headers or {},
            "json": json_body,
            "form": form,
            "timeout": timeout,
        }
        self.calls.append(call)
        return self.handler(**call)

    @property
    def methods(self) -> list[str]:
        return [c["method"] for c in self.calls]


class FakeCalendarAPI:
    """Giả lập Google Calendar API, đủ để kiểm chứng tính idempotent."""

    def __init__(self) -> None:
        self.events: dict[str, dict] = {}
        self._next = 1

    def __call__(self, method, url, headers=None, json=None, form=None, **_kw):
        path = urllib.parse.urlparse(url).path
        query = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)

        if method == "GET" and path.endswith("/events"):
            wanted = (query.get("privateExtendedProperty") or [""])[0]
            key = wanted.split("=", 1)[1] if "=" in wanted else ""
            items = [
                event
                for event in self.events.values()
                if event.get("extendedProperties", {}).get("private", {}).get(
                    EVENT_KEY_PROPERTY
                )
                == key
            ]
            return {"items": items[:1]}

        if method == "GET":
            event_id = path.rsplit("/", 1)[-1]
            return self.events.get(event_id, {})

        if method == "POST":
            event_id = f"ev{self._next}"
            self._next += 1
            stored = dict(json or {})
            stored["id"] = event_id
            self.events[event_id] = stored
            return stored

        if method == "PATCH":
            event_id = path.rsplit("/", 1)[-1]
            stored = dict(self.events.get(event_id, {}))
            stored.update(json or {})
            stored["id"] = event_id
            self.events[event_id] = stored
            return stored

        raise AssertionError(f"FakeCalendarAPI không hỗ trợ {method} {url}")


def _config(tmp_path, **kwargs) -> OAuthConfig:
    base = {
        "client_id": "test.apps.googleusercontent.com",
        "client_secret": "secret",
        "token_path": str(tmp_path / "google_token.json"),
    }
    base.update(kwargs)
    return OAuthConfig(**base)


def _session(tmp_path, transport, **kwargs) -> OAuthSession:
    return OAuthSession(_config(tmp_path, **kwargs), transport=transport)


def _weeks() -> list[WeeklySchedule]:
    return [
        WeeklySchedule(
            week=1,
            tasks=[
                ScheduleTask(
                    id="a1", title="Học SQL", day="Mon", start="20:00", duration_min=90
                ),
                ScheduleTask(
                    title="Ôn tập", day="Sat", start="09:00", duration_min=60
                ),
            ],
        ),
        WeeklySchedule(
            week=2,
            tasks=[
                ScheduleTask(
                    id="a1", title="Học SQL", day="Mon", start="20:00", duration_min=90
                )
            ],
        ),
    ]


def _free_port() -> int:
    """Xin một cổng còn trống từ hệ điều hành."""
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


# --- PKCE ---


def test_pkce_verifier_is_long_enough():
    """RFC 7636 yêu cầu code_verifier từ 43 đến 128 ký tự."""
    verifier, _challenge = pkce_pair()
    assert 43 <= len(verifier) <= 128


def test_pkce_challenge_is_sha256_of_verifier():
    verifier, challenge = pkce_pair()
    expected = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest())
        .decode("ascii")
        .rstrip("=")
    )
    assert challenge == expected


def test_pkce_challenge_has_no_padding():
    _verifier, challenge = pkce_pair()
    assert "=" not in challenge


def test_pkce_pairs_are_unique():
    first = pkce_pair()
    second = pkce_pair()
    assert first != second


# --- URL uỷ quyền ---


def _params(url: str) -> dict[str, str]:
    return {
        key: values[0]
        for key, values in urllib.parse.parse_qs(
            urllib.parse.urlparse(url).query
        ).items()
    }


def test_authorization_url_contains_required_parameters(tmp_path):
    url = authorization_url(
        _config(tmp_path), state="xyz", code_challenge="chal"
    )
    params = _params(url)
    assert params["client_id"] == "test.apps.googleusercontent.com"
    assert params["response_type"] == "code"
    assert params["state"] == "xyz"
    assert params["code_challenge"] == "chal"
    assert params["code_challenge_method"] == "S256"


def test_authorization_url_requests_offline_access(tmp_path):
    """Thiếu `access_type=offline` thì không có refresh token."""
    params = _params(
        authorization_url(_config(tmp_path), state="s", code_challenge="c")
    )
    assert params["access_type"] == "offline"


def test_authorization_url_uses_minimal_scope(tmp_path):
    """Chỉ xin quyền trên sự kiện, không xin đọc toàn bộ lịch."""
    params = _params(
        authorization_url(_config(tmp_path), state="s", code_challenge="c")
    )
    assert params["scope"] == SCOPES[0]
    assert "calendar.readonly" not in params["scope"]


def test_authorization_url_redirect_is_localhost(tmp_path):
    params = _params(
        authorization_url(_config(tmp_path), state="s", code_challenge="c")
    )
    assert params["redirect_uri"] == "http://localhost:8765/"


def test_authorization_url_includes_login_hint_when_given(tmp_path):
    params = _params(
        authorization_url(
            _config(tmp_path), state="s", code_challenge="c", login_hint="a@b.com"
        )
    )
    assert params["login_hint"] == "a@b.com"


def test_authorization_url_omits_login_hint_by_default(tmp_path):
    params = _params(
        authorization_url(_config(tmp_path), state="s", code_challenge="c")
    )
    assert "login_hint" not in params


# --- token ---


def test_token_from_response_computes_expiry():
    token = token_from_response({"access_token": "a", "expires_in": 3600})
    assert token.access_token == "a"
    assert token.expires_at > time.time() + 3000


def test_token_from_response_keeps_previous_refresh_token():
    """Google không trả lại refresh_token khi làm mới; phải giữ token cũ.

    Nếu quên, lần chạy sau sẽ mất quyền và người dùng phải đăng nhập lại.
    """
    token = token_from_response(
        {"access_token": "moi", "expires_in": 3600}, previous="cu"
    )
    assert token.refresh_token == "cu"


def test_token_from_response_prefers_new_refresh_token():
    token = token_from_response(
        {"access_token": "a", "refresh_token": "moi"}, previous="cu"
    )
    assert token.refresh_token == "moi"


def test_token_from_response_handles_garbage_expires_in():
    token = token_from_response({"access_token": "a", "expires_in": "không phải số"})
    assert token.expires_at == 0.0


def test_token_without_expiry_never_expires():
    assert TokenSet(access_token="a").expired is False


def test_token_expiry_respects_skew():
    """Token còn 30s cũng phải coi là hết hạn (làm mới sớm cho an toàn)."""
    soon = TokenSet(access_token="a", expires_at=time.time() + 30)
    assert soon.expired is True

    later = TokenSet(access_token="a", expires_at=time.time() + 600)
    assert later.expired is False


def test_token_authorization_header():
    header = TokenSet(access_token="abc", token_type="Bearer").authorization_header()
    assert header == {"Authorization": "Bearer abc"}


def test_token_can_refresh_requires_refresh_token():
    assert TokenSet(access_token="a").can_refresh is False
    assert TokenSet(access_token="a", refresh_token="r").can_refresh is True


# --- lưu token ---


def test_save_and_load_token_roundtrip(tmp_path):
    path = tmp_path / "sub" / "token.json"
    original = TokenSet(
        access_token="a", refresh_token="r", expires_at=123.0, scope="s"
    )
    save_token(original, path)
    loaded = load_token(path)
    assert loaded is not None
    assert loaded.access_token == "a"
    assert loaded.refresh_token == "r"
    assert loaded.expires_at == 123.0


def test_save_token_creates_parent_directory(tmp_path):
    path = tmp_path / "a" / "b" / "token.json"
    save_token(TokenSet(access_token="a"), path)
    assert path.exists()


def test_load_token_missing_file_returns_none(tmp_path):
    assert load_token(tmp_path / "khong-co.json") is None


def test_load_token_corrupt_file_returns_none(tmp_path):
    """File hỏng phải coi như chưa đăng nhập, không làm sập ứng dụng."""
    path = tmp_path / "token.json"
    path.write_text("{ không phải json", encoding="utf-8")
    assert load_token(path) is None


def test_load_token_missing_required_field_returns_none(tmp_path):
    path = tmp_path / "token.json"
    path.write_text(json.dumps({"refresh_token": "r"}), encoding="utf-8")
    assert load_token(path) is None


def test_token_file_is_not_world_readable(tmp_path):
    """Trên POSIX, token phải là 600. Trên Windows chmod gần như không tác dụng."""
    import os
    import stat

    if os.name == "nt":
        pytest.skip("Windows không thực thi bit quyền kiểu POSIX")
    path = tmp_path / "token.json"
    save_token(TokenSet(access_token="a"), path)
    mode = stat.S_IMODE(path.stat().st_mode)
    assert mode == 0o600


# --- phiên OAuth ---


def test_session_load_reads_token_from_disk(tmp_path):
    config = _config(tmp_path)
    save_token(TokenSet(access_token="a"), config.token_file)
    session = OAuthSession.load(config, transport=FakeTransport())
    assert session.connected is True
    assert session.token.access_token == "a"


def test_session_load_without_file_is_not_connected(tmp_path):
    session = OAuthSession.load(_config(tmp_path), transport=FakeTransport())
    assert session.connected is False


def test_access_token_raises_when_not_logged_in(tmp_path):
    session = _session(tmp_path, FakeTransport())
    with pytest.raises(GoogleCalendarError, match="Chưa đăng nhập"):
        session.access_token()


def test_access_token_returns_valid_token_without_refresh(tmp_path):
    transport = FakeTransport()
    session = _session(tmp_path, transport)
    session.token = TokenSet(access_token="tot", expires_at=time.time() + 3600)
    assert session.access_token() == "tot"
    assert transport.calls == []


def test_access_token_refreshes_when_expired(tmp_path):
    transport = FakeTransport(
        handler=lambda **_kw: {"access_token": "moi", "expires_in": 3600}
    )
    session = _session(tmp_path, transport)
    session.token = TokenSet(
        access_token="cu", refresh_token="r", expires_at=time.time() - 1
    )
    assert session.access_token() == "moi"
    assert len(transport.calls) == 1
    assert transport.calls[0]["url"] == TOKEN_ENDPOINT


def test_refresh_sends_refresh_token_grant(tmp_path):
    transport = FakeTransport(
        handler=lambda **_kw: {"access_token": "moi", "expires_in": 3600}
    )
    session = _session(tmp_path, transport)
    session.token = TokenSet(access_token="cu", refresh_token="r")
    session.refresh()
    form = transport.calls[0]["form"]
    assert form["grant_type"] == "refresh_token"
    assert form["refresh_token"] == "r"
    assert form["client_id"] == "test.apps.googleusercontent.com"


def test_refresh_without_refresh_token_raises(tmp_path):
    session = _session(tmp_path, FakeTransport())
    session.token = TokenSet(access_token="cu")
    with pytest.raises(GoogleCalendarError, match="refresh token"):
        session.refresh()


def test_refresh_persists_new_token(tmp_path):
    transport = FakeTransport(
        handler=lambda **_kw: {"access_token": "moi", "expires_in": 3600}
    )
    config = _config(tmp_path)
    session = OAuthSession(config, transport=transport)
    session.token = TokenSet(access_token="cu", refresh_token="r")
    session.refresh()
    assert load_token(config.token_file).access_token == "moi"


def test_exchange_code_sends_verifier_and_redirect(tmp_path):
    transport = FakeTransport(
        handler=lambda **_kw: {
            "access_token": "a",
            "refresh_token": "r",
            "expires_in": 3600,
        }
    )
    session = _session(tmp_path, transport)
    session.exchange_code("ma-uy-quyen", "verifier-abc")
    form = transport.calls[0]["form"]
    assert form["code"] == "ma-uy-quyen"
    assert form["code_verifier"] == "verifier-abc"
    assert form["grant_type"] == "authorization_code"
    assert form["redirect_uri"] == "http://localhost:8765/"


def test_exchange_code_saves_token(tmp_path):
    transport = FakeTransport(
        handler=lambda **_kw: {"access_token": "a", "refresh_token": "r"}
    )
    config = _config(tmp_path)
    OAuthSession(config, transport=transport).exchange_code("c", "v")
    assert load_token(config.token_file).refresh_token == "r"


def test_client_secret_is_omitted_when_empty(tmp_path):
    """Ứng dụng desktop dùng PKCE nên có thể không cần client_secret."""
    transport = FakeTransport(handler=lambda **_kw: {"access_token": "a"})
    session = _session(tmp_path, transport, client_secret="")
    session.exchange_code("c", "v")
    assert "client_secret" not in transport.calls[0]["form"]


def test_authorize_rejects_mismatched_state(tmp_path, monkeypatch):
    """`state` lệch nghĩa là phản hồi không do phiên này phát ra."""
    import lifeos.tools.google_calendar as module

    monkeypatch.setattr(
        module, "wait_for_code", lambda *a, **k: ("code", "state-cua-ke-tan-cong")
    )
    session = _session(tmp_path, FakeTransport())
    with pytest.raises(GoogleCalendarError, match="state"):
        session.authorize()


def test_authorize_happy_path(tmp_path, monkeypatch):
    import lifeos.tools.google_calendar as module

    seen: dict = {}

    def fake_wait(port, *, timeout, open_url, browser):
        seen["url"] = open_url
        seen["port"] = port
        return "ma-uy-quyen", _params(open_url)["state"]

    monkeypatch.setattr(module, "wait_for_code", fake_wait)
    transport = FakeTransport(
        handler=lambda **_kw: {"access_token": "a", "refresh_token": "r"}
    )
    session = _session(tmp_path, transport)
    token = session.authorize()

    assert token.access_token == "a"
    assert seen["port"] == 8765
    assert "code_challenge" in _params(seen["url"])


def test_authorize_opens_the_browser(tmp_path, monkeypatch):
    import lifeos.tools.google_calendar as module

    opened: list[str] = []
    monkeypatch.setattr(
        module,
        "wait_for_code",
        lambda port, *, timeout, open_url, browser: (
            opened.append(open_url) or ("c", _params(open_url)["state"])
        ),
    )
    transport = FakeTransport(handler=lambda **_kw: {"access_token": "a"})
    _session(tmp_path, transport).authorize(browser=lambda url: None)
    assert opened and opened[0].startswith("https://accounts.google.com/")


# --- server nhận chuyển hướng (localhost thật) ---


def _get(url: str) -> str:
    with urllib.request.urlopen(url, timeout=5) as response:
        return response.read().decode("utf-8")


def test_wait_for_code_captures_code_and_state():
    port = _free_port()
    result: dict = {}

    def run():
        result["value"] = wait_for_code(port, timeout=10.0)

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    time.sleep(0.3)  # để server kịp mở cổng

    body = _get(f"http://127.0.0.1:{port}/?code=abc&state=xyz")
    thread.join(timeout=5)

    assert result["value"] == ("abc", "xyz")
    assert "Đã kết nối" in body


def test_wait_for_code_reports_denial():
    port = _free_port()
    result: dict = {}

    def run():
        try:
            wait_for_code(port, timeout=10.0)
        except GoogleCalendarError as exc:
            result["error"] = str(exc)

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    time.sleep(0.3)
    _get(f"http://127.0.0.1:{port}/?error=access_denied")
    thread.join(timeout=5)

    assert "access_denied" in result.get("error", "")


def test_wait_for_code_times_out():
    port = _free_port()
    started = time.perf_counter()
    with pytest.raises(GoogleCalendarError, match="Hết"):
        wait_for_code(port, timeout=0.4)
    assert time.perf_counter() - started < 5.0


def test_wait_for_code_ignores_unrelated_requests():
    """Trình duyệt hay hỏi thêm /favicon.ico — không được coi là mã uỷ quyền."""
    port = _free_port()
    result: dict = {}

    def run():
        result["value"] = wait_for_code(port, timeout=10.0)

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    time.sleep(0.3)
    _get(f"http://127.0.0.1:{port}/favicon.ico")
    _get(f"http://127.0.0.1:{port}/?code=that&state=s1")
    thread.join(timeout=5)

    assert result["value"] == ("that", "s1")


def test_wait_for_code_reports_busy_port():
    port = _free_port()
    blocker = socket.socket()
    blocker.bind(("127.0.0.1", port))
    blocker.listen(1)
    try:
        with pytest.raises(GoogleCalendarError, match="cổng"):
            wait_for_code(port, timeout=0.2)
    finally:
        blocker.close()


def test_wait_for_code_opens_browser_with_url():
    port = _free_port()
    opened: list[str] = []
    thread = threading.Thread(
        target=lambda: wait_for_code(
            port, timeout=10.0, open_url="https://x/y", browser=opened.append
        ),
        daemon=True,
    )
    thread.start()
    time.sleep(0.3)
    _get(f"http://127.0.0.1:{port}/?code=c&state=s")
    thread.join(timeout=5)
    assert opened == ["https://x/y"]


# --- chuyển lịch thành sự kiện (hàm thuần) ---


def test_event_key_is_deterministic():
    task = ScheduleTask(id="a1", title="Học SQL", day="Mon", start="20:00")
    assert event_key(task, 1) == event_key(task, 1)
    assert event_key(task, 1) == "w1-a1-Mon-2000"


def test_event_key_differs_per_week():
    task = ScheduleTask(id="a1", title="Học SQL", day="Mon", start="20:00")
    assert event_key(task, 1) != event_key(task, 2)


def test_event_key_falls_back_to_title_slug():
    """`ScheduleTask.id` có thể rỗng, khi đó khoá phải dựa vào tiêu đề."""
    task = ScheduleTask(title="Ôn tập SQL", day="Sat", start="09:00")
    key = event_key(task, 3)
    assert key.startswith("w3-")
    assert "on-tap-sql" in key
    assert "Sat" in key


def test_event_key_strips_vietnamese_diacritics():
    task = ScheduleTask(title="Đọc tài liệu", day="Wed", start="19:30")
    assert "doc-tai-lieu" in event_key(task, 1)


def test_event_key_handles_empty_title():
    task = ScheduleTask(title="", day="Mon", start="20:00")
    assert event_key(task, 1)  # không được rỗng


def test_events_from_weeks_counts_every_session():
    events = events_from_weeks(_weeks(), start_date=MONDAY)
    assert len(events) == 3  # 2 buổi tuần 1 + 1 buổi tuần 2


def test_events_from_weeks_sets_datetimes_and_timezone():
    events = events_from_weeks(_weeks(), start_date=MONDAY)
    first = events[0]
    assert first["start"]["dateTime"] == "2025-01-06T20:00:00"
    assert first["end"]["dateTime"] == "2025-01-06T21:30:00"
    assert first["start"]["timeZone"] == DEFAULT_TIME_ZONE


def test_events_from_weeks_places_saturday_correctly():
    events = events_from_weeks(_weeks(), start_date=MONDAY)
    saturday = events[1]
    assert saturday["start"]["dateTime"].startswith("2025-01-11")


def test_events_from_weeks_second_week_is_seven_days_later():
    events = events_from_weeks(_weeks(), start_date=MONDAY)
    assert events[2]["start"]["dateTime"] == "2025-01-13T20:00:00"


def test_events_from_weeks_marks_missed_in_summary():
    """Buổi đã trượt phải nhìn thấy được ngay trên tiêu đề."""
    weeks = [
        WeeklySchedule(
            week=1,
            tasks=[
                ScheduleTask(
                    id="m1",
                    title="Ôn tập",
                    day="Sat",
                    start="09:00",
                    status=TaskStatus.MISSED,
                )
            ],
        )
    ]
    event = events_from_weeks(weeks, start_date=MONDAY)[0]
    assert event["summary"].startswith("[Đã trượt]")
    assert event["extendedProperties"]["private"]["lifeos_status"] == "missed"


def test_events_from_weeks_does_not_set_status_field():
    """`events.insert` bỏ qua `status`, nên đừng dựa vào nó để đánh dấu.

    Nếu đặt `status: cancelled` mà Google bỏ qua thì người dùng thấy buổi đã
    trượt y như buổi bình thường — tệ hơn là không đánh dấu gì.
    """
    weeks = [
        WeeklySchedule(
            week=1,
            tasks=[
                ScheduleTask(
                    id="m1", title="x", day="Mon", start="20:00", status=TaskStatus.MISSED
                )
            ],
        )
    ]
    assert "status" not in events_from_weeks(weeks, start_date=MONDAY)[0]


def test_events_from_weeks_embeds_the_key():
    events = events_from_weeks(_weeks(), start_date=MONDAY)
    private = events[0]["extendedProperties"]["private"]
    assert private[EVENT_KEY_PROPERTY] == "w1-a1-Mon-2000"
    assert private["lifeos_week"] == "1"


def test_events_from_weeks_description_has_context():
    events = events_from_weeks(_weeks(), start_date=MONDAY)
    description = events[0]["description"]
    assert "Tuần 1" in description
    assert "study" in description


def test_events_from_weeks_includes_module_and_notes():
    weeks = [
        WeeklySchedule(
            week=1,
            tasks=[
                ScheduleTask(
                    id="a",
                    title="x",
                    day="Mon",
                    start="20:00",
                    module_ref="SQL nền tảng",
                    notes="Mang laptop",
                )
            ],
        )
    ]
    description = events_from_weeks(weeks, start_date=MONDAY)[0]["description"]
    assert "SQL nền tảng" in description
    assert "Mang laptop" in description


def test_events_from_weeks_is_pure():
    """Gọi hai lần phải cho kết quả y hệt — không phụ thuộc ngày chạy."""
    weeks = _weeks()
    assert events_from_weeks(weeks, start_date=MONDAY) == events_from_weeks(
        weeks, start_date=MONDAY
    )


def test_events_from_weeks_empty_schedule():
    assert events_from_weeks([], start_date=MONDAY) == []


def test_events_from_weeks_accepts_custom_timezone():
    events = events_from_weeks(
        _weeks(), start_date=MONDAY, time_zone="Europe/Paris"
    )
    assert events[0]["start"]["timeZone"] == "Europe/Paris"


# --- client ---


def _client(tmp_path, api=None, transport=None) -> tuple[GoogleCalendarClient, FakeTransport]:
    fake = transport or FakeTransport(handler=api or FakeCalendarAPI())
    session = OAuthSession(
        _config(tmp_path),
        TokenSet(access_token="tok", expires_at=time.time() + 3600),
        transport=fake,
    )
    return GoogleCalendarClient(session, transport=fake), fake


def test_client_sends_authorization_header(tmp_path):
    client, transport = _client(tmp_path)
    client.sync_weeks(_weeks(), start_date=MONDAY)
    assert transport.calls[0]["headers"]["Authorization"] == "Bearer tok"


def test_find_by_key_queries_private_property(tmp_path):
    api = FakeCalendarAPI()
    client, transport = _client(tmp_path, api=api)
    client.find_by_key("w1-a1-Mon-2000")
    query = urllib.parse.parse_qs(
        urllib.parse.urlparse(transport.calls[0]["url"]).query
    )
    assert query["privateExtendedProperty"] == ["lifeos_key=w1-a1-Mon-2000"]


def test_find_by_key_returns_none_when_absent(tmp_path):
    client, _transport = _client(tmp_path)
    assert client.find_by_key("khong-co") is None


def test_sync_creates_events_first_time(tmp_path):
    api = FakeCalendarAPI()
    client, _transport = _client(tmp_path, api=api)
    report = client.sync_weeks(_weeks(), start_date=MONDAY)
    assert report.created == 3
    assert report.updated == 0
    assert report.failed == 0
    assert len(api.events) == 3


def test_sync_is_idempotent(tmp_path):
    """Chạy lại lần hai không được tạo sự kiện trùng."""
    api = FakeCalendarAPI()
    client, _transport = _client(tmp_path, api=api)
    client.sync_weeks(_weeks(), start_date=MONDAY)
    report = client.sync_weeks(_weeks(), start_date=MONDAY)

    assert report.created == 0
    assert report.skipped == 3
    assert len(api.events) == 3  # vẫn đúng 3, không nhân đôi


def test_sync_updates_when_content_changes(tmp_path):
    api = FakeCalendarAPI()
    client, _transport = _client(tmp_path, api=api)
    client.sync_weeks(_weeks(), start_date=MONDAY)

    changed = _weeks()
    changed[0].tasks[0].title = "Học SQL nâng cao"
    report = client.sync_weeks(changed, start_date=MONDAY)

    assert report.updated == 1
    assert report.skipped == 2
    assert len(api.events) == 3


def test_sync_reports_summary(tmp_path):
    client, _transport = _client(tmp_path)
    report = client.sync_weeks(_weeks(), start_date=MONDAY)
    assert "3 tạo mới" in report.summary()
    assert report.ok is True
    assert report.total == 3


def test_dry_run_makes_no_network_calls(tmp_path):
    client, transport = _client(tmp_path)
    report = client.sync_weeks(_weeks(), start_date=MONDAY, dry_run=True)
    assert report.skipped == 3
    assert transport.calls == []


def test_one_failure_does_not_stop_the_sync(tmp_path):
    """Một buổi lỗi thì các buổi còn lại vẫn phải được đồng bộ."""
    api = FakeCalendarAPI()
    calls = {"n": 0}

    def handler(**kwargs):
        # Cho lời gọi POST đầu tiên thất bại
        if kwargs["method"] == "POST":
            calls["n"] += 1
            if calls["n"] == 1:
                raise GoogleCalendarError("HTTP 500 từ Google", status=500)
        return api(**kwargs)

    client, _transport = _client(tmp_path, transport=FakeTransport(handler=handler))
    report = client.sync_weeks(_weeks(), start_date=MONDAY)

    assert report.failed == 1
    assert report.created == 2
    assert report.ok is False
    assert "HTTP 500" in report.errors[0]


def test_upsert_skips_unchanged_event(tmp_path):
    api = FakeCalendarAPI()
    client, transport = _client(tmp_path, api=api)
    payload = events_from_weeks(_weeks(), start_date=MONDAY)[0]

    action, event_id = client.upsert_event(payload)
    assert action == "created"

    before = len(transport.calls)
    action, second_id = client.upsert_event(payload)
    assert action == "skipped"
    assert second_id == event_id
    # GET tìm kiếm + GET chi tiết, không có POST/PATCH
    assert transport.methods[before:] == ["GET", "GET"]


def test_upsert_patches_changed_event(tmp_path):
    api = FakeCalendarAPI()
    client, transport = _client(tmp_path, api=api)
    payload = events_from_weeks(_weeks(), start_date=MONDAY)[0]
    client.upsert_event(payload)

    payload["summary"] = "Tên khác"
    action, _event_id = client.upsert_event(payload)

    assert action == "updated"
    assert "PATCH" in transport.methods


def test_unchanged_detects_description_difference():
    payload = {"summary": "a", "description": "x", "start": {}, "end": {}}
    assert GoogleCalendarClient._unchanged(dict(payload), payload) is True

    other = dict(payload, description="y")
    assert GoogleCalendarClient._unchanged(other, payload) is False


def test_unchanged_detects_time_difference():
    payload = {
        "summary": "a",
        "description": "d",
        "start": {"dateTime": "2025-01-06T20:00:00"},
        "end": {"dateTime": "2025-01-06T21:30:00"},
    }
    moved = dict(
        payload,
        start={"dateTime": "2025-01-06T21:00:00"},
    )
    assert GoogleCalendarClient._unchanged(moved, payload) is False


def test_unchanged_ignores_missing_description():
    payload = {"summary": "a", "start": {}, "end": {}}
    assert GoogleCalendarClient._unchanged({"summary": "a"}, payload) is True


def test_calendar_id_is_url_quoted(tmp_path):
    fake = FakeTransport(handler=FakeCalendarAPI())
    session = OAuthSession(
        _config(tmp_path),
        TokenSet(access_token="t", expires_at=time.time() + 3600),
        transport=fake,
    )
    client = GoogleCalendarClient(session, calendar_id="a@b.com", transport=fake)
    client.find_by_key("k")
    assert "a%40b.com" in fake.calls[0]["url"]


def test_calendar_api_base_url_is_used(tmp_path):
    client, transport = _client(tmp_path)
    client.sync_weeks(_weeks(), start_date=MONDAY)
    assert transport.calls[0]["url"].startswith(CALENDAR_API)


def test_client_uses_session_transport_by_default(tmp_path):
    fake = FakeTransport(handler=FakeCalendarAPI())
    session = OAuthSession(
        _config(tmp_path),
        TokenSet(access_token="t", expires_at=time.time() + 3600),
        transport=fake,
    )
    GoogleCalendarClient(session).sync_weeks(_weeks(), start_date=MONDAY)
    assert fake.calls


# --- transport thật ---


def test_urllib_transport_wraps_http_error():
    """Lỗi HTTP phải thành `GoogleCalendarError` có mã trạng thái."""
    transport = UrllibTransport()
    with pytest.raises(GoogleCalendarError) as excinfo:
        transport.request("GET", "http://127.0.0.1:1/khong-co", timeout=2.0)
    assert excinfo.value.status is None or excinfo.value.status >= 400


def test_urllib_transport_reports_unreachable_host():
    transport = UrllibTransport()
    with pytest.raises(GoogleCalendarError):
        transport.request("GET", "http://127.0.0.1:9/khong-co", timeout=1.0)


# --- ghép với Settings ---


def test_config_from_settings_reads_env_fields():
    from lifeos.config import Settings
    from lifeos.tools.google_calendar import config_from_settings

    settings = Settings(
        google_client_id="id.apps.googleusercontent.com",
        google_client_secret="sec",
        google_redirect_port=9999,
        google_token_path="data/khac.json",
    )
    config = config_from_settings(settings)
    assert config.client_id == "id.apps.googleusercontent.com"
    assert config.redirect_uri == "http://localhost:9999/"
    assert config.token_file.name == "khac.json"


def test_settings_reports_not_configured_by_default():
    from lifeos.config import Settings

    assert Settings(google_client_id="").google_configured is False
    assert Settings(google_client_id="x").google_configured is True


def test_build_client_without_client_id_raises(tmp_path):
    from lifeos.tools.google_calendar import build_client

    with pytest.raises(GoogleCalendarError, match="GOOGLE_CLIENT_ID"):
        build_client(_config(tmp_path, client_id=""), interactive=False)


def test_build_client_non_interactive_without_token_raises(tmp_path):
    from lifeos.tools.google_calendar import build_client

    with pytest.raises(GoogleCalendarError, match="uỷ quyền"):
        build_client(_config(tmp_path), interactive=False, transport=FakeTransport())


def test_build_client_uses_saved_token_without_browser(tmp_path):
    """Có token sẵn thì không được mở trình duyệt."""
    from lifeos.tools.google_calendar import build_client

    config = _config(tmp_path)
    save_token(TokenSet(access_token="a"), config.token_file)
    opened: list[str] = []
    fake = FakeTransport(handler=FakeCalendarAPI())
    client = build_client(
        config,
        transport=fake,
        browser=opened.append,
    )
    assert opened == []
    client.sync_weeks(_weeks(), start_date=MONDAY)
    assert fake.calls


def test_build_client_authorizes_when_no_token(tmp_path, monkeypatch):
    import lifeos.tools.google_calendar as module
    from lifeos.tools.google_calendar import build_client

    monkeypatch.setattr(
        module,
        "wait_for_code",
        lambda port, *, timeout, open_url, browser: (
            "code",
            _params(open_url)["state"],
        ),
    )
    config = _config(tmp_path)
    fake = FakeTransport(
        handler=lambda method, url, **kw: (
            {"access_token": "a", "refresh_token": "r", "expires_in": 3600}
            if url == TOKEN_ENDPOINT
            else FakeCalendarAPI()(method, url, **kw)
        )
    )
    build_client(config, transport=fake, browser=lambda url: None)
    assert load_token(config.token_file).refresh_token == "r"


def test_build_client_passes_calendar_id_and_timezone(tmp_path):
    from lifeos.tools.google_calendar import build_client

    config = _config(tmp_path)
    save_token(TokenSet(access_token="a"), config.token_file)
    fake = FakeTransport(handler=FakeCalendarAPI())
    client = build_client(
        config,
        calendar_id="a@b.com",
        time_zone="Europe/Paris",
        transport=fake,
    )
    assert client.calendar_id == "a@b.com"
    assert client.time_zone == "Europe/Paris"
