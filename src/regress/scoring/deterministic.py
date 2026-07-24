"""Deterministic scorer: JSON-schema, regex/exact-match, tool-call args,
latency/cost thresholds, refusal detection.

Every check takes a `regress.models.Span` (with `.messages` available) and
returns a `ScoreResult`. Cheap and exact by design — these run before any
judge call, per CLAUDE.md's two-tier Scorer.
"""

from __future__ import annotations

import json
import re
from typing import Any

import jsonschema

from regress.models import Span
from regress.scoring import ScoreResult, message_parts, output_text

_REFUSAL_PATTERNS = [
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"\bi can'?t (help|assist) with that\b",
        r"\bi'?m (not able|unable) to\b",
        r"\bi cannot (help|assist|provide|comply)\b",
        r"\bas an ai\b.{0,40}\bi (can'?t|cannot|won'?t)\b",
        r"\bi'?m sorry,? but i (can'?t|cannot|won'?t)\b",
    )
]


def _tool_calls(span: Span) -> list[dict[str, Any]]:
    """Tool-call parts across output messages, per the GenAI semconv shape."""
    calls = []
    for message in span.messages:
        if message.direction != "output":
            continue
        for part in message_parts(message.content):
            if part.get("type") == "tool_call":
                calls.append(part)
    return calls


def json_schema_valid(
    span: Span, schema: dict[str, Any], *, name: str = "json_schema_valid"
) -> ScoreResult:
    """Check the span's output text parses as JSON and matches `schema`."""
    text = output_text(span)
    try:
        payload = json.loads(text)
        jsonschema.validate(payload, schema)
    except (json.JSONDecodeError, jsonschema.ValidationError) as exc:
        return ScoreResult(
            name=name, value=0.0, source="deterministic", passed=False, reasoning=str(exc)
        )
    return ScoreResult(name=name, value=1.0, source="deterministic", passed=True)


def regex_match(span: Span, pattern: str, *, name: str = "regex_match") -> ScoreResult:
    """Check the span's output text matches `pattern` anywhere (re.search)."""
    matched = re.search(pattern, output_text(span)) is not None
    return ScoreResult(
        name=name, value=1.0 if matched else 0.0, source="deterministic", passed=matched
    )


def exact_match(span: Span, expected: str, *, name: str = "exact_match") -> ScoreResult:
    """Check the span's output text equals `expected` exactly."""
    matched = output_text(span) == expected
    return ScoreResult(
        name=name, value=1.0 if matched else 0.0, source="deterministic", passed=matched
    )


def tool_call_args_valid(
    span: Span, tool_name: str, schema: dict[str, Any], *, name: str = "tool_call_args_valid"
) -> ScoreResult:
    """Check every call to `tool_name` in this span has args matching `schema`.

    Passes vacuously (value=1.0) if the tool was never called in this span —
    absence isn't a failure of argument validity.
    """
    calls = [c for c in _tool_calls(span) if c.get("name") == tool_name]
    for call in calls:
        try:
            jsonschema.validate(call.get("arguments", {}), schema)
        except jsonschema.ValidationError as exc:
            return ScoreResult(
                name=name, value=0.0, source="deterministic", passed=False, reasoning=str(exc)
            )
    return ScoreResult(name=name, value=1.0, source="deterministic", passed=True)


def latency_under(span: Span, max_ms: float, *, name: str = "latency_under") -> ScoreResult:
    """Check the span's latency is under `max_ms`. Unknown latency fails closed."""
    if span.started_at is None or span.ended_at is None:
        return ScoreResult(
            name=name,
            value=0.0,
            source="deterministic",
            passed=False,
            reasoning="span has no started_at/ended_at",
        )
    latency_ms = (span.ended_at - span.started_at).total_seconds() * 1000
    passed = latency_ms <= max_ms
    return ScoreResult(name=name, value=latency_ms, source="deterministic", passed=passed)


def cost_under(
    span: Span,
    max_cost: float,
    *,
    cost_per_1k_tokens: float,
    name: str = "cost_under",
) -> ScoreResult:
    """Check the span's estimated cost (from token usage) is under `max_cost`."""
    input_tokens = span.input_tokens or 0
    output_tokens = span.output_tokens or 0
    estimated_cost = ((input_tokens + output_tokens) / 1000) * cost_per_1k_tokens
    passed = estimated_cost <= max_cost
    return ScoreResult(name=name, value=estimated_cost, source="deterministic", passed=passed)


def not_refusal(span: Span, *, name: str = "not_refusal") -> ScoreResult:
    """Check the span's output text doesn't match common LLM refusal phrasing."""
    text = output_text(span)
    refused = any(pattern.search(text) for pattern in _REFUSAL_PATTERNS)
    return ScoreResult(
        name=name,
        value=0.0 if refused else 1.0,
        source="deterministic",
        passed=not refused,
        reasoning="matched a refusal pattern" if refused else None,
    )
