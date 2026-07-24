import json
from pathlib import Path

import httpx
import pytest

from regress.evalgen.load import LoadedAssertion, LoadedCase, LoadedEval
from regress.evalgen.run import (
    run_eval_case,
    run_eval_case_against_endpoint,
    run_eval_case_against_traces,
    score_output,
)
from regress.scoring.judge import JudgeClient


def _eval(assertion: LoadedAssertion) -> LoadedEval:
    return LoadedEval(
        issue_id="i1",
        issue_title="Issue",
        name="issue",
        assertion=assertion,
        cases=[],
        path=Path("x.yaml"),
    )


def _case(bad_output: str = "I cannot help with that.") -> LoadedCase:
    return LoadedCase(trace_id="t1", input="question", bad_output=bad_output)


def test_not_refusal_assertion_fails_on_refusal_text() -> None:
    eval_ = _eval(LoadedAssertion(type="deterministic", check="not_refusal"))

    outcome = score_output(eval_, _case(), "I'm sorry, but I can't help with that.")

    assert outcome.passed is False
    assert "refusal" in outcome.reasoning


def test_not_refusal_assertion_passes_on_normal_text() -> None:
    eval_ = _eval(LoadedAssertion(type="deterministic", check="not_refusal"))

    outcome = score_output(eval_, _case(), "Sure, here's the answer.")

    assert outcome.passed is True


def test_fallback_assertion_fails_when_output_reproduces_bad_output() -> None:
    eval_ = _eval(LoadedAssertion(type="deterministic", check=None))
    case = _case(bad_output='{"error": "malformed"}')

    outcome = score_output(eval_, case, '{"error": "malformed"}')

    assert outcome.passed is False


def test_fallback_assertion_passes_when_output_differs() -> None:
    eval_ = _eval(LoadedAssertion(type="deterministic", check=None))
    case = _case(bad_output='{"error": "malformed"}')

    outcome = score_output(eval_, case, '{"status": "ok"}')

    assert outcome.passed is True


def test_fallback_assertion_ignores_surrounding_whitespace() -> None:
    eval_ = _eval(LoadedAssertion(type="deterministic", check=None))
    case = _case(bad_output="exact text")

    outcome = score_output(eval_, case, "  exact text\n")

    assert outcome.passed is False


def test_judge_assertion_passes_when_verdict_passes(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = json.dumps({"passed": True, "score": 1.0, "reasoning": "addresses it directly"})
    monkeypatch.setattr(
        "regress.scoring.judge.httpx.post",
        lambda *a, **kw: httpx.Response(
            200,
            request=httpx.Request("POST", "http://x"),
            json={"choices": [{"message": {"content": payload}}]},
        ),
    )
    eval_ = _eval(LoadedAssertion(type="judge", rubric="Addresses the refund request."))

    outcome = score_output(
        eval_, _case(), "Your refund is processed.", judge_client=JudgeClient(api_key="sk-test")
    )

    assert outcome.passed is True
    assert outcome.reasoning == "addresses it directly"


def test_judge_assertion_fails_on_judge_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def raise_connect_error(*args: object, **kwargs: object) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr("regress.scoring.judge.httpx.post", raise_connect_error)
    eval_ = _eval(LoadedAssertion(type="judge", rubric="rubric"))

    outcome = score_output(
        eval_, _case(), "some output", judge_client=JudgeClient(api_key="sk-test")
    )

    assert outcome.passed is False
    assert "judge call failed" in outcome.reasoning


def test_run_eval_case_against_traces_replays_recorded_bad_output() -> None:
    eval_ = _eval(LoadedAssertion(type="deterministic", check="not_refusal"))
    case = _case(bad_output="I'm sorry, but I can't help with that.")

    outcome = run_eval_case_against_traces(eval_, case)

    assert outcome.passed is False
    assert outcome.output == case.bad_output


def test_run_eval_case_against_endpoint_posts_input_and_scores_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def fake_post(url: str, **kwargs: object) -> httpx.Response:
        captured["url"] = url
        captured["json"] = kwargs["json"]
        return httpx.Response(
            200, request=httpx.Request("POST", url), json={"output": "Sure, happy to help!"}
        )

    monkeypatch.setattr("regress.evalgen.run.httpx.post", fake_post)
    eval_ = _eval(LoadedAssertion(type="deterministic", check="not_refusal"))
    case = _case()

    outcome = run_eval_case_against_endpoint(eval_, case, "http://localhost:9000/predict")

    assert outcome.passed is True
    assert captured["url"] == "http://localhost:9000/predict"
    assert captured["json"] == {"input": "question"}


def test_run_eval_case_against_endpoint_fails_on_http_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def raise_connect_error(*args: object, **kwargs: object) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr("regress.evalgen.run.httpx.post", raise_connect_error)
    eval_ = _eval(LoadedAssertion(type="deterministic", check="not_refusal"))

    outcome = run_eval_case_against_endpoint(eval_, _case(), "http://localhost:9000/predict")

    assert outcome.passed is False
    assert "endpoint request failed" in outcome.reasoning


def test_run_eval_case_against_endpoint_fails_on_missing_output_field(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "regress.evalgen.run.httpx.post",
        lambda url, **kw: httpx.Response(
            200, request=httpx.Request("POST", url), json={"wrong_key": "value"}
        ),
    )
    eval_ = _eval(LoadedAssertion(type="deterministic", check="not_refusal"))

    outcome = run_eval_case_against_endpoint(eval_, _case(), "http://localhost:9000/predict")

    assert outcome.passed is False
    assert "endpoint request failed" in outcome.reasoning


def test_bare_run_eval_case_defaults_to_replay() -> None:
    eval_ = _eval(LoadedAssertion(type="deterministic", check="not_refusal"))
    case = _case(bad_output="I'm sorry, but I can't help with that.")

    outcome = run_eval_case(eval_, case)

    assert outcome.passed is False
