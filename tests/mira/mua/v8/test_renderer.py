#!/usr/bin/env python3
"""
Tests for MUA V8 Renderer.

Tests the template-only fallback path (no LLM required) and validates
that the output reads like a professional NASA MUA, not a db dump.

BoundState AI 2026
"""

import pytest

from mira.mua.v8.models import (
    MUAEnvironment,
    MUAEvidenceStrength,
    MUAGap,
    MUAPrecedent,
    MUARating,
    MUARenderedDocument,
    MUASessionData,
)
from mira.mua.v8.renderer import MUADocumentRenderer


def _build_sample_session() -> MUASessionData:
    """Build the same session data from the v7 output shown by the user."""
    return MUASessionData(
        mua_id="MUA-MIRA-2026-0001",
        session_id="e3abb10c-4f76-4cb2-936c-2efc30e97339",
        finalized_at="2026-02-09",
        material_name="Aluminum 6061-T6",
        maptis_code="MAT-A00601",
        material_class="metal",
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
            application="this is a equipment rack",
        ),
        ratings=[],  # No MAPTIS test data found
        gaps=[
            MUAGap(
                gap_id="gap-tox-bc50508d",
                dimension="toxicity",
                severity="critical",
                description="Habitable environment requires current toxicity (TOX) test data, which is absent or expired.",
                disposition="Accept With Rationale",
                rationale="test",
            ),
            MUAGap(
                gap_id="gap-test-flamm-7350c8a9",
                dimension="flammability",
                severity="high",
                description="No current FLAMM test data available. This test class is required for the queried environment.",
                disposition="Accept With Rationale",
                rationale="test",
            ),
            MUAGap(
                gap_id="gap-test-tox-13d49b7c",
                dimension="toxicity testing",
                severity="medium",
                description="No current TOX test data available. This test class is required for the queried environment.",
                disposition="Accept With Rationale",
                rationale="test",
            ),
        ],
        evidence_strength=MUAEvidenceStrength(
            band="INSUFFICIENT",
            score=0.0,
            components={
                "precedent_support": "0.000 (no supporting precedents)",
                "test_coverage": "0.000 (FLAMM: missing, TOX: missing)",
                "envelope_coverage": "0.000",
                "currency": "0.000",
                "consistency": "1.000 (no conflicts)",
            },
        ),
        banners=[
            "Novel material with limited precedent data.",
        ],
        precedents=[],  # No precedents for this test
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
        """The v7 output leaked Python enum names. V8 must not."""
        session = _build_sample_session()
        renderer = MUADocumentRenderer()
        doc = renderer.render_without_llm(session)
        text = doc.document_text

        # These are the enum class names that leaked in v7
        assert "MUACategory." not in text
        assert "EvidenceStrengthBand." not in text
        assert "Center." not in text
        assert "GapSeverity." not in text

    def test_no_internal_ids_exposed(self):
        """Gap IDs and session UUIDs should not appear in the document."""
        session = _build_sample_session()
        renderer = MUADocumentRenderer()
        doc = renderer.render_without_llm(session)
        text = doc.document_text

        assert "gap-tox-bc50508d" not in text
        assert "gap-test-flamm-7350c8a9" not in text
        assert "gap-test-tox-13d49b7c" not in text

    def test_no_raw_score_math(self):
        """Raw component breakdowns should not appear."""
        session = _build_sample_session()
        renderer = MUADocumentRenderer()
        doc = renderer.render_without_llm(session)
        text = doc.document_text

        assert "raw=" not in text
        assert "weight=" not in text
        assert "weighted=" not in text

    def test_has_professional_sections(self):
        """Document should have numbered prose sections."""
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
        """Gaps should be described by dimension/severity, not by internal ID."""
        session = _build_sample_session()
        renderer = MUADocumentRenderer()
        doc = renderer.render_without_llm(session)
        text = doc.document_text

        assert "toxicity" in text.lower()
        assert "flammability" in text.lower()

    def test_with_precedents(self):
        """Test that precedents are included in references."""
        session = _build_sample_session()
        session.precedents = [
            MUAPrecedent(
                mua_number="90-A-430",
                material_name="6061-T6 Aluminum",
                determination="APPROVED",
                rationale="Material has extensive heritage in ambient air habitable environments.",
            ),
        ]
        renderer = MUADocumentRenderer()
        doc = renderer.render_without_llm(session)
        text = doc.document_text

        assert "90-A-430" in text
        assert doc.precedents_used == 1


class TestMUASessionData:
    """Test data model construction."""

    def test_minimal_session(self):
        session = MUASessionData(
            mua_id="MUA-TEST-001",
            material_name="Steel",
            category="II",
        )
        assert session.mua_id == "MUA-TEST-001"
        assert session.environment.medium == "Air"  # default

    def test_full_session(self):
        session = _build_sample_session()
        assert len(session.gaps) == 3
        assert session.evidence_strength.band == "INSUFFICIENT"
        assert session.category == "II"


class TestMUAPrecedent:
    def test_precedent_model(self):
        p = MUAPrecedent(
            mua_number="MUA-2024-001",
            material_name="CRES 316L",
            determination="APPROVED",
            rationale="316L CRES has extensive heritage in GOX service.",
        )
        assert p.mua_number == "MUA-2024-001"


class TestOutputReadability:
    """
    The whole point of v8: the output should read like a real NASA document.
    These tests check for document quality, not just data correctness.
    """

    def test_no_ascii_box_borders(self):
        """Real MUAs don't use ======== borders."""
        session = _build_sample_session()
        renderer = MUADocumentRenderer()
        doc = renderer.render_without_llm(session)

        assert "========" not in doc.document_text

    def test_no_key_value_dumps(self):
        """Real MUAs use prose, not 'Key: Value' dumps."""
        session = _build_sample_session()
        renderer = MUADocumentRenderer()
        doc = renderer.render_without_llm(session)
        text = doc.document_text

        # The header section legitimately has labeled fields, but the body
        # sections should use prose. Check that body sections don't have
        # the v7-style raw key dumps.
        assert "Evidence Strength:" not in text.split("1. PURPOSE")[1] if "1. PURPOSE" in text else True
        assert "Routing basis:" not in text
        assert "Component breakdown:" not in text

    def test_no_debug_output(self):
        session = _build_sample_session()
        renderer = MUADocumentRenderer()
        doc = renderer.render_without_llm(session)
        text = doc.document_text

        assert "unknown:" not in text
        assert "Routing basis" not in text
        assert "x0.000" not in text
        assert "x0.533" not in text
