# Báo cáo: 7 hạng mục — MultiAgentPersonality

**Repo:** https://github.com/hienvanla5/MultiAgentPersonality
**Nhánh chính:** `main` — nay ở `3b65ee9`
**Mốc xuất phát:** `2d0cfef`
**Ngôn ngữ / framework:** Python 3.12 + LangGraph + Pydantic v2 + Streamlit (quản lý bằng `uv`)
**Quy ước commit:** Conventional Commits, mô tả tiếng Việt **không dấu**
**Quy trình:** nhánh `feature/...` + Pull Request, không push thẳng `main`, không force push

---

## 1. Tóm tắt

| # | Hạng mục | Kết luận khảo sát | PR | Commit |
|---|---|---|---|---|
| 1 | Lưu thẻ ôn tập SRS xuống SQLite | **CHƯA CÓ** | [#1](https://github.com/hienvanla5/MultiAgentPersonality/pull/1) | `7230612` |
| 2 | Phân rã nhiệm vụ bằng LLM | **CHƯA CÓ** | [#2](https://github.com/hienvanla5/MultiAgentPersonality/pull/2) | `acf0359` |
| 3 | Thương lượng nhiều vòng | **CHƯA CÓ** | [#3](https://github.com/hienvanla5/MultiAgentPersonality/pull/3) | `9741bfa` |
| 4 | Runtime agent chạy nền bất đồng bộ | **CHƯA CÓ** | [#4](https://github.com/hienvanla5/MultiAgentPersonality/pull/4) | `44352ff` |
| 5 | Đồng bộ Google Calendar qua OAuth 2.0 | **CHƯA CÓ** | [#5](https://github.com/hienvanla5/MultiAgentPersonality/pull/5) | `2c0abf9` |
| 6 | Lint gate: ruff + mypy | **CHƯA CÓ** | [#6](https://github.com/hienvanla5/MultiAgentPersonality/pull/6) | `034c667`, `5c870ed` |
| 7 | Tách eval khỏi bộ test mặc định | **CHƯA CÓ** | [#7](https://github.com/hienvanla5/MultiAgentPersonality/pull/7) | `5d21825` |

**Cả 7 PR đã merge vào `main`.** Không còn PR nào mở. Tổng thay đổi so với `2d0cfef`:
**73 file, +6.620 / −340 dòng**.

---

## 2. Phần A — 5 tính năng còn thiếu

### 2.1. Kết luận khảo sát và bằng chứng

Mỗi kết luận dưới đây dựa trên bằng chứng cụ thể, không phải phỏng đoán:

| # | Tính năng | Bằng chứng "chưa có" |
|---|---|---|
| 1 | Lưu thẻ SRS xuống SQLite | `memory/store.py` chỉ có bảng `plans` + `events`; `srs.py` là logic thuần, không chạm DB |
| 2 | Phân rã bằng LLM | `team.decompose()` hard-code 5 nhiệm vụ cho **mọi** mục tiêu, không có tham số `llm` |
| 3 | Thương lượng nhiều vòng | `contract_net.py` không có biến `round`, không có vòng `while`, không có hằng số số vòng tối đa |
| 4 | Runtime chạy nền bất đồng bộ | grep `async def\|await \|asyncio\|threading\|queue\.\|Thread\(` trên `src/lifeos` → **0 kết quả** |
| 5 | Google Calendar OAuth | `google-api-python-client` không có trong `pyproject.toml`; `oauthlib` chỉ là phụ thuộc bắc cầu |

### 2.2. Thứ tự thực hiện và lý do

| Task | Nhánh | Phụ thuộc | Lý do thứ tự |
|---|---|---|---|
| T1 | `feature/srs-persistence` | — | Độc lập hoàn toàn |
| T2 | `feature/llm-decomposition` | T1 | Dùng `demo.py` / `conftest.py` đã đụng ở T1 |
| T3 | `feature/multi-round-negotiation` | T2 | `TeamPlan` do T2 sửa |
| T4 | `feature/async-agent-runtime` | T3 | Dùng lại `pick_winner` tách ra ở T3 |
| T5 | `feature/google-calendar-oauth` | T4 | Độc lập về logic, xếp cuối cho gọn chuỗi |

### 2.3. Vì sao dùng nhánh xếp chồng thay vì 5 nhánh rời từ `main`

Cả 5 tính năng đều đụng cùng những file lõi: `graph.py`, `app.py`, `models.py`,
`demo_run.py`. Nếu tách 5 nhánh độc lập từ `main` thì mỗi PR sẽ xung đột merge với
những PR còn lại, và không PR nào review sạch được.

Cách đã chọn: mỗi nhánh cắt từ nhánh trước, mỗi PR nhắm vào nhánh trước đó. Khi một
PR merge, base của PR kế tiếp được trỏ về `main`. Nhờ vậy **mỗi PR vẫn hiện đúng
diff của một tính năng**.

### 2.4. Chi tiết từng tính năng

**T1 — Lưu thẻ ôn tập SRS xuống SQLite.** Bảng `review_cards` với
`UniqueConstraint("plan_id", "topic")` nên ghi lại là cập nhật, không nhân đôi.
`GLOBAL_PLAN_ID = 0` cho thẻ không thuộc kế hoạch nào — dùng `0` chứ **không** dùng
`NULL`, vì SQLite coi mỗi `NULL` là khác nhau nên `UniqueConstraint` sẽ vô hiệu.
`app.py` thêm mục **Kế hoạch đã lưu** ở thanh bên; không có bước này thì `plan_id`
chỉ sống trong phiên và thẻ cũ thành mồ côi.

**T2 — Phân rã nhiệm vụ bằng LLM.** `decompose(goal, llm=None)`: dùng LLM khi có,
quay về quy tắc cố định khi LLM lỗi / trả `None` / trả rỗng / chỉ 1 nhiệm vụ / toàn
nhiệm vụ không hợp lệ. `DecomposedTask` cố ý **không** ràng buộc khoảng giá trị:
`autonomy.Task` yêu cầu `1 <= priority <= 3` và `0 < effort <= 1`, nhưng nếu áp ràng
buộc đó lên schema gửi cho LLM thì một giá trị hơi lệch cũng làm hỏng cả lần gọi có
cấu trúc. Thà nhận giá trị thô rồi kẹp lại ở `_normalize_tasks`.

**T3 — Thương lượng nhiều vòng.** `MAX_ROUNDS = 3`. Bộ điều phối chỉ nới được **một**
thứ: công sức. **Kỹ năng thì không** — không ai có chuyên môn phù hợp thì dừng ngay ở
vòng 1 thay vì công bố lại vô ích. Phần chưa ai nhận được ghi rõ thành
`remaining_effort` thay vì im lặng coi như đã giao xong. `pick_winner` /
`no_winner_reason` được tách ra mức module để runtime bất đồng bộ dùng lại **đúng luật
trao thầu** — hai đường chạy mà lệch luật thì kết quả sẽ khác nhau.

**T4 — Runtime agent chạy nền.** `src/lifeos/runtime.py` (mới): mỗi agent là một
`asyncio.Task` thật, có **hộp thư riêng**, tự chạy vòng lặp nhận tin → xử lý → trả
lời. Ba hệ quả kiểm chứng được bằng test: đồng thời thật (3 agent ngủ 0,15s xong
trong ~0,15s chứ không phải ~0,45s); agent chậm không chặn agent khác; agent lỗi
không làm sập runtime.

**T5 — Google Calendar OAuth 2.0.** Ba phần tách bạch: `events_from_weeks()` là **hàm
thuần** (chứa nhiều lỗi tiềm ẩn nhất nên tách hẳn khỏi phần mạng), `OAuthSession`, và
`GoogleCalendarClient`. Đồng bộ **idempotent** qua khoá `lifeos_key` trong
`extendedProperties.private`. Xin **quyền tối thiểu** (`calendar.events`), không xin
đọc toàn bộ lịch.

---

## 3. Phần B — Lint gate (hạng mục 6)

### 3.1. Kết luận khảo sát

Repo **không có lint gate nào**: không `ruff`, không `mypy`, không `pre-commit`,
không CI. Chất lượng mã chỉ dựa vào test và review tay.

### 3.2. Kết quả

```
uv run ruff check .   ->  All checks passed!
uv run mypy           ->  Success: no issues found in 38 source files
```

Đã xử lý **260 cảnh báo** trên 66 file: 224 sửa tự động bằng `ruff --fix`, phần còn
lại sửa bằng tay hoặc tắt có ghi lý do (6 × `UP042`, 7 × `BLE001` trong script chẩn đoán).

### 3.3. Ghim cấu hình tường minh, không để mặc định

Ruff **đổi bộ rule mặc định giữa các phiên bản**. Bản 0.16 bật sẵn cả `UP`, `DTZ`,
`BLE`, `SIM` — chạy mặc định cho 194 cảnh báo, gồm cả những rule dự án chưa từng
chọn. Để mặc định thì cùng một commit có thể pass ở máy này và fail ở máy khác chỉ vì
khác phiên bản ruff. `select` trong `pyproject.toml` ghim đúng bộ rule dự án chủ động
chọn (238 cảnh báo theo bộ rule đã ghim, trước khi sửa).

### 3.4. Ba rule bị tắt — có lý do, không phải để cho qua

| Rule | Vì sao tắt |
|---|---|
| `E501` | Độ dài dòng để trình soạn thảo lo; chặn ở đây chỉ tạo nhiễu khi review |
| `UP046`, `UP047` | Ép sang generic kiểu PEP 695 (`class X[T]`) — hợp lệ trong 3.12 nhưng đổi cách đánh giá tham số kiểu |
| `UP042` | Ép `class X(str, Enum)` sang `enum.StrEnum` |

`UP042` là chỗ tôi **dừng lại và kiểm chứng thay vì sửa máy móc**. Hai thứ này không
tương đương:

```
class A(str, enum.Enum): X = "xin chao"   ->  str(A.X) == 'A.X'
class B(enum.StrEnum):   X = "xin chao"   ->  str(B.X) == 'xin chao'
```

Các enum ở `models.py` và `acl.py` được dùng làm khoá và để hiển thị ở nhiều nơi, nên
đổi là **đổi hành vi thật**. Tắt rule và ghi rõ lý do trung thực hơn là sửa 6 lớp enum
rồi hy vọng test bắt được.

### 3.5. Những chỗ sửa cần phán đoán

- **`llm.py` + `agents/base.py` — Protocol `structured()` nay là generic.** Sửa đáng
  giá nhất. Trước đây Protocol khai báo trả `BaseModel`, nên **mọi** call site đều sai
  kiểu: `scheduler`, `curriculum`, `critic`, `tutor`, `orchestrator` đều nhận
  `BaseModel` rồi truy cập `.modules`, `.total_weeks`, `.summary` — mypy báo 12 lỗi.
  Nay khai báo `structured(..., Quiz)` thì nhận lại đúng `Quiz`.
- **`memory/vector.py` — phòng vệ theo kiểu, KHÔNG phải sửa lỗi đã gặp.** Đã chạy thử
  với chroma thật: bộ sưu tập rỗng trả `{"ids": [[]]}` chứ không phải `None`, nên
  **không tái hiện được** lỗi. Chữ ký `query()` của chromadb khai báo các khoá là
  `Optional`, nên đây là gia cố theo kiểu dữ liệu. Nói thẳng như vậy thay vì gọi nó là
  "sửa bug".
- **`contract_net.py` — `zip(..., strict=True)`.** `broadcast` trả đúng một tin cho mỗi
  receiver, nên hai danh sách luôn khớp độ dài. `strict=True` biến giả định đó thành
  khẳng định: nếu có ngày ai đó sửa `broadcast` cho lệch, lỗi nổ ra ngay thay vì âm
  thầm bỏ sót agent cuối.
- **`contract_net.py` — thay `lambda a=agent: ...` bằng `functools.partial`.** mypy
  không suy được kiểu của lambda có tham số mặc định; `partial` thì suy được.
- **`graph.py` — `cast` cho hai kết quả `map_parallel`.** Hai job trả về hai kiểu khác
  nhau (`Critique` và `str`) nên `map_parallel` suy ra kiểu chung là `object`.
- **`graph.py` — `BuildState.reflection` thành `Reflection | None`.** `total=False` chỉ
  nói khoá là tuỳ chọn, không nói giá trị không được `None`, mà mã nguồn thật sự truyền
  `None` vào.
- **`tests/test_graph.py` — F821 tìm ra lỗi thật.** `LifeOSPlan` được dùng làm
  annotation nhưng chỉ import **bên trong** hàm. Nếu annotation được đánh giá thì nổ
  `NameError`.
- **59 file thiếu newline ở cuối file.** Đã kiểm tra trực tiếp bằng `Get-Content -Raw`
  chứ không tin linter — và linter đúng.

### 3.6. Phạm vi kiểm tra kiểu

`mypy` chỉ chạy trên `src/lifeos`, **không** chạy trên `tests/` và `scripts/`. Không
bật `strict` vì mã nguồn dùng nhiều thư viện không có stub (`chromadb`, `icalendar`,
`langchain`); bật strict sẽ sinh hàng trăm cảnh báo về `Any` mà không chỉ ra lỗi thật.
Đây là lựa chọn có chủ ý, không phải bỏ quên.

---

## 4. Phần C — Tách eval khỏi bộ test mặc định (hạng mục 7)

### 4.1. Vấn đề

Bộ test mặc định phụ thuộc **mạng, API key và quota**: `test_eval.py` gọi LLM thật và
nằm trong lần chạy `uv run pytest -q` bình thường.

Hệ quả đã gặp thật: một lần chạy đầy đủ báo **1 failed** với `RuntimeError` từ lời gọi
LLM; chạy lại thì pass. Nghĩa là bộ test **không tất định**, và tệ hơn: một báo đỏ do
trục trặc nhà cung cấp **không phân biệt được** với một hồi quy thật.

### 4.2. Hai thay đổi

**Tách khỏi bộ mặc định.** `test_eval.py` được đánh dấu marker `eval`, và
`addopts = "-m 'not eval'"` loại nó ra. Tham số `-m` trên dòng lệnh **ghi đè được**
(pytest lấy lần xuất hiện cuối cùng).

```powershell
uv run pytest -q              # bộ mặc định, KHÔNG gồm eval
uv run pytest -q -m eval      # chỉ chạy eval
uv run pytest -q -m ""        # chạy tất cả, kể cả eval
```

**Thử lại khi lỗi tạm thời.** Mỗi lời gọi LLM trong bài eval được thử lại **3 lần** khi
**ném lỗi**, backoff tuyến tính 2s/4s.

Điểm quan trọng: **chỉ lỗi mới được thử lại**. Điểm chấm thấp **không** thử lại. Điểm
thấp là tín hiệu thật về chất lượng kế hoạch; thử lại cho tới khi giám khảo chấm điểm
đẹp hơn thì không phải làm test ổn định, mà là **tự lừa mình**.

### 4.3. Chẩn đoán khi hỏng hẳn

Khi hỏng cả 3 lần, thông báo lỗi liệt kê lỗi của **từng lần thử**. Lỗi **giống hệt
nhau** qua các lần là hỏng thật (sai key, hết quota, sai model — thử lại vô ích); lỗi
**khác nhau từng lần** là trục trặc nhất thời.

### 4.4. Điều cố ý **không** làm

Không bắt lỗi theo từ khoá kiểu `if "401" in str(exc)`. Cách đó phụ thuộc vào chuỗi
thông báo của nhà cung cấp và sẽ âm thầm hỏng khi họ đổi câu chữ. Thay vào đó, việc
phân biệt để **người đọc log** làm — với đầy đủ dữ liệu trong tay.

Cũng không tăng số lần thử lên cao: mỗi lần thử `create_plan` tốn khoảng một phút, thử
5-6 lần sẽ biến bài eval thành 6 phút mà chỉ che đi vấn đề thật lâu hơn.

---

## 5. Kiểm chứng trên `main` sau khi merge

```
uv run ruff check .   ->  All checks passed!
uv run mypy           ->  Success: no issues found in 38 source files
uv run pytest -q      ->  580 passed, 1 skipped, 1 deselected  (43 giây)
uv run pytest -q -m eval  ->  1 passed                        (~4 phút)
```

- **1 skipped**: `test_token_file_is_not_world_readable` — kiểm tra quyền POSIX 600, tự
  bỏ qua trên Windows vì `chmod` không thực thi bit quyền kiểu POSIX.
- **1 deselected**: `test_eval.py`, bị loại theo thiết kế (xem Phần C).

### Test mới thêm trong đợt này

| File | Số test | Nội dung |
|---|---|---|
| `test_srs_persistence.py` | 38 | Roundtrip, idempotent, cô lập theo kế hoạch, bỏ qua thẻ hỏng |
| `test_llm_decomposition.py` | 36 | Dùng kết quả LLM, quay về quy tắc khi LLM lỗi, kẹp giá trị số, slug tiếng Việt |
| `test_multi_round.py` | 29 | Công bố lại, chia nhỏ phạm vi, ghi rõ phần chưa ai nhận, không quá tải |
| `test_runtime.py` | 39 | Đồng thời thật (đo thời gian), cô lập lỗi, hết hạn chờ, tắt máy có chặn |
| `test_google_calendar.py` | 86 | PKCE, token, hàm chuyển lịch, đồng bộ idempotent, HTTP server localhost thật |
| `test_vector_memory.py` | 5 | Truy xuất ngữ nghĩa + chịu được phản hồi thiếu dữ liệu |
| `test_app.py` (bổ sung) | +13 | Google Calendar, kế hoạch đã lưu, thẻ SRS |
| `test_team.py` (cập nhật) | 1 đổi | Ngữ nghĩa mới của T3 (xem 6.3) |

Số test tăng từ **331** (trước đợt này) lên **582** (580 passed + 1 skipped + 1 eval).

---

## 6. Lỗi thật đã gặp và cách xử lý

Đây là phần đáng đọc nhất, vì mỗi lỗi đều là lỗi **hành vi** chứ không phải cú pháp.

### 6.1. Nhóm SRS

**Một thẻ hỏng làm mất tiến độ của tất cả thẻ còn lại.** `float("không phải số")` ném
`ValueError` và hủy cả lô ghi. Đã sửa: `_card_numbers()` trả `None` để **bỏ qua đúng
thẻ đó**, các thẻ khác vẫn được ghi.

**Kỳ vọng test sai, không phải code sai.** Tôi kỳ vọng khoảng ôn `[1, 6, 15]`, thực tế
`[1, 6, 16]`. SM-2 nhân với `ease` **cũ** (`round(6 × 2.7) = 16`) rồi mới cập nhật ease.
Đã sửa test và ghi lý do vào docstring.

### 6.2. Nhóm phân rã

**`_slug` nuốt mất chữ "Đ".** `unicodedata` NFD **không** tách được nét ngang của "Đ"
(U+0110) vì nó là một phần của ký tự, nên `encode("ascii", "ignore")` cho ra `oc` thay
vì `doc`. Đã sửa: thay `đ`/`Đ` thủ công **trước** khi chuẩn hoá. (`ơ`, `ư`, `ă` thì NFD
xử lý được.)

**Sinh id từ sai nguồn.** Khi `id` rỗng tôi lấy chính `id` làm nguồn slug thay vì lấy
`description`, nên mọi nhiệm vụ thiếu id đều thành `task-N`.

### 6.3. Nhóm thương lượng — thay đổi ngữ nghĩa có chủ ý

`test_roster_capacity_limits_concurrent_work` trước đây khẳng định nhiệm vụ thứ hai
**không ai nhận**. Nay nó **được giao một phần** (0.4/0.6). Đã cập nhật test đó và
**thêm** `test_roster_capacity_refuses_when_nothing_is_left` để vẫn có test cho trường
hợp hết sạch năng lực. Bất biến an toàn `load <= capacity` vẫn được kiểm chứng.

### 6.4. Nhóm runtime

**Agent "bỏ thầu" cho chính tin báo mình đã trúng thầu.** Handler được gọi cho *mọi*
tin nhắn, kể cả `ACCEPT_PROPOSAL`, nên bản ghi ACL có thừa một `PROPOSE` vô nghĩa.
Phát hiện khi đọc transcript trong demo CLI. Đã sửa bằng `RESPONDS_TO`: chỉ
`REQUEST`/`CRITIQUE` mới cần phản hồi.

**`stop()` treo vô hạn.** Test chạy 18,7s vì `stop()` chờ worker đang kẹt trong handler
5 giây. Một handler chờ mạng có thể giữ runtime treo mãi. Đã sửa: `stop(grace)` chờ có
chặn rồi **huỷ** worker còn kẹt.

**`timeout or self.timeout` âm thầm bỏ qua `timeout=0`.** `0` là giá trị hợp lệ (không
chờ ai) nhưng falsy, nên toán tử `or` thay bằng mặc định. Đã sửa thành kiểm tra `is None`.

### 6.5. Nhóm Google Calendar

**`events.insert` bỏ qua trường `status`.** Muốn huỷ sự kiện phải gọi `events.delete`.
Nếu chỉ đặt `status: "cancelled"` để đánh dấu buổi đã trượt thì Google bỏ qua, và người
dùng thấy buổi trượt y như buổi bình thường — **tệ hơn là không đánh dấu gì**. Đã
chuyển sang tiền tố `[Đã trượt]` trong tiêu đề, kèm test khẳng định **không** đặt
trường `status`.

**Google không trả lại `refresh_token` khi làm mới.** Không giữ token cũ thì lần chạy
sau mất quyền và người dùng phải đăng nhập lại. `token_from_response(previous=...)` xử
lý việc này.

**`_RedirectHandler` dùng biến lớp dùng chung.** Hai lần uỷ quyền chạy song song sẽ ghi
đè kết quả của nhau. Đã đổi thành handler riêng cho từng lần gọi.

### 6.6. Nhóm hạ tầng

**`mypy` sập với `INTERNAL ERROR: module 'psutil' has no attribute 'cpu_count'`.**
Nguyên nhân **không phải mã nguồn**: khi `uv` gỡ một gói, nó để lại thư mục cụt trong
`.venv` — `psutil/` còn `_psutil_windows.pyd` và `_pswindows.py` nhưng mất `__init__.py`.
Thư mục đó thành **namespace package** che mất gói thật.

**Commit message dính BOM.** PowerShell 5.1 ghi `-Encoding utf8` **kèm BOM**, nên commit
subject bắt đầu bằng U+FEFF. Đã phát hiện bằng cách đọc bytes thô của commit object
(`git cat-file commit`), vì `git log --format=%s` che mất ký tự này. Đã amend và từ đó
ghi message bằng `UTF8Encoding($false)`.

**`--delete-branch` phá nhánh xếp chồng.** Khi merge PR #1 với `--delete-branch`, GitHub
**tự đóng** PR #2 vì base branch của nó biến mất, và không cho mở lại hay đổi base của
PR đã đóng. Đã khắc phục bằng cách tạo lại con trỏ nhánh `feature/srs-persistence` tại
`7230612` (nội dung đã nằm trong `main`), rồi mở lại PR #2 và trỏ base về `main`. Các PR
sau đó merge **không** kèm `--delete-branch`.

---

## 7. Quyết định thiết kế đáng lưu ý

- **Không thêm thư viện cho OAuth.** Luồng authorization code + PKCE cho ứng dụng cài
  đặt chỉ cần `urllib` và `http.server` của thư viện chuẩn. Đổi lại: `uv sync` không phải
  kéo thêm vài chục MB phụ thuộc của Google, và **toàn bộ luồng kiểm thử được mà không
  cần mạng**.
- **Quyền tối thiểu.** Chỉ xin `calendar.events`, không xin đọc toàn bộ lịch.
- **Bộ điều phối chỉ nới công sức, không nới kỹ năng.** Giao việc ngoài chuyên môn còn tệ
  hơn để việc đó chưa ai làm, và nó che mất khoảng trống thật.
- **Kỹ năng lạ thì để lộ ra.** LLM có thể đề xuất kỹ năng không agent nào có; hệ thống
  giữ nguyên nhiệm vụ và báo "không ai nhận" thay vì gán bừa.
- **Ghi rõ phần chưa làm được.** `remaining_effort` và `partial` tồn tại để kế hoạch
  không trông "đủ người" khi thực tế thì chưa.
- **Merge bằng merge commit, không squash.** Với nhánh xếp chồng, squash sẽ làm PR kế
  tiếp hiện lại toàn bộ thay đổi của PR trước (vì commit gốc không còn là tổ tiên của
  `main`). Merge commit giữ nguyên quan hệ tổ tiên nên mỗi PR giữ đúng diff của mình.

---

## 8. Rủi ro còn lại

### Rủi ro cao

1. **Google Calendar chưa được xác minh đầu-cuối với Google thật.** Đã kiểm thử đầy đủ ở
   mức đơn vị (86 test, gồm cả HTTP server thật trên localhost), nhưng **chưa từng chạy
   với credentials thật**. Hãy coi là "đã viết xong, chưa xác minh đầu-cuối". Ba bước tự
   xác minh nằm trong README mục *Đồng bộ thẳng lên Google Calendar*.
2. **Token Google là mật khẩu.** `data/google_token.json` chứa refresh token, tức quyền
   truy cập lịch về sau mà không cần đăng nhập lại. Nằm trong `data/` (đã bị `.gitignore`
   chặn) và ghi với quyền 600 trên POSIX. **Trên Windows `chmod` gần như không có tác
   dụng**, nên đó là lớp phòng vệ thêm chứ không phải bảo đảm duy nhất.

### Rủi ro trung bình

3. **Chưa có CI.** Lint gate và test hiện chỉ chạy khi có người chạy tay. Một workflow
   GitHub Actions sẽ biến chúng thành rào chắn thật. Đây là việc tiếp theo đáng làm nhất.
4. **Giao diện Streamlit vẫn dùng đường đồng bộ.** `asyncio.run` trong vòng chạy script
   của Streamlit dễ xung đột với vòng lặp sẵn có, nên runtime bất đồng bộ chỉ dùng được
   qua `self_organize_async` hoặc `demo_run.py --async`. Đây là giới hạn đã ghi trong
   README, không phải chỗ bỏ quên.
5. **`mypy` không kiểm tra `tests/` và `scripts/`.** Lỗi kiểu trong test sẽ không bị bắt.
   Mở rộng phạm vi là việc làm được, nhưng cần dọn một lượng cảnh báo đáng kể trước.

### Rủi ro thấp (đã ghi trong README mục 10)

6. Lịch tuần 2 trở đi sinh theo công thức, không "thông minh" như tuần 1 do LLM lập.
7. Quiz chấm theo đáp án do LLM sinh, chưa kiểm chứng lại tính đúng của đáp án.
8. `tools/search.py` vẫn là stub.
9. Runtime agent chạy trong **một tiến trình**; chưa có hàng đợi bền (message broker) nên
   tin nhắn không sống qua lần khởi động lại.
10. Thương lượng chưa có **liên minh** giữa các agent: mỗi nhiệm vụ vẫn chỉ một agent nhận.
11. Học liên tục dựa trên tỉ lệ hoàn thành, chưa học từ nội dung phản hồi dạng văn bản.

---

## 9. Cách chạy

```powershell
uv sync                       # cài phụ thuộc (gồm ruff + mypy ở nhóm dev)
uv run pytest -q              # bộ test mặc định, không cần mạng
uv run pytest -q -m eval      # bài eval gọi LLM thật
uv run ruff check .           # lint
uv run mypy                   # kiểm tra kiểu
uv run streamlit run app.py   # giao diện
uv run python scripts/demo_run.py --help   # demo CLI
```
