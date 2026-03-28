from __future__ import annotations

from typing import Any

from mira.forge_claude.introspector.manifest import ColumnInfo, SchemaManifest, SchemaStatistics, TableInfo

from unified.canonical_store import CanonicalStore


class SchemaBridge:
    def doc_features_to_manifest(
        self,
        document_features: list[Any],
        database_name: str = "ic_materialized_docs",
    ) -> SchemaManifest:
        tables: list[TableInfo] = [
            TableInfo(
                name="documents",
                row_count=len(document_features),
                columns=[
                    ColumnInfo(name="doc_id", type="text", primary_key=True, nullable=False),
                    ColumnInfo(name="doc_type", type="text"),
                    ColumnInfo(name="doc_hash", type="text"),
                ],
            )
        ]

        entity_count = 0
        measurement_count = 0
        for feature in document_features:
            entities = getattr(feature, "entities", None)
            if entities is not None:
                for collection_name in ("materials", "standards", "hazards", "systems", "processes"):
                    entity_count += len(getattr(entities, collection_name, []))
            flags = getattr(feature, "flags", None)
            if flags and getattr(flags, "has_measurements", False):
                measurement_count += 1

        if entity_count:
            tables.append(
                TableInfo(
                    name="entities",
                    row_count=entity_count,
                    columns=[
                        ColumnInfo(name="doc_id", type="text", nullable=False),
                        ColumnInfo(name="entity_type", type="text", nullable=False),
                        ColumnInfo(name="value", type="text", nullable=False),
                    ],
                )
            )

        if measurement_count:
            tables.append(
                TableInfo(
                    name="measurements",
                    row_count=measurement_count,
                    columns=[
                        ColumnInfo(name="doc_id", type="text", nullable=False),
                        ColumnInfo(name="property_name", type="text"),
                        ColumnInfo(name="value", type="float"),
                        ColumnInfo(name="unit", type="text"),
                    ],
                )
            )

        statistics = SchemaStatistics(
            total_tables=len(tables),
            total_rows=sum(table.row_count for table in tables),
            total_columns=sum(len(table.columns) for table in tables),
        )
        return SchemaManifest(
            database_type="materialized_docs",
            database_name=database_name,
            tables=tables,
            statistics=statistics,
        )

    def canonical_store_to_manifest(
        self,
        store: CanonicalStore,
        database_name: str = "ic_materialized_store",
    ) -> SchemaManifest:
        documents = store.list_records("document")
        chunks = store.list_records("chunk")
        entities = store.list_records("entity")
        measurements = store.list_records("measurement")
        tables = [
            TableInfo(
                name="documents",
                row_count=len(documents),
                columns=[
                    ColumnInfo(name="doc_id", type="text", primary_key=True, nullable=False),
                    ColumnInfo(name="doc_hash", type="text", nullable=False),
                    ColumnInfo(name="source_path", type="text", nullable=False),
                    ColumnInfo(name="source_type", type="text", nullable=False),
                ],
            ),
            TableInfo(
                name="chunks",
                row_count=len(chunks),
                columns=[
                    ColumnInfo(name="chunk_id", type="text", primary_key=True, nullable=False),
                    ColumnInfo(name="doc_id", type="text", nullable=False),
                    ColumnInfo(name="content_type", type="text", nullable=False),
                    ColumnInfo(name="content_text", type="text", nullable=False),
                ],
            ),
            TableInfo(
                name="entities",
                row_count=len(entities),
                columns=[
                    ColumnInfo(name="entity_id", type="text", primary_key=True, nullable=False),
                    ColumnInfo(name="chunk_id", type="text", nullable=False),
                    ColumnInfo(name="entity_type", type="text", nullable=False),
                    ColumnInfo(name="value", type="text", nullable=False),
                ],
            ),
            TableInfo(
                name="measurements",
                row_count=len(measurements),
                columns=[
                    ColumnInfo(name="measurement_id", type="text", primary_key=True, nullable=False),
                    ColumnInfo(name="chunk_id", type="text", nullable=False),
                    ColumnInfo(name="property_name", type="text", nullable=False),
                    ColumnInfo(name="value", type="float", nullable=False),
                    ColumnInfo(name="unit", type="text", nullable=False),
                ],
            ),
        ]
        statistics = SchemaStatistics(
            total_tables=len(tables),
            total_rows=sum(table.row_count for table in tables),
            total_columns=sum(len(table.columns) for table in tables),
        )
        return SchemaManifest(
            database_type="materialized_store",
            database_name=database_name,
            tables=tables,
            statistics=statistics,
        )

