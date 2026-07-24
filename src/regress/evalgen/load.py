"""Parse an eval YAML file back into structured objects for `regress run`."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml


class EvalFileError(ValueError):
    """Raised when an eval YAML file is missing required fields or malformed."""


@dataclass
class LoadedCase:
    trace_id: str
    input: str
    bad_output: str


@dataclass
class LoadedAssertion:
    type: str  # "deterministic" | "judge"
    check: str | None = None
    params: dict[str, object] = field(default_factory=dict)
    rubric: str | None = None


@dataclass
class LoadedEval:
    issue_id: str
    issue_title: str
    name: str
    assertion: LoadedAssertion
    cases: list[LoadedCase]
    path: Path


def load_eval_file(path: Path) -> LoadedEval:
    try:
        raw = yaml.safe_load(path.read_text())
    except yaml.YAMLError as exc:
        raise EvalFileError(f"invalid YAML in {path}: {exc}") from exc

    if not isinstance(raw, dict):
        raise EvalFileError(f"{path} must contain a YAML mapping at the top level")

    try:
        assertion_raw = raw["assertion"]
        cases_raw = raw["cases"]
        assertion = LoadedAssertion(
            type=assertion_raw["type"],
            check=assertion_raw.get("check"),
            params=assertion_raw.get("params", {}),
            rubric=assertion_raw.get("rubric"),
        )
        cases = [
            LoadedCase(trace_id=c["trace_id"], input=c["input"], bad_output=c["bad_output"])
            for c in cases_raw
        ]
        return LoadedEval(
            issue_id=raw["issue_id"],
            issue_title=raw["issue_title"],
            name=raw["name"],
            assertion=assertion,
            cases=cases,
            path=path,
        )
    except (KeyError, TypeError) as exc:
        raise EvalFileError(f"{path} is missing a required field: {exc}") from exc
