"""`regress demo`: seed a self-contained sample so a brand-new user sees the
whole loop light up 30 seconds after install, without instrumenting anything.

The data is a small, obviously-fictional customer-support-bot scenario written
by hand here (so there's no real PII to sanitize and nothing to download): a
handful of failing traces, already scored, already clustered into Issues --
including one in the `regressed` state to show the headline lifecycle feature.
Everything is tagged app="demo-support-bot" so `regress demo --reset` can
remove exactly the demo rows and nothing a real user ingested.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from regress.models import Issue, IssueTrace, Message, Score, Span, Trace

DEMO_APP = "demo-support-bot"

_BASE = datetime(2026, 1, 15, 9, 0, 0, tzinfo=UTC)


@dataclass
class _DemoTrace:
    trace_id: str
    question: str
    answer: str
    rubric: str
    reasoning: str
    latency_ms: float


# Cluster 1: refuses reasonable requests.
_REFUSALS = [
    _DemoTrace(
        "demo-r1",
        "Can you help me reset my password?",
        "I'm sorry, but I can't help with that.",
        "Answers the user's question",
        "The response refuses a reasonable, answerable request.",
        420.0,
    ),
    _DemoTrace(
        "demo-r2",
        "What are your business hours?",
        "I'm not able to assist with this request.",
        "Answers the user's question",
        "Declines to answer a basic, in-scope question.",
        380.0,
    ),
    _DemoTrace(
        "demo-r3",
        "How do I update my billing address?",
        "Sorry, I can't provide that information.",
        "Answers the user's question",
        "Refuses to give routine account guidance it should know.",
        455.0,
    ),
]

# Cluster 2: confidently wrong / off-topic answers.
_WRONG_ANSWERS = [
    _DemoTrace(
        "demo-w1",
        "What's your refund window?",
        "Our refund window is 90 days from purchase.",
        "Factually correct per policy (30-day window)",
        "States 90 days; the actual policy is a 30-day refund window.",
        610.0,
    ),
    _DemoTrace(
        "demo-w2",
        "Do you ship to Canada?",
        "The Eiffel Tower is located in Paris, France.",
        "Stays on topic and answers the question asked",
        "Completely off-topic; ignores the shipping question.",
        530.0,
    ),
    _DemoTrace(
        "demo-w3",
        "Is the Pro plan monthly or annual?",
        "The Pro plan is billed weekly at $99.",
        "Factually correct per policy (monthly billing)",
        "Invents a weekly billing option that does not exist.",
        575.0,
    ),
]


def _add_trace(session: Session, dt: _DemoTrace, index: int) -> None:
    started = _BASE + timedelta(minutes=index * 3)
    ended = started + timedelta(milliseconds=dt.latency_ms)
    span_id = f"{dt.trace_id}-s"
    session.add(
        Trace(
            id=dt.trace_id,
            app=DEMO_APP,
            status="ok",
            started_at=started,
            ended_at=ended,
            latency_ms=dt.latency_ms,
        )
    )
    session.add(
        Span(
            id=span_id,
            trace_id=dt.trace_id,
            name="chat gpt-4o-mini",
            status="ok",
            gen_ai_operation_name="chat",
            gen_ai_provider_name="openai",
            request_model="gpt-4o-mini",
            response_model="gpt-4o-mini-2024",
            started_at=started,
            ended_at=ended,
        )
    )
    session.add(
        Message(
            span_id=span_id,
            direction="input",
            role="user",
            position=0,
            content={"role": "user", "parts": [{"type": "text", "content": dt.question}]},
        )
    )
    session.add(
        Message(
            span_id=span_id,
            direction="output",
            role="assistant",
            position=1,
            content={"role": "assistant", "parts": [{"type": "text", "content": dt.answer}]},
        )
    )
    session.add(
        Score(
            span_id=span_id,
            source="judge",
            name="judge_rubric",
            value=0.1,
            passed=False,
            rubric=dt.rubric,
            reasoning=dt.reasoning,
            model="gpt-4o-mini",
        )
    )


def _add_issue(
    session: Session,
    *,
    issue_id: str,
    title: str,
    description: str,
    state: str,
    traces: list[_DemoTrace],
    resolved_at: datetime | None = None,
) -> None:
    session.add(
        Issue(
            id=issue_id,
            title=title,
            description=description,
            state=state,
            centroid_vector=[0.0],  # demo data isn't re-clustered, so a stub is fine
            resolved_at=resolved_at,
        )
    )
    for dt in traces:
        session.add(IssueTrace(issue_id=issue_id, trace_id=dt.trace_id))


def demo_data_present(session: Session) -> bool:
    return session.execute(
        select(Trace.id).where(Trace.app == DEMO_APP).limit(1)
    ).first() is not None


def clear_demo_data(session: Session) -> None:
    """Remove exactly the demo rows (everything tagged DEMO_APP), leaving any
    real ingested data untouched. Cascades handle spans/messages/scores/links.
    """
    demo_issue_ids = ["demo-issue-refusals", "demo-issue-wrong"]
    for issue_id in demo_issue_ids:
        issue = session.get(Issue, issue_id)
        if issue is not None:
            session.delete(issue)
    demo_traces = session.execute(select(Trace).where(Trace.app == DEMO_APP)).scalars().all()
    for trace in demo_traces:
        session.delete(trace)
    session.flush()


def seed_demo(session: Session) -> int:
    """Insert the demo scenario. Returns the number of traces seeded."""
    all_traces = _REFUSALS + _WRONG_ANSWERS
    for i, dt in enumerate(all_traces):
        _add_trace(session, dt, i)

    _add_issue(
        session,
        issue_id="demo-issue-refusals",
        title="Refuses reasonable, answerable requests",
        description=(
            "The assistant declines routine support questions it should handle "
            "(password resets, business hours, billing address changes)."
        ),
        state="active",
        traces=_REFUSALS,
    )
    _add_issue(
        session,
        issue_id="demo-issue-wrong",
        title="Confidently wrong or off-topic answers",
        description=(
            "The assistant states incorrect policy details or answers an "
            "entirely different question than the one asked."
        ),
        state="regressed",
        traces=_WRONG_ANSWERS,
        resolved_at=_BASE - timedelta(days=2),
    )

    session.flush()
    return len(all_traces)
