from regress.calibrate.kappa import LabeledPair, cohens_kappa, kappa_by_rubric


def _pairs(judge_human: list[tuple[bool, bool]], rubric: str = "r") -> list[LabeledPair]:
    return [
        LabeledPair(judge_passed=j, human_value=h, rubric=rubric) for j, h in judge_human
    ]


def test_cohens_kappa_perfect_agreement_is_none_undefined() -> None:
    result = cohens_kappa(_pairs([(True, True)] * 10))

    # Perfect agreement with no variance makes expected_agreement == 1.0,
    # which makes kappa mathematically undefined (0/0), not 1.0 or 0.0.
    assert result.kappa is None
    assert result.agreement == 1.0


def test_cohens_kappa_perfect_disagreement() -> None:
    result = cohens_kappa(_pairs([(True, False)] * 10))

    assert result.kappa == 0.0
    assert result.agreement == 0.0


def test_cohens_kappa_matches_known_value() -> None:
    # Cross-checked against sklearn.metrics.cohen_kappa_score during
    # development: 90% raw agreement but kappa should be negative because
    # both raters mostly say "pass", so chance agreement is already high.
    pairs = _pairs([(True, True)] * 18 + [(True, False), (False, True)])

    result = cohens_kappa(pairs)

    assert result.kappa is not None
    assert result.kappa < 0
    assert result.agreement == 0.9


def test_cohens_kappa_empty_returns_none_with_zero_n() -> None:
    result = cohens_kappa([])

    assert result.kappa is None
    assert result.n == 0


def test_cohens_kappa_single_pair_returns_none() -> None:
    result = cohens_kappa(_pairs([(True, True)]))

    assert result.kappa is None
    assert result.n == 1
    assert result.agreement == 1.0


def test_cohens_kappa_reports_pass_rates() -> None:
    pairs = _pairs([(True, True), (True, False), (False, False), (False, False)])

    result = cohens_kappa(pairs)

    assert result.judge_pass_rate == 0.5
    assert result.human_pass_rate == 0.25


def test_kappa_by_rubric_groups_correctly() -> None:
    pairs = _pairs([(True, True), (True, False)], rubric="A") + _pairs(
        [(False, False), (False, False)], rubric="B"
    )

    result = kappa_by_rubric(pairs)

    assert result.overall.n == 4
    assert set(result.by_rubric.keys()) == {"A", "B"}
    assert result.by_rubric["A"].n == 2
    assert result.by_rubric["B"].n == 2


def test_kappa_by_rubric_empty_pairs() -> None:
    result = kappa_by_rubric([])

    assert result.overall.n == 0
    assert result.by_rubric == {}
