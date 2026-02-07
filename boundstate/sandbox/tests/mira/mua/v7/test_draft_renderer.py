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
from datetime import datetime, timezone

import pytest

from mira.mua.v7.draft_renderer import (
    DraftRenderer,
    DraftInput,
    MaterialInfo,
    EnvironmentInfo,
    InvestigationSummary,
    ConflictDisposition,
    GapRationale,
    ProcessConstraint,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

MUA_ID_PATTERN = re.compile(r"^MUA-MIRA-\d{4}-\d{4}$")

EXPECTED_SECTION_TITLES = [
    "Identification",
    "Material Description",
    "Use Environment",
    "Evidence Summary",
    "Rationale",
    "Constraints and Limitations",
    "Recommendation",
]


@pytest.fixture
def renderer():
    return DraftRenderer()


@pytest.fixture
def basic_input():
    """A minimal DraftInput for a straightforward aluminum MUA."""
    return DraftInput(
        mua_id="MUA-MIRA-2025-0001",
        material=MaterialInfo(
            name="6061-T6",
            canonical_id="MAT-A96061",
            family="aluminum",
            is_process_sensitive=False,
        ),
        environment=EnvironmentInfo(
            medium="AIR",
            o2_percent=20.9,
            pressure_psia=14.7,
            temp_range_f=(60.0, 120.0),
        ),
        investigation=InvestigationSummary(
            precedent_count=8,
            confidence_band="STRONG",
            category="III",
            conflicts=[],
            gaps=[],
        ),
        conflict_dispositions=[],
        gap_rationales=[],
        process_constraints=[],
        generated_at=datetime(2025, 6, 15, tzinfo=timezone.utc),
    )


@pytest.fixture
def input_with_gap_rationale(basic_input):
    """DraftInput that includes an engineer's gap rationale."""
    basic_input.investigation.gaps = ["No cryogenic test data available"]
    basic_input.gap_rationales = [
        GapRationale(
            gap_description="No cryogenic test data available",
            engineer_rationale=(
                "Application operates between 60-120 F; cryogenic data "
                "is not relevant to this use case."
            ),
        )
    ]
    return basic_input


@pytest.fixture
def input_with_conflict(basic_input):
    """DraftInput with a conflict that has been dispositioned."""
    basic_input.investigation.conflicts = [
        "MAPTIS D-rating vs approved precedent MUA-MSFC-2022-0042"
    ]
    basic_input.conflict_dispositions = [
        ConflictDisposition(
            conflict_description=(
                "MAPTIS D-rating vs approved precedent MUA-MSFC-2022-0042"
            ),
            decision="ACCEPT_PRECEDENT",
            justification=(
                "D-rating was obtained at 10.2 psia 30 % O2 which is "
                "outside the use envelope.  Precedent test conditions "
                "match the application."
            ),
        )
    ]
    return basic_input


@pytest.fixture
def adhesive_input():
    """DraftInput for an adhesive (process-sensitive) material."""
    return DraftInput(
        mua_id="MUA-MIRA-2025-0042",
        material=MaterialInfo(
            name="EA 9394",
            canonical_id="MAT-EA9394",
            family="adhesive",
            is_process_sensitive=True,
        ),
        environment=EnvironmentInfo(
            medium="AIR",
            o2_percent=20.9,
            pressure_psia=14.7,
            temp_range_f=(60.0, 200.0),
        ),
        investigation=InvestigationSummary(
            precedent_count=3,
            confidence_band="MODERATE",
            category="II",
            conflicts=[],
            gaps=[],
        ),
        conflict_dispositions=[],
        gap_rationales=[],
        process_constraints=[
            ProcessConstraint(
                constraint_type="CURE_CYCLE",
                description=(
                    "Cure at 250 F for 60 minutes minimum.  Post-cure at "
                    "350 F for 120 minutes.  Bond-line thickness not to "
                    "exceed 0.010 in."
                ),
            )
        ],
        generated_at=datetime(2025, 6, 15, tzinfo=timezone.utc),
    )


# ---------------------------------------------------------------------------
# Section structure
# ---------------------------------------------------------------------------

class TestSectionStructure:
    def test_full_7_sections(self, renderer, basic_input):
        """The rendered draft must contain exactly 7 sections with the
        prescribed titles, in order."""
        draft = renderer.render(basic_input)

        assert len(draft.sections) == 7
        titles = [s.title for s in draft.sections]
        assert titles == EXPECTED_SECTION_TITLES


# ---------------------------------------------------------------------------
# Template fallback
# ---------------------------------------------------------------------------

class TestTemplateFallback:
    def test_template_fallback(self, renderer, basic_input):
        """The renderer must produce a valid, non-empty draft even when
        no LLM is available (pure template rendering).  This ensures
        the system degrades gracefully."""
        draft = renderer.render(basic_input, use_llm=False)

        assert draft is not None
        assert len(draft.sections) == 7
        for section in draft.sections:
            assert len(section.body) > 0


# ---------------------------------------------------------------------------
# Gap rationale quoting
# ---------------------------------------------------------------------------

class TestGapRationale:
    def test_gap_rationale_quoted(self, renderer, input_with_gap_rationale):
        """The engineer's gap rationale must appear verbatim in the
        rationale section so reviewers can see the original
        justification without paraphrasing."""
        draft = renderer.render(input_with_gap_rationale, use_llm=False)

        rationale_section = next(
            s for s in draft.sections if s.title == "Rationale"
        )
        expected_fragment = (
            "Application operates between 60-120 F; cryogenic data "
            "is not relevant to this use case."
        )
        assert expected_fragment in rationale_section.body


# ---------------------------------------------------------------------------
# Conflict disposition
# ---------------------------------------------------------------------------

class TestConflictDisposition:
    def test_conflict_disposition(self, renderer, input_with_conflict):
        """When a conflict has been dispositioned, the decision and
        justification must appear in the rendered draft."""
        draft = renderer.render(input_with_conflict, use_llm=False)

        full_text = " ".join(s.body for s in draft.sections)
        assert "ACCEPT_PRECEDENT" in full_text or "precedent" in full_text.lower()
        assert "outside the use envelope" in full_text


# ---------------------------------------------------------------------------
# Process constraints
# ---------------------------------------------------------------------------

class TestProcessConstraints:
    def test_process_constraints(self, renderer, adhesive_input):
        """For process-sensitive materials (adhesives, coatings), cure
        cycle or application constraints must appear in the
        'Constraints and Limitations' section."""
        draft = renderer.render(adhesive_input, use_llm=False)

        constraints_section = next(
            s for s in draft.sections if s.title == "Constraints and Limitations"
        )
        assert "250 F" in constraints_section.body
        assert "cure" in constraints_section.body.lower()


# ---------------------------------------------------------------------------
# MUA ID format
# ---------------------------------------------------------------------------

class TestMuaIdFormat:
    def test_mua_id_format(self, renderer, basic_input):
        """The MUA identifier must follow the pattern MUA-MIRA-YYYY-NNNN
        (four-digit year, four-digit sequence number)."""
        draft = renderer.render(basic_input, use_llm=False)

        id_section = next(
            s for s in draft.sections if s.title == "Identification"
        )
        assert MUA_ID_PATTERN.search(id_section.body) is not None


# ---------------------------------------------------------------------------
# Prohibited language
# ---------------------------------------------------------------------------

class TestProhibitedLanguage:
    def test_never_says_approved(self, renderer, basic_input):
        """The draft must NEVER contain 'is approved' or 'approved for use'
        because the MUA is a recommendation, not a final approval.
        Final approval authority rests with the designated MEIT / EMES
        representative."""
        draft = renderer.render(basic_input, use_llm=False)

        full_text = " ".join(s.body for s in draft.sections).lower()
        assert "is approved" not in full_text
        assert "approved for use" not in full_text
