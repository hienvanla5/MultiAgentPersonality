"""Đồng bộ lịch học lên Google Calendar qua OAuth 2.0.

Trước đây hệ thống chỉ xuất được file `.ics` để người dùng tự import tay. Ở đây
làm nốt phần còn thiếu: xin quyền qua OAuth 2.0 rồi gọi thẳng Google Calendar API.

**Không thêm thư viện.** Luồng OAuth cho ứng dụng cài đặt (authorization code +
PKCE) chỉ cần vài request HTTP và một HTTP server nhỏ — tất cả đều có trong thư
viện chuẩn. Đổi lại là không phải kéo thêm vài chục MB phụ thuộc của Google, và
toàn bộ luồng kiểm thử được mà không cần mạng.

Ba phần, tách bạch có chủ ý:

1. `events_from_weeks()` — **hàm thuần**: lịch nhiều tuần → payload sự kiện.
   Phần này chứa nhiều lỗi tiềm ẩn nhất (thứ trong tuần, múi giờ, trạng thái) nên
   được tách hẳn khỏi phần mạng để kiểm thử không cần credentials.
2. `OAuthSession` — xin token, làm mới token khi hết hạn.
3. `GoogleCalendarClient` — đồng bộ lên lịch, **idempotent**: mỗi buổi học mang
   một khoá `lifeos_key` trong `extendedProperties.private`, nên chạy lại nhiều
   lần cập nhật đúng sự kiện cũ thay vì tạo trùng.

Mọi lời gọi mạng đi qua `Transport` (mặc định `UrllibTransport`). Test thay bằng
transport giả nên không cần credentials thật và không chạm mạng.
"""

from __future__ import annotations

import base64
import contextlib
import hashlib
import json
import os
import secrets
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from dataclasses import dataclass, field
from datetime import date
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any, Protocol

from pydantic import BaseModel

from ..models import TaskStatus, WeeklySchedule
from .calendar import task_datetimes

# --- hằng số ---

AUTHORIZATION_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
CALENDAR_API = "https://www.googleapis.com/calendar/v3"

#: Chỉ xin quyền trên sự kiện, không xin quyền đọc toàn bộ lịch.
#: Nguyên tắc quyền tối thiểu: đồng bộ lịch học không cần biết người dùng có
#: những cuộc hẹn nào khác.
SCOPES = ("https://www.googleapis.com/auth/calendar.events",)

DEFAULT_REDIRECT_PORT = 8765
DEFAULT_TIME_ZONE = "Asia/Ho_Chi_Minh"
DEFAULT_TOKEN_PATH = "data/google_token.json"

#: Làm mới token sớm hơn hạn thật một chút, tránh dùng token vừa hết hạn.
EXPIRY_SKEW_S = 60.0

#: Tiền tố khoá nhận dạng sự kiện do Life OS tạo.
EVENT_KEY_PROPERTY = "lifeos_key"


class GoogleCalendarError(RuntimeError):
    """Lỗi khi làm việc với Google Calendar."""

    def __init__(self, message: str, *, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


# --- model ---


class TokenSet(BaseModel):
    """Token OAuth và hạn của nó."""

    access_token: str
    refresh_token: str = ""
    token_type: str = "Bearer"
    scope: str = ""
    expires_at: float = 0.0

    @property
    def expired(self) -> bool:
        if self.expires_at <= 0:
            return False
        return time.time() >= self.expires_at - EXPIRY_SKEW_S

    @property
    def can_refresh(self) -> bool:
        return bool(self.refresh_token)

    def authorization_header(self) -> dict[str, str]:
        return {"Authorization": f"{self.token_type} {self.access_token}"}


class OAuthConfig(BaseModel):
    """Cấu hình OAuth của ứng dụng cài đặt."""

    client_id: str
    client_secret: str = ""
    redirect_port: int = DEFAULT_REDIRECT_PORT
    scopes: tuple[str, ...] = SCOPES
    token_path: str = DEFAULT_TOKEN_PATH

    @property
    def redirect_uri(self) -> str:
        return f"http://localhost:{self.redirect_port}/"

    @property
    def token_file(self) -> Path:
        return Path(self.token_path)


@dataclass
class SyncReport:
    """Kết quả một lần đồng bộ."""

    created: int = 0
    updated: int = 0
    skipped: int = 0
    failed: int = 0
    errors: list[str] = field(default_factory=list)

    @property
    def total(self) -> int:
        return self.created + self.updated + self.skipped + self.failed

    @property
    def ok(self) -> bool:
        return self.failed == 0

    def summary(self) -> str:
        return (
            f"Đã đồng bộ {self.total} buổi: {self.created} tạo mới, "
            f"{self.updated} cập nhật, {self.skipped} không đổi, {self.failed} lỗi."
        )


# --- PKCE ---


def _b64url(raw: bytes) -> str:
    """Base64url không đệm, đúng chuẩn RFC 7636."""
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def pkce_pair() -> tuple[str, str]:
    """Sinh cặp (code_verifier, code_challenge) cho PKCE.

    PKCE chặn kẻ nghe lén mã uỷ quyền trên máy cục bộ: mã uỷ quyền chỉ đổi được
    thành token nếu kèm đúng `code_verifier` mà chỉ tiến trình này biết.
    """
    verifier = _b64url(secrets.token_bytes(64))
    challenge = _b64url(hashlib.sha256(verifier.encode("ascii")).digest())
    return verifier, challenge


def authorization_url(
    config: OAuthConfig,
    *,
    state: str,
    code_challenge: str,
    login_hint: str = "",
) -> str:
    """Dựng URL trang đồng ý của Google."""
    params = {
        "client_id": config.client_id,
        "redirect_uri": config.redirect_uri,
        "response_type": "code",
        "scope": " ".join(config.scopes),
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
        "access_type": "offline",  # cần refresh_token để chạy lại không hỏi nữa
        "prompt": "consent",
    }
    if login_hint:
        params["login_hint"] = login_hint
    return f"{AUTHORIZATION_ENDPOINT}?{urllib.parse.urlencode(params)}"


# --- tầng mạng ---


class Transport(Protocol):
    """Giao diện tối thiểu để gọi HTTP, tách ra cho test thay được."""

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        json_body: dict[str, Any] | None = None,
        form: dict[str, str] | None = None,
        timeout: float = 30.0,
    ) -> dict[str, Any]:
        ...


class UrllibTransport:
    """Transport thật, dùng urllib của thư viện chuẩn."""

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        json_body: dict[str, Any] | None = None,
        form: dict[str, str] | None = None,
        timeout: float = 30.0,
    ) -> dict[str, Any]:
        body: bytes | None = None
        final_headers = dict(headers or {})

        if json_body is not None:
            body = json.dumps(json_body).encode("utf-8")
            final_headers.setdefault("Content-Type", "application/json")
        elif form is not None:
            body = urllib.parse.urlencode(form).encode("utf-8")
            final_headers.setdefault(
                "Content-Type", "application/x-www-form-urlencoded"
            )

        request = urllib.request.Request(
            url, data=body, headers=final_headers, method=method.upper()
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                raw = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise GoogleCalendarError(
                f"HTTP {exc.code} từ {url}: {detail[:500]}", status=exc.code
            ) from exc
        except urllib.error.URLError as exc:
            raise GoogleCalendarError(f"Không gọi được {url}: {exc.reason}") from exc

        if not raw.strip():
            return {}
        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            raise GoogleCalendarError(
                f"Phản hồi không phải JSON từ {url}: {raw[:200]}"
            ) from exc


# --- lưu token ---


def token_from_response(payload: dict[str, Any], *, previous: str = "") -> TokenSet:
    """Dựng `TokenSet` từ phản hồi của endpoint token.

    Google **không** trả lại `refresh_token` trong các lần làm mới sau, nên phải
    giữ lại token cũ; nếu không, lần chạy kế tiếp sẽ mất quyền truy cập và người
    dùng phải đăng nhập lại.
    """
    expires_in = payload.get("expires_in")
    try:
        expires_at = time.time() + float(expires_in) if expires_in else 0.0
    except (TypeError, ValueError):
        expires_at = 0.0

    return TokenSet(
        access_token=str(payload.get("access_token", "")),
        refresh_token=str(payload.get("refresh_token") or previous or ""),
        token_type=str(payload.get("token_type") or "Bearer"),
        scope=str(payload.get("scope") or ""),
        expires_at=expires_at,
    )


def save_token(token: TokenSet, path: str | Path) -> Path:
    """Ghi token xuống đĩa với quyền hạn chế.

    File chứa `refresh_token` — tức là quyền truy cập lịch về sau mà không cần
    đăng nhập lại. Đặt quyền 600 để trên máy nhiều người dùng, người khác không
    đọc được. Trên Windows `chmod` gần như không có tác dụng, nên đây là lớp
    phòng vệ thêm chứ không phải bảo đảm duy nhất — lớp chính là để file này
    nằm trong `data/` đã bị `.gitignore` chặn.
    """
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(token.model_dump_json(indent=2), encoding="utf-8")
    with contextlib.suppress(OSError):  # pragma: no cover - tuỳ hệ điều hành
        os.chmod(target, 0o600)
    return target


def load_token(path: str | Path) -> TokenSet | None:
    """Đọc token đã lưu. Trả về None nếu chưa có hoặc file hỏng."""
    target = Path(path)
    if not target.exists():
        return None
    try:
        return TokenSet.model_validate_json(target.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 - file hỏng coi như chưa đăng nhập
        return None


# --- vòng lặp OAuth ---


def wait_for_code(
    port: int,
    *,
    timeout: float = 300.0,
    open_url: str = "",
    browser=webbrowser.open,
) -> tuple[str, str]:
    """Mở trình duyệt và chờ Google chuyển hướng về `localhost:port`.

    Trả về `(code, state)`. Ném `GoogleCalendarError` nếu người dùng từ chối,
    hết thời gian chờ, hoặc cổng đang bị chiếm.

    Handler được tạo riêng cho từng lần gọi (không dùng biến lớp dùng chung):
    nếu để trạng thái ở mức lớp thì hai lần uỷ quyền chạy song song sẽ ghi đè
    kết quả của nhau, và rất khó lần ra khi gỡ lỗi.
    """
    captured: dict[str, str] = {}

    class _Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            captured.update(
                {key: values[0] for key, values in query.items() if values}
            )
            body = (
                "<html><head><meta charset='utf-8'><title>Life OS</title></head>"
                "<body style='font-family:sans-serif;padding:2rem'>"
                "<h2>Đã kết nối Google Calendar</h2>"
                "<p>Bạn có thể đóng tab này và quay lại Life OS.</p>"
                "</body></html>"
            ).encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_args) -> None:
            """Tắt log mặc định để không làm bẩn stdout của CLI."""

    try:
        server = HTTPServer(("127.0.0.1", port), _Handler)
    except OSError as exc:
        raise GoogleCalendarError(
            f"Không mở được cổng {port} để nhận chuyển hướng: {exc}. "
            "Đổi GOOGLE_REDIRECT_PORT hoặc tắt ứng dụng đang dùng cổng đó."
        ) from exc

    if open_url:
        browser(open_url)

    deadline = time.monotonic() + timeout
    try:
        while time.monotonic() < deadline:
            server.timeout = max(0.1, deadline - time.monotonic())
            server.handle_request()
            if "error" in captured:
                raise GoogleCalendarError(
                    f"Google từ chối uỷ quyền: {captured['error']}"
                )
            if captured.get("code"):
                return captured["code"], captured.get("state", "")
    finally:
        server.server_close()

    raise GoogleCalendarError(
        f"Hết {timeout:.0f}s mà chưa nhận được chuyển hướng từ Google."
    )


class OAuthSession:
    """Giữ token và tự làm mới khi cần."""

    def __init__(
        self,
        config: OAuthConfig,
        token: TokenSet | None = None,
        *,
        transport: Transport | None = None,
    ) -> None:
        self.config = config
        self.token = token
        self.transport = transport or UrllibTransport()

    @classmethod
    def load(cls, config: OAuthConfig, **kwargs) -> OAuthSession:
        return cls(config, load_token(config.token_file), **kwargs)

    @property
    def connected(self) -> bool:
        return self.token is not None and bool(self.token.access_token)

    def _post_token(self, form: dict[str, str]) -> TokenSet:
        payload = self.transport.request(
            "POST", TOKEN_ENDPOINT, form=form, timeout=30.0
        )
        previous = self.token.refresh_token if self.token else ""
        return token_from_response(payload, previous=previous)

    def exchange_code(self, code: str, code_verifier: str) -> TokenSet:
        """Đổi mã uỷ quyền lấy token, rồi lưu xuống đĩa."""
        form = {
            "client_id": self.config.client_id,
            "code": code,
            "code_verifier": code_verifier,
            "grant_type": "authorization_code",
            "redirect_uri": self.config.redirect_uri,
        }
        if self.config.client_secret:
            form["client_secret"] = self.config.client_secret
        self.token = self._post_token(form)
        save_token(self.token, self.config.token_file)
        return self.token

    def refresh(self) -> TokenSet:
        """Làm mới access token bằng refresh token."""
        if self.token is None or not self.token.can_refresh:
            raise GoogleCalendarError(
                "Không có refresh token — cần đăng nhập lại bằng authorize()."
            )
        form = {
            "client_id": self.config.client_id,
            "refresh_token": self.token.refresh_token,
            "grant_type": "refresh_token",
        }
        if self.config.client_secret:
            form["client_secret"] = self.config.client_secret
        self.token = self._post_token(form)
        save_token(self.token, self.config.token_file)
        return self.token

    def access_token(self) -> str:
        """Trả về access token còn hiệu lực, tự làm mới nếu đã hết hạn."""
        if self.token is None:
            raise GoogleCalendarError(
                "Chưa đăng nhập Google. Chạy authorize() trước."
            )
        if self.token.expired:
            self.refresh()
        return self.token.access_token

    def authorize(
        self,
        *,
        timeout: float = 300.0,
        login_hint: str = "",
        browser=webbrowser.open,
    ) -> TokenSet:
        """Chạy trọn luồng uỷ quyền tương tác."""
        verifier, challenge = pkce_pair()
        state = secrets.token_urlsafe(24)
        url = authorization_url(
            self.config,
            state=state,
            code_challenge=challenge,
            login_hint=login_hint,
        )
        code, returned_state = wait_for_code(
            self.config.redirect_port,
            timeout=timeout,
            open_url=url,
            browser=browser,
        )
        if returned_state != state:
            # `state` chống tấn công CSRF: nếu không khớp thì phản hồi này không
            # phải do phiên đăng nhập của chính ta phát ra.
            raise GoogleCalendarError(
                "`state` trả về không khớp — nghi ngờ phản hồi giả mạo."
            )
        return self.exchange_code(code, verifier)


# --- chuyển lịch thành sự kiện (hàm thuần) ---


def _slug(text: str) -> str:
    """Bỏ dấu tiếng Việt và chuẩn hoá thành slug ASCII."""
    # Phải thay `đ`/`Đ` thủ công: NFD không tách được nét ngang của "Đ" (U+0110)
    # nên `encode("ascii", "ignore")` sẽ nuốt mất chữ cái đầu.
    replaced = (text or "").replace("đ", "d").replace("Đ", "D")
    ascii_text = (
        unicodedata.normalize("NFD", replaced)
        .encode("ascii", "ignore")
        .decode("ascii")
    )
    cleaned = "".join(ch if ch.isalnum() else "-" for ch in ascii_text)
    while "--" in cleaned:
        cleaned = cleaned.replace("--", "-")
    return cleaned.strip("-").lower()


def event_key(task, week: int) -> str:
    """Khoá nhận dạng ổn định cho một buổi học.

    Phải **tất định** và không phụ thuộc thời gian chạy: nếu khoá đổi giữa hai
    lần đồng bộ thì mỗi lần chạy lại sẽ tạo thêm một sự kiện trùng thay vì cập
    nhật sự kiện cũ. Vì `ScheduleTask.id` có thể rỗng, khoá dựa thêm vào tiêu đề
    và khung giờ.
    """
    parts = [
        f"w{week}",
        task.id or _slug(task.title) or "buoi",
        task.day,
        task.start.replace(":", ""),
    ]
    return "-".join(str(p) for p in parts if p)


def _description(task, week: int) -> str:
    lines = [f"Tuần {week}", f"Loại: {task.task_type.value}"]
    if task.module_ref:
        lines.append(f"Module: {task.module_ref}")
    if task.notes:
        lines.append(task.notes)
    lines.append("Tạo bởi Life OS")
    return "\n".join(lines)


def events_from_weeks(
    weeks: list[WeeklySchedule],
    *,
    start_date: date | None = None,
    time_zone: str = DEFAULT_TIME_ZONE,
) -> list[dict[str, Any]]:
    """Chuyển lịch nhiều tuần thành payload sự kiện của Google Calendar API.

    Hàm thuần: không I/O, không credentials — nên kiểm thử được toàn bộ.

    Buổi đã trượt được đánh dấu bằng tiền tố trong tiêu đề **chứ không** đặt
    `status: "cancelled"`. Lý do: `events.insert` bỏ qua trường `status` (muốn
    huỷ thì phải gọi `events.delete`), nên nếu chỉ dựa vào `status` thì người
    dùng sẽ thấy buổi đã trượt y như buổi bình thường.
    """
    events: list[dict[str, Any]] = []
    for week in weeks:
        for task in week.tasks:
            start, end = task_datetimes(task, week.week, start_date)
            missed = task.status == TaskStatus.MISSED
            summary = f"[Đã trượt] {task.title}" if missed else task.title
            events.append(
                {
                    "summary": summary,
                    "description": _description(task, week.week),
                    "start": {
                        "dateTime": start.isoformat(),
                        "timeZone": time_zone,
                    },
                    "end": {"dateTime": end.isoformat(), "timeZone": time_zone},
                    "extendedProperties": {
                        "private": {
                            EVENT_KEY_PROPERTY: event_key(task, week.week),
                            "lifeos_week": str(week.week),
                            "lifeos_status": task.status.value,
                        }
                    },
                }
            )
    return events


# --- client ---


class GoogleCalendarClient:
    """Đồng bộ lịch học lên Google Calendar."""

    def __init__(
        self,
        session: OAuthSession,
        *,
        calendar_id: str = "primary",
        transport: Transport | None = None,
        time_zone: str = DEFAULT_TIME_ZONE,
    ) -> None:
        self.session = session
        self.calendar_id = calendar_id
        self.transport = transport or session.transport
        self.time_zone = time_zone

    # --- HTTP có xác thực ---

    def _headers(self) -> dict[str, str]:
        return self.session.token.authorization_header() if self.session.token else {}

    def _call(
        self,
        method: str,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
        params: dict[str, str] | None = None,
        authenticated: bool = True,
    ) -> dict[str, Any]:
        url = f"{CALENDAR_API}{path}"
        if params:
            url = f"{url}?{urllib.parse.urlencode(params)}"
        headers = self._headers() if authenticated else {}
        return self.transport.request(
            method, url, headers=headers, json_body=json_body, timeout=30.0
        )

    def find_by_key(self, key: str) -> str | None:
        """Tìm id sự kiện đã tạo cho một buổi học (nếu có)."""
        payload = self._call(
            "GET",
            f"/calendars/{urllib.parse.quote(self.calendar_id)}/events",
            params={
                "privateExtendedProperty": f"{EVENT_KEY_PROPERTY}={key}",
                "maxResults": "1",
                "singleEvents": "true",
            },
        )
        items = payload.get("items") or []
        if not items:
            return None
        return items[0].get("id")

    def upsert_event(self, payload: dict[str, Any]) -> tuple[str, str]:
        """Tạo hoặc cập nhật một sự kiện. Trả về `(hành động, event_id)`.

        `hành động` là `"created"`, `"updated"` hoặc `"skipped"`.
        """
        key = (payload.get("extendedProperties") or {}).get("private", {}).get(
            EVENT_KEY_PROPERTY, ""
        )
        existing_id = self.find_by_key(key) if key else None
        calendar = urllib.parse.quote(self.calendar_id)

        if existing_id:
            current = self._call("GET", f"/calendars/{calendar}/events/{existing_id}")
            if self._unchanged(current, payload):
                return "skipped", existing_id
            updated = self._call(
                "PATCH",
                f"/calendars/{calendar}/events/{existing_id}",
                json_body=payload,
            )
            return "updated", updated.get("id", existing_id)

        created = self._call(
            "POST", f"/calendars/{calendar}/events", json_body=payload
        )
        return "created", created.get("id", "")

    @staticmethod
    def _unchanged(current: dict[str, Any], payload: dict[str, Any]) -> bool:
        """Sự kiện trên lịch đã giống hệt payload chưa?

        So ba trường người dùng nhìn thấy. Không so `etag`/`updated` vì Google
        đổi chúng mỗi lần ghi, kể cả khi nội dung không đổi.
        """
        if current.get("summary") != payload.get("summary"):
            return False
        if (current.get("description") or "") != (payload.get("description") or ""):
            return False
        for edge in ("start", "end"):
            current_edge = (current.get(edge) or {}).get("dateTime", "")
            payload_edge = (payload.get(edge) or {}).get("dateTime", "")
            if current_edge != payload_edge:
                return False
        return True

    def sync_weeks(
        self,
        weeks: list[WeeklySchedule],
        *,
        start_date: date | None = None,
        dry_run: bool = False,
    ) -> SyncReport:
        """Đồng bộ toàn bộ lịch. Một buổi lỗi không làm hỏng cả lượt đồng bộ."""
        events = events_from_weeks(
            weeks, start_date=start_date, time_zone=self.time_zone
        )
        report = SyncReport()

        if dry_run:
            report.skipped = len(events)
            return report

        for payload in events:
            key = (payload.get("extendedProperties") or {}).get("private", {}).get(
                EVENT_KEY_PROPERTY, "?"
            )
            try:
                action, _event_id = self.upsert_event(payload)
            except GoogleCalendarError as exc:
                report.failed += 1
                report.errors.append(f"{key}: {exc}")
                continue
            if action == "created":
                report.created += 1
            elif action == "updated":
                report.updated += 1
            else:
                report.skipped += 1
        return report


# --- ghép với cấu hình của ứng dụng ---


def config_from_settings(settings=None) -> OAuthConfig:
    """Dựng `OAuthConfig` từ `Settings` (đọc trong `.env`)."""
    from ..config import get_settings

    settings = settings or get_settings()
    return OAuthConfig(
        client_id=settings.google_client_id,
        client_secret=settings.google_client_secret,
        redirect_port=settings.google_redirect_port,
        token_path=settings.google_token_path,
    )


def build_client(
    config: OAuthConfig,
    *,
    calendar_id: str = "primary",
    time_zone: str = DEFAULT_TIME_ZONE,
    transport: Transport | None = None,
    interactive: bool = True,
    browser=webbrowser.open,
    timeout: float = 300.0,
) -> GoogleCalendarClient:
    """Dựng client đã sẵn sàng gọi API.

    Dùng token đã lưu nếu có; nếu chưa thì chạy luồng uỷ quyền tương tác (mở
    trình duyệt). `interactive=False` để từ chối thay vì mở trình duyệt — dùng
    cho ngữ cảnh không có người ngồi trước máy (ví dụ chạy tự động).
    """
    if not config.client_id:
        raise GoogleCalendarError(
            "Chưa cấu hình GOOGLE_CLIENT_ID trong .env. Xem .env.example để biết "
            "cách tạo OAuth client ID cho ứng dụng desktop."
        )

    session = OAuthSession.load(config, transport=transport)
    if not session.connected:
        if not interactive:
            raise GoogleCalendarError(
                "Chưa có token Google đã lưu. Chạy uỷ quyền tương tác trước."
            )
        session.authorize(timeout=timeout, browser=browser)

    return GoogleCalendarClient(
        session,
        calendar_id=calendar_id,
        transport=transport,
        time_zone=time_zone,
    )
