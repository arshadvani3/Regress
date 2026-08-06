import asyncio
import json

import httpx
import pytest

from regress.models import Message, Span
from regress.scoring.judge import (
    JudgeClient,
    ajudge_rubric,
    judge_rubric,
)


def _span_with_output(text: str, span_id: str = "s1") -> Span:
    span = Span(id=span_id, trace_id="t1", name="chat", status="ok")
    span.messages = [
        Message(
            span_id=span_id,
            direction="output",
            role="assistant",
            position=0,
            content={"role": "assistant", "parts": [{"type": "text", "content": text}]},
        )
    ]
    return span


def _verdict(passed: bool = True, score: float = 0.9) -> str:
    return json.dumps({"passed": passed, "score": score, "reasoning": "ok"})


def _fake_response(content: str) -> httpx.Response:
    request = httpx.Request("POST", "http://example.test/v1/chat/completions")
    return httpx.Response(
        200, request=request, json={"choices": [{"message": {"content": content}}]}
    )


# --- verdict cache (sync) --------------------------------------------------


def test_sync_repeat_call_is_a_cache_hit(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"n": 0}

    def fake_post(*a: object, **kw: object) -> httpx.Response:
        calls["n"] += 1
        return _fake_response(_verdict())

    monkeypatch.setattr("regress.scoring.judge.httpx.post", fake_post)
    client = JudgeClient(api_key="sk-test")
    span = _span_with_output("Refunds take 3-5 days.")

    first = judge_rubric(span, "Mentions a timeframe.", client=client)
    second = judge_rubric(span, "Mentions a timeframe.", client=client)

    assert calls["n"] == 1  # second call served from cache
    assert (first.passed, first.value) == (second.passed, second.value)


def test_different_rubric_is_not_a_cache_hit(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"n": 0}

    def fake_post(*a: object, **kw: object) -> httpx.Response:
        calls["n"] += 1
        return _fake_response(_verdict())

    monkeypatch.setattr("regress.scoring.judge.httpx.post", fake_post)
    client = JudgeClient(api_key="sk-test")
    span = _span_with_output("Refunds take 3-5 days.")

    judge_rubric(span, "Mentions a timeframe.", client=client)
    judge_rubric(span, "Is polite.", client=client)

    assert calls["n"] == 2  # distinct prompt -> distinct network call


def test_fresh_client_starts_cold(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"n": 0}

    def fake_post(*a: object, **kw: object) -> httpx.Response:
        calls["n"] += 1
        return _fake_response(_verdict())

    monkeypatch.setattr("regress.scoring.judge.httpx.post", fake_post)
    span = _span_with_output("Refunds take 3-5 days.")

    judge_rubric(span, "Mentions a timeframe.", client=JudgeClient(api_key="sk-test"))
    judge_rubric(span, "Mentions a timeframe.", client=JudgeClient(api_key="sk-test"))

    assert calls["n"] == 2  # cache lives on the instance, not globally


# --- async parity + shared cache -------------------------------------------


def _patch_async(monkeypatch: pytest.MonkeyPatch, counter: dict[str, int]) -> None:
    async def fake_apost(self: object, *a: object, **kw: object) -> httpx.Response:
        counter["n"] += 1
        return _fake_response(_verdict())

    monkeypatch.setattr("regress.scoring.judge.httpx.AsyncClient.post", fake_apost)


def test_async_matches_sync_verdict(monkeypatch: pytest.MonkeyPatch) -> None:
    counter = {"n": 0}
    _patch_async(monkeypatch, counter)
    span = _span_with_output("Refunds take 3-5 days.")

    result = asyncio.run(
        ajudge_rubric(span, "Mentions a timeframe.", client=JudgeClient(api_key="sk-test"))
    )

    assert result.passed is True
    assert result.source == "judge"
    assert counter["n"] == 1


def test_async_then_sync_shares_one_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    async_counter = {"n": 0}
    sync_counter = {"n": 0}
    _patch_async(monkeypatch, async_counter)

    def fake_post(*a: object, **kw: object) -> httpx.Response:
        sync_counter["n"] += 1
        return _fake_response(_verdict())

    monkeypatch.setattr("regress.scoring.judge.httpx.post", fake_post)
    client = JudgeClient(api_key="sk-test")
    span = _span_with_output("Refunds take 3-5 days.")

    asyncio.run(ajudge_rubric(span, "Mentions a timeframe.", client=client))
    judge_rubric(span, "Mentions a timeframe.", client=client)  # same prompt

    assert async_counter["n"] == 1
    assert sync_counter["n"] == 0  # sync served from the async-populated cache
