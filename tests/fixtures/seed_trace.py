"""Seed a fixture trace into REGRESS_DB_URL. Used by test_cli_traces.py subprocess tests."""

import sys
from pathlib import Path

from sqlalchemy.orm import Session

from regress.db import _make_engine, init_db
from regress.ingest import iter_spans_from_request, parse_export_request
from regress.store import store_parsed_spans


def main() -> None:
    fixture_path = Path(sys.argv[1])
    body = fixture_path.read_bytes()
    content_type = "application/x-protobuf" if fixture_path.suffix == ".pb" else "application/json"

    engine = _make_engine()
    init_db(bind=engine)
    session = Session(engine)
    request = parse_export_request(body, content_type)
    store_parsed_spans(session, iter_spans_from_request(request))
    session.commit()


if __name__ == "__main__":
    main()
