"""Build the runtime catalog from a full ConnectWise Manage OpenAPI spec.

Usage:

    python scripts/build_catalog.py /path/to/full-connectwise-openapi.json

Reads the full spec (download it from developer.connectwise.com, "ConnectWise
Manage Public Endpoints"), applies the rules in ``connectwise_mcp.scope``
(allowed HTTP methods, optional category filter), prunes everything the kept
operations do not reference, and writes the runtime catalog to
``src/connectwise_mcp/data/openapi_catalog.json``.

The pruning keeps the file small enough to ship in the wheel and load at
startup: unreferenced component schemas are dropped, the per-request
``clientId`` header parameter is removed (the HTTP client adds it), and only
2xx responses are kept.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from connectwise_mcp.scope import ALLOWED_METHODS, SELECTED_CATEGORIES  # noqa: E402

DEFAULT_OUTPUT = REPO_ROOT / "src" / "connectwise_mcp" / "data" / "openapi_catalog.json"
_HTTP_METHODS = ("get", "post", "put", "patch", "delete", "head", "options")


def _keep_operation(method: str, op: dict[str, Any]) -> bool:
    if method.upper() not in ALLOWED_METHODS:
        return False
    if SELECTED_CATEGORIES is None:
        return True
    return any(tag in SELECTED_CATEGORIES for tag in op.get("tags", []))


def _strip_operation(op: dict[str, Any]) -> dict[str, Any]:
    out = dict(op)
    out["parameters"] = [
        p
        for p in op.get("parameters", [])
        if not (p.get("in") == "header" and p.get("name") == "clientId")
    ]
    out["responses"] = {
        code: body
        for code, body in op.get("responses", {}).items()
        if str(code).startswith("2")
    }
    return out


def _collect_refs(node: Any, found: set[str]) -> None:
    if isinstance(node, dict):
        ref = node.get("$ref")
        if isinstance(ref, str) and ref.startswith("#/components/schemas/"):
            found.add(ref.rsplit("/", 1)[-1])
        for v in node.values():
            _collect_refs(v, found)
    elif isinstance(node, list):
        for v in node:
            _collect_refs(v, found)


def _referenced_schemas(
    paths: dict[str, Any], schemas: dict[str, Any]
) -> dict[str, Any]:
    wanted: set[str] = set()
    _collect_refs(paths, wanted)
    # Transitive closure over schema-to-schema references.
    todo = list(wanted)
    while todo:
        name = todo.pop()
        inner: set[str] = set()
        _collect_refs(schemas.get(name), inner)
        for n in inner - wanted:
            wanted.add(n)
            todo.append(n)
    return {name: schemas[name] for name in sorted(wanted) if name in schemas}


def build(full_spec: dict[str, Any]) -> dict[str, Any]:
    paths: dict[str, Any] = {}
    for path, item in full_spec.get("paths", {}).items():
        kept: dict[str, Any] = {}
        for method, op in item.items():
            if method not in _HTTP_METHODS or not isinstance(op, dict):
                continue
            if _keep_operation(method, op):
                kept[method] = _strip_operation(op)
        if kept:
            paths[path] = kept

    schemas = full_spec.get("components", {}).get("schemas", {})
    info = dict(full_spec.get("info", {}))
    info["title"] = f"{info.get('title', 'ConnectWise Manage')} (MCP catalog)"
    info["x-allowed-methods"] = sorted(ALLOWED_METHODS)
    info["x-selected-categories"] = (
        None if SELECTED_CATEGORIES is None else sorted(SELECTED_CATEGORIES)
    )
    return {
        "openapi": full_spec.get("openapi", "3.0.1"),
        "info": info,
        "servers": full_spec.get("servers", []),
        "paths": paths,
        "components": {"schemas": _referenced_schemas(paths, schemas)},
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("full_spec", type=Path, help="Path to the full OpenAPI JSON")
    ap.add_argument("-o", "--output", type=Path, default=DEFAULT_OUTPUT)
    args = ap.parse_args(argv)

    full = json.loads(args.full_spec.read_text(encoding="utf-8"))
    catalog = build(full)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as f:
        json.dump(catalog, f, separators=(",", ":"), sort_keys=True)
        f.write("\n")

    counts: dict[str, int] = {}
    for item in catalog["paths"].values():
        for method in item:
            counts[method.upper()] = counts.get(method.upper(), 0) + 1
    print(
        f"wrote {args.output} ({args.output.stat().st_size // 1024} KiB): "
        f"{len(catalog['paths'])} paths, {sum(counts.values())} operations "
        f"{dict(sorted(counts.items()))}, "
        f"{len(catalog['components']['schemas'])} schemas, "
        f"spec version {catalog['info'].get('version')}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
