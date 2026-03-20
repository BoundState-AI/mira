"""
Tests for MUA Final Renderer.

Tests the template-only fallback path (no LLM required) and validates
that the output reads like a professional NASA MUA document.

BoundState AI 2026
"""

import pytest

from mira.mua.final.models import (
    MUAConflict,
    MUAEnvironment,
    MUAEnvelopeResult,
    MUAEvidenceStrength,
    MUAGap,
    MUAPrecedent,
    MUARating,
    MUARenderedDocument,
    MUASessionData,
)
from mira.mua.final.renderer import MUADocumentRenderer


def _build_sample_session() -> MUASessionData:
    """Build a realistic session from v7 investigation output."""
    return MUASessionData(
        mua_id="MUA-MIRA-2026-0001",
        session_id="e3abb10c-4f76-4cb2-936c-2efc30e97339",
        finalized_at="2026-02-09",
        material_name="Aluminum 6061-T6",
        maptis_code="MAT-A00601",
        material_class="metal",
        material_family="aluminum",
        is_novel_material=False,
        is_process_sensitive=False,
        category="II",
        center="MSFC",
        applied_standard="NASA-STD-6016C",
        reviewer="Test",
        environment=MUAEnvironment(
            medium="Air",
            o2_percent=21.0,
            pressure_psia=14.7,
            temp_min_f=60.0,
            temp_max_f=85.0,
            location="habitable",
            application="equipment rack for ISS payload",
        ),
        ratings=[],
        gaps=[
            MUAGap(
                gap_id="gap-tox-bc50508d",
                dimension="toxicity",
                severity="critical",
                description="Habitable environment requires current TOX test data.",
                disposition="Accept With Rationale",
                rationale="Material has extensive ISS heritage per MUA 90-A-430.",
            ),
            MUAGap(
                gap_id="gap-flamm-7350c8a9",
                dimension="flammability",
                severity="high",
                description="No current FLAMM test data available.",
                disposition="Accept With Rationale",
                rationale="6061-T6 is a non-flammable metal per NASA-STD-6001.",
            ),
        ],
        evidence_strength=MUAEvidenceStrength(
            band="MODERATE",
            score=0.55,
            components={
                "precedent_support": "0.600",
                "test_coverage": "0.000",
                "envelope_coverage": "0.800",
            },
        ),
        banners=["Limited test data for this configuration."],
        precedents=[
            MUAPrecedent(
                mua_number="90-A-430",
                material_name="6061-T6 Aluminum",
                determination="APPROVED",
                rationale=(
                    "Material has extensive flight heritage in ambient air "
                    "habitable environments per numerous ISS rack assemblies."
                ),
                relevance_score=0.92,
                is_supporting=True,
            ),
        ],
    )


class TestMUADocumentRendererTemplate:
    """Test the template-only renderer (no LLM)."""

    def test_render_without_llm_returns_document(self):
        session = _build_sample_session()
        renderer = MUADocumentRenderer()
        doc = renderer.render_without_llm(session)

        assert isinstance(doc, MUARenderedDocument)
        assert doc.mua_id == "MUA-MIRA-2026-0001"
        assert doc.model_used == "template-only"
        assert len(doc.document_text) > 0

    def test_header_contains_nasa_formatting(self):
        session = _build_sample_session()
        renderer = MUADocumentRenderer()
        doc = renderer.render_without_llm(session)
        text = doc.document_text

        assert "NATIONAL AERONAUTICS AND SPACE ADMINISTRATION" in text
        assert "MATERIAL USAGE AGREEMENT" in text
        assert "MUA-MIRA-2026-0001" in text
        assert "NASA-STD-6016C" in text

    def test_header_contains_material_info(self):
        session = _build_sample_session()
        renderer = MUADocumentRenderer()
        doc = renderer.render_without_llm(session)
        text = doc.document_text

        assert "Aluminum 6061-T6" in text
        assert "MAT-A00601" in text
        assert "MSFC" in text
        assert "Category" in text

    def test_no_enum_names_leak_through(self):
        """V7 output leaked Python enum names.  Final must not."""
        session = _build_sample_session()
        renderer = MUADocumentRenderer()
        doc = renderer.render_without_llm(session)
        text = doc.document_text

        assert "MUACategory." not in text
        assert "EvidenceStrengthBand." not in text
        assert "Center." not in text
        assert "GapSeverity." not in text

    def test_no_internal_ids_exposed(self):
        session = _build_sample_session()
        renderer = MUADocumentRenderer()
        doc = renderer.render_without_llm(session)
        text = doc.document_text

        assert "gap-tox-bc50508d" not in text
        assert "gap-flamm-7350c8a9" not in text

    def test_no_raw_score_math(self):
        session = _build_sample_session()
        renderer = MUADocumentRenderer()
        doc = renderer.render_without_llm(session)
        text = doc.document_text

        assert "raw=" not in text
        assert "weight=" not in text
        assert "weighted=" not in text

    def test_has_professional_sections(self):
        session = _build_sample_session()
        renderer = MUADocumentRenderer()
        doc = renderer.render_without_llm(session)
        text = doc.document_text

        assert "1. PURPOSE AND SCOPE" in text
        assert "2. TEST DATA SUMMARY" in text
        assert "3. IDENTIFIED DEFICIENCIES" in text
        assert "4. ENGINEERING RATIONALE" in text
        assert "5. MITIGATIONS" in text
        assert "6. VERIFICATION" in text
        assert "7. REFERENCES" in text

    def test_has_approval_block(self):
        session = _build_sample_session()
        renderer = MUADocumentRenderer()
        doc = renderer.render_without_llm(session)
        text = doc.document_text

        assert "APPROVALS" in text
        assert "Prepared by:" in text
        assert "Reviewed by:" in text
        assert "Approved by:" in text

    def test_environment_info_present(self):
        session = _build_sample_session()
        renderer = MUADocumentRenderer()
        doc = renderer.render_without_llm(session)
        text = doc.document_text

        assert "21.0%" in text
        assert "14.7 psia" in text
        assert "habitable" in text
        assert "equipment rack" in text

    def test_gaps_described_without_ids(self):
        session = _build_sample_session()
        renderer = MUADocumentRenderer()
        doc = renderer.render_without_llm(session)
        text = doc.document_text

        assert "toxicity" in text.lower()
        assert "flammability" in text.lower()

    def test_with_precedents(self):
        session = _build_sample_session()
        renderer = MUADocumentRenderer()
        doc = renderer.render_without_llm(session)
        text = doc.document_text

        assert "90-A-430" in text
        assert doc.precedents_used == 1

    def test_no_ascii_box_borders(self):
        session = _build_sample_session()
        renderer = MUADocumentRenderer()
        doc = renderer.render_without_llm(session)

        assert "========" not in doc.document_text

    def test_no_key_value_dumps_in_body(self):
        session = _build_sample_session()
        renderer = MUADocumentRenderer()
        doc = renderer.render_without_llm(session)
        text = doc.document_text

        assert "Routing basis:" not in text
        assert "Component breakdown:" not in text

    def test_novel_material_flagged(self):
        session = _build_sample_session()
        session.is_novel_material = True
        session.precedents = []
        renderer = MUADocumentRenderer()
        doc = renderer.render_without_llm(session)
        text = doc.document_text

        assert "novel" in text.lower()

    def test_process_sensitive_flagged(self):
        session = _build_sample_session()
        session.is_process_sensitive = True
        session.process_params = {"cure_temp_f": 250, "cure_time_min": 60}
        renderer = MUADocumentRenderer()
        doc = renderer.render_without_llm(session)
        text = doc.document_text

        assert "process" in text.lower() or "cure" in text.lower()

    def test_conflicts_shown(self):
        session = _build_sample_session()
        session.conflicts = [
            MUAConflict(
                conflict_id="c-1",
                severity="hard",
                source_a="MUA-001",
                source_b="MAPTIS-TOX",
                description="Approved MUA contradicts expired test data.",
                recommendation="Review required.",
                disposition="Include Supporting",
                rationale="MUA is more recent.",
            ),
        ]
        renderer = MUADocumentRenderer()
        doc = renderer.render_without_llm(session)
        text = doc.document_text

        assert "MUA-001" in text
        assert "MAPTIS-TOX" in text

    def test_dependency_warnings_shown(self):
        session = _build_sample_session()
        session.dependency_warnings = [
            "MUA-90-A-430 depends on MUA-88-B-100: Referenced MUA is expired."
        ]
        renderer = MUADocumentRenderer()
        doc = renderer.render_without_llm(session)
        text = doc.document_text

        assert "MUA-90-A-430" in text
        assert "expired" in text.lower()


class TestMUASessionData:
    """Test data model construction."""

    def test_minimal_session(self):
        session = MUASessionData(
            mua_id="MUA-TEST-001",
            material_name="Steel",
            category="II",
        )
        assert session.mua_id == "MUA-TEST-001"
        assert session.environment.medium == "Air"

    def test_full_session(self):
        session = _build_sample_session()
        assert len(session.gaps) == 2
        assert session.evidence_strength.band == "MODERATE"
        assert session.category == "II"
