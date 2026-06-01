# M1 — Trustworthy Read-Only Core Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Harden the existing read-only ConnectWise PSA MCP gateway into a trustworthy state — reproducible dependencies, CI, consistent style, safe logging/errors — and provide a one-command path to validate it against a live instance.

**Architecture:** No tool behavior changes. Add a `logging_setup` module (logging config + a single `redact()` credential guard), thread structured request logging and clearer error mapping through the existing `executor.cw_get`, and add tooling (pinned deps, ruff, GitHub Actions CI) plus a user-run live smoke script and connection docs.

**Tech Stack:** Python 3.10–3.13, FastMCP 3.x, httpx, pytest, ruff, GitHub Actions.

**Repo:** https://github.com/wdyoung4383/connectwise-psa-mcp (local: `C:\Users\wdyou\connectwisemcp\connectwise-mcp`)

**Spec:** `docs/superpowers/specs/2026-06-01-m1-trustworthy-read-only-core-design.md`

---

## File Structure

**Create:**
- `src/connectwise_mcp/logging_setup.py` — logging configuration + `redact()` credential guard
- `src/connectwise_mcp/__main__.py` — enables `python -m connectwise_mcp` (cross-platform launch for MCP clients)
- `tests/test_redaction.py` — unit tests for `redact()` and no-leak logging
- `tests/test_executor_errors.py` — error-mapping tests for `cw_get`
- `.github/workflows/ci.yml` — CI: ruff + pytest across Python 3.10–3.13
- `requirements-dev.lock` — captured dependency snapshot (reference repro)
- `scripts/smoke_live.py` — live read smoke test (user-run, reads `CW_*` from `.env`)
- `docs/connecting.md` — stdio connection guide (Claude Desktop + Claude Code)

**Modify:**
- `pyproject.toml` — dependency pins, ruff dep + config
- `README.md` — CI status badge
- `src/connectwise_mcp/executor.py` — request logging + error mapping (currently lines 8–16 imports, 81–89 request/response)
- `src/connectwise_mcp/server.py` — call `configure_logging()` in `main()` (currently lines 135–143)

---

## Task 1: Pin dependencies and add ruff config

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Pin runtime deps and add ruff to dev deps**

In `pyproject.toml`, replace the `dependencies` and `optional-dependencies` blocks:

```toml
dependencies = [
    "fastmcp>=3.3,<4",
    "httpx>=0.27,<1",
]

[project.optional-dependencies]
dev = ["pytest>=8", "pytest-asyncio>=0.23", "ruff>=0.6"]
```

- [ ] **Step 2: Add ruff configuration**

Append to the end of `pyproject.toml`:

```toml
[tool.ruff]
line-length = 88
target-version = "py310"

[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B"]
```

- [ ] **Step 3: Reinstall to pick up ruff**

Run: `.venv/Scripts/python.exe -m pip install -e ".[dev]"`
Expected: installs `ruff`; no resolution errors.

- [ ] **Step 4: Verify pins resolve to known-good versions**

Run: `.venv/Scripts/python.exe -c "import fastmcp, httpx; print(fastmcp.__version__, httpx.__version__)"`
Expected: prints `3.3.1 0.28.1` (or any `3.3.x` / `0.28–0.x` within the caps).

- [ ] **Step 5: Run existing tests to confirm nothing broke**

Run: `.venv/Scripts/python.exe -m pytest -q`
Expected: `5 passed`.

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml
git commit -m "build: pin fastmcp/httpx and add ruff config"
```

---

## Task 2: Apply ruff formatting and lint to the existing tree

**Files:**
- Modify: `src/connectwise_mcp/*.py`, `tests/test_catalog.py` (formatting only)

- [ ] **Step 1: Auto-fix lint findings**

Run: `.venv/Scripts/python.exe -m ruff check . --fix`
Expected: applies import sorting (`I`) and any safe fixes; prints remaining issues, if any.

- [ ] **Step 2: Apply formatting**

Run: `.venv/Scripts/python.exe -m ruff format .`
Expected: reformats files; prints "N files reformatted".

- [ ] **Step 3: Resolve any residual lint findings**

Run: `.venv/Scripts/python.exe -m ruff check .`
Expected: `All checks passed!`

If a residual finding remains (most likely `E501` on a long string literal in `catalog.py`, `conditions.py`, or `executor.py` that the formatter cannot wrap), fix it by manually breaking the string across lines using implicit string concatenation, e.g.:

```python
raise ExecutionError(
    f"Path {path!r} is not in this server's read scope. "
    "Use search_endpoints to find a valid path."
)
```

Re-run `ruff check .` until it prints `All checks passed!`. Do **not** use `# noqa` unless a finding is genuinely unavoidable.

- [ ] **Step 4: Confirm tests still pass after formatting**

Run: `.venv/Scripts/python.exe -m pytest -q`
Expected: `5 passed`.

- [ ] **Step 5: Commit (formatting isolated from logic)**

```bash
git add -A
git commit -m "style: apply ruff format and lint to existing tree"
```

---

## Task 3: Add logging setup and credential redaction

**Files:**
- Create: `src/connectwise_mcp/logging_setup.py`
- Test: `tests/test_redaction.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_redaction.py`:

```python
"""Tests for logging configuration and the credential-redaction guard."""

import logging

from connectwise_mcp.logging_setup import redact


def test_redact_masks_secret_dict_keys():
    out = redact(
        {
            "Authorization": "Basic abc",
            "clientId": "guid-value",
            "Accept": "application/json",
        }
    )
    assert out["Authorization"] == "***"
    assert out["clientId"] == "***"
    assert out["Accept"] == "application/json"


def test_redact_is_case_insensitive_and_recursive():
    out = redact({"headers": {"X-CW-Private-Key": "secret"}})
    assert out["headers"]["X-CW-Private-Key"] == "***"


def test_redact_masks_basic_token_in_strings():
    out = redact("auth=Basic Zm9vOmJhcg==")
    assert "Zm9vOmJhcg==" not in out
    assert "***" in out


def test_redact_passes_through_safe_values():
    assert redact("/service/tickets") == "/service/tickets"
    assert redact(42) == 42


def test_redacted_value_not_in_log_output(caplog):
    with caplog.at_level(logging.INFO):
        logging.getLogger("test").info(
            "headers=%s", redact({"Authorization": "Basic supersecret"})
        )
    assert "supersecret" not in caplog.text
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_redaction.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'connectwise_mcp.logging_setup'`.

- [ ] **Step 3: Implement the logging module**

Create `src/connectwise_mcp/logging_setup.py`:

```python
"""Logging configuration and credential redaction for the ConnectWise gateway.

The gateway brokers tenants' ConnectWise credentials, so nothing logged may ever
contain them. ``redact()`` is the single guard: run any structure through it
before logging. ``configure_logging()`` sets up format/level once at startup.
"""

from __future__ import annotations

import logging
import os
import re
from typing import Any

# Header/env keys whose VALUES are secret and must never appear in logs.
_SECRET_KEYS = {
    "authorization",
    "clientid",
    "x-cw-company-id",
    "x-cw-public-key",
    "x-cw-private-key",
    "x-cw-client-id",
    "cw_company_id",
    "cw_public_key",
    "cw_private_key",
    "cw_client_id",
}

_REDACTED = "***"

# Matches an HTTP Basic auth token, e.g. "Basic dXNlcjpwYXNz".
_BASIC_RE = re.compile(r"Basic\s+[A-Za-z0-9+/=]+")


def redact(value: Any) -> Any:
    """Return a copy of ``value`` with credentials masked.

    Recurses through dicts and lists. Dict entries whose key (case-insensitive)
    names a secret are masked. Strings have embedded Basic-auth tokens masked.
    Other values pass through unchanged.
    """
    if isinstance(value, dict):
        return {
            k: (_REDACTED if str(k).lower() in _SECRET_KEYS else redact(v))
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [redact(v) for v in value]
    if isinstance(value, str):
        return _BASIC_RE.sub("Basic " + _REDACTED, value)
    return value


def configure_logging(level: str | None = None) -> None:
    """Configure root logging once, honoring CW_LOG_LEVEL (default INFO)."""
    level_name = (level or os.getenv("CW_LOG_LEVEL", "INFO")).upper()
    logging.basicConfig(
        level=getattr(logging, level_name, logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_redaction.py -q`
Expected: `5 passed`.

- [ ] **Step 5: Lint the new file**

Run: `.venv/Scripts/python.exe -m ruff check src/connectwise_mcp/logging_setup.py tests/test_redaction.py`
Expected: `All checks passed!` (run `ruff format` on them if needed).

- [ ] **Step 6: Commit**

```bash
git add src/connectwise_mcp/logging_setup.py tests/test_redaction.py
git commit -m "feat: add logging config and credential redaction guard"
```

---

## Task 4: Add request logging and error mapping to the executor

**Files:**
- Modify: `src/connectwise_mcp/executor.py`
- Test: `tests/test_executor_errors.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_executor_errors.py`:

```python
"""Error-mapping and logging tests for executor.cw_get (no real network)."""

import logging

import httpx
import pytest

from connectwise_mcp.catalog import load_catalog
from connectwise_mcp.executor import ExecutionError, cw_get

CATALOG = load_catalog()


class FakeClient:
    """Minimal stand-in for httpx.AsyncClient.get used by cw_get."""

    def __init__(self, *, response=None, raise_exc=None):
        self._response = response
        self._raise = raise_exc
        self.last_params = None

    async def get(self, url, params=None):
        self.last_params = params
        if self._raise is not None:
            raise self._raise
        return self._response


def _resp(status, *, text="", json_body=None):
    request = httpx.Request("GET", "https://example/api")
    if json_body is not None:
        return httpx.Response(status, json=json_body, request=request)
    return httpx.Response(status, text=text, request=request)


async def test_success_returns_json():
    client = FakeClient(response=_resp(200, json_body=[{"id": 1}]))
    out = await cw_get(client, CATALOG, "/service/boards")
    assert out == [{"id": 1}]


async def test_auth_error_maps_to_clean_message():
    client = FakeClient(response=_resp(401, text="unauthorized"))
    with pytest.raises(ExecutionError) as ei:
        await cw_get(client, CATALOG, "/service/boards")
    msg = str(ei.value)
    assert "401" in msg
    assert "authentication failed" in msg.lower()


async def test_not_found_maps_to_404_message():
    client = FakeClient(response=_resp(404, text="missing"))
    with pytest.raises(ExecutionError) as ei:
        await cw_get(client, CATALOG, "/service/boards")
    assert "404" in str(ei.value)


async def test_validation_error_includes_redacted_detail():
    client = FakeClient(response=_resp(400, text="bad value Basic Zm9vOmJhcg=="))
    with pytest.raises(ExecutionError) as ei:
        await cw_get(client, CATALOG, "/service/boards")
    msg = str(ei.value)
    assert "400" in msg
    assert "Zm9vOmJhcg==" not in msg  # Basic token redacted from CW's body


async def test_timeout_maps_to_clean_message():
    client = FakeClient(raise_exc=httpx.TimeoutException("slow"))
    with pytest.raises(ExecutionError) as ei:
        await cw_get(client, CATALOG, "/service/boards")
    assert "timed out" in str(ei.value).lower()


async def test_transport_error_maps_to_clean_message():
    client = FakeClient(raise_exc=httpx.ConnectError("no route"))
    with pytest.raises(ExecutionError) as ei:
        await cw_get(client, CATALOG, "/service/boards")
    assert "could not reach" in str(ei.value).lower()


async def test_request_log_has_status_but_no_conditions(caplog):
    client = FakeClient(response=_resp(200, json_body=[]))
    with caplog.at_level(logging.INFO):
        await cw_get(
            client, CATALOG, "/service/boards", conditions="company/identifier='ACME'"
        )
    assert "/service/boards" in caplog.text
    assert "200" in caplog.text
    assert "ACME" not in caplog.text  # condition values must not be logged
```

(`asyncio_mode = "auto"` in `pyproject.toml` runs these `async def` tests without explicit marks.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_executor_errors.py -q`
Expected: FAIL — `test_auth_error_maps_to_clean_message` fails because the current message is `"ConnectWise returned 401: ..."` (no "authentication failed"), and the timeout/transport tests error out because httpx exceptions are not yet caught.

- [ ] **Step 3: Update executor imports and module logger**

In `src/connectwise_mcp/executor.py`, replace the import block (current lines 8–16):

```python
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
```

- [ ] **Step 4: Replace the request/response block with logging + error mapping**

In `src/connectwise_mcp/executor.py`, replace the final request/response block (current lines 81–89, from `resp = await client.get(...)` through the `return {"raw": resp.text}`):

```python
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
```

- [ ] **Step 5: Run the new tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_executor_errors.py -q`
Expected: `7 passed`.

- [ ] **Step 6: Run the full suite**

Run: `.venv/Scripts/python.exe -m pytest -q`
Expected: `17 passed` (5 catalog + 5 redaction + 7 executor-errors).

- [ ] **Step 7: Lint**

Run: `.venv/Scripts/python.exe -m ruff check . && .venv/Scripts/python.exe -m ruff format --check .`
Expected: `All checks passed!` and no reformat needed (run `ruff format .` first if it reports changes).

- [ ] **Step 8: Commit**

```bash
git add src/connectwise_mcp/executor.py tests/test_executor_errors.py
git commit -m "feat: structured request logging and clearer error mapping in cw_get"
```

---

## Task 5: Configure logging at startup and enable `python -m connectwise_mcp`

**Files:**
- Modify: `src/connectwise_mcp/server.py`
- Create: `src/connectwise_mcp/__main__.py`

- [ ] **Step 1: Call configure_logging() in main()**

In `src/connectwise_mcp/server.py`, update the imports near the top (after the existing `from .executor import ...` line) to add:

```python
from .logging_setup import configure_logging
```

Then replace the body of `main()` (current lines 135–143) so logging is configured first:

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

- [ ] **Step 2: Create the module entry point**

Create `src/connectwise_mcp/__main__.py`:

```python
"""Enable ``python -m connectwise_mcp`` (used by MCP client configs)."""

from .server import main

if __name__ == "__main__":
    main()
```

- [ ] **Step 3: Verify the module launches over stdio without real creds**

Run (stdio server starts then we interrupt it; we only need it to start cleanly):
`.venv/Scripts/python.exe -c "import connectwise_mcp.__main__ as m; print('entrypoint import ok')"`
Expected: prints `entrypoint import ok` with no error.

- [ ] **Step 4: Confirm full suite still passes**

Run: `.venv/Scripts/python.exe -m pytest -q`
Expected: `17 passed`.

- [ ] **Step 5: Lint**

Run: `.venv/Scripts/python.exe -m ruff check src/connectwise_mcp/__main__.py src/connectwise_mcp/server.py`
Expected: `All checks passed!`

- [ ] **Step 6: Commit**

```bash
git add src/connectwise_mcp/server.py src/connectwise_mcp/__main__.py
git commit -m "feat: configure logging at startup; add python -m entry point"
```

---

## Task 6: Add GitHub Actions CI and README badge

**Files:**
- Create: `.github/workflows/ci.yml`
- Modify: `README.md`

- [ ] **Step 1: Create the CI workflow**

Create `.github/workflows/ci.yml`:

```yaml
name: CI

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  test:
    runs-on: ubuntu-latest
    strategy:
      fail-fast: false
      matrix:
        python-version: ["3.10", "3.11", "3.12", "3.13"]
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: ${{ matrix.python-version }}
      - run: python -m pip install --upgrade pip
      - run: pip install -e ".[dev]"
      - run: ruff check .
      - run: ruff format --check .
      - run: pytest -q
```

- [ ] **Step 2: Add the CI badge to the README**

In `README.md`, insert this line immediately under the title `# ConnectWise PSA MCP Server (read-only)`:

```markdown
[![CI](https://github.com/wdyoung4383/connectwise-psa-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/wdyoung4383/connectwise-psa-mcp/actions/workflows/ci.yml)
```

- [ ] **Step 3: Validate the workflow YAML locally**

Run: `.venv/Scripts/python.exe -c "import yaml,sys; yaml.safe_load(open('.github/workflows/ci.yml')); print('yaml ok')"`
Expected: prints `yaml ok`. (If PyYAML is missing, install it ad hoc: `.venv/Scripts/python.exe -m pip install pyyaml`, or skip — GitHub will validate on push.)

- [ ] **Step 4: Commit and push to trigger CI**

```bash
git add .github/workflows/ci.yml README.md
git commit -m "ci: add GitHub Actions pytest+ruff matrix and README badge"
git push origin main
```

- [ ] **Step 5: Verify CI is green**

Run: `gh run watch $(gh run list --workflow=ci.yml --limit 1 --json databaseId --jq '.[0].databaseId') --exit-status`
Expected: the run completes successfully (exit status 0) across all four Python versions. If it fails, read the logs (`gh run view --log-failed`), fix, and re-push.

---

## Task 7: Capture a dependency lockfile

**Files:**
- Create: `requirements-dev.lock`

- [ ] **Step 1: Freeze the verified environment (excluding the editable package)**

Run: `.venv/Scripts/python.exe -m pip freeze --exclude-editable > requirements-dev.lock`
Expected: creates `requirements-dev.lock` listing pinned versions (fastmcp, httpx, pytest, ruff, and transitive deps). The editable `connectwise-mcp` itself is excluded so the file is machine-independent.

- [ ] **Step 2: Sanity-check the contents**

Run: `.venv/Scripts/python.exe -c "t=open('requirements-dev.lock').read(); assert 'fastmcp==' in t and 'httpx==' in t; print('lock ok')"`
Expected: prints `lock ok`.

- [ ] **Step 3: Commit**

```bash
git add requirements-dev.lock
git commit -m "build: capture requirements-dev.lock snapshot for reproducible installs"
```

---

## Task 8: Add live smoke script and connection docs (user-run validation)

**Files:**
- Create: `scripts/smoke_live.py`
- Create: `docs/connecting.md`

- [ ] **Step 1: Create the live smoke script**

Create `scripts/smoke_live.py`:

```python
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
        os.environ.setdefault(key.strip(), value.strip())


async def main() -> int:
    configure_logging()
    _load_dotenv()

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
```

- [ ] **Step 2: Verify the script imports and fails cleanly without creds**

Run (no `.env`, no `CW_*` set — should report missing creds and exit 1, proving the wiring works without needing real keys):
`.venv/Scripts/python.exe scripts/smoke_live.py`
Expected: prints the catalog line, then `ERROR: Missing ConnectWise credentials: ...`, exit code 1.

- [ ] **Step 3: Lint the script**

Run: `.venv/Scripts/python.exe -m ruff check scripts/smoke_live.py && .venv/Scripts/python.exe -m ruff format --check scripts/smoke_live.py`
Expected: `All checks passed!`

- [ ] **Step 4: Write the connection guide**

Create `docs/connecting.md`:

````markdown
# Connecting the ConnectWise PSA MCP server (local stdio)

This guide wires the **read-only** server into an MCP client over stdio, using
your ConnectWise credentials as `CW_*` environment variables. Nothing is stored
server-side — the process reads the env vars per request.

## 1. Install

```bash
python -m venv .venv
# Windows:  .venv\Scripts\activate
# macOS/Linux:  source .venv/bin/activate
pip install -e ".[dev]"
```

## 2. Get your ConnectWise API keys

In ConnectWise Manage: **System → Members → API Members** (create a dedicated
API member), then **API Keys** to generate a public/private key pair. You also
need your **company id**, your **clientId** GUID (registered in the ConnectWise
Developer Network), and your **region** (`na`, `eu`, `au`, `aus`, `za`) or a
self-hosted host.

## 3. Validate the connection (smoke test)

Copy `.env.example` to `.env`, fill in the five `CW_*` values, then run:

```bash
python scripts/smoke_live.py
```

Expected output ends with `OK: /system/members returned 1 record(s)`. If you see
`authentication failed`, re-check the keys, company id, clientId, and region.

## 4. Connect Claude Desktop

Edit `claude_desktop_config.json` (Settings → Developer → Edit Config) and add an
entry. Use the **absolute path** to the Python interpreter in your `.venv`:

```json
{
  "mcpServers": {
    "connectwise-psa": {
      "command": "C:\\Users\\wdyou\\connectwisemcp\\connectwise-mcp\\.venv\\Scripts\\python.exe",
      "args": ["-m", "connectwise_mcp"],
      "env": {
        "CW_MCP_TRANSPORT": "stdio",
        "CW_COMPANY_ID": "your_company_id",
        "CW_PUBLIC_KEY": "your_public_key",
        "CW_PRIVATE_KEY": "your_private_key",
        "CW_CLIENT_ID": "your_client_id_guid",
        "CW_REGION": "na"
      }
    }
  }
}
```

Restart Claude Desktop. The `connectwise-psa` tools (`list_modules`,
`search_endpoints`, `describe_endpoint`, `cw_get`) should appear. Ask it to
"list the ConnectWise modules" to confirm.

## 5. Connect Claude Code

From the project directory:

```bash
claude mcp add connectwise-psa \
  --env CW_MCP_TRANSPORT=stdio \
  --env CW_COMPANY_ID=your_company_id \
  --env CW_PUBLIC_KEY=your_public_key \
  --env CW_PRIVATE_KEY=your_private_key \
  --env CW_CLIENT_ID=your_client_id_guid \
  --env CW_REGION=na \
  -- C:\\Users\\wdyou\\connectwisemcp\\connectwise-mcp\\.venv\\Scripts\\python.exe -m connectwise_mcp
```

Then run `claude mcp list` to confirm it's registered.

## Manual verification checklist

- [ ] `python scripts/smoke_live.py` prints `OK: /system/members returned ...`
- [ ] Client lists the four `connectwise-psa` tools
- [ ] Asking the client to read open service tickets returns real data
- [ ] No credentials appear in the server's log output
````

- [ ] **Step 5: Commit**

```bash
git add scripts/smoke_live.py docs/connecting.md
git commit -m "docs: add live smoke script and stdio connection guide"
```

- [ ] **Step 6: Push everything**

```bash
git push origin main
```

---

## Final verification (after all tasks)

- [ ] `.venv/Scripts/python.exe -m pytest -q` → `17 passed`
- [ ] `.venv/Scripts/python.exe -m ruff check . && .venv/Scripts/python.exe -m ruff format --check .` → clean
- [ ] CI is green on `main` across Python 3.10–3.13 (badge shows passing)
- [ ] **(User step)** Fill `.env` with real keys, run `python scripts/smoke_live.py`, confirm a live read, and connect one MCP client per `docs/connecting.md`

---

## Notes for the implementer

- All `python` invocations assume the project venv at `.venv/Scripts/python.exe` (Windows). On macOS/Linux use `.venv/bin/python`.
- The Bash tool's working directory may not persist between calls in this environment; prefix commands with `cd /c/Users/wdyou/connectwisemcp/connectwise-mcp &&` if a command reports a missing path.
- `requirements-dev.lock` is a reference snapshot for exact reproduction; CI installs from `pyproject.toml` pins (intentional — avoids editable-install lock churn).
- This milestone changes **no tool behavior** and adds **no new capabilities** — it is purely hardening + validation. Write tools (M3) and hosting (M2) are separate specs.
