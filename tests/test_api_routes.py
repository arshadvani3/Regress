from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from regress.app import create_app
from regress.models import Issue, IssueTrace, Label, Message, Score, Span, Trace


@pytest.fixture
def engine() -> Iterator[Engine]:
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    yield engine
    engine.dispose()


@pytest.fixture
def client(engine: Engine) -> TestClient:
    return TestClient(create_app(engine=engine))


def _seed_trace(engine: Engine, trace_id: str = "t1") -> None:
    with Session(engine) as session:
        session.add(Trace(id=trace_id, app="demo", status="error"))
        session.add(
            Span(
                id=f"{trace_id}-s1",
                trace_id=trace_id,
                name="chat",
                status="error",
                gen_ai_operation_name="chat",
            )
        )
        session.add(
            Message(
                span_id=f"{trace_id}-s1",
                direction="input",
                role="user",
                position=0,
                content={"role": "user", "parts": [{"type": "text", "content": "hello there"}]},
            )
        )
        session.add(
            Message(
                span_id=f"{trace_id}-s1",
                direction="output",
                role="assistant",
                position=1,
                content={
                    "role": "assistant",
                    "parts": [{"type": "text", "content": "I cannot help"}],
                },
            )
        )
        session.add(
            Score(
                span_id=f"{trace_id}-s1",
                source="judge",
                name="judge_rubric",
                value=0.2,
                passed=False,
                rubric="answers the question",
                reasoning="refused",
            )
        )
        session.commit()


def test_list_traces_empty(client: TestClient) -> None:
    response = client.get("/api/traces")

    assert response.status_code == 200
    assert response.json() == []


def test_list_traces_includes_preview_from_first_input_message(
    client: TestClient, engine: Engine
) -> None:
    _seed_trace(engine)

    response = client.get("/api/traces")

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["id"] == "t1"
    assert body[0]["preview"] == "hello there"


def test_get_trace_detail_includes_spans_messages_and_scores(
    client: TestClient, engine: Engine
) -> None:
    _seed_trace(engine)

    response = client.get("/api/traces/t1")

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == "t1"
    assert len(body["spans"]) == 1
    span = body["spans"][0]
    assert [m["text"] for m in span["messages"]] == ["hello there", "I cannot help"]
    assert span["scores"][0]["rubric"] == "answers the question"


def test_get_trace_detail_404_when_missing(client: TestClient) -> None:
    response = client.get("/api/traces/nope")

    assert response.status_code == 404


def test_list_issues_empty(client: TestClient) -> None:
    response = client.get("/api/issues")

    assert response.status_code == 200
    assert response.json() == []


def test_list_issues_filters_by_state(client: TestClient, engine: Engine) -> None:
    with Session(engine) as session:
        session.add(
            Issue(title="Active one", description="d", state="active", centroid_vector=[0.1])
        )
        session.add(
            Issue(title="Resolved one", description="d", state="resolved", centroid_vector=[0.2])
        )
        session.commit()

    response = client.get("/api/issues", params={"state": "resolved"})

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["title"] == "Resolved one"


def test_get_issue_detail_includes_linked_traces(client: TestClient, engine: Engine) -> None:
    _seed_trace(engine)
    with Session(engine) as session:
        issue = Issue(title="Refusals", description="d", state="active", centroid_vector=[0.1])
        session.add(issue)
        session.commit()
        session.add(IssueTrace(issue_id=issue.id, trace_id="t1"))
        session.commit()
        issue_id = issue.id

    response = client.get(f"/api/issues/{issue_id}")

    assert response.status_code == 200
    body = response.json()
    assert body["title"] == "Refusals"
    assert len(body["traces"]) == 1
    assert body["traces"][0]["id"] == "t1"


def test_get_issue_detail_404_when_missing(client: TestClient) -> None:
    response = client.get("/api/issues/nope")

    assert response.status_code == 404


def test_unlabeled_scores_excludes_already_labeled(client: TestClient, engine: Engine) -> None:
    _seed_trace(engine)

    response = client.get("/api/calibration/unlabeled")
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["rubric"] == "answers the question"
    assert body[0]["output_preview"] == "I cannot help"

    with Session(engine) as session:
        score = session.query(Score).one()
        session.add(Label(score_id=score.id, human_value=False, labeler="arsh"))
        session.commit()

    response = client.get("/api/calibration/unlabeled")
    assert response.json() == []


def test_create_label_persists_and_404s_for_missing_score(
    client: TestClient, engine: Engine
) -> None:
    _seed_trace(engine)
    with Session(engine) as session:
        score_id = session.query(Score).one().id

    response = client.post(
        "/api/labels", json={"score_id": score_id, "human_value": False, "labeler": "arsh"}
    )

    assert response.status_code == 201
    with Session(engine) as session:
        assert session.query(Label).count() == 1

    missing = client.post(
        "/api/labels", json={"score_id": "nope", "human_value": True, "labeler": "arsh"}
    )
    assert missing.status_code == 404


def test_calibration_report_reflects_labels(client: TestClient, engine: Engine) -> None:
    _seed_trace(engine)
    with Session(engine) as session:
        score = session.query(Score).one()
        session.add(Label(score_id=score.id, human_value=False, labeler="arsh"))
        session.commit()

    response = client.get("/api/calibration/report")

    assert response.status_code == 200
    body = response.json()
    assert body["overall"]["n"] == 1
    assert body["overall"]["agreement"] == 1.0
    assert len(body["labeled_pairs"]) == 1
    assert body["labeled_pairs"][0]["labeler"] == "arsh"


def test_calibration_report_empty_when_no_labels(client: TestClient) -> None:
    response = client.get("/api/calibration/report")

    assert response.status_code == 200
    body = response.json()
    assert body["overall"]["n"] == 0
    assert body["overall"]["kappa"] is None
    assert body["labeled_pairs"] == []
