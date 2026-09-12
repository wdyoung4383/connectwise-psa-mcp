"""The catalog builder must drop DELETE, honor scope, and prune the spec."""

import importlib.util
import json
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "build_catalog.py"
_spec = importlib.util.spec_from_file_location("build_catalog", _SCRIPT)
build_catalog = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(build_catalog)

CLIENT_ID = {"name": "clientId", "in": "header", "required": True}


def _op(opid, tag, *, body=None, resp="Thing"):
    op = {
        "tags": [tag],
        "operationId": opid,
        "parameters": [CLIENT_ID, {"name": "id", "in": "path"}],
        "responses": {
            "200": {
                "content": {
                    "application/json": {
                        "schema": {"$ref": f"#/components/schemas/{resp}"}
                    }
                }
            },
            "400": {"description": "bad"},
        },
    }
    if body:
        op["requestBody"] = {
            "content": {
                "application/json": {"schema": {"$ref": f"#/components/schemas/{body}"}}
            }
        }
    return op


FULL = {
    "openapi": "3.0.1",
    "info": {"title": "T", "version": "9.9"},
    "paths": {
        "/a/things/{id}": {
            "get": _op("getThing", "Things"),
            "put": _op("putThing", "Things", body="Thing"),
            "patch": _op("patchThing", "Things", body="PatchOps"),
            "delete": _op("deleteThing", "Things"),
        },
        "/a/things": {"post": _op("postThing", "Things", body="Thing")},
        "/b/other": {
            "get": _op("getOther", "Other", resp="Other"),
            "delete": _op("deleteOther", "Other"),
        },
        "/c/only-delete": {"delete": _op("deleteOnly", "Only")},
    },
    "components": {
        "schemas": {
            "Thing": {"properties": {"ref": {"$ref": "#/components/schemas/Ref"}}},
            "Ref": {"type": "object"},
            "PatchOps": {"type": "array"},
            "Other": {"type": "object"},
            "Unused": {"type": "object"},
        }
    },
}


def test_build_drops_delete_and_prunes():
    out = build_catalog.build(FULL)
    assert set(out["paths"]) == {"/a/things/{id}", "/a/things", "/b/other"}
    assert set(out["paths"]["/a/things/{id}"]) == {"get", "put", "patch"}
    assert set(out["paths"]["/b/other"]) == {"get"}
    for item in out["paths"].values():
        assert "delete" not in item
    # Referenced schemas kept transitively, unused dropped.
    assert set(out["components"]["schemas"]) == {"Thing", "Ref", "PatchOps", "Other"}
    # clientId header stripped, path param kept, non-2xx responses dropped.
    op = out["paths"]["/a/things/{id}"]["get"]
    assert [p["name"] for p in op["parameters"]] == ["id"]
    assert set(op["responses"]) == {"200"}
    assert out["info"]["x-allowed-methods"] == ["GET", "PATCH", "POST", "PUT"]
    assert out["info"]["x-selected-categories"] is None


def test_build_honors_selected_categories(monkeypatch):
    monkeypatch.setattr(build_catalog, "SELECTED_CATEGORIES", frozenset({"Other"}))
    out = build_catalog.build(FULL)
    assert set(out["paths"]) == {"/b/other"}
    assert set(out["components"]["schemas"]) == {"Other"}
    assert out["info"]["x-selected-categories"] == ["Other"]


def test_main_writes_file(tmp_path):
    src = tmp_path / "full.json"
    src.write_text(json.dumps(FULL))
    dst = tmp_path / "out" / "catalog.json"
    assert build_catalog.main([str(src), "-o", str(dst)]) == 0
    written = json.loads(dst.read_text())
    assert "/c/only-delete" not in written["paths"]


def test_shipped_catalog_matches_scope_rules():
    from connectwise_mcp.catalog import load_catalog
    from connectwise_mcp.scope import ALLOWED_METHODS

    cat = load_catalog()
    assert {ep.method for ep in cat.endpoints.values()} <= ALLOWED_METHODS
    assert cat._spec["info"]["x-allowed-methods"] == sorted(ALLOWED_METHODS)


@pytest.mark.parametrize("method", ["delete", "head", "options"])
def test_never_kept(method):
    assert not build_catalog._keep_operation(method, {"tags": ["Things"]})
