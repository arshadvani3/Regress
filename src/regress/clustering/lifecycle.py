"""Issue lifecycle: match new clusters to existing issues, detect regressions.

`active -> resolved -> regressed` per CLAUDE.md. Resolution itself is a
human call (there's no signal in the data that a fix landed) — the
dashboard will drive it in Phase 7; for now `resolve_issue()` lets it be
exercised end-to-end. What the Clusterer owns is the reverse transition:
a resolved issue's centroid gets a new failing trace nearby, so it flips to
`regressed`. That's the headline feature CLAUDE.md calls out — a fix that
didn't hold.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from regress.clustering.cluster import Cluster
from regress.models import Issue, IssueTrace

DEFAULT_MATCH_THRESHOLD = 0.25  # cosine distance; lower = more similar


def _cosine_distance(a: list[float], b: list[float]) -> float:
    vec_a, vec_b = np.array(a), np.array(b)
    denom = np.linalg.norm(vec_a) * np.linalg.norm(vec_b)
    if denom == 0:
        return 1.0
    similarity = float(np.dot(vec_a, vec_b) / denom)
    return 1.0 - similarity


def _closest_issue(
    centroid: list[float], issues: list[Issue], *, threshold: float
) -> Issue | None:
    best: Issue | None = None
    best_distance = threshold
    for issue in issues:
        distance = _cosine_distance(centroid, issue.centroid_vector)
        if distance <= best_distance:
            best = issue
            best_distance = distance
    return best


@dataclass
class LifecycleResult:
    new_issues: list[Issue]
    updated_issues: list[Issue]
    regressed_issues: list[Issue]


def apply_clusters(
    session: Session,
    clusters: list[Cluster],
    titles: dict[int, tuple[str, str]],
    *,
    threshold: float = DEFAULT_MATCH_THRESHOLD,
) -> LifecycleResult:
    """Match each cluster to an existing issue or create a new one.

    `titles` maps each cluster's index (in `clusters`) to an (title,
    description) pair, since titling is an LLM call the caller makes
    separately (and may skip/cache).

    A cluster matching a `resolved` issue flips it to `regressed` — the new
    trace proves the fix didn't hold. A cluster matching an `active` issue
    just adds the new traces. No match creates a new `active` issue.
    """
    existing_issues = list(session.execute(select(Issue)).scalars().all())

    result = LifecycleResult(new_issues=[], updated_issues=[], regressed_issues=[])

    for index, cluster in enumerate(clusters):
        title, description = titles.get(index, ("Untitled issue", ""))
        candidates = [i for i in existing_issues if i.state != "regressed"]
        match = _closest_issue(cluster.centroid, candidates, threshold=threshold)

        if match is None:
            issue = Issue(
                title=title,
                description=description,
                state="active",
                centroid_vector=cluster.centroid,
            )
            session.add(issue)
            session.flush()
            for trace_id in cluster.trace_ids:
                session.add(IssueTrace(issue_id=issue.id, trace_id=trace_id))
            result.new_issues.append(issue)
            existing_issues.append(issue)
            continue

        existing_trace_ids = {
            row[0]
            for row in session.execute(
                select(IssueTrace.trace_id).where(IssueTrace.issue_id == match.id)
            )
        }
        newly_added = [t for t in cluster.trace_ids if t not in existing_trace_ids]
        for trace_id in newly_added:
            session.add(IssueTrace(issue_id=match.id, trace_id=trace_id))

        if match.state == "resolved" and newly_added:
            match.state = "regressed"
            result.regressed_issues.append(match)
        elif newly_added:
            result.updated_issues.append(match)

    session.flush()
    return result


def resolve_issue(issue: Issue) -> None:
    """Mark an issue resolved. A human/dashboard call — the Clusterer never
    resolves issues on its own, only detects when a resolved one regresses.
    """
    issue.state = "resolved"
    issue.resolved_at = datetime.now(UTC)
