"""Clusterer: embed scored-bad traces and group them into Issues.

Per CLAUDE.md: embed (failure reason + last user msg + output) for
scored-bad traces, HDBSCAN into clusters, LLM writes a title + description
per cluster. `sentence-transformers` (and `scikit-learn`'s HDBSCAN) are the
`cluster` extra, not core dependencies — see `regress.clustering.embed` for
why, and how the extra's absence is reported.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from regress.models import Message, Span, Trace
from regress.scoring import message_parts

_EPOCH = datetime.min.replace(tzinfo=UTC)


def _as_aware(value: datetime | None) -> datetime:
    """SQLite drops tzinfo on round-trip; treat naive datetimes as UTC."""
    if value is None:
        return _EPOCH
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _spans_oldest_first(trace: Trace) -> list[Span]:
    """Trace's spans ordered by start time; spans with no timestamp sort first."""
    return sorted(trace.spans, key=lambda s: _as_aware(s.started_at))


def _last_user_message(trace: Trace) -> str:
    """The most recent input/user message across the trace's spans, by span start time."""
    for span in reversed(_spans_oldest_first(trace)):
        input_messages = sorted(
            (m for m in span.messages if m.direction == "input" and m.role == "user"),
            key=lambda m: m.position,
        )
        if input_messages:
            return _message_text(input_messages[-1])
    return ""


def _final_output(trace: Trace) -> str:
    """The last output message across the trace's spans, by span start time."""
    for span in reversed(_spans_oldest_first(trace)):
        output_messages = sorted(
            (m for m in span.messages if m.direction == "output"), key=lambda m: m.position
        )
        if output_messages:
            return _message_text(output_messages[-1])
    return ""


def _message_text(message: Message) -> str:
    texts = [
        part["content"]
        for part in message_parts(message.content)
        if isinstance(part.get("content"), str)
    ]
    return " ".join(texts)


def _failure_reasons(trace: Trace) -> str:
    """Reasoning from every failed score on this trace or its spans."""
    reasons = [s.reasoning for s in trace.scores if s.passed is False and s.reasoning]
    for span in trace.spans:
        reasons.extend(s.reasoning for s in span.scores if s.passed is False and s.reasoning)
    return " ".join(reasons)


@dataclass
class ClusterableTrace:
    """The text CLAUDE.md specifies embedding, plus enough to build an Issue."""

    trace_id: str
    text: str


def failure_text(trace: Trace) -> ClusterableTrace:
    """Build the (failure reason + last user msg + output) text for one trace."""
    parts = [_failure_reasons(trace), _last_user_message(trace), _final_output(trace)]
    text = "\n".join(p for p in parts if p)
    return ClusterableTrace(trace_id=trace.id, text=text)


def scored_bad_traces(traces: list[Trace]) -> list[Trace]:
    """Traces with at least one failed score, on the trace or any of its spans."""
    result = []
    for trace in traces:
        has_failure = any(s.passed is False for s in trace.scores) or any(
            s.passed is False for span in trace.spans for s in span.scores
        )
        if has_failure:
            result.append(trace)
    return result


__all__ = ["ClusterableTrace", "failure_text", "scored_bad_traces"]
