import json

import httpx
import pytest

from regress.models import Message, Span
from regress.scoring.judge import JudgeClient, JudgeError, judge_rubric, judge_rubric_text


def _span_with_output(text: str) -> Span:
    span = Span(id="s1", trace_id="t1", name="chat", status="ok")
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


def _span_with_input_and_output(input_text: str, output_text: str) -> Span:
    span = Span(id="s1", trace_id="t1", name="chat", status="ok")
    span.messages = [
        Message(
            span_id="s1",
            direction="input",
            role="user",
            position=0,
            content={"role": "user", "parts": [{"type": "text", "content": input_text}]},
        ),
        Message(
            span_id="s1",
            direction="output",
            role="assistant",
            position=1,
            content={"role": "assistant", "parts": [{"type": "text", "content": output_text}]},
        ),
    ]
    return span


def _fake_response(content: str) -> httpx.Response:
    request = httpx.Request("POST", "http://example.test/v1/chat/completions")
    return httpx.Response(
        200, request=request, json={"choices": [{"message": {"content": content}}]}
    )


def test_judge_rubric_parses_passing_verdict(monkeypatch: pytest.MonkeyPatch) -> None:
    verdict = json.dumps({"passed": True, "score": 0.95, "reasoning": "on-topic and accurate"})
    monkeypatch.setattr(
        "regress.scoring.judge.httpx.post", lambda *a, **kw: _fake_response(verdict)
    )
    span = _span_with_output("Your refund arrives in 3-5 business days.")

    result = judge_rubric(
        span, "Mentions a specific timeframe.", client=JudgeClient(api_key="sk-test")
    )

    assert result.source == "judge"
    assert result.passed is True
    assert result.value == 0.95
    assert result.reasoning == "on-topic and accurate"
    assert result.rubric == "Mentions a specific timeframe."
    assert result.model == "gpt-4o-mini"


def test_judge_rubric_parses_failing_verdict(monkeypatch: pytest.MonkeyPatch) -> None:
    verdict = json.dumps({"passed": False, "score": 0.1, "reasoning": "off-topic"})
    monkeypatch.setattr(
        "regress.scoring.judge.httpx.post", lambda *a, **kw: _fake_response(verdict)
    )
    span = _span_with_output("I like turtles.")

    result = judge_rubric(span, "Answers the question.", client=JudgeClient(api_key="sk-test"))

    assert result.passed is False
    assert result.value == 0.1


def test_judge_rubric_raises_on_unparseable_verdict(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "regress.scoring.judge.httpx.post", lambda *a, **kw: _fake_response("not json")
    )
    span = _span_with_output("anything")

    with pytest.raises(JudgeError):
        judge_rubric(span, "rubric", client=JudgeClient(api_key="sk-test"))


def test_judge_rubric_raises_on_missing_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "regress.scoring.judge.httpx.post",
        lambda *a, **kw: _fake_response(json.dumps({"reasoning": "no passed/score fields"})),
    )
    span = _span_with_output("anything")

    with pytest.raises(JudgeError):
        judge_rubric(span, "rubric", client=JudgeClient(api_key="sk-test"))


def test_judge_client_raises_on_http_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def raise_connect_error(*args: object, **kwargs: object) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr("regress.scoring.judge.httpx.post", raise_connect_error)
    span = _span_with_output("anything")

    with pytest.raises(JudgeError):
        judge_rubric(span, "rubric", client=JudgeClient(api_key="sk-test"))


def test_judge_client_uses_env_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("REGRESS_JUDGE_API_KEY", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-from-env")

    client = JudgeClient()

    assert client.api_key == "sk-from-env"


def test_judge_client_prefers_regress_judge_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-openai")
    monkeypatch.setenv("REGRESS_JUDGE_API_KEY", "sk-regress-judge")

    client = JudgeClient()

    assert client.api_key == "sk-regress-judge"


def test_judge_client_sends_bearer_header_and_model(monkeypatch: pytest.MonkeyPatch) -> None:
    captured = {}

    def fake_post(url: str, **kwargs: object) -> httpx.Response:
        captured["url"] = url
        captured["headers"] = kwargs["headers"]
        captured["json"] = kwargs["json"]
        return _fake_response(json.dumps({"passed": True, "score": 1.0, "reasoning": "ok"}))

    monkeypatch.setattr("regress.scoring.judge.httpx.post", fake_post)
    span = _span_with_output("hello")
    client = JudgeClient(api_key="sk-test", model="custom-model", base_url="http://local:1234/v1")

    judge_rubric(span, "rubric", client=client)

    assert captured["url"] == "http://local:1234/v1/chat/completions"
    assert captured["headers"]["authorization"] == "Bearer sk-test"
    assert captured["json"]["model"] == "custom-model"


def test_judge_rubric_includes_span_input_in_prompt(monkeypatch: pytest.MonkeyPatch) -> None:
    captured = {}

    def fake_post(url: str, **kwargs: object) -> httpx.Response:
        captured["json"] = kwargs["json"]
        return _fake_response(json.dumps({"passed": True, "score": 1.0, "reasoning": "ok"}))

    monkeypatch.setattr("regress.scoring.judge.httpx.post", fake_post)
    span = _span_with_input_and_output(
        "What is the refund window?", "Refunds arrive in 3-5 business days."
    )

    judge_rubric(span, "Answers the question.", client=JudgeClient(api_key="sk-test"))

    user_message = captured["json"]["messages"][1]["content"]
    assert "What is the refund window?" in user_message
    assert "Refunds arrive in 3-5 business days." in user_message
    assert "User input:" in user_message


def test_judge_rubric_text_omits_input_section_when_not_given(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured = {}

    def fake_post(url: str, **kwargs: object) -> httpx.Response:
        captured["json"] = kwargs["json"]
        return _fake_response(json.dumps({"passed": True, "score": 1.0, "reasoning": "ok"}))

    monkeypatch.setattr("regress.scoring.judge.httpx.post", fake_post)

    judge_rubric_text("some output", "some rubric", client=JudgeClient(api_key="sk-test"))

    user_message = captured["json"]["messages"][1]["content"]
    assert "User input:" not in user_message


def test_judge_rubric_text_includes_input_section_when_given(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured = {}

    def fake_post(url: str, **kwargs: object) -> httpx.Response:
        captured["json"] = kwargs["json"]
        return _fake_response(json.dumps({"passed": True, "score": 1.0, "reasoning": "ok"}))

    monkeypatch.setattr("regress.scoring.judge.httpx.post", fake_post)

    judge_rubric_text(
        "some output",
        "some rubric",
        input_text="some question",
        client=JudgeClient(api_key="sk-test"),
    )

    user_message = captured["json"]["messages"][1]["content"]
    assert "User input:\nsome question" in user_message


def test_judge_rubric_with_output_only_span_omits_input_section(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured = {}

    def fake_post(url: str, **kwargs: object) -> httpx.Response:
        captured["json"] = kwargs["json"]
        return _fake_response(json.dumps({"passed": True, "score": 1.0, "reasoning": "ok"}))

    monkeypatch.setattr("regress.scoring.judge.httpx.post", fake_post)
    span = _span_with_output("anything")

    judge_rubric(span, "rubric", client=JudgeClient(api_key="sk-test"))

    user_message = captured["json"]["messages"][1]["content"]
    assert "User input:" not in user_message
