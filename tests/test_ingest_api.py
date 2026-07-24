from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from regress.app import create_app
from regress.models import Message, Span, Trace

FIXTURES = Path(__file__).parent / "fixtures"


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


def test_post_traces_protobuf_ingests_spans(client: TestClient, engine: Engine) -> None:
    body = (FIXTURES / "chat_trace.pb").read_bytes()

    response = client.post(
        "/v1/traces", content=body, headers={"content-type": "application/x-protobuf"}
    )

    assert response.status_code == 200
    assert response.headers["x-regress-spans-ingested"] == "2"

    with Session(engine) as session:
        assert session.query(Trace).count() == 1
        assert session.query(Span).count() == 2
        assert session.query(Message).count() == 2


def test_post_traces_json_ingests_spans(client: TestClient, engine: Engine) -> None:
    body = (FIXTURES / "chat_trace.json").read_bytes()

    response = client.post("/v1/traces", content=body, headers={"content-type": "application/json"})

    assert response.status_code == 200
    assert response.headers["x-regress-spans-ingested"] == "2"

    with Session(engine) as session:
        assert session.query(Trace).count() == 1


def test_post_traces_invalid_payload_returns_400(client: TestClient) -> None:
    response = client.post(
        "/v1/traces",
        content=b"garbage",
        headers={"content-type": "application/x-protobuf"},
    )

    assert response.status_code == 400


def test_post_traces_error_span_marks_trace_status_error(
    client: TestClient, engine: Engine
) -> None:
    body = (FIXTURES / "error_trace.pb").read_bytes()

    response = client.post(
        "/v1/traces", content=body, headers={"content-type": "application/x-protobuf"}
    )

    assert response.status_code == 200
    with Session(engine) as session:
        trace = session.query(Trace).one()
        assert trace.status == "error"
