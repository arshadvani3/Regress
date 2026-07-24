from datetime import UTC, datetime, timedelta

from regress.clustering import failure_text, scored_bad_traces
from regress.models import Message, Score, Span, Trace


def _message(
    span_id: str, direction: str, role: str | None, text: str, position: int = 0
) -> Message:
    return Message(
        span_id=span_id,
        direction=direction,
        role=role,
        position=position,
        content={"role": role, "parts": [{"type": "text", "content": text}]},
    )


def test_failure_text_combines_reason_last_user_msg_and_output() -> None:
    start = datetime.now(UTC)
    trace = Trace(id="t1", status="ok")
    span = Span(id="s1", trace_id="t1", name="chat", status="ok", started_at=start)
    span.messages = [
        _message("s1", "input", "user", "What's my refund status?"),
        _message("s1", "output", "assistant", "I cannot help with that."),
    ]
    span.scores = [
        Score(
            span_id="s1",
            source="deterministic",
            name="not_refusal",
            value=0.0,
            passed=False,
            reasoning="matched a refusal pattern",
        )
    ]
    trace.spans = [span]

    result = failure_text(trace)

    assert result.trace_id == "t1"
    assert "matched a refusal pattern" in result.text
    assert "What's my refund status?" in result.text
    assert "I cannot help with that." in result.text


def test_failure_text_uses_most_recent_span_by_start_time() -> None:
    start = datetime.now(UTC)
    trace = Trace(id="t1", status="ok")
    early_span = Span(id="s1", trace_id="t1", name="chat", status="ok", started_at=start)
    early_span.messages = [_message("s1", "input", "user", "first question")]
    late_span = Span(
        id="s2", trace_id="t1", name="chat", status="ok", started_at=start + timedelta(seconds=5)
    )
    late_span.messages = [_message("s2", "input", "user", "second question")]
    trace.spans = [early_span, late_span]

    result = failure_text(trace)

    assert "second question" in result.text
    assert "first question" not in result.text


def test_failure_text_handles_missing_scores_and_messages() -> None:
    trace = Trace(id="t1", status="ok")
    span = Span(id="s1", trace_id="t1", name="chat", status="ok")
    trace.spans = [span]

    result = failure_text(trace)

    assert result.trace_id == "t1"
    assert result.text == ""


def test_scored_bad_traces_filters_by_span_level_failure() -> None:
    trace_bad = Trace(id="t1", status="ok")
    span_bad = Span(id="s1", trace_id="t1", name="chat", status="ok")
    span_bad.scores = [
        Score(span_id="s1", source="deterministic", name="not_refusal", value=0.0, passed=False)
    ]
    trace_bad.spans = [span_bad]

    trace_good = Trace(id="t2", status="ok")
    span_good = Span(id="s2", trace_id="t2", name="chat", status="ok")
    span_good.scores = [
        Score(span_id="s2", source="deterministic", name="not_refusal", value=1.0, passed=True)
    ]
    trace_good.spans = [span_good]

    result = scored_bad_traces([trace_bad, trace_good])

    assert [t.id for t in result] == ["t1"]


def test_scored_bad_traces_filters_by_trace_level_failure() -> None:
    trace_bad = Trace(id="t1", status="ok")
    trace_bad.scores = [
        Score(trace_id="t1", source="human", name="thumbs", value=0.0, passed=False)
    ]

    trace_unscored = Trace(id="t2", status="ok")

    result = scored_bad_traces([trace_bad, trace_unscored])

    assert [t.id for t in result] == ["t1"]
