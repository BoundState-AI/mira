from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from unified.canonical_store import CanonicalStore
from unified.schema import ICChunk, ICDocument, ICEntity, ICMeasurement, ICProvenanceEdge


class AthenaExtractionBundle(BaseModel):
    document: ICDocument | dict[str, Any]
    chunks: list[ICChunk | dict[str, Any]] = Field(default_factory=list)
    entities: list[ICEntity | dict[str, Any]] = Field(default_factory=list)
    measurements: list[ICMeasurement | dict[str, Any]] = Field(default_factory=list)


class CanonicalStoreWriter:
    def __init__(self, store: CanonicalStore) -> None:
        self.store = store

    def write_bundle(self, bundle: AthenaExtractionBundle | dict[str, Any]) -> dict[str, int]:
        parsed = AthenaExtractionBundle.model_validate(bundle)
        document = self.store.insert_document(parsed.document)

        chunk_ids: set[str] = set()
        for chunk in parsed.chunks:
            inserted_chunk = self.store.insert_chunk(chunk)
            chunk_ids.add(inserted_chunk.chunk_id)
            self.store.insert_edge(
                ICProvenanceEdge(
                    edge_id=f"edge:{document.doc_id}:{inserted_chunk.chunk_id}",
                    source_id=inserted_chunk.chunk_id,
                    source_type="chunk",
                    target_id=document.doc_id,
                    target_type="document",
                    relationship="extracted_from",
                    confidence=1.0,
                    metadata={"bundle": document.doc_id},
                )
            )

        for entity in parsed.entities:
            inserted_entity = self.store.insert_entity(entity)
            if inserted_entity.chunk_id in chunk_ids:
                self.store.insert_edge(
                    ICProvenanceEdge(
                        edge_id=f"edge:{inserted_entity.entity_id}:{inserted_entity.chunk_id}",
                        source_id=inserted_entity.entity_id,
                        source_type="entity",
                        target_id=inserted_entity.chunk_id,
                        target_type="chunk",
                        relationship="extracted_from",
                        confidence=1.0,
                        metadata={"bundle": document.doc_id},
                    )
                )

        for measurement in parsed.measurements:
            inserted_measurement = self.store.insert_measurement(measurement)
            self.store.insert_edge(
                ICProvenanceEdge(
                    edge_id=f"edge:{inserted_measurement.measurement_id}:{inserted_measurement.chunk_id}",
                    source_id=inserted_measurement.measurement_id,
                    source_type="measurement",
                    target_id=inserted_measurement.chunk_id,
                    target_type="chunk",
                    relationship="extracted_from",
                    confidence=1.0,
                    metadata={"bundle": document.doc_id},
                )
            )

        return {
            "documents": 1,
            "chunks": len(parsed.chunks),
            "entities": len(parsed.entities),
            "measurements": len(parsed.measurements),
        }

