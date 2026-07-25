"""Render a calibration report as markdown: `regress calibrate --report`."""

from __future__ import annotations

from regress.calibrate.kappa import KappaByRubric, KappaResult
from regress.calibrate.threshold import ThresholdSuggestion

_KAPPA_INTERPRETATION = (
    (0.81, "almost perfect"),
    (0.61, "substantial"),
    (0.41, "moderate"),
    (0.21, "fair"),
    (0.01, "slight"),
    (float("-inf"), "poor / worse than chance"),
)


def _interpret(kappa: float) -> str:
    for lower_bound, label in _KAPPA_INTERPRETATION:
        if kappa >= lower_bound:
            return label
    return "poor / worse than chance"


def _format_kappa_row(name: str, result: KappaResult) -> str:
    if result.kappa is None:
        kappa_cell = "n/a"
    else:
        kappa_cell = f"{result.kappa:.3f} ({_interpret(result.kappa)})"
    return (
        f"| {name} | {result.n} | {result.agreement:.1%} | {kappa_cell} | "
        f"{result.judge_pass_rate:.1%} | {result.human_pass_rate:.1%} |"
    )


def render_report(kappa_result: KappaByRubric, threshold: ThresholdSuggestion) -> str:
    lines = [
        "# Regress Calibration Report",
        "",
        "Judge-vs-human agreement on hand-labeled judge verdicts.",
        "",
        "## Overall",
        "",
        "| Scope | N | Agreement | Cohen's kappa | Judge pass rate | Human pass rate |",
        "|---|---|---|---|---|---|",
        _format_kappa_row("Overall", kappa_result.overall),
    ]

    if kappa_result.by_rubric:
        lines += [
            "",
            "## By rubric",
            "",
            "| Rubric | N | Agreement | Cohen's kappa | Judge pass rate | Human pass rate |",
            "|---|---|---|---|---|---|",
        ]
        for rubric, result in sorted(kappa_result.by_rubric.items()):
            lines.append(_format_kappa_row(rubric, result))

    lines += ["", "## Threshold suggestion", ""]
    if threshold.suggested_threshold is None:
        lines.append("Not enough labeled data to suggest a threshold.")
    else:
        lines.append(
            f"A `score >= {threshold.suggested_threshold:.3f}` cutoff agrees with "
            f"human labels {threshold.suggested_agreement:.1%} of the time, vs. "
            f"{threshold.judge_own_agreement:.1%} for the judge's own pass/fail call "
            f"(n={threshold.n})."
        )
        if threshold.improves_on_judge:
            lines.append(
                "\nThis threshold **improves on** the judge's own verdicts — consider "
                "using it instead of (or alongside) `passed`."
            )
        else:
            lines.append(
                "\nThe judge's own pass/fail call is at least as good as any single "
                "value cutoff — no threshold change suggested."
            )

    if kappa_result.overall.n == 0:
        lines += [
            "",
            "No labeled data yet. Run `regress calibrate --label N` to sample and "
            "hand-label judge verdicts first.",
        ]

    return "\n".join(lines) + "\n"
