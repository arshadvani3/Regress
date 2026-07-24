from datetime import UTC, datetime, timedelta

import httpx
import pytest

from regress._otlp_export import (
    SpanData,
    build_export_request,
    export_spans,
    new_span_id,
    new_trace_id,
)
from regress.ingest import iter_spans_from_request


def _sample_span(**overrides: object) -> SpanData:
    start = datetime.now(UTC)
    defaults: dict[str, object] = {
        "name": "chat gpt-4",
        "trace_id": new_trace_id(),
        "span_id": new_span_id(),
        "parent_span_id": None,
        "started_at": start,
        "ended_at": start + timedelta(milliseconds=200),
        "status": "ok",
        "attributes": {
            "gen_ai.operation.name": "chat",
            "gen_ai.provider.name": "openai",
            "gen_ai.request.model": "gpt-4",
            "gen_ai.input.messages": [{"role": "user", "parts": [{"content": "hi"}]}],
            "gen_ai.output.messages": [{"role": "assistant", "parts": [{"content": "hello"}]}],
            "gen_ai.usage.input_tokens": 10,
            "gen_ai.usage.output_tokens": 5,
        },
    }
    defaults.update(overrides)
    return SpanData(**defaults)  # type: ignore[arg-type]


def test_new_ids_are_valid_otlp_hex_ids() -> None:
    trace_id = new_trace_id()
    span_id = new_span_id()

    assert bytes.fromhex(trace_id)
    assert len(trace_id) == 32
    assert bytes.fromhex(span_id)
    assert len(span_id) == 16


def test_build_export_request_round_trips_through_ingest_parser() -> None:
    span = _sample_span()

    request = build_export_request([span], service_name="test-app")
    parsed = iter_spans_from_request(request)

    assert len(parsed) == 1
    trace, parsed_span, messages = parsed[0]
    assert trace.app == "test-app"
    assert trace.id == span.trace_id
    assert parsed_span.gen_ai_operation_name == "chat"
    assert parsed_span.gen_ai_provider_name == "openai"
    assert parsed_span.request_model == "gpt-4"
    assert parsed_span.input_tokens == 10
    assert parsed_span.output_tokens == 5
    assert parsed_span.status == "ok"

    input_message = next(m for m in messages if m.direction == "input")
    output_message = next(m for m in messages if m.direction == "output")
    assert input_message.content == {"role": "user", "parts": [{"content": "hi"}]}
    assert output_message.content == {"role": "assistant", "parts": [{"content": "hello"}]}


def test_build_export_request_carries_parent_span_id_and_error_type() -> None:
    trace_id = new_trace_id()
    parent = _sample_span(trace_id=trace_id)
    child = _sample_span(
        trace_id=trace_id,
        parent_span_id=parent.span_id,
        status="error",
        error_type="RateLimitError",
        attributes={"gen_ai.operation.name": "chat"},
    )

    parsed = iter_spans_from_request(build_export_request([parent, child], "test-app"))

    _, parsed_parent, _ = parsed[0]
    _, parsed_child, _ = parsed[1]
    assert parsed_child.parent_span_id == parsed_parent.id
    assert parsed_child.status == "error"
    assert parsed_child.error_type == "RateLimitError"


def test_export_spans_posts_protobuf_to_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []

    def fake_post(url: str, **kwargs: object) -> httpx.Response:
        calls.append((url, kwargs))
        return httpx.Response(200)

    monkeypatch.setattr("regress._otlp_export.httpx.post", fake_post)

    export_spans([_sample_span()], endpoint="http://example.test/v1/traces")

    assert len(calls) == 1
    url, kwargs = calls[0]
    assert url == "http://example.test/v1/traces"
    assert kwargs["headers"]["content-type"] == "application/x-protobuf"


def test_export_spans_is_noop_for_empty_list(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []
    monkeypatch.setattr(
        "regress._otlp_export.httpx.post", lambda *a, **kw: calls.append((a, kw))
    )

    export_spans([])

    assert calls == []


def test_export_spans_swallows_network_errors_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    def raise_connect_error(*args: object, **kwargs: object) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr("regress._otlp_export.httpx.post", raise_connect_error)

    export_spans([_sample_span()])  # should not raise


def test_export_spans_raises_when_debug_export_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def raise_connect_error(*args: object, **kwargs: object) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr("regress._otlp_export.httpx.post", raise_connect_error)
    monkeypatch.setenv("REGRESS_DEBUG_EXPORT", "1")

    with pytest.raises(httpx.ConnectError):
        export_spans([_sample_span()])
