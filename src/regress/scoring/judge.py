"""Judge scorer: rubric-based LLM-as-judge over an OpenAI-compatible API.

Provider-agnostic per CLAUDE.md's stack notes — a thin httpx client against
any OpenAI-compatible chat-completions endpoint, so the default is a cheap
hosted model but Ollama (fully local) works by pointing `base_url` at it.
No dependency on the `openai` SDK; this only needs the wire format.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass

import httpx

from regress.models import Span
from regress.scoring import ScoreResult, output_text
from regress.scoring import input_text as span_input_text

DEFAULT_BASE_URL = "https://api.openai.com/v1"
DEFAULT_MODEL = "gpt-4o-mini"

_JUDGE_SYSTEM_PROMPT = (
    "You are an evaluator judging a single AI assistant response against a "
    "rubric. Respond with strict JSON: "
    '{"passed": true|false, "score": <float 0-1>, "reasoning": "<one or two sentences>"}. '
    "No other text."
)


class JudgeError(RuntimeError):
    """Raised when the judge call fails or returns an unparseable verdict."""


@dataclass
class JudgeClient:
    """Minimal OpenAI-compatible chat-completions client for judge calls."""

    api_key: str | None = None
    base_url: str = DEFAULT_BASE_URL
    model: str = DEFAULT_MODEL
    timeout: float = 30.0

    def __post_init__(self) -> None:
        if self.api_key is None:
            self.api_key = os.environ.get("REGRESS_JUDGE_API_KEY") or os.environ.get(
                "OPENAI_API_KEY"
            )

    def complete(self, *, system: str, user: str) -> str:
        headers = {"content-type": "application/json"}
        if self.api_key:
            headers["authorization"] = f"Bearer {self.api_key}"
        try:
            response = httpx.post(
                f"{self.base_url.rstrip('/')}/chat/completions",
                json={
                    "model": self.model,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                    "temperature": 0,
                },
                headers=headers,
                timeout=self.timeout,
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise JudgeError(f"judge request failed: {exc}") from exc

        body = response.json()
        try:
            return str(body["choices"][0]["message"]["content"])
        except (KeyError, IndexError, TypeError) as exc:
            raise JudgeError(f"unexpected judge response shape: {body}") from exc


def _parse_verdict(raw: str) -> tuple[bool, float, str]:
    try:
        payload = json.loads(raw)
        passed = bool(payload["passed"])
        score = float(payload["score"])
        reasoning = str(payload.get("reasoning", ""))
    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        raise JudgeError(f"could not parse judge verdict: {raw!r}") from exc
    return passed, score, reasoning


def judge_rubric_text(
    response_text: str,
    rubric: str,
    *,
    input_text: str | None = None,
    name: str = "judge_rubric",
    client: JudgeClient | None = None,
) -> ScoreResult:
    """Score arbitrary response text against a free-text rubric using an LLM judge.

    The text-level primitive `judge_rubric` and `regress.evalgen.run` both
    build on — the eval runner scores fresh HTTP responses and stored
    strings, not `Span` objects, so this is what it needs directly.

    `input_text`, when given, is what the response was actually replying
    to (e.g. the user's question) — without it, rubrics like "does this
    answer the question?" can't be graded properly, since the judge would
    only ever see the output. Optional and omitted from the prompt when
    not given, so callers scoring a bare string with no known input (e.g.
    eval replay) are unaffected.

    Stores the rubric, model, and raw reasoning on the result for
    auditability, per CLAUDE.md's Scorer spec. Raises `JudgeError` on
    request failure or an unparseable verdict — callers decide whether to
    skip or fail the run.
    """
    judge_client = client or JudgeClient()
    if input_text:
        user_prompt = (
            f"Rubric:\n{rubric}\n\n"
            f"User input:\n{input_text}\n\n"
            f"Response to evaluate:\n{response_text}"
        )
    else:
        user_prompt = f"Rubric:\n{rubric}\n\nResponse to evaluate:\n{response_text}"

    raw_verdict = judge_client.complete(system=_JUDGE_SYSTEM_PROMPT, user=user_prompt)
    passed, score, reasoning = _parse_verdict(raw_verdict)

    return ScoreResult(
        name=name,
        value=score,
        source="judge",
        passed=passed,
        rubric=rubric,
        reasoning=reasoning,
        model=judge_client.model,
    )


def judge_rubric(
    span: Span,
    rubric: str,
    *,
    name: str = "judge_rubric",
    client: JudgeClient | None = None,
) -> ScoreResult:
    """Score a span's output against a free-text rubric using an LLM judge.

    Passes the span's input text through too, so the judge can grade the
    response in context. See `judge_rubric_text` for the underlying
    implementation.
    """
    return judge_rubric_text(
        output_text(span),
        rubric,
        input_text=span_input_text(span),
        name=name,
        client=client,
    )
