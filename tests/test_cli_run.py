import json
import os
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from regress.evalgen.generate import EvalAssertion, EvalCase, GeneratedEval
from regress.evalgen.write import write_eval

SRC = str(Path(__file__).parent.parent / "src")


def _subprocess_env() -> dict[str, str]:
    existing_path = os.environ.get("PYTHONPATH", "")
    python_path = f"{SRC}{os.pathsep}{existing_path}" if existing_path else SRC
    return {**os.environ, "PYTHONPATH": python_path}


def _run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "regress.cli", *args],
        env=_subprocess_env(),
        capture_output=True,
        text=True,
        timeout=30,
    )


def _write_not_refusal_eval(directory: Path, name: str, bad_output: str) -> None:
    write_eval(
        GeneratedEval(
            issue_id=name,
            issue_title=name,
            name=name,
            assertion=EvalAssertion(type="deterministic", check="not_refusal"),
            cases=[EvalCase(trace_id=f"t-{name}", input="q", bad_output=bad_output)],
        ),
        directory,
    )


def test_run_reports_error_when_dir_missing(tmp_path: Path) -> None:
    result = _run_cli("run", str(tmp_path / "nonexistent"))

    assert result.returncode != 0
    assert "does not exist" in (result.stdout + result.stderr)


def test_run_replays_cases_against_traces_by_default(tmp_path: Path) -> None:
    evals_dir = tmp_path / "evals"
    _write_not_refusal_eval(evals_dir, "issue-a", "I'm sorry, but I can't help with that.")
    _write_not_refusal_eval(evals_dir, "issue-b", "a normal response")

    result = _run_cli("run", str(evals_dir))

    assert result.returncode == 0
    assert "1/2 case(s) passed" in result.stdout


def test_run_gate_first_run_records_baseline_without_failing(tmp_path: Path) -> None:
    evals_dir = tmp_path / "evals"
    _write_not_refusal_eval(evals_dir, "issue-a", "a normal response")

    result = _run_cli("run", str(evals_dir), "--gate")

    assert result.returncode == 0
    assert "No baseline yet" in result.stdout
    assert (evals_dir / ".regress-baseline.json").exists()


def test_run_gate_passes_when_no_significant_regression(tmp_path: Path) -> None:
    evals_dir = tmp_path / "evals"
    _write_not_refusal_eval(evals_dir, "issue-a", "a normal response")
    (evals_dir / ".regress-baseline.json").write_text(json.dumps({"passed": 1, "total": 1}))

    result = _run_cli("run", str(evals_dir), "--gate")

    assert result.returncode == 0
    assert "No significant regression" in result.stdout


class _EchoRefusalHandler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers["Content-Length"])
        self.rfile.read(length)
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"output": "I cannot help with that."}).encode())

    def log_message(self, *args: object) -> None:
        pass


def test_run_gate_fails_on_significant_regression_against_live_endpoint(
    tmp_path: Path,
) -> None:
    evals_dir = tmp_path / "evals"
    for i in range(20):
        _write_not_refusal_eval(evals_dir, f"issue-{i}", "irrelevant")
    (evals_dir / ".regress-baseline.json").write_text(json.dumps({"passed": 19, "total": 20}))

    server = HTTPServer(("127.0.0.1", 0), _EchoRefusalHandler)
    port = server.server_port
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        result = _run_cli("run", str(evals_dir), "--against", f"http://127.0.0.1:{port}", "--gate")
    finally:
        server.shutdown()
        thread.join(timeout=5)

    assert result.returncode == 1
    assert "REGRESSION" in result.stdout
