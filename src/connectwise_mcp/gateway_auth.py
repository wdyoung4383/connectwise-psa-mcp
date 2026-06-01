"""Gateway access control for the hosted HTTP transport.

In hosted (pass-through) mode the server is reachable on a public URL, so a
per-customer gateway token gates access. Tokens are configured as a JSON map of
``sha256(token) -> client-label`` in the ``CW_GATEWAY_TOKENS`` env var, so the
deployed environment never holds usable raw tokens. The loader fails closed:
the server refuses to start if the map is missing, malformed, or empty.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os

from starlette.responses import JSONResponse

log = logging.getLogger(__name__)

_EXEMPT_PATHS = ("/health",)


def load_gateway_tokens() -> dict[str, str]:
    """Parse CW_GATEWAY_TOKENS into a {sha256hex: label} map. Fail closed."""
    raw = os.getenv("CW_GATEWAY_TOKENS")
    if not raw:
        raise RuntimeError(
            "CW_GATEWAY_TOKENS is not set; refusing to start the hosted gateway "
            "(fail closed). Set it to a JSON map of sha256(token) -> client label."
        )
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"CW_GATEWAY_TOKENS is not valid JSON: {e}") from e
    if not isinstance(data, dict) or not data:
        raise RuntimeError(
            "CW_GATEWAY_TOKENS must be a non-empty JSON object mapping "
            "sha256(token) hex digests to client labels."
        )
    return {str(k).lower(): str(v) for k, v in data.items()}


class GatewayAuthMiddleware:
    """ASGI middleware: require a valid X-Gateway-Key, except on exempt paths.

    On success, stashes the client label on the ASGI scope state for log
    attribution. Never logs the gateway key or any ConnectWise credential.
    """

    def __init__(self, app, *, token_map: dict[str, str]) -> None:
        self.app = app
        self.token_map = token_map

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        if scope.get("path", "") in _EXEMPT_PATHS:
            await self.app(scope, receive, send)
            return

        headers = dict(scope.get("headers") or [])
        key = headers.get(b"x-gateway-key")
        label = self.token_map.get(hashlib.sha256(key).hexdigest()) if key else None
        if label is None:
            response = JSONResponse(
                {"error": "Unauthorized: missing or invalid gateway key."},
                status_code=401,
            )
            await response(scope, receive, send)
            return

        scope.setdefault("state", {})
        scope["state"]["gateway_client"] = label
        log.info("gateway auth ok: client=%s path=%s", label, scope.get("path", ""))
        await self.app(scope, receive, send)
