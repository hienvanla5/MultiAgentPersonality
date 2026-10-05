"""Hàm dùng chung để chạy một agent theo persona + tone."""

from __future__ import annotations

from pydantic import BaseModel

from ..llm import LLM
from ..models import LifeOSPlan
from ..personas import get_persona


def structured(
    llm: LLM,
    persona_key: str,
    tone_instruction: str,
    user_prompt: str,
    schema: type[BaseModel],
) -> BaseModel:
    """Gọi LLM với system prompt của persona, trả về object theo schema."""
    persona = get_persona(persona_key)
    return llm.structured(
        persona.render_system_prompt(tone_instruction), user_prompt, schema
    )


def say(llm: LLM, persona_key: str, tone_instruction: str, user_prompt: str) -> str:
    """Gọi LLM ở chế độ văn bản tự do."""
    persona = get_persona(persona_key)
    return llm.text(persona.render_system_prompt(tone_instruction), user_prompt)


def render_plan_summary(plan: LifeOSPlan) -> str:
    """Chuyển kế hoạch thành văn bản ngắn để đưa cho agent phản biện."""
    lines: list[str] = []
    if plan.goal:
        lines.append(
            f"Mục tiêu: {plan.goal.description} "
            f"(thời hạn {plan.goal.deadline_months} tháng)"
        )
    if plan.gaps:
        lines.append("Khoảng trống kỹ năng: " + ", ".join(g.skill for g in plan.gaps))
    if plan.study_plan:
        lines.append(
            f"Lộ trình: {plan.study_plan.total_weeks} tuần, "
            f"{len(plan.study_plan.modules)} module"
        )
        for m in plan.study_plan.modules[:10]:
            lines.append(f"  - {m.title} ({m.duration_hours}h)")
    if plan.first_week:
        lines.append(
            f"Lịch tuần {plan.first_week.week}: {plan.first_week.total_hours} giờ, "
            f"{len(plan.first_week.tasks)} buổi"
        )
        for t in plan.first_week.tasks:
            lines.append(
                f"  - {t.day} {t.start} ({t.duration_min} phút) {t.title}"
            )
    return "\n".join(lines) or "(kế hoạch trống)"