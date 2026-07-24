import os
import subprocess
import sys
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from regress.models import Base, Message, Score, Span, Trace

SRC = str(Path(__file__).parent.parent / "src")


def _subprocess_env(db_url: str) -> dict[str, str]:
    existing_path = os.environ.get("PYTHONPATH", "")
    python_path = f"{SRC}{os.pathsep}{existing_path}" if existing_path else SRC
    return {**os.environ, "REGRESS_DB_URL": db_url, "PYTHONPATH": python_path}


def _run_cli(*args: str, db_url: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "regress.cli", *args],
        env=_subprocess_env(db_url),
        capture_output=True,
        text=True,
        timeout=30,
    )


def _seed_bad_span(db_url: str, trace_id: str, text: str) -> None:
    sqlite_path = db_url.removeprefix("sqlite:///")
    engine = create_engine(f"sqlite:///{sqlite_path}")
    Base.metadata.create_all(engine)
    span_id = f"{trace_id}-s"
    with Session(engine) as session:
        session.add(Trace(id=trace_id, status="ok"))
        session.add(Span(id=span_id, trace_id=trace_id, name="chat", status="ok"))
        session.add(
            Message(
                span_id=span_id,
                direction="output",
                role="assistant",
                position=0,
                content={"role": "assistant", "parts": [{"type": "text", "content": text}]},
            )
        )
        session.add(
            Score(
                span_id=span_id,
                source="deterministic",
                name="not_refusal",
                value=0.0,
                passed=False,
            )
        )
        session.commit()
    engine.dispose()


def test_cluster_command_reports_nothing_to_cluster_when_db_empty(tmp_path: Path) -> None:
    db_url = f"sqlite:///{tmp_path / 'empty.db'}"

    result = _run_cli("cluster", db_url=db_url)

    assert result.returncode == 0
    assert "Nothing to cluster yet." in result.stdout


def test_cluster_command_reports_nothing_to_cluster_below_min_size(tmp_path: Path) -> None:
    db_url = f"sqlite:///{tmp_path / 'seeded.db'}"
    _seed_bad_span(db_url, "t1", "a refused response")

    result = _run_cli("cluster", "--min-cluster-size", "3", db_url=db_url)

    assert result.returncode == 0
    assert "Only 1 scored-bad trace(s) found" in result.stdout
    assert "Nothing to cluster yet." in result.stdout
