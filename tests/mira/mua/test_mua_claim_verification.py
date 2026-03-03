"""Tests for synthesis claim verification."""

from __future__ import annotations

from mira.mua.classifier.rationale import verify_claims
from mira.mua.evidence.models import EvidenceBundle
from mira.mua.precedent.models import PrecedentExemplar
from mira.mua.synthesis.models import Claim, SynthesisResult


def _bundle() -> EvidenceBundle:
    return EvidenceBundle(
        issue="FS",
        rating="U",
        mua_type="THIN_SCREENING",
        material_class="metal",
        media="GH2",
        precedent_summary=None,
        precedent_ring=None,
        exemplars=[
            PrecedentExemplar(
                mua_number="MUA-2021-1203",
                material_name="A286 CRES",
                alloy_family="fe_superalloy",
                media_category="hydrogen",
                determination="APPROVED",
                category="II",
                rationale_text="Long rationale text that is well beyond one hundred characters for testing claim verification behavior in unit tests.",
                confidence=0.9,
                match_ring="exact",
                match_score=1.1,
            )
        ],
        phrases=[],
        evidence_hash="abc123",
    )


def test_verify_claims_allows_template_and_valid_precedent() -> None:
    synthesis = SynthesisResult(
        rationale="Rationale",
        disposition="Disposition",
        claims=[
            Claim(text="Template claim", source_mua="TEMPLATE", source_type="template", confidence=1.0),
            Claim(text="Precedent claim", source_mua="MUA-2021-1203", source_type="precedent", confidence=0.8),
        ],
        model_id="test",
        prompt_version="v1",
    )

    verified, blocked = verify_claims(synthesis=synthesis, evidence=_bundle())

    assert len(verified) == 2
    assert blocked == []


def test_verify_claims_blocks_unknown_precedent_source() -> None:
    synthesis = SynthesisResult(
        rationale="Rationale",
        disposition="Disposition",
        claims=[
            Claim(text="Unknown precedent", source_mua="MUA-DOES-NOT-EXIST", source_type="precedent", confidence=0.5),
        ],
        model_id="test",
        prompt_version="v1",
    )

    verified, blocked = verify_claims(synthesis=synthesis, evidence=_bundle())

    assert verified == []
    assert len(blocked) == 1
