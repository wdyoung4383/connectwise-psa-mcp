"""Smoke tests for the catalog and executor (no network)."""

import pytest

from connectwise_mcp.catalog import load_catalog
from connectwise_mcp.executor import ExecutionError, _fill_path


def test_catalog_loads_with_all_non_delete_methods():
    cat = load_catalog()
    assert len(cat.endpoints) > 1000
    methods = {ep.method for ep in cat.endpoints.values()}
    assert methods == {"GET", "POST", "PUT", "PATCH"}
    assert "DELETE" not in methods


def test_catalog_has_no_delete_operations_in_spec():
    cat = load_catalog()
    for item in cat._spec["paths"].values():
        assert "delete" not in item


def test_by_path_is_method_aware():
    cat = load_catalog()
    assert cat.by_path("/service/tickets", "GET").method == "GET"
    assert cat.by_path("/service/tickets", "POST").method == "POST"
    assert cat.by_path("/service/tickets", "DELETE") is None
    assert cat.by_path("/service/tickets/{id}", "PATCH").operation_id == (
        "patchServiceTicketsById"
    )
    assert set(cat.methods_for_path("/service/tickets/{id}")) == {
        "GET",
        "PUT",
        "PATCH",
    }


def test_search_filters_by_method():
    cat = load_catalog()
    hits = cat.search("tickets", module="service", method="POST")
    assert hits and all(h.method == "POST" for h in hits)
    assert any(h.path == "/service/tickets" for h in hits)


def test_describe_write_includes_request_body():
    cat = load_catalog()
    d = cat.describe("postServiceTickets")
    assert d["method"] == "POST"
    assert d["request_body"]["required"] is True
    assert d["request_body"]["media_type"] == "application/json"
    assert "summary" in d["request_body"]["schema"]["properties"]
    assert "GET" in d["other_methods_on_path"]

    p = cat.describe("patchServiceTicketsById")
    assert p["request_body"]["schema"]["type"] == "array"
    assert "JSON Patch" in p["request_body"]["note"]


def test_describe_get_has_no_request_body():
    cat = load_catalog()
    d = cat.describe("getServiceTickets")
    assert d["method"] == "GET"
    assert "request_body" not in d
    assert not any(p["name"] == "clientId" for p in d["parameters"])


def test_modules_report_per_method_counts():
    mods = load_catalog().modules()
    svc = mods["service"]
    assert svc["total"] == sum(v for k, v in svc.items() if k != "total")
    assert svc["GET"] > svc["POST"] > 0


def test_modules_present():
    mods = load_catalog().modules()
    for m in ("service", "company", "finance", "time", "system", "procurement"):
        assert m in mods


def test_search_finds_tickets():
    cat = load_catalog()
    hits = cat.search("tickets", module="service")
    assert any(h.path == "/service/tickets" for h in hits)


def test_describe_returns_params():
    cat = load_catalog()
    hits = cat.search("tickets", module="service")
    d = cat.describe(hits[0].operation_id)
    assert d is not None
    assert "parameters" in d and isinstance(d["parameters"], list)


def test_fill_path_ok_and_missing():
    assert _fill_path("/service/tickets/{id}", {"id": 5}) == "/service/tickets/5"
    with pytest.raises(ExecutionError):
        _fill_path("/service/tickets/{id}", {})
