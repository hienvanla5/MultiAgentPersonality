"""Agent tự trị: mỗi agent giữ trạng thái nội bộ và tự quyết định.

Khác với các hàm agent hiện có (nhận đầu vào → trả đầu ra, không nhớ gì), ở đây
mỗi agent:

1. **Có trạng thái nội bộ** tồn tại qua nhiều nhiệm vụ (tải, số việc đã làm, độ
   tin cậy, lịch sử).
2. **Tự đánh giá** một nhiệm vụ dựa trên chính trạng thái của mình — không chờ
   bộ điều phối trung tâm gán việc.
3. **Có quyền từ chối** khi hết năng lực hoặc không đúng chuyên môn.

Nhờ vậy việc phân việc có thể thương lượng (xem `contract_net.py`) thay vì
hard-code trong đồ thị.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from ..personas import get_persona

#: Mức tải tối đa một agent nhận thêm trước khi tự từ chối.
DEFAULT_CAPACITY = 1.0


class Task(BaseModel):
    """Một đơn vị công việc cần được giao cho agent."""

    id: str
    description: str
    skill: str = ""
    priority: int = Field(default=2, ge=1, le=3)  # 1 = cao nhất
    effort: float = Field(default=0.3, gt=0.0, le=1.0)

    @property
    def urgency(self) -> float:
        """Ưu tiên quy đổi thành trọng số 0..1 (ưu tiên 1 là gấp nhất)."""
        return {1: 1.0, 2: 0.6, 3: 0.3}.get(self.priority, 0.3)


class Bid(BaseModel):
    """Giá thầu của một agent cho một nhiệm vụ."""

    agent: str
    task_id: str
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    cost: float = Field(default=0.3, ge=0.0, le=1.0)
    reason: str = ""

    @property
    def score(self) -> float:
        """Điểm để so thầu: tin cậy cao và chi phí thấp thì tốt hơn.

        Chi phí chỉ bị tính nửa trọng số vì một agent hơi tốn kém nhưng chắc
        tay vẫn thường là lựa chọn đúng.
        """
        return self.confidence - self.cost * 0.5


class Refusal(BaseModel):
    """Lý do một agent từ chối nhiệm vụ."""

    agent: str
    task_id: str
    reason: str


class AgentState(BaseModel):
    """Trạng thái nội bộ của một agent."""

    key: str
    skills: list[str] = Field(default_factory=list)
    capacity: float = DEFAULT_CAPACITY
    load: float = 0.0
    completed: int = 0
    refused: int = 0
    trust: float = Field(default=0.5, ge=0.0, le=1.0)
    history: list[str] = Field(default_factory=list)

    @property
    def available(self) -> float:
        """Phần năng lực còn trống."""
        return max(0.0, self.capacity - self.load)

    @property
    def is_free(self) -> bool:
        return self.available > 0.0

    def remember(self, note: str) -> None:
        self.history.append(note)


class AutonomousAgent:
    """Bọc một persona với trạng thái nội bộ và khả năng tự quyết định."""

    def __init__(
        self,
        key: str,
        skills: list[str] | None = None,
        capacity: float = DEFAULT_CAPACITY,
    ) -> None:
        self.state = AgentState(
            key=key, skills=list(skills or []), capacity=capacity
        )

    # --- thông tin ---

    @property
    def key(self) -> str:
        return self.state.key

    @property
    def name(self) -> str:
        return get_persona(self.key).name

    @property
    def role(self) -> str:
        return get_persona(self.key).role

    # --- tự quyết định ---

    def can_handle(self, task: Task) -> bool:
        """Agent có đủ chuyên môn và năng lực cho nhiệm vụ này không?

        Đây là quyết định của chính agent, dựa trên trạng thái nội bộ của nó.
        """
        if not self.state.is_free:
            return False
        if task.effort > self.state.available:
            return False
        # Nhiệm vụ không ghi kỹ năng thì ai cũng nhận được; có ghi thì phải khớp.
        return not task.skill or task.skill in self.state.skills

    def assess(self, task: Task) -> Bid | Refusal:
        """Tự đánh giá nhiệm vụ: trả về giá thầu, hoặc từ chối kèm lý do."""
        if task.skill and task.skill not in self.state.skills:
            self.state.refused += 1
            return Refusal(
                agent=self.key,
                task_id=task.id,
                reason=f"ngoài chuyên môn (cần '{task.skill}')",
            )
        if not self.state.is_free:
            self.state.refused += 1
            return Refusal(
                agent=self.key,
                task_id=task.id,
                reason="đã hết năng lực",
            )
        if task.effort > self.state.available:
            self.state.refused += 1
            return Refusal(
                agent=self.key,
                task_id=task.id,
                reason=(
                    f"nhiệm vụ cần {task.effort:.2f} nhưng chỉ còn "
                    f"{self.state.available:.2f} năng lực"
                ),
            )

        # Còn năng lực: tự tin hơn nếu cùng lúc còn trống nhiều và đã làm tốt.
        confidence = min(
            1.0, 0.4 + 0.4 * (self.state.available / self.state.capacity) + 0.2 * self.state.trust
        )
        cost = min(1.0, task.effort / max(self.state.capacity, 1e-6))
        return Bid(
            agent=self.key,
            task_id=task.id,
            confidence=round(confidence, 4),
            cost=round(cost, 4),
            reason=(
                f"còn {self.state.available:.2f} năng lực, "
                f"đã hoàn thành {self.state.completed} việc"
            ),
        )

    # --- vòng đời nhiệm vụ ---

    def accept(self, task: Task) -> None:
        """Nhận việc: tăng tải nội bộ."""
        self.state.load = min(
            self.state.capacity, self.state.load + task.effort
        )
        self.state.remember(f"nhận: {task.id}")

    def finish(self, task: Task, *, success: bool = True) -> None:
        """Hoàn thành việc: giảm tải, cập nhật độ tin cậy."""
        self.state.load = max(0.0, self.state.load - task.effort)
        if success:
            self.state.completed += 1
            # Càng làm nhiều việc tốt, độ tin cậy càng tiến về 1.
            self.state.trust = min(1.0, self.state.trust + 0.1)
            self.state.remember(f"xong: {task.id}")
        else:
            self.state.trust = max(0.0, self.state.trust - 0.2)
            self.state.remember(f"thất bại: {task.id}")

    def release(self, task: Task) -> None:
        """Trả lại năng lực đã giữ mà không tính là hoàn thành."""
        self.state.load = max(0.0, self.state.load - task.effort)
        self.state.remember(f"trả lại: {task.id}")

    def __repr__(self) -> str:  # pragma: no cover - dễ đọc khi debug
        return (
            f"<AutonomousAgent {self.key} load={self.state.load:.2f}/"
            f"{self.state.capacity:.2f} done={self.state.completed}>"
        )
