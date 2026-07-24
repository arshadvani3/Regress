import numpy as np
import pytest

from regress.clustering.cluster import cluster_traces


def test_cluster_traces_returns_empty_when_fewer_traces_than_min_cluster_size() -> None:
    embeddings = np.array([[1.0, 0.0], [0.0, 1.0]])

    clusters = cluster_traces(["t1", "t2"], embeddings, min_cluster_size=3)

    assert clusters == []


def test_cluster_traces_returns_dense_centroids_matching_embedding_dims() -> None:
    # Two well-separated, well-populated groups — HDBSCAN is sensitive to
    # min_cluster_size/density on small or overly-uniform synthetic data
    # (verified against the real embedder in test_clustering_embed.py), so
    # this uses group sizes and separation large enough to be unambiguous.
    rng = np.random.default_rng(0)
    group_a = rng.normal(loc=[10, 0, 0], scale=0.3, size=(15, 3))
    group_b = rng.normal(loc=[-10, 0, 0], scale=0.3, size=(15, 3))
    embeddings = np.vstack([group_a, group_b])
    trace_ids = [f"t{i}" for i in range(30)]

    clusters = cluster_traces(trace_ids, embeddings, min_cluster_size=3)

    assert len(clusters) >= 1
    for cluster in clusters:
        assert len(cluster.centroid) == 3
        assert set(cluster.trace_ids) <= set(trace_ids)


@pytest.mark.slow
def test_cluster_traces_separates_semantically_distinct_failures_with_real_embeddings() -> None:
    from regress.clustering.embed import load_embedder

    refund_texts = [
        "The assistant refused to help with the refund",
        "The assistant declined the refund request",
        "The assistant would not process the refund",
        "Refund request was denied by the assistant",
        "The assistant said no to the refund",
    ]
    weather_texts = [
        "The weather tool call had malformed JSON arguments",
        "get_weather tool call args did not match schema",
        "The tool call to get_weather failed with invalid arguments",
    ]
    texts = refund_texts + weather_texts
    trace_ids = [f"t{i}" for i in range(len(texts))]

    embedder = load_embedder()
    embeddings = embedder.embed(texts)
    clusters = cluster_traces(trace_ids, embeddings, min_cluster_size=3)

    assert len(clusters) == 2
    refund_ids = {f"t{i}" for i in range(len(refund_texts))}
    weather_ids = {f"t{i}" for i in range(len(refund_texts), len(texts))}
    cluster_sets = [set(c.trace_ids) for c in clusters]
    assert refund_ids in cluster_sets
    assert weather_ids in cluster_sets
