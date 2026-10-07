"""Contract Net Protocol — thương lượng phân việc giữa các agent.

Bốn pha theo FIPA Contract Net Interaction Protocol:

1. **Announce** — bộ điều phối mời bỏ thầu (broadcast `REQUEST`).
2. **Bid** — mỗi agent tự đánh giá và trả `PROPOSE`, hoặc `REFUSE` kèm lý do.
3. **Award** — bộ điều phối chọn thầu tốt nhất, gửi `ACCEPT_PROPOSAL` cho người
   thắng và `REJECT_PROPOSAL` cho những người còn lại.
4. **Report** — người thắng báo `INFORM` khi xong.

Điểm cốt lõi: việc phân việc **không do bộ điều phối áp đặt**. Bộ điều phối chỉ
công bố nhiệm vụ; ai nhận việc là kết quả của việc các agent tự đánh giá năng lực
của chính mình. Một agent hết năng lực sẽ tự từ chối và không bao giờ bị gán việc.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Iterable, Optional

from pydantic import BaseModel, Field

from ..acl import MessageBus, Performative
from .autonomy import AutonomousAgent, Bid, Refusal, Task

MANAGER = "orchestrator"
CONTRACT_NET_PROTOCOL = "contract-net"


class ContractNetResult(BaseModel):
    """Kết quả thương lượng cho một nhiệm vụ."""

    task: Task
    conversation_id: str
    bids: list[Bid] = Field(default_factory=list)
    refusals: list[Refusal] = Field(default_factory=list)
    awarded_to: Optional[str] = None
    reason: str = ""

    @property
    def assigned(self) -> bool:
        return self.awarded_to is not None

    @property
    def bid_count(self) -> int:
        return len(self.bids)


class ContractNet:
    """Bộ điều phối thương lượng theo Contract Net Protocol."""

    def __init__(
        self, bus: Optional[MessageBus] = None, manager: str = MANAGER
    ) -> None:
        # Không dùng `bus or MessageBus()`: MessageBus có `__len__` nên một bus
        # RỖNG là falsy, sẽ bị thay bằng bus mới và mọi tin nhắn bị mất.
        self.bus = bus if bus is not None else MessageBus()
        self.manager = manager

    # --- một nhiệm vụ ---

    def run(
        self,
        task: Task,
        agents: Iterable[AutonomousAgent],
        *,
        parallel: bool = False,
    ) -> ContractNetResult:
        """Chạy trọn bốn pha cho một nhiệm vụ."""
        candidates = list(agents)

        # Pha 1: công bố nhiệm vụ
        announcements = self.bus.broadcast(
            self.manager,
            [agent.key for agent in candidates],
            f"{task.description} (kỹ năng: {task.skill or 'không yêu cầu'}, "
            f"công sức {task.effort:.2f})",
            performative=Performative.REQUEST,
            protocol=CONTRACT_NET_PROTOCOL,
            metadata={"task_id": task.id},
        )
        conversation_id = announcements[0].conversation_id if announcements else ""

        # Pha 2: các agent tự đánh giá và bỏ thầu
        outcomes = self._collect_bids(task, candidates, announcements, parallel)

        bids: list[Bid] = []
        refusals: list[Refusal] = []
        for agent, announcement, outcome in outcomes:
            if isinstance(outcome, Bid):
                bids.append(outcome)
                self.bus.reply(
                    announcement,
                    agent.key,
                    Performative.PROPOSE,
                    f"tin cậy {outcome.confidence:.2f}, chi phí {outcome.cost:.2f} "
                    f"({outcome.reason})",
                    metadata={"task_id": task.id, "score": outcome.score},
                )
            else:
                refusals.append(outcome)
                self.bus.reply(
                    announcement,
                    agent.key,
                    Performative.REFUSE,
                    outcome.reason,
                    metadata={"task_id": task.id},
                )

        result = ContractNetResult(
            task=task,
            conversation_id=conversation_id,
            bids=bids,
            refusals=refusals,
        )

        if not bids:
            # Pha 3 thất bại: không ai nhận. Nói rõ vì sao để người dùng biết.
            result.reason = self._no_winner_reason(refusals, candidates)
            self.bus.inform(
                self.manager, self.manager, f"Không ai nhận '{task.id}': {result.reason}"
            )
            return result

        winner = self._pick_winner(bids)
        result.awarded_to = winner.agent
        result.reason = (
            f"{winner.agent} thắng với điểm {winner.score:.3f} "
            f"({winner.reason})"
        )

        # Pha 3: công bố kết quả cho tất cả (gửi xuôi chiều tới từng agent)
        for agent, announcement, outcome in outcomes:
            if agent.key == winner.agent:
                self.bus.notify(
                    announcement,
                    self.manager,
                    agent.key,
                    Performative.ACCEPT_PROPOSAL,
                    result.reason,
                    metadata={"task_id": task.id, "winner": winner.agent},
                )
            elif isinstance(outcome, Bid):
                self.bus.notify(
                    announcement,
                    self.manager,
                    agent.key,
                    Performative.REJECT_PROPOSAL,
                    f"đã giao cho {winner.agent}",
                    metadata={"task_id": task.id},
                )

        # Người thắng nhận việc: cập nhật trạng thái nội bộ của chính nó.
        awarded_agent = next(a for a in candidates if a.key == winner.agent)
        awarded_agent.accept(task)
        return result

    # --- nhiều nhiệm vụ ---

    def run_all(
        self,
        tasks: Iterable[Task],
        agents: Iterable[AutonomousAgent],
        *,
        parallel: bool = False,
    ) -> list[ContractNetResult]:
        """Giao lần lượt nhiều nhiệm vụ.

        Chạy tuần tự theo thứ tự ưu tiên (gấp trước) để việc `accept()` của
        nhiệm vụ trước kịp ảnh hưởng tới năng lực còn lại khi thương lượng
        nhiệm vụ sau — nhờ đó không giao quá tải cho một agent.
        """
        ordered = sorted(tasks, key=lambda t: (t.priority, t.id))
        return [
            self.run(task, agents, parallel=parallel) for task in ordered
        ]

    # --- nội bộ ---

    def _collect_bids(
        self,
        task: Task,
        candidates: list[AutonomousAgent],
        announcements: list,
        parallel: bool,
    ) -> list[tuple[AutonomousAgent, object, Bid | Refusal]]:
        """Thu thầu từ các agent, tuần tự hoặc song song."""
        pairs = list(zip(candidates, announcements))

        if not parallel or len(pairs) <= 1:
            return [
                (agent, announcement, agent.assess(task))
                for agent, announcement in pairs
            ]

        # Các agent đánh giá độc lập nên chạy song song được. `assess()` chỉ đọc
        # và tăng bộ đếm `refused` của chính agent đó, nên không tranh chấp.
        with ThreadPoolExecutor(max_workers=len(pairs)) as pool:
            futures = [
                (agent, announcement, pool.submit(agent.assess, task))
                for agent, announcement in pairs
            ]
            return [
                (agent, announcement, future.result())
                for agent, announcement, future in futures
            ]

    def _pick_winner(self, bids: list[Bid]) -> Bid:
        """Chọn thầu tốt nhất; hoà thì ưu tiên chi phí thấp rồi tới tên agent.

        Sắp xếp có tiêu chí phụ để kết quả **tất định** — cùng đầu vào luôn cho
        cùng người thắng, không phụ thuộc thứ tự duyệt.
        """
        return sorted(bids, key=lambda b: (-b.score, b.cost, b.agent))[0]

    def _no_winner_reason(
        self, refusals: list[Refusal], candidates: list[AutonomousAgent]
    ) -> str:
        if not candidates:
            return "không có agent nào được đăng ký"
        if not refusals:
            return "không agent nào phản hồi"
        detail = "; ".join(f"{r.agent}: {r.reason}" for r in refusals)
        return f"tất cả đều từ chối ({detail})"


def summarize(results: list[ContractNetResult]) -> str:
    """Tóm tắt một lượt phân việc để hiển thị cho người dùng."""
    if not results:
        return "Không có nhiệm vụ nào cần phân."
    assigned = [r for r in results if r.assigned]
    lines = [
        f"Đã giao {len(assigned)}/{len(results)} nhiệm vụ "
        f"qua {sum(r.bid_count for r in results)} giá thầu."
    ]
    for result in results:
        if result.assigned:
            lines.append(f"  ✓ {result.task.id} → {result.awarded_to}")
        else:
            lines.append(f"  ✗ {result.task.id} → không ai nhận: {result.reason}")
    return "\n".join(lines)