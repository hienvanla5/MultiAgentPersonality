"""Đồ thị LangGraph: luồng lập kế hoạch và luồng điều chỉnh kế hoạch."""

from __future__ import annotations

from datetime import datetime
from typing import Optional, TypedDict

from langgraph.graph import END, START, StateGraph

from .agents import career, curriculum, nudger, orchestrator, scheduler
from .agents import critic as critic_agent
from .agents.base import render_plan_summary
from .agents.schemas import Critique
from .llm import LLM, get_llm
from .memory import Store, VectorMemory
from .models import (
    AdjustmentEvent,
    AgentMessage,
    Goal,
    LifeOSPlan,
    Roundtable,
    SkillGap,
    StudyPlan,
    UserProfile,
    WeeklySchedule,
)
from .personas import PERSONAS, build_tone_instruction

REDUCED_LOAD_FACTOR = 0.8
ADJUST_LOAD_FACTOR = 0.9


class BuildState(TypedDict, total=False):
    """Trạng thái luồng lập kế hoạch."""

    profile: UserProfile
    goal: Goal
    tone: str
    busy: dict
    load_factor: float
    replanned: bool
    gaps: list[SkillGap]
    study_plan: StudyPlan
    first_week: WeeklySchedule
    critique: Critique
    nudge: str
    roundtable: Roundtable
    plan: LifeOSPlan


class AdjustState(TypedDict, total=False):
    """Trạng thái luồng điều chỉnh khi lệch kế hoạch."""

    profile: UserProfile
    plan: LifeOSPlan
    reason: str
    missed: list[str]
    tone: str
    critique: Critique
    nudge: str
    new_week: WeeklySchedule
    roundtable: Roundtable
    event: AdjustmentEvent
    plan_out: LifeOSPlan


def _msg(persona_key: str, content: str, tone: str) -> AgentMessage:
    persona = PERSONAS[persona_key]
    return AgentMessage(
        persona=persona.name, role=persona.role, content=content, tone=tone
    )


def build_graph(
    llm: LLM,
    store: Optional[Store] = None,
    memory: Optional[VectorMemory] = None,
):
    """Dựng đồ thị lập kế hoạch: career -> curriculum -> schedule -> hội đồng -> tổng hợp."""

    def career_node(state: BuildState) -> dict:
        gaps = career.analyze_gaps(
            llm, state["goal"], state["profile"], state["tone"]
        )
        return {"gaps": gaps}

    def curriculum_node(state: BuildState) -> dict:
        plan = curriculum.build_study_plan(
            llm, state["goal"], state.get("gaps", []), state["profile"], state["tone"]
        )
        return {"study_plan": plan}

    def schedule_node(state: BuildState) -> dict:
        week = scheduler.build_week(
            llm,
            state["study_plan"],
            state["profile"],
            state["tone"],
            week=1,
            busy=state.get("busy"),
            load_factor=state.get("load_factor", 1.0),
        )
        return {"first_week": week}

    def reduce_load_node(state: BuildState) -> dict:
        return {"load_factor": REDUCED_LOAD_FACTOR, "replanned": True}

    def roundtable_node(state: BuildState) -> dict:
        summary = render_plan_summary(
            LifeOSPlan(
                goal=state["goal"],
                gaps=state.get("gaps", []),
                study_plan=state.get("study_plan"),
                first_week=state.get("first_week"),
            )
        )
        crit = critic_agent.critique(llm, summary, state["profile"], state["tone"])
        nudge = nudger.encourage(
            llm,
            "Người dùng vừa nhận kế hoạch mới cho mục tiêu: "
            + state["goal"].description,
            state["profile"],
            state["tone"],
        )
        turns = [
            _msg(
                "critic",
                crit.summary or "; ".join(crit.risks) or "Không thấy rủi ro lớn.",
                state["tone"],
            ),
            _msg("nudger", nudge, state["tone"]),
        ]
        rt = Roundtable(
            topic="Đánh giá kế hoạch: " + state["goal"].description, turns=turns
        )
        return {"critique": crit, "nudge": nudge, "roundtable": rt}

    def route_after_roundtable(state: BuildState) -> str:
        crit = state.get("critique")
        if crit is not None and crit.overload and not state.get("replanned"):
            return "reduce_load"
        return "synthesize"

    def synthesize_node(state: BuildState) -> dict:
        rt = state["roundtable"]
        syn = orchestrator.synthesize(llm, rt.topic, rt.turns, state["tone"])
        rt.synthesis = _msg(
            "orchestrator",
            syn.message or syn.headline or "Đã tổng hợp kế hoạch.",
            state["tone"],
        )
        plan = LifeOSPlan(
            goal=state["goal"],
            gaps=state.get("gaps", []),
            study_plan=state.get("study_plan"),
            first_week=state.get("first_week"),
            roundtable=rt,
        )
        return {"roundtable": rt, "plan": plan}

    def save_node(state: BuildState) -> dict:
        plan = state["plan"]
        goal_text = plan.goal.description if plan.goal else ""
        now = datetime.now().isoformat(timespec="seconds")
        if store is not None:
            store.save_plan(goal_text, plan.model_dump(mode="json"), now)
        if memory is not None:
            memory.add(render_plan_summary(plan), {"kind": "plan", "goal": goal_text})
        return {}

    graph = StateGraph(BuildState)
    graph.add_node("career", career_node)
    graph.add_node("curriculum", curriculum_node)
    graph.add_node("schedule", schedule_node)
    graph.add_node("reduce_load", reduce_load_node)
    graph.add_node("roundtable", roundtable_node)
    graph.add_node("synthesize", synthesize_node)
    graph.add_node("save", save_node)

    graph.add_edge(START, "career")
    graph.add_edge("career", "curriculum")
    graph.add_edge("curriculum", "schedule")
    graph.add_edge("schedule", "roundtable")
    graph.add_conditional_edges(
        "roundtable",
        route_after_roundtable,
        {"reduce_load": "reduce_load", "synthesize": "synthesize"},
    )
    graph.add_edge("reduce_load", "schedule")
    graph.add_edge("synthesize", "save")
    graph.add_edge("save", END)
    return graph.compile()


def adjust_graph(llm: LLM, store: Optional[Store] = None):
    """Dựng đồ thị điều chỉnh: phản biện sự cố -> lập lịch mới -> hội đồng -> chốt."""

    def assess_node(state: AdjustState) -> dict:
        summary = render_plan_summary(state["plan"])
        missed = ", ".join(state.get("missed") or []) or "không rõ"
        crit = critic_agent.critique(
            llm,
            f"{summary}\n\nSự cố: {state['reason']}\nViệc bị trượt: {missed}",
            state["profile"],
            state["tone"],
        )
        return {"critique": crit}

    def reschedule_node(state: AdjustState) -> dict:
        study_plan = state["plan"].study_plan or StudyPlan()
        current = state["plan"].first_week
        next_week = (current.week + 1) if current else 1
        note = (
            f"Người dùng vừa lệch kế hoạch: {state['reason']}. "
            "Ưu tiên bù các buổi bị trượt, không nhồi thêm việc mới."
        )
        week = scheduler.build_week(
            llm,
            study_plan,
            state["profile"],
            state["tone"],
            week=next_week,
            load_factor=ADJUST_LOAD_FACTOR,
            note=note,
        )
        return {"new_week": week}

    def roundtable_node(state: AdjustState) -> dict:
        crit = state["critique"]
        nudge = nudger.encourage(
            llm,
            f"Người dùng lệch kế hoạch: {state['reason']}. "
            "Kế hoạch mới đã được điều chỉnh nhẹ nhàng hơn.",
            state["profile"],
            state["tone"],
        )
        turns = [
            _msg(
                "critic",
                crit.summary or "; ".join(crit.risks) or "Điều chỉnh là hợp lý.",
                state["tone"],
            ),
            _msg("nudger", nudge, state["tone"]),
        ]
        rt = Roundtable(topic=f"Điều chỉnh kế hoạch: {state['reason']}", turns=turns)
        return {"nudge": nudge, "roundtable": rt}

    def finalize_node(state: AdjustState) -> dict:
        rt = state["roundtable"]
        syn = orchestrator.synthesize(llm, rt.topic, rt.turns, state["tone"])
        rt.synthesis = _msg(
            "orchestrator",
            syn.message or syn.headline or "Đã điều chỉnh kế hoạch.",
            state["tone"],
        )
        old_plan = state["plan"]
        old_week = old_plan.first_week.week if old_plan.first_week else 0
        new_plan = old_plan.model_copy(deep=True)
        new_plan.first_week = state["new_week"]
        new_plan.roundtable = rt
        event = AdjustmentEvent(
            reason=state["reason"],
            old_week=old_week,
            new_week=state["new_week"].week,
            message=syn.message or syn.headline or "",
        )
        if store is not None:
            store.save_event(
                state["reason"],
                event.model_dump(mode="json"),
                datetime.now().isoformat(timespec="seconds"),
            )
        return {"plan_out": new_plan, "event": event, "roundtable": rt}

    graph = StateGraph(AdjustState)
    graph.add_node("assess", assess_node)
    graph.add_node("reschedule", reschedule_node)
    graph.add_node("roundtable", roundtable_node)
    graph.add_node("finalize", finalize_node)

    graph.add_edge(START, "assess")
    graph.add_edge("assess", "reschedule")
    graph.add_edge("reschedule", "roundtable")
    graph.add_edge("roundtable", "finalize")
    graph.add_edge("finalize", END)
    return graph.compile()


# --- API cấp cao ---


def create_plan(
    profile: UserProfile,
    *,
    llm: Optional[LLM] = None,
    store: Optional[Store] = None,
    memory: Optional[VectorMemory] = None,
    goal: Optional[Goal] = None,
    busy: Optional[dict] = None,
) -> LifeOSPlan:
    """Lập kế hoạch đầy đủ cho một hồ sơ người dùng."""
    llm = llm or get_llm()
    goal = goal or Goal(description=profile.goal_summary or "Mục tiêu cá nhân")
    tone = build_tone_instruction(profile)
    app = build_graph(llm, store=store, memory=memory)
    final_state = app.invoke(
        {
            "profile": profile,
            "goal": goal,
            "tone": tone,
            "busy": busy or {},
            "load_factor": 1.0,
            "replanned": False,
        }
    )
    return final_state["plan"]


def adjust_plan(
    plan: LifeOSPlan,
    profile: UserProfile,
    reason: str,
    *,
    missed: Optional[list[str]] = None,
    llm: Optional[LLM] = None,
    store: Optional[Store] = None,
) -> tuple[LifeOSPlan, AdjustmentEvent]:
    """Điều chỉnh kế hoạch khi người dùng lệch tiến độ."""
    llm = llm or get_llm()
    tone = build_tone_instruction(profile)
    app = adjust_graph(llm, store=store)
    final_state = app.invoke(
        {
            "profile": profile,
            "plan": plan,
            "reason": reason,
            "missed": missed or [],
            "tone": tone,
        }
    )
    return final_state["plan_out"], final_state["event"]