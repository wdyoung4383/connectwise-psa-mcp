# M2 — Hosted Pass-Through Gateway Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deploy the existing read-only ConnectWise MCP server to a public HTTPS URL (Render) gated by per-customer gateway tokens, so clients connect from Claude Code/Desktop with their own ConnectWise keys in headers — the host stores zero ConnectWise credentials.

**Architecture:** Add an ASGI gateway-auth middleware that validates an `X-Gateway-Key` header against a hashed token map (fail-closed at startup), expose an unauthenticated `/health` route, containerize, and deploy to Render with auto-deploy. The existing per-request `X-CW-*` credential pass-through and read-only tools are unchanged.

**Tech Stack:** Python 3.10–3.13, FastMCP 3.3.x (Starlette/uvicorn under the hood), httpx, Docker, Render.

**Repo:** https://github.com/wdyoung4383/connectwise-psa-mcp (local: `C:\Users\wdyou\connectwisemcp\connectwise-mcp`, branch `main`, commit straight to main).

**Spec:** `docs/superpowers/specs/2026-06-01-m2-hosted-passthrough-design.md`

---

## File Structure

**Create:**
- `src/connectwise_mcp/gateway_auth.py` — `load_gateway_tokens()` (fail-closed env parse) + `GatewayAuthMiddleware` (ASGI gate)
- `scripts/new_gateway_token.py` — mint a token + its sha256 hash
- `tests/test_gateway_auth.py` — token loading + middleware behavior
- `Dockerfile` — container image
- `render.yaml` — Render Blueprint (auto-deploy, /health check, env placeholders)
- `docs/hosting.md` — operator deploy + token issuance guide

**Modify:**
- `src/connectwise_mcp/config.py` — resolve HTTP port from `CW_MCP_PORT` → `PORT` → `8000`
- `src/connectwise_mcp/server.py` — add `/health` route; in HTTP mode load tokens (fail-closed) and install the gateway middleware
- `docs/connecting.md` — add a "remote (hosted)" connection section
- `tests/` — new test file as above

---

## Environment notes (for every task)
- Use `.venv/Scripts/python.exe` for all Python/pytest/ruff commands.
- The Bash tool's working directory may not persist between calls; if a command reports a missing path, prefix it with `cd /c/Users/wdyou/connectwisemcp/connectwise-mcp && <command>`.
- End every commit message with: `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`
- Ruff rules E,F,I,UP,B; line-length 88. Run `ruff check` + `ruff format` on files you create/modify before committing.
- pytest is configured with `asyncio_mode = "auto"` (so `async def test_...` runs without explicit marks; plain `def test_...` runs as sync).
- Commit (and push) straight to `main` after each task.

---

## Task 1: Resolve HTTP port from PORT (PaaS convention)

**Files:**
- Modify: `src/connectwise_mcp/config.py`
- Test: `tests/test_config.py` (new)

- [ ] **Step 1: Write the failing test**

Create `tests/test_config.py`:

```python
"""Tests for environment-driven config resolution."""

from connectwise_mcp.config import resolve_http_port


def test_port_prefers_cw_mcp_port(monkeypatch):
    monkeypatch.setenv("CW_MCP_PORT", "9001")
    monkeypatch.setenv("PORT", "12345")
    assert resolve_http_port() == 9001


def test_port_falls_back_to_PORT(monkeypatch):
    monkeypatch.delenv("CW_MCP_PORT", raising=False)
    monkeypatch.setenv("PORT", "12345")
    assert resolve_http_port() == 12345


def test_port_defaults_to_8000(monkeypatch):
    monkeypatch.delenv("CW_MCP_PORT", raising=False)
    monkeypatch.delenv("PORT", raising=False)
    assert resolve_http_port() == 8000
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_config.py -q`
Expected: FAIL — `ImportError: cannot import name 'resolve_http_port'`.

- [ ] **Step 3: Implement**

In `src/connectwise_mcp/config.py`, replace the line:
```python
HTTP_PORT = int(os.getenv("CW_MCP_PORT", "8000"))
```
with:
```python
def resolve_http_port() -> int:
    """HTTP port: CW_MCP_PORT, then the PaaS-provided PORT, then 8000."""
    return int(os.getenv("CW_MCP_PORT") or os.getenv("PORT") or "8000")


HTTP_PORT = resolve_http_port()
```
(Leave `HTTP_HOST = os.getenv("CW_MCP_HOST", "127.0.0.1")` unchanged — the container sets `CW_MCP_HOST=0.0.0.0` via env.)

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_config.py -q`
Expected: `3 passed`.

- [ ] **Step 5: Lint + full suite**

Run: `.venv/Scripts/python.exe -m ruff check src/connectwise_mcp/config.py tests/test_config.py && .venv/Scripts/python.exe -m ruff format --check src/connectwise_mcp/config.py tests/test_config.py && .venv/Scripts/python.exe -m pytest -q`
Expected: clean; `22 passed` (19 existing + 3 new).

- [ ] **Step 6: Commit + push**

```bash
git add src/connectwise_mcp/config.py tests/test_config.py
git commit -m "feat: resolve HTTP port from PORT env for PaaS hosting"
git push origin main
```

---

## Task 2: Gateway token loading (fail-closed)

**Files:**
- Create: `src/connectwise_mcp/gateway_auth.py`
- Test: `tests/test_gateway_auth.py` (new)

- [ ] **Step 1: Write the failing test**

Create `tests/test_gateway_auth.py`:

```python
"""Tests for gateway token loading and the gateway-auth ASGI middleware."""

import hashlib

import pytest

from connectwise_mcp.gateway_auth import load_gateway_tokens

_TOKEN = "test-token-abc123"
_HASH = hashlib.sha256(_TOKEN.encode()).hexdigest()


def test_load_tokens_parses_hash_map(monkeypatch):
    monkeypatch.setenv("CW_GATEWAY_TOKENS", f'{{"{_HASH}": "acme"}}')
    tokens = load_gateway_tokens()
    assert tokens[_HASH] == "acme"


def test_load_tokens_missing_env_fails_closed(monkeypatch):
    monkeypatch.delenv("CW_GATEWAY_TOKENS", raising=False)
    with pytest.raises(RuntimeError):
        load_gateway_tokens()


def test_load_tokens_malformed_json_fails_closed(monkeypatch):
    monkeypatch.setenv("CW_GATEWAY_TOKENS", "not json")
    with pytest.raises(RuntimeError):
        load_gateway_tokens()


def test_load_tokens_empty_object_fails_closed(monkeypatch):
    monkeypatch.setenv("CW_GATEWAY_TOKENS", "{}")
    with pytest.raises(RuntimeError):
        load_gateway_tokens()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_gateway_auth.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'connectwise_mcp.gateway_auth'`.

- [ ] **Step 3: Implement the loader**

Create `src/connectwise_mcp/gateway_auth.py`:

```python
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
```

(The middleware class is added in Task 3 — leave the import of `JSONResponse` and the `_EXEMPT_PATHS` constant in place now; they are used next.)

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_gateway_auth.py -q`
Expected: `4 passed`.

- [ ] **Step 5: Lint**

Run: `.venv/Scripts/python.exe -m ruff check src/connectwise_mcp/gateway_auth.py tests/test_gateway_auth.py && .venv/Scripts/python.exe -m ruff format --check src/connectwise_mcp/gateway_auth.py tests/test_gateway_auth.py`
Expected: clean. NOTE: ruff rule F401 will flag `JSONResponse` and `_EXEMPT_PATHS` as unused until Task 3 adds the middleware. If that happens, proceed to Task 3 in the SAME commit instead of committing a failing-lint state — i.e., combine Task 2 + Task 3 into one commit. (See Task 3 Step 6.) Do not add `# noqa`.

- [ ] **Step 6: (Conditional) Commit**

If lint is clean (no unused-import flag), commit now:
```bash
git add src/connectwise_mcp/gateway_auth.py tests/test_gateway_auth.py
git commit -m "feat: load gateway tokens from env (fail-closed)"
git push origin main
```
Otherwise, leave staged and complete Task 3, committing both together.

---

## Task 3: Gateway-auth ASGI middleware

**Files:**
- Modify: `src/connectwise_mcp/gateway_auth.py`
- Test: `tests/test_gateway_auth.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_gateway_auth.py`:

```python
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.responses import PlainTextResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from connectwise_mcp.gateway_auth import GatewayAuthMiddleware


def _client():
    async def ok(request):
        return PlainTextResponse("ok")

    app = Starlette(
        routes=[Route("/mcp", ok), Route("/health", ok)],
        middleware=[Middleware(GatewayAuthMiddleware, token_map={_HASH: "acme"})],
    )
    return TestClient(app)


def test_valid_key_is_authorized():
    r = _client().get("/mcp", headers={"X-Gateway-Key": _TOKEN})
    assert r.status_code == 200
    assert r.text == "ok"


def test_missing_key_rejected():
    r = _client().get("/mcp")
    assert r.status_code == 401


def test_invalid_key_rejected():
    r = _client().get("/mcp", headers={"X-Gateway-Key": "wrong"})
    assert r.status_code == 401


def test_health_is_exempt():
    r = _client().get("/health")  # no key
    assert r.status_code == 200
    assert r.text == "ok"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_gateway_auth.py -q`
Expected: FAIL — `ImportError: cannot import name 'GatewayAuthMiddleware'`.

- [ ] **Step 3: Implement the middleware**

Append to `src/connectwise_mcp/gateway_auth.py`:

```python
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
        label = (
            self.token_map.get(hashlib.sha256(key).hexdigest()) if key else None
        )
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_gateway_auth.py -q`
Expected: `8 passed` (4 loader + 4 middleware).

- [ ] **Step 5: Lint + full suite**

Run: `.venv/Scripts/python.exe -m ruff check . && .venv/Scripts/python.exe -m ruff format --check . && .venv/Scripts/python.exe -m pytest -q`
Expected: clean; `30 passed` (22 + 8).

- [ ] **Step 6: Commit + push**

Stage gateway_auth.py and its tests (plus Task 2's files if they were left staged), then:
```bash
git add src/connectwise_mcp/gateway_auth.py tests/test_gateway_auth.py
git commit -m "feat: add gateway-auth ASGI middleware (X-Gateway-Key, /health exempt)"
git push origin main
```

---

## Task 4: Wire health route + gateway middleware into the server

**Files:**
- Modify: `src/connectwise_mcp/server.py`
- Test: `tests/test_server_wiring.py` (new)

- [ ] **Step 1: Write the failing tests**

Create `tests/test_server_wiring.py`:

```python
"""Tests for the /health route and fail-closed HTTP startup."""

import json

import pytest
from starlette.requests import Request


async def test_health_returns_ok():
    from connectwise_mcp.server import health

    req = Request({"type": "http", "method": "GET", "path": "/health", "headers": []})
    resp = await health(req)
    assert resp.status_code == 200
    assert json.loads(resp.body) == {"status": "ok"}


def test_main_http_fails_closed_without_tokens(monkeypatch):
    monkeypatch.setenv("CW_MCP_TRANSPORT", "http")
    monkeypatch.delenv("CW_GATEWAY_TOKENS", raising=False)
    from connectwise_mcp.server import main

    # Should raise (fail closed) BEFORE attempting to bind/serve.
    with pytest.raises(RuntimeError):
        main()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_server_wiring.py -q`
Expected: FAIL — `ImportError: cannot import name 'health'` (and the fail-closed test errors because main() doesn't yet load tokens).

- [ ] **Step 3: Implement the health route**

In `src/connectwise_mcp/server.py`, add these imports near the other imports at the top (after the existing `from .` imports):
```python
from starlette.requests import Request
from starlette.responses import JSONResponse

from .gateway_auth import GatewayAuthMiddleware, load_gateway_tokens
```

Then, after the `mcp = FastMCP(...)` definition and the existing tool definitions (anywhere at module level after `mcp` exists), add the health route. Use the explicit-call form so the `health` name stays bound to the function regardless of what the decorator returns:
```python
async def health(request: Request) -> JSONResponse:
    """Unauthenticated liveness check for the hosting platform."""
    return JSONResponse({"status": "ok"})


mcp.custom_route("/health", methods=["GET"])(health)
```

- [ ] **Step 4: Implement fail-closed startup + middleware in main()**

In `src/connectwise_mcp/server.py`, replace the HTTP branch of `main()`. The current `main()` is:
```python
def main() -> None:
    """Run the server. Defaults to HTTP; set CW_MCP_TRANSPORT=stdio for local."""
    import os

    configure_logging()
    transport = os.getenv("CW_MCP_TRANSPORT", "http")
    if transport == "stdio":
        mcp.run()
    else:
        mcp.run(transport="http", host=config.HTTP_HOST, port=config.HTTP_PORT)
```
Replace it with:
```python
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
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_server_wiring.py -q`
Expected: `2 passed`. (The fail-closed test passes because `load_gateway_tokens()` raises `RuntimeError` before `mcp.run` is ever called, so no server is started.)

- [ ] **Step 6: Confirm the entry point still imports and stdio is unaffected**

Run: `.venv/Scripts/python.exe -c "import connectwise_mcp.__main__; from connectwise_mcp.server import health, main; print('import ok')"`
Expected: prints `import ok`.

- [ ] **Step 7: Lint + full suite**

Run: `.venv/Scripts/python.exe -m ruff check . && .venv/Scripts/python.exe -m ruff format --check . && .venv/Scripts/python.exe -m pytest -q`
Expected: clean; `32 passed` (30 + 2).

- [ ] **Step 8: Commit + push**

```bash
git add src/connectwise_mcp/server.py tests/test_server_wiring.py
git commit -m "feat: add /health route and gate hosted HTTP behind gateway middleware"
git push origin main
```

---

## Task 5: Token-minting script

**Files:**
- Modify: `pyproject.toml` (add `pythonpath = ["."]` so `scripts` is importable in tests under any pytest invocation)
- Create: `scripts/__init__.py`, `scripts/new_gateway_token.py`
- Test: `tests/test_new_gateway_token.py` (new)

- [ ] **Step 1: Write the failing test**

Create `tests/test_new_gateway_token.py`:

```python
"""Test the gateway-token minting helper."""

import hashlib


def test_mint_produces_consistent_hash():
    from scripts.new_gateway_token import mint

    token, token_hash = mint()
    assert isinstance(token, str) and len(token) >= 20
    assert token_hash == hashlib.sha256(token.encode()).hexdigest()


def test_mint_is_random():
    from scripts.new_gateway_token import mint

    assert mint()[0] != mint()[0]
```

NOTE: importing `scripts.new_gateway_token` requires `scripts/__init__.py` to exist. Create an empty `scripts/__init__.py` if one is not present (the test import depends on it).

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_new_gateway_token.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'scripts.new_gateway_token'` (or `scripts`).

- [ ] **Step 3: Implement**

First, make `scripts` importable under any pytest invocation (CI runs `pytest -q`, which does not put the repo root on `sys.path`). In `pyproject.toml`, find the `[tool.pytest.ini_options]` section and add a `pythonpath` entry so it reads:
```toml
[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
pythonpath = ["."]
```
(Keep any existing keys in that section; just add the `pythonpath` line.)

Create `scripts/__init__.py` (empty file).

Create `scripts/new_gateway_token.py`:

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_new_gateway_token.py -q`
Expected: `2 passed`.

- [ ] **Step 5: Smoke-run the script**

Run: `.venv/Scripts/python.exe scripts/new_gateway_token.py acme-msp`
Expected: prints four lines (label, token, sha256, CW_GATEWAY_TOKENS entry).

- [ ] **Step 6: Lint + full suite**

Run: `.venv/Scripts/python.exe -m ruff check . && .venv/Scripts/python.exe -m ruff format --check . && .venv/Scripts/python.exe -m pytest -q`
Expected: clean; `34 passed` (32 + 2).

- [ ] **Step 7: Commit + push**

```bash
git add pyproject.toml scripts/__init__.py scripts/new_gateway_token.py tests/test_new_gateway_token.py
git commit -m "feat: add gateway-token minting script"
git push origin main
```

---

## Task 6: Container + Render Blueprint

**Files:**
- Create: `Dockerfile`
- Create: `render.yaml`
- Create: `.dockerignore`

- [ ] **Step 1: Create the Dockerfile**

Create `Dockerfile`:

```dockerfile
FROM python:3.12-slim

WORKDIR /app

# Install the package (non-editable). pyproject's force-include bundles the
# OpenAPI data file into the wheel.
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir .

# Hosted defaults; PORT is injected by the platform at runtime.
ENV CW_MCP_TRANSPORT=http \
    CW_MCP_HOST=0.0.0.0

EXPOSE 8000

CMD ["python", "-m", "connectwise_mcp"]
```

- [ ] **Step 2: Create .dockerignore**

Create `.dockerignore`:

```
.venv/
__pycache__/
*.pyc
.git/
.github/
docs/
tests/
.env
.pytest_cache/
*.egg-info/
requirements-dev.lock
```

- [ ] **Step 3: Create render.yaml**

Create `render.yaml`:

```yaml
# Render Blueprint. After committing, create a new Blueprint in the Render
# dashboard pointed at this repo, then set CW_GATEWAY_TOKENS (a secret) there.
services:
  - type: web
    name: connectwise-psa-mcp
    runtime: docker
    plan: free  # free instances sleep when idle; bump to "starter" for always-on
    healthCheckPath: /health
    autoDeploy: true
    envVars:
      - key: CW_MCP_HOST
        value: "0.0.0.0"
      - key: CW_LOG_LEVEL
        value: INFO
      - key: CW_GATEWAY_TOKENS
        sync: false  # set in the Render dashboard (secret); JSON {sha256: label}
```

- [ ] **Step 4: Validate the YAML and Dockerfile locally**

Run: `.venv/Scripts/python.exe -c "import yaml; yaml.safe_load(open('render.yaml')); print('render.yaml ok')"`
Expected: prints `render.yaml ok`.

Run: `.venv/Scripts/python.exe -c "t=open('Dockerfile').read(); assert 'python -m' in t.replace(chr(34),'') or 'connectwise_mcp' in t; assert 'CW_MCP_HOST=0.0.0.0' in t; print('dockerfile ok')"`
Expected: prints `dockerfile ok`.

NOTE: An actual `docker build` and deploy is the operator's step (Docker may not be available in this environment, and CI installs from pyproject, not Docker). Do NOT block on running `docker build`. If Docker IS available and you want extra confidence, `docker build -t cw-mcp .` should succeed — but it is optional.

- [ ] **Step 5: Commit + push**

```bash
git add Dockerfile .dockerignore render.yaml
git commit -m "build: add Dockerfile and Render Blueprint for hosted deployment"
git push origin main
```

---

## Task 7: Operator + client connection docs

**Files:**
- Create: `docs/hosting.md`
- Modify: `docs/connecting.md`

- [ ] **Step 1: Write the operator hosting guide**

Create `docs/hosting.md`:

````markdown
# Hosting the ConnectWise PSA MCP server (Render)

This deploys the **read-only** server to a public HTTPS URL. Clients connect
from Claude Code/Desktop and pass **their own** ConnectWise keys as headers — the
host stores no ConnectWise credentials. A per-customer **gateway token** gates
access.

## 1. Deploy to Render

1. Push this repo to GitHub (already done).
2. In the Render dashboard: **New → Blueprint**, point it at this repo. Render
   reads `render.yaml` and creates the `connectwise-psa-mcp` web service.
3. Set the secret env var **`CW_GATEWAY_TOKENS`** (see step 2 below) in the
   service's Environment settings. The service will not start without it
   (fail-closed).
4. Render builds the Docker image and gives you a URL like
   `https://connectwise-psa-mcp.onrender.com`. The MCP endpoint is that URL + `/mcp`.

> The free plan sleeps when idle (slow first request). For always-on, change
> `plan: free` to `plan: starter` in `render.yaml`.

## 2. Mint and issue gateway tokens

For each client, mint a token:

```bash
python scripts/new_gateway_token.py acme-msp
```

This prints a raw **token** (give it to the client) and its **sha256 hash**.
Add the hash to `CW_GATEWAY_TOKENS`, which is a JSON object mapping
`sha256(token) -> client-label`:

```json
{"<sha256-of-acme-token>": "acme-msp", "<sha256-of-globex-token>": "globex"}
```

Set that JSON as the `CW_GATEWAY_TOKENS` env var in Render. To **revoke** a
client, remove their entry and redeploy. The server stores only hashes, never
the raw tokens.

## 3. Verify

```bash
curl https://<your-app>.onrender.com/health        # -> {"status":"ok"}
curl -i https://<your-app>.onrender.com/mcp         # -> 401 (no gateway key)
```

Then connect a client (see `docs/connecting.md`, "Remote (hosted)" section) and
ask it to list the ConnectWise modules.

## Security notes

- TLS is managed by Render.
- Gateway tokens are stored only as sha256 hashes; raw tokens live with clients.
- ConnectWise credentials are pass-through only and are never stored server-side.
- Logs never contain credentials or the gateway key (see `logging_setup.redact`).
- Residual risk: client ConnectWise credentials transit the server's memory and
  TLS termination in flight (they are not persisted, but they are processed).
````

- [ ] **Step 2: Extend the connection guide with a remote section**

In `docs/connecting.md`, append the following new section at the end of the file:

````markdown
## Remote (hosted) — connecting to a deployed server

If the server is hosted (see `docs/hosting.md`), clients connect to its public
URL and supply both a **gateway token** and their **ConnectWise keys** as headers.

### Claude Code

```bash
claude mcp add connectwise-psa \
  --transport http \
  https://<your-app>.onrender.com/mcp \
  --header "X-Gateway-Key: <your-gateway-token>" \
  --header "X-CW-Company-Id: your_company_id" \
  --header "X-CW-Public-Key: your_public_key" \
  --header "X-CW-Private-Key: your_private_key" \
  --header "X-CW-Client-Id: your_client_id_guid" \
  --header "X-CW-Region: na"
```

Then `claude mcp list` to confirm it's registered.

### Claude Desktop

Claude Desktop reaches remote MCP servers through the `mcp-remote` bridge. Add
this to `claude_desktop_config.json` (Settings → Developer → Edit Config):

```json
{
  "mcpServers": {
    "connectwise-psa": {
      "command": "npx",
      "args": [
        "-y", "mcp-remote",
        "https://<your-app>.onrender.com/mcp",
        "--header", "X-Gateway-Key: <your-gateway-token>",
        "--header", "X-CW-Company-Id: your_company_id",
        "--header", "X-CW-Public-Key: your_public_key",
        "--header", "X-CW-Private-Key: your_private_key",
        "--header", "X-CW-Client-Id: your_client_id_guid",
        "--header", "X-CW-Region: na"
      ]
    }
  }
}
```

(Requires Node.js for `npx`.) Restart Claude Desktop; the `connectwise-psa`
tools should appear.

> Note: native remote-server + custom-header support in Claude Desktop's config
> has varied across versions; the `mcp-remote` bridge above is the reliable path.
> Claude Code supports `--transport http --header` directly.
````

- [ ] **Step 3: Verify docs exist and reference the right things**

Run: `.venv/Scripts/python.exe -c "h=open('docs/hosting.md').read(); c=open('docs/connecting.md').read(); assert 'CW_GATEWAY_TOKENS' in h and 'X-Gateway-Key' in c and 'mcp-remote' in c; print('docs ok')"`
Expected: prints `docs ok`.

- [ ] **Step 4: Commit + push**

```bash
git add docs/hosting.md docs/connecting.md
git commit -m "docs: add hosting guide and remote connection instructions"
git push origin main
```

---

## Final verification (after all tasks)

- [ ] `.venv/Scripts/python.exe -m pytest -q` → `34 passed`
- [ ] `.venv/Scripts/python.exe -m ruff check . && .venv/Scripts/python.exe -m ruff format --check .` → clean
- [ ] CI green on `main` across Python 3.10–3.13
- [ ] **(Operator step)** Create the Render Blueprint, set `CW_GATEWAY_TOKENS`, deploy; `curl /health` returns ok and `curl /mcp` returns 401 without a key; then connect one real client from Claude Code with a minted token + your ConnectWise keys and confirm a live read (e.g. ask it to list modules / read `/system/members`).

---

## Notes for the implementer

- All `python` invocations assume the project venv at `.venv/Scripts/python.exe` (Windows). On macOS/Linux use `.venv/bin/python`.
- The Bash tool's working directory may not persist between calls; prefix commands with `cd /c/Users/wdyou/connectwisemcp/connectwise-mcp &&` if a command reports a missing path.
- `ASGIMiddleware` in FastMCP is an alias for `starlette.middleware.Middleware`; the `middleware=` kwarg on `mcp.run(transport="http", ...)` takes a list of `Middleware(Cls, **kwargs)` wrappers (verified on fastmcp 3.3.1).
- This milestone adds NO write capability and does NOT change the read tools. The only request-path change is the gateway gate (new) in front of the existing handler.
- Do not touch the pre-existing `cw_get.__doc__` issue (tracked separately).
