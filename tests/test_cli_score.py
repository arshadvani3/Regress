import os
import subprocess
import sys
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from regress.models import Base, Message, Span, Trace

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


def _seed_span(db_url: str, text: str) -> None:
    sqlite_path = db_url.removeprefix("sqlite:///")
    engine = create_engine(f"sqlite:///{sqlite_path}")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(Trace(id="t1", status="ok"))
        session.add(Span(id="s1", trace_id="t1", name="chat", status="ok"))
        session.add(
            Message(
                span_id="s1",
                direction="output",
                role="assistant",
                position=0,
                content={"role": "assistant", "parts": [{"type": "text", "content": text}]},
            )
        )
        session.commit()
    engine.dispose()


def test_score_command_reports_no_spans_when_db_empty(tmp_path: Path) -> None:
    db_url = f"sqlite:///{tmp_path / 'empty.db'}"

    result = _run_cli("score", db_url=db_url)

    assert result.returncode == 0
    assert "No spans to score." in result.stdout


def test_score_command_runs_default_not_refusal_check(tmp_path: Path) -> None:
    db_url = f"sqlite:///{tmp_path / 'seeded.db'}"
    _seed_span(db_url, "a perfectly normal response")

    result = _run_cli("score", db_url=db_url)

    assert result.returncode == 0
    assert "Scored 1 span(s) against 1 check(s): 1 score(s)." in result.stdout


def test_score_command_is_idempotent_without_rescore(tmp_path: Path) -> None:
    db_url = f"sqlite:///{tmp_path / 'seeded.db'}"
    _seed_span(db_url, "a perfectly normal response")

    _run_cli("score", db_url=db_url)
    second = _run_cli("score", db_url=db_url)

    assert second.returncode == 0
    assert "No spans to score." in second.stdout


def test_score_command_rescore_flag_reruns_checks(tmp_path: Path) -> None:
    db_url = f"sqlite:///{tmp_path / 'seeded.db'}"
    _seed_span(db_url, "a perfectly normal response")

    _run_cli("score", db_url=db_url)
    second = _run_cli("score", "--rescore", db_url=db_url)

    assert second.returncode == 0
    assert "Scored 1 span(s) against 1 check(s): 1 score(s)." in second.stdout


def test_score_command_uses_custom_config(tmp_path: Path) -> None:
    db_url = f"sqlite:///{tmp_path / 'seeded.db'}"
    _seed_span(db_url, "I'm sorry, but I can't help with that.")
    config_path = tmp_path / "regress.yaml"
    config_path.write_text(
        "checks:\n  - check: not_refusal\n  - check: exact_match\n    name: greeting\n"
        "    expected: hello\n"
    )

    result = _run_cli("score", "--config", str(config_path), db_url=db_url)

    assert result.returncode == 0
    assert "Scored 1 span(s) against 2 check(s): 2 score(s)." in result.stdout


def test_score_command_reports_config_error(tmp_path: Path) -> None:
    db_url = f"sqlite:///{tmp_path / 'seeded.db'}"
    config_path = tmp_path / "regress.yaml"
    config_path.write_text("checks:\n  - check: not_a_real_check\n")

    result = _run_cli("score", "--config", str(config_path), db_url=db_url)

    assert result.returncode != 0
    assert "unknown deterministic check" in (result.stdout + result.stderr)
