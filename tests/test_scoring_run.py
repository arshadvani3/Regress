from collections.abc import Iterator

import httpx
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from regress.config import CheckConfig, RegressConfig
from regress.models import Base, Message, Score, Span, Trace
from regress.scoring.judge import JudgeClient
from regress.scoring.run import run_check, score_spans


@pytest.fixture
def session() -> Iterator[Session]:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


def _make_span(session: Session, span_id: str, text: str) -> Span:
    trace = session.get(Trace, "t1")
    if trace is None:
        session.add(Trace(id="t1", status="ok"))
    span = Span(id=span_id, trace_id="t1", name="chat", status="ok")
    session.add(span)
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
    return session.get(Span, span_id)  # type: ignore[return-value]


def test_run_check_dispatches_deterministic_check(session: Session) -> None:
    span = _make_span(session, "s1", "a normal response")
    check = CheckConfig(check="not_refusal", name="not_refusal")

    result = run_check(span, check)

    assert result.source == "deterministic"
    assert result.passed is True


def test_run_check_dispatches_judge_check(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake_post(url: str, **kwargs: object) -> httpx.Response:
        request = httpx.Request("POST", url)
        return httpx.Response(
            200,
            request=request,
            json={
                "choices": [
                    {"message": {"content": '{"passed": true, "score": 1.0, "reasoning": "ok"}'}}
                ]
            },
        )

    monkeypatch.setattr("regress.scoring.judge.httpx.post", fake_post)
    span = _make_span(session, "s1", "a normal response")
    check = CheckConfig(
        check="judge_rubric", name="helpfulness", params={"rubric": "is it helpful?"}, tier="judge"
    )

    result = run_check(span, check, judge_client=JudgeClient(api_key="sk-test"))

    assert result.source == "judge"
    assert result.passed is True


def test_run_check_raises_on_unknown_check(session: Session) -> None:
    span = _make_span(session, "s1", "text")
    check = CheckConfig(check="totally_unknown", name="x")

    with pytest.raises(ValueError, match="unknown check"):
        run_check(span, check)


def test_score_spans_persists_score_rows(session: Session) -> None:
    span = _make_span(session, "s1", "a normal response")
    config = RegressConfig(checks=[CheckConfig(check="not_refusal", name="not_refusal")])

    rows = score_spans(session, [span], config)
    session.commit()

    assert len(rows) == 1
    stored = session.execute(select(Score)).scalars().all()
    assert len(stored) == 1
    assert stored[0].span_id == "s1"
    assert stored[0].name == "not_refusal"
    assert stored[0].source == "deterministic"


def test_score_spans_runs_multiple_checks_per_span(session: Session) -> None:
    span = _make_span(session, "s1", "a normal response")
    config = RegressConfig(
        checks=[
            CheckConfig(check="not_refusal", name="not_refusal"),
            CheckConfig(check="exact_match", name="greeting", params={"expected": "hello"}),
        ]
    )

    rows = score_spans(session, [span], config)

    assert len(rows) == 2
    names = {r.name for r in rows}
    assert names == {"not_refusal", "greeting"}


def test_score_spans_reports_judge_errors_without_aborting(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    def raise_connect_error(*args: object, **kwargs: object) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr("regress.scoring.judge.httpx.post", raise_connect_error)
    span = _make_span(session, "s1", "a normal response")
    config = RegressConfig(
        checks=[
            CheckConfig(check="not_refusal", name="not_refusal"),
            CheckConfig(
                check="judge_rubric", name="helpful", params={"rubric": "x"}, tier="judge"
            ),
        ]
    )
    errors = []

    rows = score_spans(
        session,
        [span],
        config,
        judge_client=JudgeClient(api_key="sk-test"),
        on_error=lambda span, check, exc: errors.append((span.id, check.name)),
    )

    assert len(rows) == 1
    assert rows[0].name == "not_refusal"
    assert errors == [("s1", "helpful")]
