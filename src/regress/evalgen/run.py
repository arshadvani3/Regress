"""Execute eval cases: replay (score recorded case data) or against a live
endpoint (POST the case's input, score the fresh response).

An eval "passes" when its assertion is *not* triggered — i.e. the failure
the eval was generated from does not reproduce. `--against traces` replays
the case's own recorded `bad_output` (useful to confirm a generated eval
is well-formed: it should fail against the very output it was generated
from); `--against <url>` is the real regression check, scoring a fresh
response from the live app.
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx

from regress.evalgen.load import LoadedCase, LoadedEval
from regress.scoring.deterministic import is_refusal
from regress.scoring.judge import JudgeClient, JudgeError, judge_rubric_text


@dataclass
class EvalOutcome:
    trace_id: str
    passed: bool
    reasoning: str
    output: str


def _score_deterministic(eval_: LoadedEval, case: LoadedCase, output: str) -> EvalOutcome:
    if eval_.assertion.check == "not_refusal":
        refused = is_refusal(output)
        return EvalOutcome(
            trace_id=case.trace_id,
            passed=not refused,
            reasoning="matched a refusal pattern" if refused else "no refusal detected",
            output=output,
        )

    # Fallback assertion: the original bad_output must not reproduce verbatim.
    reproduced = output.strip() == case.bad_output.strip()
    return EvalOutcome(
        trace_id=case.trace_id,
        passed=not reproduced,
        reasoning=(
            "output matches the original failing output exactly"
            if reproduced
            else "output differs from the original failing output"
        ),
        output=output,
    )


def _score_judge(
    eval_: LoadedEval, case: LoadedCase, output: str, judge_client: JudgeClient | None
) -> EvalOutcome:
    rubric = eval_.assertion.rubric or ""
    try:
        result = judge_rubric_text(output, rubric, client=judge_client)
    except JudgeError as exc:
        return EvalOutcome(
            trace_id=case.trace_id,
            passed=False,
            reasoning=f"judge call failed: {exc}",
            output=output,
        )
    return EvalOutcome(
        trace_id=case.trace_id,
        passed=bool(result.passed),
        reasoning=result.reasoning or "",
        output=output,
    )


def score_output(
    eval_: LoadedEval, case: LoadedCase, output: str, *, judge_client: JudgeClient | None = None
) -> EvalOutcome:
    """Score one fresh `output` against `eval_`'s assertion for `case`."""
    if eval_.assertion.type == "judge":
        return _score_judge(eval_, case, output, judge_client)
    return _score_deterministic(eval_, case, output)


def run_eval_case_against_traces(eval_: LoadedEval, case: LoadedCase) -> EvalOutcome:
    """Replay mode: score the case's own recorded bad_output.

    Confirms the eval is well-formed — a freshly generated eval should
    always fail this (the output it was generated from should trip its own
    assertion). If it doesn't, the assertion doesn't actually capture the
    failure it claims to.
    """
    return score_output(eval_, case, case.bad_output)


def run_eval_case_against_endpoint(
    eval_: LoadedEval,
    case: LoadedCase,
    endpoint: str,
    *,
    judge_client: JudgeClient | None = None,
    timeout: float = 30.0,
) -> EvalOutcome:
    """Live mode: POST {"input": case.input} to `endpoint`, score the response.

    Expects a JSON response with an "output" string field. Any request or
    response-shape failure counts as a failed case (a broken endpoint is a
    regression, not a skip).
    """
    try:
        response = httpx.post(endpoint, json={"input": case.input}, timeout=timeout)
        response.raise_for_status()
        output = str(response.json()["output"])
    except (httpx.HTTPError, KeyError, TypeError, ValueError) as exc:
        return EvalOutcome(
            trace_id=case.trace_id,
            passed=False,
            reasoning=f"endpoint request failed: {exc}",
            output="",
        )
    return score_output(eval_, case, output, judge_client=judge_client)


# Kept for the generated pytest module's plain `run_eval_case` import — a
# bare `pytest evals/` run has no --against flag, so it defaults to replay.
def run_eval_case(eval_: LoadedEval, case: LoadedCase) -> EvalOutcome:
    return run_eval_case_against_traces(eval_, case)
