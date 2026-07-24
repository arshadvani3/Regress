from pathlib import Path

import pytest

from regress.ingest import OTLPParseError, iter_spans_from_request, parse_export_request

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.mark.parametrize(
    ("filename", "content_type"),
    [
        ("chat_trace.pb", "application/x-protobuf"),
        ("chat_trace.json", "application/json"),
    ],
)
def test_parses_chat_trace_in_both_encodings(filename: str, content_type: str) -> None:
    body = (FIXTURES / filename).read_bytes()

    request = parse_export_request(body, content_type)
    parsed = iter_spans_from_request(request)

    assert len(parsed) == 2
    trace, parent_span, parent_messages = parsed[0]
    _, chat_span, chat_messages = parsed[1]

    assert trace.app == "quickstart-demo"
    assert parent_span.gen_ai_operation_name == "invoke_agent"
    assert parent_span.parent_span_id is None

    assert chat_span.parent_span_id == parent_span.id
    assert chat_span.gen_ai_operation_name == "chat"
    assert chat_span.gen_ai_provider_name == "anthropic"
    assert chat_span.request_model == "claude-sonnet-5"
    assert chat_span.response_model == "claude-sonnet-5-20260115"
    assert chat_span.input_tokens == 42
    assert chat_span.output_tokens == 18
    assert chat_span.status == "ok"

    assert len(chat_messages) == 2
    input_message = next(m for m in chat_messages if m.direction == "input")
    output_message = next(m for m in chat_messages if m.direction == "output")
    assert input_message.role == "user"
    assert input_message.content["parts"][0]["content"] == "What's my order status?"
    assert output_message.role == "assistant"
    assert output_message.content["finish_reason"] == "stop"


@pytest.mark.parametrize(
    ("filename", "content_type"),
    [
        ("error_trace.pb", "application/x-protobuf"),
        ("error_trace.json", "application/json"),
    ],
)
def test_parses_errored_span_status_and_error_type(filename: str, content_type: str) -> None:
    body = (FIXTURES / filename).read_bytes()

    request = parse_export_request(body, content_type)
    parsed = iter_spans_from_request(request)

    assert len(parsed) == 1
    trace, span, _messages = parsed[0]

    assert trace.status == "error"
    assert span.status == "error"
    assert span.error_type == "rate_limit_error"
    assert span.gen_ai_provider_name == "openai"
    assert span.request_model == "gpt-4"


def test_invalid_protobuf_raises_otlp_parse_error() -> None:
    with pytest.raises(OTLPParseError):
        parse_export_request(b"not a valid protobuf payload!!!", "application/x-protobuf")


def test_invalid_json_raises_otlp_parse_error() -> None:
    with pytest.raises(OTLPParseError):
        parse_export_request(b"{not valid json", "application/json")


def test_two_spans_in_same_trace_share_trace_id() -> None:
    body = (FIXTURES / "chat_trace.pb").read_bytes()
    request = parse_export_request(body, "application/x-protobuf")
    parsed = iter_spans_from_request(request)

    trace_ids = {trace.id for trace, _span, _messages in parsed}
    assert len(trace_ids) == 1
