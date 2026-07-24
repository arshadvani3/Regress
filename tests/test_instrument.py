from collections.abc import Iterator
from typing import Any
from unittest.mock import MagicMock

import anthropic
import openai
import pytest

import regress._instrument_sdk as sdk
from regress import current_trace_id, feedback, instrument, task
from regress._otlp_export import SpanData


@pytest.fixture(autouse=True)
def captured_spans(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[SpanData]]:
    spans: list[SpanData] = []

    def fake_export(to_export: list[SpanData], **kwargs: Any) -> None:
        spans.extend(to_export)

    monkeypatch.setattr(sdk, "export_spans", fake_export)
    yield spans


def _fake_openai_response() -> MagicMock:
    response = MagicMock()
    response.model = "gpt-4-0613"
    response.usage.prompt_tokens = 10
    response.usage.completion_tokens = 5
    choice = MagicMock()
    choice.message.role = "assistant"
    choice.message.content = "hello there"
    choice.finish_reason = "stop"
    response.choices = [choice]
    return response


def _fake_anthropic_response() -> MagicMock:
    response = MagicMock()
    response.model = "claude-sonnet-5-20260115"
    response.role = "assistant"
    response.stop_reason = "end_turn"
    response.usage.input_tokens = 12
    response.usage.output_tokens = 7
    block = MagicMock()
    block.type = "text"
    block.text = "hi there"
    response.content = [block]
    return response


def test_instrument_captures_openai_chat_completion(
    monkeypatch: pytest.MonkeyPatch, captured_spans: list[SpanData]
) -> None:
    instrument()
    fake_response = _fake_openai_response()
    monkeypatch.setattr(openai.OpenAI, "post", lambda self, *a, **kw: fake_response)

    client = openai.OpenAI(api_key="sk-fake")
    response = client.chat.completions.create(
        model="gpt-4", messages=[{"role": "user", "content": "hi"}]
    )

    assert response is fake_response
    assert len(captured_spans) == 1
    span = captured_spans[0]
    assert span.attributes["gen_ai.provider.name"] == "openai"
    assert span.attributes["gen_ai.request.model"] == "gpt-4"
    assert span.attributes["gen_ai.response.model"] == "gpt-4-0613"
    assert span.attributes["gen_ai.usage.input_tokens"] == 10
    assert span.attributes["gen_ai.usage.output_tokens"] == 5
    assert span.attributes["gen_ai.input.messages"] == [
        {"role": "user", "parts": [{"content": "hi"}]}
    ]
    assert span.status == "ok"


def test_instrument_captures_openai_error(
    monkeypatch: pytest.MonkeyPatch, captured_spans: list[SpanData]
) -> None:
    instrument()

    def raise_rate_limit(self: Any, *args: Any, **kwargs: Any) -> Any:
        raise openai.RateLimitError(
            "rate limited", response=MagicMock(status_code=429), body=None
        )

    monkeypatch.setattr(openai.OpenAI, "post", raise_rate_limit)
    client = openai.OpenAI(api_key="sk-fake")

    with pytest.raises(openai.RateLimitError):
        client.chat.completions.create(model="gpt-4", messages=[{"role": "user", "content": "hi"}])

    assert len(captured_spans) == 1
    assert captured_spans[0].status == "error"
    assert captured_spans[0].error_type == "RateLimitError"


def test_instrument_captures_anthropic_messages_create(
    monkeypatch: pytest.MonkeyPatch, captured_spans: list[SpanData]
) -> None:
    instrument()
    fake_response = _fake_anthropic_response()
    monkeypatch.setattr(anthropic.Anthropic, "post", lambda self, *a, **kw: fake_response)

    client = anthropic.Anthropic(api_key="sk-fake")
    response = client.messages.create(
        model="claude-sonnet-5", max_tokens=100, messages=[{"role": "user", "content": "hello"}]
    )

    assert response is fake_response
    assert len(captured_spans) == 1
    span = captured_spans[0]
    assert span.attributes["gen_ai.provider.name"] == "anthropic"
    assert span.attributes["gen_ai.request.model"] == "claude-sonnet-5"
    assert span.attributes["gen_ai.response.model"] == "claude-sonnet-5-20260115"
    assert span.attributes["gen_ai.usage.input_tokens"] == 12
    assert span.attributes["gen_ai.usage.output_tokens"] == 7


def test_instrument_is_idempotent(monkeypatch: pytest.MonkeyPatch) -> None:
    instrument()
    first_create = openai.resources.chat.completions.Completions.create
    instrument()
    second_create = openai.resources.chat.completions.Completions.create

    assert first_create is second_create


def test_task_decorator_wraps_function_in_a_span(captured_spans: list[SpanData]) -> None:
    @task(name="answer_question")
    def run() -> str:
        return "done"

    result = run()

    assert result == "done"
    assert len(captured_spans) == 1
    assert captured_spans[0].name == "answer_question"
    assert captured_spans[0].status == "ok"


def test_task_decorator_defaults_name_to_function_name(captured_spans: list[SpanData]) -> None:
    @task()
    def my_pipeline() -> None:
        return None

    my_pipeline()

    assert captured_spans[0].name == "my_pipeline"


def test_nested_tasks_share_trace_id_and_link_parent_span(
    captured_spans: list[SpanData],
) -> None:
    @task()
    def inner() -> None:
        return None

    @task()
    def outer() -> None:
        inner()

    outer()

    assert len(captured_spans) == 2
    inner_span = next(s for s in captured_spans if s.name == "inner")
    outer_span = next(s for s in captured_spans if s.name == "outer")
    assert inner_span.trace_id == outer_span.trace_id
    assert inner_span.parent_span_id == outer_span.span_id
    assert outer_span.parent_span_id is None


def test_task_decorator_records_error_status_and_reraises(
    captured_spans: list[SpanData],
) -> None:
    @task()
    def boom() -> None:
        raise ValueError("bad input")

    with pytest.raises(ValueError, match="bad input"):
        boom()

    assert captured_spans[0].status == "error"
    assert captured_spans[0].error_type == "ValueError"


def test_feedback_emits_span_on_given_trace_id(captured_spans: list[SpanData]) -> None:
    feedback(trace_id="abc123", score=1.0, comment="great answer")

    assert len(captured_spans) == 1
    span = captured_spans[0]
    assert span.trace_id == "abc123"
    assert span.attributes["regress.feedback.score"] == 1.0
    assert span.attributes["regress.feedback.comment"] == "great answer"
    assert span.started_at == span.ended_at


def test_feedback_without_comment(captured_spans: list[SpanData]) -> None:
    feedback(trace_id="abc123", score=0.0)

    assert captured_spans[0].attributes["regress.feedback.comment"] is None


def test_current_trace_id_is_none_outside_a_task() -> None:
    assert current_trace_id() is None


def test_current_trace_id_resolves_inside_a_task() -> None:
    seen = {}

    @task()
    def run() -> None:
        seen["trace_id"] = current_trace_id()

    run()

    assert seen["trace_id"] is not None
    assert current_trace_id() is None
