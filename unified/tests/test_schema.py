from __future__ import annotations

from unified.schema import AuthorityClass, ICChunk, ICMeasurement, ProvenanceRecord


def test_content_hash_ignores_superseded_flag() -> None:
    chunk = ICChunk(
        chunk_id="chunk-1",
        doc_id="doc-1",
        content_text="A material requirement.",
        content_type="text",
        extraction_method="manual",
        extraction_confidence=0.95,
    )
    original_hash = chunk.content_hash
    superseded = ICChunk.model_validate(
        {**chunk.model_dump(mode="python"), "is_superseded": True, "content_hash": ""}
    )
    assert superseded.content_hash == original_hash


def test_measurement_provenance_is_required() -> None:
    provenance = ProvenanceRecord(
        source_doc_id="doc-1",
        extraction_method="manual",
        extraction_confidence=0.9,
        authority_class=AuthorityClass.PRIMARY_TEST_DATA,
    )
    measurement = ICMeasurement(
        measurement_id="m-1",
        chunk_id="chunk-1",
        property_name="tensile_strength",
        value=42.0,
        unit="MPa",
        provenance=provenance,
    )
    assert measurement.provenance.source_doc_id == "doc-1"
