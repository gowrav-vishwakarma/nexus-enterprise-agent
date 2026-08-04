"""Shared redaction helpers for guards and event sinks.

One set of patterns so a value redacted from a model prompt is also redacted from
a trace, a webhook body, and an audit line.
"""

from __future__ import annotations

import re
from typing import Any

EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")
PHONE_RE = re.compile(r"\b\d{3}[-.\s]?\d{3}[-.\s]?\d{4}\b")

# Dict keys whose value is replaced wholesale, whatever it looks like.
SENSITIVE_KEYS: frozenset[str] = frozenset(
    {
        "api_key",
        "apikey",
        "authorization",
        "access_token",
        "password",
        "refresh_token",
        "secret",
        "token",
    }
)

MASK = "[REDACTED]"


def redact_text(text: str) -> str:
    """Replace email addresses and phone numbers in a string."""
    return PHONE_RE.sub("[PHONE]", EMAIL_RE.sub("[EMAIL]", text))


def redact_payload(
    value: Any,
    *,
    sensitive_keys: frozenset[str] = SENSITIVE_KEYS,
    _depth: int = 0,
) -> Any:
    """Return a copy of *value* with PII and secret-valued keys removed.

    Walks dicts and lists. A key in *sensitive_keys* (compared case-insensitively)
    has its whole value masked; every other string is scanned for PII.
    """
    if _depth > 10:
        return value
    if isinstance(value, dict):
        out: dict[Any, Any] = {}
        for key, item in value.items():
            if isinstance(key, str) and key.lower() in sensitive_keys:
                out[key] = MASK
            else:
                out[key] = redact_payload(
                    item, sensitive_keys=sensitive_keys, _depth=_depth + 1
                )
        return out
    if isinstance(value, (list, tuple)):
        redacted = [
            redact_payload(item, sensitive_keys=sensitive_keys, _depth=_depth + 1)
            for item in value
        ]
        return type(value)(redacted) if isinstance(value, tuple) else redacted
    if isinstance(value, str):
        return redact_text(value)
    return value
