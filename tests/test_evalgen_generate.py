from regress.evalgen.generate import generate_eval
from regress.models import Issue, Message, Score, Span, Trace


def _make_trace(
    trace_id: str,
    span_id: str,
    user_text: str,
    output_text: str,
    *,
    score_source: str,
    score_name: str,
    rubric: str | None = None,
) -> Trace:
    trace = Trace(id=trace_id, status="ok")
    span = Span(id=span_id, trace_id=trace_id, name="chat", status="ok")
    span.messages = [
        Message(
            span_id=span_id,
            direction="input",
            role="user",
            position=0,
            content={"role": "user", "parts": [{"type": "text", "content": user_text}]},
        ),
        Message(
            span_id=span_id,
            direction="output",
            role="assistant",
            position=0,
            content={"role": "assistant", "parts": [{"type": "text", "content": output_text}]},
        ),
    ]
    span.scores = [
        Score(
            span_id=span_id,
            source=score_source,
            name=score_name,
            value=0.0,
            passed=False,
            rubric=rubric,
        )
    ]
    trace.spans = [span]
    return trace


def test_generate_eval_uses_judge_rubric_when_judge_score_present() -> None:
    issue = Issue(
        id="i1", title="Refuses refunds", description="d", state="active", centroid_vector=[1.0]
    )
    traces = [
        _make_trace(
            "t1",
            "s1",
            "Can I get a refund?",
            "I cannot help with that.",
            score_source="judge",
            score_name="judge_rubric",
            rubric="Should address the refund request.",
        )
    ]

    result = generate_eval(issue, traces)

    assert result.assertion.type == "judge"
    assert result.assertion.rubric == "Should address the refund request."
    assert len(result.cases) == 1
    assert result.cases[0].trace_id == "t1"
    assert result.cases[0].input == "Can I get a refund?"
    assert result.cases[0].bad_output == "I cannot help with that."


def test_generate_eval_uses_paramless_deterministic_check() -> None:
    issue = Issue(
        id="i2", title="Refusal pattern", description="d", state="active", centroid_vector=[1.0]
    )
    traces = [
        _make_trace(
            "t2",
            "s2",
            "What's the weather?",
            "I'm sorry, but I can't help with that.",
            score_source="deterministic",
            score_name="not_refusal",
        )
    ]

    result = generate_eval(issue, traces)

    assert result.assertion.type == "deterministic"
    assert result.assertion.check == "not_refusal"


def test_generate_eval_falls_back_when_deterministic_check_needs_params() -> None:
    issue = Issue(
        id="i3", title="Tool errors", description="d", state="active", centroid_vector=[1.0]
    )
    traces = [
        _make_trace(
            "t3",
            "s3",
            "Book a flight",
            '{"error": "malformed args"}',
            score_source="deterministic",
            score_name="tool_call_args_valid",
        )
    ]

    result = generate_eval(issue, traces)

    assert result.assertion.type == "deterministic"
    assert result.assertion.check is None


def test_generate_eval_judge_takes_priority_over_deterministic() -> None:
    issue = Issue(
        id="i4", title="Mixed failures", description="d", state="active", centroid_vector=[1.0]
    )
    traces = [
        _make_trace(
            "t4",
            "s4",
            "q1",
            "a1",
            score_source="deterministic",
            score_name="not_refusal",
        ),
        _make_trace(
            "t5",
            "s5",
            "q2",
            "a2",
            score_source="judge",
            score_name="judge_rubric",
            rubric="Some rubric.",
        ),
    ]

    result = generate_eval(issue, traces)

    assert result.assertion.type == "judge"


def test_generate_eval_sanitizes_case_content() -> None:
    issue = Issue(
        id="i5", title="Leaks email", description="d", state="active", centroid_vector=[1.0]
    )
    traces = [
        _make_trace(
            "t6",
            "s6",
            "Email me at jane@example.com",
            "Sure, I'll use jane@example.com",
            score_source="deterministic",
            score_name="not_refusal",
        )
    ]

    result = generate_eval(issue, traces)

    assert "jane@example.com" not in result.cases[0].input
    assert "jane@example.com" not in result.cases[0].bad_output
    assert "[REDACTED_EMAIL]" in result.cases[0].input
    assert "[REDACTED_EMAIL]" in result.cases[0].bad_output


def test_generate_eval_slugifies_issue_title_for_name() -> None:
    issue = Issue(
        id="i6",
        title="Refuses Refund Requests!!!",
        description="d",
        state="active",
        centroid_vector=[1.0],
    )
    traces = [
        _make_trace(
            "t7", "s7", "q", "a", score_source="deterministic", score_name="not_refusal"
        )
    ]

    result = generate_eval(issue, traces)

    assert result.name == "refuses-refund-requests-i6"


def test_generate_eval_disambiguates_same_titled_issues() -> None:
    traces = [
        _make_trace("t7", "s7", "q", "a", score_source="deterministic", score_name="not_refusal")
    ]
    issue_a = Issue(
        id="aaaaaaaa1111",
        title="Refuses refunds",
        description="d",
        state="active",
        centroid_vector=[1.0],
    )
    issue_b = Issue(
        id="bbbbbbbb2222",
        title="Refuses refunds",
        description="d",
        state="active",
        centroid_vector=[1.0],
    )

    result_a = generate_eval(issue_a, traces)
    result_b = generate_eval(issue_b, traces)

    assert result_a.name != result_b.name


def test_generate_eval_caps_cases_at_max() -> None:
    issue = Issue(
        id="i7", title="Many failures", description="d", state="active", centroid_vector=[1.0]
    )
    traces = [
        _make_trace(
            f"t{i}",
            f"s{i}",
            f"q{i}",
            f"a{i}",
            score_source="deterministic",
            score_name="not_refusal",
        )
        for i in range(10)
    ]

    result = generate_eval(issue, traces)

    assert len(result.cases) == 5


def test_generate_eval_skips_traces_with_no_usable_content() -> None:
    issue = Issue(
        id="i8", title="Empty content", description="d", state="active", centroid_vector=[1.0]
    )
    trace = Trace(id="t8", status="ok")
    span = Span(id="s8", trace_id="t8", name="chat", status="ok")
    span.scores = [
        Score(span_id="s8", source="deterministic", name="not_refusal", value=0.0, passed=False)
    ]
    trace.spans = [span]

    result = generate_eval(issue, [trace])

    assert result.cases == []


def test_generate_eval_with_no_failing_scores_defaults_to_fallback() -> None:
    issue = Issue(
        id="i9", title="No scores", description="d", state="active", centroid_vector=[1.0]
    )
    trace = Trace(id="t9", status="ok")
    span = Span(id="s9", trace_id="t9", name="chat", status="ok")
    span.messages = [
        Message(
            span_id="s9",
            direction="output",
            role="assistant",
            position=0,
            content={"role": "assistant", "parts": [{"type": "text", "content": "output"}]},
        )
    ]
    trace.spans = [span]

    result = generate_eval(issue, [trace])

    assert result.assertion.type == "deterministic"
    assert result.assertion.check is None
