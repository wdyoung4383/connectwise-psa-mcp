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
