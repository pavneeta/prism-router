"""Production safety helpers — secret redaction and shared markers."""

from __future__ import annotations

import re

# Common provider key / bearer shapes that may appear in exception strings.
_SECRET_RE = re.compile(
    r"(?i)(?:"
    r"sk-[a-z0-9_-]{10,}"
    r"|sk-ant-[a-z0-9_-]{10,}"
    r"|fw_[a-z0-9_-]{10,}"
    r"|tgp_v1_[a-z0-9_-]{10,}"
    r"|gsk_[a-z0-9_-]{10,}"
    r"|Bearer\s+\S+"
    r"|api[_-]?key['\"]?\s*[:=]\s*['\"]?[^\s'\"]+"
    r")"
)


def redact_secrets(text: str | None) -> str | None:
    """Strip likely API keys / bearer tokens from log or client-facing strings."""
    if text is None:
        return None
    return _SECRET_RE.sub("[REDACTED]", text)
