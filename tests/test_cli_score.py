import json
import os
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from regress.models import Base, Message, Span, Trace

SRC = str(Path(__file__).parent.parent / "src")


def _subprocess_env(
    db_url: str, *, judge_api_key: str | None = None, judge_base_url: str | None = None
) -> dict[str, str]:
    existing_path = os.environ.get("PYTHONPATH", "")
    python_path = f"{SRC}{os.pathsep}{existing_path}" if existing_path else SRC
    env = {**os.environ, "REGRESS_DB_URL": db_url, "PYTHONPATH": python_path}
    # The zero-config default only adds the built-in judge check when a key
    # is present -- strip any inherited from the host shell so these tests
    # are hermetic (no accidental real judge calls) unless a test opts in.
    env.pop("OPENAI_API_KEY", None)
    env.pop("REGRESS_JUDGE_API_KEY", None)
    env.pop("REGRESS_JUDGE_BASE_URL", None)
    if judge_api_key is not None:
        env["OPENAI_API_KEY"] = judge_api_key
    if judge_base_url is not None:
        env["REGRESS_JUDGE_BASE_URL"] = judge_base_url
    return env


def _run_cli(
    *args: str,
    db_url: str,
    judge_api_key: str | None = None,
    judge_base_url: str | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "regress.cli", *args],
        env=_subprocess_env(db_url, judge_api_key=judge_api_key, judge_base_url=judge_base_url),
        capture_output=True,
        text=True,
        timeout=30,
    )


class _FakeJudgeHandler(BaseHTTPRequestHandler):
    """A local stand-in for an OpenAI-compatible chat-completions endpoint."""

    def do_POST(self) -> None:  # noqa: N802 (BaseHTTPRequestHandler's naming convention)
        verdict = json.dumps({"passed": True, "score": 0.9, "reasoning": "looks fine"})
        body = json.dumps({"choices": [{"message": {"content": verdict}}]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:  # silence test output
        pass


class _FakeJudgeServer:
    def __init__(self) -> None:
        self.server = HTTPServer(("127.0.0.1", 0), _FakeJudgeHandler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def __enter__(self) -> str:
        self.thread.start()
        port = self.server.server_address[1]
        return f"http://127.0.0.1:{port}/v1"

    def __exit__(self, *exc: object) -> None:
        self.server.shutdown()
        self.thread.join()


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


def test_score_command_prints_notice_and_runs_judge_when_key_present(
    tmp_path: Path,
) -> None:
    db_url = f"sqlite:///{tmp_path / 'seeded.db'}"
    _seed_span(db_url, "a perfectly normal response")

    with _FakeJudgeServer() as base_url:
        result = _run_cli(
            "score", db_url=db_url, judge_api_key="sk-test", judge_base_url=base_url
        )

    assert result.returncode == 0
    assert "built-in quality check" in result.stdout
    assert "Scored 1 span(s) against 2 check(s): 2 score(s)." in result.stdout


def test_score_command_no_notice_or_judge_check_without_key(tmp_path: Path) -> None:
    db_url = f"sqlite:///{tmp_path / 'seeded.db'}"
    _seed_span(db_url, "a perfectly normal response")

    result = _run_cli("score", db_url=db_url)

    assert result.returncode == 0
    assert "built-in quality check" not in result.stdout
    assert "Scored 1 span(s) against 1 check(s): 1 score(s)." in result.stdout


def test_score_command_no_notice_with_real_config_even_with_key(tmp_path: Path) -> None:
    db_url = f"sqlite:///{tmp_path / 'seeded.db'}"
    _seed_span(db_url, "a perfectly normal response")
    config_path = tmp_path / "regress.yaml"
    config_path.write_text("checks:\n  - check: not_refusal\n")

    result = _run_cli(
        "score", "--config", str(config_path), db_url=db_url, judge_api_key="sk-test"
    )

    assert result.returncode == 0
    assert "built-in quality check" not in result.stdout
