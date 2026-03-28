from __future__ import annotations

from unified.canonical_store import CanonicalStore
from unified.schema import AuthorityClass, ICChunk, ICDocument, ICMeasurement, ProvenanceRecord


def test_append_only_supersession_marks_old_record_and_keeps_lineage() -> None:
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
            content_text="42 MPa",
            content_type="text",
            extraction_method="manual",
            extraction_confidence=1.0,
        )
    )
    original = store.insert_measurement(
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
                extraction_confidence=0.9,
                authority_class=AuthorityClass.PRIMARY_TEST_DATA,
            ),
        )
    )
    revised = ICMeasurement(
        measurement_id="m-2",
        chunk_id="chunk-1",
        property_name="strength",
        value=43.0,
        unit="MPa",
        provenance=ProvenanceRecord(
            source_doc_id="doc-1",
            source_chunk_id="chunk-1",
            extraction_method="manual",
            extraction_confidence=0.95,
            authority_class=AuthorityClass.PRIMARY_TEST_DATA,
        ),
    )

    new_record, edge = store.supersede_record(
        "measurement",
        old_id=original.measurement_id,
        new_record=revised,
        edge_id="edge-1",
        metadata_payload={"reason": "lab recalibration"},
    )

    active_measurements = store.list_records("measurement")
    all_measurements = store.list_records("measurement", include_superseded=True)

    assert new_record.measurement_id == "m-2"
    assert edge.relationship == "supersedes"
    assert [measurement.measurement_id for measurement in active_measurements] == ["m-2"]
    assert sorted(measurement.measurement_id for measurement in all_measurements) == ["m-1", "m-2"]
