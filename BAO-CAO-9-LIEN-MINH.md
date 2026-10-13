# Báo cáo: Liên minh agent cho việc lớn — MultiAgentPersonality

**Repo:** https://github.com/hienvanla5/MultiAgentPersonality
**Nhánh chính:** `main` — nay ở `fd4beb6` (trước đợt này: `3b0ec86`)
**Ngôn ngữ / Framework:** Python 3.12 + LangGraph + Pydantic v2 + Streamlit (quản lý bằng `uv`)
**Lệnh test:** `uv run pytest -q`
**Lệnh lint / build:** `uv run ruff check .` và `uv run mypy`
**Quy ước commit:** Conventional Commits, mô tả tiếng Việt **không dấu**
**Quy trình:** nhánh `feature/...` + Pull Request, không push thẳng `main`, không force push, merge bằng merge commit (không squash)

---

## Bước 1 — Khảo sát và đánh giá

### Kết luận: **CÓ MỘT PHẦN**

**ĐÃ CÓ** (nền tảng để dựa vào, không viết lại):

| Thành phần | Bằng chứng |
|---|---|
| Thương lượng nhiều vòng (nới công sức) | `contract_net.py` vòng lặp `MAX_ROUNDS = 3`; `_relax()` |
| Báo cáo trung thực phần chưa ai nhận | `ContractNetResult.remaining_effort`, `partial` |
| Lập nhóm theo kỹ năng | `team.py` `build_roster()`; `TeamPlan.partial`, `fully_covered` |
| Chạy thầu song song + luật trao thầu tất định | `map_parallel`; `pick_winner()` tách ra module **để runtime dùng lại** |

**CHƯA CÓ — lỗ hổng cần lấp.** Không có đường mã nào trao một nhiệm vụ cho **nhiều hơn một** agent:

- `ContractNetResult.awarded_to: str | None` — một chuỗi duy nhất
- `pick_winner()` trả về **đúng một** `Bid`: `sorted(bids, ...)[0]`
- Chỉ **một** agent được `accept()`: `awarded_agent.accept(task)`
- `assess()` **từ chối** nếu `task.effort > available` — nên agent chỉ nhận được *một phần* thậm chí không bao giờ bỏ thầu

README §10 tự nhận, nguyên văn: *"Chưa có **liên minh** giữa các agent: mỗi nhiệm vụ vẫn chỉ một agent nhận, chưa có nhóm agent cùng đứng ra nhận một việc lớn."* Và xếp nó **đầu** danh sách Hướng mở rộng.

**CÓ MỘT PHẦN:** hạ tầng *báo cáo* đã sẵn (`remaining_effort`, `partial`, `TeamPlan.partial`) và `_relax()` đã biết cách chia nhỏ phạm vi — nhưng nó **cắt bớt việc** thay vì **chia việc cho nhiều người**.

### Phát hiện quyết định thiết kế

Đã rà toàn bộ test hiện có: **không test nào có ≥2 agent cùng đủ chuyên môn mà thiếu năng lực cá nhân**. Các test nhiều agent đều rơi vào một trong hai loại: (a) chỉ 1 agent đủ chuyên môn, (b) tất cả từ chối vì kỹ năng. Nghĩa là liên minh **chỉ kích hoạt ở đúng tổ hợp chưa từng được kiểm** — nên toàn bộ hành vi cũ có thể giữ nguyên, và đó là điều đã xảy ra: **580 test cũ vẫn xanh, không phải sửa một dòng nào.**

---

## Bước 2 — Kế hoạch và chia nhỏ task

| ID | Mục tiêu | File | Test | DoD | Phụ thuộc |
|---|---|---|---|---|---|
| **T0** | Đưa `BAO-CAO-8-CI.md` (còn untracked) vào repo **qua PR riêng**, không push thẳng `main` | `BAO-CAO-8-CI.md` | — | PR merge xong, cây sạch | — |
| **T1** | Agent được phép nhận một phần nhiệm vụ | `agents/autonomy.py` | `test_coalition.py` | `assess(allow_partial=True)` bỏ thầu `share = available`; mặc định giữ nguyên hành vi cũ | T0 |
| **T2** | Ghép liên minh trong Contract Net đồng bộ | `agents/contract_net.py` | `test_coalition.py` | Việc 0.90 + ba agent 0.40 → phủ **0.90**, `remaining_effort = 0` | T1 |
| **T3** | Đường bất đồng bộ cũng có liên minh | `runtime.py` | `test_runtime.py` | Hai đường cho cùng kết quả liên minh | T2 |
| **T4** | Báo cáo liên minh trong kế hoạch nhóm + UI | `agents/team.py`, `app.py`, `scripts/demo_run.py` | `test_coalition.py`, `test_team.py` | `TeamPlan.coalitions`; `summary()` và UI nêu tên thành viên | T2 |
| **T5** | Ghi lại tính năng | `README.md` | — | §10 bỏ mục "chưa có liên minh"; thêm §2.2 | T2, T3, T4 |
| **T6** | Cổng kiểm tra đầy đủ | — | toàn bộ | `ruff` + `mypy` + `pytest` sạch; CI xanh cả 2 hệ điều hành | T5 |

**Thứ tự:** T0 → T1 → T2 → T3 → T4 → T5 → T6. Bốn commit trên một nhánh `feature/agent-coalitions` (T1+T2 chung vì T1 một mình không quan sát được hành vi).

---

## Bước 3 — Triển khai

### 3.1 Thiết kế: bốn nguyên tắc

1. **Một agent đủ sức thì vẫn một mình nhận trọn.** Liên minh chỉ là phương án dự phòng khi không ai nhận trọn được — chia một việc mà một người làm gọn cho ba người chỉ thêm chi phối hợp.
2. **Agent tự quyết, bộ điều phối không áp đặt.** Vòng liên minh vẫn là *công bố lại* để agent tự bỏ thầu phần mình nhận. Đây là nguyên tắc cốt lõi đã ghi ở đầu `contract_net.py`.
3. **Chỉ liên minh trong phạm vi chuyên môn.** Không bao giờ gán việc ngoài kỹ năng cho bất kỳ thành viên nào.
4. **Không bao giờ quá tải.** Phần mỗi agent nhận ≤ năng lực còn trống của chính nó.

### 3.2 Diễn biến các vòng

| Vòng | Công bố | Ai bỏ thầu | Kết quả |
|---|---|---|---|
| 1 | Nhiệm vụ trọn (0.90), **không** cho nhận một phần | Chỉ agent đủ sức nhận trọn | Như trước |
| 2 | Vẫn nhiệm vụ trọn, **cho phép nhận một phần** | Agent đủ chuyên môn còn năng lực, bỏ thầu phần mình nhận được | Ghép liên minh |
| 3 | Chia nhỏ phạm vi (`_relax`, như trước) | Agent tốt nhất | Chỉ chạy khi vòng 2 không ai thầu |

**Vì sao vòng 2 đứng trước vòng 3:** liên minh phủ được **nhiều hơn hoặc bằng** việc cắt bớt phạm vi. Với ví dụ 3×0.40: liên minh phủ 0.90 (trọn vẹn), cắt phạm vi chỉ phủ 0.40.

**Vì sao không xếp chồng** (liên minh một phần rồi cắt nhỏ phần còn lại): liên minh đã vét hết các agent sẵn lòng, nên `_relax` vòng 3 sẽ thấy "cả nhóm đã kín lịch" và trả `None`. Xếp chồng hầu như không tăng độ phủ mà làm sổ sách khó đọc. Đây là **giới hạn có chủ ý**, đã ghi vào README §10.

### 3.3 Mô hình dữ liệu — giữ tương thích ngược

```python
class CoalitionShare(BaseModel):
    """Phần công sức một agent nhận trong một liên minh."""
    agent: str
    effort: float = Field(gt=0.0, le=1.0)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    reason: str = ""
```

- `Bid` thêm `share: float = 0.0`. `assess()` **luôn** đặt `share = task.effort` khi nhận trọn, `= available` khi nhận một phần. `share = 0` (thầu dựng tay trong test cũ) được coi là **nhận trọn** qua helper `share_of(bid, task)` — quy tắc tương thích ngược, có ghi chú lý do và có test riêng.
- `RoundRecord` thêm `coalition: list[CoalitionShare]` + property `is_coalition`.
- `ContractNetResult` thêm `coalition`; **giữ nguyên `awarded_to: str | None` là trường** (nhiều nơi ghi vào nó) và nó mang nghĩa **trưởng nhóm**. Thêm property `is_coalition` và `members`.
- `agreed_effort` sửa để cộng phần của liên minh.

### 3.4 Hai hàm dùng chung ở mức module

Đặt cùng chỗ với `pick_winner`/`no_winner_reason` để `runtime.py` dùng lại **đúng luật**, không chép:

```python
def can_form_coalition(task, candidates) -> bool:
    # đủ chuyên môn, available >= MIN_SLICE_EFFORT
    # cần >= 2 người; nếu một người đã đủ sức nhận trọn thì False
    # tổng khả năng phải > khả năng người giỏi nhất (nếu không thì liên minh vô nghĩa)

def plan_award(task, bids) -> tuple[str | None, list[CoalitionShare]]:
    # 1. Có thầu nhận TRỌN  -> chọn một người bằng pick_winner (giữ nguyên hành vi cũ)
    # 2. Không có           -> ghép liên minh tham lam, thứ tự (-score, cost, agent)
    #    >= 2 thành viên    -> trả (trưởng nhóm, danh sách phần)
    #    < 2 thành viên     -> quay về một người như cũ
```

### 3.5 Đường bất đồng bộ không lệch luật

Repo có nguyên tắc rõ: *"hai đường chạy mà lệch luật thì kết quả sẽ khác nhau"*. Nên:

- `negotiate(..., max_rounds=...)` và vòng liên minh khi `can_form_coalition` đúng.
- Tách thân một vòng ra `_negotiate_once()` để gọi lại lần hai với `allow_partial=True`, thay vì chép lại toàn bộ thân hàm.
- Cờ `allow_partial` đi **theo tin nhắn** (`metadata`), `_handle()` đọc rồi truyền xuống `assess()`; `_respond()` ghi thêm `share` để bên gom dựng lại đúng `Bid`.
- `rounds` nay được ghi ở đường này (trước luôn rỗng).

---

## Bước 4 — Kiểm tra tổng thể

Trên `main` sau khi merge (`fd4beb6`):

```
uv run ruff check .   ->  All checks passed!
uv run mypy           ->  Success: no issues found in 38 source files
uv run pytest -q      ->  609 passed, 1 skipped, 1 deselected  (36 giây)
```

`git status` sạch, `HEAD` khớp `origin/main`.

Và **trên runner thật của GitHub** (log trích nguyên văn):

```
Lint và kiểm tra kiểu  Ruff    All checks passed!
Lint và kiểm tra kiểu  Mypy    Success: no issues found in 38 source files
Test (ubuntu-latest)           610 passed, 1 deselected in 32.16s
Test (windows-latest)          609 passed, 1 skipped, 1 deselected in 71.13s
```

Ubuntu **610 passed, 0 skipped**; Windows **609 passed, 1 skipped** — cùng 611 test. Trên Linux test quyền POSIX 600 chạy thật, trên Windows nó bị skip. Khác biệt này là lý do CI chạy cả hai hệ điều hành (xem báo cáo CI).

| Job | Kết quả |
|---|---|
| `Lint và kiểm tra kiểu` | ✓ pass (32s) |
| `Test (ubuntu-latest)` | ✓ pass (48s) |
| `Test (windows-latest)` | ✓ pass (2m12s) |

Cả 4 lần chạy CI của đợt này đều **success**, gồm cả lần `push` lên `main` (xác nhận trigger `push` hoạt động):

| Run | Nhánh | Sự kiện | Kết quả |
|---|---|---|---|
| `38325297856` | `docs/bao-cao-ci` | `pull_request` | ✓ 1m25s |
| `38325441194` | `main` | `push` | ✓ 1m50s |
| `38327116446` | `feature/agent-coalitions` | `pull_request` | ✓ 1m39s |
| `38328004697` | `main` | `push` | ✓ 2m15s |

### Kiểm chứng số học, không chỉ "test xanh"

Ca then chốt (việc 0.90, ba agent mỗi người còn 0.40) chạy thật và in ra:

```
awarded_to        : a
is_coalition      : True
thanh vien        : [('a', 0.4), ('b', 0.4), ('c', 0.1)]
tong phan         : 0.9
original_effort   : 0.9
agreed_effort     : 0.9
remaining_effort  : 0.0
partial           : False
round_count       : 2
tai tung nguoi    : [('a', 0.4), ('b', 0.4), ('c', 0.1)]
ly do             : liên minh 3 agent nhận 0.90/0.90 công sức (a 0.40 + b 0.40 + c 0.10)
```

Tải từng người đúng bằng phần nhận, tổng 0.90, không ai vượt năng lực.

---

## Bước 5 — Push và Pull Request

Cả hai PR đã merge vào `main`. Không PR nào còn mở. Không push thẳng `main`, không force push, không squash.

| PR | Tiêu đề | Kết quả |
|---|---|---|
| [#10](https://github.com/hienvanla5/MultiAgentPersonality/pull/10) | `docs: them bao cao tinh nang CI GitHub Actions` | merged |
| [#11](https://github.com/hienvanla5/MultiAgentPersonality/pull/11) | `feat(agents): lien minh agent cho viec lon` | merged |

### Danh sách commit

| Hash | Commit | PR |
|---|---|---|
| `c276de9` | `docs: them bao cao tinh nang CI GitHub Actions` | #10 |
| `3b0ec86` | Merge pull request #10 | #10 |
| `5b3d389` | `feat(agents): ghep lien minh khi mot agent khong du suc nhan tron` | #11 |
| `0267c55` | `feat(runtime): ho tro lien minh tren duong bat dong bo` | #11 |
| `3f18772` | `feat(team): bao cao lien minh trong ke hoach nhom va giao dien` | #11 |
| `6b95fda` | `docs: ghi lai tinh nang lien minh agent` | #11 |
| `fd4beb6` | Merge pull request #11 | #11 |

**Phạm vi thay đổi** (`3b0ec86...fd4beb6`): 9 file, +1.134 / −83.

### Một sự cố lịch sử đã tự sửa

Commit T3 (`feat(runtime)`) ban đầu **thiếu** một thay đổi thuộc về nó: việc đổi `_single_reason` thành `single_reason` ở mức module (để `runtime.py` import được). Commit đó vì thế **không tự chạy được** — `runtime.py` import một tên không tồn tại ở commit ấy.

Phát hiện qua `git status` sau khi commit T5. Đã sửa bằng `git commit --fixup` + `git rebase --autosquash`, rồi **kiểm chứng lại bằng git worktree**: checkout đúng commit T3 và import `lifeos.runtime` → `T3 import OK`. Lịch sử giờ không còn commit nào hỏng, và mỗi commit đều tự nhất quán.

---

## Bước 6 — Báo cáo cuối cùng

### Vấn đề, bằng con số cụ thể

Việc 0.90 công sức, ba agent mỗi người còn 0.40 năng lực:

| | Trước | Sau |
|---|---|---|
| Phạm vi giao được | 0.40 / 0.90 | **0.90 / 0.90** |
| Chưa ai nhận | 0.50 | **0.00** |
| `partial` | `True` | **`False`** |

Nhóm **thừa sức** làm trọn (0.40 × 3 = 1.20) nhưng hệ thống cũ vẫn cắt mất hơn nửa công việc rồi báo "chưa ai nhận".

### Hai cái bẫy số thực — chỗ dễ sai âm thầm nhất

Đây là phần đáng đọc nhất của báo cáo, vì cả hai đều **không** làm test nào đỏ.

**1. Ngưỡng `MIN_SLICE_EFFORT` phải trừ dung sai.** Mảnh cuối của một nhiệm vụ hay ra `0.09999999999999998` do số thực. Đem so thẳng với `0.1` thì nó **bị loại oan**, liên minh thiếu đúng một mảnh và không phủ được trọn việc — trong khi mọi test nhỏ vẫn xanh. Đã sửa thành `take < MIN_SLICE_EFFORT - _EPS` và viết test riêng cho ca này.

**2. `agreed_effort` phải cộng phần của liên minh.** Nếu vẫn lấy công sức của vòng cuối thì một liên minh phủ `0.60/0.90` sẽ bị báo thành `0.90` — **sai theo hướng lạc quan**, đúng loại lỗi khó phát hiện nhất vì trông như đang làm tốt hơn thực tế.

### Ba lỗi khác đã bắt được trong quá trình làm

- **`mypy` bắt lỗi biến trùng tên** trong hai vòng lặp liền nhau (`portion` là `float` ở vòng này, `float | None` ở vòng kia), khiến nhánh `is None` thành không bao giờ tới. Sửa thành `if agent.key not in portions: continue`.
- **Test của tôi sai giả định về `broadcast`**: nó gửi **một tin cho mỗi người nhận**, nên 3 agent × 2 vòng = 6 tin `REQUEST`, không phải 2. Sửa test (không sửa mã) và nhân đó kiểm tra luôn cờ `allow_partial` ở từng vòng.
- **Commit T3 không tự chạy được** — xem Bước 5.

### Cách kiểm chứng lại

```powershell
uv run python scripts/demo_run.py --coalition --skip-adjust   # [14] liên minh
uv run python scripts/demo_run.py --negotiate --skip-adjust   # [12] chỉ 1 agent -> cắt phạm vi
```

Hai mục này cố ý đặt cạnh nhau: ở `[12]` chỉ có **một** agent nên cách duy nhất là cắt bớt phạm vi; ở `[14]` cả nhóm cộng lại đủ sức nên **không phải cắt gì**. Khác biệt đó chính là giá trị của tính năng.

### Rủi ro còn lại

1. **Không có trưởng nhóm điều phối nội bộ.** Các thành viên nhận phần của mình rồi thôi, chưa có ai tổng hợp kết quả giữa họ. Với một việc thật, ba người làm ba phần rời rạc vẫn cần người ghép lại — hiện chưa có.
2. **Không có thành viên vào/ra giữa chừng.** Một người làm không xong thì phần đó chưa được thương lượng lại; `finish(success=False)` chỉ hạ độ tin cậy.
3. **Mọi thành viên phải cùng một kỹ năng.** Chưa chia được một mục tiêu thành các việc khác chuyên môn để nhiều loại agent cùng nhận.
4. **Đường bất đồng bộ chưa có vòng cắt phạm vi** (`_relax`) như đường đồng bộ. Liên minh đã có ở cả hai và cho cùng kết quả (có test đối chiếu), nhưng nếu một việc vừa không ai nhận trọn vừa không ghép được liên minh thì đường bất đồng bộ dừng, còn đường đồng bộ còn một vòng chia nhỏ nữa. **Đây là bất đối xứng thật giữa hai đường chạy** và đã ghi rõ trong README §10.
5. **Ghép liên minh là tham lam, không tối ưu.** `plan_award` lấy dần theo thứ tự `(-score, cost, agent)`. Nó tất định và đủ tốt cho quy mô này, nhưng không đảm bảo dùng ít người nhất.
6. **Giới hạn cũ vẫn nguyên:** Google Calendar OAuth chưa xác minh đầu-cuối với Google (rủi ro cao nhất), `tools/search.py` còn stub, quiz chấm theo đáp án LLM sinh chưa kiểm chứng lại, lịch tuần 2+ sinh theo công thức.
7. **CI chưa chặn merge** — không có branch protection rule nào bắt buộc. Đây vẫn là việc đáng làm tiếp nhất, như đã nêu ở báo cáo CI.

### Đề xuất cải tiến

- **Trưởng nhóm điều phối trong liên minh** — bước tiếp theo tự nhiên, và README đã ghi vào Hướng mở rộng.
- **Bù bất đối xứng giữa hai đường chạy**: thêm vòng `_relax` cho `runtime.py`, hoặc ghi rõ trong tài liệu rằng đường bất đồng bộ cố ý đơn giản hơn.
- **Bật required status checks cho `main`** (rủi ro 7).
