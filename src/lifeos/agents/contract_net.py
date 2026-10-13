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

**Liên minh.** Chia nhỏ phạm vi vẫn là bỏ bớt việc. Khi cả nhóm cùng từ chối vì
việc quá lớn, nhưng **cộng năng lực của nhiều người lại thì đủ**, cách đúng không
phải là cắt bớt việc mà là để nhiều agent cùng đứng ra nhận. Bộ điều phối công bố
lại nhiệm vụ với một thay đổi duy nhất: lần này **nhận một phần cũng được**. Ai
đủ chuyên môn và còn năng lực thì bỏ thầu cho phần mình làm được; bộ điều phối
ghép các phần đó thành một liên minh phủ trọn nhiệm vụ.

Liên minh chỉ được thử khi **không ai** nhận trọn được: chia một việc mà một
người làm gọn cho ba người chỉ tạo thêm chi phối hợp. Và nó đứng **trước** việc
chia nhỏ phạm vi, vì liên minh phủ được nhiều hơn hoặc bằng.
"""

from __future__ import annotations

from collections.abc import Iterable
from functools import partial

from pydantic import BaseModel, Field

from ..acl import ACLMessage, MessageBus, Performative
from ..parallel import map_parallel
from .autonomy import AutonomousAgent, Bid, Refusal, Task

MANAGER = "orchestrator"
CONTRACT_NET_PROTOCOL = "contract-net"

#: Số vòng thương lượng tối đa cho một nhiệm vụ.
MAX_ROUNDS = 3

#: Dưới mức công sức này thì chia nhỏ không còn ý nghĩa — dừng thương lượng.
MIN_SLICE_EFFORT = 0.1

#: Sai số cho phép khi so công sức, tránh lỗi làm tròn của số thực.
_EPS = 1e-9


class CoalitionShare(BaseModel):
    """Phần công sức một agent nhận khi cùng đứng ra nhận một việc lớn."""

    agent: str
    effort: float = Field(gt=0.0, le=1.0)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    reason: str = ""


class RoundRecord(BaseModel):
    """Diễn biến một vòng thương lượng."""

    round: int = 1
    task: Task
    bids: list[Bid] = Field(default_factory=list)
    refusals: list[Refusal] = Field(default_factory=list)
    awarded_to: str | None = None
    reason: str = ""
    #: Đã nới gì so với vòng trước (rỗng ở vòng 1).
    relaxation: str = ""
    #: Phần công sức từng thành viên nhận, khi vòng này trao cho một liên minh.
    #: Rỗng nghĩa là trao trọn cho một agent.
    coalition: list[CoalitionShare] = Field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.awarded_to is not None

    @property
    def bid_count(self) -> int:
        return len(self.bids)

    @property
    def is_coalition(self) -> bool:
        """Vòng này có trao cho nhiều agent cùng lúc không?"""
        return len(self.coalition) > 1


class ContractNetResult(BaseModel):
    """Kết quả thương lượng cho một nhiệm vụ (có thể qua nhiều vòng)."""

    task: Task
    conversation_id: str
    bids: list[Bid] = Field(default_factory=list)
    refusals: list[Refusal] = Field(default_factory=list)
    awarded_to: str | None = None
    reason: str = ""
    #: Toàn bộ diễn biến các vòng, kể cả những vòng thất bại.
    rounds: list[RoundRecord] = Field(default_factory=list)
    #: Công sức ban đầu của nhiệm vụ, trước khi chia nhỏ.
    original_effort: float = 0.0
    #: True khi chỉ giao được một phần phạm vi ban đầu.
    partial: bool = False
    #: Phần công sức chưa có ai nhận.
    remaining_effort: float = 0.0
    #: Phần công sức từng thành viên nhận, khi nhiệm vụ được giao cho một liên
    #: minh. Rỗng nghĩa là giao trọn cho một mình `awarded_to`.
    coalition: list[CoalitionShare] = Field(default_factory=list)

    @property
    def assigned(self) -> bool:
        return self.awarded_to is not None

    @property
    def is_coalition(self) -> bool:
        """Nhiệm vụ này có phải do nhiều agent cùng nhận không?"""
        return len(self.coalition) > 1

    @property
    def members(self) -> list[str]:
        """Mọi agent nhận việc này: một người, hoặc cả liên minh."""
        if self.coalition:
            return [share.agent for share in self.coalition]
        return [self.awarded_to] if self.awarded_to else []

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
        """Công sức thực tế đã chốt (sau khi chia nhỏ hoặc ghép liên minh)."""
        if self.coalition:
            return round(sum(share.effort for share in self.coalition), 4)
        if not self.rounds:
            return self.task.effort
        return self.rounds[-1].task.effort


class ContractNet:
    """Bộ điều phối thương lượng theo Contract Net Protocol."""

    def __init__(
        self, bus: MessageBus | None = None, manager: str = MANAGER
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

        Thứ tự các vòng: nhận trọn → ghép liên minh → chia nhỏ phạm vi. Liên
        minh đứng trước chia nhỏ vì nó phủ được nhiều hơn hoặc bằng.
        """
        candidates = list(agents)
        original = task
        current = task
        conversation_id: str | None = None
        rounds: list[RoundRecord] = []
        relaxation = ""
        # Vòng liên minh chỉ thử một lần cho mỗi nhiệm vụ.
        coalition_tried = False
        allow_partial = False

        for round_no in range(1, max(1, int(max_rounds)) + 1):
            record, conversation_id = self._negotiate_round(
                current,
                candidates,
                parallel=parallel,
                round_no=round_no,
                relaxation=relaxation,
                conversation_id=conversation_id,
                allow_partial=allow_partial,
            )
            rounds.append(record)
            if record.ok:
                break

            # Chưa ai nhận trọn. Thử ghép liên minh trước khi cắt bớt phạm vi.
            if not coalition_tried and can_form_coalition(original, candidates):
                coalition_tried = True
                allow_partial = True
                relaxation = _coalition_relaxation(original, candidates)
                continue

            # Không ghép được liên minh: quay về chia nhỏ phạm vi như trước.
            allow_partial = False
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
            coalition=decided.coalition,
        )

        if result.assigned:
            # Liên minh phủ `sum(phần)`; một người thì phủ đúng công sức đã chốt.
            covered = (
                sum(share.effort for share in result.coalition)
                if result.coalition
                else current.effort
            )
            # Chỉ giao được một phần phạm vi ban đầu thì phải nói rõ phần còn lại.
            result.remaining_effort = round(
                max(0.0, original.effort - covered), 4
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
        conversation_id: str | None,
        allow_partial: bool = False,
    ) -> tuple[RoundRecord, str]:
        """Một vòng: công bố → thu thầu → trao thầu. Trả về (bản ghi, mã hội thoại).

        `allow_partial=True` là vòng liên minh: agent được phép bỏ thầu cho một
        phần công sức thay vì buộc phải từ chối khi không đủ sức nhận trọn.
        """
        announcements = self.bus.broadcast(
            self.manager,
            [agent.key for agent in candidates],
            self._announcement_text(task, round_no, allow_partial),
            performative=Performative.REQUEST,
            protocol=CONTRACT_NET_PROTOCOL,
            conversation_id=conversation_id,
            metadata={
                "task_id": task.id,
                "round": round_no,
                "allow_partial": allow_partial,
            },
        )
        cid = announcements[0].conversation_id if announcements else (conversation_id or "")

        outcomes = self._collect_bids(
            task, candidates, announcements, parallel, allow_partial
        )

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

        lead, shares = plan_award(task, bids)
        if lead is None:  # pragma: no cover - `bids` không rỗng nên không xảy ra
            record.reason = self._no_winner_reason(refusals, candidates)
            return record, cid

        record.awarded_to = lead
        record.coalition = shares
        record.reason = (
            coalition_reason(task, shares)
            if shares
            else single_reason(next(bid for bid in bids if bid.agent == lead))
        )

        # Phần mỗi agent nhận. Không phải liên minh thì nhận trọn nhiệm vụ.
        portions = (
            {share.agent: share.effort for share in shares}
            if shares
            else {lead: task.effort}
        )

        # Pha 3: công bố kết quả cho tất cả (gửi xuôi chiều tới từng agent)
        for agent, announcement, outcome in outcomes:
            if agent.key in portions:
                portion = portions[agent.key]
                self.bus.notify(
                    announcement,
                    self.manager,
                    agent.key,
                    Performative.ACCEPT_PROPOSAL,
                    (
                        f"{record.reason} — phần của bạn: {portion:.2f} công sức"
                        if shares
                        else record.reason
                    ),
                    metadata={
                        "task_id": task.id,
                        "round": round_no,
                        "winner": lead,
                        "share": portion,
                    },
                )
            elif isinstance(outcome, Bid):
                self.bus.notify(
                    announcement,
                    self.manager,
                    agent.key,
                    Performative.REJECT_PROPOSAL,
                    f"đã giao cho {lead}",
                    metadata={"task_id": task.id, "round": round_no},
                )

        # Người nhận việc: cập nhật trạng thái nội bộ của chính nó, theo đúng
        # phần mình nhận. Một thành viên liên minh chỉ được tính tải bằng phần
        # của mình — nếu tính cả nhiệm vụ thì cả nhóm cùng bị quá tải.
        for agent in candidates:
            if agent.key not in portions:
                continue
            portion = portions[agent.key]
            agent.accept(
                task.model_copy(update={"effort": portion}) if shares else task
            )
        return record, cid

    def _announcement_text(
        self, task: Task, round_no: int, allow_partial: bool = False
    ) -> str:
        base = (
            f"{task.description} (kỹ năng: {task.skill or 'không yêu cầu'}, "
            f"công sức {task.effort:.2f})"
        )
        if allow_partial:
            base += " — nhận một phần cũng được, hãy bỏ thầu phần bạn làm được"
        return f"[vòng {round_no}] {base}" if round_no > 1 else base

    def _relax(self, task: Task, candidates: list[AutonomousAgent]) -> Task | None:
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
        announcements: list[ACLMessage],
        parallel: bool,
        allow_partial: bool = False,
    ) -> list[tuple[AutonomousAgent, ACLMessage, Bid | Refusal]]:
        """Thu thầu từ các agent, tuần tự hoặc song song."""
        # `broadcast` trả về đúng một tin cho mỗi receiver, nên hai danh sách này
        # luôn khớp độ dài. `strict=True` biến giả định đó thành khẳng định: nếu
        # có ngày ai đó sửa `broadcast` cho lệch, lỗi nổ ra ngay tại đây thay vì
        # âm thầm bỏ sót agent cuối.
        pairs = list(zip(candidates, announcements, strict=True))

        if not parallel or len(pairs) <= 1:
            return [
                (agent, announcement, agent.assess(task, allow_partial=allow_partial))
                for agent, announcement in pairs
            ]

        # Các agent đánh giá độc lập nên chạy song song được. `assess()` chỉ đọc
        # trạng thái và tăng bộ đếm `refused` của chính agent đó.
        outcome = map_parallel(
            [
                partial(agent.assess, task, allow_partial=allow_partial)
                for agent, _ in pairs
            ],
            max_workers=len(pairs),
        )
        collected: list[tuple[AutonomousAgent, ACLMessage, Bid | Refusal]] = []
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

    def _no_winner_reason(
        self, refusals: list[Refusal], candidates: list[AutonomousAgent]
    ) -> str:
        return no_winner_reason(refusals, candidates)


def share_of(bid: Bid, task: Task) -> float:
    """Công sức mà một giá thầu nhận.

    `Bid` không nêu `share` được coi là nhận **trọn** nhiệm vụ. Đây là quy tắc
    tương thích ngược cho những giá thầu có từ trước khi có liên minh, và cũng
    là cách hiểu hợp lý: không nêu gì thì hiểu là nhận cả việc.
    """
    return bid.share if bid.share > 0.0 else task.effort


def plan_award(task: Task, bids: list[Bid]) -> tuple[str | None, list[CoalitionShare]]:
    """Quyết định trao thầu: một người nhận trọn, hay nhiều người hợp thành liên minh.

    Trả về `(trưởng nhóm, danh sách phần)`. Danh sách **rỗng** nghĩa là trao
    trọn cho một người — đó vẫn là đường đi thường gặp.

    Ưu tiên tuyệt đối cho người nhận trọn: chỉ khi **không ai** đủ sức nhận cả
    nhiệm vụ thì mới ghép liên minh. Chia một việc mà một người làm gọn được
    cho ba người chỉ tạo thêm chi phối hợp mà không lợi gì.
    """
    if not bids:
        return None, []

    full = [bid for bid in bids if share_of(bid, task) >= task.effort - _EPS]
    if full:
        return pick_winner(full).agent, []

    # Ghép liên minh: lấy dần phần của từng người theo đúng thứ tự tất định mà
    # `pick_winner` dùng, cho tới khi phủ hết nhiệm vụ hoặc hết người sẵn lòng.
    shares: list[CoalitionShare] = []
    covered = 0.0
    for bid in sorted(bids, key=lambda b: (-b.score, b.cost, b.agent)):
        if covered >= task.effort - _EPS:
            break
        take = min(share_of(bid, task), task.effort - covered)
        if take < MIN_SLICE_EFFORT - _EPS:
            # Phần quá nhỏ thì không đáng nhận — cùng ngưỡng với việc chia nhỏ
            # phạm vi, để hai cơ chế không mâu thuẫn nhau. Phải trừ dung sai:
            # phần bù cuối cùng của một nhiệm vụ hay ra 0.09999999999999998 do
            # số thực, và nếu đem so thẳng với 0.1 thì nó bị loại oan, khiến
            # liên minh thiếu đúng một mảnh và không phủ được trọn nhiệm vụ.
            continue
        shares.append(
            CoalitionShare(
                agent=bid.agent,
                effort=take,
                confidence=bid.confidence,
                reason=bid.reason,
            )
        )
        covered += take

    if len(shares) >= 2:
        return shares[0].agent, shares

    # Chỉ một người thì không phải liên minh: quay về đường cũ.
    return pick_winner(bids).agent, []


def can_form_coalition(task: Task, candidates: list[AutonomousAgent]) -> bool:
    """Có đáng thử ghép liên minh cho nhiệm vụ này không?

    Đúng khi có ít nhất hai agent đúng chuyên môn còn đủ năng lực, **không ai**
    trong số đó nhận trọn được nhiệm vụ, và cộng lại thì phủ được nhiều hơn
    người giỏi nhất làm một mình. Điều kiện cuối quan trọng: nếu người thứ hai
    không thêm được gì thì liên minh chỉ làm chậm mọi thứ.
    """
    qualified = [
        agent
        for agent in candidates
        if (not task.skill or task.skill in agent.state.skills)
        and agent.state.available >= MIN_SLICE_EFFORT
    ]
    if len(qualified) < 2:
        return False

    best = max(agent.state.available for agent in qualified)
    if best >= task.effort - _EPS:
        # Một người đã đủ sức nhận trọn; thất bại (nếu có) không phải vì công sức.
        return False

    combined = sum(min(agent.state.available, task.effort) for agent in qualified)
    return combined > best + _EPS


def coalition_reason(task: Task, shares: list[CoalitionShare]) -> str:
    """Mô tả một liên minh: ai nhận bao nhiêu, tổng được bao nhiêu."""
    detail = " + ".join(f"{share.agent} {share.effort:.2f}" for share in shares)
    total = sum(share.effort for share in shares)
    return (
        f"liên minh {len(shares)} agent nhận {total:.2f}/{task.effort:.2f} "
        f"công sức ({detail})"
    )


def single_reason(bid: Bid) -> str:
    """Mô tả lý do một giá thầu thắng trọn nhiệm vụ.

    Đặt ở mức module để đường bất đồng bộ dùng lại đúng câu chữ này — hai đường
    chạy mà mô tả khác nhau thì người đọc log sẽ tưởng là hai cơ chế khác nhau.
    """
    return f"{bid.agent} thắng với điểm {bid.score:.3f} ({bid.reason})"


def _coalition_relaxation(task: Task, candidates: list[AutonomousAgent]) -> str:
    """Mô tả vòng liên minh đã nới gì, để bản ghi đọc được như các vòng khác."""
    qualified = [
        agent
        for agent in candidates
        if not task.skill or task.skill in agent.state.skills
    ]
    total = sum(agent.state.available for agent in qualified)
    return (
        f"lập liên minh: không ai nhận trọn {task.effort:.2f}, "
        f"cả nhóm còn {total:.2f} năng lực nên chia nhau nhận"
    )


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
    coalitions = [r for r in results if r.is_coalition]
    lines = [
        f"Đã giao {len(assigned)}/{len(results)} nhiệm vụ "
        f"qua {sum(r.bid_count for r in results)} giá thầu."
    ]
    if negotiated:
        lines.append(
            f"  {len(negotiated)} nhiệm vụ phải công bố lại "
            f"(tổng {sum(r.round_count for r in negotiated)} vòng)."
        )
    if coalitions:
        lines.append(
            f"  {len(coalitions)} nhiệm vụ do liên minh nhận "
            f"({sum(len(r.coalition) for r in coalitions)} lượt agent)."
        )
    for result in results:
        if result.assigned:
            note = ""
            if result.is_coalition:
                note = " — liên minh: " + " + ".join(
                    f"{share.agent} {share.effort:.2f}" for share in result.coalition
                )
            if result.partial:
                note += (
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
