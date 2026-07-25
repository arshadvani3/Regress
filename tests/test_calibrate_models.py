from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from regress.models import Base, Label, Score


@pytest.fixture
def session() -> Iterator[Session]:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


def test_label_belongs_to_a_score(session: Session) -> None:
    score = Score(source="judge", name="judge_rubric", value=0.8, passed=True, rubric="r")
    session.add(score)
    session.commit()

    session.add(Label(score_id=score.id, human_value=True, labeler="arsh"))
    session.commit()

    assert len(score.labels) == 1
    assert score.labels[0].human_value is True
    assert score.labels[0].labeler == "arsh"


def test_multiple_labelers_can_label_the_same_score(session: Session) -> None:
    score = Score(source="judge", name="judge_rubric", value=0.8, passed=True, rubric="r")
    session.add(score)
    session.commit()

    session.add(Label(score_id=score.id, human_value=True, labeler="alice"))
    session.add(Label(score_id=score.id, human_value=False, labeler="bob"))
    session.commit()

    assert len(score.labels) == 2
    assert {label.labeler for label in score.labels} == {"alice", "bob"}


def test_deleting_score_cascades_to_its_labels(session: Session) -> None:
    score = Score(source="judge", name="judge_rubric", value=0.8, passed=True, rubric="r")
    session.add(score)
    session.commit()
    session.add(Label(score_id=score.id, human_value=True, labeler="arsh"))
    session.commit()

    session.delete(session.get(Score, score.id))
    session.commit()

    assert session.execute(select(Label)).scalars().all() == []
