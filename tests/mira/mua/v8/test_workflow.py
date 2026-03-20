#!/usr/bin/env python3
"""
Tests for MUA V8 Draft Builder and Workflow.

Tests the 80/20 workflow: AI builds draft, engineer reviews.

BoundState AI 2026
"""

import pytest

from mira.mua.v8.models import (
    MUAEnvironment,
    MUAEvidenceStrength,
    MUAGap,
    MUAPrecedent,
    MUASessionData,
)
from mira.mua.v8.draft_builder import MUADraftBuilder
from mira.mua.v8.workflow import (
    MUADraftSection,
    MUADraftWorkflow,
    PrecedentAttribution,
    ReviewAction,
    SectionStatus,
)


def _build_session_with_precedents() -> MUASessionData:
    """Build session data with precedent MUAs attached."""
    return MUASessionData(
        mua_id="MUA-MIRA-2026-0001",
        session_id="test-session",
        finalized_at="2026-02-09",
        material_name="Aluminum 6061-T6",
        maptis_code="MAT-A00601",
        material_class="metal",
        category="II",
        center="MSFC",
        applied_standard="NASA-STD-6016C",
        reviewer="J. Smith",
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
                gap_id="gap-tox-1",
                dimension="toxicity",
                severity="critical",
                description="Habitable environment requires current TOX test data.",
                disposition="Accept With Rationale",
                rationale="Material has extensive ISS heritage per MUA 90-A-430.",
            ),
            MUAGap(
                gap_id="gap-flamm-1",
                dimension="flammability",
                severity="high",
                description="No current FLAMM test data available.",
                disposition="Accept With Rationale",
                rationale="6061-T6 is a non-flammable metal per NASA-STD-6001.",
            ),
        ],
        evidence_strength=MUAEvidenceStrength(
            band="LIMITED",
            score=0.35,
        ),
        banners=["Novel material with limited precedent data."],
        precedents=[
            MUAPrecedent(
                mua_number="90-A-430",
                material_name="6061-T6 Aluminum",
                determination="APPROVED",
                rationale=(
                    "Material has extensive flight heritage in ambient air habitable "
                    "environments per numerous ISS rack assemblies. Toxicity and "
                    "flammability testing per NASA-STD-6001 Test 7 confirmed acceptable "
                    "offgassing products within SMAC limits for the crew cabin volume."
                ),
                relevance_score=0.92,
            ),
            MUAPrecedent(
                mua_number="WCE-2019-0042",
                material_name="6061-T651 Aluminum",
                determination="APPROVED",
                rationale=(
                    "6061-T651 aluminum alloy is acceptable for use in the habitable "
                    "environment based on extensive test history and heritage usage."
                ),
                relevance_score=0.85,
            ),
        ],
    )


class TestMUADraftBuilder:
    """Test the draft builder without DB (precedents pre-loaded)."""

    def test_build_draft_creates_7_sections(self):
        session = _build_session_with_precedents()
        builder = MUADraftBuilder(use_llm=False)
        workflow = builder.build_draft(session)

        assert len(workflow.sections) == 7
        assert workflow.sections[0].section_title == "PURPOSE AND SCOPE"
        assert workflow.sections[6].section_title == "REFERENCES AND TRACEABILITY"

    def test_rationale_section_needs_input(self):
        """The rationale section should be marked for engineer review."""
        session = _build_session_with_precedents()
        builder = MUADraftBuilder(use_llm=False)
        workflow = builder.build_draft(session)

        rationale = workflow.sections[3]  # Section 4
        assert rationale.section_title == "ENGINEERING RATIONALE"
        assert rationale.status == SectionStatus.NEEDS_INPUT

    def test_rationale_contains_precedent_text(self):
        """The rationale section should contain precedent MUA language."""
        session = _build_session_with_precedents()
        builder = MUADraftBuilder(use_llm=False)
        workflow = builder.build_draft(session)

        rationale = workflow.sections[3]
        assert "90-A-430" in rationale.content
        assert "heritage" in rationale.content.lower()

    def test_rationale_has_attributions(self):
        """Each section should track which precedents it used."""
        session = _build_session_with_precedents()
        builder = MUADraftBuilder(use_llm=False)
        workflow = builder.build_draft(session)

        rationale = workflow.sections[3]
        assert len(rationale.attributions) >= 1
        assert rationale.attributions[0].precedent_mua_number == "90-A-430"

    def test_references_list_precedents(self):
        session = _build_session_with_precedents()
        builder = MUADraftBuilder(use_llm=False)
        workflow = builder.build_draft(session)

        refs = workflow.sections[6]
        assert "90-A-430" in refs.content
        assert "WCE-2019-0042" in refs.content

    def test_no_internal_ids_in_any_section(self):
        session = _build_session_with_precedents()
        builder = MUADraftBuilder(use_llm=False)
        workflow = builder.build_draft(session)

        for section in workflow.sections:
            assert "gap-tox-1" not in section.content
            assert "gap-flamm-1" not in section.content


class TestMUADraftWorkflow:
    """Test the engineer review workflow."""

    def _build_workflow(self) -> MUADraftWorkflow:
        session = _build_session_with_precedents()
        builder = MUADraftBuilder(use_llm=False)
        return builder.build_draft(session)

    def test_review_progress(self):
        workflow = self._build_workflow()
        progress = workflow.review_progress

        assert progress["total_sections"] == 7
        assert progress["needs_engineer_input"] == 1  # Only rationale
        assert progress["remaining"] > 0

    def test_not_ready_to_finalize_initially(self):
        workflow = self._build_workflow()
        # Rationale section needs input, plus AI_DRAFTED sections need review
        assert not workflow.is_ready_to_finalize

    def test_accept_section(self):
        workflow = self._build_workflow()
        section = workflow.review_section(
            section_number=1,
            action=ReviewAction.ACCEPT,
            reviewer="J. Smith",
        )
        assert section.status == SectionStatus.ENGINEER_ACCEPTED
        assert section.reviewed_by == "J. Smith"

    def test_edit_section(self):
        workflow = self._build_workflow()
        new_content = "    4. ENGINEERING RATIONALE\n\n    My custom rationale here."
        section = workflow.review_section(
            section_number=4,
            action=ReviewAction.EDIT,
            content=new_content,
            reviewer="J. Smith",
        )
        assert section.status == SectionStatus.ENGINEER_MODIFIED
        assert section.final_content == new_content

    def test_override_section(self):
        workflow = self._build_workflow()
        override = "    Completely new content."
        section = workflow.review_section(
            section_number=4,
            action=ReviewAction.OVERRIDE,
            content=override,
            reviewer="J. Smith",
        )
        assert section.status == SectionStatus.ENGINEER_OVERRIDE
        assert section.final_content == override

    def test_flag_for_testing(self):
        workflow = self._build_workflow()
        section = workflow.review_section(
            section_number=3,
            action=ReviewAction.FLAG_FOR_TESTING,
            notes="Need updated FLAMM test",
            reviewer="J. Smith",
        )
        assert section.status == SectionStatus.ENGINEER_MODIFIED
        assert "FLAGGED FOR TESTING" in section.final_content

    def test_finalize_after_all_reviewed(self):
        workflow = self._build_workflow()

        # Accept all sections
        for section in workflow.sections:
            if section.status == SectionStatus.NEEDS_INPUT:
                workflow.review_section(
                    section.section_number,
                    ReviewAction.ACCEPT,
                    reviewer="J. Smith",
                )
            elif section.status == SectionStatus.AI_DRAFTED:
                workflow.review_section(
                    section.section_number,
                    ReviewAction.ACCEPT,
                    reviewer="J. Smith",
                )

        assert workflow.is_ready_to_finalize
        assert workflow.review_progress["percent_complete"] == 100

    def test_render_final_uses_engineer_edits(self):
        workflow = self._build_workflow()

        # Edit rationale section
        workflow.review_section(
            section_number=4,
            action=ReviewAction.EDIT,
            content="    4. ENGINEERING RATIONALE\n\n    Custom engineer rationale.",
            reviewer="J. Smith",
        )

        final = workflow.render_final()
        assert "Custom engineer rationale" in final
        # Original AI draft should NOT be in final
        assert ">>> ENGINEER:" not in final

    def test_render_final_preserves_ai_when_accepted(self):
        workflow = self._build_workflow()

        # Accept section 1 (AI-drafted purpose)
        workflow.review_section(1, ReviewAction.ACCEPT, reviewer="J. Smith")

        final = workflow.render_final()
        assert "PURPOSE AND SCOPE" in final


class TestPrecedentAttribution:
    """Test that provenance tracking works."""

    def test_attribution_created(self):
        attr = PrecedentAttribution(
            precedent_mua_number="90-A-430",
            precedent_material="6061-T6 Aluminum",
            relevance_score=0.92,
            rationale_excerpt="Material has extensive flight heritage...",
            used_for="rationale basis",
        )
        assert attr.precedent_mua_number == "90-A-430"
        assert attr.used_for == "rationale basis"
