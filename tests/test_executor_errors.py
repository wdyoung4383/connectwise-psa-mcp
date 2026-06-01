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
    token = "QUJDREVGR0hJSktMTU5PUFFSU1RVVldYWVo="
    client = FakeClient(response=_resp(400, text=f"bad value Basic {token}"))
    with pytest.raises(ExecutionError) as ei:
        await cw_get(client, CATALOG, "/service/boards")
    msg = str(ei.value)
    assert "400" in msg
    assert "QUJDREVGR0hJSktMTU5PUFFSU1RVVldYWVo=" not in msg  # Basic token redacted


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
