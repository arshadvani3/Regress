"""Generate and persist evals for issues: DB Issue -> GeneratedEval -> files + Eval row."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from regress.evalgen.generate import generate_eval
from regress.evalgen.write import write_eval
from regress.models import Eval, Issue, Trace

DEFAULT_EVALS_DIR = Path("evals")


@dataclass
class EvalGenOutcome:
    issue_id: str
    issue_title: str
    yaml_path: Path
    case_count: int


def _issue_traces(session: Session, issue: Issue) -> list[Trace]:
    trace_ids = [link.trace_id for link in issue.trace_links]
    if not trace_ids:
        return []
    return list(session.execute(select(Trace).where(Trace.id.in_(trace_ids))).scalars().all())


def generate_evals_for_issues(
    session: Session, issues: list[Issue], *, directory: Path = DEFAULT_EVALS_DIR
) -> list[EvalGenOutcome]:
    """Generate + write an eval for each issue, recording an `Eval` row per file.

    Issues with no cases worth generating (e.g. every member trace has empty
    input/output after sanitization) are skipped rather than writing an
    empty eval.
    """
    outcomes = []
    for issue in issues:
        traces = _issue_traces(session, issue)
        generated = generate_eval(issue, traces)
        if not generated.cases:
            continue

        yaml_path, _pytest_path = write_eval(generated, directory)
        session.add(
            Eval(
                issue_id=issue.id,
                name=generated.name,
                path=str(yaml_path),
                assertion_type=generated.assertion.type,
            )
        )
        outcomes.append(
            EvalGenOutcome(
                issue_id=issue.id,
                issue_title=issue.title,
                yaml_path=yaml_path,
                case_count=len(generated.cases),
            )
        )
    session.flush()
    return outcomes
