"""Giao thức trao đổi tin nhắn giữa các agent (lấy cảm hứng từ FIPA-ACL).

Khác với `Roundtable` (chỉ là bản ghi văn bản để hiển thị), module này mô hình
hoá **hành vi giao tiếp**: mỗi tin nhắn có một `performative` cho biết người gửi
đang *làm gì* (yêu cầu, thông báo, đề xuất, từ chối...), kèm định danh hội thoại
để ghép cặp câu hỏi - trả lời.

Đây là nền tảng cho Contract Net Protocol ở `contract_net.py`.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from enum import Enum
from uuid import uuid4

from pydantic import BaseModel, Field


class Performative(str, Enum):
    """Hành vi giao tiếp — "động từ" của tin nhắn."""

    REQUEST = "request"                  # yêu cầu thực hiện một việc
    INFORM = "inform"                    # thông báo thông tin
    PROPOSE = "propose"                  # đề xuất / bỏ thầu
    ACCEPT_PROPOSAL = "accept-proposal"  # chấp nhận đề xuất
    REJECT_PROPOSAL = "reject-proposal"  # từ chối đề xuất
    AGREE = "agree"                      # đồng ý nhận việc
    REFUSE = "refuse"                    # từ chối nhận việc
    CRITIQUE = "critique"                # phản biện nội dung
    FAILURE = "failure"                  # báo không hoàn thành được


#: Các performative là "câu trả lời" cho một đề xuất.
RESPONSE_PERFORMATIVES = frozenset(
    {
        Performative.ACCEPT_PROPOSAL,
        Performative.REJECT_PROPOSAL,
        Performative.AGREE,
        Performative.REFUSE,
    }
)


class ACLMessage(BaseModel):
    """Một tin nhắn theo giao thức ACL."""

    performative: Performative
    sender: str
    receiver: str
    content: str = ""
    conversation_id: str = Field(default_factory=lambda: uuid4().hex[:12])
    protocol: str = "lifeos"
    reply_with: str | None = None
    in_reply_to: str | None = None
    metadata: dict = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=datetime.now)

    @property
    def is_response(self) -> bool:
        return self.performative in RESPONSE_PERFORMATIVES

    def render(self) -> str:
        """Dạng người đọc được, dùng cho log và transcript."""
        head = f"[{self.performative.value}] {self.sender} -> {self.receiver}"
        if self.in_reply_to:
            head += f" (trả lời {self.in_reply_to})"
        return f"{head}: {self.content}"


class MessageBus:
    """Kênh trao đổi tin nhắn giữa các agent.

    Bus giữ toàn bộ lịch sử theo thứ tự gửi, đồng thời lập chỉ mục theo người
    nhận và theo hội thoại — đủ để dựng lại một phiên thương lượng.
    """

    def __init__(self) -> None:
        self._messages: list[ACLMessage] = []

    def send(self, message: ACLMessage) -> ACLMessage:
        """Gửi một tin nhắn vào bus."""
        self._messages.append(message)
        return message

    def request(
        self,
        sender: str,
        receiver: str,
        content: str,
        *,
        conversation_id: str | None = None,
        protocol: str = "lifeos",
        metadata: dict | None = None,
    ) -> ACLMessage:
        return self.send(
            ACLMessage(
                performative=Performative.REQUEST,
                sender=sender,
                receiver=receiver,
                content=content,
                conversation_id=conversation_id or uuid4().hex[:12],
                protocol=protocol,
                reply_with=uuid4().hex[:8],
                metadata=metadata or {},
            )
        )

    def inform(
        self,
        sender: str,
        receiver: str,
        content: str,
        *,
        conversation_id: str | None = None,
        in_reply_to: str | None = None,
    ) -> ACLMessage:
        return self.send(
            ACLMessage(
                performative=Performative.INFORM,
                sender=sender,
                receiver=receiver,
                content=content,
                conversation_id=conversation_id or uuid4().hex[:12],
                in_reply_to=in_reply_to,
            )
        )

    def reply(
        self,
        original: ACLMessage,
        sender: str,
        performative: Performative,
        content: str,
        *,
        metadata: dict | None = None,
    ) -> ACLMessage:
        """Trả lời một tin nhắn, tự ghép hội thoại và `in_reply_to`."""
        return self.send(
            ACLMessage(
                performative=performative,
                sender=sender,
                receiver=original.sender,
                content=content,
                conversation_id=original.conversation_id,
                protocol=original.protocol,
                in_reply_to=original.reply_with or original.conversation_id,
                metadata=metadata or {},
            )
        )

    def notify(
        self,
        original: ACLMessage,
        sender: str,
        receiver: str,
        performative: Performative,
        content: str,
        *,
        metadata: dict | None = None,
    ) -> ACLMessage:
        """Gửi tin **xuôi chiều** trong cùng hội thoại.

        Khác `reply()` (vốn đảo người gửi/người nhận), hàm này giữ nguyên chiều
        do bạn chỉ định. Cần cho Contract Net: bộ điều phối phải chủ động gửi
        `accept-proposal` tới người thắng, chứ không phải trả lời ngược lại.
        """
        return self.send(
            ACLMessage(
                performative=performative,
                sender=sender,
                receiver=receiver,
                content=content,
                conversation_id=original.conversation_id,
                protocol=original.protocol,
                in_reply_to=original.reply_with,
                metadata=metadata or {},
            )
        )

    def broadcast(
        self,
        sender: str,
        receivers: Iterable[str],
        content: str,
        *,
        performative: Performative = Performative.REQUEST,
        conversation_id: str | None = None,
        protocol: str = "lifeos",
        metadata: dict | None = None,
    ) -> list[ACLMessage]:
        """Gửi cùng một nội dung cho nhiều agent (dùng khi mời bỏ thầu)."""
        cid = conversation_id or uuid4().hex[:12]
        return [
            self.send(
                ACLMessage(
                    performative=performative,
                    sender=sender,
                    receiver=receiver,
                    content=content,
                    conversation_id=cid,
                    protocol=protocol,
                    reply_with=uuid4().hex[:8],
                    metadata=metadata or {},
                )
            )
            for receiver in receivers
        ]

    # --- truy vấn ---

    @property
    def messages(self) -> list[ACLMessage]:
        return list(self._messages)

    def __len__(self) -> int:
        return len(self._messages)

    def inbox(self, agent: str) -> list[ACLMessage]:
        """Tin nhắn gửi tới một agent."""
        return [m for m in self._messages if m.receiver == agent]

    def outbox(self, agent: str) -> list[ACLMessage]:
        """Tin nhắn do một agent gửi đi."""
        return [m for m in self._messages if m.sender == agent]

    def conversation(self, conversation_id: str) -> list[ACLMessage]:
        """Toàn bộ tin nhắn của một hội thoại, theo thứ tự."""
        return [m for m in self._messages if m.conversation_id == conversation_id]

    def replies_to(self, message: ACLMessage) -> list[ACLMessage]:
        """Các tin nhắn trả lời một tin nhắn cụ thể."""
        token = message.reply_with
        if not token:
            return []
        return [m for m in self._messages if m.in_reply_to == token]

    def transcript(self, conversation_id: str | None = None) -> str:
        """Bản ghi dạng văn bản, dùng để đưa vào prompt hoặc hiển thị."""
        source = (
            self.conversation(conversation_id)
            if conversation_id
            else self._messages
        )
        return "\n".join(m.render() for m in source)
