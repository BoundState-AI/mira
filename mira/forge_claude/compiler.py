"""ForgeClaudeCompiler — production FORGE compiler using forge_claude modules.

Drop-in replacement for mira.forge.ForgeCompiler. Implements the same
compile_database(ForgeCompileRequest) -> ForgeCompileResponse interface
but delegates to forge_claude's modular pipeline (v4.1).
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Callable

LOGGER = logging.getLogger(__name__)

from mira.forge.models import (
    ForgeCompilationSummary,
    ForgeCompileRequest,
    ForgeCompileResponse,
    ForgeGeneratedBundle,
)
from mira.forge_claude.bsms.config_gen import generate_bsms_config
from mira.forge_claude.bsms.lineage_gen import generate_lineage_schema
from mira.forge_claude.bsms.pipeline_gen import generate_bsms_pipeline
from mira.forge_claude.introspector.engine import (
    IntrospectionResult,
    introspect_database_full,
)
from mira.forge_claude.question_gen.curator import curate_questions
from mira.forge_claude.question_gen.execution_plans import annotate_question_map_with_execution_plans
from mira.forge_claude.question_gen.enhanced import generate_questions_enhanced
from mira.forge_claude.question_gen.llm_refiner import refine_questions_with_llm


def _redact_url(url: str) -> str:
    """Redact password from database URL for display."""
    try:
        from sqlalchemy.engine.url import make_url
        parsed = make_url(url)
        return parsed.render_as_string(hide_password=True)
    except Exception:
        return url.split("@")[-1] if "@" in url else url


def _build_capabilities(
    manifest_dict: dict[str, Any],
    relationship_graph_dict: dict[str, Any],
) -> dict[str, Any]:
    """Build capabilities map from manifest and relationships."""
    table_caps: dict[str, list[str]] = {}
    for table in manifest_dict.get("tables", []):
        name = table.get("name", "")
        caps = []
        columns = table.get("columns", [])
        has_numeric = any(
            c.get("type", "") in ("integer", "bigint", "smallint", "numeric", "decimal", "float", "real", "double")
            for c in columns
        )
        has_text = any(
            c.get("type", "") in ("varchar", "char", "text", "string")
            for c in columns
        )
        has_date = any(
            c.get("type", "") in ("date", "datetime", "timestamp", "time")
            for c in columns
        )
        if has_text:
            caps.extend(["text_search", "categorical_filter"])
        if has_numeric:
            caps.extend(["aggregation", "comparison"])
        if has_date:
            caps.append("time_series")
        caps.append("detail_view")
        table_caps[name] = caps

    return {
        "table_capabilities": table_caps,
        "total_tables": len(table_caps),
        "has_relationships": bool(relationship_graph_dict.get("relationships") or relationship_graph_dict.get("edges")),
    }


class ForgeClaudeCompiler:
    """Production FORGE compiler using forge_claude modules."""

    def compile_database(
        self,
        request: ForgeCompileRequest,
        *,
        progress_callback: Callable[[str, str, float], None] | None = None,
    ) -> ForgeCompileResponse:
        """Run the full forge_claude pipeline and return a ForgeCompileResponse."""
        warnings: list[str] = []

        def emit(stage: str, message: str, progress: float) -> None:
            if progress_callback is not None:
                progress_callback(stage, message, progress)

        # Step 1: Full v4.1 introspection
        emit("introspection", "Inspecting schema, profiling columns, and discovering relationships.", 8.0)
        LOGGER.info("FORGE compile START for %s", _redact_url(request.database_url))
        result: IntrospectionResult = introspect_database_full(
            request.database_url,
            sample_count=min(request.sample_rows_per_table, 20),
            enable_profiling=True,
            progress_callback=lambda message, progress: emit(
                "introspection",
                message,
                8.0 + (min(max(progress, 0.0), 100.0) * 0.34),
            ),
        )
        LOGGER.info("FORGE introspection DONE: %d tables, %d columns",
                     result.manifest.statistics.total_tables, result.manifest.statistics.total_columns)

        manifest = result.manifest
        manifest_dict = manifest.model_dump()
        semantic_map_dict = result.semantic_map.model_dump()
        relationship_graph_dict = result.relationship_graph.model_dump()
        latent_dict = result.latent_relationships.model_dump()
        quality_dict = result.data_quality_report.model_dump()

        # Step 2: Question generation
        use_curator = request.max_generated_questions <= 20
        if use_curator:
            emit("question_generation", "Curating top %d intent-driven questions." % request.max_generated_questions, 42.0)
            LOGGER.info("FORGE curator mode: selecting top %d questions", request.max_generated_questions)
            question_map = curate_questions(
                manifest,
                semantic_map=result.semantic_map,
                relationship_graph=result.relationship_graph,
                latent_relationships=result.latent_relationships,
                data_quality_report=result.data_quality_report,
                max_questions=request.max_generated_questions,
                progress_callback=lambda message, progress: emit(
                    "question_generation",
                    message,
                    42.0 + (min(max(progress, 0.0), 100.0) * 0.22),
                ),
            )
            LOGGER.info("FORGE curator produced %d questions across %d categories",
                         sum(len(c.questions) for c in question_map.question_categories),
                         len(question_map.question_categories))

            # LLM polish only (rewrite, no invention)
            emit("llm_refinement", "Polishing curated questions with Sonnet.", 64.0)
            LOGGER.info("FORGE LLM polish starting...")
            try:
                question_map = refine_questions_with_llm(
                    manifest,
                    question_map,
                    require_llm=request.require_llm_refinement,
                    suppress_discovery=True,
                    progress_callback=lambda message, progress: emit(
                        "llm_refinement",
                        message,
                        64.0 + (min(max(progress, 0.0), 100.0) * 0.14),
                    ),
                )
            except Exception as exc:
                if request.require_llm_refinement:
                    raise RuntimeError(f"FORGE compile requires Sonnet refinement: {exc}") from exc
                warnings.append(f"LLM refinement skipped: {exc}")
            LOGGER.info("FORGE LLM polish done")
        else:
            emit("question_generation", "Generating answerable question families from the discovered schema.", 42.0)
            LOGGER.info("FORGE generating questions (enhanced mode, max=%d)...", request.max_generated_questions)
            question_map = generate_questions_enhanced(
                manifest,
                semantic_map=result.semantic_map,
                relationship_graph=result.relationship_graph,
                latent_relationships=result.latent_relationships,
                data_quality_report=result.data_quality_report,
                max_generated_questions=request.max_generated_questions,
                max_questions_per_table=request.max_questions_per_table,
            )
            LOGGER.info("FORGE questions generated: %d categories",
                         len(question_map.question_categories))

            # LLM refinement (best-effort)
            emit("llm_refinement", "Refining generated questions with Sonnet.", 64.0)
            LOGGER.info("FORGE LLM refinement starting...")
            try:
                question_map = refine_questions_with_llm(
                    manifest,
                    question_map,
                    require_llm=request.require_llm_refinement,
                    progress_callback=lambda message, progress: emit(
                        "llm_refinement",
                        message,
                        64.0 + (min(max(progress, 0.0), 100.0) * 0.14),
                    ),
                )
            except Exception as exc:
                if request.require_llm_refinement:
                    raise RuntimeError(f"FORGE compile requires Sonnet refinement: {exc}") from exc
                warnings.append(f"LLM refinement skipped: {exc}")
            LOGGER.info("FORGE LLM refinement done")

        question_map = annotate_question_map_with_execution_plans(question_map, manifest)
        qmap_dict = question_map.model_dump()
        total_questions = sum(len(c.questions) for c in question_map.question_categories)
        LOGGER.info("FORGE total questions: %d", total_questions)

        # Build capabilities
        emit("runtime_planning", "Building capabilities, BSMS config, authority pack, and lineage schema.", 78.0)
        capabilities = _build_capabilities(manifest_dict, relationship_graph_dict)

        # Build BSMS pipeline config
        bsms_pipeline = generate_bsms_config(capabilities, qmap_dict, semantic_map_dict)

        # Build lineage schema
        lineage_schema = generate_lineage_schema()

        # Build scaffold plan
        scaffold_plan = {
            "app_name": request.app_name,
            "pages": ["Home", "Analysis", "Detail"],
            "components": ["SearchBar", "FilterSidebar", "ResultsTable", "StatsBar"],
        }

        # Build authority pack summary
        authority_pack = {
            "manifest": {
                "pack_name": f"{request.app_name} Authority Pack",
                "status": "DRAFT",
            },
            "bouncer": {
                "keywords": bsms_pipeline["bouncer_config"]["domain_keywords"][:60],
                "intents": bsms_pipeline["bouncer_config"]["allowed_intents"],
            },
            "rules_engine": bsms_pipeline["rules_engine"],
        }

        # Determine relationship and latent counts
        rels = relationship_graph_dict.get("relationships", relationship_graph_dict.get("edges", []))
        latent_rels = latent_dict.get("relationships", latent_dict.get("latent_joins", []))

        # Summary
        summary = ForgeCompilationSummary(
            app_name=request.app_name,
            database_url_redacted=_redact_url(request.database_url),
            dialect=manifest.database_type,
            schemas=[],
            table_count=manifest.statistics.total_tables,
            column_count=manifest.statistics.total_columns,
            relationship_count=len(rels) if isinstance(rels, list) else 0,
            latent_relationship_count=len(latent_rels) if isinstance(latent_rels, list) else 0,
            generated_question_count=total_questions,
        )

        # Persist artifacts if requested
        output_dir = None
        generated_bundle = None
        if request.persist_artifacts or getattr(request, "generate_bundle", False):
            emit("artifact_generation", "Writing FORGE artifacts and generated bundle to disk.", 88.0)
            out_root = Path(request.output_dir or f"./forge_output/{request.app_name.lower().replace(' ', '_')}")
            out_root.mkdir(parents=True, exist_ok=True)
            output_dir = str(out_root.resolve())

            artifacts = {
                "schema_manifest.json": manifest_dict,
                "semantic_map.json": semantic_map_dict,
                "relationship_graph.json": relationship_graph_dict,
                "latent_relationships.json": latent_dict,
                "data_quality_report.json": quality_dict,
                "capabilities.json": capabilities,
                "question_map.json": qmap_dict,
                "scaffold_plan.json": scaffold_plan,
                "bsms_pipeline.json": bsms_pipeline,
                "authority_pack.json": authority_pack,
                "lineage_schema.json": lineage_schema,
            }
            for fname, data in artifacts.items():
                (out_root / fname).write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")

            # Generate BSMS runtime
            bsms_dir = generate_bsms_pipeline(out_root, capabilities, qmap_dict, semantic_map_dict)

            files = [str(p.relative_to(out_root)) for p in out_root.rglob("*") if p.is_file()]
            generated_bundle = ForgeGeneratedBundle(
                root_dir=str(out_root),
                artifacts_dir=str(out_root),
                app_dir=str(out_root),
                backend_dir=str(out_root / "backend") if (out_root / "backend").exists() else str(out_root),
                frontend_dir=str(out_root / "frontend") if (out_root / "frontend").exists() else str(out_root),
                authority_pack_dir=str(out_root / "authority_pack") if (out_root / "authority_pack").exists() else str(out_root),
                bsms_pipeline_dir=str(bsms_dir),
                lineage_dir=str(bsms_dir / "lineage"),
                files=files,
            )

        emit("finalizing", "Finalizing FORGE compile response.", 96.0)
        return ForgeCompileResponse(
            status="ok",
            summary=summary,
            schema_manifest=manifest_dict,
            semantic_map=semantic_map_dict,
            relationship_graph=relationship_graph_dict,
            latent_relationships=latent_dict,
            data_quality_report=quality_dict,
            capabilities=capabilities,
            question_map=qmap_dict,
            scaffold_plan=scaffold_plan,
            bsms_pipeline=bsms_pipeline,
            authority_pack=authority_pack,
            lineage_schema=lineage_schema,
            warnings=warnings,
            output_dir=output_dir,
            generated_bundle=generated_bundle,
        )
