# Life OS — multi-agent personality

Hệ **multi-agent** đồng hành cùng một mục tiêu cá nhân, xuyên suốt ba lĩnh vực:
**nghề nghiệp → học tập → lịch tuần**. Mỗi agent có **tính cách riêng**, và toàn bộ
giọng điệu **thích nghi theo hồ sơ người dùng**.

Kịch bản demo: *"Chuyển từ hành chính sang Data Analyst trong 6 tháng, vẫn đi làm
full-time."*

Không chỉ dừng ở lập kế hoạch: hệ thống còn sinh **lịch nhiều tuần**, **theo dõi
tiến độ**, **ôn tập cách quãng**, **kiểm tra hiểu biết**, và đưa lịch vào Google
Calendar — hoặc xuất `.ics`, hoặc **đồng bộ thẳng qua OAuth 2.0**.

Ở tầng đa tác tử, các agent **tự trị** (có trạng thái nội bộ và quyền từ chối),
**thương lượng nhiều vòng** phân việc theo Contract Net Protocol, **tự lập nhóm**
theo kỹ năng cần có, **chạy nền thật** như những tiến trình độc lập gửi tin cho
nhau, và **học từ kết quả thật** để điều chỉnh kế hoạch sau. Xem
[mục 7](#7-đối-chiếu-8-đặc-tính-của-hệ-đa-tác-tử) để biết cái gì đã có sẵn và cái
gì mới được bổ sung.

---

## 1. Ý tưởng cốt lõi: personality kép

Điểm khác biệt so với một pipeline gọi LLM thông thường nằm ở hai cơ chế:

**a) Multi-persona — hội đồng tranh luận rồi tổng hợp**

Sáu agent có tính cách khác nhau, không phải sáu hàm giống nhau:

| Persona | Vai trò | Tính cách |
|---|---|---|
| 🧭 **Người Dẫn Đường** | Điều phối & tổng hợp | Trung lập, cân bằng |
| 🎯 **Chiến Lược Gia** | Phân tích gap kỹ năng | Sắc sảo, thực tế, nói thẳng |
| 📚 **Giáo Viên** | Lộ trình học & giải thích | Kiên nhẫn, dễ hiểu |
| ⏰ **Huấn Luyện Viên Kỷ Luật** | Sắp lịch tuần | Nghiêm túc, không nương tay với trì hoãn |
| 🔍 **Người Phản Biện** | Soi lỗ hổng, rủi ro | Hoài nghi, đặt câu hỏi khó |
| 💪 **Người Động Viên** | Giữ động lực | Ấm áp, không tạo cảm giác tội lỗi |

Người dùng nhận được **đối thoại nhiều giọng** rồi mới tới kết luận tổng hợp —
thay vì một câu trả lời phẳng.

**b) User-adaptive tone**

`personas/tone_adapter.py` ánh xạ hồ sơ người dùng (phong cách giao tiếp + mức độ
nghiêm khắc + tên) thành chỉ thị giọng điệu, chèn vào system prompt của **mọi**
agent. Cùng một kế hoạch, người thích "kỷ luật thép" và người cần "nhẹ nhàng" nhận
được văn phong khác nhau.

---

## 2. Kiến trúc

```
                    ┌──────────────────────────────┐
   UserProfile ───▶ │  tone_adapter → tone_instruction │
                    └──────────────┬───────────────┘
                                   │ (chèn vào mọi persona)
   ┌───────────────────────────────▼───────────────────────────────┐
   │                    LangGraph: build_graph                     │
   │                                                               │
   │  career ──▶ curriculum ──▶ schedule ──▶ roundtable            │
   │   (gap)      (lộ trình)     (lịch tuần)   (critic + nudger)   │
   │                              ▲                │               │
   │                              │        overload? & chưa sửa     │
   │                        reduce_load ◀──────────┤               │
   │                                               │ không         │
   │                                               ▼               │
   │                                        synthesize ──▶ save    │
   └───────────────────────────────────────────────────────────────┘
                                   │
                    ┌──────────────▼──────────────┐
                    │  LangGraph: adjust_graph     │
                    │  assess → reschedule →       │
                    │  roundtable → finalize       │
                    └──────────────────────────────┘
```

**Vòng tự sửa lỗi**: nếu Người Phản Biện đánh dấu `overload=True`, đồ thị quay lại
bước lập lịch với `load_factor=0.8` (giảm 20% tải) rồi mới tổng hợp. Cờ `replanned`
đảm bảo vòng lặp chạy **tối đa một lần**.

**Bất biến cứng bằng code** (không phụ thuộc LLM): tổng giờ trong tuần luôn
`≤ hours_per_week` — task vượt ngân sách bị cắt trong `scheduler._trim_to_budget`.

### 2.1. Tầng đa tác tử: tự trị, thương lượng, tự tổ chức

Song song với đồ thị LangGraph (thứ tự node cố định), dự án có một tầng **đa tác
tử thực sự**, nơi cấu trúc nhóm không được lập trình sẵn:

```
   decompose(goal)                    AGENT_SKILLS
        │                                  │
        ▼                                  ▼
   ┌─────────┐   kỹ năng cần có   ┌──────────────┐
   │ 5 nhiệm │ ─────────────────▶ │ build_roster │──▶ nhóm co giãn
   │   vụ    │                    └──────────────┘    (ai không có
   └────┬────┘                                        việc thì không
        │                                             được mời)
        ▼
   ┌──────────────────── ContractNet ────────────────────┐
   │ 1. announce  orchestrator ──request──▶ mọi thành viên │
   │ 2. bid       agent tự đánh giá ──propose/refuse──▶    │
   │ 3. award     ──accept-proposal──▶ người thắng         │
   │              ──reject-proposal──▶ người còn lại       │
   │ 4. report    ──inform──▶ orchestrator                 │
   └───────────────────────────────────────────────────────┘
```

Điểm mấu chốt: **không ai bị gán việc**. Bộ điều phối chỉ công bố nhiệm vụ; mỗi
agent tự tính điểm phù hợp dựa trên trạng thái nội bộ (năng lực còn trống, kỹ
năng, số việc đã làm, độ tin cậy) rồi tự quyết định bỏ thầu hay từ chối.

---

## 3. Cài đặt & chạy

```powershell
uv sync
Copy-Item .env.example .env   # rồi điền LLM_API_KEY nếu muốn gọi API thật
```

**Demo offline (không cần API key):**

```powershell
uv run python scripts/demo_run.py
```

**Demo với LLM thật:**

```powershell
uv run python scripts/demo_run.py --real
```

**Giao diện web:**

```powershell
uv run streamlit run app.py
```

Trong giao diện có sẵn checkbox **"Dùng LLM giả (offline)"** để chạy thử toàn bộ
luồng mà không tốn phí API.

Giao diện có thêm các mục **lịch nhiều tuần**, **tiến độ**, **ôn tập cách quãng**,
**kiểm tra hiểu biết**, **tự tổ chức nhóm** và nút **tải `.ics`**. Các cờ CLI
tương ứng ở [mục 8](#8-sau-khi-có-kế-hoạch-lịch-dài-tiến-độ-ôn-tập-kiểm-tra).

**Xem tầng đa tác tử (tự trị · thương lượng · tự tổ chức):**

```powershell
uv run python scripts/demo_run.py --team --weeks 4 --skip-adjust
```

Lệnh này in ra: mục tiêu được phân rã thành nhiệm vụ, nhóm tự lập theo kỹ năng
cần có, kết quả từng vòng thương lượng, và **bản ghi giao thức ACL** đầy đủ bốn
pha (`request` → `propose`/`refuse` → `accept-proposal`).

**Bật học từ quá khứ:**

```powershell
uv run python scripts/demo_run.py --adapt --weeks 4 --skip-adjust
```

Cần có kế hoạch đã lưu trước đó (`--save`). Hệ thống đọc lại SQLite, tính tỉ lệ
hoàn thành thật, và tự hạ mức tải nếu bạn hay trượt việc.

**Lưu thẻ ôn tập xuống SQLite:**

```powershell
uv run python scripts/demo_run.py --srs --weeks 4 --skip-adjust
```

Ghi thẻ xuống DB, ghi lại lần hai để chứng minh không nhân đôi, chấm một lượt ôn
rồi đọc lại từ SQLite. Trong giao diện, thanh bên có mục **Kế hoạch đã lưu** để
mở lại kế hoạch cũ kèm tiến độ ôn tập — không có bước này thì `plan_id` chỉ sống
trong phiên và thẻ cũ sẽ thành mồ côi.

**Xem thương lượng nhiều vòng:**

```powershell
uv run python scripts/demo_run.py --negotiate --skip-adjust
```

Kịch bản này cố ý thu nhỏ năng lực của agent xuống dưới mức nhiệm vụ đòi hỏi, để
lộ ra hành vi mà kịch bản thường không thấy: cả nhóm từ chối ở vòng 1, bộ điều
phối công bố lại với phạm vi chia nhỏ ở vòng 2, và phần công sức chưa ai nhận
được ghi rõ thay vì im lặng coi như đã giao xong.

**Xem agent chạy nền thật:**

```powershell
uv run python scripts/demo_run.py --async --skip-adjust
```

Ba agent cùng xử lý một việc tốn 0,3 giây. In ra thời gian thật để đối chiếu:
chạy tuần tự sẽ là ~0,9 giây, còn ở đây gần bằng agent chậm nhất. Kèm theo là
bản ghi ACL và thống kê runtime (số tin đã xử lý, số lỗi, số lần hết hạn chờ).

### Đồng bộ thẳng lên Google Calendar

Phần này cần credentials của chính bạn. Ba bước:

**1. Tạo OAuth client ID** tại Google Cloud Console → APIs & Services →
Credentials → Create credentials → OAuth client ID → **Desktop app**. Thêm
`http://localhost:8765/` vào danh sách redirect URI.

**2. Điền vào `.env`** (xem `.env.example`):

```dotenv
GOOGLE_CLIENT_ID=....apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=...
```

**3. Chạy thử rồi đồng bộ:**

```powershell
# Kiểm tra cấu hình và trạng thái token (không gọi mạng)
uv run python scripts/demo_run.py --gcal status --skip-adjust

# Xem trước payload sẽ gửi lên (không gọi mạng, không cần credentials)
uv run python scripts/demo_run.py --gcal dry-run --skip-adjust

# Đồng bộ thật — lần đầu sẽ mở trình duyệt để xin quyền
uv run python scripts/demo_run.py --gcal sync --skip-adjust
```

Trong giao diện, mục này nằm trong expander **Đồng bộ thẳng lên Google Calendar**
ngay dưới nút tải `.ics`.

Vài điểm đáng lưu ý về cách làm này:

- **Không thêm thư viện.** Luồng authorization code + PKCE cho ứng dụng cài đặt
  chỉ cần `urllib` và `http.server` của thư viện chuẩn, nên `uv sync` không phải
  kéo thêm vài chục MB phụ thuộc của Google.
- **Chỉ xin quyền trên sự kiện** (`calendar.events`), không xin đọc toàn bộ lịch.
  Đồng bộ lịch học không cần biết bạn có những cuộc hẹn nào khác.
- **Đồng bộ idempotent.** Mỗi buổi học mang một khoá `lifeos_key` trong
  `extendedProperties.private`. Chạy lại lệnh đồng bộ sẽ cập nhật đúng sự kiện
  cũ, không tạo trùng.
- **Token là mật khẩu.** File `data/google_token.json` chứa refresh token, tức
  quyền truy cập lịch về sau mà không cần đăng nhập lại. Nó nằm trong `data/`
  (đã bị `.gitignore` chặn) và được ghi với quyền 600 trên POSIX.

---

## 4. Cấu hình LLM

Mọi API tương thích chuẩn chat-completions đều dùng được — chỉ cần đổi `.env`:

| Biến | Ý nghĩa | Mặc định |
|---|---|---|
| `LLM_API_KEY` | Khoá API | — |
| `LLM_BASE_URL` | Endpoint | `https://api.openai.com/v1` |
| `LLM_MODEL` | Tên model | `gpt-4o-mini` |
| `LLM_TEMPERATURE` | Độ sáng tạo | `0.4` |
| `LLM_TIMEOUT` | Timeout mỗi lời gọi (giây) | `120` |
| `LLM_MAX_RETRIES` | Số lần thử lại khi lỗi | `0` |
| `GOOGLE_CLIENT_ID` | OAuth client ID (tuỳ chọn, cho Google Calendar) | — |
| `GOOGLE_CLIENT_SECRET` | OAuth client secret (tuỳ chọn) | — |
| `GOOGLE_REDIRECT_PORT` | Cổng nhận chuyển hướng OAuth | `8765` |
| `GOOGLE_TOKEN_PATH` | Nơi lưu token | `data/google_token.json` |
| `GOOGLE_CALENDAR_ID` | Lịch nhận sự kiện | `primary` |
| `GOOGLE_TIME_ZONE` | Múi giờ gửi lên Google | `Asia/Ho_Chi_Minh` |

### Chọn model: nguyên nhân "treo" phổ biến nhất

Cả luồng lập kế hoạch cần **~10 lời gọi LLM liên tiếp**. Nếu mỗi lời gọi mất 30s,
cả luồng mất 5 phút và trông như bị treo. Đo thực tế trên một gateway đa model:

| Model | TTFT | Tổng | Structured output |
|---|---|---|---|
| `deepseek-v4.1-flash` | 2.1s | 2.8s | ✅ `json_schema` |
| `glm-5.3-flash` | 3.1s | 3.6s | ⚠️ cần cascade (tầng tool calling) |
| `qwen3.8-flash` (model suy luận) | 31.0s | 31.9s | chậm |
| `gemini-3.8-flash` | — | — | ❌ 502 upstream |

Cascade thực sự có tác dụng: `glm-5.3-flash` hỏng ở tầng `json_schema` nhưng chạy
được qua tầng tool calling — nếu chỉ dùng `with_structured_output` trần thì model
này không dùng được.

**Khuyến nghị:** dùng model "flash" không suy luận. Nếu buộc dùng model suy luận,
tăng `LLM_TIMEOUT` lên 180-300.

### Gateway không hỗ trợ `json_schema`

Nhiều proxy đa model **không thực thi** `response_format: json_schema` — model vẫn
trả markdown. `lifeos/llm.py` xử lý bằng cascade 3 tầng:

1. structured output gốc (`json_schema`)
2. structured output qua tool calling
3. yêu cầu JSON dạng văn bản → tự trích xuất (bỏ code fence, tìm object cân bằng),
   thử lại 1 lần

Khi tầng 1-2 hỏng, kết quả được ghi nhớ nên các lời gọi sau đi thẳng vào tầng 3.

### Chẩn đoán nhanh

```powershell
uv run python scripts/diagnose_llm.py   # đo từng tầng: DNS, TCP, HTTP, chat, structured, cascade
uv run python scripts/probe_models.py   # so sánh độ trễ nhiều model
uv run python scripts/probe_models.py deepseek-v4.1-flash glm-5.3-flash   # chỉ định model
```

---

## 5. Cấu trúc thư mục

```
src/lifeos/
├── config.py            # đọc .env
├── models.py            # schema Pydantic dùng chung
├── llm.py               # giao diện LLM + adapter LangChain
├── clarify.py           # phát hiện mục tiêu mơ hồ → câu hỏi làm rõ
├── demo.py              # LLM giả cho demo/test offline
├── graph.py             # LangGraph: build_graph + adjust_graph
├── acl.py               # giao thức tin nhắn giữa agent (performative + bus)
├── runtime.py           # agent chạy nền thật (asyncio) + hộp thư riêng
├── parallel.py          # chạy song song các bước độc lập
├── progress.py          # theo dõi tiến độ trên lịch nhiều tuần
├── persistence.py       # lưu/khôi phục/liệt kê kế hoạch + thẻ ôn tập
├── reflection.py        # suy ngẫm từ ký ức + phản hồi thật
├── srs.py               # ôn tập cách quãng (SM-2)
├── personas/
│   ├── base.py          # lớp Persona
│   ├── registry.py      # 6 persona
│   └── tone_adapter.py  # UserProfile → chỉ thị giọng điệu
├── agents/
│   ├── career.py … orchestrator.py   # 6 agent chuyên trách
│   ├── autonomy.py      # AgentState + AutonomousAgent (tự trị)
│   ├── contract_net.py  # thương lượng phân việc nhiều vòng (Contract Net)
│   └── team.py          # phân rã mục tiêu + tự lập nhóm
├── memory/
│   ├── store.py         # SQLite: kế hoạch, sự kiện điều chỉnh, thẻ ôn tập
│   └── vector.py        # Chroma: truy xuất ngữ nghĩa
└── tools/
    ├── calendar.py      # parse/ghi ICS, phát hiện & dịch khỏi khoảng bận
    └── google_calendar.py  # OAuth 2.0 + đồng bộ thẳng lên Google Calendar
```

---

## 6. Test

```powershell
uv run pytest -q
```

- `test_personas.py` — persona + tone adapter + câu hỏi làm rõ
- `test_acl.py` — performative, ghép hội thoại, broadcast, `reply` vs `notify`
- `test_autonomy.py` — trạng thái nội bộ, tự đánh giá, quyền từ chối, độ tin cậy
- `test_contract_net.py` — đủ 4 pha thương lượng, trao thầu tất định, hết năng lực
- `test_multi_round.py` — công bố lại khi công sức vượt năng lực, chia nhỏ phạm
  vi, ghi rõ phần chưa ai nhận, không bao giờ giao quá tải
- `test_runtime.py` — agent chạy nền thật: đồng thời thật (đo bằng thời gian),
  agent chậm không chặn người khác, agent lỗi không làm sập runtime, tắt máy có
  chặn thời gian
- `test_google_calendar.py` — PKCE, URL uỷ quyền, làm mới token, lưu token, hàm
  chuyển lịch thành sự kiện, đồng bộ idempotent, và server nhận chuyển hướng
  trên localhost. Chạy **không cần mạng và không cần credentials thật**
- `test_team.py` — phân rã mục tiêu, nhóm co giãn theo kỹ năng cần có
- `test_llm_decomposition.py` — phân rã bằng LLM: dùng kết quả LLM, chuẩn hoá
  slug tiếng Việt, kẹp giá trị số, và quay về quy tắc khi LLM lỗi
- `test_parallel.py` — giữ thứ tự, một job lỗi không phá các job khác, nhanh hơn tuần tự
- `test_reflection.py` — đọc ký ức, tính tỉ lệ hoàn thành, đề xuất hệ số tải
- `test_calendar.py` — parse ICS, khoảng bận, dịch giờ
- `test_scheduler.py` — ngân sách giờ, tránh khoảng bận, chuẩn hoá
- `test_program.py` — phân bổ module theo tuần + sinh lịch nhiều tuần không cần LLM
- `test_progress.py` — đánh dấu buổi học, % hoàn thành, streak, đúng/chệch tiến độ
- `test_persistence.py` — lưu, khôi phục, cập nhật, liệt kê và đọc lại kế hoạch
- `test_ics_export.py` — xuất `.ics`, ánh xạ tuần → ngày thật, đọc lại được
- `test_srs.py` — giãn khoảng cách SM-2, reset khi quên, chặn trên/dưới
- `test_srs_persistence.py` — thẻ ôn tập lưu xuống SQLite, ghi đè theo
  `(plan_id, topic)`, thẻ đến hạn, chịu được bản ghi hỏng
- `test_vector_memory.py` — truy xuất ngữ nghĩa, và chịu được phản hồi thiếu dữ
  liệu từ chromadb thay vì sập
- `test_quiz.py` — quiz nhiều câu, chấm điểm, phát hiện chủ đề yếu
- `test_llm.py` — trích JSON chịu lỗi + cascade structured output
- `test_graph.py` — tích hợp: lập kế hoạch, vòng giảm tải, điều chỉnh, lưu trữ,
  học từ quá khứ, chịu lỗi khi một agent hỏng
- `test_app.py` — giao diện Streamlit qua `AppTest` (chạy offline)
- `test_eval.py` — **LLM-as-judge** chấm `coherence` + `tone_fit`
  (tự động bỏ qua nếu chưa có `LLM_API_KEY`)

Test dùng `FakeLLM` tất định nên chạy nhanh và không tốn API. Riêng `test_eval.py`
gọi API thật và mất vài phút — đó là bài kiểm chứng end-to-end duy nhất chạm
endpoint thật.

### 6.1. Lint & kiểm tra kiểu

```powershell
uv run ruff check .          # lint
uv run ruff check . --fix    # tự sửa phần sửa được
uv run mypy                  # kiểm tra kiểu trên src/lifeos
```

Cả hai đã được cấu hình trong `pyproject.toml` và **đang sạch** — chạy lên không
có cảnh báo nào.

**Vì sao cấu hình tường minh thay vì để mặc định.** Ruff đổi bộ rule mặc định
giữa các phiên bản: bản 0.16 bật sẵn cả `UP`, `DTZ`, `BLE`, `SIM`. Nếu không
ghim `select` thì cùng một commit có thể pass ở máy này và fail ở máy khác chỉ vì
khác phiên bản ruff. `pyproject.toml` ghim đúng bộ rule dự án chủ động chọn.

**Ba rule bị tắt có lý do, không phải để cho qua:**

| Rule | Vì sao tắt |
|---|---|
| `E501` | Độ dài dòng để trình soạn thảo lo; chặn ở đây chỉ tạo nhiễu khi review |
| `UP046`, `UP047` | Ép sang generic kiểu PEP 695 (`class X[T]`) — cú pháp hợp lệ trong 3.12 nhưng đổi cách đánh giá tham số kiểu |
| `UP042` | Ép `class X(str, Enum)` sang `enum.StrEnum`. **Hai thứ này không tương đương**: `str(X.A)` cho `"X.A"` với `(str, Enum)` nhưng cho `"<giá trị>"` với `StrEnum`. Các enum ở `models.py`/`acl.py` được dùng làm khoá và để hiển thị ở nhiều nơi, nên đổi là đổi hành vi thật |

**Phạm vi kiểm tra kiểu.** `mypy` chỉ chạy trên `src/lifeos`, không chạy trên
`tests/` hay `scripts/`. Không bật `strict` vì mã nguồn dùng nhiều thư viện không
có stub (`chromadb`, `icalendar`, `langchain`); bật strict sẽ sinh hàng trăm cảnh
báo về `Any` mà không chỉ ra lỗi thật.

**Nếu `mypy` báo `INTERNAL ERROR`.** Đây là lỗi môi trường, không phải lỗi mã
nguồn: khi `uv` gỡ một gói, nó có thể để lại thư mục cụt trong `.venv` (ví dụ
`psutil/` còn `_psutil_windows.pyd` nhưng mất `__init__.py`). Thư mục đó thành
namespace package che mất gói thật và làm `mypy` sập khi dò số luồng CPU. Cách
sửa: xoá thư mục cụt đó rồi chạy lại, hoặc `uv sync --reinstall`.

---

## 7. Đối chiếu 8 đặc tính của hệ đa tác tử

Bảng dưới nói rõ **cái gì đã có từ trước** và **cái gì được bổ sung** trong đợt
này. Cột "trước" ghi trung thực cả những chỗ còn thiếu.

| # | Đặc tính | Trước | Sau | Ở đâu |
|---|---|---|---|---|
| 1 | **Tự trị** (Autonomy) | ❌ Agent là hàm thuần, không có trạng thái nội bộ, không có quyền từ chối | ✅ Mỗi agent giữ `AgentState` (tải, năng lực, độ tin cậy, lịch sử) và **tự quyết định** nhận việc hay từ chối | `agents/autonomy.py` |
| 2 | **Tương tác** (Social Ability) | ⚠️ Có `Roundtable` nhưng chỉ là văn bản để hiển thị, không có hành vi giao tiếp | ✅ `ACLMessage` có **performative** (request/inform/propose/refuse/accept-proposal…) + `MessageBus` ghép hội thoại | `acl.py` |
| 3 | **Cộng tác & phân phối** | ⚠️ `synthesize()` chỉ tổng hợp văn bản; việc phân rã do đồ thị hard-code | ✅ Bộ điều phối **phân rã mục tiêu bằng LLM** rồi giao qua thương lượng; LLM lỗi thì có lưới an toàn bằng quy tắc | `agents/team.py` |
| 4 | **Chuyên môn hóa** | ✅ Đã có — 6 persona, mỗi agent một module riêng | ✅ Giữ nguyên, nay kèm khai báo kỹ năng máy đọc được (`AGENT_SKILLS`) | `personas/registry.py` |
| 5 | **Thương lượng** (Negotiation) | ❌ **Không có gì** — phản biện nói "quá tải" thì đồ thị tự giảm tải, không ai thương lượng | ✅ **Contract Net Protocol** đủ 4 pha, **công bố lại nhiều vòng** khi công sức vượt năng lực | `agents/contract_net.py` |
| 6 | **Tự tổ chức** (Self-Organization) | ❌ Thứ tự node cố định trong `StateGraph` | ✅ Nhóm **co giãn theo việc**: ai không có nhiệm vụ phù hợp thì không được mời; thêm agent mới chỉ cần khai báo kỹ năng | `agents/team.py` |
| 7 | **Mở rộng & song song** | ❌ Chạy tuần tự hoàn toàn | ✅ Hai mức: `map_parallel` cho các bước độc lập, và **runtime asyncio** cho agent chạy nền thật với hộp thư riêng | `parallel.py`, `runtime.py` |
| 8 | **Học liên tục** | ⚠️ Bộ nhớ **chỉ ghi** — `memory.search()` chưa bao giờ được gọi trong luồng thật | ✅ **Suy ngẫm** trước khi lập kế hoạch: đọc lại ký ức + tỉ lệ hoàn thành thật để tự hạ mức tải | `reflection.py` |

Hai điểm đáng nói về tính trung thực của bảng này:

- **Đặc tính 4 đã có sẵn** từ trước, không phải làm mới. Nói nó "đã có" quan
  trọng hơn là gán ghép cho đủ 8 ô.
- **Đặc tính 8 trước đây chỉ là hình thức.** `VectorMemory` tồn tại và có test,
  nhưng `search()` **chỉ được gọi trong test** — nghĩa là hệ thống ghi ký ức rồi
  không bao giờ đọc lại. Đây là dạng "tính năng có mà không hoạt động" khó phát
  hiện, nên đợt này khép vòng bằng `reflection.py`.

### Học từ phản hồi thật hoạt động thế nào

`reflection.outcome_stats()` nhìn tỉ lệ hoàn thành của các kế hoạch cũ và quyết
định mức tải cho kế hoạch mới:

| Tỉ lệ hoàn thành trung bình | Hệ số tải | Ý nghĩa |
|---|---|---|
| < 50% | 0.75 | Người dùng đang nhận quá sức — giảm mạnh |
| 50% – <75% | 0.90 | Chưa đều — giảm nhẹ |
| ≥ 75% | 1.00 | Giữ nguyên |

Hệ số này **nhân** vào mức tải hiện tại chứ không gán đè, nên nếu hội đồng cũng
kết luận quá tải thì hai mức giảm cộng dồn (`0.75 × 0.8 = 0.6`). Nếu gán đè, một
kế hoạch đã được hạ xuống 0.75 vì lịch sử sẽ bị đẩy ngược lên 0.8 — tức là vô
tình làm nặng thêm đúng cái mà dữ liệu nói là quá sức. Có test riêng cho việc này.

---

## 8. Sau khi có kế hoạch: lịch dài, tiến độ, ôn tập, kiểm tra

Luồng lập kế hoạch chỉ sinh **tuần 1** bằng LLM. Bốn tính năng dưới đây biến nó
thành thứ dùng được hàng ngày — và **không tốn thêm lời gọi LLM nào**, vì đều là
logic thuần có test:

| Tính năng | Module | Ghi chú |
|---|---|---|
| **Lịch nhiều tuần** | `scheduler.allocate_modules` | Chia module theo số giờ, giữ thứ tự học; module dài bị cắt qua nhiều tuần. Tuần 2+ sinh bằng công thức nên lộ trình 26 tuần vẫn mất ~1 phút thay vì 26 lần gọi LLM |
| **Theo dõi tiến độ** | `progress.py` | Đánh dấu từng buổi, tính % hoàn thành, số giờ, **chuỗi tuần hoàn thành liên tiếp**, và cảnh báo chệch tiến độ |
| **Lưu & khôi phục** | `persistence.py` | Kế hoạch lưu vào SQLite, mở lại được ở phiên sau kèm % tiến độ |
| **Ôn tập cách quãng** | `srs.py` | SM-2 rút gọn: nhớ tốt → giãn 1 → 6 → `interval × ease` ngày; quên → reset và tăng `lapses` |
| **Kiểm tra hiểu biết** | `tutor.quiz_set` + `tutor.grade` | Nhiều câu một lượt, chấm điểm, chỉ ra **câu hỏi bị sai** để biết phần nào cần ôn |
| **Xuất lịch** | `calendar.tasks_to_ics` | Ánh xạ "tuần N + thứ" → **ngày tháng thật**, xuất `.ics` import vào Google Calendar |

Một chi tiết đáng chú ý: khi hội đồng kết luận kế hoạch **quá tải** và giảm tải
tuần 1, hệ số giảm đó được **áp cho toàn bộ chương trình** (`load_factor` xuyên
qua `program_node`). Nếu chỉ giảm tuần 1 thì tuần 2 trở đi lại đầy 100% ngân
sách — đúng cái mà hội đồng vừa bác bỏ.

Dùng qua CLI:

```powershell
uv run python scripts/demo_run.py --weeks 12 --progress --quiz `
    --ics data/lich.ics --save
uv run python scripts/demo_run.py --list-plans    # xem lại kế hoạch đã lưu
```

---

## 9. Xử lý tình huống lệch kế hoạch

`adjust_plan()` chạy đồ thị thứ hai:

1. **assess** — Người Phản Biện phân tích nguyên nhân và mức độ trượt
2. **reschedule** — Huấn Luyện Viên lập tuần mới với `load_factor=0.9`, ưu tiên bù
   phần trượt nhưng không nhồi thêm việc
3. **roundtable** — Phản Biện + Động Viên phát biểu
4. **finalize** — Người Dẫn Đường tổng hợp, tạo `AdjustmentEvent` (tuần cũ → tuần
   mới) và lưu vào SQLite

Kế hoạch cũ được `model_copy(deep=True)` trước khi sửa, nên **không bị thay đổi
tại chỗ** (có test kiểm chứng).

---

## 10. Giới hạn của MVP

- Giao diện và nội dung mẫu bằng **tiếng Việt**.
- Lịch nhiều tuần sinh theo **công thức** cho tuần 2 trở đi: đúng ngân sách giờ
  và thứ tự module, nhưng không "thông minh" như tuần 1 do LLM lập.
- Xuất `.ics` được, và **đồng bộ thẳng lên Google Calendar** qua OAuth 2.0. Phần
  này đã kiểm thử đầy đủ ở mức đơn vị nhưng **chưa chạy thật với Google** trong
  quá trình phát triển (cần credentials của người dùng), nên hãy coi là "đã viết
  xong, chưa xác minh đầu-cuối".
- `tools/search.py` còn là stub.
- Quiz chấm theo **đáp án cố định** do LLM sinh, chưa kiểm chứng lại tính đúng
  của đáp án đó.
- **Chưa có giao tiếp giữa các agent theo thời gian thực.** `runtime.py` cho các
  agent chạy nền thật và gửi tin qua hộp thư trong **một tiến trình**, nhưng
  chúng chưa phải tiến trình/máy riêng, và chưa có hàng đợi bền (message broker)
  nên tin nhắn không sống qua lần khởi động lại. Giao diện Streamlit vẫn dùng
  đường đồng bộ (`self_organize`) vì `asyncio.run` trong vòng chạy script của
  Streamlit dễ xung đột với vòng lặp sẵn có; đường bất đồng bộ dùng qua
  `self_organize_async` hoặc `demo_run.py --async`.
- **Thương lượng nhiều vòng chỉ nới được công sức**, không nới kỹ năng: nếu
  không agent nào có chuyên môn phù hợp thì dừng ngay ở vòng 1 thay vì công bố
  lại vô ích. Việc chưa ai nhận được ghi rõ thành `remaining_effort`, nhưng hệ
  thống chưa tự đề xuất cách xử lý (tăng năng lực, đổi người, hay bỏ việc).
- Chưa có **liên minh** giữa các agent: mỗi nhiệm vụ vẫn chỉ một agent nhận,
  chưa có nhóm agent cùng đứng ra nhận một việc lớn.
- Học liên tục dựa trên **tỉ lệ hoàn thành**, chưa học từ nội dung phản hồi
  dạng văn bản của người dùng.
- Phân rã bằng LLM **có lưới an toàn**: nếu LLM lỗi, trả về ít hơn 2 nhiệm vụ,
  hoặc nhiệm vụ thiếu kỹ năng/mô tả thì hệ thống quay về bộ quy tắc cố định. Bộ
  quy tắc đó vẫn không phụ thuộc mục tiêu, nên khi nó chạy thì mọi mục tiêu đều
  ra cùng một danh sách.
- LLM có thể đề xuất **kỹ năng mà không agent nào có**; hệ thống giữ nguyên
  nhiệm vụ đó và báo "không ai nhận" thay vì tự gán bừa cho một agent.

**Hướng mở rộng:** liên minh agent cho việc lớn, hàng đợi tin bền (message
broker), `tools/search.py` thật, và bộ test eval lớn hơn.

---

## 11. Giấy phép

MIT — xem [LICENSE](LICENSE).
