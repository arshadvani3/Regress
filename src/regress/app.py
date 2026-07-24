"""FastAPI application factory for the Regress collector + API.

Phase 0 ships a health check only. Ingest, scoring, clustering, and eval
generation land in later phases per CLAUDE.md's MASTER_PLAN.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from fastapi import FastAPI, HTTPException, Request, Response
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from regress import __version__
from regress.db import engine as default_engine
from regress.db import init_db
from regress.ingest import OTLPParseError, iter_spans_from_request, parse_export_request
from regress.store import store_parsed_spans


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

    return app


app = create_app()
