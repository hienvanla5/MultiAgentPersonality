"""Lớp lưu trữ SQLite dùng SQLAlchemy ORM."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date

from sqlalchemy import (
    JSON,
    Float,
    Integer,
    String,
    Text,
    UniqueConstraint,
    create_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

#: Giá trị `plan_id` dùng cho thẻ không gắn với kế hoạch cụ thể nào.
#: Dùng số 0 thay vì NULL để ràng buộc duy nhất (plan_id, topic) hoạt động được —
#: SQLite coi mọi giá trị NULL là khác nhau nên NULL sẽ phá vỡ tính duy nhất.
GLOBAL_PLAN_ID = 0


class Base(DeclarativeBase):
    pass


class PlanRecord(Base):
    """Lưu một kế hoạch Life OS đã tạo (JSON hoá các schema Pydantic)."""

    __tablename__ = "plans"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    goal_summary: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_at: Mapped[str] = mapped_column(String(40), nullable=False)


class EventRecord(Base):
    """Lưu các sự kiện điều chỉnh kế hoạch."""

    __tablename__ = "events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_at: Mapped[str] = mapped_column(String(40), nullable=False)


class ReviewCardRecord(Base):
    """Lưu một thẻ ôn tập cách quãng (SRS).

    `due_date` và `last_reviewed` lưu dạng chuỗi ISO `YYYY-MM-DD`. Định dạng này
    so sánh theo thứ tự từ điển cũng đúng như theo thời gian, nên truy vấn
    "đến hạn" chỉ cần một phép so sánh chuỗi.
    """

    __tablename__ = "review_cards"
    __table_args__ = (
        UniqueConstraint("plan_id", "topic", name="uq_review_card_plan_topic"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    plan_id: Mapped[int] = mapped_column(Integer, nullable=False, default=GLOBAL_PLAN_ID)
    topic: Mapped[str] = mapped_column(String(300), nullable=False)
    module_ref: Mapped[str | None] = mapped_column(String(300), nullable=True)
    ease: Mapped[float] = mapped_column(Float, nullable=False, default=2.5)
    interval_days: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    repetitions: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    lapses: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    due_date: Mapped[str] = mapped_column(String(10), nullable=False)
    last_reviewed: Mapped[str | None] = mapped_column(String(10), nullable=True)
    updated_at: Mapped[str] = mapped_column(String(40), nullable=False, default="")


def _card_to_dict(rec: ReviewCardRecord) -> dict:
    """Chuyển bản ghi ORM thành dict thuần để tầng trên dựng lại Pydantic."""
    return {
        "plan_id": rec.plan_id,
        "topic": rec.topic,
        "module_ref": rec.module_ref,
        "ease": rec.ease,
        "interval_days": rec.interval_days,
        "repetitions": rec.repetitions,
        "lapses": rec.lapses,
        "due_date": rec.due_date,
        "last_reviewed": rec.last_reviewed,
    }


class Store:
    def __init__(self, db_url: str):
        self._engine = create_engine(db_url, future=True)
        Base.metadata.create_all(self._engine)
        self._session_factory = sessionmaker(bind=self._engine, future=True)

    @contextmanager
    def session(self) -> Iterator[Session]:
        with self._session_factory() as session:
            yield session

    def save_plan(self, goal_summary: str, payload: dict, created_at: str) -> int:
        with self.session() as s:
            rec = PlanRecord(
                goal_summary=goal_summary, payload=payload, created_at=created_at
            )
            s.add(rec)
            s.commit()
            return rec.id

    def save_event(self, reason: str, payload: dict, created_at: str) -> int:
        with self.session() as s:
            rec = EventRecord(reason=reason, payload=payload, created_at=created_at)
            s.add(rec)
            s.commit()
            return rec.id

    def latest_plan(self, goal_summary: str) -> dict | None:
        with self.session() as s:
            rec = (
                s.query(PlanRecord)
                .filter(PlanRecord.goal_summary == goal_summary)
                .order_by(PlanRecord.id.desc())
                .first()
            )
            return rec.payload if rec else None

    def get_plan(self, plan_id: int) -> dict | None:
        """Lấy payload của một kế hoạch theo id."""
        with self.session() as s:
            rec = s.get(PlanRecord, plan_id)
            return rec.payload if rec else None

    def list_plans(self, limit: int = 20) -> list[dict]:
        """Liệt kê kế hoạch đã lưu, mới nhất trước."""
        with self.session() as s:
            recs = (
                s.query(PlanRecord)
                .order_by(PlanRecord.id.desc())
                .limit(max(1, limit))
                .all()
            )
            return [
                {
                    "id": rec.id,
                    "goal_summary": rec.goal_summary,
                    "created_at": rec.created_at,
                }
                for rec in recs
            ]

    def update_plan(self, plan_id: int, payload: dict) -> bool:
        """Ghi đè payload của một kế hoạch (dùng khi cập nhật tiến độ)."""
        with self.session() as s:
            rec = s.get(PlanRecord, plan_id)
            if rec is None:
                return False
            rec.payload = payload
            s.commit()
            return True

    # --- thẻ ôn tập cách quãng (SRS) ---

    def save_cards(
        self,
        plan_id: int,
        cards: list[dict],
        updated_at: str = "",
    ) -> int:
        """Lưu danh sách thẻ, ghi đè theo khoá (plan_id, topic).

        Gọi lại nhiều lần với cùng dữ liệu **không** tạo bản ghi trùng — nhờ vậy
        người dùng bấm "lưu" nhiều lần vẫn an toàn.

        Thẻ có dữ liệu không đọc được (chủ đề rỗng, `ease` không phải số) bị **bỏ
        qua riêng lẻ** chứ không làm hỏng cả lượt lưu: một thẻ hỏng không được
        phép xoá sạch tiến độ ôn của những thẻ còn lại. Trả về số thẻ đã ghi.
        """
        if not cards:
            return 0
        written = 0
        with self.session() as s:
            for card in cards:
                topic = str(card.get("topic") or "").strip()
                if not topic:
                    # Thẻ không có chủ đề thì không có khoá để ghi đè.
                    continue
                numbers = _card_numbers(card)
                if numbers is None:
                    continue
                rec = (
                    s.query(ReviewCardRecord)
                    .filter(
                        ReviewCardRecord.plan_id == plan_id,
                        ReviewCardRecord.topic == topic,
                    )
                    .first()
                )
                if rec is None:
                    rec = ReviewCardRecord(plan_id=plan_id, topic=topic)
                    s.add(rec)
                rec.module_ref = card.get("module_ref")
                rec.ease = numbers["ease"]
                rec.interval_days = numbers["interval_days"]
                rec.repetitions = numbers["repetitions"]
                rec.lapses = numbers["lapses"]
                rec.due_date = _iso_date(card.get("due_date"))
                last = card.get("last_reviewed")
                rec.last_reviewed = _iso_date(last) if last else None
                rec.updated_at = updated_at
                written += 1
            s.commit()
        return written

    def load_cards(self, plan_id: int | None = None) -> list[dict]:
        """Lấy thẻ đã lưu. Không truyền `plan_id` thì lấy tất cả."""
        with self.session() as s:
            q = s.query(ReviewCardRecord)
            if plan_id is not None:
                q = q.filter(ReviewCardRecord.plan_id == plan_id)
            recs = q.order_by(ReviewCardRecord.topic).all()
            return [_card_to_dict(r) for r in recs]

    def due_cards(
        self, plan_id: int | None = None, today: str | None = None
    ) -> list[dict]:
        """Thẻ đã đến hạn, thẻ quá hạn lâu nhất lên trước."""
        cutoff = today or date.today().isoformat()
        with self.session() as s:
            q = s.query(ReviewCardRecord).filter(
                ReviewCardRecord.due_date <= cutoff
            )
            if plan_id is not None:
                q = q.filter(ReviewCardRecord.plan_id == plan_id)
            recs = q.order_by(
                ReviewCardRecord.due_date, ReviewCardRecord.topic
            ).all()
            return [_card_to_dict(r) for r in recs]

    def get_card(self, plan_id: int, topic: str) -> dict | None:
        """Lấy một thẻ theo khoá (plan_id, topic)."""
        with self.session() as s:
            rec = (
                s.query(ReviewCardRecord)
                .filter(
                    ReviewCardRecord.plan_id == plan_id,
                    ReviewCardRecord.topic == topic,
                )
                .first()
            )
            return _card_to_dict(rec) if rec else None

    def count_cards(self, plan_id: int | None = None) -> int:
        with self.session() as s:
            q = s.query(ReviewCardRecord)
            if plan_id is not None:
                q = q.filter(ReviewCardRecord.plan_id == plan_id)
            return q.count()

    def delete_cards(self, plan_id: int) -> int:
        """Xoá toàn bộ thẻ của một kế hoạch. Trả về số thẻ đã xoá."""
        with self.session() as s:
            deleted = (
                s.query(ReviewCardRecord)
                .filter(ReviewCardRecord.plan_id == plan_id)
                .delete()
            )
            s.commit()
            return int(deleted)


def _card_numbers(card: dict) -> dict | None:
    """Ép các trường số của thẻ về đúng kiểu. Trả về None nếu không đọc được.

    Trả về None (thay vì âm thầm dùng giá trị mặc định) để thẻ hỏng bị bỏ qua
    thay vì ghi vào DB một tiến độ ôn sai lệch mà người dùng không biết.
    """
    try:
        return {
            "ease": float(card.get("ease", 2.5)),
            "interval_days": int(card.get("interval_days", 1)),
            "repetitions": int(card.get("repetitions", 0)),
            "lapses": int(card.get("lapses", 0)),
        }
    except (TypeError, ValueError):
        return None


def _iso_date(value) -> str:
    """Chuẩn hoá `date`/`datetime`/chuỗi thành `YYYY-MM-DD`.

    Nhận cả ba kiểu vì thẻ có thể đến từ Pydantic (`date`), từ JSON đã lưu
    (chuỗi) hoặc từ dữ liệu cũ. Giá trị không phân tích được thì trả về **hôm
    nay**: với `due_date` điều đó có nghĩa là thẻ hiện ra ngay để người dùng ôn,
    an toàn hơn là làm hỏng cả lượt lưu.
    """
    if value is None:
        return date.today().isoformat()
    text = value.strip() if isinstance(value, str) else None
    if text is None:
        if not hasattr(value, "isoformat"):
            return date.today().isoformat()
        text = value.isoformat()
    try:
        return date.fromisoformat(text[:10]).isoformat()
    except ValueError:
        return date.today().isoformat()
