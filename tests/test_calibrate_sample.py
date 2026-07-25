from regress.calibrate.sample import sample_judge_scores
from regress.models import Label, Score


def _judge_score(idx: str, rubric: str) -> Score:
    return Score(
        id=idx, source="judge", name="judge_rubric", value=0.5, passed=True, rubric=rubric
    )


def test_sample_excludes_deterministic_scores() -> None:
    scores = [
        Score(id="d1", source="deterministic", name="not_refusal", value=1.0, passed=True),
        _judge_score("j1", "rubric A"),
    ]

    sample = sample_judge_scores(scores, 10, seed=0)

    assert [s.id for s in sample] == ["j1"]


def test_sample_excludes_judge_scores_without_a_rubric() -> None:
    scores = [
        Score(id="j1", source="judge", name="judge_rubric", value=0.5, passed=True, rubric=None),
        _judge_score("j2", "rubric A"),
    ]

    sample = sample_judge_scores(scores, 10, seed=0)

    assert [s.id for s in sample] == ["j2"]


def test_sample_excludes_already_labeled_scores_by_default() -> None:
    labeled = _judge_score("j1", "rubric A")
    labeled.labels = [Label(score_id="j1", human_value=True, labeler="arsh")]
    unlabeled = _judge_score("j2", "rubric A")

    sample = sample_judge_scores([labeled, unlabeled], 10, seed=0)

    assert [s.id for s in sample] == ["j2"]


def test_sample_includes_labeled_scores_when_requested() -> None:
    labeled = _judge_score("j1", "rubric A")
    labeled.labels = [Label(score_id="j1", human_value=True, labeler="arsh")]

    sample = sample_judge_scores([labeled], 10, include_labeled=True, seed=0)

    assert [s.id for s in sample] == ["j1"]


def test_sample_caps_at_n() -> None:
    scores = [_judge_score(f"j{i}", "rubric A") for i in range(20)]

    sample = sample_judge_scores(scores, 5, seed=0)

    assert len(sample) == 5


def test_sample_caps_at_candidate_count_when_fewer_than_n() -> None:
    scores = [_judge_score(f"j{i}", "rubric A") for i in range(3)]

    sample = sample_judge_scores(scores, 100, seed=0)

    assert len(sample) == 3


def test_sample_stratifies_across_rubrics() -> None:
    scores = [_judge_score(f"a{i}", "rubric A") for i in range(20)]
    scores += [_judge_score(f"b{i}", "rubric B") for i in range(2)]

    sample = sample_judge_scores(scores, 4, seed=0)

    rubrics = {s.rubric for s in sample}
    assert rubrics == {"rubric A", "rubric B"}


def test_sample_returns_no_duplicates() -> None:
    scores = [_judge_score(f"j{i}", "rubric A") for i in range(10)]

    sample = sample_judge_scores(scores, 10, seed=0)

    assert len({s.id for s in sample}) == len(sample)


def test_sample_empty_candidates_returns_empty() -> None:
    assert sample_judge_scores([], 5, seed=0) == []


def test_sample_is_deterministic_given_a_seed() -> None:
    scores = [_judge_score(f"j{i}", "rubric A") for i in range(20)]

    first = sample_judge_scores(scores, 5, seed=42)
    second = sample_judge_scores(scores, 5, seed=42)

    assert [s.id for s in first] == [s.id for s in second]
