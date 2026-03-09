"""React Router configuration generation."""

from __future__ import annotations

from mira.forge_claude.scaffolder.page_builder import PageSpec


def build_route_imports(pages: list[PageSpec]) -> str:
    """Generate import statements for page components."""
    lines = []
    for page in pages:
        name = page.name
        lines.append(f'import {name} from "./pages/{name}";')
    return "\n".join(lines)


def build_route_elements(pages: list[PageSpec]) -> str:
    """Generate Route elements for React Router."""
    lines = []
    for page in pages:
        lines.append(f'          <Route path="{page.route}" element={{<{page.name} />}} />')
    return "\n".join(lines)
