"""Optional client API keys for the public gateway.

When ``MODEL_ROUTER_API_KEYS`` is non-empty, requests (except health probes)
must present a matching key via ``Authorization: Bearer …`` or ``X-Api-Key``.

Leave unset for local open access. **Set this on any internet-facing deploy**
so strangers cannot burn your provider keys.
"""

from __future__ import annotations

import hmac
import hashlib
import os
import secrets


def configured_api_keys() -> frozenset[str]:
    raw = (os.environ.get("MODEL_ROUTER_API_KEYS") or "").strip()
    if not raw:
        return frozenset()
    return frozenset(k.strip() for k in raw.split(",") if k.strip())


def extract_client_api_key(authorization: str | None, x_api_key: str | None) -> str | None:
    if x_api_key and x_api_key.strip():
        return x_api_key.strip()
    if authorization:
        parts = authorization.split(None, 1)
        if len(parts) == 2 and parts[0].lower() == "bearer" and parts[1].strip():
            return parts[1].strip()
    return None


def client_api_key_ok(presented: str | None, allowed: frozenset[str] | None = None) -> bool:
    keys = configured_api_keys() if allowed is None else allowed
    if not keys:
        return True
    if not presented:
        return False
    return any(hmac.compare_digest(presented, k) for k in keys)


def client_principal(presented: str | None) -> str:
    """Non-reversible tenant namespace; never retain/log the raw client key."""
    if not presented:
        return "anonymous"
    return hashlib.sha256(presented.encode()).hexdigest()[:24]


def new_client_api_key() -> str:
    """Helper for operators generating a gateway client key."""
    return f"pr_{secrets.token_urlsafe(32)}"
