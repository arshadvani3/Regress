import os
import subprocess
import sys
from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures"
SRC = str(Path(__file__).parent.parent / "src")


def _subprocess_env(db_url: str) -> dict[str, str]:
    # The editable install's .pth may be skipped by CPython's "hidden .pth
    # file" heuristic on some platforms; PYTHONPATH guarantees the child
    # process can still import regress regardless of that quirk.
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


def test_traces_command_reports_empty_before_ingest(tmp_path: Path) -> None:
    db_url = f"sqlite:///{tmp_path / 'empty.db'}"

    result = _run_cli("traces", db_url=db_url)

    assert result.returncode == 0
    assert "No traces ingested yet." in result.stdout


def test_traces_command_lists_ingested_trace(tmp_path: Path) -> None:
    db_url = f"sqlite:///{tmp_path / 'seeded.db'}"
    env = _subprocess_env(db_url)
    seed_script = Path(__file__).parent / "fixtures" / "seed_trace.py"

    subprocess.run(
        [sys.executable, str(seed_script), str(FIXTURES / "chat_trace.pb")],
        env=env,
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    )

    result = _run_cli("traces", db_url=db_url)

    assert result.returncode == 0
    assert "quickstart-demo" in result.stdout
    assert "ok" in result.stdout
