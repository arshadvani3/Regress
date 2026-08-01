"""Streaming capture: instrument() must reassemble a streamed response into a
span identical in shape to a non-streamed one, without breaking any caller
pattern (iteration, context manager, .close(), early close, mid-stream error).

These build fake chunk objects and drive the wrapper directly rather than
going through the real SDK's streaming transport, so no network is involved.
"""

from collections.abc import Iterator
from types import SimpleNamespace
from typing import Any

import pytest

import regress._instrument_sdk as sdk
from regress._instrument_sdk import _SpanContext, _StreamAccumulator, _StreamProxy
from regress._otlp_export import SpanData


@pytest.fixture(autouse=True)
def captured_spans(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[SpanData]]:
    spans: list[SpanData] = []
    monkeypatch.setattr(sdk, "export_spans", lambda to_export, **kw: spans.extend(to_export))
    yield spans


def _openai_chunk(
    content: str | None = None,
    *,
    role: str | None = None,
    finish_reason: str | None = None,
    model: str = "gpt-4o-mini-2024",
    usage: Any = None,
) -> SimpleNamespace:
    delta = SimpleNamespace(role=role, content=content)
    choice = SimpleNamespace(delta=delta, finish_reason=finish_reason)
    return SimpleNamespace(model=model, choices=[choice], usage=usage)


def _ctx() -> _SpanContext:
    return _SpanContext(
        provider="openai",
        request_model="gpt-4o-mini",
        input_messages=[{"role": "user", "parts": [{"content": "hi"}]}],
        started_at=sdk.datetime.now(sdk.UTC),
        trace_id="t1",
        span_id="s1",
        parent_span_id=None,
    )


def test_accumulator_reassembles_openai_deltas() -> None:
    acc = _StreamAccumulator("openai")
    acc.consume(_openai_chunk(role="assistant"))
    acc.consume(_openai_chunk("Hello"))
    acc.consume(_openai_chunk(", "))
    acc.consume(_openai_chunk("world", finish_reason="stop"))

    messages = acc.output_messages()
    assert messages == [
        {"role": "assistant", "parts": [{"content": "Hello, world"}], "finish_reason": "stop"}
    ]
    assert acc.model == "gpt-4o-mini-2024"


def test_sync_stream_yields_every_chunk_and_emits_one_span(
    captured_spans: list[SpanData],
) -> None:
    chunks = [_openai_chunk("Hel"), _openai_chunk("lo"), _openai_chunk("!", finish_reason="stop")]
    proxy = _StreamProxy(iter(chunks), _ctx())

    received = list(proxy)

    # Every chunk passed through unchanged.
    assert received == chunks
    # Exactly one span, with the reassembled output.
    assert len(captured_spans) == 1
    span = captured_spans[0]
    assert span.attributes["gen_ai.output.messages"] == [
        {"role": "assistant", "parts": [{"content": "Hello!"}], "finish_reason": "stop"}
    ]
    assert span.status == "ok"


def test_sync_stream_captures_usage_when_present(captured_spans: list[SpanData]) -> None:
    usage = SimpleNamespace(prompt_tokens=11, completion_tokens=4)
    chunks = [
        _openai_chunk("hi", finish_reason="stop"),
        _openai_chunk(usage=usage),  # final usage-only chunk
    ]
    list(_StreamProxy(iter(chunks), _ctx()))

    span = captured_spans[0]
    assert span.attributes["gen_ai.usage.input_tokens"] == 11
    assert span.attributes["gen_ai.usage.output_tokens"] == 4


def test_sync_stream_without_usage_omits_token_attrs(captured_spans: list[SpanData]) -> None:
    list(_StreamProxy(iter([_openai_chunk("hi", finish_reason="stop")]), _ctx()))

    span = captured_spans[0]
    assert "gen_ai.usage.input_tokens" not in span.attributes
    assert "gen_ai.usage.output_tokens" not in span.attributes


def test_sync_stream_emits_partial_span_on_mid_stream_error(
    captured_spans: list[SpanData],
) -> None:
    def exploding() -> Iterator[Any]:
        yield _openai_chunk("par")
        yield _openai_chunk("tial")
        raise RuntimeError("connection dropped")

    proxy = _StreamProxy(exploding(), _ctx())

    with pytest.raises(RuntimeError, match="connection dropped"):
        list(proxy)

    assert len(captured_spans) == 1
    span = captured_spans[0]
    assert span.status == "error"
    assert span.error_type == "RuntimeError"
    # The partial text collected before the error is still captured.
    assert span.attributes["gen_ai.output.messages"][0]["parts"][0]["content"] == "partial"


def test_sync_stream_emits_once_even_if_iterated_twice(
    captured_spans: list[SpanData],
) -> None:
    proxy = _StreamProxy(iter([_openai_chunk("hi", finish_reason="stop")]), _ctx())

    list(proxy)
    list(proxy)  # already exhausted; StopIteration again must not re-emit

    assert len(captured_spans) == 1


def test_context_manager_delegates_and_emits(captured_spans: list[SpanData]) -> None:
    class FakeStream:
        def __init__(self) -> None:
            self.entered = False
            self.exited = False
            self._chunks = iter([_openai_chunk("hi", finish_reason="stop")])

        def __enter__(self) -> "FakeStream":
            self.entered = True
            return self

        def __exit__(self, *exc: Any) -> None:
            self.exited = True

        def __iter__(self) -> "FakeStream":
            return self

        def __next__(self) -> Any:
            return next(self._chunks)

    fake = FakeStream()
    proxy = _StreamProxy(fake, _ctx())

    with proxy as s:
        collected = [c for c in s]

    assert fake.entered and fake.exited
    assert len(collected) == 1
    assert len(captured_spans) == 1


def test_getattr_delegates_to_wrapped_stream() -> None:
    fake = SimpleNamespace(response="the-http-response", close=lambda: "closed")
    proxy = _StreamProxy(fake, _ctx())

    assert proxy.response == "the-http-response"
    assert proxy.close() == "closed"


def test_async_stream_yields_every_chunk_and_emits_one_span(
    captured_spans: list[SpanData],
) -> None:
    # Driven via asyncio.run so it needs no pytest async plugin (the project
    # has none); still exercises the real __aiter__/__anext__ proxy path.
    import asyncio

    chunks = [_openai_chunk("as"), _openai_chunk("ync", finish_reason="stop")]

    class FakeAsyncStream:
        def __init__(self) -> None:
            self._it = iter(chunks)

        def __aiter__(self) -> "FakeAsyncStream":
            return self

        async def __anext__(self) -> Any:
            try:
                return next(self._it)
            except StopIteration:
                raise StopAsyncIteration from None

    async def drive() -> list[Any]:
        proxy = _StreamProxy(FakeAsyncStream(), _ctx())
        return [c async for c in proxy]

    received = asyncio.run(drive())

    assert received == chunks
    assert len(captured_spans) == 1
    assert captured_spans[0].attributes["gen_ai.output.messages"][0]["parts"][0][
        "content"
    ] == "async"


def test_anthropic_stream_events_reassemble() -> None:
    acc = _StreamAccumulator("anthropic")
    acc.consume(
        SimpleNamespace(
            type="message_start",
            message=SimpleNamespace(
                role="assistant",
                model="claude-x",
                usage=SimpleNamespace(input_tokens=9),
            ),
        )
    )
    acc.consume(
        SimpleNamespace(type="content_block_delta", delta=SimpleNamespace(text="Hi "))
    )
    acc.consume(
        SimpleNamespace(type="content_block_delta", delta=SimpleNamespace(text="there"))
    )
    acc.consume(
        SimpleNamespace(
            type="message_delta",
            delta=SimpleNamespace(stop_reason="end_turn"),
            usage=SimpleNamespace(output_tokens=3),
        )
    )

    messages = acc.output_messages()
    assert messages[0]["parts"][0]["content"] == "Hi there"
    assert messages[0]["finish_reason"] == "end_turn"
    assert acc.usage() == (9, 3)
    assert acc.model == "claude-x"
