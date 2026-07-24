from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from regress.evalgen.orchestrate import generate_evals_for_issues
from regress.models import Base, Eval, Issue, IssueTrace, Message, Score, Span, Trace


@pytest.fixture
def session() -> Iterator[Session]:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


def _seed_issue_with_trace(session: Session, issue_id: str, trace_id: str) -> Issue:
    trace = Trace(id=trace_id, status="ok")
    span = Span(id=f"{trace_id}-s", trace_id=trace_id, name="chat", status="ok")
    span.messages = [
        Message(
            span_id=span.id,
            direction="input",
            role="user",
            position=0,
            content={"role": "user", "parts": [{"type": "text", "content": "Can I get a refund?"}]},
        ),
        Message(
            span_id=span.id,
            direction="output",
            role="assistant",
            position=0,
            content={
                "role": "assistant",
                "parts": [{"type": "text", "content": "I'm sorry, but I can't help with that."}],
            },
        ),
    ]
    span.scores = [
        Score(span_id=span.id, source="deterministic", name="not_refusal", value=0.0, passed=False)
    ]
    trace.spans = [span]
    session.add(trace)

    issue = Issue(
        id=issue_id, title="Refuses refund requests", description="d", state="active",
        centroid_vector=[1.0],
    )
    session.add(issue)
    session.commit()
    session.add(IssueTrace(issue_id=issue_id, trace_id=trace_id))
    session.commit()
    return issue


def test_generate_evals_for_issues_writes_files_and_eval_rows(
    session: Session, tmp_path: Path
) -> None:
    issue = _seed_issue_with_trace(session, "i1", "t1")

    outcomes = generate_evals_for_issues(session, [issue], directory=tmp_path)
    session.commit()

    assert len(outcomes) == 1
    assert outcomes[0].yaml_path.exists()
    assert outcomes[0].case_count == 1

    eval_rows = session.execute(select(Eval)).scalars().all()
    assert len(eval_rows) == 1
    assert eval_rows[0].issue_id == "i1"
    assert eval_rows[0].assertion_type == "deterministic"


def test_generate_evals_for_issues_skips_issue_with_no_member_traces(
    session: Session, tmp_path: Path
) -> None:
    issue = Issue(
        id="i2", title="Orphan issue", description="d", state="active", centroid_vector=[1.0]
    )
    session.add(issue)
    session.commit()

    outcomes = generate_evals_for_issues(session, [issue], directory=tmp_path)

    assert outcomes == []
    assert session.execute(select(Eval)).scalars().all() == []


def test_generate_evals_for_issues_handles_multiple_issues(
    session: Session, tmp_path: Path
) -> None:
    issue1 = _seed_issue_with_trace(session, "i3", "t3")
    issue2 = _seed_issue_with_trace(session, "i4", "t4")

    outcomes = generate_evals_for_issues(session, [issue1, issue2], directory=tmp_path)

    assert len(outcomes) == 2
    assert len(list(tmp_path.glob("*.yaml"))) == 2
