"""HDBSCAN clustering over embedded scored-bad traces.

Uses scikit-learn's HDBSCAN (available since 1.3, part of the `cluster`
extra alongside sentence-transformers) rather than the separate `hdbscan`
PyPI package — avoids a second heavy/compiled dependency for the same
algorithm, per CLAUDE.md's "scikit-learn/hdbscan" stack note.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import numpy as np

NOISE_LABEL = -1


@dataclass
class Cluster:
    """One HDBSCAN cluster: which trace_ids belong to it, and its centroid."""

    trace_ids: list[str]
    centroid: list[float]


def cluster_traces(
    trace_ids: list[str],
    embeddings: np.ndarray,
    *,
    min_cluster_size: int = 3,
) -> list[Cluster]:
    """Group traces into clusters by embedding similarity.

    Traces HDBSCAN marks as noise (no cluster reaches `min_cluster_size`
    around them) are dropped — an isolated failure isn't a pattern yet.
    Returns one `Cluster` per non-noise label, in label order.
    """
    from sklearn.cluster import HDBSCAN

    if len(trace_ids) < min_cluster_size:
        return []

    model = HDBSCAN(
        min_cluster_size=min_cluster_size,
        metric="cosine",
        store_centers="centroid",
        copy=True,
    )
    labels = model.fit_predict(embeddings)

    clusters: dict[int, list[str]] = {}
    for trace_id, label in zip(trace_ids, labels, strict=True):
        if label == NOISE_LABEL:
            continue
        clusters.setdefault(int(label), []).append(trace_id)

    return [
        Cluster(trace_ids=members, centroid=model.centroids_[label].tolist())
        for label, members in sorted(clusters.items())
    ]
