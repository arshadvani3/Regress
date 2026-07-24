"""End-to-end: instrument() -> OTLP export -> /v1/traces -> stored trace."""

from collections.abc import Iterator
from unittest.mock import MagicMock

import openai
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

import regress._otlp_export as otlp_export
from regress import instrument, task
from regress.app import create_app
from regress.models import Span, Trace


@pytest.fixture
def engine() -> Iterator[Engine]:
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    yield engine
    engine.dispose()


@pytest.fixture
def client(engine: Engine) -> TestClient:
    return TestClient(create_app(engine=engine))


@pytest.fixture(autouse=True)
def route_exports_to_test_client(
    monkeypatch: pytest.MonkeyPatch, client: TestClient
) -> None:
    """Redirect regress._otlp_export.httpx.post to the in-process TestClient."""

    def fake_post(url: str, *, content: bytes, headers: dict[str, str], **kwargs: object) -> object:
        return client.post("/v1/traces", content=content, headers=headers)

    monkeypatch.setattr(otlp_export.httpx, "post", fake_post)


def test_task_decorated_call_is_ingested_and_queryable(
    client: TestClient, engine: Engine
) -> None:
    @task(name="answer_question")
    def run() -> str:
        return "done"

    run()

    with Session(engine) as session:
        trace = session.execute(select(Trace)).scalar_one()
        span = session.execute(select(Span)).scalar_one()
        assert span.name == "answer_question"
        assert span.status == "ok"
        assert trace.status == "ok"


def test_instrumented_openai_call_is_ingested_with_messages(
    monkeypatch: pytest.MonkeyPatch, client: TestClient, engine: Engine
) -> None:
    instrument()
    fake_response = MagicMock()
    fake_response.model = "gpt-4-0613"
    fake_response.usage.prompt_tokens = 10
    fake_response.usage.completion_tokens = 5
    choice = MagicMock()
    choice.message.role = "assistant"
    choice.message.content = "hello there"
    choice.finish_reason = "stop"
    fake_response.choices = [choice]
    monkeypatch.setattr(openai.OpenAI, "post", lambda self, *a, **kw: fake_response)

    sdk_client = openai.OpenAI(api_key="sk-fake")
    sdk_client.chat.completions.create(
        model="gpt-4", messages=[{"role": "user", "content": "what's the weather"}]
    )

    with Session(engine) as session:
        span = session.execute(select(Span)).scalar_one()
        assert span.gen_ai_provider_name == "openai"
        assert span.request_model == "gpt-4"
        assert span.response_model == "gpt-4-0613"
        assert span.input_tokens == 10
        assert span.output_tokens == 5
        messages = list(span.messages)
        assert any(m.direction == "input" and m.role == "user" for m in messages)
        assert any(m.direction == "output" and m.role == "assistant" for m in messages)
