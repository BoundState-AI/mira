from __future__ import annotations

from typing import Any

from sqlalchemy import Column, Float, MetaData, String, Table, create_engine, insert

from unified.canonical_store import CanonicalStore


class RelationalMaterializer:
    def __init__(self, store: CanonicalStore) -> None:
        self.store = store

    def materialize(self, target_db_url: str) -> dict[str, Any]:
        kwargs: dict[str, Any] = {}
        if target_db_url.startswith("sqlite"):
            kwargs["connect_args"] = {"check_same_thread": False}
        engine = create_engine(target_db_url, future=True, **kwargs)
        metadata = MetaData()

        documents = Table(
            "documents",
            metadata,
            Column("doc_id", String, primary_key=True),
            Column("doc_hash", String, nullable=False),
            Column("source_path", String, nullable=False),
            Column("source_type", String, nullable=False),
        )
        chunks = Table(
            "chunks",
            metadata,
            Column("chunk_id", String, primary_key=True),
            Column("doc_id", String, nullable=False),
            Column("content_type", String, nullable=False),
            Column("content_text", String, nullable=False),
        )
        entities = Table(
            "entities",
            metadata,
            Column("entity_id", String, primary_key=True),
            Column("chunk_id", String, nullable=False),
            Column("entity_type", String, nullable=False),
            Column("value", String, nullable=False),
        )
        measurements = Table(
            "measurements",
            metadata,
            Column("measurement_id", String, primary_key=True),
            Column("chunk_id", String, nullable=False),
            Column("property_name", String, nullable=False),
            Column("value", Float, nullable=False),
            Column("unit", String, nullable=False),
        )
        metadata.create_all(engine)

        doc_rows = [
            {
                "doc_id": document.doc_id,
                "doc_hash": document.doc_hash,
                "source_path": document.source_path,
                "source_type": document.source_type,
            }
            for document in self.store.list_records("document")
        ]
        chunk_rows = [
            {
                "chunk_id": chunk.chunk_id,
                "doc_id": chunk.doc_id,
                "content_type": chunk.content_type,
                "content_text": chunk.content_text,
            }
            for chunk in self.store.list_records("chunk")
        ]
        entity_rows = [
            {
                "entity_id": entity.entity_id,
                "chunk_id": entity.chunk_id,
                "entity_type": entity.entity_type,
                "value": entity.value,
            }
            for entity in self.store.list_records("entity")
        ]
        measurement_rows = [
            {
                "measurement_id": measurement.measurement_id,
                "chunk_id": measurement.chunk_id,
                "property_name": measurement.property_name,
                "value": measurement.value,
                "unit": measurement.unit,
            }
            for measurement in self.store.list_records("measurement")
        ]

        with engine.begin() as connection:
            if doc_rows:
                connection.execute(insert(documents), doc_rows)
            if chunk_rows:
                connection.execute(insert(chunks), chunk_rows)
            if entity_rows:
                connection.execute(insert(entities), entity_rows)
            if measurement_rows:
                connection.execute(insert(measurements), measurement_rows)

        return {
            "db_url": target_db_url,
            "documents": len(doc_rows),
            "chunks": len(chunk_rows),
            "entities": len(entity_rows),
            "measurements": len(measurement_rows),
        }

