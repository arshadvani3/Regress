"""FastAPI application factory for the Regress collector + API.

Ingest, the dashboard's read API, and (when built) the dashboard's static
assets are all served from this one process/port, per CLAUDE.md's "one
process, one port" DX rule.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, Response
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
        app.mount("/", StaticFiles(directory=_DASHBOARD_DIST, html=True), name="dashboard")

    return app


app = create_app()
