"""Runtime cho agent chạy nền thật sự.

`parallel.map_parallel` chạy các bước **độc lập** bằng thread rồi thu kết quả —
đủ cho "gọi hai LLM cùng lúc", nhưng không phải là các agent đang sống: chúng
không có hộp thư, không ai gửi tin cho ai, và không có gì xảy ra trong khoảng
giữa lúc bắt đầu và lúc kết thúc.

Ở đây mỗi agent là một `asyncio.Task` thật, có **hộp thư riêng**, tự chạy vòng
lặp nhận tin → xử lý → trả lời. Ba hệ quả kiểm chứng được bằng test:

1. **Chạy thật sự đồng thời.** Tổng thời gian ≈ agent chậm nhất, không phải tổng
   thời gian các agent.
2. **Agent chậm không chặn agent khác.** Hết hạn chờ thì agent đó bị coi là
   không phản hồi, những người còn lại vẫn có kết quả dùng được.
3. **Agent lỗi không làm sập runtime.** Lỗi được ghi vào bản ghi ACL dưới dạng
   `FAILURE`; các agent khác chạy tiếp bình thường.

Bản ghi ACL vẫn là `MessageBus` cũ, nên `bus.conversation(id)` đọc được toàn bộ
cuộc thương lượng như trước — chỉ khác là lần này các tin nhắn thật sự đi qua
hộp thư của những agent đang chạy, chứ không phải được ghi lại sau khi mọi việc
đã xong.
"""

from __future__ import annotations

import asyncio
import inspect
import time
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass, field
from uuid import uuid4

from .acl import ACLMessage, MessageBus, Performative
from .agents.autonomy import AutonomousAgent, Bid, Refusal, Task
from .agents.contract_net import (
    CONTRACT_NET_PROTOCOL,
    MANAGER,
    ContractNetResult,
    no_winner_reason,
    pick_winner,
)

#: Thời gian chờ phản hồi mặc định cho một vòng (giây).
DEFAULT_TIMEOUT = 5.0

#: Thời gian ân hạn khi tắt runtime trước khi huỷ các worker còn kẹt (giây).
DEFAULT_SHUTDOWN_GRACE = 1.0

#: Những performative **cần** agent phản hồi.
#:
#: Các loại còn lại (`INFORM`, `ACCEPT_PROPOSAL`, `REJECT_PROPOSAL`, `FAILURE`)
#: chỉ là thông báo: agent ghi nhận rồi thôi. Nếu vẫn gọi handler cho chúng thì
#: một agent sẽ "bỏ thầu" cho chính tin báo mình đã trúng thầu — vô nghĩa, và
#: làm bẩn bản ghi ACL bằng những tin nhắn không có thật trong cuộc thương lượng.
RESPONDS_TO = frozenset(
    {Performative.REQUEST, Performative.CRITIQUE}
)

#: Giá trị đánh dấu dừng vòng lặp của một agent.
_STOP = object()

#: Hàm xử lý tin nhắn: nhận (agent, tin nhắn), trả về nội dung trả lời, một
#: `Bid`/`Refusal`, `None` (không trả lời), hoặc awaitable của những thứ đó.
Handler = Callable[
    [AutonomousAgent, ACLMessage],
    str | Bid | Refusal | Awaitable[object | None] | None,
]


@dataclass
class RuntimeStats:
    """Số liệu một phiên chạy runtime."""

    handled: int = 0
    failed: int = 0
    timed_out: int = 0
    duration_s: float = 0.0

    @property
    def total(self) -> int:
        return self.handled + self.failed

    def summary(self) -> str:
        return (
            f"đã xử lý {self.handled} tin, {self.failed} lỗi, "
            f"{self.timed_out} hết hạn chờ, {self.duration_s:.3f}s"
        )


@dataclass
class _AgentSlot:
    """Một agent đã đăng ký: hộp thư, hàm xử lý, và task nền của nó."""

    agent: AutonomousAgent
    handler: Handler | None = None
    inbox: asyncio.Queue = field(default_factory=asyncio.Queue)
    worker: asyncio.Task | None = None


class AgentRuntime:
    """Chạy các agent như những task nền giao tiếp qua hộp thư.

    Dùng như context manager để không quên tắt:

    ```python
    async with AgentRuntime() as runtime:
        runtime.register(AutonomousAgent("tutor", ["curriculum"]))
        result = await runtime.negotiate(task, runtime.agents)
    ```
    """

    def __init__(
        self,
        bus: MessageBus | None = None,
        *,
        manager: str = MANAGER,
        timeout: float = DEFAULT_TIMEOUT,
        shutdown_grace: float = DEFAULT_SHUTDOWN_GRACE,
    ) -> None:
        # Không dùng `bus or MessageBus()`: MessageBus có `__len__` nên một bus
        # RỖNG là falsy và sẽ bị thay bằng bus mới, làm mất hết tin nhắn.
        self.bus = bus if bus is not None else MessageBus()
        self.manager = manager
        self.timeout = timeout
        self.shutdown_grace = shutdown_grace
        self.stats = RuntimeStats()
        self._slots: dict[str, _AgentSlot] = {}
        self._tasks: dict[str, Task] = {}
        self._collectors: dict[str, asyncio.Queue] = {}
        self._started = False

    # --- đăng ký ---

    def register(
        self, agent: AutonomousAgent, handler: Handler | None = None
    ) -> AutonomousAgent:
        """Đăng ký một agent. Gọi trước `start()`.

        `handler=None` dùng cách xử lý mặc định: tra nhiệm vụ theo
        `metadata["task_id"]` rồi để chính agent tự `assess()` — tức là agent
        vẫn tự quyết định, không bị bộ điều phối gán việc.
        """
        if agent.key in self._slots:
            raise ValueError(f"agent '{agent.key}' đã được đăng ký")
        self._slots[agent.key] = _AgentSlot(agent=agent, handler=handler)
        return agent

    @property
    def agents(self) -> list[AutonomousAgent]:
        return [slot.agent for slot in self._slots.values()]

    def agent(self, key: str) -> AutonomousAgent:
        if key not in self._slots:
            raise KeyError(f"agent '{key}' chưa được đăng ký")
        return self._slots[key].agent

    def inbox(self, key: str) -> asyncio.Queue:
        """Hộp thư của một agent (chỉ dùng khi đang chạy)."""
        if key not in self._slots:
            raise KeyError(f"agent '{key}' chưa được đăng ký")
        return self._slots[key].inbox

    # --- vòng đời ---

    async def start(self) -> None:
        """Spawn một task nền cho mỗi agent đã đăng ký."""
        if self._started:
            raise RuntimeError("runtime đã chạy")
        if not self._slots:
            raise RuntimeError("chưa có agent nào được đăng ký")
        self._started = True
        for slot in self._slots.values():
            slot.worker = asyncio.create_task(
                self._worker(slot), name=f"agent-{slot.agent.key}"
            )
        # Nhường một nhịp để mọi worker kịp vào vòng lặp chờ tin trước khi có
        # tin đầu tiên được gửi tới.
        await asyncio.sleep(0)

    async def stop(self, grace: float = 1.0) -> None:
        """Dừng tất cả worker.

        Chờ tối đa `grace` giây để các agent xử lý nốt tin đang dở, rồi **huỷ**
        những worker còn kẹt. Không có bước huỷ này thì một handler chậm (ví dụ
        đang chờ mạng) sẽ giữ `stop()` treo vô hạn — runtime phải tắt được kể cả
        khi có agent hỏng.
        """
        if not self._started:
            return
        for slot in self._slots.values():
            await slot.inbox.put(_STOP)
        workers = [s.worker for s in self._slots.values() if s.worker is not None]
        if workers:
            _done, pending = await asyncio.wait(workers, timeout=grace)
            for task in pending:
                task.cancel()
            if pending:
                await asyncio.gather(*pending, return_exceptions=True)
        for slot in self._slots.values():
            slot.worker = None
        self._started = False

    async def __aenter__(self) -> AgentRuntime:
        await self.start()
        return self

    async def __aexit__(self, *_exc) -> None:
        await self.stop(grace=self.shutdown_grace)

    @property
    def running(self) -> bool:
        return self._started

    # --- gửi tin ---

    async def deliver(self, message: ACLMessage) -> None:
        """Đưa một tin nhắn vào hộp thư của người nhận."""
        if message.receiver not in self._slots:
            raise KeyError(f"không có hộp thư cho '{message.receiver}'")
        await self._slots[message.receiver].inbox.put(message)

    async def send(
        self,
        sender: str,
        receiver: str,
        content: str,
        *,
        performative: Performative = Performative.INFORM,
        conversation_id: str | None = None,
        protocol: str = "lifeos",
        metadata: dict | None = None,
    ) -> ACLMessage:
        """Ghi tin vào bản ghi ACL rồi chuyển tới hộp thư người nhận.

        Dựng thẳng `ACLMessage` thay vì dùng `bus.request()`: hàm đó luôn gán
        `Performative.REQUEST`, còn ở đây cần cả `ACCEPT_PROPOSAL` và
        `REJECT_PROPOSAL`.
        """
        message = ACLMessage(
            performative=performative,
            sender=sender,
            receiver=receiver,
            content=content,
            conversation_id=conversation_id or uuid4().hex[:12],
            protocol=protocol,
            reply_with=uuid4().hex[:8],
            metadata=metadata or {},
        )
        self.bus.send(message)
        await self.deliver(message)
        return message

    # --- vòng lặp của agent ---

    async def _worker(self, slot: _AgentSlot) -> None:
        """Vòng lặp nền của một agent: nhận tin → xử lý → trả lời."""
        while True:
            message = await slot.inbox.get()
            if message is _STOP:
                slot.inbox.task_done()
                return
            try:
                if message.performative in RESPONDS_TO:
                    outcome = self._handle(slot, message)
                    if inspect.isawaitable(outcome):
                        outcome = await outcome
                    self._respond(slot, message, outcome)
                # Thông báo thì đã nằm trong bản ghi ACL; agent chỉ ghi nhận.
                self.stats.handled += 1
            except Exception as exc:  # noqa: BLE001 - một agent lỗi không được
                # làm sập cả runtime; ghi lại thành FAILURE rồi chạy tiếp.
                self.stats.failed += 1
                self.bus.send(
                    ACLMessage(
                        performative=Performative.FAILURE,
                        sender=slot.agent.key,
                        receiver=MANAGER,
                        content=f"{type(exc).__name__}: {exc}",
                        conversation_id=message.conversation_id,
                        in_reply_to=message.reply_with or message.conversation_id,
                        protocol=message.protocol,
                        metadata=dict(message.metadata),
                    )
                )
            finally:
                slot.inbox.task_done()

    def _handle(self, slot: _AgentSlot, message: ACLMessage):
        """Chạy hàm xử lý của agent (mặc định: tự đánh giá nhiệm vụ)."""
        if slot.handler is not None:
            return slot.handler(slot.agent, message)
        task = self._tasks.get(str(message.metadata.get("task_id", "")))
        if task is None:
            return None
        return slot.agent.assess(task)

    def _respond(self, slot: _AgentSlot, message: ACLMessage, outcome) -> None:
        """Ghi câu trả lời của agent vào bản ghi ACL và chuyển cho người gom."""
        reply: ACLMessage | None = None

        if isinstance(outcome, Bid):
            reply = self.bus.reply(
                message,
                slot.agent.key,
                Performative.PROPOSE,
                f"tin cậy {outcome.confidence:.2f}, chi phí {outcome.cost:.2f} "
                f"({outcome.reason})",
                # Ghi đủ confidence/cost để bên gom dựng lại đúng giá thầu,
                # không phải đoán từ phần nội dung.
                metadata={
                    **message.metadata,
                    "score": outcome.score,
                    "confidence": outcome.confidence,
                    "cost": outcome.cost,
                    "bid_reason": outcome.reason,
                },
            )
        elif isinstance(outcome, Refusal):
            reply = self.bus.reply(
                message,
                slot.agent.key,
                Performative.REFUSE,
                outcome.reason,
                metadata=dict(message.metadata),
            )
        elif isinstance(outcome, str):
            reply = self.bus.reply(
                message,
                slot.agent.key,
                Performative.INFORM,
                outcome,
                metadata=dict(message.metadata),
            )

        if reply is not None:
            collector = self._collectors.get(message.conversation_id)
            if collector is not None:
                collector.put_nowait(reply)

    # --- thương lượng bất đồng bộ ---

    async def negotiate(
        self,
        task: Task,
        agents: Iterable[AutonomousAgent] | None = None,
        *,
        timeout: float | None = None,
        conversation_id: str | None = None,
    ) -> ContractNetResult:
        """Một vòng Contract Net, nhưng các agent phản hồi thật sự đồng thời.

        Khác `ContractNet.run`: ở đây bộ điều phối **gửi tin rồi chờ**, không
        tự gọi hàm của từng agent theo thứ tự. Ai chậm thì phần người đó bị
        tính là không phản hồi, không kéo dài lượt chạy.
        """
        if not self._started:
            raise RuntimeError("phải gọi start() trước khi thương lượng")

        candidates = list(agents) if agents is not None else self.agents
        # `timeout if ... is not None` chứ không phải `timeout or self.timeout`:
        # `0.0` là giá trị hợp lệ (không chờ ai cả) nhưng lại falsy, nên toán tử
        # `or` sẽ âm thầm thay bằng mặc định.
        budget = self.timeout if timeout is None else timeout
        if not candidates:
            return ContractNetResult(
                task=task,
                conversation_id=conversation_id or "",
                reason="không có agent nào được đăng ký",
                original_effort=task.effort,
                remaining_effort=task.effort,
            )

        self._tasks[task.id] = task
        for agent in candidates:
            if agent.key not in self._slots:
                raise KeyError(f"agent '{agent.key}' chưa được đăng ký")

        announcements = self.bus.broadcast(
            self.manager,
            [agent.key for agent in candidates],
            f"{task.description} (kỹ năng: {task.skill or 'không yêu cầu'}, "
            f"công sức {task.effort:.2f})",
            performative=Performative.REQUEST,
            protocol=CONTRACT_NET_PROTOCOL,
            conversation_id=conversation_id,
            metadata={"task_id": task.id},
        )
        cid = announcements[0].conversation_id if announcements else ""

        collector: asyncio.Queue = asyncio.Queue()
        self._collectors[cid] = collector
        started = time.perf_counter()
        try:
            for announcement in announcements:
                await self.deliver(announcement)
            replies = await self._collect(collector, len(candidates), budget)
        finally:
            self._collectors.pop(cid, None)

        self.stats.duration_s += time.perf_counter() - started
        self.stats.timed_out += len(candidates) - len(replies)

        bids: list[Bid] = []
        refusals: list[Refusal] = []
        responded: set[str] = set()
        for reply in replies:
            responded.add(reply.sender)
            task_id = str(reply.metadata.get("task_id", task.id))
            if reply.performative is Performative.PROPOSE:
                bids.append(
                    Bid(
                        agent=reply.sender,
                        task_id=task_id,
                        confidence=reply.metadata.get("confidence", 0.5),
                        cost=reply.metadata.get("cost", 0.3),
                        reason=reply.metadata.get("bid_reason", reply.content),
                    )
                )
            else:
                refusals.append(
                    Refusal(agent=reply.sender, task_id=task_id, reason=reply.content)
                )

        # Agent không kịp phản hồi cũng phải xuất hiện trong lý do, nếu không
        # người dùng sẽ tưởng họ đã đồng ý.
        for agent in candidates:
            if agent.key not in responded:
                refusals.append(
                    Refusal(
                        agent=agent.key,
                        task_id=task.id,
                        reason=f"không phản hồi trong {budget:.1f}s",
                    )
                )

        result = ContractNetResult(
            task=task,
            conversation_id=cid,
            bids=bids,
            refusals=refusals,
            original_effort=task.effort,
        )

        if not bids:
            result.reason = no_winner_reason(refusals, candidates)
            result.remaining_effort = task.effort
            self.bus.inform(
                self.manager,
                self.manager,
                f"Không ai nhận '{task.id}': {result.reason}",
                conversation_id=cid,
            )
            return result

        winner = pick_winner(bids)
        result.awarded_to = winner.agent
        result.reason = (
            f"{winner.agent} thắng với điểm {winner.score:.3f} ({winner.reason})"
        )

        for agent in candidates:
            if agent.key == winner.agent:
                await self.send(
                    self.manager,
                    agent.key,
                    result.reason,
                    performative=Performative.ACCEPT_PROPOSAL,
                    conversation_id=cid,
                    protocol=CONTRACT_NET_PROTOCOL,
                    metadata={"task_id": task.id, "winner": winner.agent},
                )
            elif agent.key in responded:
                await self.send(
                    self.manager,
                    agent.key,
                    f"đã giao cho {winner.agent}",
                    performative=Performative.REJECT_PROPOSAL,
                    conversation_id=cid,
                    protocol=CONTRACT_NET_PROTOCOL,
                    metadata={"task_id": task.id},
                )

        self.agent(winner.agent).accept(task)
        return result

    async def negotiate_all(
        self,
        tasks: Iterable[Task],
        agents: Iterable[AutonomousAgent] | None = None,
        *,
        timeout: float | None = None,
    ) -> list[ContractNetResult]:
        """Giao lần lượt nhiều nhiệm vụ, ưu tiên việc gấp trước."""
        ordered = sorted(tasks, key=lambda t: (t.priority, t.id))
        return [
            await self.negotiate(task, agents, timeout=timeout) for task in ordered
        ]

    async def _collect(
        self, collector: asyncio.Queue, expected: int, timeout: float
    ) -> list[ACLMessage]:
        """Gom tối đa `expected` câu trả lời trong `timeout` giây."""
        replies: list[ACLMessage] = []
        deadline = time.perf_counter() + timeout
        for _ in range(expected):
            remaining = deadline - time.perf_counter()
            if remaining <= 0:
                break
            try:
                replies.append(await asyncio.wait_for(collector.get(), remaining))
            except TimeoutError:
                break
        return replies
