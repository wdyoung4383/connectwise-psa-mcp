# M1 — Trustworthy read-only core, validated on live data

**Date:** 2026-06-01
**Status:** Approved
**Project:** connectwise-psa-mcp (read-only MCP gateway for ConnectWise Manage / PSA)

## Context

The project is a working FastMCP server that exposes ConnectWise Manage (PSA) as
a read-only gateway. Four gateway tools (`list_modules`, `search_endpoints`,
`describe_endpoint`, `cw_get`) sit over a runtime catalog of 324 in-scope GET
endpoints loaded from an OpenAPI spec. Credentials are supplied per request
(`X-CW-*` headers over HTTP, `CW_*` env vars over stdio) and never stored in the
process — a deliberately multi-tenant design.

The code installs cleanly, all 5 offline tests pass, the catalog loads (324
endpoints / 9 modules), and all four tools register. However, it has never been
run against a live ConnectWise instance and its dependencies are unpinned
(declared `fastmcp>=2.3.0` but resolves to FastMCP 3.3.1, across a breaking 2→3
API change).

## Roadmap (this spec covers M1 only)

- **M1 — Trustworthy read-only core, validated on live data.** Reproducible
  deps, CI, consistent style, safe logging/errors, and a verified live stdio
  connection. *(This document.)*
- **M2 — Hosted multi-tenant service.** Docker, HTTP deployment, gateway auth,
  secure per-client credential handling, security hardening. The ultimate
  business goal: clients connect from their own MCP-capable tools. *(Future
  spec.)*
- **M3 — Write/action tools.** Create/update operations with safety design
  (guardrails, confirmation, dry-run, audit). *(Future spec.)*

Sequence: validate locally → host → add writes. Each milestone gets its own
spec → plan → build cycle.

## Goal

Take the working-but-unproven server to a state worth trusting: reproducible
dependencies, automated tests in CI, consistent code style, safe logging and
error surfaces, and a verified connection to a real ConnectWise instance via
local stdio.

## Scope

### 1. Dependency pinning

- `pyproject.toml`: change `fastmcp>=2.3.0` → `fastmcp>=3.3,<4` and
  `httpx>=0.27` → `httpx>=0.27,<1`. Verified working on fastmcp 3.3.1 /
  httpx 0.28.1.
- Add a `requirements-dev.lock` (generated via `pip freeze` from the verified
  venv) so CI and local installs resolve identical versions. Prevents the
  2→3-style surprise from recurring.

### 2. GitHub Actions CI

- `.github/workflows/ci.yml`, triggered on push and pull_request to `main`.
- Python version matrix: 3.10, 3.11, 3.12, 3.13 (matches
  `requires-python >= 3.10`).
- Steps per matrix entry: checkout → set up Python → `pip install -e ".[dev]"`
  → `ruff check .` → `ruff format --check .` → `pytest`.
- Add a CI status badge to `README.md`.

### 3. Ruff lint + format

- Add `ruff` to the `dev` optional-dependencies group.
- Configure ruff in `pyproject.toml`: `line-length = 88`,
  `target-version = "py310"`, rule set `["E", "F", "I", "UP", "B"]`.
- Run a one-time `ruff format` pass over `src/` and `tests/` in its own isolated
  commit, so formatting churn does not mix with logic changes.

### 4. Logging + error hardening

- A small logging setup: module-level loggers, level controlled by a
  `CW_LOG_LEVEL` env var (default `INFO`).
- Log each `cw_get` at INFO with method, path, HTTP status, and duration.
  **Never** log headers, credentials, or query/condition values that could carry
  PII.
- A dedicated credential-redaction helper that scrubs `X-CW-*` / `CW_*` /
  Basic-auth values from any structure before it is logged. Backed by a unit
  test asserting credential keys/values never appear in emitted log output.
- Tighten error surfaces in `executor.py` / `server.py`: map auth failures
  (401/403), not-found (404), ConnectWise validation errors, and
  transport/timeout errors into clear, distinct `{"error": ...}` messages an
  agent can act on — without echoing raw credentials.

### 5. Live validation (user-executed)

This step requires real ConnectWise credentials, which only the user has; the
deliverables make it a one-command, well-documented step.

- `scripts/smoke_live.py`: loads `CW_*` from `.env`, calls `list_modules`, then
  performs one real `cw_get` against a low-risk endpoint (e.g. `/system/info`
  or `/service/boards`), and prints the results.
- `docs/connecting.md`: step-by-step instructions to wire the stdio server into
  **Claude Desktop** and **Claude Code** (config snippets, required env vars),
  plus a short manual verification checklist.

## Testing

- Keep the existing 5 offline tests passing.
- Add a redaction-helper test (asserts credentials never appear in log output).
- Add an error-mapping test (mock httpx responses → assert clean, credential-free
  error dicts for 401/403/404/validation/timeout).
- CI runs the full suite across the Python matrix.

## Acceptance criteria

- `pyproject.toml` pins are in place and `pip install -e ".[dev]"` resolves the
  verified versions; lockfile committed.
- CI workflow is green on `main` across Python 3.10–3.13, badge visible in README.
- `ruff check .` and `ruff format --check .` pass with zero findings.
- Logging emits structured `cw_get` lines; redaction test proves no credentials
  leak.
- Error-mapping test passes for the enumerated failure classes.
- User runs `scripts/smoke_live.py` against their instance and sees real data,
  and connects one MCP client (per `docs/connecting.md`) that successfully
  reads from ConnectWise.

## Out of scope (deferred to M2/M3)

HTTP/hosted deployment, Dockerfile, gateway authentication, multi-tenant
credential management, write/action tools, broader endpoint coverage. M1 changes
no tool behavior and adds no new capabilities — it hardens what exists and proves
it works live.

## Deliverables

- Pinned `pyproject.toml` + `requirements-dev.lock`
- `.github/workflows/ci.yml` + README badge
- Ruff config + formatted tree
- Logging module + credential-redaction guard
- Hardened error handling in `executor.py` / `server.py`
- `scripts/smoke_live.py`
- `docs/connecting.md`
- New tests (redaction, error mapping)
