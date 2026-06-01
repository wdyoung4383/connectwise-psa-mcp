"""Executes GET calls against ConnectWise. Read-only by construction.

Only GET is implemented here. There is intentionally no create/update/delete
path, so the read-only guarantee is enforced by the absence of code, not by a
flag that could be flipped.
"""

from __future__ import annotations

import logging
import re
import time
from typing import Any

import httpx

from .catalog import Catalog
from .config import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE
from .logging_setup import redact

_PATH_VAR = re.compile(r"\{([^}]+)\}")

log = logging.getLogger(__name__)


class ExecutionError(Exception):
    pass


def _fill_path(path: str, path_params: dict[str, Any] | None) -> str:
    path_params = path_params or {}
    needed = _PATH_VAR.findall(path)
    missing = [v for v in needed if v not in path_params]
    if missing:
        raise ExecutionError(
            f"Missing path parameter(s) {missing} for {path}. "
            f"Provide them in path_params."
        )
    return _PATH_VAR.sub(lambda m: str(path_params[m.group(1)]), path)


async def cw_get(
    client: httpx.AsyncClient,
    catalog: Catalog,
    path: str,
    *,
    path_params: dict[str, Any] | None = None,
    conditions: str | None = None,
    child_conditions: str | None = None,
    custom_field_conditions: str | None = None,
    order_by: str | None = None,
    fields: str | None = None,
    page: int | None = None,
    page_size: int | None = None,
    extra_query: dict[str, Any] | None = None,
) -> Any:
    """Execute a GET against a known in-scope path and return parsed JSON."""
    ep = catalog.by_path(path)
    if ep is None:
        raise ExecutionError(
            f"Path {path!r} is not in this server's read scope. "
            "Use search_endpoints to find a valid path."
        )

    url = _fill_path(path, path_params)

    ps = page_size if page_size is not None else DEFAULT_PAGE_SIZE
    ps = max(1, min(ps, MAX_PAGE_SIZE))

    query: dict[str, Any] = {"pageSize": ps}
    if conditions:
        query["conditions"] = conditions
    if child_conditions:
        query["childConditions"] = child_conditions
    if custom_field_conditions:
        query["customFieldConditions"] = custom_field_conditions
    if order_by:
        query["orderBy"] = order_by
    if fields:
        query["fields"] = fields
    if page is not None:
        query["page"] = page
    if extra_query:
        query.update(extra_query)

    start = time.monotonic()
    try:
        resp = await client.get(url, params=query)
    except httpx.TimeoutException as e:
        raise ExecutionError(
            f"ConnectWise request timed out for {url}. The instance may be slow "
            "or unreachable; try again or narrow the query."
        ) from e
    except httpx.TransportError as e:
        raise ExecutionError(
            f"Could not reach ConnectWise for {url}: {type(e).__name__}. "
            "Check the region/host and network connectivity."
        ) from e

    duration_ms = (time.monotonic() - start) * 1000
    # Log path/status/duration only — never query values, which can carry PII.
    log.info("cw_get %s -> %s (%.0f ms)", url, resp.status_code, duration_ms)

    if resp.status_code >= 400:
        if resp.status_code in (401, 403):
            raise ExecutionError(
                f"ConnectWise authentication failed (HTTP {resp.status_code}). "
                "Verify the company id, public/private keys, and clientId."
            )
        if resp.status_code == 404:
            raise ExecutionError(
                f"ConnectWise returned 404 Not Found for {url}. The record or "
                "path may not exist on this instance."
            )
        detail = redact(resp.text[:1000])
        raise ExecutionError(
            f"ConnectWise rejected the request (HTTP {resp.status_code}): {detail}"
        )

    try:
        return resp.json()
    except ValueError:
        return {"raw": resp.text}
