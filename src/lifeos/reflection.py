"""Suy ngẫm và thích ứng: biến ký ức thành thay đổi hành vi.

Trước module này, bộ nhớ của hệ thống là **chỉ ghi**: `VectorMemory.add()` được
gọi khi lưu kế hoạch, nhưng `search()` chưa bao giờ được dùng trong luồng thật
(chỉ có trong test). Nói cách khác hệ thống "nhớ" nhưng không bao giờ "nhớ lại".

Module này khép vòng học tập đó bằng hai nguồn phản hồi:

1. **Ký ức ngữ nghĩa** — tìm lại các kế hoạch trước có mục tiêu tương tự để rút
   ra bài học (qua `VectorMemory`).
2. **Phản hồi số** — nhìn tỉ lệ hoàn thành thực tế của các kế hoạch cũ để điều
   chỉnh mức tải cho kế hoạch mới.

Nguồn thứ hai đặc biệt quan trọng: nếu người dùng liên tục trượt việc, hệ thống
phải **tự hạ mức tải** thay vì lặp lại y nguyên một kế hoạch quá sức.
"""

from __future__ import annotations

from collections.abc import Iterable

from .llm import LLM
from .memory import VectorMemory
from .models import Lesson, LifeOSPlan, OutcomeStats, Reflection, UserProfile
from .progress import program_progress

#: Ngưỡng tỉ lệ hoàn thành để quyết định mức tải cho lần sau.
LOW_COMPLETION = 0.5
MEDIUM_COMPLETION = 0.75
#: Hệ số tải tương ứng.
LOW_COMPLETION_FACTOR = 0.75
MEDIUM_COMPLETION_FACTOR = 0.9
FULL_COMPLETION_FACTOR = 1.0

#: Không kết luận gì khi có quá ít dữ liệu.
MIN_PLANS_FOR_ADAPTATION = 1


# --- nguồn 1: ký ức ngữ nghĩa ---


def recall(
    memory: VectorMemory | None, query: str, k: int = 3
) -> list[Lesson]:
    """Tìm lại các kế hoạch trước tương tự mục tiêu hiện tại."""
    if memory is None or not query.strip():
        return []

    try:
        hits = memory.search(query, k=k)
    except Exception:  # noqa: BLE001 - bộ nhớ hỏng không được chặn lập kế hoạch
        return []

    lessons: list[Lesson] = []
    for hit in hits:
        metadata = hit.get("metadata") or {}
        text = (hit.get("text") or "").strip()
        if not text:
            continue
        # Bỏ qua chính nội dung trùng khít để tránh lặp vô nghĩa.
        if metadata.get("goal") and metadata["goal"] == query:
            continue
        lessons.append(
            Lesson(
                goal=str(metadata.get("goal", "")),
                text=text[:400],
                distance=metadata.get("distance"),
            )
        )
    return lessons


# --- nguồn 2: phản hồi số từ kết quả thật ---


def outcome_stats(plans: Iterable[LifeOSPlan]) -> OutcomeStats:
    """Tính tỉ lệ hoàn thành trung bình và đề xuất mức tải cho lần sau.

    Chỉ tính các kế hoạch đã có ít nhất một buổi được đánh dấu, vì kế hoạch chưa
    ai đụng tới không nói lên điều gì về năng lực thật của người dùng.
    """
    measured: list[float] = []
    for plan in plans:
        summary = program_progress(plan)
        total = sum(w.total for w in summary.weeks)
        if total == 0:
            continue
        done = sum(w.done for w in summary.weeks)
        # Chỉ tính kế hoạch đã có ít nhất một buổi xong hoặc trượt. Kế hoạch chưa
        # ai đụng tới không nói lên điều gì về năng lực thật của người dùng.
        marked = done + sum(w.missed for w in summary.weeks)
        if marked == 0:
            continue
        measured.append(done / total)

    if len(measured) < MIN_PLANS_FOR_ADAPTATION:
        return OutcomeStats(
            plans=0,
            suggested_load_factor=FULL_COMPLETION_FACTOR,
            reason="chưa có dữ liệu hoàn thành để điều chỉnh",
        )

    average = sum(measured) / len(measured)
    if average < LOW_COMPLETION:
        factor = LOW_COMPLETION_FACTOR
        verdict = "hoàn thành rất thấp — giảm đáng kể để không bỏ cuộc"
    elif average < MEDIUM_COMPLETION:
        factor = MEDIUM_COMPLETION_FACTOR
        verdict = "hoàn thành chưa đều — giảm nhẹ"
    else:
        factor = FULL_COMPLETION_FACTOR
        verdict = "hoàn thành tốt — giữ nguyên mức tải"

    return OutcomeStats(
        plans=len(measured),
        avg_completion=round(average, 4),
        suggested_load_factor=factor,
        reason=(
            f"{len(measured)} kế hoạch trước hoàn thành trung bình "
            f"{average * 100:.0f}% ({verdict})"
        ),
    )


def suggested_load_factor(plans: Iterable[LifeOSPlan]) -> float:
    """Hệ số tải nên dùng cho kế hoạch mới, dựa trên kết quả thật."""
    return outcome_stats(plans).suggested_load_factor


# --- tổng hợp ---


def reflect(
    llm: LLM | None,
    memory: VectorMemory | None,
    profile: UserProfile,
    *,
    past_plans: Iterable[LifeOSPlan] | None = None,
    tone: str = "",
    k: int = 3,
) -> Reflection:
    """Suy ngẫm trước khi lập kế hoạch: tìm bài học và điều chỉnh mức tải.

    Không gọi LLM nếu không có bài học nào để diễn giải — tránh tốn một lượt gọi
    vô ích. Khi có, LLM chỉ làm một việc: đúc kết thành lời khuyên ngắn.
    """
    query = profile.goal_summary or profile.name
    lessons = recall(memory, query, k=k)
    stats = outcome_stats(past_plans or [])

    advice = ""
    if lessons and llm is not None:
        from .agents.base import say

        transcript = "\n".join(f"- [{item.goal}] {item.text}" for item in lessons)
        prompt = (
            f"Mục tiêu mới: {query}\n\n"
            f"Kinh nghiệm từ các kế hoạch trước:\n{transcript}\n\n"
            f"Phản hồi thực tế: {stats.reason}\n\n"
            "Hãy rút ra 2-3 bài học ngắn, cụ thể, có thể áp dụng ngay cho lần "
            "lập kế hoạch này. Nêu thẳng điều gì nên làm khác đi."
        )
        try:
            advice = say(llm, "critic", tone, prompt)
        except Exception:  # noqa: BLE001 - suy ngẫm lỗi không được chặn kế hoạch
            advice = ""

    if not advice and stats.plans:
        advice = stats.reason

    return Reflection(lessons=lessons, stats=stats, advice=advice)


def remember_plan(
    memory: VectorMemory | None, plan: LifeOSPlan, extra: dict | None = None
) -> str | None:
    """Ghi kế hoạch vào bộ nhớ ngữ nghĩa kèm số liệu kết quả.

    Khác `save_node` (chỉ ghi nội dung kế hoạch), hàm này ghi kèm **kết quả thực
    tế** để lần sau `outcome_stats` có dữ liệu mà học.
    """
    if memory is None:
        return None
    from .agents.base import render_plan_summary

    summary = program_progress(plan)
    metadata = {
        "kind": "plan",
        "goal": plan.goal.description if plan.goal else "",
        "completion": summary.overall_pct / 100.0,
        "hours_done": summary.hours_done,
        "on_track": summary.on_track,
    }
    if extra:
        metadata.update(extra)
    text = render_plan_summary(plan)
    return memory.add(text, metadata)
