"""Discover and run an entire evals/ directory, with baseline tracking for --gate."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from regress.evalgen.load import EvalFileError, LoadedEval, load_eval_file
from regress.evalgen.run import (
    EvalOutcome,
    run_eval_case_against_endpoint,
    run_eval_case_against_traces,
)
from regress.scoring.judge import JudgeClient

BASELINE_FILENAME = ".regress-baseline.json"


@dataclass
class SuiteResult:
    outcomes: list[EvalOutcome] = field(default_factory=list)
    load_errors: list[str] = field(default_factory=list)

    @property
    def passed_count(self) -> int:
        return sum(1 for o in self.outcomes if o.passed)

    @property
    def total_count(self) -> int:
        return len(self.outcomes)


def discover_evals(directory: Path) -> tuple[list[LoadedEval], list[str]]:
    """Load every `*.yaml` in `directory`. Malformed files are reported, not fatal."""
    evals = []
    errors = []
    for path in sorted(directory.glob("*.yaml")):
        try:
            evals.append(load_eval_file(path))
        except EvalFileError as exc:
            errors.append(str(exc))
    return evals, errors


def run_suite(
    directory: Path,
    *,
    against: str = "traces",
    judge_client: JudgeClient | None = None,
) -> SuiteResult:
    """Run every eval in `directory`. `against` is "traces" (replay) or a
    live endpoint URL.
    """
    evals, load_errors = discover_evals(directory)
    result = SuiteResult(load_errors=load_errors)

    for loaded_eval in evals:
        for case in loaded_eval.cases:
            if against == "traces":
                outcome = run_eval_case_against_traces(loaded_eval, case)
            else:
                outcome = run_eval_case_against_endpoint(
                    loaded_eval, case, against, judge_client=judge_client
                )
            result.outcomes.append(outcome)

    return result


def load_baseline(directory: Path) -> tuple[int, int] | None:
    """(passed, total) from the last recorded run, or None if there isn't one."""
    path = directory / BASELINE_FILENAME
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
        return int(data["passed"]), int(data["total"])
    except (json.JSONDecodeError, KeyError, TypeError, ValueError):
        return None


def save_baseline(directory: Path, result: SuiteResult) -> None:
    path = directory / BASELINE_FILENAME
    path.write_text(json.dumps({"passed": result.passed_count, "total": result.total_count}))
