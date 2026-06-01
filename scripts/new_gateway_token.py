"""Mint a gateway token for a client.

Prints the raw token (give this to the client) and its sha256 hash (add this to
the server's CW_GATEWAY_TOKENS map). The server only ever stores the hash.

    python scripts/new_gateway_token.py acme-msp
"""

from __future__ import annotations

import hashlib
import secrets
import sys


def mint() -> tuple[str, str]:
    """Return (raw_token, sha256_hex_of_token)."""
    token = secrets.token_urlsafe(32)
    return token, hashlib.sha256(token.encode()).hexdigest()


def main() -> None:
    label = sys.argv[1] if len(sys.argv) > 1 else "client"
    token, token_hash = mint()
    print(f"label:                  {label}")
    print(f"token (give to client): {token}")
    print(f"sha256 (server):        {token_hash}")
    print(f'CW_GATEWAY_TOKENS entry: "{token_hash}": "{label}"')


if __name__ == "__main__":
    main()
