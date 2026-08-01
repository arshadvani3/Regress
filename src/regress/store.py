"""Persist normalized OTLP spans, merging into existing traces/spans on conflict."""

from __future__ import annotations

import os
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from regress.models import Message, Span, Trace
from regress.sanitize import sanitize_message_content

_TRUTHY = {"1", "true", "yes", "on"}


def _sanitize_ingest_enabled() -> bool:
    """Whether to redact PII from message text before it's persisted.

    Off by default so the zero-config path stores traces verbatim (redaction
    is lossy, and many users want the raw text locally). Operators running a
    shared collector opt in with `REGRESS_SANITIZE_INGEST=1`, and then raw
    emails/keys/phone numbers never touch the database — a stronger guarantee
    than sanitizing only at eval-generation time.
    """
    return os.environ.get("REGRESS_SANITIZE_INGEST", "").strip().lower() in _TRUTHY


def _as_aware(value: datetime | None) -> datetime | None:
    """SQLite drops tzinfo on round-trip; treat naive datetimes as UTC."""
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


def upsert_trace(session: Session, trace: Trace) -> Trace:
    existing = session.get(Trace, trace.id)
    if existing is None:
        session.add(trace)
        session.flush()
        return trace

    existing_started_at = _as_aware(existing.started_at)
    existing_ended_at = _as_aware(existing.ended_at)

    if trace.root_span_id is not None:
        existing.root_span_id = trace.root_span_id
    if trace.app is not None:
        existing.app = trace.app
    starts_earlier = existing_started_at is None or (
        trace.started_at is not None and trace.started_at < existing_started_at
    )
    if trace.started_at is not None and starts_earlier:
        existing.started_at = trace.started_at
        existing_started_at = trace.started_at

    ends_later = existing_ended_at is None or (
        trace.ended_at is not None and trace.ended_at > existing_ended_at
    )
    if trace.ended_at is not None and ends_later:
        existing.ended_at = trace.ended_at
        existing_ended_at = trace.ended_at
    if existing_started_at is not None and existing_ended_at is not None:
        existing.latency_ms = (existing_ended_at - existing_started_at).total_seconds() * 1000
    if trace.status == "error":
        existing.status = "error"
    session.flush()
    return existing


def upsert_span(session: Session, span: Span, messages: list[Message]) -> Span:
    existing = session.get(Span, span.id)
    if existing is not None:
        session.delete(existing)
        session.flush()
    session.add(span)
    for message in messages:
        session.add(message)
    session.flush()
    return span


def store_parsed_spans(session: Session, parsed: list[tuple[Trace, Span, list[Message]]]) -> int:
    sanitize = _sanitize_ingest_enabled()
    count = 0
    for trace, span, messages in parsed:
        if sanitize:
            for message in messages:
                if isinstance(message.content, dict):
                    message.content = sanitize_message_content(message.content)
        upsert_trace(session, trace)
        upsert_span(session, span, messages)
        count += 1
    return count
