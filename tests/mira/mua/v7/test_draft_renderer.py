"""Tests for MUA v7 draft renderer.

The draft renderer produces a structured MUA document with exactly
seven sections.  It must:

  1. Produce valid output even without an LLM (template fallback).
  2. Include the engineer's gap rationale verbatim (quoted) in the
     rationale section.
  3. Reflect conflict disposition decisions.
  4. Include process constraints for adhesive / coating materials.
  5. Follow the MUA-MIRA-YYYY-NNNN identifier format.
  6. NEVER use the phrase "is approved" or "approved for use" because
     the MUA is a *recommendation*, not an approval.  Final approval
     authority rests with the designated MEIT / EMES representative.
"""

import re

import pytest

from mira.mua.v7.draft_renderer import DraftRenderer
from mira.mua.v7.models import (
    CategoryRoutingResult,
    ConflictDecision,
    ConflictFound,
    ConflictSeverity,
    DeterminationStatus,
    DraftSection,
    EnvironmentSpec,
    EvidenceStrengthBand,
    EvidenceStrengthResult,
    GapDecision,
    GapDecisionType,
    GapIdentified,
    InvestigationResult,
    MaterialClass,
    MaterialResolution,
    MUACategory,
    MUADraft,
    PrecedentDecision,
    PrecedentMatch,
    ProcessParams,
    ResolutionStatus,
    ReviewDecisions,
    ReviewDecisionType,
    TestDataRecord,
)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MUA_ID_PATTERN = re.compile(r"^MUA-MIRA-\d{4}-\d{4}$")

EXPECTED_SECTION_TITLES = [
    "Header",
    "Ratings",
    "Gap Profile",
    "Rationale",
    "Mitigations / Controls",
    "Verification Requirements",
    "Traceability & Citations",
]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def renderer():
    return DraftRenderer()


@pytest.fixture
def base_material():
    """Resolved aluminum material (non-process-sensitive)."""
    return MaterialResolution(
        input_text="6061-T6",
        status=ResolutionStatus.RESOLVED,
        material_code="MAT-A96061",
        resolved_name="6061-T6 Aluminum",
        family="aluminum",
    )


@pytest.fixture
def adhesive_material():
    """Resolved adhesive material (process-sensitive)."""
    return MaterialResolution(
        input_text="EA 9394",
        status=ResolutionStatus.RESOLVED,
        material_code="MAT-EA9394",
        resolved_name="EA 9394 Adhesive",
        material_class=MaterialClass.ADHESIVE,
        family="adhesive",
        is_process_sensitive=True,
    )


@pytest.fixture
def base_env():
    """Standard non-habitable air environment."""
    return EnvironmentSpec(
        o2_percent=20.9,
        pressure_psia=14.7,
        temp_min_f=60.0,
        temp_max_f=120.0,
        medium="AIR",
        location="non_habitable",
        application="General structural component",
    )


@pytest.fixture
def base_test_data():
    """Standard A-rated test data set."""
    return [
        TestDataRecord(test_class="FLAMM", rating="A", is_current=True),
        TestDataRecord(test_class="ODOR", rating="A", is_current=True),
        TestDataRecord(test_class="OFFGAS", rating="A", is_current=True),
    ]


@pytest.fixture
def base_precedents():
    """Two supporting precedents for basic tests."""
    return [
        PrecedentMatch(
            mua_number="MUA-MSFC-2023-0101",
            material_designation="6061-T6 Aluminum",
            determination=DeterminationStatus.APPROVED,
            environment_description="Air, 14.7 psia, 60-120 F",
            relevance_score=0.85,
            is_supporting=True,
        ),
        PrecedentMatch(
            mua_number="MUA-MSFC-2022-0055",
            material_designation="6061-T651 Aluminum",
            determination=DeterminationStatus.APPROVED,
            environment_description="Air, 14.7 psia, 40-160 F",
            relevance_score=0.72,
            is_supporting=True,
        ),
    ]


@pytest.fixture
def basic_investigation(base_material, base_env, base_test_data, base_precedents):
    """Minimal investigation result for a straightforward aluminum MUA."""
    return InvestigationResult(
        material=base_material,
        environment=base_env,
        test_data=base_test_data,
        supporting_precedents=base_precedents,
        evidence_strength=EvidenceStrengthResult(
            score=0.78,
            band=EvidenceStrengthBand.MODERATE,
        ),
    )


@pytest.fixture
def basic_review_decisions(base_precedents):
    """Review decisions that include both precedents as supporting."""
    return ReviewDecisions(
        precedent_decisions=[
            PrecedentDecision(
                mua_number="MUA-MSFC-2023-0101",
                decision=ReviewDecisionType.INCLUDE_SUPPORTING,
            ),
            PrecedentDecision(
                mua_number="MUA-MSFC-2022-0055",
                decision=ReviewDecisionType.INCLUDE_SUPPORTING,
            ),
        ],
        all_items_reviewed=True,
    )


@pytest.fixture
def basic_routing():
    """Category III routing result."""
    return CategoryRoutingResult(
        category=MUACategory.III,
        routing_basis=[
            {
                "rule_id": "CAT3-001",
                "rule_description": "Location is non-habitable (Cat III eligible)",
                "citation": "NASA-STD-6016C SS4.3.3 criterion (a)",
                "triggered_by": "location=non_habitable",
            }
        ],
        authority_pack="NASA-STD-6016C",
    )


@pytest.fixture
def investigation_with_gap(basic_investigation):
    """Investigation with a gap identified."""
    basic_investigation.gaps = [
        GapIdentified(
            gap_id="GAP-001",
            dimension="temperature",
            description="No cryogenic test data available",
            severity="medium",
            requires_review=True,
        ),
    ]
    return basic_investigation


@pytest.fixture
def review_with_gap_rationale(basic_review_decisions):
    """Review decisions with gap accepted with engineer rationale."""
    basic_review_decisions.gap_decisions = [
        GapDecision(
            gap_id="GAP-001",
            decision=GapDecisionType.ACCEPT_WITH_RATIONALE,
            rationale=(
                "Application operates between 60-120 F; cryogenic data "
                "is not relevant to this use case."
            ),
        ),
    ]
    return basic_review_decisions


@pytest.fixture
def investigation_with_conflict(basic_investigation):
    """Investigation with a conflict found."""
    basic_investigation.conflicts = [
        ConflictFound(
            conflict_id="CONF-001",
            severity=ConflictSeverity.SOFT,
            source_a="MAPTIS Test #12345",
            source_b="MUA-MSFC-2022-0042",
            description=(
                "MAPTIS D-rating vs approved precedent MUA-MSFC-2022-0042"
            ),
            recommendation=(
                "Review test conditions; D-rating was obtained outside "
                "the use envelope"
            ),
        ),
    ]
    return basic_investigation


@pytest.fixture
def review_with_conflict(basic_review_decisions):
    """Review decisions with a conflict disposition."""
    basic_review_decisions.conflict_decisions = [
        ConflictDecision(
            conflict_id="CONF-001",
            decision=ReviewDecisionType.INCLUDE_CONTEXT,
            rationale=(
                "D-rating was obtained at 10.2 psia 30 % O2 which is "
                "outside the use envelope.  Precedent test conditions "
                "match the application."
            ),
        ),
    ]
    return basic_review_decisions


@pytest.fixture
def adhesive_investigation(adhesive_material, base_env, base_test_data):
    """Investigation for a process-sensitive adhesive material."""
    return InvestigationResult(
        material=adhesive_material,
        environment=base_env,
        test_data=base_test_data,
        process_params=ProcessParams(
            cure_temp_f=250.0,
            cure_time_min=60.0,
        ),
        evidence_strength=EvidenceStrengthResult(
            score=0.55,
            band=EvidenceStrengthBand.MODERATE,
        ),
    )


@pytest.fixture
def adhesive_routing():
    """Category II routing for an adhesive material."""
    return CategoryRoutingResult(
        category=MUACategory.II,
        routing_basis=[],
        authority_pack="NASA-STD-6016C",
    )


# ---------------------------------------------------------------------------
# Section structure
# ---------------------------------------------------------------------------


class TestSectionStructure:
    def test_full_7_sections(
        self, renderer, basic_investigation, basic_review_decisions, basic_routing
    ):
        """The rendered draft must contain exactly 7 sections with the
        prescribed titles, in order."""
        draft = renderer.render(
            basic_investigation, basic_review_decisions, basic_routing
        )

        assert len(draft.sections) == 7
        titles = [s.title for s in draft.sections]
        assert titles == EXPECTED_SECTION_TITLES


# ---------------------------------------------------------------------------
# Template fallback (always template-based, no LLM dependency)
# ---------------------------------------------------------------------------


class TestTemplateFallback:
    def test_template_produces_valid_sections(
        self, renderer, basic_investigation, basic_review_decisions, basic_routing
    ):
        """The renderer must produce a valid, non-empty draft using
        template-based rendering (no LLM needed).  This ensures
        the system is always functional."""
        draft = renderer.render(
            basic_investigation, basic_review_decisions, basic_routing
        )

        assert draft is not None
        assert len(draft.sections) == 7
        for section in draft.sections:
            assert len(section.content) > 0


# ---------------------------------------------------------------------------
# Gap rationale quoting
# ---------------------------------------------------------------------------


class TestGapRationale:
    def test_gap_rationale_quoted(
        self,
        renderer,
        investigation_with_gap,
        review_with_gap_rationale,
        basic_routing,
    ):
        """The engineer's gap rationale must appear verbatim in the
        rationale section so reviewers can see the original
        justification without paraphrasing."""
        draft = renderer.render(
            investigation_with_gap, review_with_gap_rationale, basic_routing
        )

        rationale_section = next(
            s for s in draft.sections if s.title == "Rationale"
        )
        expected_fragment = (
            "Application operates between 60-120 F; cryogenic data "
            "is not relevant to this use case."
        )
        assert expected_fragment in rationale_section.content


# ---------------------------------------------------------------------------
# Conflict disposition
# ---------------------------------------------------------------------------


class TestConflictDisposition:
    def test_conflict_in_mitigations(
        self,
        renderer,
        investigation_with_conflict,
        review_with_conflict,
        basic_routing,
    ):
        """When a conflict has been identified, its information must appear
        in the mitigations section of the rendered draft."""
        draft = renderer.render(
            investigation_with_conflict, review_with_conflict, basic_routing
        )

        mitigations_section = next(
            s for s in draft.sections if s.title == "Mitigations / Controls"
        )
        # The conflict description or recommendation should appear
        full_text = draft.full_text.lower()
        assert (
            "conflict" in mitigations_section.content.lower()
            or "outside the use envelope" in full_text
        )


# ---------------------------------------------------------------------------
# Process constraints for adhesive materials
# ---------------------------------------------------------------------------


class TestProcessConstraints:
    def test_adhesive_includes_process_section(
        self,
        renderer,
        adhesive_investigation,
        basic_review_decisions,
        adhesive_routing,
    ):
        """For process-sensitive materials (adhesives, composites), process
        parameter information must appear in the rendered draft."""
        draft = renderer.render(
            adhesive_investigation, basic_review_decisions, adhesive_routing
        )

        full_text = draft.full_text.lower()
        # The word "process" and cure temperature should appear
        assert "process" in full_text
        assert "250" in draft.full_text


# ---------------------------------------------------------------------------
# MUA ID format
# ---------------------------------------------------------------------------


class TestMuaIdFormat:
    def test_mua_id_format(
        self, renderer, basic_investigation, basic_review_decisions, basic_routing
    ):
        """The MUA identifier must follow the pattern MUA-MIRA-YYYY-NNNN
        (four-digit year, four-digit sequence number)."""
        draft = renderer.render(
            basic_investigation, basic_review_decisions, basic_routing
        )

        assert MUA_ID_PATTERN.match(draft.mua_id) is not None


# ---------------------------------------------------------------------------
# Prohibited language
# ---------------------------------------------------------------------------


class TestProhibitedLanguage:
    def test_never_says_approved(
        self, renderer, basic_investigation, basic_review_decisions, basic_routing
    ):
        """The draft must NEVER contain 'is approved' or 'approved for use'
        because the MUA is a recommendation, not a final approval.
        Final approval authority rests with the designated MEIT / EMES
        representative."""
        draft = renderer.render(
            basic_investigation, basic_review_decisions, basic_routing
        )

        full_text_lower = draft.full_text.lower()
        assert "is approved" not in full_text_lower
        assert "approved for use" not in full_text_lower


# ---------------------------------------------------------------------------
# Cited precedents
# ---------------------------------------------------------------------------


class TestCitedPrecedents:
    def test_included_precedents_in_cited_list(
        self, renderer, basic_investigation, basic_review_decisions, basic_routing
    ):
        """Precedents included by the engineer's review decisions must
        appear in the cited_precedents list of the rendered draft."""
        draft = renderer.render(
            basic_investigation, basic_review_decisions, basic_routing
        )

        assert "MUA-MSFC-2023-0101" in draft.cited_precedents
        assert "MUA-MSFC-2022-0055" in draft.cited_precedents
