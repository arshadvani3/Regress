"""Judge scorer: rubric-based LLM-as-judge over an OpenAI-compatible API.

Provider-agnostic per CLAUDE.md's stack notes — a thin httpx client against
any OpenAI-compatible chat-completions endpoint, so the default is a cheap
hosted model but Ollama (fully local) works by pointing `base_url` at it.
No dependency on the `openai` SDK; this only needs the wire format.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field

import httpx

from regress.models import Span
from regress.scoring import ScoreResult, output_text
from regress.scoring import input_text as span_input_text

DEFAULT_BASE_URL = "https://api.openai.com/v1"
DEFAULT_MODEL = "gpt-4o-mini"
DEFAULT_MAX_CONCURRENCY = 8

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
    """Minimal OpenAI-compatible chat-completions client for judge calls.

    Verdicts are cached per client keyed on `(model, system, user)`: judge
    calls run at `temperature=0`, so identical prompts are deterministic and
    re-judging the same output+rubric (e.g. re-running a scoring pass while
    iterating on config) is a cache hit instead of a paid round-trip. The
    cache lives on the instance, so a fresh client starts cold.

    `acomplete()` is the async twin of `complete()` for concurrent judging
    (see `score_spans`); both share the same cache and response parsing.
    """

    api_key: str | None = None
    base_url: str = DEFAULT_BASE_URL
    model: str = DEFAULT_MODEL
    timeout: float = 30.0
    max_concurrency: int = DEFAULT_MAX_CONCURRENCY
    _cache: dict[str, str] = field(default_factory=dict, repr=False, compare=False)

    def __post_init__(self) -> None:
        if self.api_key is None:
            self.api_key = os.environ.get("REGRESS_JUDGE_API_KEY") or os.environ.get(
                "OPENAI_API_KEY"
            )
        # Only applies when base_url is still the plain, uncustomized
        # default -- an explicit base_url (e.g. from regress.yaml) always
        # wins. Mirrors REGRESS_JUDGE_API_KEY: lets zero-config users (and
        # tests) point the judge at a local/self-hosted endpoint, e.g.
        # Ollama, without writing a config file.
        if self.base_url == DEFAULT_BASE_URL:
            self.base_url = os.environ.get("REGRESS_JUDGE_BASE_URL", DEFAULT_BASE_URL)

    def _cache_key(self, system: str, user: str) -> str:
        digest = hashlib.sha256(f"{self.model}\x00{system}\x00{user}".encode())
        return digest.hexdigest()

    def _headers(self) -> dict[str, str]:
        headers = {"content-type": "application/json"}
        if self.api_key:
            headers["authorization"] = f"Bearer {self.api_key}"
        return headers

    def _payload(self, system: str, user: str) -> dict[str, object]:
        return {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": 0,
        }

    def _content_from(self, body: object) -> str:
        try:
            return str(body["choices"][0]["message"]["content"])  # type: ignore[index]
        except (KeyError, IndexError, TypeError) as exc:
            raise JudgeError(f"unexpected judge response shape: {body}") from exc

    def complete(self, *, system: str, user: str) -> str:
        key = self._cache_key(system, user)
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        try:
            response = httpx.post(
                f"{self.base_url.rstrip('/')}/chat/completions",
                json=self._payload(system, user),
                headers=self._headers(),
                timeout=self.timeout,
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise JudgeError(f"judge request failed: {exc}") from exc

        content = self._content_from(response.json())
        self._cache[key] = content
        return content

    async def acomplete(self, *, system: str, user: str) -> str:
        """Async twin of `complete()`, sharing its verdict cache."""
        key = self._cache_key(system, user)
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    f"{self.base_url.rstrip('/')}/chat/completions",
                    json=self._payload(system, user),
                    headers=self._headers(),
                )
                response.raise_for_status()
        except httpx.HTTPError as exc:
            raise JudgeError(f"judge request failed: {exc}") from exc

        content = self._content_from(response.json())
        self._cache[key] = content
        return content


def _parse_verdict(raw: str) -> tuple[bool, float, str]:
    try:
        payload = json.loads(raw)
        passed = bool(payload["passed"])
        score = float(payload["score"])
        reasoning = str(payload.get("reasoning", ""))
    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        raise JudgeError(f"could not parse judge verdict: {raw!r}") from exc
    return passed, score, reasoning


def _build_user_prompt(response_text: str, rubric: str, input_text: str | None) -> str:
    if input_text:
        return (
            f"Rubric:\n{rubric}\n\n"
            f"User input:\n{input_text}\n\n"
            f"Response to evaluate:\n{response_text}"
        )
    return f"Rubric:\n{rubric}\n\nResponse to evaluate:\n{response_text}"


def _verdict_to_result(raw_verdict: str, *, name: str, rubric: str, model: str) -> ScoreResult:
    passed, score, reasoning = _parse_verdict(raw_verdict)
    return ScoreResult(
        name=name,
        value=score,
        source="judge",
        passed=passed,
        rubric=rubric,
        reasoning=reasoning,
        model=model,
    )


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
    user_prompt = _build_user_prompt(response_text, rubric, input_text)
    raw_verdict = judge_client.complete(system=_JUDGE_SYSTEM_PROMPT, user=user_prompt)
    return _verdict_to_result(
        raw_verdict, name=name, rubric=rubric, model=judge_client.model
    )


async def ajudge_rubric_text(
    response_text: str,
    rubric: str,
    *,
    input_text: str | None = None,
    name: str = "judge_rubric",
    client: JudgeClient | None = None,
) -> ScoreResult:
    """Async twin of `judge_rubric_text`, used by concurrent scoring runs.

    Identical semantics and prompt to the sync version (and shares the same
    verdict cache via the client); it just awaits the HTTP call so many
    judgments can be in flight at once.
    """
    judge_client = client or JudgeClient()
    user_prompt = _build_user_prompt(response_text, rubric, input_text)
    raw_verdict = await judge_client.acomplete(system=_JUDGE_SYSTEM_PROMPT, user=user_prompt)
    return _verdict_to_result(
        raw_verdict, name=name, rubric=rubric, model=judge_client.model
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


async def ajudge_rubric(
    span: Span,
    rubric: str,
    *,
    name: str = "judge_rubric",
    client: JudgeClient | None = None,
) -> ScoreResult:
    """Async twin of `judge_rubric` for concurrent scoring. See `judge_rubric`."""
    return await ajudge_rubric_text(
        output_text(span),
        rubric,
        input_text=span_input_text(span),
        name=name,
        client=client,
    )
