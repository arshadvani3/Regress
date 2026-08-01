"""Build and send OTLP/HTTP protobuf export requests.

`instrument()` needs to emit spans in exactly the wire format `regress.ingest`
already parses. Rather than depend on the full `opentelemetry-sdk` +
`opentelemetry-exporter-otlp` stack, build the `ExportTraceServiceRequest`
proto directly with `opentelemetry-proto` (already a dependency) and POST it
with `httpx` (already a dependency). Keeps `instrument()` a thin convenience
layer, per CLAUDE.md.
"""

from __future__ import annotations

import os
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import cast

import httpx
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest
from opentelemetry.proto.common.v1.common_pb2 import AnyValue, KeyValue
from opentelemetry.proto.common.v1.common_pb2 import InstrumentationScope as ProtoScope
from opentelemetry.proto.resource.v1.resource_pb2 import Resource as ProtoResource
from opentelemetry.proto.trace.v1.trace_pb2 import ResourceSpans, ScopeSpans
from opentelemetry.proto.trace.v1.trace_pb2 import Span as ProtoSpan
from opentelemetry.proto.trace.v1.trace_pb2 import Status as ProtoStatus

DEFAULT_ENDPOINT = "http://127.0.0.1:8990/v1/traces"

_STATUS_CODES = {"unset": 0, "ok": 1, "error": 2}


@dataclass
class SpanData:
    """A single span in wire-ready form, matching `regress.ingest`'s expectations."""

    name: str
    trace_id: str
    span_id: str
    parent_span_id: str | None
    started_at: datetime
    ended_at: datetime
    attributes: dict[str, object] = field(default_factory=dict)
    status: str = "ok"
    error_type: str | None = None


def new_trace_id() -> str:
    return uuid.uuid4().hex


def new_span_id() -> str:
    return uuid.uuid4().hex[:16]


def _python_to_any_value(value: object) -> AnyValue:
    any_value = AnyValue()
    if isinstance(value, bool):
        any_value.bool_value = value
    elif isinstance(value, int):
        any_value.int_value = value
    elif isinstance(value, float):
        any_value.double_value = value
    elif isinstance(value, str):
        any_value.string_value = value
    elif isinstance(value, list):
        for item in value:
            any_value.array_value.values.append(_python_to_any_value(item))
    elif isinstance(value, dict):
        # Structured dict attributes (e.g. one message in gen_ai.*.messages)
        # round-trip through kvlist_value so the ingest side sees a real dict.
        for k, v in value.items():
            any_value.kvlist_value.values.append(_key_value(k, v))
    else:
        any_value.string_value = "" if value is None else str(value)
    return any_value


def _key_value(key: str, value: object) -> KeyValue:
    kv = KeyValue()
    kv.key = key
    kv.value.CopyFrom(_python_to_any_value(value))
    return kv


def _list_to_any_value(items: list[object]) -> AnyValue:
    any_value = AnyValue()
    for item in items:
        any_value.array_value.values.append(_python_to_any_value(item))
    return any_value


def _attrs_to_kvlist(attrs: dict[str, object]) -> list[KeyValue]:
    kvs = []
    for key, value in attrs.items():
        if isinstance(value, list):
            kv = KeyValue()
            kv.key = key
            kv.value.CopyFrom(_list_to_any_value(value))
            kvs.append(kv)
        else:
            kvs.append(_key_value(key, value))
    return kvs


def build_export_request(spans: list[SpanData], service_name: str) -> ExportTraceServiceRequest:
    request = ExportTraceServiceRequest()
    resource_spans = ResourceSpans()
    resource = ProtoResource()
    resource.attributes.append(_key_value("service.name", service_name))
    resource_spans.resource.CopyFrom(resource)

    scope_spans = ScopeSpans()
    scope_spans.scope.CopyFrom(ProtoScope(name="regress.instrument"))

    for span_data in spans:
        proto_span = ProtoSpan()
        proto_span.trace_id = bytes.fromhex(span_data.trace_id)
        proto_span.span_id = bytes.fromhex(span_data.span_id)
        if span_data.parent_span_id:
            proto_span.parent_span_id = bytes.fromhex(span_data.parent_span_id)
        proto_span.name = span_data.name
        proto_span.kind = ProtoSpan.SpanKind.SPAN_KIND_CLIENT
        proto_span.start_time_unix_nano = int(span_data.started_at.timestamp() * 1e9)
        proto_span.end_time_unix_nano = int(span_data.ended_at.timestamp() * 1e9)
        status_code = cast(
            "ProtoStatus.StatusCode.ValueType", _STATUS_CODES.get(span_data.status, 0)
        )
        proto_span.status.CopyFrom(ProtoStatus(code=status_code))

        attrs = dict(span_data.attributes)
        if span_data.error_type:
            attrs["error.type"] = span_data.error_type
        proto_span.attributes.extend(_attrs_to_kvlist(attrs))

        scope_spans.spans.append(proto_span)

    resource_spans.scope_spans.append(scope_spans)
    request.resource_spans.append(resource_spans)
    return request


def export_spans(
    spans: list[SpanData],
    *,
    endpoint: str | None = None,
    service_name: str = "regress-instrumented-app",
    timeout: float = 5.0,
) -> None:
    """POST spans to a Regress (or any OTLP/HTTP) collector as protobuf.

    Best-effort: network/collector failures are swallowed so instrumentation
    never breaks the host application. Set `REGRESS_DEBUG_EXPORT=1` to raise.
    """
    if not spans:
        return
    target = endpoint or os.environ.get("REGRESS_ENDPOINT", DEFAULT_ENDPOINT)
    request = build_export_request(spans, service_name)
    headers = {"content-type": "application/x-protobuf"}
    # Same env var that guards the collector lets instrument() reach a
    # token-protected one, with no extra config to wire through.
    auth_token = os.environ.get("REGRESS_AUTH_TOKEN")
    if auth_token:
        headers["authorization"] = f"Bearer {auth_token}"
    try:
        httpx.post(
            target,
            content=request.SerializeToString(),
            headers=headers,
            timeout=timeout,
        )
    except httpx.HTTPError:
        if os.environ.get("REGRESS_DEBUG_EXPORT"):
            raise
