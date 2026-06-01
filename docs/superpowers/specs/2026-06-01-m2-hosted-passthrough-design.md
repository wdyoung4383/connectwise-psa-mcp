# M2 — Hosted pass-through gateway for Claude Desktop/Code

**Date:** 2026-06-01
**Status:** Approved
**Project:** connectwise-psa-mcp (read-only MCP gateway for ConnectWise Manage / PSA)
**Builds on:** M1 (trustworthy read-only core) — complete.

## Context

M1 hardened the read-only server (pinned deps, CI, ruff, logging + credential
redaction, clearer error mapping) and validated it locally over stdio. The
server is already multi-tenant by construction: credentials arrive per request
as `X-CW-*` HTTP headers (or `CW_*` env vars for stdio) via `auth.get_credentials()`
and are never stored. The HTTP transport already exists (`mcp.run(transport="http", ...)`).

The business goal is to host the server so the operator's clients can use it
from their own AI tools. Research into Claude's connector model (Nov 2025 MCP
spec + Anthropic connector docs) established:

- **Claude.ai web custom connectors support OAuth 2.1 only** — no field for
  custom headers or a static token (Anthropic lists user-pasted bearer tokens as
  "not yet supported"). Hosting for Claude.ai web would therefore require an
  OAuth 2.1 authorization server **and** storing each client's CW credentials
  server-side, keyed to their OAuth identity.
- **Claude Desktop / Claude Code config files DO support static `headers`/`env`
  for remote servers**, so a client can supply their own CW keys per request and
  the host stores nothing.

M2 deliberately targets the second path — the small, zero-credential-storage
build — to reach "real clients using it" quickly. The OAuth/web product is a
later milestone.

## Roadmap (this spec covers M2 only)

- **M1 — Trustworthy read-only core.** Complete.
- **M2 — Hosted pass-through gateway for Claude Desktop/Code.** *(This document.)*
- **Later — Claude.ai web product:** OAuth 2.1 authorization server + encrypted
  per-client credential vault (the polished "Connect & sign in" experience).
- **Later — Write/action tools** with safety design.

## Goal

Deploy the existing read-only server to a public HTTPS URL so clients connect
from Claude Code/Desktop using **their own** ConnectWise keys (passed as
headers). The host stores **zero** ConnectWise credentials. A per-customer
gateway token gates access. No OAuth, no credential vault, no write tools.

## Architecture / data flow

```
Claude Code / Desktop (client)
   │  HTTPS POST /mcp
   │  headers:  X-Gateway-Key: <per-customer token>
   │            X-CW-Company-Id / -Public-Key / -Private-Key / -Client-Id / -Region
   ▼
Render (managed TLS)  →  uvicorn  →  Starlette app = FastMCP.http_app(middleware=[...])
   │
   ├─ GatewayAuthMiddleware  → validates X-Gateway-Key (401 if missing/invalid);
   │                           tags the request with the client label for logs
   ├─ /health route          → 200, no auth (Render health checks)
   └─ FastMCP MCP handler     → existing tools → get_credentials() reads X-CW-*
                                → ConnectWise API
```

The tenant identity *is* the ConnectWise keys; the gateway token is purely
access control plus a per-client label for logging/revocation.

## Components

### 1. Container (`Dockerfile`)
`python:3.12-slim`; install the package; run `python -m connectwise_mcp` in HTTP
mode bound to `0.0.0.0:$PORT`. No credentials baked into the image.

### 2. `config.py` adjustment
Resolve the HTTP port from `CW_MCP_PORT`, then fall back to `PORT` (the PaaS
convention), then `8000`. Allow the bind host to be set to `0.0.0.0` via
`CW_MCP_HOST` for the container. No other behavior change.

### 3. Gateway auth middleware (`src/connectwise_mcp/gateway_auth.py`, new)
An ASGI/Starlette middleware:
- Reads the `X-Gateway-Key` request header.
- Looks up `sha256(key)` in the configured token map.
- Returns `401` (JSON error, no detail that aids guessing) if the header is
  missing or the hash is not found.
- On success, stashes the client label (e.g. on `request.state`/scope) so log
  lines can be attributed to a client, then passes the request through.
- Exempts the `/health` path (no token required).
- Never logs the raw `X-Gateway-Key` or any `X-CW-*` value (uses M1 `redact()`
  discipline).

### 4. Token store
Environment variable `CW_GATEWAY_TOKENS` holding a JSON object mapping
`sha256(token)` → client-label, e.g.:
```json
{"<sha256hex>": "acme-msp", "<sha256hex>": "globex"}
```
The deployed env therefore never holds a usable raw token; the raw token lives
only with the client. A helper script `scripts/new_gateway_token.py` mints a
random token and prints both the token (to hand to the client) and its sha256
hash (to add to `CW_GATEWAY_TOKENS`). Loading parses the JSON once at startup;
a malformed/empty value is a fatal startup error (fail closed — never run the
gateway with auth effectively disabled).

### 5. Health route
`@mcp.custom_route("/health")` returning `{"status": "ok"}` with 200, no auth,
for Render health checks.

### 6. Server wiring (`server.py`)
In HTTP mode, build the Starlette app via `mcp.http_app(middleware=[...])` with
the gateway-auth middleware installed, register the `/health` route, and serve.
stdio mode (local dev) is unchanged and does NOT apply the gateway middleware.

### 7. Deployment (`render.yaml`)
A Render Blueprint defining the web service (Docker), a `/health` health-check
path, and env var placeholders (`CW_GATEWAY_TOKENS`, `CW_MCP_HOST=0.0.0.0`,
`CW_LOG_LEVEL`). Auto-deploy on push to `main` is enabled. Real secret values
are set in the Render dashboard, not committed.

### 8. Documentation
- `docs/hosting.md` (operator): deploy to Render via the Blueprint, set env vars,
  mint and issue per-client gateway tokens, rotate/revoke by editing
  `CW_GATEWAY_TOKENS`.
- Extend `docs/connecting.md` (client): connect a **remote** server from Claude
  Code (`claude mcp add --transport http <url> --header "X-Gateway-Key: ..."
  --header "X-CW-Company-Id: ..."` etc.), and from Claude Desktop via the
  `mcp-remote` bridge passing the same `--header` flags. Note the open question
  below about native Desktop remote support.

## Security model

- TLS everywhere (Render-managed HTTPS).
- Gateway tokens stored only as sha256 hashes; raw tokens held only by clients.
- Fail closed: the server refuses to start if `CW_GATEWAY_TOKENS` is missing or
  malformed.
- ConnectWise credentials are pass-through only — never persisted server-side.
- M1 redaction keeps CW credentials and PII out of logs; the gateway middleware
  must not log the gateway key.
- Per-client label logged for audit/troubleshooting.
- Documented residual risk: client CW credentials transit the server's memory
  and TLS termination in-flight (not stored, but in the blast radius).

## Testing

- New unit tests for `GatewayAuthMiddleware` using Starlette `TestClient`
  against `mcp.http_app(...)`:
  - valid `X-Gateway-Key` → request is authorized (not 401),
  - missing key → 401,
  - invalid/unknown key → 401,
  - `/health` reachable with no key → 200.
- New unit test that a malformed/empty `CW_GATEWAY_TOKENS` causes a fatal
  startup error (fail closed).
- All 19 existing tests stay green; CI runs the full suite across Python
  3.10–3.13 (unchanged matrix).

## Acceptance criteria

- Container builds; `render.yaml` deploys to Render with managed HTTPS and a
  passing `/health` check.
- A request to `/mcp` without a valid `X-Gateway-Key` is rejected with 401; a
  request with a valid token and valid `X-CW-*` headers returns ConnectWise data.
- `scripts/new_gateway_token.py` mints a token + hash; adding the hash to
  `CW_GATEWAY_TOKENS` authorizes that token.
- New middleware tests + the fail-closed test pass; full suite green in CI.
- **(Operator step)** Deploy to Render, mint a token, and connect **one** real
  client (you) from Claude Code against your live ConnectWise instance over the
  hosted URL; confirm a read (e.g. `/system/members`) succeeds end-to-end.

## Out of scope (later milestones)

Claude.ai web support, OAuth 2.1 authorization server, encrypted per-client
credential vault, write/action tools, rate limiting beyond the access gate,
billing/usage metering, multi-region deployment.

## Open question to resolve during implementation

Native remote-URL + custom-header support in **Claude Desktop's** config is
uncertain (Claude **Code** supports it directly; Desktop historically required
the `mcp-remote` stdio→HTTP bridge). The implementation must verify the working
path for Desktop and document whichever is correct; this does not block the
Render deployment or the Claude Code path.

## Deliverables

- `Dockerfile`
- `config.py` port/host adjustment
- `src/connectwise_mcp/gateway_auth.py` + wiring in `server.py`
- `/health` route
- `scripts/new_gateway_token.py`
- `render.yaml` (auto-deploy on push to main)
- `docs/hosting.md` + extended `docs/connecting.md`
- New tests (gateway auth + fail-closed)
