"""Generate golden OTLP fixture payloads for tests.

Builds realistic ExportTraceServiceRequest messages using the real
opentelemetry-proto types (not hand-rolled JSON), covering a two-span
trace: an invoke_agent parent and a chat child span with GenAI-convention
attributes, tool-call messages, token usage, and one errored span. Run
this script to regenerate the fixtures under tests/fixtures/.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from google.protobuf.json_format import MessageToJson
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest
from opentelemetry.proto.common.v1.common_pb2 import AnyValue, KeyValue
from opentelemetry.proto.trace.v1.trace_pb2 import ResourceSpans, ScopeSpans, Span, Status

FIXTURES_DIR = Path(__file__).parent

TRACE_ID = bytes.fromhex("0af7651916cd43dd8448eb211c80319c")
PARENT_SPAN_ID = bytes.fromhex("b7ad6b7169203331")
CHAT_SPAN_ID = bytes.fromhex("00f067aa0ba902b7")

ERROR_TRACE_ID = bytes.fromhex("1bf7651916cd43dd8448eb211c80319d")
ERROR_SPAN_ID = bytes.fromhex("11f067aa0ba902b8")


def _kv(key: str, value: object) -> KeyValue:
    kv = KeyValue()
    kv.key = key
    av = AnyValue()
    if isinstance(value, bool):
        av.bool_value = value
    elif isinstance(value, int):
        av.int_value = value
    elif isinstance(value, float):
        av.double_value = value
    elif isinstance(value, str):
        av.string_value = value
    else:
        raise TypeError(f"unsupported fixture attribute type: {type(value)}")
    kv.value.CopyFrom(av)
    return kv


def _now_ns(offset_seconds: float = 0.0) -> int:
    return int((time.time() + offset_seconds) * 1e9)


def build_success_request() -> ExportTraceServiceRequest:
    request = ExportTraceServiceRequest()
    resource_spans = ResourceSpans()
    resource_spans.resource.attributes.append(_kv("service.name", "quickstart-demo"))

    scope_spans = ScopeSpans()
    scope_spans.scope.name = "regress.instrument"

    start = _now_ns(-2.0)
    end = _now_ns(0.0)

    parent = Span()
    parent.trace_id = TRACE_ID
    parent.span_id = PARENT_SPAN_ID
    parent.name = "invoke_agent support-triage"
    parent.kind = Span.SpanKind.SPAN_KIND_INTERNAL
    parent.start_time_unix_nano = start
    parent.end_time_unix_nano = end
    parent.attributes.append(_kv("gen_ai.operation.name", "invoke_agent"))
    parent.status.code = Status.StatusCode.STATUS_CODE_OK

    input_messages = json.dumps(
        [
            {"role": "user", "parts": [{"type": "text", "content": "What's my order status?"}]},
        ]
    )
    output_messages = json.dumps(
        [
            {
                "role": "assistant",
                "parts": [{"type": "text", "content": "Your order ships tomorrow."}],
                "finish_reason": "stop",
            }
        ]
    )

    chat = Span()
    chat.trace_id = TRACE_ID
    chat.span_id = CHAT_SPAN_ID
    chat.parent_span_id = PARENT_SPAN_ID
    chat.name = "chat claude-sonnet-5"
    chat.kind = Span.SpanKind.SPAN_KIND_CLIENT
    chat.start_time_unix_nano = start
    chat.end_time_unix_nano = end
    chat.status.code = Status.StatusCode.STATUS_CODE_OK
    for kv in (
        _kv("gen_ai.operation.name", "chat"),
        _kv("gen_ai.provider.name", "anthropic"),
        _kv("gen_ai.request.model", "claude-sonnet-5"),
        _kv("gen_ai.response.model", "claude-sonnet-5-20260115"),
        _kv("gen_ai.usage.input_tokens", 42),
        _kv("gen_ai.usage.output_tokens", 18),
        _kv("gen_ai.input.messages", input_messages),
        _kv("gen_ai.output.messages", output_messages),
    ):
        chat.attributes.append(kv)

    scope_spans.spans.append(parent)
    scope_spans.spans.append(chat)
    resource_spans.scope_spans.append(scope_spans)
    request.resource_spans.append(resource_spans)
    return request


def build_error_request() -> ExportTraceServiceRequest:
    request = ExportTraceServiceRequest()
    resource_spans = ResourceSpans()
    resource_spans.resource.attributes.append(_kv("service.name", "quickstart-demo"))

    scope_spans = ScopeSpans()
    scope_spans.scope.name = "regress.instrument"

    start = _now_ns(-1.0)
    end = _now_ns(0.0)

    span = Span()
    span.trace_id = ERROR_TRACE_ID
    span.span_id = ERROR_SPAN_ID
    span.name = "chat gpt-4"
    span.kind = Span.SpanKind.SPAN_KIND_CLIENT
    span.start_time_unix_nano = start
    span.end_time_unix_nano = end
    span.status.code = Status.StatusCode.STATUS_CODE_ERROR
    span.status.message = "rate limit exceeded"
    for kv in (
        _kv("gen_ai.operation.name", "chat"),
        _kv("gen_ai.provider.name", "openai"),
        _kv("gen_ai.request.model", "gpt-4"),
        _kv("error.type", "rate_limit_error"),
    ):
        span.attributes.append(kv)

    scope_spans.spans.append(span)
    resource_spans.scope_spans.append(scope_spans)
    request.resource_spans.append(resource_spans)
    return request


def main() -> None:
    success = build_success_request()
    error = build_error_request()

    (FIXTURES_DIR / "chat_trace.pb").write_bytes(success.SerializeToString())
    (FIXTURES_DIR / "chat_trace.json").write_text(MessageToJson(success))
    (FIXTURES_DIR / "error_trace.pb").write_bytes(error.SerializeToString())
    (FIXTURES_DIR / "error_trace.json").write_text(MessageToJson(error))
    print("Wrote fixtures to", FIXTURES_DIR)


if __name__ == "__main__":
    main()
