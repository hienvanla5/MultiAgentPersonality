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

from pydantic import BaseModel, Field

from .autonomy import AutonomousAgent, Task
from .contract_net import ContractNet, ContractNetResult

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
    def fully_staffed(self) -> bool:
        return bool(self.results) and not self.unassigned

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
            lines.append(f"  {mark} {result.task.id}: {target}")
        return "\n".join(lines)


def decompose(goal: str) -> GoalBreakdown:
    """Phân rã mục tiêu thành các nhiệm vụ theo giai đoạn.

    Quy tắc dựa trên cấu trúc chung của một mục tiêu phát triển bản thân: hiểu
    khoảng trống → thiết kế lộ trình → xếp lịch → phản biện rủi ro → giữ động
    lực. Cố định và tất định để kết quả kiểm thử được, nhưng vẫn là *dữ liệu*
    chứ không phải các cạnh cứng trong đồ thị.
    """
    text = (goal or "").strip() or "Mục tiêu cá nhân"
    return GoalBreakdown(
        goal=text,
        tasks=[
            Task(
                id="gap-analysis",
                description=f"Phân tích khoảng trống kỹ năng cho: {text}",
                skill="gap-analysis",
                priority=1,
                effort=0.3,
            ),
            Task(
                id="curriculum",
                description=f"Thiết kế lộ trình học cho: {text}",
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
        ],
    )


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
    extra_agents: dict[str, list[str]] | None = None,
    parallel: bool = True,
) -> TeamPlan:
    """Chạy trọn quy trình: phân rã → lập nhóm → thương lượng phân việc."""
    breakdown = decompose(goal)
    members, excluded = build_roster(breakdown, extra_agents=extra_agents)

    net = ContractNet()
    results = net.run_all(breakdown.tasks, members, parallel=parallel)

    return TeamPlan(
        breakdown=breakdown,
        members=[agent.key for agent in members],
        excluded=excluded,
        results=results,
    )