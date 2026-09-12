"""Error-mapping and logging tests for the executor (no real network)."""

import logging

import httpx
import pytest

from connectwise_mcp.catalog import load_catalog
from connectwise_mcp.executor import ExecutionError, cw_get, cw_write

CATALOG = load_catalog()


class FakeClient:
    """Minimal stand-in for httpx.AsyncClient.request used by the executor."""

    def __init__(self, *, response=None, raise_exc=None):
        self._response = response
        self._raise = raise_exc
        self.last_method = None
        self.last_url = None
        self.last_params = None
        self.last_json = None

    async def request(self, method, url, params=None, json=None):
        self.last_method = method
        self.last_url = url
        self.last_params = params
        self.last_json = json
        if self._raise is not None:
            raise self._raise
        return self._response


def _resp(status, *, text="", json_body=None, method="GET"):
    request = httpx.Request(method, "https://example/api")
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


async def test_get_rejects_path_outside_scope():
    client = FakeClient(response=_resp(200, json_body=[]))
    with pytest.raises(ExecutionError) as ei:
        await cw_get(client, CATALOG, "/service/not-a-real-path")
    assert "not in this server's scope" in str(ei.value)
    assert client.last_method is None  # refused before any network call


# ---------------- writes ----------------


async def test_post_sends_json_body_and_returns_created():
    created = {"id": 99, "summary": "New ticket"}
    client = FakeClient(response=_resp(201, json_body=created, method="POST"))
    body = {"summary": "New ticket", "board": {"id": 1}, "company": {"id": 2}}
    out = await cw_write(client, CATALOG, "POST", "/service/tickets", body=body)
    assert out == created
    assert client.last_method == "POST"
    assert client.last_url == "/service/tickets"
    assert client.last_json == body
    assert client.last_params is None


async def test_patch_sends_operation_list():
    client = FakeClient(response=_resp(200, json_body={"id": 5}, method="PATCH"))
    ops = [{"op": "replace", "path": "/summary", "value": "x"}]
    out = await cw_write(
        client,
        CATALOG,
        "patch",
        "/service/tickets/{id}",
        path_params={"id": 5},
        body=ops,
    )
    assert out == {"id": 5}
    assert client.last_method == "PATCH"
    assert client.last_url == "/service/tickets/5"
    assert client.last_json == ops


async def test_patch_rejects_non_list_body():
    client = FakeClient(response=_resp(200, json_body={}))
    with pytest.raises(ExecutionError) as ei:
        await cw_write(
            client,
            CATALOG,
            "PATCH",
            "/service/tickets/{id}",
            path_params={"id": 5},
            body={"summary": "x"},
        )
    assert "JSON Patch" in str(ei.value)
    assert client.last_method is None


async def test_put_passes_query_params():
    client = FakeClient(response=_resp(200, json_body={"id": 5}, method="PUT"))
    await cw_write(
        client,
        CATALOG,
        "PUT",
        "/service/tickets/{id}",
        path_params={"id": 5},
        body={"summary": "x"},
        query={"fields": "id,summary"},
    )
    assert client.last_method == "PUT"
    assert client.last_params == {"fields": "id,summary"}


async def test_write_refuses_delete_even_if_asked():
    client = FakeClient(response=_resp(204))
    with pytest.raises(ExecutionError) as ei:
        await cw_write(
            client, CATALOG, "DELETE", "/service/tickets/{id}", path_params={"id": 1}
        )
    assert "not a supported write method" in str(ei.value)
    assert client.last_method is None


async def test_write_refuses_method_not_in_catalog_for_path():
    # /service/tickets/{id} has GET/PUT/PATCH but no POST.
    client = FakeClient(response=_resp(201, json_body={}))
    with pytest.raises(ExecutionError) as ei:
        await cw_write(
            client, CATALOG, "POST", "/service/tickets/{id}", path_params={"id": 1}
        )
    msg = str(ei.value)
    assert "POST is not available" in msg
    assert "PATCH" in msg
    assert client.last_method is None


async def test_write_requires_body_when_spec_requires_it():
    client = FakeClient(response=_resp(201, json_body={}))
    with pytest.raises(ExecutionError) as ei:
        await cw_write(client, CATALOG, "POST", "/service/tickets")
    assert "requires a JSON body" in str(ei.value)
    assert "postServiceTickets" in str(ei.value)


async def test_write_rejects_non_json_body_endpoints():
    # /system/documents is the one multipart/form-data upload in the spec.
    client = FakeClient(response=_resp(201, json_body={}))
    with pytest.raises(ExecutionError) as ei:
        await cw_write(client, CATALOG, "POST", "/system/documents", body={"a": 1})
    assert "multipart/form-data" in str(ei.value)


async def test_write_204_returns_ok_marker():
    client = FakeClient(response=_resp(204, method="POST"))
    out = await cw_write(
        client,
        CATALOG,
        "POST",
        "/service/tickets",
        body={"summary": "x"},
    )
    assert out == {"status": 204, "ok": True}


async def test_write_error_detail_is_redacted_and_body_not_logged(caplog):
    token = "QUJDREVGR0hJSktMTU5PUFFSU1RVVldYWVo="
    client = FakeClient(response=_resp(400, text=f"bad Basic {token}", method="POST"))
    with caplog.at_level(logging.INFO):
        with pytest.raises(ExecutionError) as ei:
            await cw_write(
                client,
                CATALOG,
                "POST",
                "/service/tickets",
                body={"summary": "SECRET-SUMMARY-TEXT"},
            )
    assert token not in str(ei.value)
    assert "SECRET-SUMMARY-TEXT" not in caplog.text
    assert "POST /service/tickets" in caplog.text
    assert "400" in caplog.text
