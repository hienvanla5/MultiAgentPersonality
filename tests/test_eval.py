"""Eval bằng LLM-as-judge: gọi API thật, mặc định bị loại khỏi bộ test.

Chấm hai tiêu chí:
- coherence: lộ trình có mạch lạc, deadline có khả thi không?
- tone_fit: giọng điệu có khớp hồ sơ người dùng không?

Bài này khác mọi bài còn lại ở chỗ nó phụ thuộc mạng, API key và quota. Vì vậy:

- được đánh dấu `eval` và **bị loại khỏi `uv run pytest -q` mặc định**, để bộ test
  mặc định luôn tất định và không cần mạng;
- chạy riêng bằng `uv run pytest -q -m eval`;
- tự thử lại khi lời gọi **ném lỗi** (lỗi mạng/API thường chỉ là nhất thời), nhưng
  **không** thử lại khi điểm thấp — điểm thấp là tín hiệu thật về chất lượng, thử
  lại chỉ để có điểm đẹp hơn là tự lừa mình.
"""

from __future__ import annotations

import time

import pytest
from pydantic import BaseModel, Field

from lifeos.graph import create_plan
from lifeos.llm import get_llm, has_api_key

pytestmark = [
    pytest.mark.eval,
    pytest.mark.skipif(not has_api_key(), reason="Cần LLM_API_KEY thật để chạy eval"),
]

#: Số lần thử cho mỗi lời gọi. Lỗi mạng thường chỉ nhất thời, nhưng thử lại nhiều
#: sẽ biến một bài eval vài phút thành vài chục phút.
ATTEMPTS = 3

#: Nghỉ giữa các lần thử, nhân theo số lần đã thử (backoff tuyến tính).
RETRY_DELAY_S = 2.0


def _retry(describe: str, call):
    """Gọi `call()`, thử lại khi nó ném lỗi.

    Chỉ bắt **lỗi** để thử lại. Kết quả chấm điểm thấp không đi qua đường này,
    nên không có chuyện thử lại cho tới khi giám khảo chấm điểm đẹp hơn.

    Khi hỏng hẳn, thông báo liệt kê lỗi của **từng lần thử**. Đây là thứ quyết
    định chẩn đoán: lỗi giống hệt nhau qua các lần là hỏng thật (sai key, hết
    quota, sai model), còn lỗi khác nhau từng lần là trục trặc nhất thời.
    """
    errors: list[str] = []
    for attempt in range(1, ATTEMPTS + 1):
        try:
            return call()
        except Exception as exc:
            errors.append(f"  lần {attempt}: {type(exc).__name__}: {exc}")
            if attempt < ATTEMPTS:
                time.sleep(RETRY_DELAY_S * attempt)

    raise AssertionError(
        f"{describe}: lỗi cả {ATTEMPTS} lần.\n"
        "Nếu các dòng dưới giống hệt nhau thì đây là hỏng thật (key/quota/model), "
        "không phải trục trặc nhất thời:\n" + "\n".join(errors)
    )


class Verdict(BaseModel):
    coherence: int = Field(ge=1, le=5)
    tone_fit: int = Field(ge=1, le=5)
    comment: str = ""


def test_plan_coherence_and_tone_fit(profile):
    llm = get_llm()
    plan = _retry("Lập kế hoạch", lambda: create_plan(profile, llm=llm))

    assert plan.study_plan is not None
    assert plan.first_week is not None
    # Bất biến cứng: lịch không được vượt quỹ thời gian
    assert plan.first_week.total_hours <= profile.hours_per_week

    judge_prompt = f"""Chấm kế hoạch dưới đây theo thang 1-5.

- coherence: lộ trình học có mạch lạc, thời hạn 6 tháng có khả thi không?
- tone_fit: giọng điệu có khớp người dùng "thẳng thắn + nghiêm khắc" không?

Kế hoạch:
{plan.model_dump_json(indent=2)[:6000]}
"""
    verdict = _retry(
        "Chấm điểm bằng giám khảo LLM",
        lambda: llm.structured("Bạn là giám khảo khó tính.", judge_prompt, Verdict),
    )

    assert verdict.coherence >= 3, f"coherence thấp: {verdict.comment}"
    assert verdict.tone_fit >= 3, f"tone_fit thấp: {verdict.comment}"
