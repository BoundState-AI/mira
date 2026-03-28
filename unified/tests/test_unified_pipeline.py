from __future__ import annotations

import sqlite3
from pathlib import Path

from unified.canonical_store import CanonicalStore
from unified.evidence.db_provider import DBEvidenceProvider
from unified.evidence.doc_provider import DocumentEvidenceProvider
from unified.pipeline.pipeline import UnifiedPipeline
from unified.schema import AUTHORITY_BOUNDARY_TEXT, ICChunk, ICDocument, QueryRequest, QuerySource


def test_unified_pipeline_runs_hybrid_query(tmp_path: Path) -> None:
    db_path = tmp_path / "pipeline.db"
    connection = sqlite3.connect(db_path)
    connection.execute(
        "CREATE TABLE test_data (id INTEGER PRIMARY KEY, name TEXT, property_name TEXT, value REAL, authority_class TEXT)"
    )
    connection.execute(
        "INSERT INTO test_data (name, property_name, value, authority_class) VALUES ('Titanium', 'strength', 43.0, 'primary_test_data')"
    )
    connection.commit()
    connection.close()

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

    pipeline = UnifiedPipeline(
        db_provider=DBEvidenceProvider(f"sqlite:///{db_path}"),
        doc_provider=DocumentEvidenceProvider(store=store),
    )
    result = pipeline.query(QueryRequest(query="Titanium strength", source=QuerySource.HYBRID))

    assert result.route.value == "cross_source"
    assert {citation.source_type.value for citation in result.citations} == {"db", "doc"}
    assert result.authority_boundary == AUTHORITY_BOUNDARY_TEXT
    assert "db, doc" in result.answer
