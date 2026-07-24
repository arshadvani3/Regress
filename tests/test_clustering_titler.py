import json

import httpx
import pytest

from regress.clustering.titler import TitlerError, title_cluster
from regress.scoring.judge import JudgeClient


def _fake_response(content: str) -> httpx.Response:
    request = httpx.Request("POST", "http://example.test/v1/chat/completions")
    return httpx.Response(
        200, request=request, json={"choices": [{"message": {"content": content}}]}
    )


def test_title_cluster_parses_title_and_description(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = json.dumps(
        {"title": "Refuses refund requests", "description": "Declines valid refunds."}
    )
    monkeypatch.setattr(
        "regress.scoring.judge.httpx.post", lambda *a, **kw: _fake_response(payload)
    )

    result = title_cluster(
        ["The assistant refused the refund", "The assistant declined the refund"],
        client=JudgeClient(api_key="sk-test"),
    )

    assert result.title == "Refuses refund requests"
    assert result.description == "Declines valid refunds."


def test_title_cluster_truncates_to_max_examples(monkeypatch: pytest.MonkeyPatch) -> None:
    captured = {}

    def fake_post(url: str, **kwargs: object) -> httpx.Response:
        captured["json"] = kwargs["json"]
        return _fake_response(json.dumps({"title": "t", "description": "d"}))

    monkeypatch.setattr("regress.scoring.judge.httpx.post", fake_post)
    many_examples = [f"failure example {i}" for i in range(20)]

    title_cluster(many_examples, client=JudgeClient(api_key="sk-test"))

    user_message = captured["json"]["messages"][1]["content"]
    for i in range(8):
        assert f"failure example {i}" in user_message
    assert "failure example 10" not in user_message


def test_title_cluster_raises_on_unparseable_response(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "regress.scoring.judge.httpx.post", lambda *a, **kw: _fake_response("not json")
    )

    with pytest.raises(TitlerError):
        title_cluster(["x"], client=JudgeClient(api_key="sk-test"))


def test_title_cluster_raises_on_missing_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "regress.scoring.judge.httpx.post",
        lambda *a, **kw: _fake_response(json.dumps({"title": "only a title"})),
    )

    with pytest.raises(TitlerError):
        title_cluster(["x"], client=JudgeClient(api_key="sk-test"))


def test_title_cluster_wraps_judge_request_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    def raise_connect_error(*args: object, **kwargs: object) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr("regress.scoring.judge.httpx.post", raise_connect_error)

    with pytest.raises(TitlerError):
        title_cluster(["x"], client=JudgeClient(api_key="sk-test"))
