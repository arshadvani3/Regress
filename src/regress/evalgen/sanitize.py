"""Backwards-compatible re-export of the shared sanitizer.

The redaction primitives moved to `regress.sanitize` when ingest-time
sanitization began sharing them with EvalGen (a lower-level module shouldn't
depend on `evalgen`). This module keeps the historical
`regress.evalgen.sanitize` import path working.
"""

from __future__ import annotations

from regress.sanitize import sanitize, sanitize_message_content, sanitize_messages

__all__ = ["sanitize", "sanitize_message_content", "sanitize_messages"]
