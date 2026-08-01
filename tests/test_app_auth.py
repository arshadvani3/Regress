from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from regress.app import create_app
from regress.models import Trace

TOKEN = "s3cret-token"


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
def auth_client(engine: Engine, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    # The token is read at app-build time, so set it before create_app().
    monkeypatch.setenv("REGRESS_AUTH_TOKEN", TOKEN)
    app = create_app(engine=engine)  # creates the schema via init_db()
    with Session(engine) as session:
        session.add(Trace(id="t1", app="demo", status="ok"))
        session.commit()
    return TestClient(app)


def test_no_token_env_means_no_auth(engine: Engine, monkeypatch: pytest.MonkeyPatch) -> None:
    # Zero-config default: nothing set -> API is open, unchanged behavior.
    monkeypatch.delenv("REGRESS_AUTH_TOKEN", raising=False)
    client = TestClient(create_app(engine=engine))

    assert client.get("/api/traces").status_code == 200


def test_api_rejects_missing_token(auth_client: TestClient) -> None:
    response = auth_client.get("/api/traces")

    assert response.status_code == 401
    assert response.headers.get("www-authenticate") == "Bearer"


def test_api_rejects_wrong_token(auth_client: TestClient) -> None:
    response = auth_client.get("/api/traces", headers={"authorization": "Bearer nope"})

    assert response.status_code == 401


def test_api_accepts_correct_token(auth_client: TestClient) -> None:
    response = auth_client.get("/api/traces", headers={"authorization": f"Bearer {TOKEN}"})

    assert response.status_code == 200


def test_ingest_is_protected(auth_client: TestClient) -> None:
    response = auth_client.post(
        "/v1/traces", content=b"{}", headers={"content-type": "application/json"}
    )

    assert response.status_code == 401


def test_ingest_accepts_correct_token(auth_client: TestClient) -> None:
    response = auth_client.post(
        "/v1/traces",
        content=b'{"resourceSpans": []}',
        headers={"content-type": "application/json", "authorization": f"Bearer {TOKEN}"},
    )

    assert response.status_code == 200


def test_health_is_open_even_with_auth(auth_client: TestClient) -> None:
    # Liveness probes have no token; health must stay reachable.
    assert auth_client.get("/health").status_code == 200


def test_non_bearer_scheme_is_rejected(auth_client: TestClient) -> None:
    response = auth_client.get(
        "/api/traces", headers={"authorization": f"Basic {TOKEN}"}
    )

    assert response.status_code == 401
