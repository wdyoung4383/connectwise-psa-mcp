"""Tests for gateway token loading and the gateway-auth ASGI middleware."""

import hashlib

import pytest
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.responses import PlainTextResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from connectwise_mcp.gateway_auth import GatewayAuthMiddleware, load_gateway_tokens

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
