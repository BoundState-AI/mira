from __future__ import annotations

from unified.canonical_store import CanonicalStore
from unified.evidence.doc_provider import DocumentEvidenceProvider
from unified.pipeline.pipeline import UnifiedPipeline
from unified.schema import ICChunk, ICDocument, QueryRequest, QuerySource


def test_synthesis_is_cached_but_not_persisted_to_canonical_store() -> None:
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
            content_text="Titanium shall have strength of 42 MPa.",
            content_type="text",
            extraction_method="manual",
            extraction_confidence=1.0,
        )
    )

    pipeline = UnifiedPipeline(doc_provider=DocumentEvidenceProvider(store=store))
    before = store.audit_status()["record_count"]

    first = pipeline.query(QueryRequest(query="Titanium strength", source=QuerySource.DOCS))
    second = pipeline.query(QueryRequest(query="Titanium strength", source=QuerySource.DOCS))
    after = store.audit_status()["record_count"]

    assert first.insufficient_evidence is False
    assert second.audit["cache_hit"] is True
    assert before == after

