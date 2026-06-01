"""Per-request ConnectWise credential resolution.

This server is multi-tenant: credentials are NOT baked into the process. For
HTTP transport each caller supplies their ConnectWise keys as request headers;
for local/stdio use we fall back to environment variables so you can develop
against a single instance.

Required values (header / env):
    X-CW-Company-Id  / CW_COMPANY_ID
    X-CW-Public-Key  / CW_PUBLIC_KEY
    X-CW-Private-Key / CW_PRIVATE_KEY
    X-CW-Client-Id   / CW_CLIENT_ID    (the GUID CW requires on every call)
Optional:
    X-CW-Region      / CW_REGION       (na|eu|au|...; default na)
    X-CW-Host        / CW_HOST         (full host for self-hosted instances)
"""

from __future__ import annotations

import base64
import os
from dataclasses import dataclass

try:  # available only when running under the HTTP transport
    from fastmcp.server.dependencies import get_http_headers
except Exception:  # pragma: no cover - fastmcp always present in practice
    def get_http_headers() -> dict[str, str]:  # type: ignore
        return {}


class MissingCredentials(Exception):
    """Raised when a request lacks the ConnectWise credentials it needs."""


@dataclass(frozen=True)
class CWCredentials:
    company_id: str
    public_key: str
    private_key: str
    client_id: str
    region: str | None = None
    host: str | None = None

    def auth_header(self) -> str:
        """ConnectWise Basic auth: base64(companyId+publicKey : privateKey)."""
        token = f"{self.company_id}+{self.public_key}:{self.private_key}"
        return "Basic " + base64.b64encode(token.encode()).decode()


def _pick(headers: dict[str, str], header_name: str, env_name: str) -> str | None:
    # get_http_headers() lowercases keys; env is the local fallback.
    return headers.get(header_name.lower()) or os.getenv(env_name)


def get_credentials() -> CWCredentials:
    """Resolve credentials for the current request (headers first, env fallback)."""
    h = get_http_headers() or {}
    company = _pick(h, "X-CW-Company-Id", "CW_COMPANY_ID")
    public = _pick(h, "X-CW-Public-Key", "CW_PUBLIC_KEY")
    private = _pick(h, "X-CW-Private-Key", "CW_PRIVATE_KEY")
    client_id = _pick(h, "X-CW-Client-Id", "CW_CLIENT_ID")
    region = _pick(h, "X-CW-Region", "CW_REGION")
    host = _pick(h, "X-CW-Host", "CW_HOST")

    missing = [
        name
        for name, val in [
            ("company_id", company),
            ("public_key", public),
            ("private_key", private),
            ("client_id", client_id),
        ]
        if not val
    ]
    if missing:
        raise MissingCredentials(
            "Missing ConnectWise credentials: "
            + ", ".join(missing)
            + ". Supply them as X-CW-* request headers (HTTP) or CW_* env vars (local)."
        )

    return CWCredentials(
        company_id=company,  # type: ignore[arg-type]
        public_key=public,  # type: ignore[arg-type]
        private_key=private,  # type: ignore[arg-type]
        client_id=client_id,  # type: ignore[arg-type]
        region=region,
        host=host,
    )
