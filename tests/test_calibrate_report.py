from regress.calibrate.kappa import KappaByRubric, KappaResult, LabeledPair, kappa_by_rubric
from regress.calibrate.report import render_report
from regress.calibrate.threshold import ThresholdSuggestion, ValuedPair, suggest_threshold


def test_render_report_includes_overall_section() -> None:
    kappa_result = kappa_by_rubric(
        [LabeledPair(judge_passed=True, human_value=True, rubric="r")]
    )
    threshold = suggest_threshold([ValuedPair(value=0.5, judge_passed=True, human_value=True)])

    report = render_report(kappa_result, threshold)

    assert "# Regress Calibration Report" in report
    assert "## Overall" in report


def test_render_report_includes_by_rubric_section_when_multiple_rubrics() -> None:
    pairs = [
        LabeledPair(judge_passed=True, human_value=True, rubric="Rubric A"),
        LabeledPair(judge_passed=False, human_value=False, rubric="Rubric B"),
    ]
    kappa_result = kappa_by_rubric(pairs)
    threshold = ThresholdSuggestion(
        suggested_threshold=0.5, suggested_agreement=1.0, judge_own_agreement=1.0, n=2,
        improves_on_judge=False,
    )

    report = render_report(kappa_result, threshold)

    assert "## By rubric" in report
    assert "Rubric A" in report
    assert "Rubric B" in report


def test_render_report_omits_by_rubric_section_when_no_data() -> None:
    kappa_result = kappa_by_rubric([])
    threshold = suggest_threshold([])

    report = render_report(kappa_result, threshold)

    assert "## By rubric" not in report


def test_render_report_shows_no_data_message_when_empty() -> None:
    kappa_result = kappa_by_rubric([])
    threshold = suggest_threshold([])

    report = render_report(kappa_result, threshold)

    assert "No labeled data yet" in report
    assert "Not enough labeled data to suggest a threshold" in report


def test_render_report_shows_improvement_message_when_threshold_wins() -> None:
    kappa_result = kappa_by_rubric([])
    threshold = ThresholdSuggestion(
        suggested_threshold=0.6, suggested_agreement=0.9, judge_own_agreement=0.5, n=10,
        improves_on_judge=True,
    )

    report = render_report(kappa_result, threshold)

    assert "improves on" in report


def test_render_report_shows_no_change_message_when_judge_already_optimal() -> None:
    kappa_result = kappa_by_rubric([])
    threshold = ThresholdSuggestion(
        suggested_threshold=0.6, suggested_agreement=0.9, judge_own_agreement=0.9, n=10,
        improves_on_judge=False,
    )

    report = render_report(kappa_result, threshold)

    assert "no threshold change suggested" in report


def test_render_report_kappa_none_shows_na() -> None:
    result = KappaByRubric(
        overall=KappaResult(
            kappa=None, agreement=1.0, n=1, judge_pass_rate=1.0, human_pass_rate=1.0
        )
    )
    threshold = suggest_threshold([])

    report = render_report(result, threshold)

    assert "n/a" in report


def test_render_report_interprets_kappa_strength() -> None:
    result = KappaByRubric(
        overall=KappaResult(
            kappa=0.85, agreement=0.9, n=20, judge_pass_rate=0.5, human_pass_rate=0.5
        )
    )
    threshold = suggest_threshold([])

    report = render_report(result, threshold)

    assert "almost perfect" in report
