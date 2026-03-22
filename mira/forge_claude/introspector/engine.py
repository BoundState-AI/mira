"""SQLAlchemy connection and introspection engine.

v4.1 enhanced: produces SchemaManifest plus optional artifacts:
  - SemanticMap
  - RelationshipGraph
  - LatentRelationships
  - DataQualityReport

The basic introspect_database() function remains backwards-compatible.
The new introspect_database_full() returns all artifacts.
"""

from __future__ import annotations

import logging
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Callable

from sqlalchemy import create_engine, inspect

LOGGER = logging.getLogger(__name__)
from sqlalchemy.engine import Engine

from mira.forge_claude.config import DEFAULT_SAMPLE_COUNT, ENUM_LIKE_THRESHOLD
from mira.forge_claude.introspector.dialect_adapters import detect_dialect, normalize_type
from mira.forge_claude.introspector.manifest import (
    ColumnInfo,
    DataQualityReport,
    ForeignKey,
    LatentRelationships,
    Relationship,
    RelationshipGraph,
    SchemaManifest,
    SchemaStatistics,
    SemanticMap,
    TableInfo,
)
from mira.forge_claude.introspector.samplers import (
    count_rows,
    count_unique_values,
    is_text_type,
    profile_column,
    sample_column_values,
)


def _create_introspection_engine(db_url: str):
    kwargs = {}
    if db_url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
    else:
        kwargs.update({"pool_pre_ping": True, "pool_size": 5, "max_overflow": 10})
    return create_engine(db_url, **kwargs)


def _table_parts(table_ref: str | tuple[str | None, str]) -> tuple[str | None, str]:
    if isinstance(table_ref, tuple):
        return table_ref
    return None, table_ref


def _table_display_name(schema: str | None, table: str) -> str:
    return f"{schema}.{table}" if schema else table


def _get_database_type(url: str) -> str:
    """Extract database type from connection URL."""
    if url.startswith("sqlite"):
        return "sqlite"
    elif url.startswith("postgresql") or url.startswith("postgres"):
        return "postgresql"
    elif url.startswith("mysql"):
        return "mysql"
    return "unknown"


def _get_database_name(engine: Engine, url: str) -> str:
    """Extract database name from engine or URL."""
    if "sqlite" in url:
        # Extract filename without extension
        parts = url.split("/")
        if parts:
            name = parts[-1]
            if "." in name:
                name = name.rsplit(".", 1)[0]
            return name
    return engine.url.database or "unknown"


def _introspect_columns(
    insp,
    engine: Engine,
    table_name: str | tuple[str | None, str],
    row_count: int,
    sample_count: int,
    dialect: str = "sqlite",
    enable_profiling: bool = False,
) -> list[ColumnInfo]:
    """Introspect all columns in a table."""
    columns = []
    schema, raw_table_name = _table_parts(table_name)
    pk_cols = set(insp.get_pk_constraint(raw_table_name, schema=schema).get("constrained_columns", []))

    for col in insp.get_columns(raw_table_name, schema=schema):
        col_name = col["name"]
        raw_type = str(col["type"])
        col_type = normalize_type(raw_type, dialect)

        info = ColumnInfo(
            name=col_name,
            type=col_type,
            primary_key=col_name in pk_cols,
            nullable=col.get("nullable", True),
        )

        # Sample text/varchar columns
        if is_text_type(col_type) and row_count > 0:
            info.sample_values = sample_column_values(
                engine, table_name, col_name, sample_count
            )

        # Count unique values
        if row_count > 0:
            info.unique_count = count_unique_values(engine, table_name, col_name)

        # Column profiling (v4.1)
        if enable_profiling and row_count > 0:
            info.profile = profile_column(
                engine, table_name, col_name, col_type,
                row_count, info.unique_count or 0,
            )

        columns.append(info)

    return columns


def _introspect_foreign_keys(insp, table_name: str) -> list[ForeignKey]:
    """Introspect foreign keys for a table."""
    schema, raw_table_name = _table_parts(table_name)
    fks = []
    for fk in insp.get_foreign_keys(raw_table_name, schema=schema):
        if fk.get("constrained_columns") and fk.get("referred_columns"):
            referred_schema = fk.get("referred_schema")
            referred_table = fk["referred_table"]
            fks.append(
                ForeignKey(
                    column=fk["constrained_columns"][0],
                    references_table=_table_display_name(referred_schema, referred_table),
                    references_column=fk["referred_columns"][0],
                )
            )
    return fks


def _build_relationships(tables: list[TableInfo]) -> list[Relationship]:
    """Build relationship list from all foreign keys across tables."""
    relationships = []
    for table in tables:
        for fk in table.foreign_keys:
            relationships.append(
                Relationship(
                    type="many_to_one",
                    from_table=table.name,
                    from_column=fk.column,
                    to_table=fk.references_table,
                    to_column=fk.references_column,
                )
            )
    return relationships


def _build_manifest(
    engine: Engine,
    insp,
    db_url: str,
    sample_count: int,
    enable_profiling: bool = False,
    progress_callback: Callable[[str, float], None] | None = None,
) -> SchemaManifest:
    """Core manifest builder shared by both introspect functions."""
    db_type = _get_database_type(db_url)
    db_name = _get_database_name(engine, db_url)
    dialect = detect_dialect(db_url)

    tables = []
    total_rows = 0
    total_columns = 0

    # Discover tables across all non-system schemas
    system_schemas = {"information_schema", "pg_catalog", "pg_toast"}
    available_schemas = [s for s in insp.get_schema_names() if s not in system_schemas]
    if not available_schemas:
        available_schemas = [None]  # fallback: default schema
    LOGGER.info("Discovered schemas: %s", available_schemas)

    all_table_names: list[tuple[str | None, str]] = []
    for schema in available_schemas:
        for t in insp.get_table_names(schema=schema):
            # Store as (schema, table) — use schema-qualified name in SQL
            all_table_names.append((schema, t))

    # Skip backup/migration tables to avoid redundant introspection
    skip_suffixes = ("_backup_migration", "_backup_2")
    table_names = [(s, t) for s, t in all_table_names if not any(sfx in t for sfx in skip_suffixes)]
    if len(table_names) < len(all_table_names):
        LOGGER.info("Skipping %d backup tables, introspecting %d", len(all_table_names) - len(table_names), len(table_names))
    max_workers = max(1, min(len(table_names), int(os.environ.get("FORGE_INTROSPECTION_WORKERS", "6"))))

    def introspect_one(index: int, table_name: tuple[str | None, str]) -> tuple[int, int, int, TableInfo]:
        local_insp = inspect(engine)
        schema, raw_table_name = table_name
        display_name = _table_display_name(schema, raw_table_name)
        LOGGER.info("Introspecting table %d/%d: %s", index + 1, len(table_names), display_name)
        row_count = count_rows(engine, table_name)
        columns = _introspect_columns(
            local_insp,
            engine,
            table_name,
            row_count,
            sample_count,
            dialect=dialect,
            enable_profiling=enable_profiling,
        )
        foreign_keys = _introspect_foreign_keys(local_insp, table_name)
        indexes = [idx["name"] for idx in local_insp.get_indexes(raw_table_name, schema=schema) if idx.get("name")]
        table = TableInfo(
            name=display_name,
            row_count=row_count,
            columns=columns,
            foreign_keys=foreign_keys,
            indexes=indexes,
        )
        return index, row_count, len(columns), table

    if max_workers == 1:
        results = [introspect_one(index, table_name) for index, table_name in enumerate(table_names)]
        if progress_callback:
            progress_callback("Manifest built.", 60.0)
    else:
        results: list[tuple[int, int, int, TableInfo]] = []
        with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="forge-table") as executor:
            futures = {
                executor.submit(introspect_one, index, table_name): (index, table_name)
                for index, table_name in enumerate(table_names)
            }
            completed = 0
            total = max(len(futures), 1)
            for future in as_completed(futures):
                index, table_name = futures[future]
                results.append(future.result())
                completed += 1
                if progress_callback:
                    progress_callback(
                        f"Introspected table {completed}/{total}: {_table_display_name(table_name[0], table_name[1])}",
                        60.0 * (completed / total),
                    )

    results.sort(key=lambda item: item[0])
    for _, row_count, column_count, table in results:
        total_rows += row_count
        total_columns += column_count
        tables.append(table)

    relationships = _build_relationships(tables)

    return SchemaManifest(
        database_type=db_type,
        database_name=db_name,
        tables=tables,
        relationships=relationships,
        statistics=SchemaStatistics(
            total_tables=len(tables),
            total_rows=total_rows,
            total_columns=total_columns,
        ),
    )


def introspect_database(
    db_url: str,
    sample_count: int = DEFAULT_SAMPLE_COUNT,
) -> SchemaManifest:
    """Introspect a database and return a SchemaManifest.

    This is the backwards-compatible entry point. For the full v4.1
    artifact suite, use introspect_database_full().

    Args:
        db_url: SQLAlchemy connection string.
        sample_count: Number of sample values to collect per text column.

    Returns:
        A fully populated SchemaManifest.

    Raises:
        sqlalchemy.exc.OperationalError: If connection fails.
    """
    engine = _create_introspection_engine(db_url)
    insp = inspect(engine)

    manifest = _build_manifest(engine, insp, db_url, sample_count)

    engine.dispose()
    return manifest


@dataclass
class IntrospectionResult:
    """All artifacts produced by a full v4.1 introspection."""

    manifest: SchemaManifest
    semantic_map: SemanticMap
    relationship_graph: RelationshipGraph
    latent_relationships: LatentRelationships
    data_quality_report: DataQualityReport


def introspect_database_full(
    db_url: str,
    sample_count: int = DEFAULT_SAMPLE_COUNT,
    enable_profiling: bool = True,
    entropy_budget: int | None = None,
    progress_callback: Callable[[str, float], None] | None = None,
) -> IntrospectionResult:
    """Full v4.1 introspection: manifest + all analysis artifacts.

    Args:
        db_url: SQLAlchemy connection string.
        sample_count: Number of sample values to collect per text column.
        enable_profiling: Whether to compute column profiles (min/max/mean/etc).
        entropy_budget: Max column pairs for entropy discovery (None = no limit).

    Returns:
        IntrospectionResult with manifest, semantic_map, relationship_graph,
        latent_relationships, and data_quality_report.
    """
    from mira.forge_claude.introspector.entropy_discovery import discover_latent_relationships
    from mira.forge_claude.introspector.quality_inspector import inspect_quality
    from mira.forge_claude.introspector.relationship_discovery import build_relationship_graph
    from mira.forge_claude.introspector.semantic_inference import build_semantic_map

    engine = _create_introspection_engine(db_url)
    insp = inspect(engine)

    # Step 1a: Build manifest (with profiling)
    manifest = _build_manifest(
        engine, insp, db_url, sample_count,
        enable_profiling=enable_profiling,
        progress_callback=progress_callback,
    )

    # Step 1b: Semantic inference
    LOGGER.info("Step 1b: Semantic inference...")
    if progress_callback:
        progress_callback("Running semantic inference.", 66.0)
    semantic_map = build_semantic_map(manifest)

    # Step 1c: Three-mechanism relationship discovery
    LOGGER.info("Step 1c: Relationship discovery...")
    if progress_callback:
        progress_callback("Discovering relationships.", 74.0)
    relationship_graph = build_relationship_graph(
        manifest,
        engine,
        progress_callback=lambda message, progress: progress_callback(message, 66.0 + (progress * 0.18))
        if progress_callback
        else None,
    )

    # Step 1d: Entropy-based latent join discovery
    LOGGER.info("Step 1d: Entropy-based latent join discovery...")
    if progress_callback:
        progress_callback("Running entropy-based latent join discovery.", 84.0)
    latent_relationships = discover_latent_relationships(
        manifest, engine, semantic_map,
        budget_max_pairs=entropy_budget,
        progress_callback=lambda message, progress: progress_callback(message, 84.0 + (progress * 0.08))
        if progress_callback
        else None,
    )

    # Step 1e: Data quality inspection
    LOGGER.info("Step 1e: Data quality inspection...")
    if progress_callback:
        progress_callback("Inspecting data quality.", 92.0)
    data_quality_report = inspect_quality(
        manifest,
        engine,
        semantic_map,
        progress_callback=progress_callback,
    )
    LOGGER.info("Introspection pipeline complete.")
    if progress_callback:
        progress_callback("Introspection pipeline complete.", 100.0)

    engine.dispose()

    return IntrospectionResult(
        manifest=manifest,
        semantic_map=semantic_map,
        relationship_graph=relationship_graph,
        latent_relationships=latent_relationships,
        data_quality_report=data_quality_report,
    )
