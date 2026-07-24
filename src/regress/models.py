"""Data model per CLAUDE.md's minimum schema.

Phase 1 implements `traces`, `spans`, and `messages`. `scores`, `issues`,
`issue_traces`, `evals`, and `labels` land in later phases.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Index, String, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _uuid() -> str:
    return uuid.uuid4().hex


class Base(DeclarativeBase):
    pass


class Trace(Base):
    __tablename__ = "traces"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    root_span_id: Mapped[str | None] = mapped_column(String, nullable=True)
    app: Mapped[str | None] = mapped_column(String, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cost: Mapped[float | None] = mapped_column(Float, nullable=True)
    latency_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String, default="unset")
    ingested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    spans: Mapped[list[Span]] = relationship(
        back_populates="trace", cascade="all, delete-orphan"
    )


class Span(Base):
    __tablename__ = "spans"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    trace_id: Mapped[str] = mapped_column(String, ForeignKey("traces.id"), index=True)
    parent_span_id: Mapped[str | None] = mapped_column(String, nullable=True)
    name: Mapped[str] = mapped_column(String)
    kind: Mapped[str] = mapped_column(String, default="INTERNAL")
    gen_ai_operation_name: Mapped[str | None] = mapped_column(String, nullable=True)
    gen_ai_provider_name: Mapped[str | None] = mapped_column(String, nullable=True)
    request_model: Mapped[str | None] = mapped_column(String, nullable=True)
    response_model: Mapped[str | None] = mapped_column(String, nullable=True)
    input_tokens: Mapped[int | None] = mapped_column(nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String, default="unset")
    error_type: Mapped[str | None] = mapped_column(String, nullable=True)
    attrs: Mapped[dict[str, object]] = mapped_column(JSON, default=dict)

    trace: Mapped[Trace] = relationship(back_populates="spans")
    messages: Mapped[list[Message]] = relationship(
        back_populates="span", cascade="all, delete-orphan"
    )


class Message(Base):
    __tablename__ = "messages"
    __table_args__ = (Index("ix_messages_span_id_direction", "span_id", "direction"),)

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    span_id: Mapped[str] = mapped_column(String, ForeignKey("spans.id"), index=True)
    direction: Mapped[str] = mapped_column(String)  # "input" | "output" | "system"
    role: Mapped[str | None] = mapped_column(String, nullable=True)
    content: Mapped[dict[str, object]] = mapped_column(JSON)
    position: Mapped[int] = mapped_column(default=0)

    span: Mapped[Span] = relationship(back_populates="messages")
