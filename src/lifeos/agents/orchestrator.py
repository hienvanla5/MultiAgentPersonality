"""Người Dẫn Đường — tổng hợp ý kiến hội đồng thành kết luận."""

from __future__ import annotations

from ..llm import LLM
from ..models import AgentMessage
from .base import structured
from .schemas import Synthesis


def synthesize(
    llm: LLM, topic: str, turns: list[AgentMessage], tone: str
) -> Synthesis:
    """Tổng hợp các lượt phát biểu của hội đồng persona."""
    transcript = (
        "\n".join(f"[{t.persona} - {t.role}] {t.content}" for t in turns)
        or "(chưa có ý kiến)"
    )
    prompt = f"""Chủ đề: {topic}

Ý kiến từ các chuyên gia:
{transcript}

Hãy tổng hợp thành một kết luận cân bằng, không thiên vị ai:
- headline: một câu kết luận chính
- key_points: 2-4 điểm quan trọng nhất (đã cân nhắc cả ý phản biện)
- next_actions: 2-4 hành động cụ thể, làm được ngay trong tuần này
- message: đoạn tổng hợp 3-5 câu gửi trực tiếp cho người dùng, giọng phù hợp"""

    result = structured(llm, "orchestrator", tone, prompt, Synthesis)
    return result