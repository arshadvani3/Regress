from regress.evalgen.gate import two_proportion_z_test


def test_large_significant_drop_is_a_regression() -> None:
    result = two_proportion_z_test(95, 100, 80, 100)

    assert result.is_regression is True
    assert result.p_value < 0.05


def test_tiny_drop_on_small_sample_is_not_a_regression() -> None:
    result = two_proportion_z_test(9, 10, 8, 10)

    assert result.is_regression is False


def test_small_drop_on_large_sample_is_not_significant() -> None:
    result = two_proportion_z_test(50, 100, 48, 100)

    assert result.is_regression is False


def test_massive_drop_is_a_regression() -> None:
    result = two_proportion_z_test(100, 100, 60, 100)

    assert result.is_regression is True
    assert result.p_value < 0.001


def test_improvement_is_never_a_regression() -> None:
    result = two_proportion_z_test(50, 100, 55, 100)

    assert result.is_regression is False
    assert result.p_value == 1.0


def test_no_change_at_100_percent_is_not_a_regression() -> None:
    result = two_proportion_z_test(10, 10, 10, 10)

    assert result.is_regression is False


def test_no_change_at_zero_percent_is_not_a_regression() -> None:
    result = two_proportion_z_test(0, 10, 0, 10)

    assert result.is_regression is False


def test_zero_baseline_total_is_not_a_regression() -> None:
    result = two_proportion_z_test(0, 0, 5, 10)

    assert result.is_regression is False


def test_zero_current_total_is_not_a_regression() -> None:
    result = two_proportion_z_test(5, 10, 0, 0)

    assert result.is_regression is False


def test_complete_drop_from_100_percent_is_a_regression() -> None:
    result = two_proportion_z_test(10, 10, 0, 10)

    assert result.is_regression is True
    assert result.p_value < 0.001


def test_stricter_alpha_requires_stronger_evidence() -> None:
    lenient = two_proportion_z_test(20, 20, 17, 20, alpha=0.10)
    strict = two_proportion_z_test(20, 20, 17, 20, alpha=0.001)

    assert lenient.p_value == strict.p_value
    assert lenient.is_regression or not strict.is_regression


def test_result_reports_pass_rates() -> None:
    result = two_proportion_z_test(80, 100, 60, 100)

    assert result.baseline_pass_rate == 0.8
    assert result.current_pass_rate == 0.6
