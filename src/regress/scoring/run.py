"""Dispatch configured checks against spans and persist the resulting scores."""

from __future__ import annotations

import asyncio
from collections.abc import Callable

from sqlalchemy.orm import Session

from regress.config import CheckConfig, RegressConfig
from regress.models import Score, Span
from regress.scoring import ScoreResult
from regress.scoring.deterministic import (
    cost_under,
    exact_match,
    json_schema_valid,
    latency_under,
    not_refusal,
    regex_match,
    tool_call_args_valid,
)
from regress.scoring.judge import JudgeClient, JudgeError, ajudge_rubric, judge_rubric

_DETERMINISTIC_DISPATCH = {
    "json_schema_valid": lambda span, params: json_schema_valid(span, **params),
    "regex_match": lambda span, params: regex_match(span, **params),
    "exact_match": lambda span, params: exact_match(span, **params),
    "tool_call_args_valid": lambda span, params: tool_call_args_valid(span, **params),
    "latency_under": lambda span, params: latency_under(span, **params),
    "cost_under": lambda span, params: cost_under(span, **params),
    "not_refusal": lambda span, params: not_refusal(span, **params),
}


def run_check(
    span: Span, check: CheckConfig, *, judge_client: JudgeClient | None = None
) -> ScoreResult:
    """Run one configured check against one span."""
    if check.tier == "judge":
        rubric = str(check.params.get("rubric", ""))
        return judge_rubric(span, rubric, name=check.name, client=judge_client)

    dispatch = _DETERMINISTIC_DISPATCH.get(check.check)
    if dispatch is None:
        raise ValueError(f"unknown check: {check.check!r}")
    return dispatch(span, {**check.params, "name": check.name})


def score_to_row(result: ScoreResult, *, span_id: str) -> Score:
    return Score(
        span_id=span_id,
        source=result.source,
        name=result.name,
        value=result.value,
        passed=result.passed,
        rubric=result.rubric,
        reasoning=result.reasoning,
        model=result.model,
    )


async def _run_judge_checks(
    pairs: list[tuple[Span, CheckConfig]],
    client: JudgeClient,
    max_concurrency: int,
) -> list[ScoreResult | BaseException]:
    """Judge every (span, check) pair concurrently, bounded by a semaphore.

    Returns one entry per input pair in the same order — either the
    `ScoreResult` or the exception it raised — so the caller can stitch
    results back into the original span-major sequence and apply the same
    per-check error isolation the sync path uses.
    """
    semaphore = asyncio.Semaphore(max_concurrency)

    async def one(span: Span, check: CheckConfig) -> ScoreResult:
        rubric = str(check.params.get("rubric", ""))
        async with semaphore:
            return await ajudge_rubric(span, rubric, name=check.name, client=client)

    tasks = [one(span, check) for span, check in pairs]
    return await asyncio.gather(*tasks, return_exceptions=True)


def score_spans(
    session: Session,
    spans: list[Span],
    config: RegressConfig,
    *,
    judge_client: JudgeClient | None = None,
    on_error: Callable[[Span, CheckConfig, Exception], None] | None = None,
) -> list[Score]:
    """Run every configured check against every span and persist the results.

    Deterministic checks run inline; judge checks run concurrently (bounded by
    the client's `max_concurrency`), since each is an independent network
    round-trip — a large run is no longer a sequential wait. Results are
    persisted in a stable span-major, check-order sequence regardless of which
    judgment finished first.

    A judge call failing (network error, unparseable verdict) doesn't abort
    the run — it's reported via `on_error` and skipped, so one bad judge
    response can't blank out an otherwise-successful scoring pass.
    """
    client = judge_client
    if client is None and any(c.tier == "judge" for c in config.checks):
        client = JudgeClient(model=config.judge_model, base_url=config.judge_base_url)

    # First pass: run deterministic checks inline and record, in order, where
    # each judge check belongs so its concurrent result slots back in.
    ordered: list[ScoreResult | None] = []
    judge_pairs: list[tuple[Span, CheckConfig]] = []
    judge_slots: list[int] = []
    for span in spans:
        for check in config.checks:
            if check.tier == "judge":
                judge_slots.append(len(ordered))
                judge_pairs.append((span, check))
                ordered.append(None)  # filled in after the concurrent batch
            else:
                ordered.append(run_check(span, check, judge_client=client))

    if judge_pairs:
        assert client is not None  # a judge check implies a client was built
        judge_results = asyncio.run(
            _run_judge_checks(judge_pairs, client, client.max_concurrency)
        )
        for slot, (span, check), result in zip(
            judge_slots, judge_pairs, judge_results, strict=True
        ):
            if isinstance(result, JudgeError):
                if on_error is not None:
                    on_error(span, check, result)
                ordered[slot] = None  # skipped, no row
            elif isinstance(result, BaseException):
                raise result  # unexpected error type -- don't silently swallow
            else:
                ordered[slot] = result

    # Second pass: persist in the original span-major order.
    rows = []
    for slot, persisted in enumerate(ordered):
        if persisted is None:
            continue
        span = spans[slot // len(config.checks)]
        row = score_to_row(persisted, span_id=span.id)
        session.add(row)
        rows.append(row)
    session.flush()
    return rows
