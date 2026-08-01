from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from regress.models import Base, Message, Span, Trace
from regress.store import store_parsed_spans

PII_TEXT = "Contact me at jane@example.com, my key is sk-ABCDEF0123456789."


@pytest.fixture
def session() -> Iterator[Session]:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


def _parsed_with_pii() -> list[tuple[Trace, Span, list[Message]]]:
    trace = Trace(id="t1", app="demo", status="ok")
    span = Span(id="t1-s1", trace_id="t1", name="chat", status="ok")
    message = Message(
        span_id="t1-s1",
        direction="input",
        role="user",
        content={"role": "user", "parts": [{"content": PII_TEXT}]},
        position=0,
    )
    return [(trace, span, [message])]


def _stored_content(session: Session) -> str:
    message = session.query(Message).one()
    parts = message.content["parts"]  # type: ignore[index]
    return str(parts[0]["content"])


def test_ingest_stores_raw_text_by_default(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("REGRESS_SANITIZE_INGEST", raising=False)

    store_parsed_spans(session, _parsed_with_pii())
    session.commit()

    # Default is verbatim: the raw PII is preserved locally.
    assert _stored_content(session) == PII_TEXT


def test_ingest_redacts_when_enabled(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("REGRESS_SANITIZE_INGEST", "1")

    store_parsed_spans(session, _parsed_with_pii())
    session.commit()

    stored = _stored_content(session)
    assert "jane@example.com" not in stored
    assert "sk-ABCDEF0123456789" not in stored
    assert "[REDACTED_EMAIL]" in stored
    assert "[REDACTED_KEY]" in stored


@pytest.mark.parametrize("flag", ["0", "false", "no", "", "off"])
def test_falsy_flag_values_leave_text_raw(
    session: Session, monkeypatch: pytest.MonkeyPatch, flag: str
) -> None:
    monkeypatch.setenv("REGRESS_SANITIZE_INGEST", flag)

    store_parsed_spans(session, _parsed_with_pii())
    session.commit()

    assert _stored_content(session) == PII_TEXT


def test_sanitize_preserves_message_structure(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("REGRESS_SANITIZE_INGEST", "yes")

    store_parsed_spans(session, _parsed_with_pii())
    session.commit()

    message = session.query(Message).one()
    assert message.content["role"] == "user"  # type: ignore[index]
    assert message.role == "user"
    assert message.direction == "input"
