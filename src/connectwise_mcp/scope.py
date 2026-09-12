"""What part of the ConnectWise API this server exposes.

Scope is decided at build time: ``scripts/build_catalog.py`` filters the full
ConnectWise OpenAPI spec down to the operations allowed here and writes the
result to ``data/openapi_catalog.json``. The runtime catalog only ever sees the
filtered file, so anything excluded here has no code path at all.

Rules:

* ``ALLOWED_METHODS`` - HTTP methods kept. DELETE is deliberately excluded:
  there is no delete tool and no delete entry in the catalog.
* ``SELECTED_CATEGORIES`` - OpenAPI tags to keep, or ``None`` for every
  category in the spec. Set to a set of tag names to narrow the surface.

Edit and rebuild with::

    python scripts/build_catalog.py /path/to/full-connectwise-openapi.json
"""

from __future__ import annotations

ALLOWED_METHODS: frozenset[str] = frozenset({"GET", "POST", "PUT", "PATCH"})

# None means "all categories in the spec". To narrow, use a set of tag names,
# e.g. {"Tickets", "Companies", "Contacts"}.
SELECTED_CATEGORIES: frozenset[str] | None = None
