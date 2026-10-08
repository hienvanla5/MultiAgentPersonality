"""Test suy ngẫm và thích ứng từ ký ức + phản hồi thực tế."""

from __future__ import annotations

from lifeos.models import (
    Goal,
    LifeOSPlan,
    ScheduleTask,
    TaskStatus,
    TaskType,
    WeeklySchedule,
)
from lifeos.reflection import (
    FULL_COMPLETION_FACTOR,
    LOW_COMPLETION_FACTOR,
    MEDIUM_COMPLETION_FACTOR,
    Lesson,
    OutcomeStats,
    Reflection,
    outcome_stats,
    recall,
    reflect,
    remember_plan,
    suggested_load_factor,
)

# --- tiện ích dựng dữ liệu ---


def _task(task_id: str, status: TaskStatus, duration: int = 60) -> ScheduleTask:
    return ScheduleTask(
        id=task_id,
        title=f"việc {task_id}",
        task_type=TaskType.STUDY,
        day="Mon",
        start="20:00",
        duration_min=duration,
        status=status,
    )


def _plan(*tasks: ScheduleTask, goal: str = "Mục tiêu cũ") -> LifeOSPlan:
    week = WeeklySchedule(
        week=1,
        tasks=list(tasks),
        total_hours=round(sum(t.duration_min for t in tasks) / 60),
    )
    return LifeOSPlan(
        goal=Goal(description=goal), weeks=[week], first_week=week
    )


# --- recall ---


class _FakeMemory:
    def __init__(self, hits):
        self._hits = hits
        self.queries: list[tuple[str, int]] = []

    def search(self, query: str, k: int = 4):
        self.queries.append((query, k))
        return self._hits


def test_recall_without_memory_returns_empty():
    assert recall(None, "Data Analyst") == []


def test_recall_with_blank_query_returns_empty():
    memory = _FakeMemory([{"text": "x", "metadata": {}}])
    assert recall(memory, "   ") == []


def test_recall_converts_hits_to_lessons():
    memory = _FakeMemory(
        [{"text": "kế hoạch cũ", "metadata": {"goal": "Data Analyst"}}]
    )
    lessons = recall(memory, "Data Analyst mới", k=2)
    assert len(lessons) == 1
    assert lessons[0].text == "kế hoạch cũ"
    assert lessons[0].goal == "Data Analyst"
    assert memory.queries == [("Data Analyst mới", 2)]


def test_recall_skips_exact_same_goal():
    memory = _FakeMemory(
        [{"text": "chính nó", "metadata": {"goal": "Data Analyst"}}]
    )
    assert recall(memory, "Data Analyst") == []


def test_recall_skips_empty_text():
    memory = _FakeMemory([{"text": "   ", "metadata": {"goal": "x"}}])
    assert recall(memory, "y") == []


def test_recall_truncates_long_text():
    memory = _FakeMemory([{"text": "a" * 900, "metadata": {"goal": "x"}}])
    lessons = recall(memory, "y")
    assert len(lessons[0].text) == 400


def test_recall_survives_broken_memory():
    class Broken:
        def search(self, query, k=4):
            raise RuntimeError("chroma hỏng")

    assert recall(Broken(), "x") == []


# --- outcome_stats ---


def test_outcome_stats_without_plans():
    stats = outcome_stats([])
    assert stats.plans == 0
    assert stats.suggested_load_factor == FULL_COMPLETION_FACTOR
    assert "chưa có dữ liệu" in stats.reason


def test_outcome_stats_ignores_untouched_plan():
    plan = _plan(_task("a", TaskStatus.PLANNED), _task("b", TaskStatus.PLANNED))
    stats = outcome_stats([plan])
    assert stats.plans == 0


def test_outcome_stats_all_done_keeps_full_load():
    plan = _plan(_task("a", TaskStatus.DONE), _task("b", TaskStatus.DONE))
    stats = outcome_stats([plan])
    assert stats.plans == 1
    assert stats.avg_completion == 1.0
    assert stats.suggested_load_factor == FULL_COMPLETION_FACTOR


def test_outcome_stats_all_missed_reduces_load_sharply():
    plan = _plan(_task("a", TaskStatus.MISSED), _task("b", TaskStatus.MISSED))
    stats = outcome_stats([plan])
    assert stats.plans == 1
    assert stats.avg_completion == 0.0
    assert stats.suggested_load_factor == LOW_COMPLETION_FACTOR


def test_outcome_stats_at_medium_threshold_keeps_full_load():
    # Đúng 3/4 = 75%: ngưỡng là "nhỏ hơn 75%" nên 75% vẫn giữ nguyên mức tải
    plan = _plan(
        _task("a", TaskStatus.DONE),
        _task("b", TaskStatus.DONE),
        _task("c", TaskStatus.DONE),
        _task("d", TaskStatus.MISSED),
    )
    stats = outcome_stats([plan])
    assert stats.avg_completion == 0.75
    assert stats.suggested_load_factor == FULL_COMPLETION_FACTOR


def test_outcome_stats_just_below_medium_threshold():
    # 2/3 xong = 66.7% -> nằm giữa 50% và 75% -> giảm nhẹ
    plan = _plan(
        _task("a", TaskStatus.DONE),
        _task("b", TaskStatus.DONE),
        _task("c", TaskStatus.MISSED),
    )
    stats = outcome_stats([plan])
    assert 0.5 <= stats.avg_completion < 0.75
    assert stats.suggested_load_factor == MEDIUM_COMPLETION_FACTOR


def test_outcome_stats_averages_multiple_plans():
    good = _plan(_task("a", TaskStatus.DONE), _task("b", TaskStatus.DONE))
    bad = _plan(_task("c", TaskStatus.MISSED), _task("d", TaskStatus.MISSED))
    stats = outcome_stats([good, bad])
    assert stats.plans == 2
    assert stats.avg_completion == 0.5


def test_outcome_stats_skips_empty_plan():
    assert outcome_stats([LifeOSPlan()]).plans == 0


def test_suggested_load_factor_helper():
    plan = _plan(_task("a", TaskStatus.MISSED))
    assert suggested_load_factor([plan]) == LOW_COMPLETION_FACTOR


# --- Reflection ---


def test_reflection_prompt_block_empty():
    assert Reflection().prompt_block() == ""


def test_reflection_prompt_block_includes_lessons_and_stats():
    reflection = Reflection(
        lessons=[Lesson(goal="cũ", text="đừng nhồi 10h/tuần")],
        stats=OutcomeStats(plans=2, reason="2 kế hoạch hoàn thành 40%"),
        advice="bắt đầu 6h/tuần",
    )
    block = reflection.prompt_block()
    assert "đừng nhồi 10h/tuần" in block
    assert "2 kế hoạch hoàn thành 40%" in block
    assert "bắt đầu 6h/tuần" in block


def test_reflection_has_lessons_flag():
    assert Reflection().has_lessons is False
    assert Reflection(lessons=[Lesson(text="x")]).has_lessons is True


# --- reflect ---


def test_reflect_without_memory_still_reports_stats(profile):
    plan = _plan(_task("a", TaskStatus.MISSED))
    reflection = reflect(None, None, profile, past_plans=[plan])
    assert reflection.lessons == []
    assert reflection.stats.plans == 1
    assert reflection.advice


def test_reflect_does_not_call_llm_without_lessons(fake_llm, profile):
    reflect(fake_llm, None, profile, past_plans=[])
    assert fake_llm.count("text") == 0


def test_reflect_calls_llm_when_lessons_exist(fake_llm, profile):
    memory = _FakeMemory(
        [{"text": "bài học cũ", "metadata": {"goal": "mục tiêu khác"}}]
    )
    reflection = reflect(fake_llm, memory, profile, tone="tone")
    assert reflection.lessons
    assert fake_llm.count("text") == 1
    assert reflection.advice


def test_reflect_survives_llm_failure(profile):
    class BrokenLLM:
        def structured(self, s, u, schema):
            raise RuntimeError("x")

        def text(self, s, u):
            raise RuntimeError("llm chết")

    memory = _FakeMemory([{"text": "bài học", "metadata": {"goal": "khác"}}])
    reflection = reflect(BrokenLLM(), memory, profile)
    assert reflection.lessons
    assert reflection.advice == "" or isinstance(reflection.advice, str)


def test_reflect_uses_goal_as_query(fake_llm, profile):
    memory = _FakeMemory([])
    reflect(fake_llm, memory, profile)
    assert memory.queries[0][0] == profile.goal_summary


# --- remember_plan ---


def test_remember_plan_without_memory_returns_none():
    assert remember_plan(None, _plan(_task("a", TaskStatus.DONE))) is None


def test_remember_plan_stores_completion_metadata():
    added: list[tuple] = []

    class Recorder(_FakeMemory):
        def add(self, text, metadata=None):
            added.append((text, metadata))
            return "id-1"

    recorder = Recorder([])
    plan = _plan(_task("a", TaskStatus.DONE), _task("b", TaskStatus.DONE))
    result = remember_plan(recorder, plan)

    assert result == "id-1"
    text, metadata = added[0]
    assert metadata["kind"] == "plan"
    assert metadata["completion"] == 1.0
    assert metadata["on_track"] is True
    assert text


def test_remember_plan_merges_extra_metadata():
    added: list[dict] = []

    class Recorder:
        def add(self, text, metadata=None):
            added.append(metadata)
            return "id"

    remember_plan(Recorder(), _plan(_task("a", TaskStatus.DONE)), {"run": 7})
    assert added[0]["run"] == 7
