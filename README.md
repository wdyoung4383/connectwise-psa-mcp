# ConnectWise PSA MCP Server (read-only)

A [FastMCP](https://gofastmcp.com) server that exposes **ConnectWise Manage
(PSA)** as a read-only gateway for AI agents.

## Why a gateway, not 300 tools

The ConnectWise API has thousands of operations; the in-scope read subset alone
is **324 GET endpoints** across 71 categories. Exposing one tool per endpoint
would overwhelm any LLM client. Instead the OpenAPI spec is loaded as a runtime
**catalog**, and four gateway tools sit in front of it:

| Tool | Purpose |
|------|---------|
| `list_modules` | Orientation: modules + endpoint counts |
| `search_endpoints` | Find a GET endpoint by keyword |
| `describe_endpoint` | See an endpoint's params + response shape |
| `cw_get` | Execute an in-scope GET (paging + `conditions` filtering) |

**Read-only by construction:** there is no create/update/delete code path.

## Scope

Only `GET` operations under the categories listed in
[`scope.py`](src/connectwise_mcp/scope.py) are included. To change scope, edit
that set and regenerate `data/openapi_get_filtered.json` from the full spec.

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
