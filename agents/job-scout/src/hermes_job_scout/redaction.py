"""Structured, value-safe redaction for reports and CLI errors."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

_SECRET_KEY = re.compile(r"(?:api[_-]?key|access[_-]?token|password|secret|credential)", re.I)
_ASSIGNMENT = re.compile(
    r"(?i)\b(?:api[_-]?key|access[_-]?token|token|password|secret)\s*[:=]\s*[^\s,;]+"
)
_EMAIL = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
_PHONE = re.compile(r"(?<!\w)(?:\+?\d[\d ()-]{7,}\d)(?!\w)")
_HOME_PATH = re.compile(r"/(?:Users|home)/[^\s,;]+")


def redact_text(value: str) -> str:
    redacted = _ASSIGNMENT.sub("<REDACTED>", value)
    redacted = _EMAIL.sub("<REDACTED>", redacted)
    redacted = _PHONE.sub("<REDACTED>", redacted)
    return _HOME_PATH.sub("<REDACTED>", redacted)


def redact_data(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): "<REDACTED>" if _SECRET_KEY.search(str(key)) else redact_data(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact_data(item) for item in value]
    if isinstance(value, tuple):
        return tuple(redact_data(item) for item in value)
    if isinstance(value, str):
        return redact_text(value)
    return value


__all__ = ["redact_data", "redact_text"]
