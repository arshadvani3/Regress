"""Covers app.py's SPA-fallback route, using a fake dashboard_dist so the
test doesn't depend on `npm run build` having been run.
"""

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.pool import StaticPool

from regress import app as app_module


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
def client(engine: Engine, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    dist = tmp_path / "dashboard_dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<html><body>dashboard shell</body></html>")
    (dist / "assets" / "app.js").write_text("console.log('ok')")
    monkeypatch.setattr(app_module, "_DASHBOARD_DIST", dist)

    return TestClient(app_module.create_app(engine=engine))


def test_root_serves_index_html(client: TestClient) -> None:
    response = client.get("/")

    assert response.status_code == 200
    assert "dashboard shell" in response.text


def test_client_side_route_falls_back_to_index_html(client: TestClient) -> None:
    response = client.get("/traces/some-trace-id")

    assert response.status_code == 200
    assert "dashboard shell" in response.text


def test_static_asset_is_served_directly(client: TestClient) -> None:
    response = client.get("/assets/app.js")

    assert response.status_code == 200
    assert "console.log" in response.text


def test_api_routes_are_not_shadowed_by_spa_fallback(client: TestClient) -> None:
    response = client.get("/api/traces")

    assert response.status_code == 200
    assert response.json() == []


def test_health_is_not_shadowed_by_spa_fallback(client: TestClient) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_unknown_api_path_stays_json_404_not_spa_fallback(client: TestClient) -> None:
    response = client.get("/api/traces/does-not-exist")

    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/json")


def test_no_dashboard_dist_means_no_spa_routes(
    engine: Engine, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(app_module, "_DASHBOARD_DIST", tmp_path / "does-not-exist")
    client = TestClient(app_module.create_app(engine=engine))

    response = client.get("/")

    assert response.status_code == 404
