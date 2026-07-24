"""Regress CLI entrypoint.

`regress up` starts the collector + API + dashboard as a single process,
per the instant-developer-pickup design north star in CLAUDE.md.
"""

from __future__ import annotations

from pathlib import Path

import click
from sqlalchemy import select

from regress import __version__


@click.group()
@click.version_option(version=__version__, prog_name="regress")
def main() -> None:
    """Regress: your agent's production failures become its regression suite."""


@main.command()
@click.option("--host", default="127.0.0.1", show_default=True, help="Bind host.")
@click.option("--port", default=8990, show_default=True, help="Bind port.")
@click.option("--reload", is_flag=True, default=False, help="Enable autoreload (development only).")
def up(host: str, port: int, reload: bool) -> None:
    """Start the Regress collector, API, and dashboard as one process."""
    import uvicorn

    click.echo(f"Starting Regress on http://{host}:{port}")
    uvicorn.run("regress.app:app", host=host, port=port, reload=reload)


@main.command()
@click.option("--limit", default=20, show_default=True, help="Maximum number of traces to list.")
def traces(limit: int) -> None:
    """List ingested traces, most recent first."""
    from regress.db import get_session, init_db
    from regress.models import Trace

    init_db()
    with get_session() as session:
        rows = session.execute(
            select(Trace).order_by(Trace.ingested_at.desc()).limit(limit)
        ).scalars().all()

        if not rows:
            click.echo("No traces ingested yet.")
            return

        header = f"{'TRACE ID':<34} {'APP':<16} {'STATUS':<8} {'LATENCY (ms)':<14} {'STARTED AT'}"
        click.echo(header)
        for row in rows:
            latency = f"{row.latency_ms:.1f}" if row.latency_ms is not None else "-"
            started = row.started_at.isoformat() if row.started_at else "-"
            click.echo(
                f"{row.id:<34} {(row.app or '-'):<16} {row.status:<8} {latency:<14} {started}"
            )


@main.command()
@click.option(
    "--config",
    "config_path",
    type=click.Path(path_type=Path),
    default=None,
    help="Path to regress.yaml. Defaults to ./regress.yaml if present, otherwise runs "
    "only the zero-config not_refusal check.",
)
@click.option(
    "--rescore",
    is_flag=True,
    default=False,
    help="Re-run checks even on spans that already have scores.",
)
def score(config_path: Path | None, rescore: bool) -> None:
    """Run deterministic + judge checks against ingested spans."""
    from regress.config import ConfigError, load_config
    from regress.db import get_session, init_db
    from regress.models import Score, Span
    from regress.scoring.run import score_spans

    try:
        config = load_config(config_path)
    except ConfigError as exc:
        raise click.ClickException(str(exc)) from exc

    if not config.checks:
        click.echo("No checks configured. Add a regress.yaml or use the default not_refusal check.")
        return

    init_db()
    with get_session() as session:
        query = select(Span)
        if not rescore:
            already_scored = select(Score.span_id).where(Score.span_id.is_not(None))
            query = query.where(~Span.id.in_(already_scored))
        spans = session.execute(query).scalars().all()

        if not spans:
            click.echo("No spans to score.")
            return

        errors: list[str] = []
        rows = score_spans(
            session,
            list(spans),
            config,
            on_error=lambda span, check, exc: errors.append(f"{span.id}/{check.name}: {exc}"),
        )
        session.commit()

        click.echo(
            f"Scored {len(spans)} span(s) against {len(config.checks)} check(s): "
            f"{len(rows)} score(s)."
        )
        for error in errors:
            click.echo(f"  skipped: {error}")


if __name__ == "__main__":
    main()
