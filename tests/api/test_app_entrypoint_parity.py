from __future__ import annotations

from mira.api.app import app as prod_app
from mira.api.app_codex import app as codex_app


def _route_set(app) -> set[tuple[str, tuple[str, ...]]]:
    return {
        (route.path, tuple(sorted(route.methods or [])))
        for route in app.router.routes
        if hasattr(route, "path")
    }


def test_app_entrypoints_have_identical_route_sets():
    assert _route_set(prod_app) == _route_set(codex_app)
