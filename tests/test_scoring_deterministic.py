from datetime import UTC, datetime, timedelta

from regress.models import Message, Span
from regress.scoring.deterministic import (
    cost_under,
    exact_match,
    json_schema_valid,
    latency_under,
    not_refusal,
    regex_match,
    tool_call_args_valid,
)


def _span_with_output(text: str, **overrides: object) -> Span:
    span = Span(id="s1", trace_id="t1", name="chat", status="ok", **overrides)  # type: ignore[arg-type]
    span.messages = [
        Message(
            span_id="s1",
            direction="output",
            role="assistant",
            position=0,
            content={"role": "assistant", "parts": [{"type": "text", "content": text}]},
        )
    ]
    return span


def test_json_schema_valid_passes_on_matching_payload() -> None:
    span = _span_with_output('{"answer": 42}')
    schema = {
        "type": "object",
        "properties": {"answer": {"type": "integer"}},
        "required": ["answer"],
    }

    result = json_schema_valid(span, schema)

    assert result.passed is True
    assert result.value == 1.0
    assert result.source == "deterministic"


def test_json_schema_valid_fails_on_bad_type() -> None:
    span = _span_with_output('{"answer": "not a number"}')
    schema = {"type": "object", "properties": {"answer": {"type": "integer"}}}

    result = json_schema_valid(span, schema)

    assert result.passed is False
    assert result.value == 0.0
    assert result.reasoning is not None


def test_json_schema_valid_fails_on_unparseable_json() -> None:
    span = _span_with_output("not json at all")

    result = json_schema_valid(span, {"type": "object"})

    assert result.passed is False


def test_regex_match() -> None:
    span = _span_with_output("Your order #12345 ships tomorrow.")

    assert regex_match(span, r"#\d+").passed is True
    assert regex_match(span, r"refund").passed is False


def test_exact_match() -> None:
    span = _span_with_output("exact text")

    assert exact_match(span, "exact text").passed is True
    assert exact_match(span, "different text").passed is False


def test_tool_call_args_valid_passes_when_tool_not_called() -> None:
    span = _span_with_output("no tool calls here")

    result = tool_call_args_valid(span, "get_weather", {"type": "object"})

    assert result.passed is True


def test_tool_call_args_valid_checks_matching_calls() -> None:
    span = Span(id="s1", trace_id="t1", name="chat", status="ok")
    span.messages = [
        Message(
            span_id="s1",
            direction="output",
            role="assistant",
            position=0,
            content={
                "role": "assistant",
                "parts": [
                    {"type": "tool_call", "name": "get_weather", "arguments": {"city": "SF"}}
                ],
            },
        )
    ]
    schema = {
        "type": "object",
        "properties": {"city": {"type": "string"}},
        "required": ["city"],
    }

    assert tool_call_args_valid(span, "get_weather", schema).passed is True

    bad_schema = {"type": "object", "properties": {"city": {"type": "integer"}}}
    result = tool_call_args_valid(span, "get_weather", bad_schema)
    assert result.passed is False
    assert result.reasoning is not None


def test_latency_under_passes_and_fails() -> None:
    start = datetime.now(UTC)
    fast = _span_with_output("hi", started_at=start, ended_at=start + timedelta(milliseconds=100))
    slow = _span_with_output("hi", started_at=start, ended_at=start + timedelta(seconds=5))

    assert latency_under(fast, 500).passed is True
    assert latency_under(slow, 500).passed is False


def test_latency_under_fails_closed_when_timestamps_missing() -> None:
    span = _span_with_output("hi")

    result = latency_under(span, 500)

    assert result.passed is False
    assert result.reasoning is not None


def test_cost_under() -> None:
    cheap = _span_with_output("hi", input_tokens=10, output_tokens=10)
    expensive = _span_with_output("hi", input_tokens=1_000_000, output_tokens=1_000_000)

    assert cost_under(cheap, 1.0, cost_per_1k_tokens=0.002).passed is True
    assert cost_under(expensive, 1.0, cost_per_1k_tokens=0.002).passed is False


def test_not_refusal_passes_on_normal_response() -> None:
    span = _span_with_output("Your refund will arrive in 3-5 business days.")

    result = not_refusal(span)

    assert result.passed is True
    assert result.value == 1.0


def test_not_refusal_detects_common_refusal_phrasing() -> None:
    span = _span_with_output("I'm sorry, but I can't help with that request.")

    result = not_refusal(span)

    assert result.passed is False
    assert result.value == 0.0
    assert result.reasoning is not None


def test_checks_accept_custom_name() -> None:
    span = _span_with_output("hello")

    result = exact_match(span, "hello", name="greeting_check")

    assert result.name == "greeting_check"
