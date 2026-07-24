import json
from collections.abc import Iterator

import httpx
import numpy as np
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import regress.clustering.run as run_module
from regress.clustering.cluster import Cluster
from regress.clustering.run import run_clustering
from regress.models import Base, Message, Score, Span, Trace
from regress.scoring.judge import JudgeClient


@pytest.fixture
def session() -> Iterator[Session]:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


class _FakeEmbedder:
    """Returns a fixed-size zero matrix — what HDBSCAN does with it doesn't
    matter here, since these tests stub `cluster_traces` directly rather
    than depend on HDBSCAN actually finding structure in synthetic vectors
    (its cosine-metric density estimate is too sensitive to arbitrary
    synthetic data to be a reliable orchestration-test fixture; that
    behavior is covered against real embeddings in test_clustering_cluster.py).
    """

    def embed(self, texts: list[str]) -> np.ndarray:
        return np.zeros((len(texts), 3))


def _seed_bad_trace(session: Session, trace_id: str, text: str) -> None:
    span_id = f"{trace_id}-s"
    session.add(Trace(id=trace_id, status="ok"))
    session.add(Span(id=span_id, trace_id=trace_id, name="chat", status="ok"))
    session.add(
        Message(
            span_id=span_id,
            direction="output",
            role="assistant",
            position=0,
            content={"role": "assistant", "parts": [{"type": "text", "content": text}]},
        )
    )
    session.add(
        Score(span_id=span_id, source="deterministic", name="not_refusal", value=0.0, passed=False)
    )
    session.commit()


def _fake_judge_response(url: str, **kwargs: object) -> httpx.Response:
    request = httpx.Request("POST", url)
    payload = json.dumps({"title": "Some issue", "description": "Some description"})
    body = {"choices": [{"message": {"content": payload}}]}
    return httpx.Response(200, request=request, json=body)


def test_run_clustering_skips_when_too_few_bad_traces(session: Session) -> None:
    _seed_bad_trace(session, "t1", "same failure")

    result = run_clustering(session, min_cluster_size=3, embedder=_FakeEmbedder())

    assert result.traces_considered == 1
    assert result.clusters_found == 0
    assert result.lifecycle.new_issues == []


def test_run_clustering_creates_issues_from_clustered_traces(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("regress.scoring.judge.httpx.post", _fake_judge_response)
    same_text = "the assistant refused to help"
    for i in range(4):
        _seed_bad_trace(session, f"t{i}", same_text)
    monkeypatch.setattr(
        run_module,
        "cluster_traces",
        lambda trace_ids, embeddings, min_cluster_size: [
            Cluster(trace_ids=trace_ids, centroid=[1.0, 0.0, 0.0])
        ],
    )

    result = run_clustering(
        session,
        min_cluster_size=3,
        embedder=_FakeEmbedder(),
        judge_client=JudgeClient(api_key="sk-test"),
    )

    assert result.traces_considered == 4
    assert result.clusters_found == 1
    assert len(result.lifecycle.new_issues) == 1
    assert result.lifecycle.new_issues[0].title == "Some issue"
    assert result.titling_errors == []


def test_run_clustering_only_considers_scored_bad_traces(session: Session) -> None:
    for i in range(3):
        _seed_bad_trace(session, f"bad{i}", "same failure")
    good_span_id = "good-s"
    session.add(Trace(id="good", status="ok"))
    session.add(Span(id=good_span_id, trace_id="good", name="chat", status="ok"))
    session.add(
        Score(
            span_id=good_span_id,
            source="deterministic",
            name="not_refusal",
            value=1.0,
            passed=True,
        )
    )
    session.commit()

    result = run_clustering(session, min_cluster_size=3, embedder=_FakeEmbedder())

    assert result.traces_considered == 3


def test_run_clustering_records_titling_errors_but_still_creates_issue(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    def raise_connect_error(*args: object, **kwargs: object) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr("regress.scoring.judge.httpx.post", raise_connect_error)
    same_text = "the assistant refused to help"
    trace_ids = [f"t{i}" for i in range(3)]
    for trace_id in trace_ids:
        _seed_bad_trace(session, trace_id, same_text)
    monkeypatch.setattr(
        run_module,
        "cluster_traces",
        lambda tids, embeddings, min_cluster_size: [Cluster(trace_ids=tids, centroid=[1.0, 0.0])],
    )

    result = run_clustering(
        session,
        min_cluster_size=3,
        embedder=_FakeEmbedder(),
        judge_client=JudgeClient(api_key="sk-test"),
    )

    assert len(result.titling_errors) == 1
    assert len(result.lifecycle.new_issues) == 1
    assert "Untitled cluster" in result.lifecycle.new_issues[0].title


def test_run_clustering_returns_zero_clusters_when_all_traces_are_noise(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    for i in range(3):
        _seed_bad_trace(session, f"t{i}", "an isolated failure")
    monkeypatch.setattr(run_module, "cluster_traces", lambda *a, **kw: [])

    result = run_clustering(session, min_cluster_size=3, embedder=_FakeEmbedder())

    assert result.traces_considered == 3
    assert result.clusters_found == 0
    assert result.lifecycle.new_issues == []
