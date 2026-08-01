import os
import subprocess
import sys
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from regress.models import Issue, Trace

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


def _counts(db_url: str) -> tuple[int, int]:
    engine = create_engine(f"sqlite:///{db_url.removeprefix('sqlite:///')}")
    with Session(engine) as session:
        result = session.query(Trace).count(), session.query(Issue).count()
    engine.dispose()
    return result


def test_demo_seeds_traces_and_issues(tmp_path: Path) -> None:
    db_url = f"sqlite:///{tmp_path / 'demo.db'}"

    result = _run_cli("demo", db_url=db_url)

    assert result.returncode == 0
    assert "Seeded 6 demo trace(s)" in result.stdout
    assert _counts(db_url) == (6, 2)


def test_demo_refuses_to_reseed_when_already_present(tmp_path: Path) -> None:
    db_url = f"sqlite:///{tmp_path / 'demo.db'}"
    _run_cli("demo", db_url=db_url)

    result = _run_cli("demo", db_url=db_url)

    assert result.returncode == 0
    assert "already loaded" in result.stdout
    assert _counts(db_url) == (6, 2)  # not doubled


def test_demo_reset_clears_seeded_data(tmp_path: Path) -> None:
    db_url = f"sqlite:///{tmp_path / 'demo.db'}"
    _run_cli("demo", db_url=db_url)

    result = _run_cli("demo", "--reset", db_url=db_url)

    assert result.returncode == 0
    assert "Removed demo data." in result.stdout
    assert _counts(db_url) == (0, 0)


def test_demo_reset_on_empty_db_is_safe(tmp_path: Path) -> None:
    db_url = f"sqlite:///{tmp_path / 'empty.db'}"

    result = _run_cli("demo", "--reset", db_url=db_url)

    assert result.returncode == 0
    assert _counts(db_url) == (0, 0)
