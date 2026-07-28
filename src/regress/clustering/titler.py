"""LLM-written title + description for a cluster of failing traces.

Reuses `regress.scoring.judge.JudgeClient` — same provider-agnostic
OpenAI-compatible thin client the judge scorer uses, so clustering doesn't
need a second HTTP client or a second way to configure model/base_url/key.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from regress.scoring.judge import JudgeClient, JudgeError

_TITLER_SYSTEM_PROMPT = (
    "You are labeling a cluster of similar AI assistant failures for a bug "
    "tracker. Given several example failures, respond with strict JSON: "
    '{"title": "<five to eight words, imperative or noun phrase>", '
    '"description": "<one to three sentences describing the common failure '
    'pattern>"}. No other text.'
)

_MAX_EXAMPLES = 8


class TitlerError(RuntimeError):
    """Raised when the titling call fails or returns an unparseable response."""


@dataclass
class IssueTitle:
    title: str
    description: str


def title_cluster(
    example_texts: list[str], *, client: JudgeClient | None = None
) -> IssueTitle:
    """Ask the judge model to title and describe a cluster from example failures."""
    titler_client = client or JudgeClient()
    examples = example_texts[:_MAX_EXAMPLES]
    user_prompt = "Example failures:\n\n" + "\n---\n".join(examples)

    try:
        raw = titler_client.complete(system=_TITLER_SYSTEM_PROMPT, user=user_prompt)
    except JudgeError as exc:
        raise TitlerError(f"titling request failed: {exc}") from exc

    try:
        payload = json.loads(raw)
        # Models sometimes "helpfully" return a JSON array of title/description
        # objects (one per example failure) instead of the single object asked
        # for. Coalesce to the first object rather than failing the whole
        # cluster — a title is a title.
        if isinstance(payload, list):
            if not payload:
                raise TitlerError(f"titler returned an empty list: {raw!r}")
            payload = payload[0]
        title = str(payload["title"])
        description = str(payload["description"])
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        raise TitlerError(f"could not parse titler response: {raw!r}") from exc

    return IssueTitle(title=title, description=description)
