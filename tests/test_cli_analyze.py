import os
import subprocess
import sys
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from regress.models import Base, Issue, IssueTrace, Message, Score, Span, Trace

SRC = str(Path(__file__).parent.parent / "src")


def _subprocess_env(db_url: str) -> dict[str, str]:
    existing_path = os.environ.get("PYTHONPATH", "")
    python_path = f"{SRC}{os.pathsep}{existing_path}" if existing_path else SRC
    env = {**os.environ, "REGRESS_DB_URL": db_url, "PYTHONPATH": python_path}
    env.pop("OPENAI_API_KEY", None)
    env.pop("REGRESS_JUDGE_API_KEY", None)
    return env


def _run_cli(*args: str, db_url: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "regress.cli", *args],
        env=_subprocess_env(db_url),
        capture_output=True,
        text=True,
        timeout=30,
    )


def _engine(db_url: str) -> Engine:
    sqlite_path = db_url.removeprefix("sqlite:///")
    engine = create_engine(f"sqlite:///{sqlite_path}")
    Base.metadata.create_all(engine)
    return engine


def _seed_unscored_span(db_url: str, trace_id: str, text: str) -> None:
    engine = _engine(db_url)
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
        session.commit()
    engine.dispose()


def _seed_active_issue_with_scored_trace(db_url: str) -> None:
    """An issue that already exists (as if clustering ran previously), with
    a scored-bad trace linked to it -- lets evalgen be exercised without
    depending on the real embedding model / HDBSCAN clustering succeeding.
    """
    engine = _engine(db_url)
    with Session(engine) as session:
        session.add(Trace(id="t-issue", status="ok"))
        session.add(Span(id="s-issue", trace_id="t-issue", name="chat", status="ok"))
        session.add(
            Message(
                span_id="s-issue",
                direction="input",
                role="user",
                position=0,
                content={"role": "user", "parts": [{"type": "text", "content": "help me"}]},
            )
        )
        session.add(
            Message(
                span_id="s-issue",
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
                span_id="s-issue",
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
                state="active",
                centroid_vector=[1.0],
            )
        )
        session.commit()
        session.add(IssueTrace(issue_id="i1", trace_id="t-issue"))
        session.commit()
    engine.dispose()


def test_analyze_reports_no_checks_configured_with_broken_config(tmp_path: Path) -> None:
    db_url = f"sqlite:///{tmp_path / 'empty.db'}"
    config_path = tmp_path / "regress.yaml"
    config_path.write_text("checks:\n  - check: not_a_real_check\n")

    result = _run_cli("analyze", "--config", str(config_path), db_url=db_url)

    assert result.returncode != 0
    assert "unknown deterministic check" in (result.stdout + result.stderr)


def test_analyze_scores_then_reports_nothing_to_cluster_below_min_size(
    tmp_path: Path,
) -> None:
    db_url = f"sqlite:///{tmp_path / 'seeded.db'}"
    _seed_unscored_span(db_url, "t1", "I'm sorry, but I can't help with that.")

    result = _run_cli("analyze", "--min-cluster-size", "3", db_url=db_url)

    assert result.returncode == 0
    assert "Scored 1 span(s) against 1 check(s): 1 score(s), 1 failing." in result.stdout
    assert "Clustered: only 1 scored-bad trace(s) found" in result.stdout


def test_analyze_reports_nothing_new_to_score_when_all_spans_scored(
    tmp_path: Path,
) -> None:
    db_url = f"sqlite:///{tmp_path / 'seeded.db'}"
    _seed_active_issue_with_scored_trace(db_url)

    result = _run_cli(
        "analyze", "--min-cluster-size", "3", "--dir", str(tmp_path / "evals"), db_url=db_url
    )

    assert result.returncode == 0
    assert "Scored 0 span(s) (nothing new to score)." in result.stdout


def test_analyze_generates_evals_for_preexisting_active_issue(tmp_path: Path) -> None:
    db_url = f"sqlite:///{tmp_path / 'seeded.db'}"
    _seed_active_issue_with_scored_trace(db_url)
    evals_dir = tmp_path / "evals"

    result = _run_cli(
        "analyze", "--min-cluster-size", "3", "--dir", str(evals_dir), db_url=db_url
    )

    assert result.returncode == 0
    assert "Generated 1 eval(s)" in result.stdout
    assert "Refuses to help" in result.stdout
    assert evals_dir.exists()
    assert len(list(evals_dir.glob("*.yaml"))) == 1


def test_analyze_reports_no_active_issues_when_none_exist(tmp_path: Path) -> None:
    db_url = f"sqlite:///{tmp_path / 'empty.db'}"

    result = _run_cli("analyze", db_url=db_url)

    assert result.returncode == 0
    assert "Evals: no active issues to generate from." in result.stdout
