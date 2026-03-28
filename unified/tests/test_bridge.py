from __future__ import annotations

from unified.discovery.unified_discovery import UnifiedDiscovery
from unified.materializer.bridge import SchemaBridge


def test_bridge_creates_manifest_from_document_features() -> None:
    discovery = UnifiedDiscovery()
    features = discovery.discover_documents(
        [
            {
                "doc_id": "doc-1",
                "content": "Titanium shall be tested per NASA-STD-6016.",
                "file_type": "pdf",
            }
        ]
    )
    manifest = SchemaBridge().doc_features_to_manifest(features, database_name="bridge_test")

    assert manifest.database_name == "bridge_test"
    assert [table.name for table in manifest.tables][:2] == ["documents", "entities"]
    assert manifest.statistics.total_tables >= 2

