from __future__ import annotations

import sqlite3
from pathlib import Path

from unified.discovery.unified_discovery import UnifiedDiscovery


def test_unified_discovery_combines_db_and_document_capabilities(tmp_path: Path) -> None:
    db_path = tmp_path / "discovery.db"
    connection = sqlite3.connect(db_path)
    connection.execute(
        "CREATE TABLE materials (id INTEGER PRIMARY KEY, name TEXT, property_name TEXT, value REAL)"
    )
    connection.execute(
        "INSERT INTO materials (name, property_name, value) VALUES ('Titanium', 'strength', 42.0)"
    )
    connection.commit()
    connection.close()

    discovery = UnifiedDiscovery()
    result = discovery.discover(
        db_url=f"sqlite:///{db_path}",
        documents=[
            {
                "doc_id": "doc-1",
                "content": "Titanium shall be tested per NASA-STD-6016 for strength.",
                "file_type": "pdf",
            }
        ],
    )

    assert result.db_result is not None
    assert result.document_features[0].doc_id == "doc-1"
    assert "materials" in result.capabilities.db_tables
    assert "hybrid" in result.capabilities.supported_sources
    assert "titanium" in result.capabilities.overlap_terms

