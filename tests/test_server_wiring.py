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
