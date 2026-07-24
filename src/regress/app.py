"""FastAPI application factory for the Regress collector + API.

Phase 0 ships a health check only. Ingest, scoring, clustering, and eval
generation land in later phases per CLAUDE.md's MASTER_PLAN.
"""

from __future__ import annotations

from fastapi import FastAPI

from regress import __version__


def create_app() -> FastAPI:
    app = FastAPI(
        title="Regress",
        description="Your agent's production failures become its regression suite. Automatically.",
        version=__version__,
    )

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    return app


app = create_app()
