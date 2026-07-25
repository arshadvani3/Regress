"""Pick N judge-sourced scores for a human to label.

Stratifies across distinct rubrics so a small N still gives some coverage
of every rubric in use, rather than all N landing on whichever rubric
happens to have the most scores. Already-labeled scores are excluded by
default — labeling the same verdict twice doesn't add calibration signal
unless the caller explicitly wants inter-labeler agreement, which
`include_labeled` supports.
"""

from __future__ import annotations

import random

from regress.models import Score


def sample_judge_scores(
    scores: list[Score],
    n: int,
    *,
    include_labeled: bool = False,
    seed: int | None = None,
) -> list[Score]:
    """Sample up to `n` judge-sourced scores, stratified by rubric.

    Round-robins across rubrics (each drawn from its own shuffled pool) so
    coverage spreads evenly rather than exhausting one rubric before
    touching the next.
    """
    candidates = [s for s in scores if s.source == "judge" and s.rubric]
    if not include_labeled:
        candidates = [s for s in candidates if not s.labels]

    by_rubric: dict[str, list[Score]] = {}
    for score in candidates:
        rubric = score.rubric or ""
        by_rubric.setdefault(rubric, []).append(score)

    rng = random.Random(seed)
    for pool in by_rubric.values():
        rng.shuffle(pool)

    rubrics = list(by_rubric.keys())
    rng.shuffle(rubrics)

    selected: list[Score] = []
    while len(selected) < n and any(by_rubric[r] for r in rubrics):
        for rubric in rubrics:
            if len(selected) >= n:
                break
            pool = by_rubric[rubric]
            if pool:
                selected.append(pool.pop())

    return selected
