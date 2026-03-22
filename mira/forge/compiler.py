#!/usr/bin/env python3
"""
Deterministic FORGE database compiler.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import statistics
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable, Iterable, Optional
from uuid import UUID

from sqlalchemy import MetaData, Table, create_engine, func, inspect, select
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.engine.url import make_url

from .generator import ForgeBundleGenerator
from .models import (
    ForgeCompilationSummary,
    ForgeCompileRequest,
    ForgeCompileResponse,
    ForgeGeneratedBundle,
)

_SYSTEM_SCHEMAS = {
    "postgresql": {"pg_catalog", "information_schema"},
    "mysql": {"information_schema", "mysql", "performance_schema", "sys"},
}
_ALLOWED_DIALECTS = {"sqlite", "postgresql", "mysql"}
_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}
_NUMERIC_TYPES = {"integer", "bigint", "smallint", "numeric", "decimal", "float", "real", "double"}
_TEXT_TYPES = {"varchar", "char", "text", "string"}
_TIME_TYPES = {"date", "datetime", "timestamp", "time"}
_GRAPH_NODE_TYPES = (
    "Material",
    "MaterialType",
    "Specification",
    "Test",
    "Result",
    "Evidence",
    "Precedent",
    "Application",
    "Requirement",
    "Section",
    "Batch",
    "Lookup",
    "Document",
    "Entity",
)
_QUESTION_TYPE_BUDGETS = {
    "relationship": 36,
    "aggregation": 18,
    "filter": 16,
    "text_search": 16,
    "comparison": 14,
    "time_series": 14,
    "detail_view": 18,
}
_MAX_QUESTION_COUNT = 140
_DEFAULT_JOIN_DEPTH = 2
_MAX_JOIN_DEPTH = 3
_MAX_NEIGHBORS_PER_NODE = 12
_MAX_PATH_EXPANSIONS = 2500
_MAX_STATISTICAL_COLUMNS = 360
_MAX_STATISTICAL_PAIRS = 30000
_EXPANSION_NODE_TYPES = {
    "Material",
    "Specification",
    "Test",
    "Result",
    "Evidence",
    "Precedent",
    "Application",
    "Requirement",
    "Section",
    "Document",
}


@dataclass(slots=True)
class _ColumnProfile:
    qualified_table: str
    column_name: str
    data_type: str
    is_primary_key: bool
    is_foreign_key: bool
    nullable: bool
    sample_values: list[Any]
    non_null_values: list[Any]
    stats: dict[str, Any]
    semantic: dict[str, Any]


@dataclass(slots=True)
class _TableProfile:
    schema: Optional[str]
    name: str
    qualified_name: str
    table: Table
    row_count: int
    columns: list[dict[str, Any]]
    column_profiles: list[_ColumnProfile]
    primary_key: list[str]
    foreign_keys: list[dict[str, Any]]
    indexes: list[dict[str, Any]]
    sample_rows: list[dict[str, Any]]


class ForgeCompiler:
    """Compile a database into deterministic FORGE artifacts."""

    def __init__(self) -> None:
        self._bundle_generator = ForgeBundleGenerator()

    def compile_database(
        self,
        request: ForgeCompileRequest,
        *,
        progress_callback: Callable[[str, str, float], None] | None = None,
    ) -> ForgeCompileResponse:
        def _progress(stage: str, message: str, progress: float) -> None:
            if progress_callback is not None:
                progress_callback(stage, message, progress)

        url = self._validate_database_url(request.database_url)
        engine = self._create_engine(url)
        max_questions = request.max_generated_questions
        max_per_table = request.max_questions_per_table

        try:
            _progress("introspection", "Introspecting database schema.", 5.0)
            table_profiles, warnings = self._introspect_database(
                engine=engine,
                sample_rows_per_table=request.sample_rows_per_table,
            )

            if request.require_llm_refinement:
                warnings.append(
                    "LLM refinement requested but not yet implemented. "
                    "Questions were generated using deterministic rules only."
                )

            _progress("schema_manifest", "Building schema manifest.", 15.0)
            schema_manifest = self._build_schema_manifest(
                app_name=request.app_name,
                engine=engine,
                table_profiles=table_profiles,
            )
            semantic_map = self._build_semantic_map(table_profiles)
            _progress("relationship_discovery", "Discovering relationships.", 25.0)
            statistical_relationships = self._discover_statistical_relationships(table_profiles)
            latent_relationships = self._discover_latent_relationships(table_profiles)
            relationship_graph = self._build_relationship_graph(
                table_profiles=table_profiles,
                statistical_relationships=statistical_relationships,
                latent_relationships=latent_relationships,
            )
            _progress("data_quality", "Analyzing data quality.", 40.0)
            data_quality_report = self._build_data_quality_report(table_profiles)
            capabilities = self._build_capabilities(table_profiles, relationship_graph)
            _progress("question_generation", "Generating curated questions.", 55.0)
            question_map = self._build_question_map(
                table_profiles,
                capabilities,
                data_quality_report,
                relationship_graph,
                max_questions=max_questions,
                max_per_table=max_per_table,
            )
            _progress("scaffold", "Building scaffold and pipeline.", 75.0)
            scaffold_plan = self._build_scaffold_plan(request.app_name, question_map)
            bsms_pipeline = self._build_bsms_pipeline(capabilities, question_map, semantic_map)
            authority_pack = self._build_authority_pack(
                request.app_name,
                semantic_map,
                capabilities,
                question_map,
            )
            lineage_schema = self._build_lineage_schema()

            output_dir = None
            generated_bundle: ForgeGeneratedBundle | None = None
            should_write_output = request.persist_artifacts or request.generate_bundle
            _progress("bundle_generation", "Generating application bundle.", 85.0)
            if should_write_output:
                output_root = self._resolve_output_root(request)
                output_dir = str(output_root.resolve())
                self._persist_artifacts(
                    output_root=output_root,
                    artifacts={
                        "schema_manifest.json": schema_manifest,
                        "semantic_map.json": semantic_map,
                        "relationship_graph.json": relationship_graph,
                        "latent_relationships.json": latent_relationships,
                        "data_quality_report.json": data_quality_report,
                        "capabilities.json": capabilities,
                        "question_map.json": question_map,
                        "scaffold_plan.json": scaffold_plan,
                        "bsms_pipeline.json": bsms_pipeline,
                        "authority_pack.json": authority_pack,
                        "lineage_schema.json": lineage_schema,
                    },
                )
                if request.generate_bundle:
                    generated_bundle = self._bundle_generator.generate(
                        base_dir=output_root,
                        app_name=request.app_name,
                        database_url_redacted=url.render_as_string(hide_password=True),
                        schema_manifest=schema_manifest,
                        semantic_map=semantic_map,
                        relationship_graph=relationship_graph,
                        latent_relationships=latent_relationships,
                        data_quality_report=data_quality_report,
                        capabilities=capabilities,
                        question_map=question_map,
                        scaffold_plan=scaffold_plan,
                        bsms_pipeline=bsms_pipeline,
                        authority_pack=authority_pack,
                        lineage_schema=lineage_schema,
                    )

            summary = ForgeCompilationSummary(
                app_name=request.app_name,
                database_url_redacted=url.render_as_string(hide_password=True),
                dialect=engine.dialect.name,
                schemas=sorted(
                    {
                        profile.schema or ("main" if engine.dialect.name == "sqlite" else "default")
                        for profile in table_profiles
                    }
                ),
                table_count=len(table_profiles),
                column_count=sum(len(profile.columns) for profile in table_profiles),
                relationship_count=len(relationship_graph["relationships"]),
                latent_relationship_count=len(latent_relationships["candidates"]),
                generated_question_count=len(question_map["questions"]),
            )

            return ForgeCompileResponse(
                status="ok",
                summary=summary,
                schema_manifest=schema_manifest,
                semantic_map=semantic_map,
                relationship_graph=relationship_graph,
                latent_relationships=latent_relationships,
                data_quality_report=data_quality_report,
                capabilities=capabilities,
                question_map=question_map,
                scaffold_plan=scaffold_plan,
                bsms_pipeline=bsms_pipeline,
                authority_pack=authority_pack,
                lineage_schema=lineage_schema,
                warnings=warnings,
                output_dir=output_dir,
                generated_bundle=generated_bundle,
            )
        finally:
            engine.dispose()

    def _validate_database_url(self, raw_url: str):
        url = make_url(raw_url)
        dialect = url.get_backend_name()
        if dialect not in _ALLOWED_DIALECTS:
            raise ValueError(
                f"Unsupported database dialect '{dialect}'. "
                "FORGE currently supports sqlite, postgresql, and mysql."
            )

        if dialect != "sqlite":
            allow_remote = os.getenv("FORGE_ALLOW_REMOTE_DATABASES", "").strip().lower() in {
                "1",
                "true",
                "yes",
            }
            if (url.host or "").lower() not in _LOCAL_HOSTS and not allow_remote:
                raise ValueError(
                    "Remote database URLs are disabled by default. Use a local database host "
                    "or set FORGE_ALLOW_REMOTE_DATABASES=true explicitly."
                )

        return url

    def _create_engine(self, url) -> Engine:
        connect_args = {"check_same_thread": False} if url.get_backend_name() == "sqlite" else {}
        kwargs = {"future": True, "connect_args": connect_args}
        if url.get_backend_name() != "sqlite":
            kwargs.update({"pool_pre_ping": True, "pool_size": 5, "max_overflow": 10})
        return create_engine(url, **kwargs)

    def _introspect_database(
        self,
        *,
        engine: Engine,
        sample_rows_per_table: int,
    ) -> tuple[list[_TableProfile], list[str]]:
        inspector = inspect(engine)
        schemas = self._list_schemas(engine, inspector)
        warnings: list[str] = []
        profiles: list[_TableProfile] = []

        with engine.connect() as connection:
            for schema in schemas:
                for table_name in inspector.get_table_names(schema=schema):
                    profile = self._profile_table(
                        connection=connection,
                        inspector=inspector,
                        schema=schema,
                        table_name=table_name,
                        sample_rows_per_table=sample_rows_per_table,
                    )
                    profiles.append(profile)

        if not profiles:
            warnings.append("No user tables were discovered in the target database.")

        return profiles, warnings

    def _list_schemas(self, engine: Engine, inspector) -> list[Optional[str]]:
        if engine.dialect.name == "sqlite":
            return [None]

        blocked = _SYSTEM_SCHEMAS.get(engine.dialect.name, set())
        schemas = [schema for schema in inspector.get_schema_names() if schema not in blocked]
        default_schema = inspector.default_schema_name
        if default_schema and default_schema not in schemas and default_schema not in blocked:
            schemas.insert(0, default_schema)
        return schemas or [default_schema]

    def _profile_table(
        self,
        *,
        connection: Connection,
        inspector,
        schema: Optional[str],
        table_name: str,
        sample_rows_per_table: int,
    ) -> _TableProfile:
        metadata = MetaData()
        table = Table(table_name, metadata, schema=schema, autoload_with=connection)
        qualified_name = self._qualified_name(schema, table_name)

        row_count = int(
            connection.execute(select(func.count()).select_from(table)).scalar_one() or 0
        )
        sample_rows = [
            {key: self._json_safe(value) for key, value in row.items()}
            for row in connection.execute(select(*table.c).limit(sample_rows_per_table)).mappings()
        ]

        pk_constraint = inspector.get_pk_constraint(table_name, schema=schema) or {}
        primary_key = [col for col in pk_constraint.get("constrained_columns") or [] if col]

        foreign_keys = []
        fk_columns = set()
        for fk in inspector.get_foreign_keys(table_name, schema=schema):
            constrained = [col for col in fk.get("constrained_columns") or [] if col]
            referred_schema = fk.get("referred_schema")
            referred_table = fk.get("referred_table")
            referred_columns = [col for col in fk.get("referred_columns") or [] if col]
            fk_columns.update(constrained)
            foreign_keys.append(
                {
                    "constrained_columns": constrained,
                    "referred_schema": referred_schema,
                    "referred_table": referred_table,
                    "referred_columns": referred_columns,
                }
            )

        indexes = [
            {
                "name": index.get("name"),
                "column_names": index.get("column_names") or [],
                "unique": bool(index.get("unique")),
            }
            for index in inspector.get_indexes(table_name, schema=schema)
        ]
        unique_constraints = inspector.get_unique_constraints(table_name, schema=schema)
        for constraint in unique_constraints:
            indexes.append(
                {
                    "name": constraint.get("name"),
                    "column_names": constraint.get("column_names") or [],
                    "unique": True,
                }
            )

        columns: list[dict[str, Any]] = []
        column_profiles: list[_ColumnProfile] = []
        for column in inspector.get_columns(table_name, schema=schema):
            col_name = str(column["name"])
            data_type = self._normalize_type(column.get("type"))
            sample_values = [row.get(col_name) for row in sample_rows]
            non_null_values = [value for value in sample_values if value is not None]
            stats = self._profile_column_values(sample_values, data_type, row_count)
            semantic = self._infer_semantic(
                qualified_table=qualified_name,
                column_name=col_name,
                data_type=data_type,
                sample_values=sample_values,
                is_primary_key=col_name in primary_key,
                is_foreign_key=col_name in fk_columns,
            )

            columns.append(
                {
                    "name": col_name,
                    "data_type": data_type,
                    "nullable": bool(column.get("nullable", True)),
                    "default": self._json_safe(column.get("default")),
                    "primary_key": col_name in primary_key,
                    "foreign_key": col_name in fk_columns,
                    "semantic_type": semantic["semantic_type"],
                    "confidence": semantic["confidence"],
                    "stats": stats,
                }
            )
            column_profiles.append(
                _ColumnProfile(
                    qualified_table=qualified_name,
                    column_name=col_name,
                    data_type=data_type,
                    is_primary_key=col_name in primary_key,
                    is_foreign_key=col_name in fk_columns,
                    nullable=bool(column.get("nullable", True)),
                    sample_values=sample_values,
                    non_null_values=non_null_values,
                    stats=stats,
                    semantic=semantic,
                )
            )

        return _TableProfile(
            schema=schema,
            name=table_name,
            qualified_name=qualified_name,
            table=table,
            row_count=row_count,
            columns=columns,
            column_profiles=column_profiles,
            primary_key=primary_key,
            foreign_keys=foreign_keys,
            indexes=indexes,
            sample_rows=sample_rows,
        )

    def _build_schema_manifest(
        self,
        *,
        app_name: str,
        engine: Engine,
        table_profiles: list[_TableProfile],
    ) -> dict[str, Any]:
        return {
            "app_name": app_name,
            "dialect": engine.dialect.name,
            "generated_at": datetime.utcnow().isoformat() + "Z",
            "tables": [
                {
                    "schema": profile.schema,
                    "table_name": profile.name,
                    "qualified_name": profile.qualified_name,
                    "row_count": profile.row_count,
                    "primary_key": profile.primary_key,
                    "foreign_keys": profile.foreign_keys,
                    "indexes": profile.indexes,
                    "columns": profile.columns,
                    "sample_rows": profile.sample_rows[:5],
                }
                for profile in table_profiles
            ],
        }

    def _build_semantic_map(self, table_profiles: list[_TableProfile]) -> dict[str, Any]:
        tables = {}
        for profile in table_profiles:
            tables[profile.qualified_name] = {
                "columns": {
                    column.column_name: column.semantic
                    for column in profile.column_profiles
                }
            }
        return {
            "generated_at": datetime.utcnow().isoformat() + "Z",
            "tables": tables,
        }

    def _build_relationship_graph(
        self,
        *,
        table_profiles: list[_TableProfile],
        statistical_relationships: list[dict[str, Any]],
        latent_relationships: dict[str, Any],
    ) -> dict[str, Any]:
        relationships: list[dict[str, Any]] = []
        seen: set[tuple[str, str, str, str]] = set()

        for profile in table_profiles:
            for fk in profile.foreign_keys:
                source_columns = fk["constrained_columns"]
                target_columns = fk["referred_columns"]
                if not source_columns or not target_columns or not fk.get("referred_table"):
                    continue
                key = (
                    profile.qualified_name,
                    source_columns[0],
                    self._qualified_name(fk.get("referred_schema"), fk["referred_table"]),
                    target_columns[0],
                )
                if key in seen:
                    continue
                seen.add(key)
                relationships.append(
                    {
                        "source_table": profile.qualified_name,
                        "source_column": source_columns[0],
                        "target_table": self._qualified_name(
                            fk.get("referred_schema"),
                            fk["referred_table"],
                        ),
                        "target_column": target_columns[0],
                        "discovery_method": "explicit_foreign_key",
                        "confidence": 1.0,
                        "overlap_ratio": 1.0,
                        "join_coverage": 1.0,
                    }
                )

        for candidate in statistical_relationships:
            key = (
                candidate["left_table"],
                candidate["left_column"],
                candidate["right_table"],
                candidate["right_column"],
            )
            reverse_key = (
                candidate["right_table"],
                candidate["right_column"],
                candidate["left_table"],
                candidate["left_column"],
            )
            if key in seen or reverse_key in seen:
                continue
            seen.add(key)
            relationships.append(
                {
                    "source_table": candidate["left_table"],
                    "source_column": candidate["left_column"],
                    "target_table": candidate["right_table"],
                    "target_column": candidate["right_column"],
                    "discovery_method": "statistical_key_matching",
                    "confidence": candidate["confidence"],
                    "overlap_ratio": candidate["overlap_ratio"],
                    "join_coverage": candidate["join_coverage"],
                }
            )

        for candidate in latent_relationships["candidates"]:
            if not candidate.get("accepted"):
                continue
            key = (
                candidate["left_table"],
                candidate["left_column"],
                candidate["right_table"],
                candidate["right_column"],
            )
            reverse_key = (
                candidate["right_table"],
                candidate["right_column"],
                candidate["left_table"],
                candidate["left_column"],
            )
            if key in seen or reverse_key in seen:
                continue
            seen.add(key)
            relationships.append(
                {
                    "source_table": candidate["left_table"],
                    "source_column": candidate["left_column"],
                    "target_table": candidate["right_table"],
                    "target_column": candidate["right_column"],
                    "discovery_method": candidate["discovery_method"],
                    "confidence": candidate["confidence"],
                    "overlap_ratio": candidate["overlap_ratio"],
                    "join_coverage": candidate["join_coverage"],
                }
            )
        table_bindings = {
            profile.qualified_name: self._bind_table_to_graph_node(profile)
            for profile in table_profiles
        }
        graph_nodes = [
            {
                "table": profile.qualified_name,
                "table_name": profile.name,
                "schema": profile.schema,
                "row_count": profile.row_count,
                **table_bindings[profile.qualified_name],
            }
            for profile in table_profiles
        ]

        typed_relationships = []
        for index, relationship in enumerate(relationships, start=1):
            source_binding = table_bindings.get(relationship["source_table"], {"node_type": "Entity"})
            target_binding = table_bindings.get(relationship["target_table"], {"node_type": "Entity"})
            traversal = self._relationship_traversal_policy(relationship)
            typed_relationships.append(
                {
                    **relationship,
                    "edge_id": f"edge-{index:04d}",
                    "edge_type": self._infer_edge_type(
                        source_binding["node_type"],
                        target_binding["node_type"],
                        relationship,
                    ),
                    "source_node_type": source_binding["node_type"],
                    "target_node_type": target_binding["node_type"],
                    "answerable": traversal["answerable"],
                    "preferred_max_depth": traversal["preferred_max_depth"],
                }
            )

        answerable_paths = self._enumerate_answerable_paths(graph_nodes, typed_relationships)
        return {
            "generated_at": datetime.utcnow().isoformat() + "Z",
            "node_types": list(_GRAPH_NODE_TYPES),
            "relationships": typed_relationships,
            "graph_nodes": graph_nodes,
            "table_bindings": table_bindings,
            "path_templates": self._graph_path_templates(),
            "answerable_paths": answerable_paths,
            "join_depth_policy": {
                "default_depth": _DEFAULT_JOIN_DEPTH,
                "max_depth": _MAX_JOIN_DEPTH,
                "expert_note": "Paths deeper than 3 joins should be curated explicitly rather than generated by default.",
            },
        }

    def _bind_table_to_graph_node(self, profile: _TableProfile) -> dict[str, Any]:
        name = profile.name.lower()
        schema = (profile.schema or "default").lower()
        columns = {column.column_name.lower() for column in profile.column_profiles}

        node_type = "Entity"
        semantic_role = "general_record"
        if name.endswith("_results") or name == "test_results":
            node_type = "Result"
            semantic_role = "result_record"
        elif name.endswith("_tests") or name == "tests":
            node_type = "Test"
            semantic_role = "test_record"
        elif "material_spec" in name or "specification" in name:
            node_type = "Specification"
            semantic_role = "material_specification"
        elif name in {"materials", "material"} or ("material_code" in columns and "material" in name):
            node_type = "Material"
            semantic_role = "material_master"
        elif "material_type" in name or name.endswith("material_types"):
            node_type = "MaterialType"
            semantic_role = "material_taxonomy"
        elif "evidence" in name:
            node_type = "Evidence"
            semantic_role = "evidence_record"
        elif "precedent" in name:
            node_type = "Precedent"
            semantic_role = "precedent_record"
        elif "application" in name:
            node_type = "Application"
            semantic_role = "application_record"
        elif "requirement" in name:
            node_type = "Requirement"
            semantic_role = "requirement_record"
        elif "section" in name:
            node_type = "Section"
            semantic_role = "document_section"
        elif "batch" in name or "import" in name or schema == "stage":
            node_type = "Batch"
            semantic_role = "ingest_batch"
        elif schema in {"ref", "view"}:
            node_type = "Lookup"
            semantic_role = "reference_lookup"
        elif {"document_id", "document_title"} & columns:
            node_type = "Document"
            semantic_role = "document_record"

        anchor_priority = {
            "Material": 100,
            "Application": 95,
            "Evidence": 92,
            "Precedent": 90,
            "Specification": 88,
            "Test": 86,
            "Result": 82,
            "Requirement": 80,
            "Section": 78,
            "Document": 75,
            "Lookup": 65,
            "Batch": 60,
            "MaterialType": 58,
            "Entity": 50,
        }[node_type]

        return {
            "node_type": node_type,
            "semantic_role": semantic_role,
            "anchor_priority": anchor_priority,
        }

    def _relationship_traversal_policy(self, relationship: dict[str, Any]) -> dict[str, Any]:
        method = relationship["discovery_method"]
        confidence = float(relationship.get("confidence", 0.0))
        if method == "explicit_foreign_key":
            return {"answerable": True, "preferred_max_depth": _MAX_JOIN_DEPTH}
        if method == "statistical_key_matching" and confidence >= 0.92:
            return {"answerable": True, "preferred_max_depth": 2}
        if method == "latent_entropy" and confidence >= 0.9:
            return {"answerable": True, "preferred_max_depth": 2}
        return {"answerable": False, "preferred_max_depth": 1}

    def _infer_edge_type(
        self,
        source_node_type: str,
        target_node_type: str,
        relationship: dict[str, Any],
    ) -> str:
        pair = (source_node_type, target_node_type)
        if pair == ("Result", "Test"):
            return "RESULT_OF_TEST"
        if pair == ("Test", "Material"):
            return "TEST_OF_MATERIAL"
        if pair == ("Result", "Material"):
            return "RESULT_FOR_MATERIAL"
        if pair == ("Evidence", "Material"):
            return "EVIDENCE_FOR_MATERIAL"
        if pair == ("Application", "Material"):
            return "APPLICATION_OF_MATERIAL"
        if pair == ("Requirement", "Section"):
            return "REQUIREMENT_IN_SECTION"
        if pair == ("Specification", "Material"):
            return "SPECIFIES_MATERIAL"
        if pair == ("Material", "MaterialType"):
            return "HAS_MATERIAL_TYPE"
        if relationship["source_column"].endswith("_id") and relationship["target_column"].endswith("_id"):
            return "IDENTIFIER_REFERENCE"
        return "REFERENCES"

    def _graph_path_templates(self) -> list[dict[str, Any]]:
        return [
            {
                "family": "material_to_test",
                "node_types": ["Material", "Test"],
                "question_type": "relationship",
            },
            {
                "family": "material_to_test_to_result",
                "node_types": ["Material", "Test", "Result"],
                "question_type": "relationship",
            },
            {
                "family": "application_to_material",
                "node_types": ["Application", "Material"],
                "question_type": "relationship",
            },
            {
                "family": "evidence_to_material",
                "node_types": ["Evidence", "Material"],
                "question_type": "relationship",
            },
            {
                "family": "specification_to_material",
                "node_types": ["Specification", "Material"],
                "question_type": "relationship",
            },
            {
                "family": "requirement_to_section",
                "node_types": ["Requirement", "Section"],
                "question_type": "relationship",
            },
            {
                "family": "test_to_result",
                "node_types": ["Test", "Result"],
                "question_type": "relationship",
            },
        ]

    def _enumerate_answerable_paths(
        self,
        graph_nodes: list[dict[str, Any]],
        relationships: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        node_lookup = {node["table"]: node for node in graph_nodes}
        adjacency: dict[str, list[dict[str, Any]]] = defaultdict(list)
        discovered: dict[tuple[str, ...], dict[str, Any]] = {}

        for edge in relationships:
            if not edge.get("answerable"):
                continue
            direct_path = self._materialize_answerable_path(
                [edge["source_table"], edge["target_table"]],
                [
                    {
                        "source_table": edge["source_table"],
                        "source_column": edge["source_column"],
                        "target_table": edge["target_table"],
                        "target_column": edge["target_column"],
                        "edge_id": edge["edge_id"],
                        "edge_type": edge["edge_type"],
                        "discovery_method": edge["discovery_method"],
                        "confidence": edge["confidence"],
                        "preferred_max_depth": edge["preferred_max_depth"],
                    }
                ],
                node_lookup,
            )
            if direct_path is not None:
                discovered[tuple(direct_path["tables"])] = direct_path
            adjacency[edge["source_table"]].append(
                {
                    "next_table": edge["target_table"],
                    "step": {
                        "source_table": edge["source_table"],
                        "source_column": edge["source_column"],
                        "target_table": edge["target_table"],
                        "target_column": edge["target_column"],
                        "edge_id": edge["edge_id"],
                        "edge_type": edge["edge_type"],
                        "discovery_method": edge["discovery_method"],
                        "confidence": edge["confidence"],
                        "preferred_max_depth": edge["preferred_max_depth"],
                    },
                }
            )
            adjacency[edge["target_table"]].append(
                {
                    "next_table": edge["source_table"],
                    "step": {
                        "source_table": edge["target_table"],
                        "source_column": edge["target_column"],
                        "target_table": edge["source_table"],
                        "target_column": edge["source_column"],
                        "edge_id": edge["edge_id"],
                        "edge_type": edge["edge_type"],
                        "discovery_method": edge["discovery_method"],
                        "confidence": edge["confidence"],
                        "preferred_max_depth": edge["preferred_max_depth"],
                    },
                }
            )

        for table, neighbors in list(adjacency.items()):
            neighbors.sort(
                key=lambda item: (
                    float(item["step"].get("confidence", 0.0)),
                    node_lookup.get(item["next_table"], {}).get("anchor_priority", 0),
                    1 if node_lookup.get(item["next_table"], {}).get("node_type") != "Entity" else 0,
                ),
                reverse=True,
            )
            adjacency[table] = neighbors[:_MAX_NEIGHBORS_PER_NODE]

        seed_tables = sorted(
            [
                node
                for node in graph_nodes
                if node["node_type"] != "Entity" or len(graph_nodes) <= 20
            ],
            key=lambda node: (node["anchor_priority"], node["row_count"]),
            reverse=True,
        )[:24]

        expansions = 0
        for seed in seed_tables:
            stack: list[tuple[str, list[str], list[dict[str, Any]]]] = [(seed["table"], [seed["table"]], [])]
            while stack:
                current, visited, steps = stack.pop()
                if steps:
                    path = self._materialize_answerable_path(visited, steps, node_lookup)
                    if path is not None:
                        signature = tuple(path["tables"])
                        best = discovered.get(signature)
                        if best is None or path["confidence"] > best["confidence"]:
                            discovered[signature] = path
                if len(steps) >= _MAX_JOIN_DEPTH:
                    continue
                if steps and not self._should_expand_path(visited, node_lookup):
                    continue
                for neighbor in adjacency.get(current, []):
                    expansions += 1
                    if expansions > _MAX_PATH_EXPANSIONS:
                        break
                    next_table = neighbor["next_table"]
                    if next_table in visited:
                        continue
                    next_depth = len(steps) + 1
                    if next_depth > int(neighbor["step"].get("preferred_max_depth", _DEFAULT_JOIN_DEPTH)):
                        continue
                    candidate_tables = visited + [next_table]
                    if next_depth > 1 and not self._supports_path_prefix(candidate_tables, node_lookup):
                        continue
                    stack.append((next_table, candidate_tables, steps + [neighbor["step"]]))
                if expansions > _MAX_PATH_EXPANSIONS:
                    break
            if expansions > _MAX_PATH_EXPANSIONS:
                break

        return sorted(
            discovered.values(),
            key=lambda item: (item["priority"], item["confidence"], -item["depth"]),
            reverse=True,
        )[:160]

    def _should_expand_path(
        self,
        tables: list[str],
        node_lookup: dict[str, dict[str, Any]],
    ) -> bool:
        node_types = [node_lookup[table]["node_type"] for table in tables]
        if any(node_type in _EXPANSION_NODE_TYPES for node_type in node_types):
            return True
        return self._supports_path_prefix(tables, node_lookup)

    def _supports_path_prefix(
        self,
        tables: list[str],
        node_lookup: dict[str, dict[str, Any]],
    ) -> bool:
        if len(tables) <= 2:
            return True
        node_types = [node_lookup[table]["node_type"] for table in tables]
        templates = [template["node_types"] for template in self._graph_path_templates()]
        for template in templates:
            if tuple(node_types) == tuple(template[: len(node_types)]):
                return True
            if tuple(reversed(node_types)) == tuple(template[: len(node_types)]):
                return True
        return len(set(node_types) & _EXPANSION_NODE_TYPES) >= 2

    def _materialize_answerable_path(
        self,
        tables: list[str],
        join_path: list[dict[str, Any]],
        node_lookup: dict[str, dict[str, Any]],
    ) -> dict[str, Any] | None:
        if len(tables) < 2:
            return None
        node_types = [node_lookup[table]["node_type"] for table in tables]
        if not self._path_has_engineering_value(node_types):
            return None

        family = self._infer_path_family(node_types)
        confidence = round(
            sum(float(step["confidence"]) for step in join_path) / max(1, len(join_path)),
            4,
        )
        priority = round(
            confidence
            + (0.12 if "Material" in node_types else 0.0)
            + (0.08 if "Result" in node_types else 0.0)
            + (0.06 if "Evidence" in node_types or "Precedent" in node_types else 0.0)
            - (0.03 * max(0, len(join_path) - _DEFAULT_JOIN_DEPTH)),
            4,
        )
        prompt = self._path_prompt(family, tables, node_types)
        if prompt is None:
            return None

        return {
            "path_id": self._slugify("-".join(tables)),
            "family": family,
            "depth": len(join_path),
            "tables": tables,
            "node_types": node_types,
            "join_path": join_path,
            "confidence": confidence,
            "priority": priority,
            "question_type": "relationship",
            "prompt": prompt,
        }

    def _path_has_engineering_value(self, node_types: list[str]) -> bool:
        joined = set(node_types)
        if "Material" in joined and "Test" in joined:
            return True
        if "Material" in joined and "Result" in joined:
            return True
        if "Evidence" in joined and "Material" in joined:
            return True
        if "Application" in joined and "Material" in joined:
            return True
        if "Requirement" in joined and "Section" in joined:
            return True
        if "Test" in joined and "Result" in joined:
            return True
        if len(node_types) == 2:
            return joined != {"Batch"}
        return len(joined) >= 2 and "Entity" not in joined

    def _infer_path_family(self, node_types: list[str]) -> str:
        templates = {tuple(template["node_types"]): template["family"] for template in self._graph_path_templates()}
        family = templates.get(tuple(node_types))
        if family:
            return family
        if len(node_types) == 2:
            return "direct_join"
        if "Material" in node_types and "Result" in node_types:
            return "material_result_trace"
        if "Material" in node_types and "Test" in node_types:
            return "material_test_trace"
        if "Evidence" in node_types:
            return "evidence_trace"
        return "join_path"

    def _path_prompt(
        self,
        family: str,
        tables: list[str],
        node_types: list[str],
    ) -> str | None:
        display_tables = [table.split(".", 1)[-1] for table in tables]
        if family == "material_to_test":
            return f"What {display_tables[-1]} records are available for a given material?"
        if family == "material_to_test_to_result":
            return (
                f"For a given material, what {display_tables[-1]} outcomes can be answered through "
                f"{display_tables[1]}?"
            )
        if family == "application_to_material":
            return f"Which materials are referenced by each {display_tables[0]} record?"
        if family == "evidence_to_material":
            return f"What material evidence can be retrieved by joining {display_tables[0]} to {display_tables[-1]}?"
        if family == "specification_to_material":
            return f"Which materials are governed by each {display_tables[0]} entry?"
        if family == "requirement_to_section":
            return f"Which requirements belong to each {display_tables[-1]} section?"
        if family == "test_to_result":
            return f"What {display_tables[-1]} records are available for each {display_tables[0]} test?"
        if family == "material_result_trace":
            return f"For a material, what can be answered by joining {' -> '.join(display_tables)}?"
        if family == "material_test_trace":
            return f"What engineering questions can be answered by joining {' -> '.join(display_tables)}?"
        if family == "evidence_trace":
            return f"What evidence-backed joins are available across {' -> '.join(display_tables)}?"
        if family == "direct_join":
            return f"What can be answered by joining {display_tables[0]} to {display_tables[-1]}?"
        if len(tables) <= _DEFAULT_JOIN_DEPTH + 1:
            return f"What can be answered by joining {' -> '.join(display_tables)}?"
        return None

    def _discover_statistical_relationships(
        self,
        table_profiles: list[_TableProfile],
    ) -> list[dict[str, Any]]:
        candidates: list[dict[str, Any]] = []
        columns = [
            column
            for profile in table_profiles
            for column in profile.column_profiles
            if column.semantic["family"] in {"identifier", "reference"}
            and float(column.semantic.get("confidence", 0.0)) >= 0.8
        ]
        columns.sort(
            key=lambda column: (
                1 if column.is_foreign_key else 0,
                1 if column.semantic["semantic_type"] in {"foreign_key", "business_code", "primary_key"} else 0,
                len(column.non_null_values),
            ),
            reverse=True,
        )
        columns = columns[:_MAX_STATISTICAL_COLUMNS]
        token_cache = {
            (column.qualified_table, column.column_name): {
                token
                for value in column.non_null_values
                if (token := self._normalized_token(value))
            }
            for column in columns
        }
        comparisons = 0

        for index, left in enumerate(columns):
            left_values = token_cache[(left.qualified_table, left.column_name)]
            if len(left_values) < 2:
                continue
            for right in columns[index + 1:]:
                if comparisons >= _MAX_STATISTICAL_PAIRS:
                    break
                if left.qualified_table == right.qualified_table:
                    continue
                if not self._compatible_semantic_families(left.semantic, right.semantic):
                    continue
                right_values = token_cache[(right.qualified_table, right.column_name)]
                smaller = min(len(left_values), len(right_values))
                if smaller == 0:
                    continue
                larger = max(len(left_values), len(right_values))
                if larger / smaller > 40:
                    continue
                comparisons += 1
                overlap = left_values & right_values
                overlap_ratio = len(overlap) / smaller
                if overlap_ratio < 0.8:
                    continue

                candidates.append(
                    {
                        "left_table": left.qualified_table,
                        "left_column": left.column_name,
                        "right_table": right.qualified_table,
                        "right_column": right.column_name,
                        "overlap_ratio": round(overlap_ratio, 4),
                        "join_coverage": round(overlap_ratio, 4),
                        "confidence": round(min(0.98, 0.75 + (overlap_ratio * 0.2)), 4),
                    }
                )
            if comparisons >= _MAX_STATISTICAL_PAIRS:
                break

        return candidates

    def _discover_latent_relationships(self, table_profiles: list[_TableProfile]) -> dict[str, Any]:
        candidates: list[dict[str, Any]] = []
        all_columns = [
            column
            for profile in table_profiles
            for column in profile.column_profiles
            if not column.is_primary_key and not column.is_foreign_key
        ]

        max_pairs = min(len(all_columns) ** 2, 400)
        comparisons = 0
        for index, left in enumerate(all_columns):
            for right in all_columns[index + 1:]:
                if comparisons >= max_pairs:
                    break
                if left.qualified_table == right.qualified_table:
                    continue
                if not self._compatible_semantic_families(left.semantic, right.semantic):
                    continue
                left_values = [self._normalized_token(value) for value in left.non_null_values]
                right_values = [self._normalized_token(value) for value in right.non_null_values]
                left_values = [value for value in left_values if value]
                right_values = [value for value in right_values if value]
                if len(left_values) < 3 or len(right_values) < 3:
                    continue

                left_unique = set(left_values)
                right_unique = set(right_values)
                smaller = min(len(left_unique), len(right_unique))
                larger = max(len(left_unique), len(right_unique))
                if smaller == 0 or larger / smaller > 100:
                    continue

                overlap = left_unique & right_unique
                overlap_ratio = len(overlap) / smaller
                mutual_information = self._mutual_information(left_values, right_values)
                composite = round(
                    min(1.0, (mutual_information * 0.55) + (overlap_ratio * 0.45)),
                    4,
                )
                join_coverage = round(overlap_ratio, 4)
                accepted = overlap_ratio >= 0.8 and composite >= 0.55

                candidates.append(
                    {
                        "left_table": left.qualified_table,
                        "left_column": left.column_name,
                        "right_table": right.qualified_table,
                        "right_column": right.column_name,
                        "semantic_family": left.semantic["family"],
                        "mutual_information": round(mutual_information, 4),
                        "overlap_ratio": round(overlap_ratio, 4),
                        "join_coverage": join_coverage,
                        "confidence": composite,
                        "accepted": accepted,
                        "discovery_method": (
                            "latent_entropy" if accepted else "latent_entropy_candidate"
                        ),
                    }
                )
                comparisons += 1

        return {
            "generated_at": datetime.utcnow().isoformat() + "Z",
            "comparison_budget": max_pairs,
            "candidates": sorted(
                candidates,
                key=lambda item: (item["accepted"], item["confidence"], item["overlap_ratio"]),
                reverse=True,
            ),
        }

    def _build_data_quality_report(self, table_profiles: list[_TableProfile]) -> dict[str, Any]:
        tables = {}
        for profile in table_profiles:
            anomalies: list[str] = []
            columns = {}
            for column in profile.column_profiles:
                if column.stats["null_rate"] >= 0.5:
                    anomalies.append(
                        f"{column.column_name} has null_rate {column.stats['null_rate']:.2f}"
                    )
                if (
                    column.column_name.endswith("_id")
                    and not column.is_primary_key
                    and not column.is_foreign_key
                ):
                    anomalies.append(f"{column.column_name} looks relational but has no FK")
                columns[column.column_name] = {
                    "null_rate": column.stats["null_rate"],
                    "distinct_ratio": column.stats["distinct_ratio"],
                    "sample_size": column.stats["sample_size"],
                    "outliers_detected": column.stats.get("outliers_detected", 0),
                    "inconsistent_units": column.stats.get("inconsistent_units", False),
                    "semantic_type": column.semantic["semantic_type"],
                }

            duplicate_key_columns = []
            for key_col in profile.primary_key:
                matching = next(
                    (column for column in profile.column_profiles if column.column_name == key_col),
                    None,
                )
                if matching and matching.stats["duplicate_sample_values"] > 0:
                    duplicate_key_columns.append(key_col)
                    anomalies.append(f"Primary key sample duplicates found in {key_col}")

            tables[profile.qualified_name] = {
                "row_count": profile.row_count,
                "columns": columns,
                "duplicate_key_columns": duplicate_key_columns,
                "schema_anomalies": sorted(set(anomalies)),
            }

        return {
            "generated_at": datetime.utcnow().isoformat() + "Z",
            "tables": tables,
        }

    def _build_capabilities(
        self,
        table_profiles: list[_TableProfile],
        relationship_graph: dict[str, Any],
    ) -> dict[str, Any]:
        relationships_by_table: dict[str, int] = Counter()
        for relationship in relationship_graph["relationships"]:
            relationships_by_table[relationship["source_table"]] += 1
            relationships_by_table[relationship["target_table"]] += 1

        table_capabilities = {}
        unsupported_global: list[str] = []
        has_timestamp = False

        for profile in table_profiles:
            numeric_columns = [
                column.column_name
                for column in profile.column_profiles
                if self._is_numeric_type(column.data_type)
            ]
            categorical_columns = [
                column.column_name
                for column in profile.column_profiles
                if column.stats["distinct_count"] <= 20 and column.stats["sample_size"] > 0
            ]
            timestamp_columns = [
                column.column_name
                for column in profile.column_profiles
                if self._is_time_type(column.data_type) or column.semantic["semantic_type"] == "timestamp"
            ]
            text_columns = [
                column.column_name
                for column in profile.column_profiles
                if self._is_text_type(column.data_type)
            ]

            has_timestamp = has_timestamp or bool(timestamp_columns)

            supported = {
                "lookup": bool(profile.primary_key),
                "filter": bool(categorical_columns),
                "aggregation": bool(numeric_columns),
                "comparison": len(numeric_columns) >= 2,
                "trend": bool(timestamp_columns and numeric_columns),
                "relationship": relationships_by_table.get(profile.qualified_name, 0) > 0,
                "classification": bool(categorical_columns or numeric_columns),
                "search": bool(text_columns),
                "detail_view": True,
            }

            unsupported = [name for name, value in supported.items() if not value]
            table_capabilities[profile.qualified_name] = {
                **supported,
                "supported_operations": [name for name, value in supported.items() if value],
                "unsupported_operations": unsupported,
                "numeric_columns": numeric_columns,
                "categorical_columns": categorical_columns,
                "timestamp_columns": timestamp_columns,
                "text_columns": text_columns,
            }

        if not has_timestamp:
            unsupported_global.append(
                "Trend analysis unsupported because no timestamp-like columns were detected."
            )

        return {
            "generated_at": datetime.utcnow().isoformat() + "Z",
            "table_capabilities": table_capabilities,
            "unsupported_questions": unsupported_global,
            "demoted_questions": [],
        }

    def _build_question_map(
        self,
        table_profiles: list[_TableProfile],
        capabilities: dict[str, Any],
        data_quality_report: dict[str, Any],
        relationship_graph: dict[str, Any],
        *,
        max_questions: int = _MAX_QUESTION_COUNT,
        max_per_table: int = 0,
    ) -> dict[str, Any]:
        all_candidates: list[dict[str, Any]] = []
        by_table: dict[str, list[dict[str, Any]]] = defaultdict(list)
        demoted: list[dict[str, Any]] = []
        paths_by_root: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for path in relationship_graph.get("answerable_paths", []):
            if path["tables"]:
                paths_by_root[path["tables"][0]].append(path)

        for profile in table_profiles:
            cap = capabilities["table_capabilities"][profile.qualified_name]
            quality = data_quality_report["tables"][profile.qualified_name]
            questions: list[dict[str, Any]] = []
            richness = len(cap["supported_operations"])
            path_count = len(paths_by_root.get(profile.qualified_name, []))

            questions.append(
                self._make_question(
                    profile.qualified_name,
                    "detail_view",
                    f"View the full record details for {profile.name}.",
                    round(0.5 + min(0.24, richness * 0.025) + min(0.06, path_count * 0.01), 3),
                )
            )

            if cap["numeric_columns"]:
                numeric = cap["numeric_columns"][0]
                questions.append(
                    self._make_question(
                        profile.qualified_name,
                        "aggregation",
                        f"What are the min, max, and average values for {numeric} in {profile.name}?",
                        round(0.68 + min(0.12, richness * 0.012), 3),
                    )
                )

            if cap["filter"]:
                column = cap["categorical_columns"][0]
                questions.append(
                    self._make_question(
                        profile.qualified_name,
                        "filter",
                        f"Filter {profile.name} records by {column}.",
                        round(0.66 + min(0.1, richness * 0.012), 3),
                    )
                )

            if cap["search"]:
                column = cap["text_columns"][0]
                questions.append(
                    self._make_question(
                        profile.qualified_name,
                        "text_search",
                        f"Search {profile.name} by {column}.",
                        round(0.64 + min(0.1, richness * 0.012), 3),
                    )
                )

            if cap["comparison"]:
                first, second = cap["numeric_columns"][:2]
                questions.append(
                    self._make_question(
                        profile.qualified_name,
                        "comparison",
                        f"Compare {first} versus {second} in {profile.name}.",
                        round(0.62 + min(0.1, richness * 0.012), 3),
                    )
                )

            if cap["trend"]:
                ts = cap["timestamp_columns"][0]
                numeric = cap["numeric_columns"][0]
                questions.append(
                    self._make_question(
                        profile.qualified_name,
                        "time_series",
                        f"How does {numeric} change over {ts} in {profile.name}?",
                        round(0.67 + min(0.1, richness * 0.012), 3),
                    )
                )

            if cap["relationship"] and not paths_by_root.get(profile.qualified_name):
                questions.append(
                    self._make_question(
                        profile.qualified_name,
                        "relationship",
                        f"Which related records connect to {profile.name} through discovered joins?",
                        round(0.69 + min(0.1, richness * 0.012), 3),
                    )
                )

            scored = []
            for question in questions:
                quality_penalty = 0.0
                for column_name, column_quality in quality["columns"].items():
                    if column_quality["null_rate"] > 0.5 and column_name in question["question"]:
                        quality_penalty += 0.15
                question["utility_score"] = round(max(0.0, question["utility_score"] - quality_penalty), 3)
                scored.append(question)

            for question in sorted(scored, key=lambda item: item["utility_score"], reverse=True):
                by_table[profile.qualified_name].append(question)
                all_candidates.append(question)

        for path in relationship_graph.get("answerable_paths", []):
            question = self._make_question(
                path["tables"][0],
                path["question_type"],
                path["prompt"],
                round(min(0.94, 0.74 + (path["priority"] * 0.12)), 3),
            )
            question.update(
                {
                    "join_path": path["join_path"],
                    "path_tables": path["tables"],
                    "path_node_types": path["node_types"],
                    "path_depth": path["depth"],
                    "path_family": path["family"],
                    "graph_path_id": path["path_id"],
                }
            )
            by_table[question["table"]].append(question)
            all_candidates.append(question)

        deduped: list[dict[str, Any]] = []
        seen: set[tuple[str, str, tuple[str, ...]]] = set()
        for question in sorted(all_candidates, key=lambda item: item["utility_score"], reverse=True):
            dedupe_key = (
                question["question_type"],
                question["question"],
                tuple(question.get("path_tables", [])),
            )
            if dedupe_key in seen:
                demoted.append(
                    {
                        "table": question["table"],
                        "question": question["question"],
                        "reason": "redundant",
                    }
                )
                continue
            seen.add(dedupe_key)
            deduped.append(question)

        selected, allocation_demoted = self._allocate_question_budgets(
            deduped, max_questions=max_questions, max_per_table=max_per_table,
        )
        demoted.extend(allocation_demoted)
        selected_lookup = {question["id"] for question in selected}

        capabilities["demoted_questions"] = demoted
        return {
            "generated_at": datetime.utcnow().isoformat() + "Z",
            "questions": selected,
            "questions_by_table": {
                table: [question for question in questions if question["id"] in selected_lookup]
                for table, questions in by_table.items()
                if any(question["id"] in selected_lookup for question in questions)
            },
            "question_type_counts": dict(Counter(question["question_type"] for question in selected)),
            "answerable_join_paths": relationship_graph.get("answerable_paths", [])[:60],
            "join_depth_policy": relationship_graph.get("join_depth_policy", {}),
        }

    def _allocate_question_budgets(
        self,
        questions: list[dict[str, Any]],
        *,
        max_questions: int = _MAX_QUESTION_COUNT,
        max_per_table: int = 0,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        cap = max_questions if max_questions > 0 else _MAX_QUESTION_COUNT

        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for question in questions:
            grouped[question["question_type"]].append(question)

        for items in grouped.values():
            items.sort(key=lambda item: item["utility_score"], reverse=True)

        selected: list[dict[str, Any]] = []
        selected_ids: set[str] = set()
        demoted: list[dict[str, Any]] = []
        table_counts: dict[str, int] = Counter()

        for question_type, budget in _QUESTION_TYPE_BUDGETS.items():
            bucket = grouped.get(question_type, [])
            for question in bucket[:budget]:
                if question["id"] in selected_ids:
                    continue
                if max_per_table > 0 and table_counts[question["table"]] >= max_per_table:
                    demoted.append(
                        {
                            "table": question["table"],
                            "question": question["question"],
                            "reason": "per_table_cap",
                        }
                    )
                    continue
                selected.append(question)
                selected_ids.add(question["id"])
                table_counts[question["table"]] += 1
            for question in bucket[budget:]:
                demoted.append(
                    {
                        "table": question["table"],
                        "question": question["question"],
                        "reason": f"type_budget:{question_type}",
                    }
                )

        leftovers = [
            question
            for question in sorted(questions, key=lambda item: item["utility_score"], reverse=True)
            if question["id"] not in selected_ids
        ]
        for question in leftovers:
            if len(selected) >= cap:
                demoted.append(
                    {
                        "table": question["table"],
                        "question": question["question"],
                        "reason": "application_cap",
                    }
                )
                continue
            if max_per_table > 0 and table_counts[question["table"]] >= max_per_table:
                demoted.append(
                    {
                        "table": question["table"],
                        "question": question["question"],
                        "reason": "per_table_cap",
                    }
                )
                continue
            selected.append(question)
            selected_ids.add(question["id"])
            table_counts[question["table"]] += 1

        selected.sort(key=lambda item: item["utility_score"], reverse=True)
        return selected[:cap], demoted

    def _build_scaffold_plan(self, app_name: str, question_map: dict[str, Any]) -> dict[str, Any]:
        question_types = sorted({question["question_type"] for question in question_map["questions"]})
        component_library = {
            "text_search": "SearchBar",
            "filter": "FilterSidebar",
            "detail_view": "DetailPanel",
            "aggregation": "StatsBar",
            "comparison": "ComparisonView",
            "time_series": "TimelineView",
            "relationship": "EvidenceViewer",
        }
        components = sorted({component_library[q] for q in question_types if q in component_library})

        return {
            "app_name": app_name,
            "frontend": {
                "framework": "React + Tailwind",
                "pages": [
                    "Home",
                    "Analysis",
                    "Detail",
                    "Admin",
                ],
                "components": components,
            },
            "backend": {
                "framework": "FastAPI + SQLAlchemy",
                "generated_endpoints": [
                    f"/api/generated/{question['table'].replace('.', '/')}/{question['question_type']}"
                    for question in question_map["questions"][:20]
                ],
            },
        }

    def _build_bsms_pipeline(
        self,
        capabilities: dict[str, Any],
        question_map: dict[str, Any],
        semantic_map: dict[str, Any],
    ) -> dict[str, Any]:
        allowed_intents = sorted({question["question_type"] for question in question_map["questions"]})
        vocabulary = sorted(
            {
                column_name
                for table in semantic_map["tables"].values()
                for column_name in table["columns"].keys()
            }
        )
        return {
            "architecture": "Bouncer -> LLM Parse -> Deterministic Rules -> LLM Format",
            "bouncer_config": {
                "allowed_intents": allowed_intents,
                "domain_keywords": vocabulary[:100],
                "mutation_terms_blocked": [
                    "delete",
                    "drop",
                    "truncate",
                    "update",
                    "insert",
                    "alter",
                    "create",
                    "grant",
                    "revoke",
                ],
            },
            "parser_config": {
                "field_mappings": {
                    table_name: list(table["columns"].keys())
                    for table_name, table in semantic_map["tables"].items()
                },
                "llm_selection_mode": "candidate_question_selection",
            },
            "rules_engine": {
                "mode": "deterministic_python",
                "supported_operations": capabilities["table_capabilities"],
                "status": "active_scaffold",
                "human_review_terms": [
                    "approve",
                    "certify",
                    "guarantee",
                    "sign off",
                    "safety critical",
                    "compliance decision",
                ],
            },
            "formatter_config": {
                "citation_style": "evidence_first",
                "include_executed_query": True,
                "include_rules_applied": True,
                "llm_summary_mode": "grounded_json_only",
            },
            "llm_runtime": {
                "provider": "anthropic",
                "enabled_env": "FORGE_BSMS_ENABLE_LLM",
                "api_key_env": "ANTHROPIC_API_KEY",
                "model_env": "FORGE_BSMS_MODEL",
                "default_model": "claude-sonnet-4-6",
            },
        }

    def _build_authority_pack(
        self,
        app_name: str,
        semantic_map: dict[str, Any],
        capabilities: dict[str, Any],
        question_map: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "manifest": {
                "pack_name": f"{app_name} Authority Pack",
                "status": "DRAFT",
                "generated_at": datetime.utcnow().isoformat() + "Z",
            },
            "bouncer": {
                "keywords": sorted(
                    {
                        keyword
                        for table in semantic_map["tables"].values()
                        for keyword in table["columns"].keys()
                    }
                )[:120],
                "intents": sorted({question["question_type"] for question in question_map["questions"]}),
                "rejection_templates": [
                    {
                        "status": "DRAFT",
                        "template": "The question is outside the supported database capabilities.",
                    }
                ],
            },
            "parser": {
                "field_mappings": {
                    table_name: table["columns"]
                    for table_name, table in semantic_map["tables"].items()
                },
                "query_templates": [
                    {
                        "intent": question["question_type"],
                        "table": question["table"],
                        "status": "DETERMINISTIC_ROUTE_REQUIRED",
                    }
                    for question in question_map["questions"]
                ],
                "examples": [
                    {
                        "status": "DRAFT",
                        "intent": question["question_type"],
                        "utterance": question["question"],
                    }
                    for question in question_map["questions"][:10]
                ],
            },
            "rules": {
                "categorical": {"status": "DRAFT", "rules": []},
                "threshold": {"status": "DRAFT", "rules": []},
                "relationship": {
                    "status": "DRAFT",
                    "rules": capabilities["table_capabilities"],
                },
            },
            "evidence": {
                "schema": {
                    "required_fields": [
                        "question",
                        "executed_query",
                        "rules_applied",
                        "evidence_sources",
                        "confidence",
                    ]
                }
            },
            "formatter": {
                "citation_style": {"status": "DRAFT", "mode": "evidence_first"},
                "vocabulary": sorted(
                    {
                        column_name
                        for table in semantic_map["tables"].values()
                        for column_name in table["columns"].keys()
                    }
                ),
                "response_templates": [
                    {"status": "DRAFT", "name": "default_answer"}
                ],
            },
            "gates": {
                "human_review": {
                    "status": "REQUIRED_HUMAN_AUTHORING",
                    "gate_a": "Safety/compliance decisions",
                    "gate_b": "Data mutations",
                    "gate_c": "Ambiguous analytical output",
                },
                "escalation": {
                    "status": "REQUIRED_HUMAN_AUTHORING",
                    "thresholds": {"warn_below": 0.6, "escalate_below": 0.4},
                },
            },
        }

    def _build_lineage_schema(self) -> dict[str, Any]:
        return {
            "generated_at": datetime.utcnow().isoformat() + "Z",
            "fields": [
                {"name": "question", "type": "string"},
                {"name": "bouncer_verdict", "type": "string"},
                {"name": "parsed_intent", "type": "object"},
                {"name": "executed_query", "type": "string"},
                {"name": "rules_applied", "type": "array"},
                {"name": "evidence_sources", "type": "array"},
                {"name": "confidence", "type": "number"},
                {"name": "timestamp", "type": "string"},
                {"name": "user", "type": "string"},
            ],
        }

    def _persist_artifacts(
        self,
        *,
        output_root: Path,
        artifacts: dict[str, Any],
    ) -> None:
        base_dir = output_root / "artifacts"
        base_dir.mkdir(parents=True, exist_ok=True)
        for filename, payload in artifacts.items():
            (base_dir / filename).write_text(
                json.dumps(payload, indent=2, sort_keys=True, default=self._json_safe),
                encoding="utf-8",
            )

    def _resolve_output_root(self, request: ForgeCompileRequest) -> Path:
        return Path(request.output_dir or f"./forge_output/{self._slugify(request.app_name)}")

    def _make_question(
        self,
        table_name: str,
        question_type: str,
        question: str,
        utility_score: float,
    ) -> dict[str, Any]:
        return {
            "id": self._question_id(table_name, question_type, question),
            "table": table_name,
            "question_type": question_type,
            "question": question,
            "utility_score": utility_score,
        }

    def _profile_column_values(
        self,
        sample_values: list[Any],
        data_type: str,
        row_count: int,
    ) -> dict[str, Any]:
        sample_size = len(sample_values)
        non_null_values = [value for value in sample_values if value is not None]
        distinct_values = {self._normalized_token(value) for value in non_null_values if self._normalized_token(value)}
        null_rate = 0.0 if sample_size == 0 else (sample_size - len(non_null_values)) / sample_size

        stats = {
            "sample_size": sample_size,
            "null_rate": round(null_rate, 4),
            "distinct_count": len(distinct_values),
            "distinct_ratio": round((len(distinct_values) / sample_size) if sample_size else 0.0, 4),
            "duplicate_sample_values": max(0, len(non_null_values) - len(distinct_values)),
            "estimated_row_count": row_count,
        }

        if self._is_numeric_type(data_type):
            numeric_values = [float(value) for value in non_null_values if self._is_number(value)]
            if numeric_values:
                sorted_values = sorted(numeric_values)
                q1 = self._quantile(sorted_values, 0.25)
                q3 = self._quantile(sorted_values, 0.75)
                iqr = q3 - q1
                lower = q1 - (1.5 * iqr)
                upper = q3 + (1.5 * iqr)
                outliers = [value for value in numeric_values if value < lower or value > upper]
                stats.update(
                    {
                        "min": min(numeric_values),
                        "max": max(numeric_values),
                        "mean": round(statistics.fmean(numeric_values), 4),
                        "outliers_detected": len(outliers),
                    }
                )
        else:
            units = {
                match
                for value in non_null_values
                for match in self._extract_inline_units(str(value))
            }
            stats["inconsistent_units"] = len(units) > 1

        return stats

    def _infer_semantic(
        self,
        *,
        qualified_table: str,
        column_name: str,
        data_type: str,
        sample_values: list[Any],
        is_primary_key: bool,
        is_foreign_key: bool,
    ) -> dict[str, Any]:
        lower_name = column_name.lower()
        units = self._infer_units(lower_name)
        family = "text"
        semantic_type = "free_text"
        confidence = 0.55
        property_name = None

        if is_primary_key:
            family = "identifier"
            semantic_type = "primary_key"
            confidence = 0.99
        elif is_foreign_key or lower_name.endswith("_id"):
            family = "identifier"
            semantic_type = "foreign_key"
            confidence = 0.94 if is_foreign_key else 0.84
        elif self._is_time_type(data_type) or any(tok in lower_name for tok in ("date", "time", "timestamp")):
            family = "temporal"
            semantic_type = "timestamp"
            confidence = 0.93
        elif any(self._looks_like_iso_datetime(value) for value in sample_values if value is not None):
            family = "temporal"
            semantic_type = "timestamp"
            confidence = 0.88
        elif "email" in lower_name or any("@" in str(value) for value in sample_values if value is not None):
            family = "contact"
            semantic_type = "email"
            confidence = 0.95
        elif "url" in lower_name or any(str(value).startswith(("http://", "https://")) for value in sample_values if value is not None):
            family = "contact"
            semantic_type = "url"
            confidence = 0.95
        elif any(token in lower_name for token in ("temp", "temperature")):
            family = "measurement"
            semantic_type = "temperature"
            property_name = "temperature"
            confidence = 0.93
        elif any(token in lower_name for token in ("pressure", "psi", "kpa", "bar")):
            family = "measurement"
            semantic_type = "pressure"
            property_name = "pressure"
            confidence = 0.93
        elif any(token in lower_name for token in ("strength", "hardness", "density", "elongation")):
            family = "measurement"
            semantic_type = "mechanical_property"
            property_name = lower_name
            confidence = 0.9
        elif self._is_numeric_type(data_type):
            family = "measurement"
            semantic_type = "numeric_measure"
            confidence = 0.78
        elif any(token in lower_name for token in ("status", "type", "category", "family")):
            family = "categorical"
            semantic_type = "categorical"
            confidence = 0.85
        elif "name" in lower_name:
            family = "reference"
            semantic_type = "name"
            confidence = 0.8
        elif "code" in lower_name or "number" in lower_name:
            family = "identifier"
            semantic_type = "business_code"
            confidence = 0.82
        elif self._is_text_type(data_type):
            family = "text"
            semantic_type = "text_search" if any(" " in str(value) for value in sample_values if value) else "short_text"
            confidence = 0.72

        return {
            "table": qualified_table,
            "column": column_name,
            "family": family,
            "semantic_type": semantic_type,
            "property": property_name,
            "units": units,
            "confidence": round(confidence, 3),
        }

    def _compatible_semantic_families(
        self,
        left: dict[str, Any],
        right: dict[str, Any],
    ) -> bool:
        if left["family"] == right["family"]:
            return True
        families = {left["family"], right["family"]}
        return families <= {"identifier", "reference"} or families <= {"measurement", "categorical"}

    def _mutual_information(self, left_values: list[str], right_values: list[str]) -> float:
        if not left_values or not right_values:
            return 0.0

        overlap = list((Counter(left_values) & Counter(right_values)).elements())
        if not overlap:
            return 0.0

        left_entropy = self._entropy(left_values)
        overlap_entropy = self._entropy(overlap)
        if left_entropy <= 0:
            return 0.0
        return min(1.0, max(0.0, overlap_entropy / left_entropy))

    def _entropy(self, values: Iterable[str]) -> float:
        counts = Counter(values)
        total = sum(counts.values())
        if total == 0:
            return 0.0
        entropy = 0.0
        for count in counts.values():
            probability = count / total
            entropy -= probability * math.log2(probability)
        return entropy

    def _extract_inline_units(self, text: str) -> list[str]:
        lowered = text.lower()
        units = []
        for unit in ("mpa", "psi", "kpa", "bar", "c", "f", "k", "%"):
            if unit in lowered:
                units.append(unit.upper())
        return units

    def _infer_units(self, lower_name: str) -> Optional[str]:
        if "mpa" in lower_name:
            return "MPa"
        if "psi" in lower_name:
            return "psi"
        if "kpa" in lower_name:
            return "kPa"
        if lower_name.endswith("_c") or "celsius" in lower_name:
            return "C"
        if lower_name.endswith("_f") or "fahrenheit" in lower_name:
            return "F"
        if lower_name.endswith("_k") or "kelvin" in lower_name:
            return "K"
        if lower_name.endswith("_pct") or lower_name.endswith("_percent") or "percentage" in lower_name:
            return "%"
        return None

    def _is_numeric_type(self, data_type: str) -> bool:
        return any(token in data_type for token in _NUMERIC_TYPES)

    def _is_text_type(self, data_type: str) -> bool:
        return any(token in data_type for token in _TEXT_TYPES)

    def _is_time_type(self, data_type: str) -> bool:
        return any(token in data_type for token in _TIME_TYPES)

    def _normalize_type(self, type_value: Any) -> str:
        normalized = str(type_value).lower()
        if "(" in normalized:
            normalized = normalized.split("(", 1)[0]
        return normalized.strip()

    def _json_safe(self, value: Any) -> Any:
        if isinstance(value, (datetime, date)):
            return value.isoformat()
        if isinstance(value, Decimal):
            return float(value)
        if isinstance(value, UUID):
            return str(value)
        if isinstance(value, Path):
            return str(value)
        if isinstance(value, set):
            return sorted(self._json_safe(item) for item in value)
        return value

    def _qualified_name(self, schema: Optional[str], table_name: str) -> str:
        if schema:
            return f"{schema}.{table_name}"
        return table_name

    def _slugify(self, value: str) -> str:
        return "".join(ch.lower() if ch.isalnum() else "-" for ch in value).strip("-")

    def _question_id(self, table_name: str, question_type: str, question: str) -> str:
        base = self._slugify(f"{table_name}-{question_type}-{question}")
        if len(base) <= 96:
            return base or "question"
        digest = hashlib.sha256(base.encode()).hexdigest()[:8]
        return f"{base[:87]}-{digest}"

    def _normalized_token(self, value: Any) -> str:
        text = str(value).strip().lower()
        return "".join(ch for ch in text if ch.isalnum())

    def _is_number(self, value: Any) -> bool:
        try:
            float(value)
            return True
        except (TypeError, ValueError):
            return False

    def _looks_like_iso_datetime(self, value: Any) -> bool:
        text = str(value).strip()
        if len(text) < 10 or text[4:5] != "-" or text[7:8] != "-":
            return False
        return "T" in text or ":" in text

    def _quantile(self, sorted_values: list[float], q: float) -> float:
        if not sorted_values:
            return 0.0
        position = (len(sorted_values) - 1) * q
        lower = math.floor(position)
        upper = math.ceil(position)
        if lower == upper:
            return sorted_values[int(position)]
        lower_value = sorted_values[lower]
        upper_value = sorted_values[upper]
        return lower_value + (upper_value - lower_value) * (position - lower)
