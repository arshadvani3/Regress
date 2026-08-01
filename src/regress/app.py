"""FastAPI application factory for the Regress collector + API.

Ingest, the dashboard's read API, and (when built) the dashboard's static
assets are all served from this one process/port, per CLAUDE.md's "one
process, one port" DX rule.
"""

from __future__ import annotations

import hmac
import os
from collections.abc import Awaitable, Callable, Iterator
from contextlib import contextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from regress import __version__
from regress.api.routes import make_router
from regress.db import engine as default_engine
from regress.db import init_db
from regress.ingest import OTLPParseError, iter_spans_from_request, parse_export_request
from regress.store import store_parsed_spans

_DASHBOARD_DIST = Path(__file__).parent / "dashboard_dist"

# When REGRESS_AUTH_TOKEN is set, the bearer token guards the data plane —
# ingest (`/v1/...`) and the read API (`/api/...`) — and nothing else. The
# static dashboard shell, health, and API docs stay open so probes work and a
# browser can load the SPA (which then attaches the token to its own fetches).
# This is the "single optional bearer token" of CLAUDE.md's non-goals: a
# shared-secret gate for a self-hosted collector, not a login system.
_AUTH_PROTECTED_PREFIXES = ("/api", "/v1")


def _extract_bearer(request: Request) -> str | None:
    header = request.headers.get("authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token:
        return None
    return token


def _requires_auth(path: str) -> bool:
    """True for paths guarded by the bearer token (the API/ingest data plane)."""
    return path.startswith(_AUTH_PROTECTED_PREFIXES)


def create_app(engine: Engine | None = None) -> FastAPI:
    """Build the Regress FastAPI app.

    Accepts an optional SQLAlchemy engine so tests can bind to an isolated
    in-memory database instead of the default `regress.db` SQLite file.
    """
    bind = engine or default_engine
    session_factory = sessionmaker(bind=bind, autoflush=False, autocommit=False)
    init_db(bind=bind)

    @contextmanager
    def get_session() -> Iterator[Session]:
        session = session_factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    app = FastAPI(
        title="Regress",
        description="Your agent's production failures become its regression suite. Automatically.",
        version=__version__,
    )

    auth_token = os.environ.get("REGRESS_AUTH_TOKEN") or None
    if auth_token:

        @app.middleware("http")
        async def require_bearer_token(
            request: Request, call_next: Callable[[Request], Awaitable[Response]]
        ) -> Response:
            if _requires_auth(request.url.path):
                presented = _extract_bearer(request)
                # hmac.compare_digest keeps the check constant-time so a wrong
                # token can't be recovered by timing the response.
                if presented is None or not hmac.compare_digest(presented, auth_token):
                    return JSONResponse(
                        status_code=401,
                        content={"detail": "missing or invalid bearer token"},
                        headers={"www-authenticate": "Bearer"},
                    )
            return await call_next(request)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    @app.post("/v1/traces")
    async def ingest_traces(request: Request) -> Response:
        body = await request.body()
        content_type = request.headers.get("content-type", "")
        try:
            export_request = parse_export_request(body, content_type)
        except OTLPParseError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        parsed = iter_spans_from_request(export_request)
        with get_session() as session:
            span_count = store_parsed_spans(session, parsed)

        return Response(
            status_code=200,
            content=b"" if "json" not in content_type else b"{}",
            media_type=content_type if "json" in content_type else "application/x-protobuf",
            headers={"x-regress-spans-ingested": str(span_count)},
        )

    app.include_router(make_router(session_factory))

    if _DASHBOARD_DIST.is_dir():
        app.mount(
            "/assets", StaticFiles(directory=_DASHBOARD_DIST / "assets"), name="dashboard-assets"
        )

        index_html = _DASHBOARD_DIST / "index.html"

        @app.get("/{full_path:path}", include_in_schema=False)
        async def dashboard_spa(full_path: str) -> Response:
            # React Router owns everything not already handled above (API,
            # health, ingest, /assets) — serve index.html for any of those
            # paths so a hard refresh on e.g. /traces/abc still works.
            candidate = _DASHBOARD_DIST / full_path
            if full_path and candidate.is_file():
                return FileResponse(candidate)
            return FileResponse(index_html)

    return app


app = create_app()
