"""FastMCP server exposing ConnectWise PSA through a small set of gateway tools.

Design: rather than emit one tool per operation (2,700+ in scope), we expose a
handful of gateway tools over a runtime catalog of the OpenAPI spec:

    list_modules        -> orientation
    search_endpoints    -> find the right operation (any method)
    describe_endpoint   -> see its exact params, request body, response shape
    cw_get              -> execute any in-scope GET (with CW paging/conditions)
    cw_post / cw_put / cw_patch
                        -> execute any in-scope create / replace / patch

DELETE is out of scope by construction: it is dropped when the catalog is
built, so there is no delete tool and no delete code path.

Credentials are per request (X-CW-* headers over HTTP, CW_* env vars locally).
"""

from __future__ import annotations

from typing import Any

from fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import JSONResponse

from . import config
from .auth import MissingCredentials, get_credentials
from .catalog import load_catalog
from .client import make_client
from .conditions import CONDITIONS_HELP
from .executor import ExecutionError
from .executor import cw_get as _cw_get
from .executor import cw_write as _cw_write
from .gateway_auth import GatewayAuthMiddleware, load_gateway_tokens
from .logging_setup import configure_logging

mcp = FastMCP(
    name="connectwise-psa",
    instructions=(
        "Access to ConnectWise Manage (PSA): reads plus create/update, never "
        "delete. Workflow: call search_endpoints to find the operation you need "
        "(filter by method GET/POST/PUT/PATCH), describe_endpoint to see its "
        "parameters and request body, then cw_get to fetch data or "
        "cw_post/cw_put/cw_patch to change it. Use the `conditions` parameter "
        "on cw_get to filter (see cw_get docs for syntax). Before any write, "
        "read the current record and confirm the exact change with the user."
    ),
)

catalog = load_catalog()

_READ_ONLY = {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True}
# POST creates; PUT/PATCH modify existing records. None of them delete, but a
# PUT replaces the whole record, so it is flagged destructive for clients that
# gate on that hint.
_WRITE_HINTS = {
    "POST": {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False},
    "PUT": {"readOnlyHint": False, "destructiveHint": True, "idempotentHint": True},
    "PATCH": {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False},
}

_CW_GET_DESCRIPTION = (
    """Execute an in-scope ConnectWise GET and return the JSON result.

`path` is a path from search_endpoints, e.g. "/service/tickets" or
"/service/tickets/{id}". Fill `{...}` segments via `path_params`
(e.g. {"id": 123}).

Filtering uses the ConnectWise `conditions` query language:
"""
    + CONDITIONS_HELP
    + """

`fields` projects a subset of columns (comma-separated) to slim responses.
`order_by` sorts (e.g. "dateEntered desc"). `page`/`page_size` paginate.
"""
)

_WRITE_COMMON = """
`path` is a path from search_endpoints (method-filtered), e.g. "/service/tickets"
or "/service/tickets/{id}". Fill `{...}` segments via `path_params`.
`body` is the JSON request body; run describe_endpoint first to see the exact
shape (required fields, nested reference objects like {"id": 123}). `query`
carries any optional query-string parameters the operation lists.

Writes require CW_MCP_ALLOW_WRITES to be enabled on the server (default: on).
Always show the user the exact change and get confirmation before calling.
"""

_CW_POST_DESCRIPTION = (
    "Create a ConnectWise record (or invoke a POST action) via an in-scope POST.\n"
    "Returns the created record as ConnectWise returns it (HTTP 201 body).\n"
    + _WRITE_COMMON
)

_CW_PUT_DESCRIPTION = (
    "Replace a ConnectWise record via an in-scope PUT.\n"
    "PUT replaces the WHOLE record: send the complete object (fetch it with "
    "cw_get first, modify, send back). Prefer cw_patch for partial updates.\n"
    + _WRITE_COMMON
)

_CW_PATCH_DESCRIPTION = (
    "Partially update a ConnectWise record via an in-scope PATCH.\n"
    "`body` MUST be a JSON Patch operation list, the only format ConnectWise "
    "accepts, e.g.\n"
    '  [{"op": "replace", "path": "/summary", "value": "New summary"},\n'
    '   {"op": "replace", "path": "/status", "value": {"id": 42}}]\n'
    "Ops: add, replace, remove. Paths are field names with a leading slash; "
    'reference fields take an object like {"id": 42}.\n' + _WRITE_COMMON
)


@mcp.tool(annotations=_READ_ONLY)
def list_modules() -> dict[str, Any]:
    """List the ConnectWise modules in scope with operation counts per method.

    Use this for orientation before searching (e.g. service, company, finance,
    project, sales, time, schedule, procurement, system). Only GET, POST, PUT
    and PATCH are ever present; DELETE is excluded from this server.
    """
    return {
        "modules": catalog.modules(),
        "methods": catalog.methods,
        "total_operations": len(catalog.endpoints),
        "writes_enabled": config.writes_enabled(),
    }


@mcp.tool(annotations=_READ_ONLY)
def search_endpoints(
    query: str,
    module: str | None = None,
    method: str | None = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Search the in-scope operations by keyword.

    Matches operationId, method, path, summary and category/tag. Optionally
    restrict to one `module` (see list_modules) and/or one `method`
    (GET, POST, PUT, PATCH). Returns enough detail (method + path + params) to
    often skip describe_endpoint for reads; for writes, call describe_endpoint
    to get the request body shape.

    Examples: search_endpoints("open tickets", module="service")
              search_endpoints("ticket note", method="POST")
    """
    results = catalog.search(query, module=module, method=method, limit=limit)
    return [
        {
            "operationId": ep.operation_id,
            "method": ep.method,
            "path": ep.path,
            "module": ep.module,
            "tags": ep.tags,
            "summary": ep.summary,
            "path_params": ep.path_params,
            "has_body": ep.has_body,
        }
        for ep in results
    ]


@mcp.tool(annotations=_READ_ONLY)
def describe_endpoint(operation_id: str) -> dict[str, Any]:
    """Return the full contract for one operation.

    Pass the `operationId` from search_endpoints. Returns parameters, the
    request body schema (for POST/PUT/PATCH), the response shape, and which
    other methods exist on the same path.
    """
    desc = catalog.describe(operation_id)
    if desc is None:
        return {"error": f"Unknown operationId {operation_id!r}. Try search_endpoints."}
    return desc


@mcp.tool(description=_CW_GET_DESCRIPTION, annotations=_READ_ONLY)
async def cw_get(
    path: str,
    path_params: dict[str, Any] | None = None,
    conditions: str | None = None,
    child_conditions: str | None = None,
    order_by: str | None = None,
    fields: str | None = None,
    page: int | None = None,
    page_size: int = config.DEFAULT_PAGE_SIZE,
) -> Any:
    """Execute an in-scope ConnectWise GET.

    Filtering syntax is in the tool description (_CW_GET_DESCRIPTION).
    """
    try:
        creds = get_credentials()
    except MissingCredentials as e:
        return {"error": str(e)}

    try:
        async with make_client(creds) as client:
            return await _cw_get(
                client,
                catalog,
                path,
                path_params=path_params,
                conditions=conditions,
                child_conditions=child_conditions,
                order_by=order_by,
                fields=fields,
                page=page,
                page_size=page_size,
            )
    except ExecutionError as e:
        return {"error": str(e)}


async def _write(
    method: str,
    path: str,
    path_params: dict[str, Any] | None,
    body: Any,
    query: dict[str, Any] | None,
) -> Any:
    if not config.writes_enabled():
        return {
            "error": (
                "Write operations are disabled on this server "
                "(CW_MCP_ALLOW_WRITES is off). Only cw_get is available."
            )
        }
    try:
        creds = get_credentials()
    except MissingCredentials as e:
        return {"error": str(e)}

    try:
        async with make_client(creds) as client:
            return await _cw_write(
                client,
                catalog,
                method,
                path,
                path_params=path_params,
                body=body,
                query=query,
            )
    except ExecutionError as e:
        return {"error": str(e)}


@mcp.tool(description=_CW_POST_DESCRIPTION, annotations=_WRITE_HINTS["POST"])
async def cw_post(
    path: str,
    body: dict[str, Any] | list[Any] | None = None,
    path_params: dict[str, Any] | None = None,
    query: dict[str, Any] | None = None,
) -> Any:
    """Execute an in-scope ConnectWise POST (create / action)."""
    return await _write("POST", path, path_params, body, query)


@mcp.tool(description=_CW_PUT_DESCRIPTION, annotations=_WRITE_HINTS["PUT"])
async def cw_put(
    path: str,
    body: dict[str, Any],
    path_params: dict[str, Any] | None = None,
    query: dict[str, Any] | None = None,
) -> Any:
    """Execute an in-scope ConnectWise PUT (full replace)."""
    return await _write("PUT", path, path_params, body, query)


@mcp.tool(description=_CW_PATCH_DESCRIPTION, annotations=_WRITE_HINTS["PATCH"])
async def cw_patch(
    path: str,
    body: list[dict[str, Any]],
    path_params: dict[str, Any] | None = None,
    query: dict[str, Any] | None = None,
) -> Any:
    """Execute an in-scope ConnectWise PATCH (JSON Patch operation list)."""
    return await _write("PATCH", path, path_params, body, query)


async def health(request: Request) -> JSONResponse:
    """Unauthenticated liveness check for the hosting platform."""
    return JSONResponse({"status": "ok"})


mcp.custom_route("/health", methods=["GET"])(health)


def main() -> None:
    """Run the server. Defaults to HTTP; set CW_MCP_TRANSPORT=stdio for local."""
    import os

    from starlette.middleware import Middleware

    configure_logging()
    transport = os.getenv("CW_MCP_TRANSPORT", "http")
    if transport == "stdio":
        mcp.run()
        return

    # Hosted HTTP: fail closed if no gateway tokens are configured, then gate
    # every request (except /health) behind the X-Gateway-Key middleware.
    token_map = load_gateway_tokens()
    mcp.run(
        transport="http",
        host=config.HTTP_HOST,
        port=config.HTTP_PORT,
        middleware=[Middleware(GatewayAuthMiddleware, token_map=token_map)],
    )


if __name__ == "__main__":
    main()
