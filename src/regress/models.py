"""Data model per CLAUDE.md's minimum schema.

Phase 1 implements `traces`, `spans`, and `messages`. Phase 3 adds `scores`.
Phase 4 adds `issues`/`issue_traces`. Phase 5 adds `evals`. Phase 6 adds
`labels`, completing the minimum schema.
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
    scores: Mapped[list[Score]] = relationship(
        back_populates="trace", cascade="all, delete-orphan"
    )
    issue_links: Mapped[list[IssueTrace]] = relationship(
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
    scores: Mapped[list[Score]] = relationship(
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


class Score(Base):
    """A deterministic-, judge-, or human-sourced verdict on a span or trace.

    Scored at the span level when a check is about one call (e.g. a single
    tool-call's arguments); at the trace level when it's about the whole
    interaction (e.g. a human feedback rating). Exactly one of
    `span_id`/`trace_id` is set.
    """

    __tablename__ = "scores"
    __table_args__ = (
        Index("ix_scores_span_id_name", "span_id", "name"),
        Index("ix_scores_trace_id_name", "trace_id", "name"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    span_id: Mapped[str | None] = mapped_column(String, ForeignKey("spans.id"), nullable=True)
    trace_id: Mapped[str | None] = mapped_column(String, ForeignKey("traces.id"), nullable=True)
    source: Mapped[str] = mapped_column(String)  # "deterministic" | "judge" | "human"
    name: Mapped[str] = mapped_column(String)
    value: Mapped[float] = mapped_column(Float)
    passed: Mapped[bool | None] = mapped_column(nullable=True)
    rubric: Mapped[str | None] = mapped_column(String, nullable=True)
    reasoning: Mapped[str | None] = mapped_column(String, nullable=True)
    model: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    span: Mapped[Span | None] = relationship(back_populates="scores")
    trace: Mapped[Trace | None] = relationship(back_populates="scores")
    labels: Mapped[list[Label]] = relationship(back_populates="score", cascade="all, delete-orphan")


class Issue(Base):
    """A cluster of scored-bad traces, with an LLM-written title/description.

    Lifecycle: `active` (open, unresolved) -> `resolved` (fixed, no longer
    seeing new failures) -> `regressed` (a new failing trace landed back in
    a resolved cluster — the fix didn't hold). `regressed` is the headline
    state transition per CLAUDE.md; the Clusterer is what detects it.
    """

    __tablename__ = "issues"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    title: Mapped[str] = mapped_column(String)
    description: Mapped[str] = mapped_column(String)
    state: Mapped[str] = mapped_column(String, default="active")  # active|resolved|regressed
    centroid_vector: Mapped[list[float]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    trace_links: Mapped[list[IssueTrace]] = relationship(
        back_populates="issue", cascade="all, delete-orphan"
    )
    evals: Mapped[list[Eval]] = relationship(back_populates="issue", cascade="all, delete-orphan")


class IssueTrace(Base):
    """Membership of one trace in one issue's cluster."""

    __tablename__ = "issue_traces"
    __table_args__ = (Index("ix_issue_traces_issue_id_trace_id", "issue_id", "trace_id"),)

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    issue_id: Mapped[str] = mapped_column(String, ForeignKey("issues.id"), index=True)
    trace_id: Mapped[str] = mapped_column(String, ForeignKey("traces.id"), index=True)
    added_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    issue: Mapped[Issue] = relationship(back_populates="trace_links")
    trace: Mapped[Trace] = relationship(back_populates="issue_links")


class Eval(Base):
    """A generated regression test for one issue.

    `path` points at the YAML file on disk (human-editable, the source of
    truth for `regress run`); this row just tracks that it was generated,
    from which issue, and what assertion tier it uses. Deleting the DB row
    never deletes the file — `evals/` is meant to be committed to the
    user's repo, per CLAUDE.md's "everything is also a file" principle.
    """

    __tablename__ = "evals"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    issue_id: Mapped[str] = mapped_column(String, ForeignKey("issues.id"), index=True)
    name: Mapped[str] = mapped_column(String)
    path: Mapped[str] = mapped_column(String)
    assertion_type: Mapped[str] = mapped_column(String)  # "deterministic" | "judge"
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    issue: Mapped[Issue] = relationship(back_populates="evals")


class Label(Base):
    """A human's independent verdict on a Score, for calibrating the judge.

    Only meaningful against judge-sourced scores — deterministic checks
    have no ambiguity to calibrate. `human_value` is the human's
    pass/fail call on the same case the judge scored; Cohen's kappa
    between this and `Score.passed` is the Calibrator's headline number.
    Multiple labelers can label the same score (each gets their own row),
    which is what makes disagreement-among-humans visible too.
    """

    __tablename__ = "labels"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    score_id: Mapped[str] = mapped_column(String, ForeignKey("scores.id"), index=True)
    human_value: Mapped[bool] = mapped_column()
    labeler: Mapped[str] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    score: Mapped[Score] = relationship(back_populates="labels")


class TraceEmbedding(Base):
    """A persisted embedding of one trace's failure text, so `regress cluster`
    embeds only *new* failures on a repeat run instead of recomputing every
    vector from scratch (embedding is the slow, model-loading part of
    clustering).

    `text_hash` is a fingerprint of the exact text that was embedded. A trace's
    failure text can change (e.g. after re-scoring produces new judge
    reasoning), so a stored vector is only reused when the current text hashes
    to the same value — otherwise it's re-embedded and this row is updated. The
    vector is stored as JSON, which keeps this in the zero-config SQLite path
    with no database server; Postgres + pgvector remain the documented scale
    option (storage is already abstracted behind `REGRESS_DB_URL`).
    """

    __tablename__ = "trace_embeddings"

    trace_id: Mapped[str] = mapped_column(
        String, ForeignKey("traces.id"), primary_key=True
    )
    text_hash: Mapped[str] = mapped_column(String)
    vector: Mapped[list[float]] = mapped_column(JSON)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
