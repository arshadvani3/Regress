"""Two-tier scoring per CLAUDE.md: deterministic checks and an LLM judge.

Deterministic checks are cheap, exact, and run first. The judge is for
semantic properties deterministic checks can't express. Both write to the
same `scores` table via `regress.scoring.ScoreResult`, so the eventual
Clusterer (Phase 4) doesn't need to know which tier produced a verdict.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from regress.models import Span


@dataclass
class ScoreResult:
    """One verdict, ready to persist as a `regress.models.Score` row."""

    name: str
    value: float
    source: str  # "deterministic" | "judge" | "human"
    passed: bool | None = None
    rubric: str | None = None
    reasoning: str | None = None
    model: str | None = None


def message_parts(message_content: dict[str, object]) -> list[dict[str, Any]]:
    """Structured `parts` list from a `Message.content` dict, per GenAI semconv."""
    raw_parts = message_content.get("parts", [])
    if not isinstance(raw_parts, list):
        return []
    return [part for part in raw_parts if isinstance(part, dict)]


def output_text(span: Span) -> str:
    """Concatenate all of a span's output-message text content, in order."""
    parts = []
    for message in sorted(span.messages, key=lambda m: m.position):
        if message.direction != "output":
            continue
        for part in message_parts(message.content):
            content = part.get("content")
            if isinstance(content, str):
                parts.append(content)
    return "\n".join(parts)


def input_text(span: Span) -> str:
    """Concatenate all of a span's input-message text content, in order.

    Lets the judge see what was actually asked, not just what came back --
    without it, rubrics like "does this answer the question?" can't be
    graded properly.
    """
    parts = []
    for message in sorted(span.messages, key=lambda m: m.position):
        if message.direction != "input":
            continue
        for part in message_parts(message.content):
            content = part.get("content")
            if isinstance(content, str):
                parts.append(content)
    return "\n".join(parts)


__all__ = ["ScoreResult", "input_text", "message_parts", "output_text"]
