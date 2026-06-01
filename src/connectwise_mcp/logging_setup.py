"""Logging configuration and credential redaction for the ConnectWise gateway.

The gateway brokers tenants' ConnectWise credentials, so nothing logged may ever
contain them. ``redact()`` is the single guard: run any structure through it
before logging. ``configure_logging()`` sets up format/level once at startup.
"""

from __future__ import annotations

import logging
import os
import re
from typing import Any

# Scope: ConnectWise credential header/env names only. Generic secrets like
# "password" are out of scope. Non-dict/list/str values (tuples, sets, ints)
# pass through redact() unchanged.
# Header/env keys whose VALUES are secret and must never appear in logs.
_SECRET_KEYS = {
    "authorization",
    "clientid",
    "x-cw-company-id",
    "x-cw-public-key",
    "x-cw-private-key",
    "x-cw-client-id",
    "cw_company_id",
    "cw_public_key",
    "cw_private_key",
    "cw_client_id",
}

_REDACTED = "***"

# Require a long token so prose like "Basic auth is required" is not masked.
# A real ConnectWise Basic token (base64 of "company+public:private") is 30+ chars.
_BASIC_RE = re.compile(r"Basic\s+[A-Za-z0-9+/=]{20,}", re.IGNORECASE)


def redact(value: Any) -> Any:
    """Return a copy of ``value`` with credentials masked.

    Recurses through dicts and lists. Dict entries whose key (case-insensitive)
    names a secret are masked. Strings have embedded Basic-auth tokens masked.
    Other values pass through unchanged.
    """
    if isinstance(value, dict):
        return {
            k: (_REDACTED if str(k).lower() in _SECRET_KEYS else redact(v))
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [redact(v) for v in value]
    if isinstance(value, str):
        return _BASIC_RE.sub("Basic " + _REDACTED, value)
    return value


def configure_logging(level: str | None = None) -> None:
    """Configure root logging once, honoring CW_LOG_LEVEL (default INFO)."""
    level_name = (level or os.getenv("CW_LOG_LEVEL", "INFO")).upper()
    logging.basicConfig(
        level=getattr(logging, level_name, logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
