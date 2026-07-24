"""Regress CLI entrypoint.

`regress up` starts the collector + API + dashboard as a single process,
per the instant-developer-pickup design north star in CLAUDE.md.
"""

from __future__ import annotations

import click

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


if __name__ == "__main__":
    main()
