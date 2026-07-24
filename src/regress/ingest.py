"""Parse OTLP/HTTP trace payloads and normalize GenAI-convention spans.

Speaks the OpenTelemetry wire protocol directly (protobuf binary and the
protobuf JSON encoding) via opentelemetry-proto, so any exporter that emits
standard OTLP/HTTP traces works here without a Regress-specific SDK -
`instrument()` is a convenience, not a requirement, per CLAUDE.md.
"""

from __future__ import annotations

from datetime import UTC, datetime

from google.protobuf.json_format import Parse
from google.protobuf.message import DecodeError
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest
from opentelemetry.proto.common.v1.common_pb2 import AnyValue, KeyValue
from opentelemetry.proto.trace.v1.trace_pb2 import Span as ProtoSpan

from regress.models import Message, Span, Trace

_STATUS_CODE_NAMES = {0: "unset", 1: "ok", 2: "error"}


class OTLPParseError(ValueError):
    """Raised when a request body is neither valid OTLP protobuf nor OTLP JSON."""


def parse_export_request(body: bytes, content_type: str) -> ExportTraceServiceRequest:
    request = ExportTraceServiceRequest()
    if "json" in content_type:
        try:
            Parse(body, request)
        except Exception as exc:
            raise OTLPParseError(f"invalid OTLP JSON payload: {exc}") from exc
    else:
        try:
            request.ParseFromString(body)
        except DecodeError as exc:
            raise OTLPParseError(f"invalid OTLP protobuf payload: {exc}") from exc
    return request


def _any_value_to_python(value: AnyValue) -> object:
    kind = value.WhichOneof("value")
    if kind is None:
        return None
    if kind == "array_value":
        return [_any_value_to_python(v) for v in value.array_value.values]
    if kind == "kvlist_value":
        return {kv.key: _any_value_to_python(kv.value) for kv in value.kvlist_value.values}
    if kind == "bytes_value":
        return value.bytes_value.hex()
    return getattr(value, kind)


def _attrs_to_dict(attributes: list[KeyValue]) -> dict[str, object]:
    return {kv.key: _any_value_to_python(kv.value) for kv in attributes}


def _hex_id(raw: bytes) -> str:
    return raw.hex()


def _nanos_to_datetime(nanos: int) -> datetime | None:
    if not nanos:
        return None
    return datetime.fromtimestamp(nanos / 1e9, tz=UTC)


def _parse_gen_ai_messages(raw: object) -> list[dict[str, object]]:
    """Parse gen_ai.input.messages / gen_ai.output.messages / gen_ai.system_instructions.

    Per the GenAI semconv, this attribute is either already structured (list of
    {role, parts: [...]}) or a JSON string when the exporter's span format
    doesn't support structured attributes.
    """
    import json

    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (TypeError, ValueError):
            return []
    if isinstance(raw, list):
        return [m for m in raw if isinstance(m, dict)]
    return []


def normalize_span(
    proto_span: ProtoSpan, resource_attrs: dict[str, object]
) -> tuple[Trace, Span, list[Message]]:
    """Convert one OTLP proto span into ORM Trace/Span/Message rows."""
    attrs = _attrs_to_dict(list(proto_span.attributes))

    trace_id = _hex_id(proto_span.trace_id)
    span_id = _hex_id(proto_span.span_id)
    parent_span_id = _hex_id(proto_span.parent_span_id) if proto_span.parent_span_id else None

    started_at = _nanos_to_datetime(proto_span.start_time_unix_nano)
    ended_at = _nanos_to_datetime(proto_span.end_time_unix_nano)
    latency_ms = None
    if proto_span.start_time_unix_nano and proto_span.end_time_unix_nano:
        latency_ms = (proto_span.end_time_unix_nano - proto_span.start_time_unix_nano) / 1e6

    status_code = _STATUS_CODE_NAMES.get(proto_span.status.code, "unset")
    error_type = attrs.get("error.type") if status_code == "error" else None

    trace = Trace(
        id=trace_id,
        root_span_id=span_id if not parent_span_id else None,
        app=resource_attrs.get("service.name"),
        started_at=started_at,
        ended_at=ended_at,
        latency_ms=latency_ms,
        status=status_code,
    )

    span = Span(
        id=span_id,
        trace_id=trace_id,
        parent_span_id=parent_span_id,
        name=proto_span.name,
        kind=(
            ProtoSpan.SpanKind.Name(proto_span.kind)
            if proto_span.kind
            else "SPAN_KIND_UNSPECIFIED"
        ),
        gen_ai_operation_name=attrs.get("gen_ai.operation.name"),
        gen_ai_provider_name=attrs.get("gen_ai.provider.name") or attrs.get("gen_ai.system"),
        request_model=attrs.get("gen_ai.request.model"),
        response_model=attrs.get("gen_ai.response.model"),
        input_tokens=attrs.get("gen_ai.usage.input_tokens"),
        output_tokens=attrs.get("gen_ai.usage.output_tokens"),
        started_at=started_at,
        ended_at=ended_at,
        status=status_code,
        error_type=error_type,
        attrs=attrs,
    )

    messages: list[Message] = []
    for direction, attr_name in (
        ("input", "gen_ai.input.messages"),
        ("output", "gen_ai.output.messages"),
        ("system", "gen_ai.system_instructions"),
    ):
        for position, raw_message in enumerate(_parse_gen_ai_messages(attrs.get(attr_name))):
            messages.append(
                Message(
                    span_id=span_id,
                    direction=direction,
                    role=raw_message.get("role"),
                    content=raw_message,
                    position=position,
                )
            )

    return trace, span, messages


def iter_spans_from_request(
    request: ExportTraceServiceRequest,
) -> list[tuple[Trace, Span, list[Message]]]:
    results: list[tuple[Trace, Span, list[Message]]] = []
    for resource_spans in request.resource_spans:
        resource_attrs = _attrs_to_dict(list(resource_spans.resource.attributes))
        for scope_spans in resource_spans.scope_spans:
            for proto_span in scope_spans.spans:
                results.append(normalize_span(proto_span, resource_attrs))
    return results
