"""`instrument()`: patch openai/anthropic clients to emit OTel GenAI spans.

Per CLAUDE.md, this is a convenience layer, not the product — the wire
format is plain OTLP/HTTP, so anyone already exporting OTel GenAI spans
(via Langfuse, the OTel SDK, etc.) doesn't need this module at all. Keep it
thin: patch the chat/messages entrypoints, build one span per call, export.
"""

from __future__ import annotations

import functools
from collections.abc import Callable
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any, TypeVar

from regress._otlp_export import SpanData, export_spans, new_span_id, new_trace_id

_F = TypeVar("_F", bound=Callable[..., Any])

# The active trace/parent-span context, so calls made inside a `@task` (or
# inside another instrumented call) are linked into the same trace instead
# of each starting a fresh one.
_current_trace_id: ContextVar[str | None] = ContextVar("_current_trace_id", default=None)
_current_span_id: ContextVar[str | None] = ContextVar("_current_span_id", default=None)
_service_name: ContextVar[str] = ContextVar("_service_name", default="regress-instrumented-app")

_PATCHED_ATTR = "_regress_instrumented"

_Extractor = Callable[[dict[str, Any]], list[dict[str, object]]]
_OutputExtractor = Callable[[Any], list[dict[str, object]]]
_ModelExtractor = Callable[[Any], "str | None"]
_UsageExtractor = Callable[[Any], "tuple[int | None, int | None]"]


def _emit(span: SpanData) -> None:
    export_spans([span], service_name=_service_name.get())


def _build_span(
    *,
    operation: str,
    provider: str,
    request_model: str | None,
    input_messages: list[dict[str, object]],
    started_at: datetime,
    ended_at: datetime,
    response: Any,
    response_model: _ModelExtractor,
    extract_output: _OutputExtractor,
    usage: _UsageExtractor,
    status: str,
    error_type: str | None,
    trace_id: str,
    span_id: str,
    parent_span_id: str | None,
) -> SpanData:
    attrs: dict[str, object] = {
        "gen_ai.operation.name": operation,
        "gen_ai.provider.name": provider,
        "gen_ai.request.model": request_model,
        "gen_ai.input.messages": input_messages,
    }
    if response is not None:
        attrs["gen_ai.response.model"] = response_model(response)
        attrs["gen_ai.output.messages"] = extract_output(response)
        input_tokens, output_tokens = usage(response)
        if input_tokens is not None:
            attrs["gen_ai.usage.input_tokens"] = input_tokens
        if output_tokens is not None:
            attrs["gen_ai.usage.output_tokens"] = output_tokens

    return SpanData(
        name=f"{operation} {request_model or provider}",
        trace_id=trace_id,
        span_id=span_id,
        parent_span_id=parent_span_id,
        started_at=started_at,
        ended_at=ended_at,
        attributes=attrs,
        status=status,
        error_type=error_type,
    )


def _extract_openai_messages(kwargs: dict[str, Any]) -> list[dict[str, object]]:
    messages = kwargs.get("messages") or []
    parsed = []
    for m in messages:
        role = m.get("role") if isinstance(m, dict) else getattr(m, "role", None)
        content = m.get("content") if isinstance(m, dict) else getattr(m, "content", None)
        parsed.append({"role": role, "parts": [{"content": content}]})
    return parsed


def _extract_openai_output(response: Any) -> list[dict[str, object]]:
    choices = getattr(response, "choices", None) or []
    output = []
    for choice in choices:
        message = getattr(choice, "message", None)
        finish_reason = getattr(choice, "finish_reason", None)
        if message is not None:
            output.append(
                {
                    "role": getattr(message, "role", "assistant"),
                    "parts": [{"content": getattr(message, "content", None)}],
                    "finish_reason": finish_reason,
                }
            )
    return output


def _extract_anthropic_messages(kwargs: dict[str, Any]) -> list[dict[str, object]]:
    messages = kwargs.get("messages") or []
    parsed = []
    for m in messages:
        role = m.get("role") if isinstance(m, dict) else getattr(m, "role", None)
        content = m.get("content") if isinstance(m, dict) else getattr(m, "content", None)
        text: object
        if isinstance(content, list):
            text = " ".join(
                block.get("text", "") if isinstance(block, dict) else str(block)
                for block in content
            )
        else:
            text = content
        parsed.append({"role": role, "parts": [{"content": text}]})
    return parsed


def _extract_anthropic_output(response: Any) -> list[dict[str, object]]:
    blocks = getattr(response, "content", None) or []
    text = " ".join(getattr(b, "text", "") for b in blocks if getattr(b, "type", None) == "text")
    role = getattr(response, "role", "assistant")
    finish_reason = getattr(response, "stop_reason", None)
    return [{"role": role, "parts": [{"content": text}], "finish_reason": finish_reason}]


def _openai_usage(response: Any) -> tuple[int | None, int | None]:
    usage = getattr(response, "usage", None)
    return getattr(usage, "prompt_tokens", None), getattr(usage, "completion_tokens", None)


def _anthropic_usage(response: Any) -> tuple[int | None, int | None]:
    usage = getattr(response, "usage", None)
    return getattr(usage, "input_tokens", None), getattr(usage, "output_tokens", None)


class _StreamAccumulator:
    """Reassembles a streamed response into the same shape a non-streamed one
    has, so a span from `stream=True` looks identical to one from a normal call
    downstream. Provider-agnostic: `_consume_chunk` folds each chunk into the
    running text / role / finish_reason / usage, and `synthetic_response`
    exposes them through the same attribute names `_extract_*`/`*_usage` read.
    """

    def __init__(self, provider: str) -> None:
        self.provider = provider
        self._text = ""
        self._role = "assistant"
        self._finish_reason: str | None = None
        self._model: str | None = None
        self._input_tokens: int | None = None
        self._output_tokens: int | None = None

    def consume(self, chunk: Any) -> None:
        if getattr(chunk, "model", None):
            self._model = chunk.model
        if self.provider == "openai":
            self._consume_openai(chunk)
        else:
            self._consume_anthropic(chunk)

    def _consume_openai(self, chunk: Any) -> None:
        for choice in getattr(chunk, "choices", None) or []:
            delta = getattr(choice, "delta", None)
            if delta is not None:
                if getattr(delta, "role", None):
                    self._role = delta.role
                if getattr(delta, "content", None):
                    self._text += delta.content
            if getattr(choice, "finish_reason", None):
                self._finish_reason = choice.finish_reason
        # Usage only arrives (in a final chunk) when the caller passes
        # stream_options={"include_usage": True}; absent otherwise.
        usage = getattr(chunk, "usage", None)
        if usage is not None:
            self._input_tokens = getattr(usage, "prompt_tokens", None)
            self._output_tokens = getattr(usage, "completion_tokens", None)

    def _consume_anthropic(self, chunk: Any) -> None:
        # Anthropic streams typed events: message_start carries role + input
        # tokens, content_block_delta carries text, message_delta carries the
        # stop_reason and cumulative output tokens.
        event_type = getattr(chunk, "type", None)
        if event_type == "message_start":
            message = getattr(chunk, "message", None)
            if message is not None:
                self._role = getattr(message, "role", self._role)
                if getattr(message, "model", None):
                    self._model = message.model
                usage = getattr(message, "usage", None)
                if usage is not None:
                    self._input_tokens = getattr(usage, "input_tokens", None)
        elif event_type == "content_block_delta":
            delta = getattr(chunk, "delta", None)
            if delta is not None and getattr(delta, "text", None):
                self._text += delta.text
        elif event_type == "message_delta":
            delta = getattr(chunk, "delta", None)
            if delta is not None and getattr(delta, "stop_reason", None):
                self._finish_reason = delta.stop_reason
            usage = getattr(chunk, "usage", None)
            if usage is not None:
                self._output_tokens = getattr(usage, "output_tokens", None)

    def output_messages(self) -> list[dict[str, object]]:
        return [
            {
                "role": self._role,
                "parts": [{"content": self._text}],
                "finish_reason": self._finish_reason,
            }
        ]

    @property
    def model(self) -> str | None:
        return self._model

    def usage(self) -> tuple[int | None, int | None]:
        return self._input_tokens, self._output_tokens


def _emit_streamed_span(
    *,
    provider: str,
    request_model: str | None,
    input_messages: list[dict[str, object]],
    started_at: datetime,
    accumulator: _StreamAccumulator,
    status: str,
    error_type: str | None,
    trace_id: str,
    span_id: str,
    parent_span_id: str | None,
) -> None:
    """Emit a span from an accumulated stream, using whatever was collected
    before the stream ended (a partial output on an early close or mid-stream
    error is better than none)."""
    attrs: dict[str, object] = {
        "gen_ai.operation.name": "chat",
        "gen_ai.provider.name": provider,
        "gen_ai.request.model": request_model,
        "gen_ai.input.messages": input_messages,
        "gen_ai.response.model": accumulator.model,
        "gen_ai.output.messages": accumulator.output_messages(),
    }
    input_tokens, output_tokens = accumulator.usage()
    if input_tokens is not None:
        attrs["gen_ai.usage.input_tokens"] = input_tokens
    if output_tokens is not None:
        attrs["gen_ai.usage.output_tokens"] = output_tokens

    _emit(
        SpanData(
            name=f"chat {request_model or provider}",
            trace_id=trace_id,
            span_id=span_id,
            parent_span_id=parent_span_id,
            started_at=started_at,
            ended_at=datetime.now(UTC),
            attributes=attrs,
            status=status,
            error_type=error_type,
        )
    )


class _SpanContext:
    """The per-call span metadata a stream proxy needs to emit its span."""

    __slots__ = (
        "provider",
        "request_model",
        "input_messages",
        "started_at",
        "trace_id",
        "span_id",
        "parent_span_id",
    )

    def __init__(
        self,
        *,
        provider: str,
        request_model: str | None,
        input_messages: list[dict[str, object]],
        started_at: datetime,
        trace_id: str,
        span_id: str,
        parent_span_id: str | None,
    ) -> None:
        self.provider = provider
        self.request_model = request_model
        self.input_messages = input_messages
        self.started_at = started_at
        self.trace_id = trace_id
        self.span_id = span_id
        self.parent_span_id = parent_span_id


class _StreamProxy:
    """Transparent wrapper around an SDK stream object.

    Delegates every attribute (`.close()`, `.response`, context-manager
    protocol, ...) to the real stream, so no caller pattern breaks -- but
    intercepts iteration to accumulate the streamed chunks and emit exactly
    one span when the stream is exhausted, closed, or errors. One span per
    call, emitted once, whichever of those ends the stream first.
    """

    def __init__(self, stream: Any, ctx: _SpanContext) -> None:
        self._regress_stream = stream
        self._regress_ctx = ctx
        self._regress_acc = _StreamAccumulator(ctx.provider)
        self._regress_emitted = False
        self._regress_status = "ok"
        self._regress_error_type: str | None = None

    def _regress_emit(self) -> None:
        if self._regress_emitted:
            return
        self._regress_emitted = True
        ctx = self._regress_ctx
        _emit_streamed_span(
            provider=ctx.provider,
            request_model=ctx.request_model,
            input_messages=ctx.input_messages,
            started_at=ctx.started_at,
            accumulator=self._regress_acc,
            status=self._regress_status,
            error_type=self._regress_error_type,
            trace_id=ctx.trace_id,
            span_id=ctx.span_id,
            parent_span_id=ctx.parent_span_id,
        )

    # --- sync iteration ---
    def __iter__(self) -> _StreamProxy:
        return self

    def __next__(self) -> Any:
        try:
            chunk = next(self._regress_stream)
        except StopIteration:
            self._regress_emit()
            raise
        except Exception as exc:
            self._regress_status, self._regress_error_type = "error", type(exc).__name__
            self._regress_emit()
            raise
        self._regress_acc.consume(chunk)
        return chunk

    # --- async iteration ---
    def __aiter__(self) -> _StreamProxy:
        return self

    async def __anext__(self) -> Any:
        try:
            chunk = await self._regress_stream.__anext__()
        except StopAsyncIteration:
            self._regress_emit()
            raise
        except Exception as exc:
            self._regress_status, self._regress_error_type = "error", type(exc).__name__
            self._regress_emit()
            raise
        self._regress_acc.consume(chunk)
        return chunk

    # --- context managers: delegate, but still emit on exit ---
    def __enter__(self) -> _StreamProxy:
        self._regress_stream.__enter__()
        return self

    def __exit__(self, *exc: Any) -> Any:
        try:
            return self._regress_stream.__exit__(*exc)
        finally:
            self._regress_emit()

    async def __aenter__(self) -> _StreamProxy:
        await self._regress_stream.__aenter__()
        return self

    async def __aexit__(self, *exc: Any) -> Any:
        try:
            return await self._regress_stream.__aexit__(*exc)
        finally:
            self._regress_emit()

    # --- everything else: delegate to the real stream ---
    def __getattr__(self, name: str) -> Any:
        # Our own attributes are set in __init__ and resolve normally, so
        # __getattr__ only fires for the wrapped stream's API. Guard the
        # private names anyway to avoid infinite recursion if one is looked
        # up before __init__ finishes.
        if name.startswith("_regress_"):
            raise AttributeError(name)
        return getattr(self._regress_stream, name)


def _wrap_sync(
    original: Callable[..., Any],
    *,
    provider: str,
    extract_input: _Extractor,
    extract_output: _OutputExtractor,
    usage: _UsageExtractor,
) -> Callable[..., Any]:
    @functools.wraps(original)
    def patched(self: Any, *args: Any, **kwargs: Any) -> Any:
        trace_id = _current_trace_id.get() or new_trace_id()
        parent_span_id = _current_span_id.get()
        span_id = new_span_id()
        started_at = datetime.now(UTC)
        status, error_type, response = "ok", None, None
        try:
            response = original(self, *args, **kwargs)
        except Exception as exc:
            status, error_type = "error", type(exc).__name__
            _emit(
                _build_span(
                    operation="chat",
                    provider=provider,
                    request_model=kwargs.get("model"),
                    input_messages=extract_input(kwargs),
                    started_at=started_at,
                    ended_at=datetime.now(UTC),
                    response=None,
                    response_model=lambda r: getattr(r, "model", None),
                    extract_output=extract_output,
                    usage=usage,
                    status=status,
                    error_type=error_type,
                    trace_id=trace_id,
                    span_id=span_id,
                    parent_span_id=parent_span_id,
                )
            )
            raise

        if kwargs.get("stream"):
            return _StreamProxy(
                response,
                _SpanContext(
                    provider=provider,
                    request_model=kwargs.get("model"),
                    input_messages=extract_input(kwargs),
                    started_at=started_at,
                    trace_id=trace_id,
                    span_id=span_id,
                    parent_span_id=parent_span_id,
                ),
            )

        _emit(
            _build_span(
                operation="chat",
                provider=provider,
                request_model=kwargs.get("model"),
                input_messages=extract_input(kwargs),
                started_at=started_at,
                ended_at=datetime.now(UTC),
                response=response,
                response_model=lambda r: getattr(r, "model", None),
                extract_output=extract_output,
                usage=usage,
                status=status,
                error_type=error_type,
                trace_id=trace_id,
                span_id=span_id,
                parent_span_id=parent_span_id,
            )
        )
        return response

    return patched


def _wrap_async(
    original: Callable[..., Any],
    *,
    provider: str,
    extract_input: _Extractor,
    extract_output: _OutputExtractor,
    usage: _UsageExtractor,
) -> Callable[..., Any]:
    @functools.wraps(original)
    async def patched(self: Any, *args: Any, **kwargs: Any) -> Any:
        trace_id = _current_trace_id.get() or new_trace_id()
        parent_span_id = _current_span_id.get()
        span_id = new_span_id()
        started_at = datetime.now(UTC)
        status, error_type, response = "ok", None, None
        try:
            response = await original(self, *args, **kwargs)
        except Exception as exc:
            status, error_type = "error", type(exc).__name__
            _emit(
                _build_span(
                    operation="chat",
                    provider=provider,
                    request_model=kwargs.get("model"),
                    input_messages=extract_input(kwargs),
                    started_at=started_at,
                    ended_at=datetime.now(UTC),
                    response=None,
                    response_model=lambda r: getattr(r, "model", None),
                    extract_output=extract_output,
                    usage=usage,
                    status=status,
                    error_type=error_type,
                    trace_id=trace_id,
                    span_id=span_id,
                    parent_span_id=parent_span_id,
                )
            )
            raise

        if kwargs.get("stream"):
            return _StreamProxy(
                response,
                _SpanContext(
                    provider=provider,
                    request_model=kwargs.get("model"),
                    input_messages=extract_input(kwargs),
                    started_at=started_at,
                    trace_id=trace_id,
                    span_id=span_id,
                    parent_span_id=parent_span_id,
                ),
            )

        _emit(
            _build_span(
                operation="chat",
                provider=provider,
                request_model=kwargs.get("model"),
                input_messages=extract_input(kwargs),
                started_at=started_at,
                ended_at=datetime.now(UTC),
                response=response,
                response_model=lambda r: getattr(r, "model", None),
                extract_output=extract_output,
                usage=usage,
                status=status,
                error_type=error_type,
                trace_id=trace_id,
                span_id=span_id,
                parent_span_id=parent_span_id,
            )
        )
        return response

    return patched


def _patch_openai() -> None:
    try:
        import openai
    except ImportError:
        return

    sync_cls = openai.resources.chat.completions.Completions
    if not getattr(sync_cls, _PATCHED_ATTR, False):
        sync_cls.create = _wrap_sync(  # type: ignore[method-assign]
            sync_cls.create,
            provider="openai",
            extract_input=_extract_openai_messages,
            extract_output=_extract_openai_output,
            usage=_openai_usage,
        )
        setattr(sync_cls, _PATCHED_ATTR, True)

    async_cls = openai.resources.chat.completions.AsyncCompletions
    if not getattr(async_cls, _PATCHED_ATTR, False):
        async_cls.create = _wrap_async(  # type: ignore[method-assign]
            async_cls.create,
            provider="openai",
            extract_input=_extract_openai_messages,
            extract_output=_extract_openai_output,
            usage=_openai_usage,
        )
        setattr(async_cls, _PATCHED_ATTR, True)


def _patch_anthropic() -> None:
    try:
        import anthropic
    except ImportError:
        return

    sync_cls = anthropic.resources.messages.Messages
    if not getattr(sync_cls, _PATCHED_ATTR, False):
        sync_cls.create = _wrap_sync(  # type: ignore[method-assign]
            sync_cls.create,
            provider="anthropic",
            extract_input=_extract_anthropic_messages,
            extract_output=_extract_anthropic_output,
            usage=_anthropic_usage,
        )
        setattr(sync_cls, _PATCHED_ATTR, True)

    async_cls = anthropic.resources.messages.AsyncMessages
    if not getattr(async_cls, _PATCHED_ATTR, False):
        async_cls.create = _wrap_async(  # type: ignore[method-assign]
            async_cls.create,
            provider="anthropic",
            extract_input=_extract_anthropic_messages,
            extract_output=_extract_anthropic_output,
            usage=_anthropic_usage,
        )
        setattr(async_cls, _PATCHED_ATTR, True)


def instrument(*, service_name: str = "regress-instrumented-app") -> None:
    """Patch installed `openai`/`anthropic` clients to emit OTel GenAI spans.

    Idempotent and safe to call even if one or both SDKs aren't installed —
    each is patched only if importable. Spans are exported to
    `REGRESS_ENDPOINT` (default `http://127.0.0.1:8990/v1/traces`).
    """
    _service_name.set(service_name)
    _patch_openai()
    _patch_anthropic()


def task(name: str | None = None) -> Callable[[_F], _F]:
    """Decorator that wraps a function call in its own span.

    Nests correctly with `instrument()`-patched SDK calls made inside it: any
    OpenAI/Anthropic call made within a `@task`-decorated function attaches
    to the task's trace as a child span.
    """

    def decorator(func: _F) -> _F:
        span_name = name or func.__name__

        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            trace_id = _current_trace_id.get() or new_trace_id()
            parent_span_id = _current_span_id.get()
            span_id = new_span_id()
            started_at = datetime.now(UTC)

            trace_token = _current_trace_id.set(trace_id)
            span_token = _current_span_id.set(span_id)
            status = "ok"
            error_type: str | None = None
            try:
                return func(*args, **kwargs)
            except Exception as exc:
                status = "error"
                error_type = type(exc).__name__
                raise
            finally:
                _current_trace_id.reset(trace_token)
                _current_span_id.reset(span_token)
                _emit(
                    SpanData(
                        name=span_name,
                        trace_id=trace_id,
                        span_id=span_id,
                        parent_span_id=parent_span_id,
                        started_at=started_at,
                        ended_at=datetime.now(UTC),
                        attributes={"gen_ai.operation.name": "invoke_agent"},
                        status=status,
                        error_type=error_type,
                    )
                )

        return wrapper  # type: ignore[return-value]

    return decorator


def current_trace_id() -> str | None:
    """The trace_id of the innermost active `@task` or instrumented SDK call, if any."""
    return _current_trace_id.get()


def feedback(trace_id: str, score: float, comment: str | None = None) -> None:
    """Attach a human feedback score to a trace.

    Emits a zero-duration span carrying `regress.feedback.*` attributes on
    the given trace. Phase 3's Scorer reads these; until then they're stored
    as ordinary span attributes via the existing ingest path.
    """
    now = datetime.now(UTC)
    _emit(
        SpanData(
            name="regress.feedback",
            trace_id=trace_id,
            span_id=new_span_id(),
            parent_span_id=None,
            started_at=now,
            ended_at=now,
            attributes={
                "gen_ai.operation.name": "feedback",
                "regress.feedback.score": score,
                "regress.feedback.comment": comment,
            },
            status="ok",
        )
    )
