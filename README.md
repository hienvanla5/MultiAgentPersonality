# Life OS — multi-agent personality

Hệ **multi-agent** đồng hành cùng một mục tiêu cá nhân, xuyên suốt ba lĩnh vực:
**nghề nghiệp → học tập → lịch tuần**. Mỗi agent có **tính cách riêng**, và toàn bộ
giọng điệu **thích nghi theo hồ sơ người dùng**.

Kịch bản demo: *"Chuyển từ hành chính sang Data Analyst trong 6 tháng, vẫn đi làm
full-time."*

Không chỉ dừng ở lập kế hoạch: hệ thống còn sinh **lịch nhiều tuần**, **theo dõi
tiến độ**, **ôn tập cách quãng**, **kiểm tra hiểu biết**, và **xuất `.ics`** để
đưa vào Google Calendar.

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
**kiểm tra hiểu biết** và nút **tải `.ics`**. Các cờ CLI tương ứng ở [mục 7](#7-sau-khi-có-kế-hoạch-lịch-dài-tiến-độ-ôn-tập-kiểm-tra).

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
├── progress.py          # theo dõi tiến độ trên lịch nhiều tuần
├── persistence.py       # lưu/khôi phục/liệt kê kế hoạch
├── srs.py               # ôn tập cách quãng (SM-2)
├── personas/
│   ├── base.py          # lớp Persona
│   ├── registry.py      # 6 persona
│   └── tone_adapter.py  # UserProfile → chỉ thị giọng điệu
├── agents/              # career, curriculum, scheduler, tutor, critic, nudger, orchestrator
├── memory/
│   ├── store.py         # SQLite: lưu kế hoạch & sự kiện điều chỉnh
│   └── vector.py        # Chroma: truy xuất ngữ nghĩa
└── tools/
    └── calendar.py      # parse/ghi ICS, phát hiện & dịch khỏi khoảng bận
```

---

## 6. Test

```powershell
uv run pytest -q
```

- `test_personas.py` — persona + tone adapter + câu hỏi làm rõ
- `test_calendar.py` — parse ICS, khoảng bận, dịch giờ
- `test_scheduler.py` — ngân sách giờ, tránh khoảng bận, chuẩn hoá
- `test_program.py` — phân bổ module theo tuần + sinh lịch nhiều tuần không cần LLM
- `test_progress.py` — đánh dấu buổi học, % hoàn thành, streak, đúng/chệch tiến độ
- `test_persistence.py` — lưu, khôi phục, cập nhật và liệt kê kế hoạch
- `test_ics_export.py` — xuất `.ics`, ánh xạ tuần → ngày thật, đọc lại được
- `test_srs.py` — giãn khoảng cách SM-2, reset khi quên, chặn trên/dưới
- `test_quiz.py` — quiz nhiều câu, chấm điểm, phát hiện chủ đề yếu
- `test_llm.py` — trích JSON chịu lỗi + cascade structured output
- `test_graph.py` — tích hợp: lập kế hoạch, vòng giảm tải, điều chỉnh, lưu trữ
- `test_app.py` — giao diện Streamlit qua `AppTest` (chạy offline)
- `test_eval.py` — **LLM-as-judge** chấm `coherence` + `tone_fit`
  (tự động bỏ qua nếu chưa có `LLM_API_KEY`)

Test dùng `FakeLLM` tất định nên chạy nhanh và không tốn API. Riêng `test_eval.py`
gọi API thật và mất vài phút — đó là bài kiểm chứng end-to-end duy nhất chạm
endpoint thật.

---

## 7. Sau khi có kế hoạch: lịch dài, tiến độ, ôn tập, kiểm tra

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

## 8. Xử lý tình huống lệch kế hoạch

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

## 9. Giới hạn của MVP

- Giao diện và nội dung mẫu bằng **tiếng Việt**.
- Lịch nhiều tuần sinh theo **công thức** cho tuần 2 trở đi: đúng ngân sách giờ
  và thứ tự module, nhưng không "thông minh" như tuần 1 do LLM lập.
- Xuất `.ics` được, nhưng **chưa có OAuth** Google Calendar (import thủ công).
- `tools/search.py` còn là stub.
- Thẻ ôn tập chưa được lưu xuống SQLite — mới tồn tại trong phiên làm việc.
- Quiz chấm theo **đáp án cố định** do LLM sinh, chưa kiểm chứng lại tính đúng
  của đáp án đó.

**Hướng mở rộng:** gắn Google Calendar qua OAuth, lưu thẻ SRS, thêm agent luyện
phỏng vấn, nhiều mục tiêu song song, và bộ test eval lớn hơn.

---

## 10. Giấy phép

MIT — xem [LICENSE](LICENSE).
