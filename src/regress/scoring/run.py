"""Dispatch configured checks against spans and persist the resulting scores."""

from __future__ import annotations

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
from regress.scoring.judge import JudgeClient, JudgeError, judge_rubric

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


def score_spans(
    session: Session,
    spans: list[Span],
    config: RegressConfig,
    *,
    judge_client: JudgeClient | None = None,
    on_error: Callable[[Span, CheckConfig, Exception], None] | None = None,
) -> list[Score]:
    """Run every configured check against every span and persist the results.

    A judge call failing (network error, unparseable verdict) doesn't abort
    the run — it's reported via `on_error` and skipped, so one bad judge
    response can't blank out an otherwise-successful scoring pass.
    """
    client = judge_client
    if client is None and any(c.tier == "judge" for c in config.checks):
        client = JudgeClient(model=config.judge_model, base_url=config.judge_base_url)

    rows = []
    for span in spans:
        for check in config.checks:
            try:
                result = run_check(span, check, judge_client=client)
            except JudgeError as exc:
                if on_error is not None:
                    on_error(span, check, exc)
                continue
            row = score_to_row(result, span_id=span.id)
            session.add(row)
            rows.append(row)
    session.flush()
    return rows
