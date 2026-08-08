"""Orchestrate the Clusterer end to end: embed -> HDBSCAN -> title -> lifecycle."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from regress.clustering import failure_text, scored_bad_traces
from regress.clustering.cluster import Cluster, cluster_traces
from regress.clustering.embed import Embedder, load_embedder
from regress.clustering.embed_store import embed_incremental
from regress.clustering.lifecycle import LifecycleResult, apply_clusters
from regress.clustering.titler import IssueTitle, TitlerError, title_cluster
from regress.models import Trace
from regress.scoring.judge import JudgeClient


@dataclass
class ClusterRunResult:
    lifecycle: LifecycleResult
    clusters_found: int
    traces_considered: int
    titling_errors: list[str]


def run_clustering(
    session: Session,
    *,
    min_cluster_size: int = 3,
    embedder: Embedder | None = None,
    judge_client: JudgeClient | None = None,
) -> ClusterRunResult:
    """Embed every scored-bad trace, cluster them, title each cluster, and
    reconcile against existing Issues (new / updated / regressed).
    """
    traces = list(session.execute(select(Trace)).scalars().all())
    bad_traces = scored_bad_traces(traces)

    if len(bad_traces) < min_cluster_size:
        return ClusterRunResult(
            lifecycle=LifecycleResult(new_issues=[], updated_issues=[], regressed_issues=[]),
            clusters_found=0,
            traces_considered=len(bad_traces),
            titling_errors=[],
        )

    clusterable = [failure_text(trace) for trace in bad_traces]
    active_embedder = embedder or load_embedder()
    # Incremental: reuse stored vectors, embed only new/changed failure text.
    embeddings = embed_incremental(session, clusterable, active_embedder)

    clusters: list[Cluster] = cluster_traces(
        [c.trace_id for c in clusterable], embeddings, min_cluster_size=min_cluster_size
    )

    text_by_trace_id = {c.trace_id: c.text for c in clusterable}
    titler_client = judge_client or JudgeClient()
    titles: dict[int, tuple[str, str]] = {}
    titling_errors: list[str] = []
    for index, cluster in enumerate(clusters):
        examples = [text_by_trace_id[t] for t in cluster.trace_ids]
        try:
            title: IssueTitle = title_cluster(examples, client=titler_client)
            titles[index] = (title.title, title.description)
        except TitlerError as exc:
            titling_errors.append(f"cluster {index}: {exc}")
            titles[index] = (
                f"Untitled cluster ({len(cluster.trace_ids)} traces)",
                "Titling failed; see logs.",
            )

    lifecycle = apply_clusters(session, clusters, titles)

    return ClusterRunResult(
        lifecycle=lifecycle,
        clusters_found=len(clusters),
        traces_considered=len(bad_traces),
        titling_errors=titling_errors,
    )
