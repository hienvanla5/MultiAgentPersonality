"""Test runtime agent chạy nền thật (T4).

Trước đây `MessageBus` chỉ là một cuốn sổ: thương lượng xong mới ghi lại, không
agent nào thực sự chạy, không ai có hộp thư, và `asyncio` không được dùng ở đâu
trong `src/lifeos` (0 lời gọi `async def`/`await`).

Ở đây kiểm chứng những thứ chỉ đúng khi agent **thật sự** chạy nền: đồng thời
thật, agent chậm không chặn người khác, agent lỗi không làm sập runtime.
"""

from __future__ import annotations

import asyncio
import time

import pytest

from lifeos.acl import ACLMessage, MessageBus, Performative
from lifeos.agents.autonomy import AutonomousAgent, Bid, Task
from lifeos.agents.team import self_organize_async
from lifeos.runtime import (
    DEFAULT_SHUTDOWN_GRACE,
    DEFAULT_TIMEOUT,
    AgentRuntime,
    RuntimeStats,
)

DELAY = 0.15


def _agent(key: str, skills: list[str], capacity: float = 1.0) -> AutonomousAgent:
    return AutonomousAgent(key, skills=skills, capacity=capacity)


def _task(effort: float = 0.3, skill: str = "scheduling", task_id: str = "t") -> Task:
    return Task(id=task_id, description="việc", skill=skill, effort=effort)


def _bid(agent_key: str, task_id: str = "t", cost: float = 0.1) -> Bid:
    """Giá thầu để handler tự trả về.

    Handler trả về **chuỗi** được ghi thành `INFORM` (một thông báo), không
    phải `PROPOSE` — nên muốn tham gia bỏ thầu thì phải trả về `Bid`.
    """
    return Bid(
        agent=agent_key,
        task_id=task_id,
        confidence=0.9,
        cost=cost,
        reason="sẵn sàng nhận",
    )


async def _slow_bid_handler(delay: float = DELAY):
    """Handler bất đồng bộ có độ trễ, để đo tính đồng thời."""

    async def handler(agent, message):
        await asyncio.sleep(delay)
        return _bid(agent.key)

    return handler


# --- đăng ký và vòng đời ---


async def test_start_requires_registered_agents():
    runtime = AgentRuntime()
    with pytest.raises(RuntimeError, match="chưa có agent nào"):
        await runtime.start()


async def test_start_twice_is_refused():
    runtime = AgentRuntime()
    runtime.register(_agent("a", ["x"]))
    await runtime.start()
    try:
        with pytest.raises(RuntimeError, match="đã chạy"):
            await runtime.start()
    finally:
        await runtime.stop()


async def test_context_manager_starts_and_stops():
    runtime = AgentRuntime()
    runtime.register(_agent("a", ["x"]))
    async with runtime:
        assert runtime.running is True
    assert runtime.running is False


async def test_duplicate_registration_is_refused():
    runtime = AgentRuntime()
    runtime.register(_agent("a", ["x"]))
    with pytest.raises(ValueError, match="đã được đăng ký"):
        runtime.register(_agent("a", ["y"]))


async def test_stop_is_idempotent():
    runtime = AgentRuntime()
    runtime.register(_agent("a", ["x"]))
    await runtime.start()
    await runtime.stop()
    await runtime.stop()  # không được ném lỗi


async def test_stop_is_bounded_even_with_a_stuck_handler():
    """Handler kẹt không được giữ `stop()` treo vô hạn."""
    runtime = AgentRuntime(timeout=0.1, shutdown_grace=0.1)

    async def stuck(agent, message):
        await asyncio.sleep(60.0)

    runtime.register(_agent("ket", ["scheduling"]), handler=stuck)
    await runtime.start()
    await runtime.deliver(
        ACLMessage(
            performative=Performative.REQUEST,
            sender="orchestrator",
            receiver="ket",
            content="việc",
        )
    )
    await asyncio.sleep(0.05)  # để worker kịp nhận và kẹt trong handler

    started = time.perf_counter()
    await runtime.stop()
    elapsed = time.perf_counter() - started

    assert elapsed < 2.0, f"stop() bị treo {elapsed:.2f}s"
    assert runtime.running is False


async def test_cancelled_handler_is_not_counted_as_failure():
    """Huỷ worker lúc tắt máy không phải là lỗi của agent."""
    runtime = AgentRuntime(timeout=0.1, shutdown_grace=0.05)

    async def stuck(agent, message):
        await asyncio.sleep(60.0)

    runtime.register(_agent("ket", ["scheduling"]), handler=stuck)
    await runtime.start()
    await runtime.deliver(
        ACLMessage(
            performative=Performative.REQUEST,
            sender="orchestrator",
            receiver="ket",
            content="việc",
        )
    )
    await asyncio.sleep(0.05)
    await runtime.stop()

    assert runtime.stats.failed == 0
    assert not [
        m for m in runtime.bus.messages if m.performative is Performative.FAILURE
    ]


async def test_agents_property_lists_registered():
    runtime = AgentRuntime()
    runtime.register(_agent("a", ["x"]))
    runtime.register(_agent("b", ["y"]))
    assert [a.key for a in runtime.agents] == ["a", "b"]


async def test_unknown_agent_inbox_raises():
    runtime = AgentRuntime()
    with pytest.raises(KeyError, match="chưa được đăng ký"):
        runtime.inbox("không-có")


async def test_deliver_to_unknown_agent_raises():
    runtime = AgentRuntime()
    runtime.register(_agent("a", ["x"]))

    async with runtime:
        with pytest.raises(KeyError):
            await runtime.deliver(
                ACLMessage(
                    performative=Performative.INFORM,
                    sender="x",
                    receiver="không-có",
                    content="hi",
                )
            )


# --- đồng thời thật ---


async def test_agents_run_concurrently_not_sequentially():
    """Ba agent ngủ 0.15s cùng lúc phải xong trong ~0.15s, không phải ~0.45s."""
    runtime = AgentRuntime(timeout=2.0)
    for key in ("a", "b", "c"):
        runtime.register(
            _agent(key, ["scheduling"]), handler=await _slow_bid_handler()
        )

    async with runtime:
        started = time.perf_counter()
        results = await asyncio.gather(
            *[
                runtime.negotiate(_task(task_id=f"t-{key}"), [runtime.agent(key)])
                for key in ("a", "b", "c")
            ]
        )
        elapsed = time.perf_counter() - started

    assert all(r.assigned for r in results)
    assert elapsed < DELAY * 2, f"chạy tuần tự rồi: {elapsed:.3f}s"


async def test_one_slow_agent_does_not_block_others():
    """Agent chậm bị coi là không phản hồi, người nhanh vẫn có kết quả."""
    # `shutdown_grace` nhỏ để test không phải chờ handler 5s lúc tắt runtime.
    runtime = AgentRuntime(timeout=0.5, shutdown_grace=0.05)

    async def slow(agent, message):
        await asyncio.sleep(5.0)
        return _bid(agent.key)

    async def fast(agent, message):
        return _bid(agent.key, cost=0.05)

    runtime.register(_agent("cham", ["scheduling"]), handler=slow)
    runtime.register(_agent("nhanh", ["scheduling"]), handler=fast)

    async with runtime:
        started = time.perf_counter()
        result = await runtime.negotiate(_task(task_id="t"), runtime.agents)
        elapsed = time.perf_counter() - started

    assert result.awarded_to == "nhanh"
    assert elapsed < 2.0, f"bị agent chậm giữ: {elapsed:.3f}s"
    assert result.refusals  # agent chậm phải xuất hiện trong lý do


async def test_timeout_is_reported_as_no_response():
    """Agent không kịp phản hồi phải hiện ra, không được im lặng biến mất."""
    runtime = AgentRuntime(timeout=0.2, shutdown_grace=0.05)

    async def slow(agent, message):
        await asyncio.sleep(5.0)
        return "muộn"

    runtime.register(_agent("cham", ["scheduling"]), handler=slow)

    async with runtime:
        result = await runtime.negotiate(_task(task_id="t"), runtime.agents)

    assert result.assigned is False
    assert "không phản hồi" in result.reason
    assert runtime.stats.timed_out == 1


async def test_stats_count_handled_messages():
    """`handled` đếm mọi tin agent nhận, gồm cả thông báo trúng thầu.

    Mỗi lượt thương lượng có hai tin tới agent: công bố nhiệm vụ, rồi thông báo
    `ACCEPT_PROPOSAL`. Cả hai đều đi qua hộp thư thật nên đều được xử lý.
    """
    runtime = AgentRuntime(timeout=2.0)
    runtime.register(
        _agent("a", ["scheduling"]), handler=await _slow_bid_handler(0.01)
    )

    async with runtime:
        await runtime.negotiate(_task(task_id="t1"), runtime.agents)
        await runtime.negotiate(_task(task_id="t2"), runtime.agents)

    assert runtime.stats.handled == 4  # 2 công bố + 2 thông báo trúng thầu
    assert runtime.stats.failed == 0
    assert "đã xử lý 4 tin" in runtime.stats.summary()


# --- cô lập lỗi ---


async def test_agent_error_does_not_crash_runtime():
    """Một agent ném lỗi thì các agent khác vẫn phải chạy tiếp."""
    runtime = AgentRuntime(timeout=1.0)

    async def boom(agent, message):
        raise ValueError("hỏng phần cứng")

    async def ok(agent, message):
        return _bid(agent.key, cost=0.05)

    runtime.register(_agent("loi", ["scheduling"]), handler=boom)
    runtime.register(_agent("on", ["scheduling"]), handler=ok)

    async with runtime:
        result = await runtime.negotiate(_task(task_id="t"), runtime.agents)
        # Runtime vẫn sống và nhận việc tiếp
        assert runtime.running is True
        second = await runtime.negotiate(_task(task_id="t2"), [runtime.agent("on")])

    assert result.awarded_to == "on"
    assert second.awarded_to == "on"
    assert runtime.stats.failed == 1


async def test_agent_error_is_recorded_as_failure_message():
    runtime = AgentRuntime(timeout=1.0)

    async def boom(agent, message):
        raise ValueError("hỏng")

    runtime.register(_agent("loi", ["scheduling"]), handler=boom)

    async with runtime:
        await runtime.negotiate(_task(task_id="t"), runtime.agents)

    failures = [
        m for m in runtime.bus.messages if m.performative is Performative.FAILURE
    ]
    assert len(failures) == 1
    assert failures[0].sender == "loi"
    assert "ValueError" in failures[0].content


async def test_sync_handler_exception_is_isolated():
    runtime = AgentRuntime(timeout=1.0)

    def boom(agent, message):
        raise RuntimeError("handler đồng bộ hỏng")

    runtime.register(_agent("loi", ["scheduling"]), handler=boom)
    runtime.register(_agent("on", ["scheduling"]), handler=lambda a, m: _bid(a.key))

    async with runtime:
        result = await runtime.negotiate(_task(task_id="t"), runtime.agents)

    assert result.awarded_to == "on"
    assert runtime.stats.failed == 1


# --- thương lượng bất đồng bộ ---


async def test_negotiate_requires_start():
    runtime = AgentRuntime()
    runtime.register(_agent("a", ["scheduling"]))
    with pytest.raises(RuntimeError, match="start"):
        await runtime.negotiate(_task(), runtime.agents)


async def test_default_handler_uses_agent_own_assessment():
    """Không truyền handler: agent tự đánh giá, đúng tinh thần tự trị."""
    runtime = AgentRuntime(timeout=2.0)
    runtime.register(_agent("scheduler", ["scheduling"]))
    runtime.register(_agent("tutor", ["curriculum"]))

    async with runtime:
        result = await runtime.negotiate(_task(skill="scheduling"), runtime.agents)

    assert result.awarded_to == "scheduler"
    # tutor từ chối vì ngoài chuyên môn
    assert any(r.agent == "tutor" and "chuyên môn" in r.reason for r in result.refusals)


async def test_negotiate_assigns_work_to_winner():
    runtime = AgentRuntime(timeout=2.0)
    runtime.register(_agent("scheduler", ["scheduling"]))

    async with runtime:
        await runtime.negotiate(_task(effort=0.4, task_id="t"), runtime.agents)

    assert runtime.agent("scheduler").state.load == pytest.approx(0.4)


async def test_negotiate_with_no_agents():
    runtime = AgentRuntime()
    runtime.register(_agent("a", ["x"]))
    async with runtime:
        result = await runtime.negotiate(_task(), [])
    assert result.assigned is False
    assert "không có agent nào" in result.reason


async def test_negotiate_with_unregistered_agent_raises():
    runtime = AgentRuntime(timeout=1.0)
    runtime.register(_agent("a", ["scheduling"]))
    async with runtime:
        with pytest.raises(KeyError):
            await runtime.negotiate(_task(), [_agent("la", ["scheduling"])])


async def test_negotiate_bid_metadata_roundtrips():
    """Giá thầu dựng lại từ tin nhắn phải giữ đúng confidence và cost."""
    runtime = AgentRuntime(timeout=2.0)
    runtime.register(_agent("scheduler", ["scheduling"], capacity=0.5))

    async with runtime:
        result = await runtime.negotiate(_task(effort=0.25, task_id="t"), runtime.agents)

    bid = result.bids[0]
    assert bid.agent == "scheduler"
    assert 0.0 <= bid.confidence <= 1.0
    assert bid.cost == pytest.approx(0.5)  # 0.25 / 0.5
    assert "năng lực" in bid.reason


async def test_negotiate_all_orders_by_priority():
    runtime = AgentRuntime(timeout=2.0)
    for key in ("a", "b", "c"):
        runtime.register(_agent(key, ["scheduling"], capacity=1.0))

    tasks = [
        Task(id="thap", description="c", skill="scheduling", effort=0.1, priority=3),
        Task(id="cao", description="a", skill="scheduling", effort=0.1, priority=1),
        Task(id="vua", description="b", skill="scheduling", effort=0.1, priority=2),
    ]
    async with runtime:
        results = await runtime.negotiate_all(tasks, runtime.agents)

    assert [r.task.id for r in results] == ["cao", "vua", "thap"]


async def test_negotiate_respects_capacity():
    """Bất biến an toàn: agent không bao giờ bị giao quá năng lực."""
    runtime = AgentRuntime(timeout=2.0)
    agent = _agent("scheduler", ["scheduling"], capacity=0.5)
    runtime.register(agent)

    tasks = [
        Task(id="t1", description="a", skill="scheduling", effort=0.5, priority=1),
        Task(id="t2", description="b", skill="scheduling", effort=0.5, priority=2),
    ]
    async with runtime:
        results = await runtime.negotiate_all(tasks, runtime.agents)

    assert results[0].assigned is True
    assert results[1].assigned is False
    assert agent.state.load <= agent.state.capacity


async def test_no_response_reason_mentions_timeout():
    runtime = AgentRuntime(timeout=0.15, shutdown_grace=0.05)

    async def slow(agent, message):
        await asyncio.sleep(5.0)

    runtime.register(_agent("cham", ["scheduling"]), handler=slow)
    async with runtime:
        result = await runtime.negotiate(_task(task_id="t"), runtime.agents)

    assert "0.1s" in result.reason or "0.2s" in result.reason


# --- bản ghi ACL ---


async def test_all_messages_share_one_conversation():
    runtime = AgentRuntime(timeout=2.0)
    runtime.register(_agent("scheduler", ["scheduling"]))
    runtime.register(_agent("tutor", ["curriculum"]))

    async with runtime:
        result = await runtime.negotiate(_task(task_id="t"), runtime.agents)

    conversation = runtime.bus.conversation(result.conversation_id)
    assert len(conversation) == len(runtime.bus)
    assert conversation  # có tin thật


async def test_transcript_shows_request_and_propose():
    runtime = AgentRuntime(timeout=2.0)
    runtime.register(_agent("scheduler", ["scheduling"]))

    async with runtime:
        result = await runtime.negotiate(_task(task_id="t"), runtime.agents)

    transcript = runtime.bus.transcript(result.conversation_id)
    assert "[request]" in transcript
    assert "[propose]" in transcript
    assert "[accept-proposal]" in transcript


async def test_send_records_and_delivers():
    runtime = AgentRuntime(timeout=1.0)
    received = []

    def handler(agent, message):
        received.append(message.content)
        return "đã nhận"

    runtime.register(_agent("a", ["x"]), handler=handler)

    async with runtime:
        await runtime.send(
            "orchestrator",
            "a",
            "xin chào",
            performative=Performative.REQUEST,
            conversation_id="c1",
        )
        await asyncio.sleep(0.05)

    assert received == ["xin chào"]
    assert runtime.bus.conversation("c1")[0].content == "xin chào"


async def test_agent_does_not_reply_to_notifications():
    """Thông báo trúng thầu không được sinh thêm một 'giá thầu' nữa.

    Lỗi này từng có thật: handler được gọi cho mọi tin nhắn, nên agent bỏ thầu
    cho chính tin báo mình đã trúng thầu, làm bản ghi ACL có thừa một tin.
    """
    runtime = AgentRuntime(timeout=2.0)
    runtime.register(_agent("scheduler", ["scheduling"]))

    async with runtime:
        result = await runtime.negotiate(_task(task_id="t"), runtime.agents)

    conversation = runtime.bus.conversation(result.conversation_id)
    proposes = [m for m in conversation if m.performative is Performative.PROPOSE]
    assert len(proposes) == 1, f"thừa giá thầu: {[m.render() for m in proposes]}"

    # Tin cuối cùng của hội thoại là thông báo trúng thầu, không phải thầu mới
    assert conversation[-1].performative is Performative.ACCEPT_PROPOSAL
    assert conversation[-1].receiver == "scheduler"


async def test_inform_message_is_recorded_but_not_answered():
    runtime = AgentRuntime(timeout=1.0)
    calls = []

    def handler(agent, message):
        calls.append(message.content)
        return "trả lời"

    runtime.register(_agent("a", ["x"]), handler=handler)

    async with runtime:
        await runtime.send(
            "orchestrator", "a", "chỉ để báo", performative=Performative.INFORM
        )
        await asyncio.sleep(0.05)

    assert calls == []  # handler không được gọi cho tin thông báo
    assert len(runtime.bus) == 1  # nhưng tin vẫn nằm trong bản ghi


async def test_bus_can_be_shared_with_contract_net():
    """Dùng chung bus với ContractNet thì bản ghi vẫn đọc được như cũ."""
    bus = MessageBus()
    runtime = AgentRuntime(bus, timeout=2.0)
    runtime.register(_agent("scheduler", ["scheduling"]))

    async with runtime:
        result = await runtime.negotiate(_task(task_id="t"), runtime.agents)

    assert result.conversation_id in {m.conversation_id for m in bus.messages}


# --- tích hợp với tự tổ chức nhóm ---


async def test_self_organize_async_staffs_the_team():
    plan = await self_organize_async("mục tiêu")
    assert plan.fully_staffed is True
    assert set(plan.members) == {"career", "tutor", "scheduler", "critic", "nudger"}


async def test_self_organize_async_matches_sync_result():
    """Hai đường chạy phải cho cùng kết quả phân việc, chỉ khác cách chạy."""
    from lifeos.agents.team import self_organize

    sync_plan = self_organize("mục tiêu")
    async_plan = await self_organize_async("mục tiêu")

    assert async_plan.members == sync_plan.members
    assert async_plan.excluded == sync_plan.excluded
    assert [r.awarded_to for r in async_plan.results] == [
        r.awarded_to for r in sync_plan.results
    ]


async def test_self_organize_async_with_llm_decomposition():
    from lifeos.agents.schemas import DecomposedTask, TaskBreakdown
    from lifeos.agents.team import decompose

    class Stub:
        def structured(self, system_prompt, user_prompt, schema):
            return TaskBreakdown(
                tasks=[
                    DecomposedTask(id="a", description="x", skill="gap-analysis"),
                    DecomposedTask(id="b", description="y", skill="curriculum"),
                ]
            )

        def text(self, *a, **k):
            raise AssertionError

    plan = await self_organize_async("mục tiêu", llm=Stub())
    assert set(plan.members) == {"career", "tutor"}
    assert plan.fully_staffed is True
    assert [t.id for t in decompose("mục tiêu", llm=Stub()).tasks] == ["a", "b"]


async def test_self_organize_async_timeout_is_respected():
    """timeout = 0 nghĩa là không chờ ai cả, không phải 'dùng mặc định'."""
    plan = await self_organize_async("mục tiêu", timeout=0.0)
    assert plan.fully_staffed is False
    assert len(plan.unassigned) == len(plan.results)


# --- chi tiết ---


async def test_default_timeout_is_positive():
    assert DEFAULT_TIMEOUT > 0
    assert DEFAULT_SHUTDOWN_GRACE > 0


def test_runtime_stats_total_and_summary():
    stats = RuntimeStats(handled=3, failed=1, timed_out=2, duration_s=0.5)
    assert stats.total == 4
    assert "3 tin" in stats.summary()
    assert "1 lỗi" in stats.summary()
    assert "2 hết hạn" in stats.summary()


async def test_worker_loop_survives_many_messages():
    runtime = AgentRuntime(timeout=2.0)
    runtime.register(_agent("a", ["scheduling"]), handler=lambda ag, m: _bid(ag.key))

    async with runtime:
        for i in range(20):
            await runtime.negotiate(_task(task_id=f"t{i}"), runtime.agents)

    # 20 công bố + 20 thông báo trúng thầu
    assert runtime.stats.handled == 40
    assert runtime.stats.failed == 0
