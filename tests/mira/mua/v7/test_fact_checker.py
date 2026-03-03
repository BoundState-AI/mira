"""Tests for MUA v7 fact checker.

The fact checker verifies claims made in a draft MUA document against the
underlying evidence set.  Each claim is tagged as:

  VERIFIED   -- The claim matches the evidence.
  UNVERIFIED -- The claim does not match or cannot be confirmed.
  JUDGMENT   -- The claim is a subjective assessment rather than a
                verifiable fact; it should be labeled transparently.

This module catches hallucinated counts, incorrect ratings, fabricated
MUA numbers, and unmarked subjective language.
"""

import pytest

from mira.mua.v7.fact_checker import FactChecker
from mira.mua.v7.models import (
    CategoryRoutingResult,
    ClaimType,
    DeterminationStatus,
    DraftSection,
    EnvironmentSpec,
    EvidenceStrengthBand,
    EvidenceStrengthResult,
    FactCheckResult,
    InvestigationResult,
    MaterialResolution,
    MUACategory,
    MUADraft,
    PrecedentDecision,
    PrecedentMatch,
    ResolutionStatus,
    ReviewDecisions,
    ReviewDecisionType,
    TestDataRecord,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def checker():
    return FactChecker()


@pytest.fixture
def base_material():
    """A resolved material for building investigation results."""
    return MaterialResolution(
        input_text="6061-T6",
        status=ResolutionStatus.RESOLVED,
        resolved_name="6061-T6 Aluminum",
    )


@pytest.fixture
def base_environment():
    """A standard cabin-air environment."""
    return EnvironmentSpec(
        o2_percent=20.9,
        pressure_psia=14.7,
        temp_min_f=60.0,
        temp_max_f=120.0,
        medium="AIR",
        location="habitable",
        application="Cabin rack structural bracket",
    )


def _make_precedents(count: int, start_index: int = 0) -> list[PrecedentMatch]:
    """Create a list of APPROVED supporting precedents."""
    return [
        PrecedentMatch(
            mua_number=f"MUA-MSFC-2023-{start_index + i:04d}",
            material_designation="6061-T6",
            determination=DeterminationStatus.APPROVED,
            environment_description="Air at 14.7 psia, 60-120 degF",
            relevance_score=0.8,
            is_supporting=True,
            is_conflicting=False,
        )
        for i in range(count)
    ]


def _make_review_decisions(precedents: list[PrecedentMatch]) -> ReviewDecisions:
    """Create INCLUDE_SUPPORTING decisions for all given precedents."""
    return ReviewDecisions(
        precedent_decisions=[
            PrecedentDecision(
                mua_number=p.mua_number,
                decision=ReviewDecisionType.INCLUDE_SUPPORTING,
            )
            for p in precedents
        ],
    )


def _make_draft(content: str, mua_id: str = "MUA-MIRA-2026-0001") -> MUADraft:
    """Create a simple MUA draft with a single section containing `content`."""
    return MUADraft(
        mua_id=mua_id,
        sections=[
            DraftSection(
                section_number=1,
                title="Technical Basis",
                content=content,
            ),
        ],
        category=MUACategory.I,
        evidence_strength=EvidenceStrengthResult(
            score=0.8,
            band=EvidenceStrengthBand.STRONG,
        ),
    )


# ---------------------------------------------------------------------------
# Count verification
# ---------------------------------------------------------------------------

class TestCountVerification:
    def test_count_verification(self, checker, base_material, base_environment):
        """When the draft says '10 approved precedents' and the evidence
        set actually contains 10 approved precedents that are all included,
        the claim should be VERIFIED."""
        precedents = _make_precedents(10)
        investigation = InvestigationResult(
            material=base_material,
            environment=base_environment,
            supporting_precedents=precedents,
        )
        review = _make_review_decisions(precedents)
        draft = _make_draft("This material has 10 approved precedents in the evidence base.")

        results = checker.check_draft(draft, investigation, review)

        count_results = [r for r in results if "10 approved precedent" in r.claim_text]
        assert len(count_results) >= 1
        assert count_results[0].status == "verified"

    def test_count_mismatch(self, checker, base_material, base_environment):
        """When the draft says '10 approved precedents' but only 8 exist
        included, the claim must be UNVERIFIED. This catches LLM
        hallucination of inflated counts."""
        precedents = _make_precedents(8)
        investigation = InvestigationResult(
            material=base_material,
            environment=base_environment,
            supporting_precedents=precedents,
        )
        review = _make_review_decisions(precedents)
        draft = _make_draft("This material has 10 approved precedents supporting this usage.")

        results = checker.check_draft(draft, investigation, review)

        count_results = [r for r in results if "10 approved precedent" in r.claim_text]
        assert len(count_results) >= 1
        assert count_results[0].status == "unverified"


# ---------------------------------------------------------------------------
# Rating verification
# ---------------------------------------------------------------------------

class TestRatingVerification:
    def test_rating_verification(self, checker, base_material, base_environment):
        """A draft statement 'FLAMM Rating: A' that matches the test data
        should be VERIFIED."""
        investigation = InvestigationResult(
            material=base_material,
            environment=base_environment,
            test_data=[
                TestDataRecord(test_class="FLAMM", rating="A", is_current=True),
            ],
        )
        review = ReviewDecisions()
        draft = _make_draft("The material has a FLAMM Rating: A per MAPTIS test records.")

        results = checker.check_draft(draft, investigation, review)

        rating_results = [r for r in results if r.claim_type == ClaimType.RATING]
        assert len(rating_results) >= 1
        assert rating_results[0].status == "verified"


# ---------------------------------------------------------------------------
# MUA number verification
# ---------------------------------------------------------------------------

class TestMuaNumberVerification:
    def test_mua_number_verification(self, checker, base_material, base_environment):
        """When the draft cites a specific MUA number that exists in the
        evidence set and is included, the citation is VERIFIED."""
        precedents = _make_precedents(10)
        investigation = InvestigationResult(
            material=base_material,
            environment=base_environment,
            supporting_precedents=precedents,
        )
        review = _make_review_decisions(precedents)
        draft = _make_draft("As documented in MUA-MSFC-2023-0005, this usage is well established.")

        results = checker.check_draft(draft, investigation, review)

        mua_results = [r for r in results if "MUA-MSFC-2023-0005" in r.claim_text]
        assert len(mua_results) >= 1
        assert mua_results[0].status == "verified"

    def test_mua_number_missing(self, checker, base_material, base_environment):
        """When the draft cites a MUA number that does NOT appear in the
        evidence set, the citation is UNVERIFIED. This catches fabricated
        MUA references."""
        precedents = _make_precedents(8)
        investigation = InvestigationResult(
            material=base_material,
            environment=base_environment,
            supporting_precedents=precedents,
        )
        review = _make_review_decisions(precedents)
        draft = _make_draft("As documented in MUA-MSFC-2023-9999, the material is approved.")

        results = checker.check_draft(draft, investigation, review)

        mua_results = [r for r in results if "MUA-MSFC-2023-9999" in r.claim_text]
        assert len(mua_results) >= 1
        assert mua_results[0].status == "unverified"


# ---------------------------------------------------------------------------
# Judgment tagging
# ---------------------------------------------------------------------------

class TestJudgmentTagging:
    def test_judgment_tagging(self, checker, base_material, base_environment):
        """Subjective language like 'demonstrates acceptable performance'
        is not a verifiable fact. The fact checker should tag it as
        JUDGMENT so that the reviewer knows it is an assessment, not
        a data point."""
        investigation = InvestigationResult(
            material=base_material,
            environment=base_environment,
        )
        review = ReviewDecisions()
        draft = _make_draft(
            "The material demonstrates acceptable performance in this environment "
            "based on the evidence reviewed above."
        )

        results = checker.check_draft(draft, investigation, review)

        judgment_results = [r for r in results if r.status == "judgment"]
        assert len(judgment_results) >= 1


# ---------------------------------------------------------------------------
# Category verification
# ---------------------------------------------------------------------------

class TestCategoryVerification:
    def test_category_verification(self, checker, base_material, base_environment):
        """When the draft states 'Category III' and the routing result
        confirms Category III, the claim is VERIFIED."""
        investigation = InvestigationResult(
            material=base_material,
            environment=base_environment,
        )
        review = ReviewDecisions()
        routing = CategoryRoutingResult(category=MUACategory.III)
        draft = _make_draft("This material usage falls under Category III per NASA-STD-6016C.")

        results = checker.check_draft(draft, investigation, review, category_routing=routing)

        cat_results = [r for r in results if r.claim_type == ClaimType.APPLICABILITY and r.status != "judgment"]
        assert len(cat_results) >= 1
        assert cat_results[0].status == "verified"

    def test_category_mismatch(self, checker, base_material, base_environment):
        """When the draft states 'Category III' but routing says Category II,
        the claim is UNVERIFIED."""
        investigation = InvestigationResult(
            material=base_material,
            environment=base_environment,
        )
        review = ReviewDecisions()
        routing = CategoryRoutingResult(category=MUACategory.II)
        draft = _make_draft("This material usage falls under Category III per NASA-STD-6016C.")

        results = checker.check_draft(draft, investigation, review, category_routing=routing)

        cat_results = [r for r in results if r.claim_type == ClaimType.APPLICABILITY and r.status != "judgment"]
        assert len(cat_results) >= 1
        assert cat_results[0].status == "unverified"


# ---------------------------------------------------------------------------
# Self-reference (draft's own MUA ID)
# ---------------------------------------------------------------------------

class TestSelfReference:
    def test_self_reference_verified(self, checker, base_material, base_environment):
        """The draft's own MUA ID (MUA-MIRA-YYYY-NNNN pattern) should be
        VERIFIED as a self-reference, not flagged as an unknown citation."""
        investigation = InvestigationResult(
            material=base_material,
            environment=base_environment,
        )
        review = ReviewDecisions()
        draft = _make_draft(
            "This document, MUA-MIRA-2026-0001, covers the usage of 6061-T6 aluminum.",
            mua_id="MUA-MIRA-2026-0001",
        )

        results = checker.check_draft(draft, investigation, review)

        self_ref_results = [r for r in results if "MUA-MIRA-2026-0001" in r.claim_text]
        assert len(self_ref_results) >= 1
        assert self_ref_results[0].status == "verified"
