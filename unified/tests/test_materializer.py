from __future__ import annotations

import sqlite3
from pathlib import Path

from unified.canonical_store import CanonicalStore
from unified.materializer.materializer import RelationalMaterializer
from unified.materializer.store_writer import AthenaExtractionBundle, CanonicalStoreWriter
from unified.schema import AuthorityClass, ICChunk, ICDocument, ICEntity, ICMeasurement, ProvenanceRecord


def test_store_writer_and_materializer_flow(tmp_path: Path) -> None:
    store = CanonicalStore()
    writer = CanonicalStoreWriter(store)
    writer.write_bundle(
        AthenaExtractionBundle(
            document=ICDocument(
                doc_id="doc-1",
                doc_hash="hash-1",
                source_path="/tmp/doc-1.pdf",
                source_type="pdf",
            ),
            chunks=[
                ICChunk(
                    chunk_id="chunk-1",
                    doc_id="doc-1",
                    content_text="Titanium strength 42 MPa",
                    content_type="text",
                    extraction_method="manual",
                    extraction_confidence=1.0,
                )
            ],
            entities=[
                ICEntity(
                    entity_id="entity-1",
                    chunk_id="chunk-1",
                    entity_type="material",
                    value="Titanium",
                    confidence=1.0,
                )
            ],
            measurements=[
                ICMeasurement(
                    measurement_id="m-1",
                    chunk_id="chunk-1",
                    property_name="strength",
                    value=42.0,
                    unit="MPa",
                    provenance=ProvenanceRecord(
                        source_doc_id="doc-1",
                        source_chunk_id="chunk-1",
                        extraction_method="manual",
                        extraction_confidence=1.0,
                        authority_class=AuthorityClass.PRIMARY_TEST_DATA,
                    ),
                )
            ],
        )
    )

    edges = store.provenance_chain("chunk-1")
    assert edges

    target = tmp_path / "materialized.db"
    summary = RelationalMaterializer(store).materialize(f"sqlite:///{target}")

    connection = sqlite3.connect(target)
    counts = {
        table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        for table in ("documents", "chunks", "entities", "measurements")
    }
    connection.close()

    assert summary["documents"] == 1
    assert counts == {"documents": 1, "chunks": 1, "entities": 1, "measurements": 1}
