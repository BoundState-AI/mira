from __future__ import annotations

from unified.evidence.merger import EvidenceMerger
from unified.schema import AuthorityClass, EvidenceSourceType, ICEvidenceItem, ProvenanceRecord


def _item(
    evidence_id: str,
    source_type: EvidenceSourceType,
    value: str,
    authority_class: AuthorityClass,
    safety_critical: bool = False,
) -> ICEvidenceItem:
    return ICEvidenceItem(
        evidence_id=evidence_id,
        source_type=source_type,
        source_label=evidence_id,
        source_id=evidence_id,
        content=value,
        snippet=value,
        score=0.8,
        authority_class=authority_class,
        provenance=ProvenanceRecord(
            source_doc_id=evidence_id,
            extraction_method="manual",
            extraction_confidence=1.0,
            authority_class=authority_class,
        ),
        claim_key="strength",
        claim_value=value,
        metadata={"safety_critical": safety_critical},
    )


def test_evidence_merger_ranks_by_intent_scoped_authority() -> None:
    merger = EvidenceMerger()
    db_item = _item("db", EvidenceSourceType.DB, "43", AuthorityClass.PRIMARY_TEST_DATA)
    doc_item = _item("doc", EvidenceSourceType.DOC, "42", AuthorityClass.SPECIFICATION_REQUIREMENT)

    material_lookup = merger.merge([db_item], [doc_item], intent="material_lookup")
    compliance_check = merger.merge([db_item], [doc_item], intent="compliance_check")

    assert material_lookup.items[0].evidence_id == "db"
    assert compliance_check.items[0].evidence_id == "doc"


def test_safety_critical_conflicts_require_human_review() -> None:
    merger = EvidenceMerger()
    merged = merger.merge(
        db_items=[_item("db", EvidenceSourceType.DB, "43", AuthorityClass.PRIMARY_TEST_DATA, safety_critical=True)],
        doc_items=[_item("doc", EvidenceSourceType.DOC, "42", AuthorityClass.SPECIFICATION_REQUIREMENT, safety_critical=True)],
        intent="compatibility_check",
    )

    assert merged.conflicts
    assert merged.conflicts[0].requires_human_review is True
    assert merged.human_review_required is True
