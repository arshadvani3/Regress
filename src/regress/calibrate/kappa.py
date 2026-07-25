"""Cohen's kappa between judge and human pass/fail verdicts.

Plain agreement rate overstates how good a judge is whenever most cases
are easy (nearly all pass, say) — two raters can agree 95% of the time by
each just saying "pass" almost always, with zero actual signal. Kappa
corrects for that by subtracting the agreement expected from the raters'
marginal distributions by chance alone.

Implemented by hand (no scikit-learn/statsmodels dependency — calibration
should work without the `cluster` extra) and cross-checked against
sklearn.metrics.cohen_kappa_score during development.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class LabeledPair:
    """One (judge, human) verdict pair for the same score, plus the rubric
    it came from — everything kappa-by-rubric needs.
    """

    judge_passed: bool
    human_value: bool
    rubric: str


@dataclass
class KappaResult:
    kappa: float | None  # None when there's not enough data to compute it
    agreement: float
    n: int
    judge_pass_rate: float
    human_pass_rate: float


def cohens_kappa(pairs: list[LabeledPair]) -> KappaResult:
    """Cohen's kappa over `pairs`. Returns kappa=None (not 0 or NaN) when
    fewer than 2 pairs exist, or when both raters are perfectly unanimous
    (expected agreement is 1.0, making kappa mathematically undefined
    rather than merely 0) — a caller shouldn't silently plot that as "no
    agreement".
    """
    n = len(pairs)
    if n == 0:
        return KappaResult(kappa=None, agreement=0.0, n=0, judge_pass_rate=0.0, human_pass_rate=0.0)

    observed_agreement = sum(1 for p in pairs if p.judge_passed == p.human_value) / n
    judge_pass_rate = sum(1 for p in pairs if p.judge_passed) / n
    human_pass_rate = sum(1 for p in pairs if p.human_value) / n

    if n < 2:
        return KappaResult(
            kappa=None,
            agreement=observed_agreement,
            n=n,
            judge_pass_rate=judge_pass_rate,
            human_pass_rate=human_pass_rate,
        )

    expected_agreement = judge_pass_rate * human_pass_rate + (1 - judge_pass_rate) * (
        1 - human_pass_rate
    )

    if expected_agreement >= 1.0:
        kappa = None
    else:
        kappa = (observed_agreement - expected_agreement) / (1 - expected_agreement)

    return KappaResult(
        kappa=kappa,
        agreement=observed_agreement,
        n=n,
        judge_pass_rate=judge_pass_rate,
        human_pass_rate=human_pass_rate,
    )


@dataclass
class KappaByRubric:
    overall: KappaResult
    by_rubric: dict[str, KappaResult] = field(default_factory=dict)


def kappa_by_rubric(pairs: list[LabeledPair]) -> KappaByRubric:
    """Overall kappa plus a breakdown per rubric, so a user can see which
    rubrics the judge is actually well-calibrated on vs. which are noise.
    """
    grouped: dict[str, list[LabeledPair]] = {}
    for pair in pairs:
        grouped.setdefault(pair.rubric, []).append(pair)

    return KappaByRubric(
        overall=cohens_kappa(pairs),
        by_rubric={rubric: cohens_kappa(group) for rubric, group in grouped.items()},
    )
