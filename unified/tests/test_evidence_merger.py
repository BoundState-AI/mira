from __future__ import annotations

import sqlite3
from pathlib import Path

from unified.canonical_store import CanonicalStore
from unified.evidence.db_provider import DBEvidenceProvider
from unified.evidence.doc_provider import DocumentEvidenceProvider
from unified.evidence.merger import EvidenceMerger
from unified.schema import ICChunk, ICDocument


def test_db_and_doc_providers_return_rankable_evidence(tmp_path: Path) -> None:
    db_path = tmp_path / "evidence.db"
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

    db_provider = DBEvidenceProvider(f"sqlite:///{db_path}")
    doc_provider = DocumentEvidenceProvider(store=store)

    db_items = db_provider.get_evidence("Titanium strength", intent="material_lookup")
    doc_items = doc_provider.get_evidence("Titanium strength", intent="material_lookup")
    merged = EvidenceMerger().merge(db_items=db_items, doc_items=doc_items, intent="material_lookup")

    assert db_items
    assert doc_items
    assert merged.items[0].source_type.value == "db"
    assert merged.source_counts == {"db": 1, "doc": 1}

