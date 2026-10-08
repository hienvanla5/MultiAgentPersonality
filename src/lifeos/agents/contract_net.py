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

**Thương lượng nhiều vòng.** Một vòng là chưa đủ khi cả nhóm cùng từ chối vì
nhiệm vụ đòi hỏi nhiều công sức hơn phần năng lực còn trống. Khi đó bộ điều phối
công bố lại với **phạm vi được chia nhỏ cho vừa năng lực thực tế**, và ghi lại
phần chưa ai nhận (`remaining_effort`) thay vì im lặng coi như đã giao xong.

Bộ điều phối chỉ nới được **một** thứ: công sức. Kỹ năng thì không — giao một
việc cho agent không có chuyên môn còn tệ hơn là để việc đó chưa ai làm. Vì vậy
nếu không ai có kỹ năng phù hợp thì dừng ngay ở vòng 1, không nới tiếp vô ích.
"""

from __future__ import annotations

from typing import Iterable, Optional

from pydantic import BaseModel, Field

from ..acl import MessageBus, Performative
from ..parallel import map_parallel
from .autonomy import AutonomousAgent, Bid, Refusal, Task

MANAGER = "orchestrator"
CONTRACT_NET_PROTOCOL = "contract-net"

#: Số vòng thương lượng tối đa cho một nhiệm vụ.
MAX_ROUNDS = 3

#: Dưới mức công sức này thì chia nhỏ không còn ý nghĩa — dừng thương lượng.
MIN_SLICE_EFFORT = 0.1


class RoundRecord(BaseModel):
    """Diễn biến một vòng thương lượng."""

    round: int = 1
    task: Task
    bids: list[Bid] = Field(default_factory=list)
    refusals: list[Refusal] = Field(default_factory=list)
    awarded_to: Optional[str] = None
    reason: str = ""
    #: Đã nới gì so với vòng trước (rỗng ở vòng 1).
    relaxation: str = ""

    @property
    def ok(self) -> bool:
        return self.awarded_to is not None

    @property
    def bid_count(self) -> int:
        return len(self.bids)


class ContractNetResult(BaseModel):
    """Kết quả thương lượng cho một nhiệm vụ (có thể qua nhiều vòng)."""

    task: Task
    conversation_id: str
    bids: list[Bid] = Field(default_factory=list)
    refusals: list[Refusal] = Field(default_factory=list)
    awarded_to: Optional[str] = None
    reason: str = ""
    #: Toàn bộ diễn biến các vòng, kể cả những vòng thất bại.
    rounds: list[RoundRecord] = Field(default_factory=list)
    #: Công sức ban đầu của nhiệm vụ, trước khi chia nhỏ.
    original_effort: float = 0.0
    #: True khi chỉ giao được một phần phạm vi ban đầu.
    partial: bool = False
    #: Phần công sức chưa có ai nhận.
    remaining_effort: float = 0.0

    @property
    def assigned(self) -> bool:
        return self.awarded_to is not None

    @property
    def bid_count(self) -> int:
        return len(self.bids)

    @property
    def round_count(self) -> int:
        return len(self.rounds)

    @property
    def negotiated(self) -> bool:
        """Có phải công bố lại ít nhất một lần không?"""
        return len(self.rounds) > 1

    @property
    def agreed_effort(self) -> float:
        """Công sức thực tế đã chốt (sau khi chia nhỏ, nếu có)."""
        if not self.rounds:
            return self.task.effort
        return self.rounds[-1].task.effort


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
        max_rounds: int = MAX_ROUNDS,
    ) -> ContractNetResult:
        """Chạy thương lượng cho một nhiệm vụ, công bố lại nếu cần.

        Mỗi vòng dùng chung một `conversation_id` để bản ghi ACL đọc được như
        một cuộc thương lượng duy nhất chứ không phải nhiều cuộc rời rạc.
        """
        candidates = list(agents)
        original = task
        current = task
        conversation_id: Optional[str] = None
        rounds: list[RoundRecord] = []
        relaxation = ""

        for round_no in range(1, max(1, int(max_rounds)) + 1):
            record, conversation_id = self._negotiate_round(
                current,
                candidates,
                parallel=parallel,
                round_no=round_no,
                relaxation=relaxation,
                conversation_id=conversation_id,
            )
            rounds.append(record)
            if record.ok:
                break

            relaxed = self._relax(current, candidates)
            if relaxed is None:
                # Không còn gì nới được (thường là không ai có chuyên môn).
                break
            relaxation = (
                f"chia nhỏ công sức {current.effort:.2f} → {relaxed.effort:.2f}"
            )
            current = relaxed

        decided = rounds[-1]
        result = ContractNetResult(
            task=original,
            conversation_id=conversation_id or "",
            bids=decided.bids,
            refusals=decided.refusals,
            awarded_to=decided.awarded_to,
            reason=decided.reason,
            rounds=rounds,
            original_effort=original.effort,
        )

        if result.assigned:
            # Chỉ giao được một phần phạm vi ban đầu thì phải nói rõ phần còn lại.
            result.remaining_effort = round(
                max(0.0, original.effort - current.effort), 4
            )
            result.partial = result.remaining_effort > 0
        else:
            result.remaining_effort = original.effort
        return result

    def _negotiate_round(
        self,
        task: Task,
        candidates: list[AutonomousAgent],
        *,
        parallel: bool,
        round_no: int,
        relaxation: str,
        conversation_id: Optional[str],
    ) -> tuple[RoundRecord, str]:
        """Một vòng: công bố → thu thầu → trao thầu. Trả về (bản ghi, mã hội thoại)."""
        announcements = self.bus.broadcast(
            self.manager,
            [agent.key for agent in candidates],
            self._announcement_text(task, round_no),
            performative=Performative.REQUEST,
            protocol=CONTRACT_NET_PROTOCOL,
            conversation_id=conversation_id,
            metadata={"task_id": task.id, "round": round_no},
        )
        cid = announcements[0].conversation_id if announcements else (conversation_id or "")

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
                    metadata={
                        "task_id": task.id,
                        "round": round_no,
                        "score": outcome.score,
                    },
                )
            else:
                refusals.append(outcome)
                self.bus.reply(
                    announcement,
                    agent.key,
                    Performative.REFUSE,
                    outcome.reason,
                    metadata={"task_id": task.id, "round": round_no},
                )

        record = RoundRecord(
            round=round_no,
            task=task,
            bids=bids,
            refusals=refusals,
            relaxation=relaxation,
        )

        if not bids:
            record.reason = self._no_winner_reason(refusals, candidates)
            self.bus.inform(
                self.manager,
                self.manager,
                f"[vòng {round_no}] Không ai nhận '{task.id}': {record.reason}",
                conversation_id=cid,
            )
            return record, cid

        winner = self._pick_winner(bids)
        record.awarded_to = winner.agent
        record.reason = (
            f"{winner.agent} thắng với điểm {winner.score:.3f} ({winner.reason})"
        )

        # Pha 3: công bố kết quả cho tất cả (gửi xuôi chiều tới từng agent)
        for agent, announcement, outcome in outcomes:
            if agent.key == winner.agent:
                self.bus.notify(
                    announcement,
                    self.manager,
                    agent.key,
                    Performative.ACCEPT_PROPOSAL,
                    record.reason,
                    metadata={
                        "task_id": task.id,
                        "round": round_no,
                        "winner": winner.agent,
                    },
                )
            elif isinstance(outcome, Bid):
                self.bus.notify(
                    announcement,
                    self.manager,
                    agent.key,
                    Performative.REJECT_PROPOSAL,
                    f"đã giao cho {winner.agent}",
                    metadata={"task_id": task.id, "round": round_no},
                )

        # Người thắng nhận việc: cập nhật trạng thái nội bộ của chính nó.
        awarded_agent = next(a for a in candidates if a.key == winner.agent)
        awarded_agent.accept(task)
        return record, cid

    def _announcement_text(self, task: Task, round_no: int) -> str:
        base = (
            f"{task.description} (kỹ năng: {task.skill or 'không yêu cầu'}, "
            f"công sức {task.effort:.2f})"
        )
        return f"[vòng {round_no}] {base}" if round_no > 1 else base

    def _relax(self, task: Task, candidates: list[AutonomousAgent]) -> Optional[Task]:
        """Nới điều khoản cho vòng sau. Trả về None nếu không nới được gì.

        Chỉ nới **công sức**, và chỉ khi có agent đúng chuyên môn nhưng đang
        thiếu năng lực. Nếu không ai có chuyên môn thì nới công sức cũng vô ích.
        """
        qualified = [
            agent
            for agent in candidates
            if not task.skill or task.skill in agent.state.skills
        ]
        if not qualified:
            return None

        best = max(agent.state.available for agent in qualified)
        if best < MIN_SLICE_EFFORT:
            # Cả nhóm đã kín lịch: vấn đề là thời điểm, không phải phạm vi.
            return None
        if best >= task.effort:
            # Công sức đã vừa với ai đó, vậy thất bại không phải vì công sức.
            return None

        effort = max(MIN_SLICE_EFFORT, min(1.0, round(best, 4)))
        return task.model_copy(
            update={
                "effort": effort,
                "description": (
                    f"{task.description} [phần vừa năng lực: {effort:.2f}]"
                ),
            }
        )

    # --- nhiều nhiệm vụ ---

    def run_all(
        self,
        tasks: Iterable[Task],
        agents: Iterable[AutonomousAgent],
        *,
        parallel: bool = False,
        max_rounds: int = MAX_ROUNDS,
    ) -> list[ContractNetResult]:
        """Giao lần lượt nhiều nhiệm vụ.

        Chạy tuần tự theo thứ tự ưu tiên (gấp trước) để việc `accept()` của
        nhiệm vụ trước kịp ảnh hưởng tới năng lực còn lại khi thương lượng
        nhiệm vụ sau — nhờ đó không giao quá tải cho một agent.
        """
        ordered = sorted(tasks, key=lambda t: (t.priority, t.id))
        return [
            self.run(task, agents, parallel=parallel, max_rounds=max_rounds)
            for task in ordered
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
        # trạng thái và tăng bộ đếm `refused` của chính agent đó.
        outcome = map_parallel(
            [lambda a=agent: a.assess(task) for agent, _ in pairs],
            max_workers=len(pairs),
        )
        collected: list[tuple[AutonomousAgent, object, Bid | Refusal]] = []
        for index, (agent, announcement) in enumerate(pairs):
            value = outcome.values[index]
            if value is None:
                # Một agent lỗi không được làm hỏng cả lượt thương lượng.
                value = Refusal(
                    agent=agent.key,
                    task_id=task.id,
                    reason=f"lỗi khi đánh giá ({outcome.errors[index]})",
                )
            collected.append((agent, announcement, value))
        return collected

    def _pick_winner(self, bids: list[Bid]) -> Bid:
        return pick_winner(bids)

    def _no_winner_reason(
        self, refusals: list[Refusal], candidates: list[AutonomousAgent]
    ) -> str:
        return no_winner_reason(refusals, candidates)


def pick_winner(bids: list[Bid]) -> Bid:
    """Chọn thầu tốt nhất; hoà thì ưu tiên chi phí thấp rồi tới tên agent.

    Sắp xếp có tiêu chí phụ để kết quả **tất định** — cùng đầu vào luôn cho
    cùng người thắng, không phụ thuộc thứ tự duyệt.

    Đặt ở mức module để runtime bất đồng bộ dùng lại đúng luật trao thầu này,
    không phải chép lại — hai đường chạy mà lệch luật thì kết quả sẽ khác nhau.
    """
    return sorted(bids, key=lambda b: (-b.score, b.cost, b.agent))[0]


def no_winner_reason(
    refusals: list[Refusal], candidates: list[AutonomousAgent]
) -> str:
    """Giải thích vì sao không ai nhận việc."""
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
    partial = [r for r in results if r.partial]
    negotiated = [r for r in results if r.negotiated]
    lines = [
        f"Đã giao {len(assigned)}/{len(results)} nhiệm vụ "
        f"qua {sum(r.bid_count for r in results)} giá thầu."
    ]
    if negotiated:
        lines.append(
            f"  {len(negotiated)} nhiệm vụ phải công bố lại "
            f"(tổng {sum(r.round_count for r in negotiated)} vòng)."
        )
    for result in results:
        if result.assigned:
            note = ""
            if result.partial:
                note = (
                    f" — chỉ {result.agreed_effort:.2f}/{result.original_effort:.2f} "
                    f"công sức, còn lại {result.remaining_effort:.2f} chưa ai nhận"
                )
            lines.append(f"  ✓ {result.task.id} → {result.awarded_to}{note}")
        else:
            lines.append(f"  ✗ {result.task.id} → không ai nhận: {result.reason}")
    if partial:
        lines.append(
            f"  Lưu ý: {len(partial)} nhiệm vụ mới giao được một phần phạm vi."
        )
    return "\n".join(lines)