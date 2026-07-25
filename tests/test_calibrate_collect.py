from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from regress.calibrate.collect import labeled_judge_scores, to_labeled_pairs, to_valued_pairs
from regress.models import Base, Label, Score


@pytest.fixture
def session() -> Iterator[Session]:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


def test_labeled_judge_scores_excludes_unlabeled(session: Session) -> None:
    labeled = Score(source="judge", name="judge_rubric", value=0.8, passed=True, rubric="r")
    unlabeled = Score(source="judge", name="judge_rubric", value=0.6, passed=True, rubric="r")
    session.add_all([labeled, unlabeled])
    session.commit()
    session.add(Label(score_id=labeled.id, human_value=True, labeler="arsh"))
    session.commit()

    result = labeled_judge_scores(session)

    assert [s.id for s in result] == [labeled.id]


def test_labeled_judge_scores_excludes_deterministic(session: Session) -> None:
    det = Score(source="deterministic", name="not_refusal", value=1.0, passed=True)
    session.add(det)
    session.commit()
    session.add(Label(score_id=det.id, human_value=True, labeler="arsh"))
    session.commit()

    result = labeled_judge_scores(session)

    assert result == []


def test_labeled_judge_scores_no_duplicates_with_multiple_labels(session: Session) -> None:
    score = Score(source="judge", name="judge_rubric", value=0.8, passed=True, rubric="r")
    session.add(score)
    session.commit()
    session.add(Label(score_id=score.id, human_value=True, labeler="alice"))
    session.add(Label(score_id=score.id, human_value=False, labeler="bob"))
    session.commit()

    result = labeled_judge_scores(session)

    assert len(result) == 1


def test_to_labeled_pairs_creates_one_pair_per_label(session: Session) -> None:
    score = Score(source="judge", name="judge_rubric", value=0.8, passed=True, rubric="r")
    session.add(score)
    session.commit()
    session.add(Label(score_id=score.id, human_value=True, labeler="alice"))
    session.add(Label(score_id=score.id, human_value=False, labeler="bob"))
    session.commit()
    session.refresh(score)

    pairs = to_labeled_pairs([score])

    assert len(pairs) == 2
    assert {p.human_value for p in pairs} == {True, False}
    assert all(p.judge_passed is True for p in pairs)
    assert all(p.rubric == "r" for p in pairs)


def test_to_labeled_pairs_handles_none_rubric(session: Session) -> None:
    score = Score(source="judge", name="judge_rubric", value=0.8, passed=True, rubric=None)
    session.add(score)
    session.commit()
    session.add(Label(score_id=score.id, human_value=True, labeler="arsh"))
    session.commit()
    session.refresh(score)

    pairs = to_labeled_pairs([score])

    assert pairs[0].rubric == ""


def test_to_valued_pairs_includes_score_value(session: Session) -> None:
    score = Score(source="judge", name="judge_rubric", value=0.73, passed=True, rubric="r")
    session.add(score)
    session.commit()
    session.add(Label(score_id=score.id, human_value=False, labeler="arsh"))
    session.commit()
    session.refresh(score)

    pairs = to_valued_pairs([score])

    assert pairs[0].value == 0.73
    assert pairs[0].judge_passed is True
    assert pairs[0].human_value is False


def test_to_pairs_empty_scores_list() -> None:
    assert to_labeled_pairs([]) == []
    assert to_valued_pairs([]) == []
