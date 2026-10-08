"""Tự tổ chức nhóm: phân rã mục tiêu rồi tự chọn thành viên.

Điểm khác biệt so với đồ thị LangGraph (vốn có thứ tự node cố định): ở đây
**cấu trúc nhóm không được lập trình sẵn**. Bộ điều phối:

1. Phân rã mục tiêu thành các nhiệm vụ nhỏ.
2. Nhìn vào kỹ năng mà các nhiệm vụ đó đòi hỏi để **tự chọn** thành viên.
3. Chỉ mời những agent thật sự phù hợp — ai không có việc thì không tham gia.

Nhờ vậy thêm một agent mới vào `ROSTER` là đủ để nó được dùng khi có việc phù
hợp, không phải sửa đồ thị.
"""

from __future__ import annotations

import re
import unicodedata

from pydantic import BaseModel, Field

from ..llm import LLM
from .autonomy import AutonomousAgent, Task
from .contract_net import ContractNet, ContractNetResult
from .schemas import TaskBreakdown

#: Kỹ năng của từng agent — căn cứ để phân việc và chọn thành viên.
AGENT_SKILLS: dict[str, list[str]] = {
    "career": ["gap-analysis"],
    "tutor": ["curriculum", "teaching"],
    "scheduler": ["scheduling"],
    "critic": ["risk-review"],
    "nudger": ["motivation"],
    "orchestrator": ["coordination"],
}

#: Năng lực mặc định của từng agent khi thành lập nhóm.
AGENT_CAPACITY: dict[str, float] = {
    "career": 1.0,
    "tutor": 1.0,
    "scheduler": 1.0,
    "critic": 1.0,
    "nudger": 1.0,
    "orchestrator": 1.0,
}

#: Số nhiệm vụ tối thiểu để coi một kết quả phân rã của LLM là dùng được.
#: Ít hơn thì quay về quy tắc cố định — một mục tiêu chỉ có một nhiệm vụ thì
#: không cần đến cơ chế thương lượng.
MIN_LLM_TASKS = 2

#: Chặn trên số nhiệm vụ, tránh LLM sinh ra danh sách dài không dùng được.
MAX_LLM_TASKS = 8


class GoalBreakdown(BaseModel):
    """Kết quả phân rã một mục tiêu thành nhiệm vụ."""

    goal: str = ""
    tasks: list[Task] = Field(default_factory=list)

    @property
    def skills_needed(self) -> list[str]:
        """Các kỹ năng cần có, giữ thứ tự xuất hiện và không trùng."""
        needed: list[str] = []
        for task in self.tasks:
            if task.skill and task.skill not in needed:
                needed.append(task.skill)
        return needed


class TeamPlan(BaseModel):
    """Kết quả tự tổ chức: nhóm được lập và việc đã giao."""

    breakdown: GoalBreakdown
    members: list[str] = Field(default_factory=list)
    excluded: list[str] = Field(default_factory=list)
    results: list[ContractNetResult] = Field(default_factory=list)

    @property
    def assigned_count(self) -> int:
        return sum(1 for r in self.results if r.assigned)

    @property
    def unassigned(self) -> list[str]:
        return [r.task.id for r in self.results if not r.assigned]

    @property
    def partial(self) -> list[str]:
        """Nhiệm vụ chỉ giao được một phần phạm vi ban đầu."""
        return [r.task.id for r in self.results if r.partial]

    @property
    def remaining_effort(self) -> float:
        """Tổng công sức chưa có ai nhận."""
        return round(sum(r.remaining_effort for r in self.results), 4)

    @property
    def fully_staffed(self) -> bool:
        return bool(self.results) and not self.unassigned

    @property
    def fully_covered(self) -> bool:
        """Vừa giao đủ nhiệm vụ, vừa không nhiệm vụ nào bị cắt bớt phạm vi."""
        return self.fully_staffed and not self.partial

    def summary(self) -> str:
        lines = [
            f"Mục tiêu: {self.breakdown.goal}",
            f"Nhóm tự lập: {', '.join(self.members) or '(không có ai)'}",
        ]
        if self.excluded:
            lines.append(f"Không tham gia: {', '.join(self.excluded)}")
        lines.append(
            f"Đã giao {self.assigned_count}/{len(self.results)} nhiệm vụ."
        )
        for result in self.results:
            mark = "✓" if result.assigned else "✗"
            target = result.awarded_to or f"không ai nhận ({result.reason})"
            suffix = ""
            if result.negotiated:
                suffix += f" [{result.round_count} vòng]"
            if result.partial:
                suffix += (
                    f" [chỉ {result.agreed_effort:.2f}/{result.original_effort:.2f},"
                    f" còn {result.remaining_effort:.2f}]"
                )
            lines.append(f"  {mark} {result.task.id}: {target}{suffix}")
        return "\n".join(lines)


def decompose(goal: str, llm: LLM | None = None) -> GoalBreakdown:
    """Phân rã mục tiêu thành các nhiệm vụ.

    Có `llm` thì để LLM đề xuất nhiệm vụ theo đúng mục tiêu cụ thể; không có
    (hoặc LLM lỗi, hoặc kết quả không dùng được) thì rơi về quy tắc cố định.

    Quy tắc cố định là **lưới an toàn**, không phải đường chính: nó luôn trả
    cùng một danh sách cho mọi mục tiêu, nên nếu chỉ dùng nó thì "tự tổ chức"
    chỉ là hình thức — nhóm co giãn theo kỹ năng nhưng kỹ năng cần có thì không
    bao giờ đổi.
    """
    text = (goal or "").strip() or "Mục tiêu cá nhân"

    if llm is not None:
        tasks = _llm_tasks(llm, text)
        if tasks is not None:
            return GoalBreakdown(goal=text, tasks=tasks)

    return GoalBreakdown(goal=text, tasks=_rule_tasks(text))


def _llm_tasks(llm: LLM, goal: str) -> list[Task] | None:
    """Gọi LLM phân rã mục tiêu. Trả về None nếu không dùng được."""
    try:
        raw = llm.structured(_DECOMPOSE_SYSTEM, _decompose_prompt(goal), TaskBreakdown)
    except Exception:  # noqa: BLE001 - LLM lỗi thì quay về quy tắc cố định
        return None

    tasks = _normalize_tasks(getattr(raw, "tasks", None) or [])
    if len(tasks) < MIN_LLM_TASKS:
        return None
    return tasks


def _decompose_prompt(goal: str) -> str:
    """Prompt nêu rõ mục tiêu và danh sách kỹ năng mà hệ thống thực sự có."""
    skills = ", ".join(
        f"{key} ({'/'.join(values)})"
        for key, values in AGENT_SKILLS.items()
        if key != "orchestrator"
    )
    return (
        f"Mục tiêu: {goal}\n\n"
        f"Các agent hiện có và kỹ năng của họ: {skills}.\n"
        f"Hãy chia mục tiêu thành {MIN_LLM_TASKS}-{MAX_LLM_TASKS} nhiệm vụ. "
        "Mỗi nhiệm vụ phải dùng đúng một kỹ năng trong danh sách trên. "
        "Chỉ tạo nhiệm vụ thật sự cần cho mục tiêu này — đừng thêm cho đủ."
    )


_DECOMPOSE_SYSTEM = (
    "Bạn là bộ điều phối của một nhóm agent. Nhiệm vụ của bạn là phân rã mục "
    "tiêu của người dùng thành các nhiệm vụ nhỏ, mỗi nhiệm vụ gắn với một kỹ "
    "năng mà nhóm thực sự có. Trả về JSON có khoá `tasks`, mỗi phần tử gồm "
    "`id` (ngắn, không dấu, dạng slug), `description`, `skill`, "
    "`priority` (1 = gấp nhất, 3 = thấp nhất) và `effort` (0 < effort <= 1)."
)


def _slug(text: str, fallback: str) -> str:
    """Chuẩn hoá về slug ASCII: bỏ dấu, thay ký tự lạ bằng gạch nối.

    Phải thay `đ`/`Đ` thủ công trước khi chuẩn hoá: NFD chỉ tách được dấu tổ
    hợp, còn nét ngang của "Đ" (U+0110) là một phần của ký tự nên không tách ra
    được — `encode("ascii", "ignore")` sẽ nuốt mất chữ cái đầu và "Đọc" thành
    "oc". Các ký tự `ơ`, `ư`, `ă` thì NFD xử lý được vì chúng là chữ cái + dấu.
    """
    replaced = (text or "").replace("đ", "d").replace("Đ", "D")
    ascii_text = (
        unicodedata.normalize("NFD", replaced)
        .encode("ascii", "ignore")
        .decode("ascii")
    )
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", ascii_text).strip("-").lower()
    return slug or fallback


def _normalize_tasks(raw_tasks: list) -> list[Task]:
    """Chuẩn hoá đề xuất thô của LLM thành `Task` dùng được.

    Loại bỏ nhiệm vụ không định tuyến được (thiếu mô tả hoặc thiếu kỹ năng) và
    kẹp các giá trị số về đúng khoảng. Nhiệm vụ thiếu kỹ năng bị loại vì
    `build_roster` chọn thành viên theo kỹ năng — giữ lại chỉ tạo ra một nhiệm
    vụ chắc chắn không ai nhận, trông như lỗi hệ thống chứ không phải lỗi dữ liệu.
    """
    tasks: list[Task] = []
    seen_ids: set[str] = set()

    for index, item in enumerate(raw_tasks):
        if len(tasks) >= MAX_LLM_TASKS:
            break
        description = str(getattr(item, "description", "") or "").strip()
        skill = str(getattr(item, "skill", "") or "").strip()
        if not description or not skill:
            continue

        task_id = _slug(
            str(getattr(item, "id", "") or "").strip() or description,
            f"task-{index + 1}",
        )
        if task_id in seen_ids:
            # LLM hay lặp id; thêm hậu tố để không mất nhiệm vụ.
            suffix = 2
            while f"{task_id}-{suffix}" in seen_ids:
                suffix += 1
            task_id = f"{task_id}-{suffix}"
        seen_ids.add(task_id)

        tasks.append(
            Task(
                id=task_id,
                description=description,
                skill=skill,
                priority=_clamp_int(getattr(item, "priority", 2), 1, 3, 2),
                effort=_clamp_effort(getattr(item, "effort", 0.3)),
            )
        )
    return tasks


def _clamp_int(value, low: int, high: int, default: int) -> int:
    try:
        return max(low, min(high, int(value)))
    except (TypeError, ValueError):
        return default


def _clamp_effort(value) -> float:
    """Kẹp công sức vào (0, 1]. Giá trị <= 0 thành 0.1 vì `Task` cấm 0."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.3
    if number <= 0:
        return 0.1
    return min(1.0, number)


def _rule_tasks(goal: str) -> list[Task]:
    """Quy tắc cố định, dùng làm lưới an toàn khi không có LLM.

    Dựa trên cấu trúc chung của một mục tiêu phát triển bản thân: hiểu khoảng
    trống → thiết kế lộ trình → xếp lịch → phản biện rủi ro → giữ động lực.
    Tất định để kết quả kiểm thử được.
    """
    return [
        Task(
            id="gap-analysis",
            description=f"Phân tích khoảng trống kỹ năng cho: {goal}",
            skill="gap-analysis",
            priority=1,
            effort=0.3,
        ),
        Task(
            id="curriculum",
            description=f"Thiết kế lộ trình học cho: {goal}",
            skill="curriculum",
            priority=1,
            effort=0.4,
        ),
        Task(
            id="scheduling",
            description="Xếp lịch tuần khả thi trong ngân sách giờ",
            skill="scheduling",
            priority=2,
            effort=0.4,
        ),
        Task(
            id="risk-review",
            description="Soi rủi ro và khả năng quá tải của kế hoạch",
            skill="risk-review",
            priority=2,
            effort=0.2,
        ),
        Task(
            id="motivation",
            description="Viết lời động viên bám sát mục tiêu",
            skill="motivation",
            priority=3,
            effort=0.1,
        ),
    ]


def build_roster(
    breakdown: GoalBreakdown,
    *,
    extra_agents: dict[str, list[str]] | None = None,
) -> tuple[list[AutonomousAgent], list[str]]:
    """Lập nhóm chỉ gồm những agent có kỹ năng mà nhiệm vụ cần.

    Trả về `(thành viên, bị loại)`. Agent không phù hợp không được mời — đây là
    điểm thể hiện tính tự tổ chức: nhóm co giãn theo việc, không cố định.
    """
    skills = dict(AGENT_SKILLS)
    if extra_agents:
        skills.update(extra_agents)

    needed = set(breakdown.skills_needed)
    members: list[AutonomousAgent] = []
    excluded: list[str] = []

    for key, agent_skills in skills.items():
        if key == "orchestrator":
            # Bộ điều phối không tự nhận việc chuyên môn.
            continue
        if needed & set(agent_skills):
            members.append(
                AutonomousAgent(
                    key,
                    skills=agent_skills,
                    capacity=AGENT_CAPACITY.get(key, 1.0),
                )
            )
        else:
            excluded.append(key)
    return members, excluded


def self_organize(
    goal: str,
    *,
    llm: LLM | None = None,
    extra_agents: dict[str, list[str]] | None = None,
    parallel: bool = True,
) -> TeamPlan:
    """Chạy trọn quy trình: phân rã → lập nhóm → thương lượng phân việc."""
    breakdown = decompose(goal, llm=llm)
    members, excluded = build_roster(breakdown, extra_agents=extra_agents)

    net = ContractNet()
    results = net.run_all(breakdown.tasks, members, parallel=parallel)

    return TeamPlan(
        breakdown=breakdown,
        members=[agent.key for agent in members],
        excluded=excluded,
        results=results,
    )