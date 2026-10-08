"""Test phân rã nhiệm vụ bằng LLM (T2).

Trước đây `decompose()` chỉ có quy tắc cố định: mọi mục tiêu đều ra đúng 5
nhiệm vụ giống nhau, nên "tự tổ chức" chỉ là hình thức — nhóm co giãn theo kỹ
năng nhưng kỹ năng cần có thì không bao giờ đổi.
"""

from __future__ import annotations

from types import SimpleNamespace

from lifeos.agents.autonomy import Task
from lifeos.agents.schemas import DecomposedTask, TaskBreakdown
from lifeos.agents.team import (
    MAX_LLM_TASKS,
    MIN_LLM_TASKS,
    _normalize_tasks,
    _rule_tasks,
    _slug,
    build_roster,
    decompose,
    self_organize,
)


class _StubLLM:
    """LLM giả trả về đúng `TaskBreakdown` được dựng sẵn."""

    def __init__(self, breakdown=None, error: Exception | None = None) -> None:
        self.breakdown = breakdown
        self.error = error
        self.prompts: list[tuple[str, str]] = []

    def structured(self, system_prompt, user_prompt, schema):
        self.prompts.append((system_prompt, user_prompt))
        if self.error is not None:
            raise self.error
        return self.breakdown

    def text(self, system_prompt, user_prompt):
        raise AssertionError("không được gọi text()")


def _breakdown(*tasks: DecomposedTask) -> TaskBreakdown:
    return TaskBreakdown(tasks=list(tasks))


def _task(task_id, skill, description="việc", priority=2, effort=0.3):
    return DecomposedTask(
        id=task_id,
        description=description,
        skill=skill,
        priority=priority,
        effort=effort,
    )


def _raw(task_id, skill, description="việc", priority=2, effort=0.3):
    """Đối tượng thô kiểu duck-typing.

    `DecomposedTask` đã ép kiểu số nên không dựng được giá trị rác qua nó.
    `_normalize_tasks` đọc thuộc tính bằng `getattr` nên vẫn phải chịu được
    kiểu rác — dùng `SimpleNamespace` để chạm tới các nhánh phòng vệ đó.
    """
    return SimpleNamespace(
        id=task_id,
        description=description,
        skill=skill,
        priority=priority,
        effort=effort,
    )


# --- không có LLM: quy tắc cố định ---


def test_decompose_without_llm_uses_rules():
    breakdown = decompose("Chuyển sang Data Analyst")
    assert [t.id for t in breakdown.tasks] == [
        "gap-analysis",
        "curriculum",
        "scheduling",
        "risk-review",
        "motivation",
    ]


def test_rules_are_used_for_every_goal_identically():
    """Đây chính là hạn chế mà T2 khắc phục — quy tắc không phụ thuộc mục tiêu."""
    first = [t.id for t in decompose("mục tiêu A").tasks]
    second = [t.id for t in decompose("mục tiêu B rất khác").tasks]
    assert first == second


# --- có LLM: dùng kết quả của LLM ---


def test_decompose_with_llm_uses_llm_tasks():
    llm = _StubLLM(
        _breakdown(
            _task("doc-jd", "gap-analysis"),
            _task("lo-trinh", "curriculum"),
            _task("lich", "scheduling"),
        )
    )
    breakdown = decompose("mục tiêu", llm=llm)
    assert [t.id for t in breakdown.tasks] == ["doc-jd", "lo-trinh", "lich"]


def test_llm_result_differs_from_rules():
    """Phải chứng minh đường LLM thật sự được dùng, không phải quy tắc."""
    llm = _StubLLM(_breakdown(_task("a", "gap-analysis"), _task("b", "curriculum")))
    ids = [t.id for t in decompose("mục tiêu", llm=llm).tasks]
    assert ids == ["a", "b"]
    assert ids != [t.id for t in _rule_tasks("mục tiêu")]


def test_llm_prompt_lists_available_skills():
    llm = _StubLLM(_breakdown(_task("a", "gap-analysis"), _task("b", "curriculum")))
    decompose("mục tiêu của tôi", llm=llm)
    _system, user = llm.prompts[0]
    assert "mục tiêu của tôi" in user
    assert "gap-analysis" in user
    assert "scheduling" in user


def test_llm_is_not_called_when_absent():
    """Không truyền LLM thì không có lời gọi nào (không tốn API)."""
    breakdown = decompose("mục tiêu")
    assert breakdown.tasks


# --- LLM lỗi hoặc kết quả không dùng được: quay về quy tắc ---


def test_llm_exception_falls_back_to_rules():
    llm = _StubLLM(error=RuntimeError("gateway sập"))
    breakdown = decompose("mục tiêu", llm=llm)
    assert [t.id for t in breakdown.tasks] == [t.id for t in _rule_tasks("mục tiêu")]


def test_llm_returning_none_falls_back_to_rules():
    llm = _StubLLM(None)
    assert len(decompose("mục tiêu", llm=llm).tasks) == len(_rule_tasks("mục tiêu"))


def test_llm_returning_empty_tasks_falls_back_to_rules():
    llm = _StubLLM(_breakdown())
    assert len(decompose("mục tiêu", llm=llm).tasks) == len(_rule_tasks("mục tiêu"))


def test_single_task_falls_back_to_rules():
    """Một nhiệm vụ thì không cần thương lượng -> coi như không dùng được."""
    llm = _StubLLM(_breakdown(_task("a", "gap-analysis")))
    assert len(decompose("mục tiêu", llm=llm).tasks) == len(_rule_tasks("mục tiêu"))
    assert MIN_LLM_TASKS == 2


def test_llm_all_tasks_invalid_falls_back_to_rules():
    llm = _StubLLM(
        _breakdown(
            _task("a", ""),  # thiếu kỹ năng
            _task("b", "gap-analysis", description="   "),  # thiếu mô tả
        )
    )
    assert len(decompose("mục tiêu", llm=llm).tasks) == len(_rule_tasks("mục tiêu"))


def test_llm_error_does_not_leak_to_caller():
    class Exploding:
        def structured(self, *a, **k):
            raise ValueError("json hỏng")

        def text(self, *a, **k):
            raise AssertionError

    assert decompose("mục tiêu", llm=Exploding()).tasks


# --- chuẩn hoá ---


def test_slug_strips_vietnamese_diacritics():
    assert _slug("Đọc tin tuyển dụng", "x") == "doc-tin-tuyen-dung"


def test_slug_handles_empty_text():
    assert _slug("", "du-phong") == "du-phong"
    assert _slug("!!!", "du-phong") == "du-phong"


def test_normalize_generates_id_from_description_when_missing():
    tasks = _normalize_tasks([_task("", "gap-analysis", description="Đọc JD")])
    assert tasks[0].id == "doc-jd"


def test_normalize_falls_back_to_index_when_id_unusable():
    tasks = _normalize_tasks([_task("", "gap-analysis", description="!!!")])
    assert tasks[0].id == "task-1"


def test_normalize_deduplicates_repeated_ids():
    tasks = _normalize_tasks(
        [_task("a", "gap-analysis"), _task("a", "curriculum"), _task("a", "scheduling")]
    )
    assert [t.id for t in tasks] == ["a", "a-2", "a-3"]


def test_normalize_drops_task_without_skill():
    tasks = _normalize_tasks([_task("a", ""), _task("b", "curriculum")])
    assert [t.id for t in tasks] == ["b"]


def test_normalize_drops_task_without_description():
    tasks = _normalize_tasks([_task("a", "gap-analysis", description="  ")])
    assert tasks == []


def test_normalize_clamps_priority_high():
    tasks = _normalize_tasks([_task("a", "gap-analysis", priority=99)])
    assert tasks[0].priority == 3


def test_normalize_clamps_priority_low():
    tasks = _normalize_tasks([_task("a", "gap-analysis", priority=-5)])
    assert tasks[0].priority == 1


def test_normalize_clamps_effort_above_one():
    tasks = _normalize_tasks([_task("a", "gap-analysis", effort=7.5)])
    assert tasks[0].effort == 1.0


def test_normalize_clamps_zero_effort_up():
    """`Task` cấm effort = 0 nên phải kéo lên một mức dương nhỏ."""
    tasks = _normalize_tasks([_task("a", "gap-analysis", effort=0)])
    assert tasks[0].effort == 0.1


def test_normalize_handles_negative_effort():
    tasks = _normalize_tasks([_task("a", "gap-analysis", effort=-3)])
    assert tasks[0].effort == 0.1


def test_normalize_handles_garbage_numeric_values():
    """Giá trị không phải số thì dùng mặc định, không được làm sập."""
    tasks = _normalize_tasks(
        [_raw("a", "gap-analysis", priority="cao", effort="nhiều")]
    )
    assert tasks[0].priority == 2
    assert tasks[0].effort == 0.3


def test_normalize_handles_missing_attributes():
    """Đối tượng thiếu hẳn thuộc tính vẫn phải chuẩn hoá được."""
    tasks = _normalize_tasks([SimpleNamespace(description="Đọc JD", skill="gap-analysis")])
    assert tasks[0].id == "doc-jd"
    assert tasks[0].priority == 2
    assert tasks[0].effort == 0.3


def test_normalize_caps_number_of_tasks():
    many = [_task(f"t{i}", "gap-analysis") for i in range(MAX_LLM_TASKS + 5)]
    assert len(_normalize_tasks(many)) == MAX_LLM_TASKS


def test_normalize_returns_task_objects():
    tasks = _normalize_tasks([_task("a", "gap-analysis")])
    assert isinstance(tasks[0], Task)


def test_normalize_empty_input():
    assert _normalize_tasks([]) == []


def test_normalize_keeps_unknown_skill_visible():
    """Kỹ năng lạ vẫn giữ lại để lộ ra khoảng trống, không âm thầm đổi."""
    tasks = _normalize_tasks([_task("a", "ky-nang-la")])
    assert tasks[0].skill == "ky-nang-la"


# --- tác động lên việc lập nhóm ---


def test_llm_breakdown_shrinks_the_team():
    """Không có nhiệm vụ risk-review thì critic không được mời."""
    llm = _StubLLM(
        _breakdown(
            _task("doc-jd", "gap-analysis"),
            _task("lo-trinh", "curriculum"),
            _task("lich", "scheduling"),
            _task("dong-luc", "motivation"),
        )
    )
    plan = self_organize("mục tiêu", llm=llm)
    assert set(plan.members) == {"career", "tutor", "scheduler", "nudger"}
    assert "critic" in plan.excluded
    assert plan.fully_staffed is True


def test_llm_breakdown_unknown_skill_leaves_task_unassigned():
    """Kỹ năng không agent nào có thì nhiệm vụ phải lộ ra là chưa giao được."""
    llm = _StubLLM(
        _breakdown(
            _task("a", "gap-analysis"),
            _task("b", "curriculum"),
            _task("c", "ky-nang-khong-ai-co"),
        )
    )
    plan = self_organize("mục tiêu", llm=llm)
    assert plan.fully_staffed is False
    assert "c" in plan.unassigned


def test_llm_breakdown_team_has_members_for_all_skills():
    llm = _StubLLM(
        _breakdown(_task("a", "gap-analysis"), _task("b", "scheduling"))
    )
    breakdown = decompose("mục tiêu", llm=llm)
    members, _ = build_roster(breakdown)
    assert {a.key for a in members} == {"career", "scheduler"}


def test_fallback_rules_produce_a_staffable_team():
    """Lưới an toàn phải luôn cho ra nhóm giao được hết việc."""
    plan = self_organize("mục tiêu", llm=_StubLLM(error=RuntimeError("sập")))
    assert plan.fully_staffed is True


def test_self_organize_without_llm_still_works():
    plan = self_organize("mục tiêu")
    assert plan.fully_staffed is True
    assert set(plan.members) == {"career", "tutor", "scheduler", "critic", "nudger"}


def test_demollm_breakdown_is_not_the_rule_based_one():
    """DemoLLM phải cho ra kết quả khác quy tắc, nếu không demo vô nghĩa."""
    from lifeos.demo import DemoLLM

    plan = self_organize("Chuyển sang Data Analyst", llm=DemoLLM())
    rule_ids = [t.id for t in _rule_tasks("Chuyển sang Data Analyst")]
    assert [r.task.id for r in plan.results] != rule_ids
    assert "critic" in plan.excluded
    assert plan.fully_staffed is True
