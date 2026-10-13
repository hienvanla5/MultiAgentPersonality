# Báo cáo: CI GitHub Actions — MultiAgentPersonality

**Repo:** https://github.com/hienvanla5/MultiAgentPersonality
**Nhánh chính:** `main` — nay ở `2a21cc3` (trước đợt này: `2143e1a`)
**Ngôn ngữ / Framework:** Python 3.12 + LangGraph + Pydantic v2 + Streamlit (quản lý bằng `uv`)
**Lệnh test:** `uv run pytest -q`
**Lệnh lint / build:** `uv run ruff check .` và `uv run mypy` (đã có từ trước đợt này)
**Quy ước commit:** Conventional Commits, mô tả tiếng Việt **không dấu**
**Quy trình:** nhánh `feature/...` + Pull Request, không push thẳng `main`, không force push

---

## Bước 1 — Khảo sát và đánh giá

### Kết luận: **CHƯA CÓ**

Bằng chứng:

```
$ Test-Path ".github"
False

$ gh api repos/astral-sh/setup-uv/...        # không có file workflow nào để đọc
```

Repo **không có CI nào**: không thư mục `.github/`, không file workflow, không badge.
`ruff`, `mypy` và `pytest` đã tồn tại (thêm ở PR #6 và #7), nhưng **không có gì bắt buộc
chạy chúng** — một commit có thể lên `main` mà chưa từng được kiểm.

Đây chính là rủi ro tôi đã tự ghi vào báo cáo trước, nguyên văn:

> **Chưa có CI.** Lint gate và test hiện chỉ chạy khi có người chạy tay. Một workflow
> GitHub Actions sẽ biến chúng thành rào chắn thật. Đây là việc tiếp theo đáng làm nhất.

Ngoài ra, khảo sát phát hiện `.gitattributes` đã có `* text=auto eol=lf` — nghĩa là dấu
xuống dòng đã được chuẩn hoá về LF, nên không cần xử lý gì thêm cho CI trên Linux.

---

## Bước 2 — Kế hoạch và chia nhỏ task

| ID | Task | Mục tiêu | File | Test / kiểm chứng | DoD | Phụ thuộc |
|---|---|---|---|---|---|---|
| **C1** | Khảo sát + xác minh giả định | Xác nhận CI chưa có; xác minh tag và tên input của action **từ nguồn thật** thay vì viết theo trí nhớ | — | `Test-Path`, `git ls-remote --tags`, đọc `action.yml` thật | Có bằng chứng cho mọi giả định về action | — |
| **C2** | Viết workflow | Hai job `lint` và `test`, chạy trên Ubuntu + Windows | `.github/workflows/ci.yml` | Parse YAML; `uv lock --check` | File hợp lệ, `--locked` thoả | C1 |
| **C3** | Kiểm chứng trên Linux sạch | Chạy đúng các bước CI trên Linux **trước khi push**, không lấy `.venv` của máy dev | — | `uv sync --locked`, `ruff`, `mypy`, `pytest`, đo flaky 3 lần | Tất cả pass trên Linux | C2 |
| **C4** | Ghi lại quyết định | Badge + mục 6.3 giải thích lựa chọn | `README.md` | Đọc lại | Người sau không phải đoán lý do | C2 |
| **C5** | Push + PR + merge | Nhánh `feature/...`, PR, chờ CI trên runner thật rồi merge | — | `gh pr checks --watch` | 3/3 job xanh | C3, C4 |
| **C6** | Sửa tiếp từ log CI | Log lần chạy đầu có 2 cảnh báo; đọc kỹ, sửa cái đáng sửa, giải thích cái không | `.github/workflows/ci.yml` | Chạy lại CI, xác minh cảnh báo biến mất | Cảnh báo tranh cache hết | C5 |

**Thứ tự thực hiện:** C1 → C2 → C3 → C4 → C5 → C6. C6 chỉ ra đời **sau khi đọc log CI thật**
— nó không nằm trong kế hoạch ban đầu, và đó chính là giá trị của việc có CI.

---

## Bước 3 — Triển khai

### C1. Xác minh giả định trước khi viết

Hai giả định dễ sai, nên tôi kiểm tra bằng nguồn thật:

**`astral-sh/setup-uv` không có tag nổi theo số major.** Khác `actions/checkout` (có cả
`v7` **lẫn** `v7.0.1`), action này chỉ có `v10.3.0`, `v10.2.0`, …:

```
$ git ls-remote --tags https://github.com/astral-sh/setup-uv.git
KHONG refs/tags/v10$
KHONG refs/tags/v9$
CO    refs/tags/v10.3.0$
```

Nên `@v10` sẽ **không resolve**. Đã ghim `v10.3.0`.

**Tên input.** Tôi đọc `action.yml` của đúng tag `v10.3.0` để lấy tên input thật
(`python-version`, `enable-cache`, `cache-python`, `save-cache`) thay vì viết theo trí nhớ.

### C2. Workflow

`.github/workflows/ci.yml`:

| Job | Chạy trên | Nội dung |
|---|---|---|
| `lint` | `ubuntu-latest` | `uv run ruff check .` và `uv run mypy` |
| `test` | `ubuntu-latest` **và** `windows-latest` | `uv run pytest -q` |

Kèm: `permissions: contents: read` (quyền tối thiểu), `concurrency` huỷ lần chạy cũ khi
push liên tiếp, `timeout-minutes: 20`, `fail-fast: false`, và `uv sync --locked`.

**Vì sao chạy cả Windows lẫn Ubuntu.** Máy phát triển là Windows nên mã có những nhánh
**chỉ Windows mới đi qua** (`os.name == "nt"`, `os.chmod` không thực thi bit quyền kiểu
POSIX); nhưng nơi triển khai thật gần như chắc chắn là Linux. Chỉ chạy một trong hai thì
một nửa số nhánh đó không bao giờ được kiểm. Sự khác biệt này **đo được**:

```
Ubuntu  :  581 passed, 1 deselected          (0 skipped)
Windows :  580 passed, 1 skipped, 1 deselected
```

Cùng 582 test. Trên Linux, test quyền POSIX 600 **chạy thật và pass**; trên Windows nó bị
skip — đúng cái nhánh mà chỉ Ubuntu kiểm được.

### C3. Kiểm chứng trên Linux sạch trước khi push

Push một workflow chưa từng chạy là đoán. Nên tôi dựng môi trường Linux sạch (WSL Ubuntu,
Python 3.12.3), **không lấy `.venv` của máy dev**, chép mã nguồn sang, cài `uv` từ đầu rồi
chạy đúng từng bước như trong workflow:

```
uv sync --locked        -> 132 gói, build được lifeos
uv run ruff check .     -> All checks passed
uv run mypy             -> Success: no issues found in 38 source files
uv run pytest -q        -> 581 passed, 1 deselected (69 giây)
```

Vì `test_runtime.py` có test **đo thời gian thật** (`elapsed < 0.30s` cho 3 tác vụ ngủ
`0.15s`), tôi chạy riêng nó **3 lần** để kiểm tra flaky — pass cả 3.

### C4. README

Badge CI ở đầu file và mục **6.3. CI trên GitHub Actions**, ghi rõ ba quyết định: vì sao
chạy cả hai hệ điều hành, vì sao ghim `v10.3.0` chứ không `@v10`, vì sao dùng `--locked`.

---

## Bước 4 — Kiểm tra tổng thể

Trên `main` sau khi merge (`2a21cc3`):

```
uv run ruff check .   ->  All checks passed!
uv run mypy           ->  Success: no issues found in 38 source files
uv run pytest -q      ->  580 passed, 1 skipped, 1 deselected  (43 giây)
```

`git status` sạch, `HEAD` khớp `origin/main`.

Và **trên runner thật của GitHub** — đây mới là phần kiểm chứng của một workflow:

| Job | Thời lượng | Kết quả |
|---|---|---|
| `Lint và kiểm tra kiểu` | 28s | ✓ pass |
| `Test (ubuntu-latest)` | 43s | ✓ pass |
| `Test (windows-latest)` | 1m21s | ✓ pass |

Log thật, trích nguyên văn:

```
Lint và kiểm tra kiểu  Ruff    All checks passed!
Lint và kiểm tra kiểu  Mypy    Success: no issues found in 38 source files
Test (ubuntu-latest)   Chạy test   581 passed, 1 deselected in 25.42s
Test (windows-latest)  Chạy test   580 passed, 1 skipped, 1 deselected in 48.40s
```

Số liệu này **khớp chính xác** với dự đoán từ môi trường WSL ở bước C3.

**Cả 4 lần chạy CI đều success**, gồm cả lần `push` lên `main` (xác nhận trigger `push`
hoạt động, không chỉ `pull_request`):

| Run | Nhánh | Sự kiện | Kết quả |
|---|---|---|---|
| `38014766800` | `feature/github-actions-ci` | `pull_request` | ✓ 1m20s |
| `38014892682` | `main` | `push` | ✓ 1m29s |
| `38015181279` | `fix/ci-cache-race` | `pull_request` | ✓ 1m24s |
| `38015303285` | `main` | `push` | ✓ 1m28s |

---

## Bước 5 — Push và Pull Request

Cả hai PR đã merge vào `main`. Không PR nào còn mở. Không push thẳng `main`, không force
push, không squash (merge commit để giữ quan hệ tổ tiên).

| PR | Tiêu đề | Kết quả |
|---|---|---|
| [#8](https://github.com/hienvanla5/MultiAgentPersonality/pull/8) | `ci(github): them workflow chay lint, kiem tra kieu va test` | merged |
| [#9](https://github.com/hienvanla5/MultiAgentPersonality/pull/9) | `ci(github): tat ghi cache o job lint va ghi ro hai canh bao vo hai` | merged |

### Danh sách commit

| Hash | Commit | PR |
|---|---|---|
| `afe149c` | `ci(github): them workflow chay lint, kiem tra kieu va test` | #8 |
| `1b08682` | `docs: ghi lai CI trong README va them badge` | #8 |
| `26fa895` | Merge pull request #8 | #8 |
| `00458d6` | `ci(github): tat ghi cache o job lint va ghi ro hai canh bao vo hai` | #9 |
| `2a21cc3` | Merge pull request #9 | #9 |

---

## Bước 6 — Báo cáo cuối cùng

### Phát hiện quan trọng nhất: CI đã tự tìm ra lỗi trong chính cấu hình CI

Lần chạy đầu tiên pass cả 3 job nhưng log có **hai cảnh báo**. Tôi đọc kỹ từng cái thay vì
đoán, và kết luận **một cái đáng sửa, một cái không nên sửa**. Đây là phần đáng đọc nhất
của báo cáo.

**Cảnh báo 1 — đáng sửa, đã sửa.**

```
! Failed to save: Unable to reserve cache with key setup-uv-2-x86_64-unknown-linux-gnu-
  ubuntu-24.04-3.12-py-10dc9212..., another job may be creating this cache.
```

Job `lint` và `test (ubuntu-latest)` cài **đúng bộ phụ thuộc giống hệt nhau** nên dùng
chung một khoá cache, dẫn đến tranh nhau ghi — một job mất lượt lưu. Sửa bằng
`save-cache: "false"` ở job `lint`: `test` lo việc ghi, `lint` chỉ đọc lại. Không mất gì
vì nội dung cache là như nhau.

Đã xác minh sau khi sửa: `Unable to reserve: False`.

**Cảnh báo 2 — KHÔNG nên sửa, và đây là chỗ tôi suýt làm sai.**

```
! Python cache path /home/runner/work/_temp/uv-python-dir does not exist on disk.
  Skipping Python cache save because no managed Python installation was found.
```

Cảnh báo này **gợi ý sẵn cách sửa**: đặt `UV_PYTHON_PREFERENCE=only-managed`. Tôi đã thử:

```powershell
$ uv python find 3.12                          # mặc định
E:\personal_project\multi-agent-personality\.venv\Scripts\python.exe

$ $env:UV_PYTHON_PREFERENCE = "only-managed"
$ uv python find 3.12
error: No interpreter found for Python 3.12 in virtual environments or managed
installations
```

Nhưng "cách sửa" đó **không đáng làm**: nó buộc uv **tải Python mỗi lần chạy** mà **không
đổi phiên bản Python thực dùng** — vì `python-version: "3.12"` đã bảo đảm đúng 3.12 bất kể
image. Thêm một bước tải ~30MB chỉ để một cảnh báo biến mất là đánh đổi sai.

Và cảnh báo này **tự khỏi**: trên `ubuntu-24.04` Python 3.12 có sẵn trong image nên uv
dùng bản hệ thống; khi `ubuntu-latest` chuyển sang Ubuntu 26 (log nói **19/10/2026**), bản
hệ thống không còn 3.12, uv sẽ tự tải Python 3.12 do nó quản lý, và cảnh báo biến mất.

Thay vì sửa, tôi **ghi lại lý do** trong file để người đọc log sau không phải tra cứu lại.

### Những cái bẫy khác đã xử lý

- **`setup-uv` không có tag nổi `v10`** → ghim `v10.3.0`, xác minh bằng `git ls-remote`.
- **Tên input của action** → đọc từ `action.yml` thật, không viết theo trí nhớ.
- **`--locked`** → kiểm tra `uv lock --check` trả 0 trước khi dùng, để job không đỏ vì lý
  do không liên quan.
- **Commit message dính BOM** (bệnh cũ của PowerShell 5.1) → đã kiểm tra bằng cách đọc
  bytes thô của commit object; cả 3 commit đợt này đều sạch.
- **`.github` không bị `.gitignore` chặn** → xác minh bằng `git check-ignore`.

### Rủi ro còn lại

1. **Phiên bản `uv` không được ghim.** `setup-uv` không có input `version` nên lấy bản mới
   nhất; máy dev đang dùng `0.11.18`, WSL cài `0.13.0`. Bộ **phụ thuộc** vẫn tái lập được
   vì `uv.lock` ghim chúng và `--locked` chặn lệch, nhưng bản thân `uv` thì trôi. Ghim được
   bằng `[tool.uv] required-version` trong `pyproject.toml` — chưa làm vì nó sẽ **chặn cả
   máy dev** nếu bản `uv` ở đó không khớp.
2. **Test đo thời gian vẫn là test đo thời gian.** `test_agents_run_concurrently_not_sequentially`
   cho ngân sách `0.30s` cho 3 tác vụ ngủ `0.15s` — biên 2×. Đã pass trên Windows, Linux và
   runner CI. Nhưng trên runner quá tải nó vẫn có thể đỏ. Nếu đỏ, cách sửa đúng là **nâng
   ngân sách**, không phải xoá test.
3. **`ubuntu-latest` sẽ chuyển sang Ubuntu 26 ngày 19/10/2026** (9 ngày kể từ hôm nay).
   Về mặt Python thì an toàn (uv tự lo 3.12), nhưng image mới có thể đổi thứ khác. Nếu muốn
   ổn định tuyệt đối thì ghim `ubuntu-24.04`.
4. **CI chưa chặn merge trên GitHub.** Workflow chạy và báo đỏ, nhưng không có branch
   protection rule nào bắt buộc. Muốn biến nó thành rào chắn cứng thì cần bật required
   status checks trong Settings → Branches. **Đây là việc tiếp theo đáng làm nhất.**
5. **Eval chưa chạy trên CI** — cố ý, vì cần secret `LLM_API_KEY` mà repo chưa có; một
   workflow không chạy được thì chỉ là mã chết. Cách thêm đã ghi trong README mục 6.3.
6. **7 nhánh `feature/*` cũ trên remote vẫn còn** (đã merge hết, xoá được an toàn). Giữ lại
   vì lần trước `--delete-branch` gây sự cố với nhánh xếp chồng.

### Đề xuất cải tiến

- Bật **required status checks** cho `main` (rủi ro 4) — biến CI từ "báo cáo" thành "cổng".
- Cân nhắc `ruff format --check` như một bước riêng, **một PR riêng** vì nó sẽ tạo diff
  định dạng lớn làm nhiễu review.
- Cân nhắc job `coverage` nếu muốn theo dõi độ phủ theo thời gian.
