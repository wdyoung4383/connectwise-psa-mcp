"""Live smoke test: read from a real ConnectWise instance using CW_* creds.

Run locally after filling .env (see .env.example):

    python scripts/smoke_live.py

Exits 0 on a successful live read, 1 otherwise.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

from connectwise_mcp.auth import MissingCredentials, get_credentials
from connectwise_mcp.catalog import load_catalog
from connectwise_mcp.client import make_client
from connectwise_mcp.executor import ExecutionError, cw_get
from connectwise_mcp.logging_setup import configure_logging


def _load_dotenv(path: str = ".env") -> None:
    """Minimal .env loader (no external dependency)."""
    p = Path(path)
    if not p.exists():
        return
    for raw in p.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
            value = value[1:-1]
        os.environ.setdefault(key.strip(), value)


async def main() -> int:
    _load_dotenv()
    configure_logging()

    catalog = load_catalog()
    print(f"catalog: {len(catalog.endpoints)} endpoints, modules={catalog.modules()}")

    try:
        creds = get_credentials()
    except MissingCredentials as e:
        print(f"ERROR: {e}")
        return 1

    try:
        async with make_client(creds) as client:
            members = await cw_get(client, catalog, "/system/members", page_size=1)
            print(f"OK: /system/members returned {len(members)} record(s)")
            if members:
                print(f"first member id: {members[0].get('id')}")
    except ExecutionError as e:
        print(f"ERROR: {e}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
