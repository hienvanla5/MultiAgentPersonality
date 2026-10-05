"""Eval bằng LLM-as-judge: chỉ chạy khi có API key thật.

Chấm hai tiêu chí:
- coherence: lộ trình có mạch lạc, deadline có khả thi không?
- tone_fit: giọng điệu có khớp hồ sơ người dùng không?
"""

from __future__ import annotations

import pytest
from pydantic import BaseModel, Field

from lifeos.graph import create_plan
from lifeos.llm import get_llm, has_api_key

pytestmark = pytest.mark.skipif(
    not has_api_key(), reason="Cần LLM_API_KEY thật để chạy eval"
)


class Verdict(BaseModel):
    coherence: int = Field(ge=1, le=5)
    tone_fit: int = Field(ge=1, le=5)
    comment: str = ""


def test_plan_coherence_and_tone_fit(profile):
    llm = get_llm()
    plan = create_plan(profile, llm=llm)

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
    verdict = llm.structured("Bạn là giám khảo khó tính.", judge_prompt, Verdict)

    assert verdict.coherence >= 3, f"coherence thấp: {verdict.comment}"
    assert verdict.tone_fit >= 3, f"tone_fit thấp: {verdict.comment}"