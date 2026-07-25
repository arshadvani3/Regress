import os
import subprocess
import sys
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from regress.models import Base, Label, Message, Score, Span, Trace

SRC = str(Path(__file__).parent.parent / "src")


def _subprocess_env(db_url: str) -> dict[str, str]:
    existing_path = os.environ.get("PYTHONPATH", "")
    python_path = f"{SRC}{os.pathsep}{existing_path}" if existing_path else SRC
    return {**os.environ, "REGRESS_DB_URL": db_url, "PYTHONPATH": python_path}


def _run_cli(
    *args: str, db_url: str, stdin: str | None = None
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "regress.cli", *args],
        env=_subprocess_env(db_url),
        input=stdin,
        capture_output=True,
        text=True,
        timeout=30,
    )


def _seed_judge_scores(db_url: str, count: int, rubric: str = "Answers the question") -> None:
    sqlite_path = db_url.removeprefix("sqlite:///")
    engine = create_engine(f"sqlite:///{sqlite_path}")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        for i in range(count):
            trace_id, span_id = f"t{i}", f"s{i}"
            session.add(Trace(id=trace_id, status="ok"))
            session.add(Span(id=span_id, trace_id=trace_id, name="chat", status="ok"))
            session.add(
                Message(
                    span_id=span_id,
                    direction="output",
                    role="assistant",
                    position=0,
                    content={
                        "role": "assistant",
                        "parts": [{"type": "text", "content": f"response {i}"}],
                    },
                )
            )
            session.add(
                Score(
                    span_id=span_id,
                    source="judge",
                    name="judge_rubric",
                    value=0.7,
                    passed=True,
                    rubric=rubric,
                    reasoning="looks fine",
                )
            )
        session.commit()
    engine.dispose()


def test_calibrate_requires_label_or_report(tmp_path: Path) -> None:
    db_url = f"sqlite:///{tmp_path / 'empty.db'}"

    result = _run_cli("calibrate", db_url=db_url)

    assert result.returncode != 0
    assert "Pass --label N and/or --report" in (result.stdout + result.stderr)


def test_calibrate_label_records_labels(tmp_path: Path) -> None:
    db_url = f"sqlite:///{tmp_path / 'seeded.db'}"
    _seed_judge_scores(db_url, 3)

    result = _run_cli(
        "calibrate", "--label", "3", "--labeler", "test-labeler", db_url=db_url, stdin="y\nn\ny\n"
    )

    assert result.returncode == 0
    assert "Recorded 3 label(s)." in result.stdout

    engine = create_engine(f"sqlite:///{tmp_path / 'seeded.db'}")
    with Session(engine) as session:
        labels = session.query(Label).all()
        assert len(labels) == 3
        assert all(label.labeler == "test-labeler" for label in labels)
    engine.dispose()


def test_calibrate_label_reports_no_scores_when_none_available(tmp_path: Path) -> None:
    db_url = f"sqlite:///{tmp_path / 'empty.db'}"

    result = _run_cli("calibrate", "--label", "5", db_url=db_url, stdin="")

    assert result.returncode == 0
    assert "No unlabeled judge-sourced scores to sample from." in result.stdout


def test_calibrate_report_writes_markdown_file(tmp_path: Path) -> None:
    db_url = f"sqlite:///{tmp_path / 'seeded.db'}"
    _seed_judge_scores(db_url, 2)
    report_path = tmp_path / "report.md"

    label_result = _run_cli(
        "calibrate", "--label", "2", "--labeler", "arsh", db_url=db_url, stdin="y\ny\n"
    )
    assert label_result.returncode == 0

    result = _run_cli("calibrate", "--report", str(report_path), db_url=db_url)

    assert result.returncode == 0
    assert report_path.exists()
    content = report_path.read_text()
    assert "# Regress Calibration Report" in content
    assert "Cohen's kappa" in content


def test_calibrate_report_prints_to_stdout_when_bare_flag(tmp_path: Path) -> None:
    db_url = f"sqlite:///{tmp_path / 'seeded.db'}"
    _seed_judge_scores(db_url, 2)
    label_result = _run_cli(
        "calibrate", "--label", "2", "--labeler", "arsh", db_url=db_url, stdin="y\ny\n"
    )
    assert label_result.returncode == 0

    result = _run_cli("calibrate", "--report", db_url=db_url)

    assert result.returncode == 0
    assert "# Regress Calibration Report" in result.stdout
    assert "Cohen's kappa" in result.stdout


def test_calibrate_label_then_report_in_one_invocation(tmp_path: Path) -> None:
    db_url = f"sqlite:///{tmp_path / 'seeded.db'}"
    _seed_judge_scores(db_url, 2)
    report_path = tmp_path / "report.md"

    result = _run_cli(
        "calibrate",
        "--label",
        "2",
        "--labeler",
        "arsh",
        "--report",
        str(report_path),
        db_url=db_url,
        stdin="y\nn\n",
    )

    assert result.returncode == 0
    assert "Recorded 2 label(s)." in result.stdout
    assert report_path.exists()
