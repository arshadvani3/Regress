import click
import pytest

from regress.cli import (
    MIN_ALLOWED_CLUSTER_SIZE,
    _too_few_failures_message,
    _validate_min_cluster_size,
)


def test_validate_min_cluster_size_accepts_two_and_above() -> None:
    _validate_min_cluster_size(2)
    _validate_min_cluster_size(3)
    _validate_min_cluster_size(100)


@pytest.mark.parametrize("bad", [1, 0, -1])
def test_validate_min_cluster_size_rejects_below_two(bad: int) -> None:
    with pytest.raises(click.ClickException, match="must be at least 2"):
        _validate_min_cluster_size(bad)


def test_too_few_failures_message_zero_points_at_score() -> None:
    msg = _too_few_failures_message(0, 3)
    assert "No scored-bad traces" in msg
    assert "regress score" in msg


def test_too_few_failures_message_suggests_lower_floor_when_possible() -> None:
    # 2 failures, floor 3: could retry at --min-cluster-size 2
    msg = _too_few_failures_message(2, 3)
    assert "Only 2 scored-bad traces" in msg
    assert f"--min-cluster-size {MIN_ALLOWED_CLUSTER_SIZE}" in msg


def test_too_few_failures_message_singular_grammar() -> None:
    msg = _too_few_failures_message(1, 3)
    assert "Only 1 scored-bad trace " in msg  # no plural 's'


def test_too_few_failures_message_no_lower_floor_when_at_hdbscan_minimum() -> None:
    # 1 failure with floor already at the HDBSCAN minimum (2): can't suggest
    # a lower floor, so it should just say keep accumulating.
    msg = _too_few_failures_message(1, 2)
    assert "keep running your app" in msg.lower() or "accumulate more" in msg.lower()
    assert "--min-cluster-size" not in msg
