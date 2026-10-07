"""Test giao thức ACL."""

from __future__ import annotations

from lifeos.acl import (
    RESPONSE_PERFORMATIVES,
    ACLMessage,
    MessageBus,
    Performative,
)


# --- ACLMessage ---


def test_message_has_conversation_id_by_default():
    msg = ACLMessage(
        performative=Performative.INFORM, sender="a", receiver="b", content="x"
    )
    assert msg.conversation_id
    assert msg.protocol == "lifeos"
    assert msg.timestamp is not None


def test_two_messages_get_different_conversation_ids():
    first = ACLMessage(performative=Performative.INFORM, sender="a", receiver="b")
    second = ACLMessage(performative=Performative.INFORM, sender="a", receiver="b")
    assert first.conversation_id != second.conversation_id


def test_is_response_classification():
    for performative in RESPONSE_PERFORMATIVES:
        msg = ACLMessage(performative=performative, sender="a", receiver="b")
        assert msg.is_response is True
    for performative in (Performative.REQUEST, Performative.INFORM, Performative.PROPOSE):
        msg = ACLMessage(performative=performative, sender="a", receiver="b")
        assert msg.is_response is False


def test_render_includes_performative_and_route():
    msg = ACLMessage(
        performative=Performative.PROPOSE,
        sender="tutor",
        receiver="orchestrator",
        content="tôi nhận việc",
    )
    text = msg.render()
    assert "propose" in text
    assert "tutor -> orchestrator" in text
    assert "tôi nhận việc" in text


def test_render_mentions_in_reply_to_when_present():
    msg = ACLMessage(
        performative=Performative.AGREE,
        sender="tutor",
        receiver="orchestrator",
        in_reply_to="abc123",
    )
    assert "trả lời abc123" in msg.render()


# --- MessageBus: gửi cơ bản ---


def test_send_appends_in_order():
    bus = MessageBus()
    bus.inform("a", "b", "1")
    bus.inform("a", "b", "2")
    assert [m.content for m in bus.messages] == ["1", "2"]
    assert len(bus) == 2


def test_empty_bus():
    bus = MessageBus()
    assert len(bus) == 0
    assert bus.messages == []
    assert bus.transcript() == ""


def test_request_sets_reply_with_and_protocol():
    bus = MessageBus()
    msg = bus.request("orchestrator", "tutor", "làm lộ trình", protocol="contract-net")
    assert msg.performative == Performative.REQUEST
    assert msg.reply_with
    assert msg.protocol == "contract-net"


def test_request_can_reuse_conversation_id():
    bus = MessageBus()
    first = bus.request("o", "a", "x", conversation_id="cid-1")
    second = bus.request("o", "b", "y", conversation_id="cid-1")
    assert first.conversation_id == second.conversation_id == "cid-1"


# --- MessageBus: reply ---


def test_reply_swaps_sender_and_receiver():
    bus = MessageBus()
    request = bus.request("orchestrator", "tutor", "làm lộ trình")
    reply = bus.reply(request, "tutor", Performative.AGREE, "nhận việc")

    assert reply.sender == "tutor"
    assert reply.receiver == "orchestrator"
    assert reply.performative == Performative.AGREE


def test_reply_joins_same_conversation():
    bus = MessageBus()
    request = bus.request("o", "t", "x")
    reply = bus.reply(request, "t", Performative.AGREE, "ok")

    assert reply.conversation_id == request.conversation_id
    assert reply.protocol == request.protocol


def test_reply_links_via_in_reply_to():
    bus = MessageBus()
    request = bus.request("o", "t", "x")
    reply = bus.reply(request, "t", Performative.AGREE, "ok")

    assert reply.in_reply_to == request.reply_with
    assert bus.replies_to(request) == [reply]


def test_replies_to_unknown_message_is_empty():
    bus = MessageBus()
    orphan = ACLMessage(
        performative=Performative.REQUEST, sender="o", receiver="t"
    )
    assert bus.replies_to(orphan) == []


def test_multiple_replies_to_one_request():
    bus = MessageBus()
    request = bus.request("o", "t", "x")
    bus.reply(request, "t", Performative.PROPOSE, "tôi làm")
    bus.reply(request, "c", Performative.REFUSE, "tôi bận")
    assert len(bus.replies_to(request)) == 2


# --- MessageBus: broadcast ---


def test_broadcast_sends_to_every_receiver():
    bus = MessageBus()
    sent = bus.broadcast("orchestrator", ["tutor", "critic", "nudger"], "mời bỏ thầu")
    assert len(sent) == 3
    assert {m.receiver for m in sent} == {"tutor", "critic", "nudger"}


def test_broadcast_shares_one_conversation_id():
    bus = MessageBus()
    sent = bus.broadcast("o", ["a", "b"], "x")
    assert len({m.conversation_id for m in sent}) == 1


def test_broadcast_gives_each_receiver_its_own_reply_token():
    bus = MessageBus()
    sent = bus.broadcast("o", ["a", "b"], "x")
    assert sent[0].reply_with != sent[1].reply_with


def test_broadcast_empty_receiver_list():
    bus = MessageBus()
    assert bus.broadcast("o", [], "x") == []
    assert len(bus) == 0


# --- MessageBus: truy vấn ---


def test_inbox_and_outbox():
    bus = MessageBus()
    bus.inform("a", "b", "1")
    bus.inform("b", "a", "2")
    bus.inform("c", "b", "3")

    assert len(bus.inbox("b")) == 2
    assert len(bus.outbox("a")) == 1
    assert bus.outbox("a")[0].content == "1"


def test_inbox_unknown_agent_is_empty():
    bus = MessageBus()
    bus.inform("a", "b", "1")
    assert bus.inbox("khong-ai") == []


def test_conversation_isolates_threads():
    bus = MessageBus()
    bus.request("o", "t", "việc 1", conversation_id="c1")
    bus.request("o", "t", "việc 2", conversation_id="c2")
    bus.request("o", "c", "việc 3", conversation_id="c1")

    assert len(bus.conversation("c1")) == 2
    assert len(bus.conversation("c2")) == 1
    assert bus.conversation("khong-co") == []


def test_transcript_covers_all_messages():
    bus = MessageBus()
    bus.request("o", "t", "một")
    bus.inform("t", "o", "hai")
    text = bus.transcript()
    assert "một" in text and "hai" in text
    assert text.count("\n") == 1


def test_transcript_filtered_by_conversation():
    bus = MessageBus()
    bus.request("o", "t", "thuộc c1", conversation_id="c1")
    bus.request("o", "t", "thuộc c2", conversation_id="c2")

    text = bus.transcript("c1")
    assert "thuộc c1" in text
    assert "thuộc c2" not in text


def test_messages_property_returns_copy():
    bus = MessageBus()
    bus.inform("a", "b", "1")
    snapshot = bus.messages
    snapshot.clear()
    assert len(bus) == 1