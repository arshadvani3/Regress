"""Strip likely-sensitive content from real trace text before it lands in a
generated eval file, per CLAUDE.md's Quality bar: "Sanitize any real trace
content before it lands in generated evals or docs (strip emails, keys,
names) — there's a sanitize() pass in EvalGen from day one."

This is regex-based best-effort redaction, not a guarantee of PII removal.
Names in particular have no reliable pattern-based detection without an NER
model (a dependency this project isn't taking on) — the name heuristic here
catches common "Hi, I'm Jane Smith" / "My name is..." introductions, not
every name in every text. Generated evals are meant to be human-reviewed
before committing; this pass exists to make that review safer, not to
replace it.
"""

from __future__ import annotations

import re

_EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")

_PHONE_RE = re.compile(r"(?<!\d)(\+?\d{1,3}[\s.-]?)?\(?\d{3}\)?[\s.-]\d{3}[\s.-]\d{4}(?!\d)")

# Common API key / secret token shapes: provider-prefixed keys (sk-, AKIA,
# ghp_, xox*, AIza), and generic long hex/base64-ish runs that read as
# credentials rather than prose.
_KEY_PATTERNS = [
    re.compile(r"\bsk-[A-Za-z0-9]{10,}\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bghp_[A-Za-z0-9]{20,}\b"),
    re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b"),
    re.compile(r"\bAIza[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"\b[a-f0-9]{32,}\b", re.IGNORECASE),
    re.compile(r"\b[A-Za-z0-9+/]{40,}={0,2}\b"),
]

# "Hi, I'm Jane Smith" / "My name is Jane Smith" / "This is Jane Smith speaking"
# (?i:...) scopes case-insensitivity to the intro phrase only, so the name
# itself still has to look like a proper name (capitalized words).
_NAME_INTRO_RE = re.compile(
    r"\b(?i:I'?m|I am|my name is|this is)\s+"
    r"([A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,2})",
)


def sanitize(text: str) -> str:
    """Redact emails, phone numbers, likely API keys, and introduced names."""
    if not text:
        return text
    result = _EMAIL_RE.sub("[REDACTED_EMAIL]", text)
    result = _PHONE_RE.sub("[REDACTED_PHONE]", result)
    for pattern in _KEY_PATTERNS:
        result = pattern.sub("[REDACTED_KEY]", result)
    result = _NAME_INTRO_RE.sub(
        lambda m: m.group(0).replace(m.group(1), "[REDACTED_NAME]"), result
    )
    return result


def sanitize_messages(messages: list[dict[str, object]]) -> list[dict[str, object]]:
    """Sanitize the text `content` of every part in a list of GenAI-convention
    messages (the shape `regress.scoring.message_parts` reads), leaving
    structure and non-string fields untouched.
    """
    sanitized = []
    for message in messages:
        parts = message.get("parts")
        if not isinstance(parts, list):
            sanitized.append(message)
            continue
        new_parts = []
        for part in parts:
            if isinstance(part, dict) and isinstance(part.get("content"), str):
                new_parts.append({**part, "content": sanitize(part["content"])})
            else:
                new_parts.append(part)
        sanitized.append({**message, "parts": new_parts})
    return sanitized
