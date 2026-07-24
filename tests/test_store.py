from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from regress.ingest import iter_spans_from_request, parse_export_request
from regress.models import Base, Message, Span, Trace
from regress.store import store_parsed_spans

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def session() -> Iterator[Session]:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


def test_store_parsed_spans_persists_trace_span_and_messages(session: Session) -> None:
    body = (FIXTURES / "chat_trace.pb").read_bytes()
    request = parse_export_request(body, "application/x-protobuf")
    parsed = iter_spans_from_request(request)

    count = store_parsed_spans(session, parsed)
    session.commit()

    assert count == 2
    assert session.query(Trace).count() == 1
    assert session.query(Span).count() == 2
    assert session.query(Message).count() == 2


def test_reingesting_same_spans_does_not_duplicate(session: Session) -> None:
    body = (FIXTURES / "chat_trace.pb").read_bytes()
    request = parse_export_request(body, "application/x-protobuf")

    store_parsed_spans(session, iter_spans_from_request(request))
    session.commit()
    store_parsed_spans(session, iter_spans_from_request(request))
    session.commit()

    assert session.query(Trace).count() == 1
    assert session.query(Span).count() == 2
    assert session.query(Message).count() == 2


def test_trace_latency_computed_from_span_bounds(session: Session) -> None:
    body = (FIXTURES / "chat_trace.pb").read_bytes()
    request = parse_export_request(body, "application/x-protobuf")
    parsed = iter_spans_from_request(request)

    store_parsed_spans(session, parsed)
    session.commit()

    trace = session.query(Trace).one()
    assert trace.latency_ms is not None
    assert trace.latency_ms > 0
    assert trace.app == "quickstart-demo"
