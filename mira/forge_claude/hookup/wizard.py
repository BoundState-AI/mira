"""Interactive CLI wizard for connecting frontend to backend."""

from __future__ import annotations

import json
from pathlib import Path

from mira.forge_claude.config import DEFAULT_OUTPUT_DIR
from mira.forge_claude.hookup.backend_gen import (
    generate_app_py,
    generate_config_py,
    generate_database_py,
)
from mira.forge_claude.hookup.deploy_gen import (
    generate_backend_dockerfile,
    generate_backend_requirements,
    generate_docker_compose,
    generate_frontend_dockerfile,
    generate_railway_json,
    generate_vercel_json,
)
from mira.forge_claude.hookup.model_gen import generate_pydantic_models
from mira.forge_claude.hookup.router_gen import generate_routers
from mira.forge_claude.introspector.manifest import DataQualityReport, SchemaManifest, SemanticMap
from mira.forge_claude.question_gen.question_map import QuestionMap


def run_hookup_wizard(
    question_map: QuestionMap,
    manifest: SchemaManifest,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    db_url: str | None = None,
    *,
    semantic_map: SemanticMap | None = None,
    data_quality_report: DataQualityReport | None = None,
) -> Path:
    """Generate the full backend and deployment configs.

    Args:
        question_map: The question map from Step 2.
        manifest: The schema manifest from Step 1.
        output_dir: Base output directory.
        db_url: Optional database URL for config.
        semantic_map: Optional v4.1 semantic map for enriched models.
        data_quality_report: Optional v4.1 data quality report for health endpoint.

    Returns:
        Path to the generated project directory.
    """
    db_name = question_map.database_name
    project_dir = output_dir / db_name
    backend_dir = project_dir / "backend"
    routers_dir = backend_dir / "routers"
    routers_dir.mkdir(parents=True, exist_ok=True)

    # Generate Pydantic models (with optional semantic descriptions)
    models_code = generate_pydantic_models(manifest, semantic_map=semantic_map)
    (backend_dir / "models.py").write_text(models_code)

    # Generate routers
    router_files = generate_routers(question_map)
    (routers_dir / "__init__.py").write_text("")
    for filename, content in router_files.items():
        (routers_dir / filename).write_text(content)

    # Generate main app (with optional quality stats in health endpoint)
    app_code = generate_app_py(
        question_map, list(router_files.keys()),
        data_quality_report=data_quality_report,
    )
    (backend_dir / "app.py").write_text(app_code)

    # Generate database module
    db_code = generate_database_py()
    (backend_dir / "database.py").write_text(db_code)

    # Generate config
    config_code = generate_config_py(db_name)
    (backend_dir / "config.py").write_text(config_code)

    # Generate deployment configs
    (backend_dir / "Dockerfile").write_text(generate_backend_dockerfile())
    (backend_dir / "requirements.txt").write_text(generate_backend_requirements())

    frontend_dir = project_dir / "frontend"
    if frontend_dir.exists():
        (frontend_dir / "Dockerfile").write_text(generate_frontend_dockerfile())
        (frontend_dir / "vercel.json").write_text(generate_vercel_json())

    (project_dir / "docker-compose.yml").write_text(generate_docker_compose(db_name))
    (backend_dir / "railway.json").write_text(generate_railway_json(db_name))

    return project_dir
