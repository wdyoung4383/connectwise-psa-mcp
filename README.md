# ConnectWise PSA MCP Server

[![CI](https://github.com/wdyoung4383/connectwise-psa-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/wdyoung4383/connectwise-psa-mcp/actions/workflows/ci.yml)

A [FastMCP](https://gofastmcp.com) server that exposes **ConnectWise Manage
(PSA)** to AI agents: every read, create and update operation in the public
API, and no delete.

## Why a gateway, not 2,700 tools

The ConnectWise API has thousands of operations; the in-scope set is **2,780
operations** (1,725 GET, 399 POST, 327 PUT, 329 PATCH) across 12 modules.
Exposing one tool per operation would overwhelm any LLM client. Instead the
OpenAPI spec is loaded as a runtime **catalog**, and seven gateway tools sit in
front of it:

| Tool | Purpose |
|------|---------|
| `list_modules` | Orientation: modules + operation counts per method |
| `search_endpoints` | Find an operation by keyword, optionally by module/method |
| `describe_endpoint` | See an operation's params, request body and response shape |
| `cw_get` | Execute an in-scope GET (paging + `conditions` filtering) |
| `cw_post` | Execute an in-scope POST (create a record / invoke an action) |
| `cw_put` | Execute an in-scope PUT (replace a whole record) |
| `cw_patch` | Execute an in-scope PATCH (JSON Patch operation list) |

**No delete by construction:** DELETE operations are dropped when the catalog
is built, so there is no delete tool and no delete code path. The write tools
also refuse any method other than POST/PUT/PATCH.

Read tools carry the MCP `readOnlyHint`; write tools do not, so clients that
gate on annotations prompt before a write. `cw_put` is additionally flagged
`destructiveHint` because a PUT replaces the entire record.

## Scope

[`scope.py`](src/connectwise_mcp/scope.py) defines the rules:
`ALLOWED_METHODS` (GET, POST, PUT, PATCH) and `SELECTED_CATEGORIES` (`None` =
every category, or a set of OpenAPI tags to narrow it). Rebuild the catalog
after changing either:

```bash
python scripts/build_catalog.py /path/to/full-connectwise-openapi.json
```

The full spec ("ConnectWise Manage Public Endpoints") is downloadable from the
[ConnectWise Developer Network](https://developer.connectwise.com/Products/ConnectWise_PSA/REST)
(login required). The build prunes unreferenced schemas, non-2xx responses and
the per-request `clientId` header so the shipped
`data/openapi_catalog.json` stays around 3 MB. The committed catalog was built
from spec version **2025.16**.

## Writes

`cw_post`, `cw_put` and `cw_patch` are enabled by default. Set
`CW_MCP_ALLOW_WRITES=false` to run a read-only gateway; the tools stay
registered but refuse every call, so a hosted deployment can be flipped without
a code change. Writes use the same per-request credentials as reads, so what an
API member can change in ConnectWise is what the agent can change here.

ConnectWise PATCH bodies are JSON Patch operation lists:

```json
[{"op": "replace", "path": "/summary", "value": "New summary"},
 {"op": "replace", "path": "/status", "value": {"id": 42}}]
```

`describe_endpoint` returns the request body schema for every write operation.
The one `multipart/form-data` upload in the spec (`POST /system/documents`) is
in the catalog but refused at execution time; only JSON bodies are sent.

## Credentials

Multi-tenant: credentials are supplied **per request**, never stored in the
process.

- **Hosted (HTTP):** send headers `X-CW-Company-Id`, `X-CW-Public-Key`,
  `X-CW-Private-Key`, `X-CW-Client-Id`, and optionally `X-CW-Region`
  (`na`/`eu`/`au`/…) or `X-CW-Host` (self-hosted).
- **Local (stdio):** set the `CW_*` env vars (see `.env.example`).

ConnectWise auth = HTTP Basic `base64(companyId+publicKey : privateKey)` plus
the required `clientId` header — both are built per request.

## Run

```bash
pip install -e ".[dev]"

# Hosted HTTP (default)
connectwise-mcp                       # binds 127.0.0.1:8000

# Local stdio (uses CW_* env vars)
CW_MCP_TRANSPORT=stdio connectwise-mcp
```

## Test

```bash
pytest            # offline smoke tests (catalog + path filling)
```

## Filtering with `conditions`

`cw_get` accepts ConnectWise's `conditions` query language, e.g.

```
status/name = 'Open' and board/id = 1
lastUpdated > [2026-01-01T00:00:00Z]
company/identifier = 'ACME'
```

See `conditions.py` for the full cheatsheet (also embedded in the `cw_get`
tool docstring so the agent has it inline).
