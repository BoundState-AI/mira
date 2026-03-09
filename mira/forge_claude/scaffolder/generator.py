"""Main scaffolding orchestrator."""

from __future__ import annotations

import json
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from mira.forge_claude.introspector.manifest import SchemaManifest
from mira.forge_claude.question_gen.question_map import QuestionMap
from mira.forge_claude.scaffolder.api_stub_builder import build_api_endpoints
from mira.forge_claude.scaffolder.component_picker import needs_recharts
from mira.forge_claude.scaffolder.mock_data import generate_mock_data_module, generate_mock_rows
from mira.forge_claude.scaffolder.page_builder import PageSpec, build_pages
from mira.forge_claude.scaffolder.route_builder import build_route_elements, build_route_imports

TEMPLATE_DIR = Path(__file__).parent / "templates"


def _get_jinja_env() -> Environment:
    return Environment(
        loader=FileSystemLoader(str(TEMPLATE_DIR)),
        keep_trailing_newline=True,
    )


def _collect_components(pages: list[PageSpec]) -> set[str]:
    """Collect all unique components used across pages."""
    components = set()
    for page in pages:
        components.update(page.components)
    return components


def _build_mock_columns(manifest: SchemaManifest) -> list[dict]:
    """Build column definitions for ResultsTable from the first major table."""
    if not manifest.tables:
        return []
    # Pick the table with the most columns (likely the main entity)
    table = max(manifest.tables, key=lambda t: len(t.columns))
    columns = []
    for col in table.columns[:8]:  # Limit to 8 columns for display
        columns.append({"key": col.name, "label": col.name.replace("_", " ").title()})
    return columns


def _build_mock_rows(manifest: SchemaManifest) -> list[dict]:
    """Build mock rows for ResultsTable."""
    if not manifest.tables:
        return []
    table = max(manifest.tables, key=lambda t: len(t.columns))
    return generate_mock_rows(table, count=5)


def _build_mock_filters(manifest: SchemaManifest) -> list[dict]:
    """Build filter definitions from categorical columns."""
    filters = []
    for table in manifest.tables:
        for col in table.columns:
            if (
                col.sample_values
                and col.unique_count
                and col.unique_count <= 20
                and not col.primary_key
            ):
                filters.append({
                    "name": col.name,
                    "label": col.name.replace("_", " ").title(),
                    "options": col.sample_values[:10],
                })
    return filters[:5]  # Limit to 5 filters


def _build_mock_stats(manifest: SchemaManifest) -> list[dict]:
    """Build mock stats for StatsBar."""
    stats = []
    stats.append({
        "label": "Total Tables",
        "value": str(manifest.statistics.total_tables),
    })
    stats.append({
        "label": "Total Records",
        "value": f"{manifest.statistics.total_rows:,}",
    })
    for table in manifest.tables[:2]:
        stats.append({
            "label": f"{table.name.replace('_', ' ').title()}",
            "value": f"{table.row_count:,}",
            "sublabel": "records",
        })
    return stats


def _build_mock_detail(manifest: SchemaManifest) -> dict:
    """Build a mock detail record."""
    if not manifest.tables:
        return {}
    table = max(manifest.tables, key=lambda t: len(t.columns))
    rows = generate_mock_rows(table, count=1)
    return rows[0] if rows else {}


def scaffold_frontend(
    question_map: QuestionMap,
    manifest: SchemaManifest,
    output_dir: Path,
    data_quality_report=None,
) -> Path:
    """Generate a complete React + Tailwind frontend.

    Args:
        question_map: The question map from Step 2.
        manifest: The schema manifest from Step 1.
        output_dir: Base output directory.
        data_quality_report: Optional DataQualityReport for quality page context.

    Returns:
        Path to the generated frontend directory.
    """
    env = _get_jinja_env()
    db_name = question_map.database_name
    frontend_dir = output_dir / db_name / "frontend"

    # Build page specs
    pages = build_pages(question_map)
    all_components = _collect_components(pages)
    use_recharts = needs_recharts(all_components)

    # Build API endpoints
    endpoints = build_api_endpoints(question_map)

    # Build mock data
    mock_columns = _build_mock_columns(manifest)
    mock_rows = _build_mock_rows(manifest)
    mock_filters = _build_mock_filters(manifest)
    mock_stats = _build_mock_stats(manifest)
    mock_detail = _build_mock_detail(manifest)

    # Create directory structure
    (frontend_dir / "src" / "pages").mkdir(parents=True, exist_ok=True)
    (frontend_dir / "src" / "components").mkdir(parents=True, exist_ok=True)
    (frontend_dir / "src" / "lib").mkdir(parents=True, exist_ok=True)

    # Render config files
    _render(env, "package.json.j2", frontend_dir / "package.json", {
        "database_name": db_name,
        "needs_recharts": use_recharts,
    })
    _render(env, "vite.config.js.j2", frontend_dir / "vite.config.js", {})
    _render(env, "tailwind.config.js.j2", frontend_dir / "tailwind.config.js", {})
    _render(env, "postcss.config.js.j2", frontend_dir / "postcss.config.js", {})
    _render(env, "index.html.j2", frontend_dir / "index.html", {
        "title": f"{db_name.replace('_', ' ').title()} Explorer",
    })
    _render(env, "main.jsx.j2", frontend_dir / "src" / "main.jsx", {})
    _render(env, "index.css.j2", frontend_dir / "src" / "index.css", {})

    # Render App.jsx with routes
    route_imports = build_route_imports(pages)
    route_elements = build_route_elements(pages)
    _render(env, "App.jsx.j2", frontend_dir / "src" / "App.jsx", {
        "title": f"{db_name.replace('_', ' ').title()} Explorer",
        "pages": [{"name": p.name, "route": p.route} for p in pages],
        "route_imports": route_imports,
        "route_elements": route_elements,
    })

    # Render API stubs
    _render(env, "api.js.j2", frontend_dir / "src" / "lib" / "api.js", {
        "database_name": db_name,
        "endpoints": endpoints,
    })

    # Render components
    for comp in all_components:
        template_name = f"{comp}.jsx.j2"
        try:
            _render(env, template_name, frontend_dir / "src" / "components" / f"{comp}.jsx", {})
        except Exception:
            pass  # Skip components without templates

    # Render pages
    for page in pages:
        template_name = f"{page.name}.jsx.j2"
        context = {
            "title": page.title,
            "database_name": db_name,
            "components": page.components,
            "mock_columns": mock_columns,
            "mock_rows": mock_rows,
            "mock_filters": mock_filters,
            "mock_stats": mock_stats,
            "mock_detail": mock_detail,
        }
        # Merge extra context (e.g., quality data for DataQuality page)
        if page.extra_context:
            # Inject quality summary from data_quality_report if available
            if data_quality_report and "quality_summary" in page.extra_context:
                page.extra_context["quality_summary"] = data_quality_report.summary
            context.update(page.extra_context)
        try:
            _render(env, template_name, frontend_dir / "src" / "pages" / page.filename, context)
        except Exception:
            pass  # Skip pages without templates

    # Write mock data module
    mock_data_js = generate_mock_data_module(manifest)
    (frontend_dir / "src" / "lib" / "mockData.js").write_text(mock_data_js)

    return frontend_dir


def _render(env: Environment, template_name: str, output_path: Path, context: dict) -> None:
    """Render a Jinja2 template to a file."""
    template = env.get_template(template_name)
    content = template.render(**context)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(content)
