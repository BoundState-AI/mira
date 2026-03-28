from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from pydantic import BaseModel
from sqlalchemy import JSON, Boolean, Column, DateTime, Float, MetaData, String, Table, create_engine, select
from sqlalchemy.engine import Engine
from sqlalchemy.pool import StaticPool

from unified.audit.merkle import MerkleAuditManager, register_merkle_tables
from unified.schema import ICChunk, ICDocument, ICEntity, ICMeasurement, ICProvenanceEdge


metadata = MetaData()

ic_documents = Table(
    "ic_documents",
    metadata,
    Column("doc_id", String(255), primary_key=True),
    Column("doc_hash", String(255), nullable=False),
    Column("source_path", String(2048), nullable=False),
    Column("source_type", String(32), nullable=False),
    Column("ingested_at", DateTime, nullable=False),
    Column("features", JSON, nullable=True),
    Column("content_hash", String(64), nullable=False),
    Column("is_superseded", Boolean, nullable=False, default=False),
)

ic_chunks = Table(
    "ic_chunks",
    metadata,
    Column("chunk_id", String(255), primary_key=True),
    Column("doc_id", String(255), nullable=False),
    Column("page", String(64), nullable=True),
    Column("location", String(512), nullable=True),
    Column("content_text", String, nullable=False),
    Column("content_type", String(64), nullable=False),
    Column("extraction_method", String(64), nullable=False),
    Column("extraction_confidence", Float, nullable=False),
    Column("extraction_model", String(255), nullable=True),
    Column("content_hash", String(64), nullable=False),
    Column("is_superseded", Boolean, nullable=False, default=False),
)

ic_entities = Table(
    "ic_entities",
    metadata,
    Column("entity_id", String(255), primary_key=True),
    Column("chunk_id", String(255), nullable=False),
    Column("entity_type", String(64), nullable=False),
    Column("value", String, nullable=False),
    Column("normalized_value", String, nullable=True),
    Column("confidence", Float, nullable=False),
    Column("content_hash", String(64), nullable=False),
    Column("is_superseded", Boolean, nullable=False, default=False),
)

ic_measurements = Table(
    "ic_measurements",
    metadata,
    Column("measurement_id", String(255), primary_key=True),
    Column("chunk_id", String(255), nullable=False),
    Column("assertion_id", String(255), nullable=True),
    Column("property_name", String(255), nullable=False),
    Column("value", Float, nullable=False),
    Column("unit", String(64), nullable=False),
    Column("normalized_value", Float, nullable=True),
    Column("normalized_unit", String(64), nullable=True),
    Column("test_conditions", JSON, nullable=False, default=dict),
    Column("provenance", JSON, nullable=False),
    Column("content_hash", String(64), nullable=False),
    Column("is_superseded", Boolean, nullable=False, default=False),
)

ic_provenance_edges = Table(
    "ic_provenance_edges",
    metadata,
    Column("edge_id", String(255), primary_key=True),
    Column("source_id", String(255), nullable=False),
    Column("source_type", String(64), nullable=False),
    Column("target_id", String(255), nullable=False),
    Column("target_type", String(64), nullable=False),
    Column("relationship", String(64), nullable=False),
    Column("confidence", Float, nullable=False),
    Column("metadata", JSON, nullable=False, default=dict),
    Column("content_hash", String(64), nullable=False),
    Column("is_superseded", Boolean, nullable=False, default=False),
)

ic_merkle_nodes, ic_merkle_meta = register_merkle_tables(metadata)


MODEL_TABLE_MAP = {
    ICDocument: (ic_documents, "doc_id"),
    ICChunk: (ic_chunks, "chunk_id"),
    ICEntity: (ic_entities, "entity_id"),
    ICMeasurement: (ic_measurements, "measurement_id"),
    ICProvenanceEdge: (ic_provenance_edges, "edge_id"),
}

TABLE_NAME_MAP = {
    "document": (ICDocument, ic_documents, "doc_id"),
    "chunk": (ICChunk, ic_chunks, "chunk_id"),
    "entity": (ICEntity, ic_entities, "entity_id"),
    "measurement": (ICMeasurement, ic_measurements, "measurement_id"),
    "assertion": (None, None, None),
    "edge": (ICProvenanceEdge, ic_provenance_edges, "edge_id"),
}


class CanonicalStore:
    def __init__(self, db_url: str = "sqlite+pysqlite:///:memory:") -> None:
        kwargs: dict[str, Any] = {}
        if db_url.startswith("sqlite"):
            kwargs["connect_args"] = {"check_same_thread": False}
            if ":memory:" in db_url:
                kwargs["poolclass"] = StaticPool
        self.engine: Engine = create_engine(db_url, future=True, **kwargs)
        self.merkle = MerkleAuditManager(ic_merkle_nodes, ic_merkle_meta)
        self.create_schema()

    def create_schema(self) -> None:
        metadata.create_all(self.engine)

    def insert_document(self, document: ICDocument | dict[str, Any]) -> ICDocument:
        return self._insert(ICDocument.model_validate(document))

    def insert_chunk(self, chunk: ICChunk | dict[str, Any]) -> ICChunk:
        return self._insert(ICChunk.model_validate(chunk))

    def insert_entity(self, entity: ICEntity | dict[str, Any]) -> ICEntity:
        return self._insert(ICEntity.model_validate(entity))

    def insert_measurement(self, measurement: ICMeasurement | dict[str, Any]) -> ICMeasurement:
        return self._insert(ICMeasurement.model_validate(measurement))

    def insert_edge(self, edge: ICProvenanceEdge | dict[str, Any]) -> ICProvenanceEdge:
        return self._insert(ICProvenanceEdge.model_validate(edge))

    def _insert(self, record):
        table, primary_key = MODEL_TABLE_MAP[type(record)]
        row = self._prepare_row(record)
        with self.engine.begin() as connection:
            connection.execute(table.insert().values(**row))
            self.merkle.append_leaf(
                connection=connection,
                record_hash=record.content_hash,
                record_id=str(row[primary_key]),
                record_type=table.name,
            )
        return record

    def fetch(self, record_type: str, record_id: str):
        model_cls, table, primary_key = TABLE_NAME_MAP[record_type]
        if table is None or primary_key is None or model_cls is None:
            raise ValueError(f"Unsupported record type: {record_type}")
        with self.engine.begin() as connection:
            row = connection.execute(
                select(table).where(getattr(table.c, primary_key) == record_id)
            ).mappings().first()
        return model_cls.model_validate(dict(row)) if row else None

    def list_records(self, record_type: str, include_superseded: bool = False) -> list[Any]:
        model_cls, table, _ = TABLE_NAME_MAP[record_type]
        if table is None or model_cls is None:
            return []
        stmt = select(table)
        if not include_superseded:
            stmt = stmt.where(table.c.is_superseded.is_(False))
        with self.engine.begin() as connection:
            rows = connection.execute(stmt).mappings().all()
        return [model_cls.model_validate(dict(row)) for row in rows]

    def supersede_record(
        self,
        record_type: str,
        old_id: str,
        new_record,
        edge_id: str,
        confidence: float = 1.0,
        metadata_payload: dict[str, Any] | None = None,
    ):
        existing = self.fetch(record_type, old_id)
        if existing is None:
            raise KeyError(f"Record not found: {record_type}:{old_id}")

        model_cls, table, primary_key = TABLE_NAME_MAP[record_type]
        if table is None or primary_key is None:
            raise ValueError(f"Unsupported record type: {record_type}")

        inserted = self._insert(new_record)
        new_id = getattr(inserted, primary_key)
        edge = ICProvenanceEdge(
            edge_id=edge_id,
            source_id=str(new_id),
            source_type=record_type,
            target_id=old_id,
            target_type=record_type,
            relationship="supersedes",
            confidence=confidence,
            metadata=metadata_payload or {},
        )

        with self.engine.begin() as connection:
            connection.execute(
                table.update()
                .where(getattr(table.c, primary_key) == old_id)
                .values(is_superseded=True)
            )
            connection.execute(ic_provenance_edges.insert().values(**self._prepare_row(edge)))
            self.merkle.append_leaf(
                connection=connection,
                record_hash=edge.content_hash,
                record_id=edge.edge_id,
                record_type=ic_provenance_edges.name,
            )
        return inserted, edge

    def provenance_chain(self, record_id: str) -> list[ICProvenanceEdge]:
        with self.engine.begin() as connection:
            rows = connection.execute(
                select(ic_provenance_edges).where(
                    (ic_provenance_edges.c.source_id == record_id)
                    | (ic_provenance_edges.c.target_id == record_id)
                )
            ).mappings().all()
        return [ICProvenanceEdge.model_validate(dict(row)) for row in rows]

    def audit_status(self) -> dict[str, Any]:
        with self.engine.begin() as connection:
            return self.merkle.cached_root(connection)

    def verify_audit_integrity(self) -> dict[str, Any]:
        with self.engine.begin() as connection:
            return self.merkle.verify(connection)

    @staticmethod
    def _json_ready(value: Any) -> Any:
        if isinstance(value, BaseModel):
            return value.model_dump(mode="json")
        if isinstance(value, dict) or isinstance(value, list):
            return json.loads(json.dumps(value, default=str))
        return value

    def _prepare_row(self, record) -> dict[str, Any]:
        row = record.model_dump(mode="python")
        for key in ("features", "provenance", "test_conditions", "metadata"):
            if key in row and row[key] is not None:
                row[key] = self._json_ready(row[key])
        return row
