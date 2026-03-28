from __future__ import annotations

from unified.audit.integrity import AuditIntegrityService
from unified.canonical_store import CanonicalStore
from unified.schema import ICDocument


def test_audit_integrity_service_verifies_and_signs_manifest() -> None:
    store = CanonicalStore()
    store.insert_document(
        ICDocument(
            doc_id="doc-1",
            doc_hash="hash-1",
            source_path="/tmp/doc-1.pdf",
            source_type="pdf",
        )
    )
    service = AuditIntegrityService(signer=lambda payload: f"signed:{len(payload)}")
    report = service.verify(store, version="1.2.3", domain_pack_hash="abc")

    assert report["valid"] is True
    assert report["manifest"]["ic_version"] == "1.2.3"
    assert report["signature"].startswith("signed:")

