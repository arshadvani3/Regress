"""Pull labeled judge scores from the DB into the shapes kappa/threshold need.

When a score has multiple labels (more than one labeler), each label
becomes its own pair — that's what makes inter-labeler disagreement
visible in the kappa breakdown rather than silently averaged away.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from regress.calibrate.kappa import LabeledPair
from regress.calibrate.threshold import ValuedPair
from regress.models import Label, Score


def labeled_judge_scores(session: Session) -> list[Score]:
    """Judge-sourced scores that have at least one human label."""
    stmt = (
        select(Score)
        .join(Label, Label.score_id == Score.id)
        .where(Score.source == "judge")
        .distinct()
    )
    return list(session.execute(stmt).scalars().all())


def to_labeled_pairs(scores: list[Score]) -> list[LabeledPair]:
    pairs = []
    for score in scores:
        for label in score.labels:
            pairs.append(
                LabeledPair(
                    judge_passed=bool(score.passed),
                    human_value=label.human_value,
                    rubric=score.rubric or "",
                )
            )
    return pairs


def to_valued_pairs(scores: list[Score]) -> list[ValuedPair]:
    pairs = []
    for score in scores:
        for label in score.labels:
            pairs.append(
                ValuedPair(
                    value=score.value,
                    judge_passed=bool(score.passed),
                    human_value=label.human_value,
                )
            )
    return pairs
