"""Suggest a better `Score.value` cutoff for judge pass/fail, from human labels.

The judge decides `passed` and `value` independently in one LLM call —
there's no existing numeric threshold in the system to "tune". What this
does instead: sweep candidate cutoffs on `value`, find the one that best
reproduces the human's `human_value`, and report it alongside how the
judge's own `passed` field currently compares. If the suggested cutoff
beats the judge's own calls, that's a concrete, actionable signal
("score >= 0.72 agrees with humans better than the judge's own verdict").
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ValuedPair:
    value: float
    judge_passed: bool
    human_value: bool


@dataclass
class ThresholdSuggestion:
    suggested_threshold: float | None
    suggested_agreement: float
    judge_own_agreement: float
    n: int
    improves_on_judge: bool


def _agreement_at_threshold(pairs: list[ValuedPair], threshold: float) -> float:
    correct = sum(1 for p in pairs if (p.value >= threshold) == p.human_value)
    return correct / len(pairs)


def suggest_threshold(pairs: list[ValuedPair]) -> ThresholdSuggestion:
    """Find the `value` cutoff maximizing agreement with `human_value`.

    Candidate thresholds are the midpoints between consecutive distinct
    observed values (plus the boundaries), which is sufficient to find the
    optimal cutoff for any 1-D threshold classifier — the decision only
    ever changes at a point strictly between two observed values.
    """
    if not pairs:
        return ThresholdSuggestion(
            suggested_threshold=None,
            suggested_agreement=0.0,
            judge_own_agreement=0.0,
            n=0,
            improves_on_judge=False,
        )

    judge_own_agreement = sum(1 for p in pairs if p.judge_passed == p.human_value) / len(pairs)

    values = sorted({p.value for p in pairs})
    # Deliberately mismatched lengths: values[1:] is always one shorter,
    # forming the sliding pairwise window (v[0],v[1]), (v[1],v[2]), ...
    pairwise = zip(values, values[1:], strict=False)
    candidates = [values[0] - 1e-9] + [(a + b) / 2 for a, b in pairwise]

    best_threshold = candidates[0]
    best_agreement = _agreement_at_threshold(pairs, best_threshold)
    for candidate in candidates[1:]:
        agreement = _agreement_at_threshold(pairs, candidate)
        if agreement > best_agreement:
            best_agreement = agreement
            best_threshold = candidate

    return ThresholdSuggestion(
        suggested_threshold=best_threshold,
        suggested_agreement=best_agreement,
        judge_own_agreement=judge_own_agreement,
        n=len(pairs),
        improves_on_judge=best_agreement > judge_own_agreement,
    )
