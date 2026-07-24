import os
import subprocess
import sys
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from regress.models import Base, Issue, IssueTrace, Message, Score, Span, Trace

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


def _seed_issue(db_url: str, *, state: str = "active") -> None:
    sqlite_path = db_url.removeprefix("sqlite:///")
    engine = create_engine(f"sqlite:///{sqlite_path}")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(Trace(id="t1", status="ok"))
        session.add(Span(id="s1", trace_id="t1", name="chat", status="ok"))
        session.add(
            Message(
                span_id="s1",
                direction="input",
                role="user",
                position=0,
                content={"role": "user", "parts": [{"type": "text", "content": "help me"}]},
            )
        )
        session.add(
            Message(
                span_id="s1",
                direction="output",
                role="assistant",
                position=0,
                content={
                    "role": "assistant",
                    "parts": [{"type": "text", "content": "I can't help with that."}],
                },
            )
        )
        session.add(
            Score(
                span_id="s1",
                source="deterministic",
                name="not_refusal",
                value=0.0,
                passed=False,
            )
        )
        session.add(
            Issue(
                id="i1",
                title="Refuses to help",
                description="d",
                state=state,
                centroid_vector=[1.0],
            )
        )
        session.commit()
        session.add(IssueTrace(issue_id="i1", trace_id="t1"))
        session.commit()
    engine.dispose()


def test_evalgen_reports_no_issues_when_db_empty(tmp_path: Path) -> None:
    db_url = f"sqlite:///{tmp_path / 'empty.db'}"

    result = _run_cli("evalgen", "--dir", str(tmp_path / "evals"), db_url=db_url)

    assert result.returncode == 0
    assert "No issues in state 'active'" in result.stdout


def test_evalgen_generates_eval_for_active_issue(tmp_path: Path) -> None:
    db_url = f"sqlite:///{tmp_path / 'seeded.db'}"
    _seed_issue(db_url)
    evals_dir = tmp_path / "evals"

    result = _run_cli("evalgen", "--dir", str(evals_dir), db_url=db_url)

    assert result.returncode == 0
    assert "Generated 1 eval(s)" in result.stdout
    assert list(evals_dir.glob("*.yaml"))


def test_evalgen_state_filter_excludes_resolved_issues(tmp_path: Path) -> None:
    db_url = f"sqlite:///{tmp_path / 'seeded.db'}"
    _seed_issue(db_url, state="resolved")
    evals_dir = tmp_path / "evals"

    result = _run_cli("evalgen", "--dir", str(evals_dir), db_url=db_url)

    assert result.returncode == 0
    assert "No issues in state 'active'" in result.stdout


def test_evalgen_all_state_includes_resolved_issues(tmp_path: Path) -> None:
    db_url = f"sqlite:///{tmp_path / 'seeded.db'}"
    _seed_issue(db_url, state="resolved")
    evals_dir = tmp_path / "evals"

    result = _run_cli("evalgen", "--dir", str(evals_dir), "--state", "all", db_url=db_url)

    assert result.returncode == 0
    assert "Generated 1 eval(s)" in result.stdout
