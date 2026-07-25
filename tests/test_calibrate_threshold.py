from regress.calibrate.threshold import ValuedPair, suggest_threshold


def test_suggest_threshold_finds_a_perfect_cutoff() -> None:
    pairs = [
        ValuedPair(value=0.9, judge_passed=True, human_value=True),
        ValuedPair(value=0.8, judge_passed=True, human_value=True),
        ValuedPair(value=0.3, judge_passed=False, human_value=False),
        ValuedPair(value=0.2, judge_passed=False, human_value=False),
    ]

    result = suggest_threshold(pairs)

    assert result.suggested_agreement == 1.0
    assert result.suggested_threshold is not None
    assert 0.3 < result.suggested_threshold < 0.8


def test_suggest_threshold_reports_judge_own_agreement() -> None:
    pairs = [
        ValuedPair(value=0.9, judge_passed=True, human_value=True),
        ValuedPair(value=0.1, judge_passed=True, human_value=False),  # judge wrong
        ValuedPair(value=0.2, judge_passed=False, human_value=False),
        ValuedPair(value=0.8, judge_passed=False, human_value=True),  # judge wrong
    ]

    result = suggest_threshold(pairs)

    assert result.judge_own_agreement == 0.5


def test_suggest_threshold_improves_on_judge_when_cutoff_beats_it() -> None:
    pairs = [
        ValuedPair(value=0.9, judge_passed=True, human_value=True),
        ValuedPair(value=0.8, judge_passed=False, human_value=True),  # judge wrong
        ValuedPair(value=0.3, judge_passed=True, human_value=False),  # judge wrong
        ValuedPair(value=0.2, judge_passed=False, human_value=False),
    ]

    result = suggest_threshold(pairs)

    assert result.improves_on_judge is True
    assert result.suggested_agreement > result.judge_own_agreement


def test_suggest_threshold_does_not_improve_when_judge_already_optimal() -> None:
    pairs = [
        ValuedPair(value=0.9, judge_passed=True, human_value=True),
        ValuedPair(value=0.8, judge_passed=True, human_value=True),
        ValuedPair(value=0.3, judge_passed=False, human_value=False),
        ValuedPair(value=0.2, judge_passed=False, human_value=False),
    ]

    result = suggest_threshold(pairs)

    assert result.improves_on_judge is False


def test_suggest_threshold_empty_pairs() -> None:
    result = suggest_threshold([])

    assert result.suggested_threshold is None
    assert result.n == 0
    assert result.improves_on_judge is False


def test_suggest_threshold_single_pair() -> None:
    result = suggest_threshold([ValuedPair(value=0.5, judge_passed=True, human_value=True)])

    assert result.suggested_agreement == 1.0
    assert result.n == 1


def test_suggest_threshold_all_same_value_still_returns_a_cutoff() -> None:
    pairs = [
        ValuedPair(value=0.5, judge_passed=True, human_value=True),
        ValuedPair(value=0.5, judge_passed=True, human_value=False),
    ]

    result = suggest_threshold(pairs)

    assert result.suggested_threshold is not None
    assert result.n == 2


def test_suggest_threshold_all_human_pass_finds_cutoff_below_min_value() -> None:
    pairs = [
        ValuedPair(value=0.9, judge_passed=True, human_value=True),
        ValuedPair(value=0.5, judge_passed=False, human_value=True),
        ValuedPair(value=0.1, judge_passed=False, human_value=True),
    ]

    result = suggest_threshold(pairs)

    assert result.suggested_agreement == 1.0
    assert result.suggested_threshold is not None
    assert result.suggested_threshold < 0.1
