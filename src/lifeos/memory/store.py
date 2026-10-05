"""Lớp lưu trữ SQLite dùng SQLAlchemy ORM."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator, Optional

from sqlalchemy import JSON, Integer, String, Text, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker


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

    def latest_plan(self, goal_summary: str) -> Optional[dict]:
        with self.session() as s:
            rec = (
                s.query(PlanRecord)
                .filter(PlanRecord.goal_summary == goal_summary)
                .order_by(PlanRecord.id.desc())
                .first()
            )
            return rec.payload if rec else None