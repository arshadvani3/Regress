"""Two-proportion significance test for the CI gate.

CLAUDE.md is explicit: "a two-proportion significance test (not raw
pass-rate diff — flakiness awareness matters)". A baseline pass rate of
9/10 vs. a current 8/10 is a raw drop but not statistically distinguishable
from noise on that little data; the gate should only fail the build when
the drop is unlikely to be chance. Implemented by hand with just `math`
(no scipy/statsmodels dependency) so `--gate` works without the `cluster`
extra installed — it's a core CLI feature, not clustering-adjacent.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

DEFAULT_ALPHA = 0.05


@dataclass
class SignificanceResult:
    baseline_pass_rate: float
    current_pass_rate: float
    z_score: float
    p_value: float
    is_regression: bool
    alpha: float


def _standard_normal_cdf(z: float) -> float:
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


def two_proportion_z_test(
    baseline_passed: int,
    baseline_total: int,
    current_passed: int,
    current_total: int,
    *,
    alpha: float = DEFAULT_ALPHA,
) -> SignificanceResult:
    """One-sided test: is `current`'s pass rate significantly *lower* than
    `baseline`'s? A rise in pass rate, or a drop too small to distinguish
    from sampling noise at `alpha`, is not a regression.

    Zero-total inputs (nothing ran) can't support a significance claim —
    treated as no regression rather than raising, since an empty gate run
    is a configuration issue for the caller to notice, not a test failure.
    """
    if baseline_total == 0 or current_total == 0:
        return SignificanceResult(
            baseline_pass_rate=0.0,
            current_pass_rate=0.0,
            z_score=0.0,
            p_value=1.0,
            is_regression=False,
            alpha=alpha,
        )

    p_baseline = baseline_passed / baseline_total
    p_current = current_passed / current_total

    if p_current >= p_baseline:
        return SignificanceResult(
            baseline_pass_rate=p_baseline,
            current_pass_rate=p_current,
            z_score=0.0,
            p_value=1.0,
            is_regression=False,
            alpha=alpha,
        )

    # Pooled variance is only ever 0 when both groups have identical pass
    # counts of 0 or of their totals, which forces p_current == p_baseline —
    # already handled by the early return above, so standard_error is
    # guaranteed nonzero here.
    pooled = (baseline_passed + current_passed) / (baseline_total + current_total)
    standard_error = math.sqrt(pooled * (1 - pooled) * (1 / baseline_total + 1 / current_total))
    z_score = (p_baseline - p_current) / standard_error
    p_value = 1.0 - _standard_normal_cdf(z_score)

    return SignificanceResult(
        baseline_pass_rate=p_baseline,
        current_pass_rate=p_current,
        z_score=z_score,
        p_value=p_value,
        is_regression=p_value < alpha,
        alpha=alpha,
    )
