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
    async def raise_connect_error(self: object, *a: object, **kw: object) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr("regress.scoring.judge.httpx.AsyncClient.post", raise_connect_error)
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


def _judge_config() -> RegressConfig:
    return RegressConfig(
        checks=[
            CheckConfig(
                check="judge_rubric", name="helpful", params={"rubric": "x"}, tier="judge"
            )
        ]
    )


def _fake_ok_response() -> httpx.Response:
    import json

    request = httpx.Request("POST", "http://example.test/v1/chat/completions")
    verdict = json.dumps({"passed": True, "score": 0.9, "reasoning": "ok"})
    return httpx.Response(
        200, request=request, json={"choices": [{"message": {"content": verdict}}]}
    )


def test_score_spans_judges_spans_concurrently(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Many judge calls should overlap, not run one-at-a-time."""
    import asyncio

    state = {"in_flight": 0, "peak": 0}

    async def fake_apost(self: object, *a: object, **kw: object) -> httpx.Response:
        state["in_flight"] += 1
        state["peak"] = max(state["peak"], state["in_flight"])
        await asyncio.sleep(0.02)  # hold the slot so overlap is observable
        state["in_flight"] -= 1
        return _fake_ok_response()

    monkeypatch.setattr("regress.scoring.judge.httpx.AsyncClient.post", fake_apost)

    # 6 distinct spans (distinct text -> distinct cache keys -> 6 real calls)
    spans = [_make_span(session, f"s{i}", f"response number {i}") for i in range(6)]
    client = JudgeClient(api_key="sk-test", max_concurrency=4)

    rows = score_spans(session, spans, _judge_config(), judge_client=client)

    assert len(rows) == 6
    assert state["peak"] > 1  # actually concurrent, not sequential
    assert state["peak"] <= 4  # but bounded by max_concurrency


def test_score_spans_async_error_isolation(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A judge failure on one span is reported and skipped, not fatal, on the
    concurrent path too."""

    async def raise_connect_error(self: object, *a: object, **kw: object) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr("regress.scoring.judge.httpx.AsyncClient.post", raise_connect_error)
    spans = [_make_span(session, f"s{i}", f"response number {i}") for i in range(3)]
    client = JudgeClient(api_key="sk-test")
    errors = []

    rows = score_spans(
        session,
        spans,
        _judge_config(),
        judge_client=client,
        on_error=lambda span, check, exc: errors.append(span.id),
    )

    assert rows == []
    assert sorted(errors) == ["s0", "s1", "s2"]
