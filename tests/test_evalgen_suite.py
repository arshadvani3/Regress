from pathlib import Path

from regress.evalgen.generate import EvalAssertion, EvalCase, GeneratedEval
from regress.evalgen.suite import discover_evals, load_baseline, run_suite, save_baseline
from regress.evalgen.write import write_eval


def _write(directory: Path, name: str, bad_output: str) -> None:
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


def test_discover_evals_finds_all_yaml_files(tmp_path: Path) -> None:
    _write(tmp_path, "issue-a", "I can't help.")
    _write(tmp_path, "issue-b", "normal response")

    evals, errors = discover_evals(tmp_path)

    assert errors == []
    assert {e.name for e in evals} == {"issue-a", "issue-b"}


def test_discover_evals_reports_malformed_files_without_failing(tmp_path: Path) -> None:
    _write(tmp_path, "issue-a", "I can't help.")
    (tmp_path / "broken.yaml").write_text("not: a valid\n  eval: file: at all")

    evals, errors = discover_evals(tmp_path)

    assert len(evals) == 1
    assert len(errors) == 1


def test_discover_evals_empty_directory(tmp_path: Path) -> None:
    evals, errors = discover_evals(tmp_path)

    assert evals == []
    assert errors == []


def test_run_suite_replays_all_cases_by_default(tmp_path: Path) -> None:
    _write(tmp_path, "issue-a", "I'm sorry, but I can't help with that.")
    _write(tmp_path, "issue-b", "a perfectly normal response")

    result = run_suite(tmp_path)

    assert result.total_count == 2
    assert result.passed_count == 1


def test_run_suite_reports_load_errors(tmp_path: Path) -> None:
    _write(tmp_path, "issue-a", "normal")
    (tmp_path / "broken.yaml").write_text("cases: [\n  unclosed")

    result = run_suite(tmp_path)

    assert result.total_count == 1
    assert len(result.load_errors) == 1


def test_load_baseline_returns_none_when_missing(tmp_path: Path) -> None:
    assert load_baseline(tmp_path) is None


def test_save_and_load_baseline_round_trips(tmp_path: Path) -> None:
    _write(tmp_path, "issue-a", "normal response")
    result = run_suite(tmp_path)

    save_baseline(tmp_path, result)

    assert load_baseline(tmp_path) == (result.passed_count, result.total_count)


def test_load_baseline_returns_none_on_corrupt_file(tmp_path: Path) -> None:
    (tmp_path / ".regress-baseline.json").write_text("not valid json{{{")

    assert load_baseline(tmp_path) is None
