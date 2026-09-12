"""Runtime catalog over the filtered ConnectWise OpenAPI spec.

The spec is data, not generated tools: the gateway tools search this catalog to
*find* an operation, describe its contract, then execute it. This keeps the
whole API surface (every module, every non-DELETE method) reachable behind a
handful of tools.

Operations are keyed by ``operationId`` (unique across the spec) and by
``(METHOD, path)``. DELETE never appears here: ``scripts/build_catalog.py``
drops it at build time, so there is no delete code path at all.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from functools import lru_cache
from importlib import resources
from typing import Any

_SPEC_RESOURCE = "openapi_catalog.json"

# Order used for display and for tie-breaking search results.
METHOD_ORDER = ("GET", "POST", "PUT", "PATCH")


@dataclass
class Endpoint:
    operation_id: str
    method: str
    path: str
    module: str
    tags: list[str]
    summary: str
    parameters: list[dict[str, Any]] = field(default_factory=list)
    request_body: dict[str, Any] | None = None

    @property
    def path_params(self) -> list[str]:
        return [p["name"] for p in self.parameters if p.get("in") == "path"]

    @property
    def query_params(self) -> list[str]:
        return [p["name"] for p in self.parameters if p.get("in") == "query"]

    @property
    def has_body(self) -> bool:
        return self.request_body is not None

    @property
    def body_media_type(self) -> str | None:
        if not self.request_body:
            return None
        content = self.request_body.get("content") or {}
        for media in content:
            if "json" in media:
                return media
        return next(iter(content), None)


class Catalog:
    def __init__(self, spec: dict[str, Any]):
        self._spec = spec
        self._schemas = spec.get("components", {}).get("schemas", {})
        self.endpoints: dict[str, Endpoint] = {}
        self._by_method_path: dict[tuple[str, str], Endpoint] = {}
        for path, item in spec.get("paths", {}).items():
            for method, op in item.items():
                if not isinstance(op, dict):
                    continue
                m = method.upper()
                opid = op.get("operationId") or f"{method} {path}"
                ep = Endpoint(
                    operation_id=opid,
                    method=m,
                    path=path,
                    module=path.strip("/").split("/")[0],
                    tags=op.get("tags", []),
                    summary=op.get("summary", "") or "",
                    parameters=op.get("parameters", []),
                    request_body=op.get("requestBody"),
                )
                self.endpoints[opid] = ep
                self._by_method_path[(m, path)] = ep

    # ------- lookups -------
    @property
    def methods(self) -> list[str]:
        present = {ep.method for ep in self.endpoints.values()}
        return [m for m in METHOD_ORDER if m in present] + sorted(
            present - set(METHOD_ORDER)
        )

    def modules(self) -> dict[str, dict[str, int]]:
        """Per module: operation counts by method plus a total."""
        out: dict[str, dict[str, int]] = {}
        for ep in self.endpoints.values():
            row = out.setdefault(ep.module, {})
            row[ep.method] = row.get(ep.method, 0) + 1
        result: dict[str, dict[str, int]] = {}
        for module in sorted(out):
            counts = out[module]
            ordered = {m: counts[m] for m in self.methods if m in counts}
            ordered["total"] = sum(counts.values())
            result[module] = ordered
        return result

    def get(self, operation_id: str) -> Endpoint | None:
        return self.endpoints.get(operation_id)

    def by_path(self, path: str, method: str = "GET") -> Endpoint | None:
        return self._by_method_path.get((method.upper(), path))

    def methods_for_path(self, path: str) -> list[str]:
        return [m for (m, p) in self._by_method_path if p == path]

    def search(
        self,
        query: str,
        module: str | None = None,
        method: str | None = None,
        limit: int = 20,
    ) -> list[Endpoint]:
        terms = [t for t in query.lower().split() if t]
        wanted_method = method.upper() if method else None
        scored: list[tuple[int, int, Endpoint]] = []
        for ep in self.endpoints.values():
            if module and ep.module != module:
                continue
            if wanted_method and ep.method != wanted_method:
                continue
            haystack = " ".join(
                [ep.operation_id, ep.method, ep.path, ep.summary, " ".join(ep.tags)]
            ).lower()
            if not terms:
                score = 1
            else:
                score = 0
                for t in terms:
                    if t in haystack:
                        score += 2
                        # boost exact-ish matches in path/tag
                        if t in ep.path.lower() or t in " ".join(ep.tags).lower():
                            score += 1
                if score == 0:
                    continue
            rank = (
                METHOD_ORDER.index(ep.method)
                if ep.method in METHOD_ORDER
                else len(METHOD_ORDER)
            )
            scored.append((score, rank, ep))
        scored.sort(key=lambda s: (-s[0], s[2].path, s[1]))
        return [ep for _, _, ep in scored[:limit]]

    # ------- schema resolution -------
    def resolve_schema(self, ref_or_schema: Any, _depth: int = 0, _seen=None) -> Any:
        """Resolve $refs into a compact, model-friendly schema summary."""
        if _seen is None:
            _seen = set()
        if _depth > 6 or ref_or_schema is None:
            return {"note": "...truncated..."}
        node = ref_or_schema
        if isinstance(node, dict) and "$ref" in node:
            name = node["$ref"].split("/")[-1]
            if name in _seen:
                return {"$ref": name, "note": "recursive"}
            _seen = _seen | {name}
            node = self._schemas.get(name, {})
        if not isinstance(node, dict):
            return node

        t = node.get("type")
        if t == "array" or "items" in node:
            return {
                "type": "array",
                "items": self.resolve_schema(node.get("items"), _depth + 1, _seen),
            }
        if "properties" in node or t == "object":
            props = {}
            for pname, pschema in (node.get("properties") or {}).items():
                ps = self.resolve_schema(pschema, _depth + 1, _seen)
                props[pname] = ps if isinstance(ps, (dict, str)) else str(ps)
            out: dict[str, Any] = {"type": "object", "properties": props}
            if node.get("required"):
                out["required"] = node["required"]
            return out
        # primitive
        prim = {"type": t or "any"}
        if "format" in node:
            prim["format"] = node["format"]
        if "enum" in node:
            prim["enum"] = node["enum"]
        if node.get("readOnly"):
            prim["readOnly"] = True
        return prim

    @staticmethod
    def _first_schema(content: dict[str, Any]) -> Any:
        # ConnectWise uses a vendor media type (application/vnd.connectwise.com+json),
        # so take whichever content entry is present rather than assuming json.
        for media in content.values():
            if isinstance(media, dict) and media.get("schema"):
                return media["schema"]
        return None

    def describe(self, operation_id: str) -> dict[str, Any] | None:
        ep = self.endpoints.get(operation_id)
        if not ep:
            return None
        params = []
        for p in ep.parameters:
            params.append(
                {
                    "name": p["name"],
                    "in": p.get("in"),
                    "required": p.get("required", p.get("in") == "path"),
                    "type": (p.get("schema") or {}).get("type", "string"),
                    "description": p.get("description", ""),
                }
            )
        op = self._spec["paths"][ep.path][ep.method.lower()]

        # Surface the first 2xx body schema so callers know the returned shape.
        resp = None
        for code in ("200", "201"):
            content = op.get("responses", {}).get(code, {}).get("content", {})
            resp = self._first_schema(content)
            if resp is not None:
                break

        body_schema = None
        if ep.request_body:
            body_schema = self._first_schema(ep.request_body.get("content") or {})

        out: dict[str, Any] = {
            "operationId": ep.operation_id,
            "method": ep.method,
            "path": ep.path,
            "module": ep.module,
            "tags": ep.tags,
            "summary": ep.summary,
            "path_params": ep.path_params,
            "query_params": ep.query_params,
            "parameters": params,
            "response_schema": self.resolve_schema(resp) if resp else None,
        }
        if ep.request_body:
            out["request_body"] = {
                "required": bool(ep.request_body.get("required")),
                "media_type": ep.body_media_type,
                "description": ep.request_body.get("description", ""),
                "schema": self.resolve_schema(body_schema) if body_schema else None,
            }
            if ep.method == "PATCH":
                out["request_body"]["note"] = (
                    "ConnectWise PATCH bodies are JSON Patch operation lists, e.g. "
                    '[{"op": "replace", "path": "/summary", "value": "New text"}]. '
                    "Supported ops: add, replace, remove."
                )
        out["other_methods_on_path"] = sorted(
            m for m in self.methods_for_path(ep.path) if m != ep.method
        )
        return out


@lru_cache(maxsize=1)
def load_catalog() -> Catalog:
    with (
        resources.files("connectwise_mcp.data")
        .joinpath(_SPEC_RESOURCE)
        .open("r", encoding="utf-8") as f
    ):
        spec = json.load(f)
    return Catalog(spec)
