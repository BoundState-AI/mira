from __future__ import annotations

from unified.audit.merkle import compute_merkle_root
from unified.canonical_store import CanonicalStore
from unified.schema import ICChunk, ICDocument


def test_merkle_root_updates_with_inserts() -> None:
    store = CanonicalStore()
    store.insert_document(
        ICDocument(
            doc_id="doc-1",
            doc_hash="hash-1",
            source_path="/tmp/doc-1.pdf",
            source_type="pdf",
        )
    )
    store.insert_chunk(
        ICChunk(
            chunk_id="chunk-1",
            doc_id="doc-1",
            content_text="alpha",
            content_type="text",
            extraction_method="manual",
            extraction_confidence=1.0,
        )
    )

    verification = store.verify_audit_integrity()
    assert verification["valid"] is True
    assert verification["cached_root_hash"] == compute_merkle_root(
        [
            store.fetch("document", "doc-1").content_hash,
            store.fetch("chunk", "chunk-1").content_hash,
        ]
    )

