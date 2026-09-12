"""Executes catalog operations against ConnectWise.

Every call is checked against the catalog first: the (method, path) pair must
exist there or the request is refused before any network activity. Because
``scripts/build_catalog.py`` never emits DELETE operations, there is no delete
code path at all, and ``cw_write`` additionally refuses any method outside
``WRITE_METHODS`` as belt-and-braces.
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

WRITE_METHODS = frozenset({"POST", "PUT", "PATCH"})

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


def _require_in_scope(catalog: Catalog, method: str, path: str) -> None:
    if catalog.by_path(path, method) is not None:
        return
    others = catalog.methods_for_path(path)
    if others:
        raise ExecutionError(
            f"{method} is not available for {path!r} in this server's scope "
            f"(available: {', '.join(sorted(others))}). "
            "Use search_endpoints to find the right operation."
        )
    raise ExecutionError(
        f"Path {path!r} is not in this server's scope. "
        "Use search_endpoints to find a valid path."
    )


async def _send(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    *,
    params: dict[str, Any] | None = None,
    json_body: Any = None,
) -> Any:
    """Send one request, map transport/HTTP failures to ExecutionError."""
    start = time.monotonic()
    try:
        resp = await client.request(method, url, params=params, json=json_body)
    except httpx.TimeoutException as e:
        raise ExecutionError(
            f"ConnectWise request timed out for {method} {url}. The instance "
            "may be slow or unreachable; try again or narrow the request."
        ) from e
    except httpx.TransportError as e:
        raise ExecutionError(
            f"Could not reach ConnectWise for {method} {url}: {type(e).__name__}. "
            "Check the region/host and network connectivity."
        ) from e

    duration_ms = (time.monotonic() - start) * 1000
    # Log method/path/status/duration only. Never query values or request
    # bodies, which can carry PII.
    log.info("%s %s -> %s (%.0f ms)", method, url, resp.status_code, duration_ms)

    if resp.status_code >= 400:
        if resp.status_code in (401, 403):
            raise ExecutionError(
                f"ConnectWise authentication failed (HTTP {resp.status_code}). "
                "Verify the company id, public/private keys, and clientId, and "
                "that the API member has permission for this operation."
            )
        if resp.status_code == 404:
            raise ExecutionError(
                f"ConnectWise returned 404 Not Found for {method} {url}. The "
                "record or path may not exist on this instance."
            )
        detail = redact(resp.text[:1000])
        raise ExecutionError(
            f"ConnectWise rejected the request (HTTP {resp.status_code}): {detail}"
        )

    if resp.status_code == 204 or not resp.content:
        return {"status": resp.status_code, "ok": True}
    try:
        return resp.json()
    except ValueError:
        return {"raw": resp.text}


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
    _require_in_scope(catalog, "GET", path)
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

    return await _send(client, "GET", url, params=query)


async def cw_write(
    client: httpx.AsyncClient,
    catalog: Catalog,
    method: str,
    path: str,
    *,
    path_params: dict[str, Any] | None = None,
    body: Any = None,
    query: dict[str, Any] | None = None,
) -> Any:
    """Execute a POST/PUT/PATCH against a known in-scope path.

    ``body`` is sent as JSON. For PATCH it must be a JSON Patch operation list
    (``[{"op": "replace", "path": "/summary", "value": "..."}]``), which is
    the only PATCH format ConnectWise accepts.
    """
    method = method.upper()
    if method not in WRITE_METHODS:
        raise ExecutionError(
            f"Method {method!r} is not a supported write method "
            f"(allowed: {', '.join(sorted(WRITE_METHODS))})."
        )
    _require_in_scope(catalog, method, path)
    ep = catalog.by_path(path, method)
    assert ep is not None  # guaranteed by _require_in_scope

    if ep.has_body:
        media = ep.body_media_type or ""
        if "json" not in media:
            raise ExecutionError(
                f"{method} {path} expects a {media} body, which this server does "
                "not support (JSON bodies only)."
            )
        if body is None and ep.request_body.get("required", False):
            raise ExecutionError(
                f"{method} {path} requires a JSON body. Call describe_endpoint "
                f"('{ep.operation_id}') to see the expected shape."
            )
    if method == "PATCH" and body is not None and not isinstance(body, list):
        raise ExecutionError(
            "PATCH body must be a list of JSON Patch operations, e.g. "
            '[{"op": "replace", "path": "/summary", "value": "New text"}].'
        )

    url = _fill_path(path, path_params)
    return await _send(client, method, url, params=query or None, json_body=body)
