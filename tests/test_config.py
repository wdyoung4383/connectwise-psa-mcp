"""Tests for environment-driven config resolution."""

import pytest

from connectwise_mcp import config
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


def test_writes_enabled_defaults_on(monkeypatch):
    monkeypatch.delenv("CW_MCP_ALLOW_WRITES", raising=False)
    assert config.writes_enabled() is True


@pytest.mark.parametrize("value", ["false", "0", "no", "off", " False "])
def test_writes_disabled_by_env(monkeypatch, value):
    monkeypatch.setenv("CW_MCP_ALLOW_WRITES", value)
    assert config.writes_enabled() is False
