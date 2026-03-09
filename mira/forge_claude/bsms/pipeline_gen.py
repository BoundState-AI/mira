"""Orchestrator: generate complete BSMS runtime directory.

Writes bouncer/, parser/, rules/, formatter/ modules plus
config files and lineage schema into the generated application.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from mira.forge_claude.bsms.bouncer_gen import generate_bouncer_code
from mira.forge_claude.bsms.config_gen import generate_bsms_config
from mira.forge_claude.bsms.formatter_gen import generate_formatter_code
from mira.forge_claude.bsms.lineage_gen import generate_lineage_code, generate_lineage_schema
from mira.forge_claude.bsms.parser_gen import generate_parser_code
from mira.forge_claude.bsms.rules_gen import generate_rules_code
from mira.forge_claude.bsms.service_gen import generate_service_code


def generate_bsms_pipeline(
    output_dir: Path,
    capabilities: dict[str, Any],
    question_map: dict[str, Any],
    semantic_map: dict[str, Any],
) -> Path:
    """Generate the complete BSMS pipeline directory.

    Args:
        output_dir: Root output directory (e.g., forge_output/mydb).
        capabilities: Capabilities dict from the compiler.
        question_map: Question map dict from question generation.
        semantic_map: Semantic map dict from introspection.

    Returns:
        Path to the generated bsms_pipeline directory.
    """
    bsms_dir = output_dir / "bsms_pipeline"
    bsms_code_dir = bsms_dir / "bsms"
    lineage_dir = bsms_dir / "lineage"

    for d in (bsms_code_dir, lineage_dir):
        d.mkdir(parents=True, exist_ok=True)

    # Generate BSMS module files
    (bsms_code_dir / "__init__.py").write_text("", encoding="utf-8")
    (bsms_code_dir / "bouncer.py").write_text(generate_bouncer_code(), encoding="utf-8")
    (bsms_code_dir / "parser.py").write_text(generate_parser_code(), encoding="utf-8")
    (bsms_code_dir / "rules.py").write_text(generate_rules_code(), encoding="utf-8")
    (bsms_code_dir / "formatter.py").write_text(generate_formatter_code(), encoding="utf-8")
    (bsms_code_dir / "service.py").write_text(generate_service_code(), encoding="utf-8")

    # Generate pipeline config
    pipeline_config = generate_bsms_config(capabilities, question_map, semantic_map)
    (bsms_dir / "pipeline_config.json").write_text(
        json.dumps(pipeline_config, indent=2), encoding="utf-8"
    )

    # Generate lineage schema and module
    (lineage_dir / "lineage_schema.json").write_text(
        json.dumps(generate_lineage_schema(), indent=2), encoding="utf-8"
    )
    (lineage_dir / "lineage.py").write_text(generate_lineage_code(), encoding="utf-8")

    return bsms_dir
