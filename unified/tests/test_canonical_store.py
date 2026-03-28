from __future__ import annotations

from unified.canonical_store import CanonicalStore
from unified.schema import AuthorityClass, ICChunk, ICDocument, ICMeasurement, ProvenanceRecord


def test_canonical_store_insert_and_fetch() -> None:
    store = CanonicalStore()
    document = store.insert_document(
        ICDocument(
            doc_id="doc-1",
            doc_hash="hash-1",
            source_path="/tmp/doc-1.pdf",
            source_type="pdf",
        )
    )
    chunk = store.insert_chunk(
        ICChunk(
            chunk_id="chunk-1",
            doc_id=document.doc_id,
            content_text="Tensile strength = 42 MPa",
            content_type="text",
            extraction_method="manual",
            extraction_confidence=1.0,
        )
    )
    store.insert_measurement(
        ICMeasurement(
            measurement_id="m-1",
            chunk_id=chunk.chunk_id,
            property_name="tensile_strength",
            value=42.0,
            unit="MPa",
            provenance=ProvenanceRecord(
                source_doc_id=document.doc_id,
                source_chunk_id=chunk.chunk_id,
                extraction_method="manual",
                extraction_confidence=1.0,
                authority_class=AuthorityClass.PRIMARY_TEST_DATA,
            ),
        )
    )

    fetched = store.fetch("document", "doc-1")
    audit = store.audit_status()

    assert fetched is not None
    assert fetched.doc_id == "doc-1"
    assert audit["record_count"] == 3
    assert audit["root_hash"]

