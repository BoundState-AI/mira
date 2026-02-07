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

from mira.mua.v7.fact_checker import (
    FactChecker,
    ClaimVerdict,
    DraftClaim,
    EvidenceSet,
    EvidenceItem,
    RoutingResult,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def checker():
    return FactChecker()


@pytest.fixture
def ten_approved_items():
    """An evidence set containing exactly 10 approved precedents."""
    items = []
    for i in range(10):
        items.append(
            EvidenceItem(
                item_type="PRECEDENT",
                mua_number=f"MUA-MSFC-2023-{i:04d}",
                outcome="APPROVED",
                rating=None,
                detail=f"Approved for application #{i}",
            )
        )
    return EvidenceSet(items=items)


@pytest.fixture
def eight_approved_items():
    """An evidence set containing exactly 8 approved precedents."""
    items = []
    for i in range(8):
        items.append(
            EvidenceItem(
                item_type="PRECEDENT",
                mua_number=f"MUA-MSFC-2023-{i:04d}",
                outcome="APPROVED",
                rating=None,
                detail=f"Approved for application #{i}",
            )
        )
    return EvidenceSet(items=items)


@pytest.fixture
def flamm_a_evidence():
    """Evidence set containing a single MAPTIS record with rating A."""
    return EvidenceSet(
        items=[
            EvidenceItem(
                item_type="MAPTIS",
                mua_number=None,
                outcome=None,
                rating="A",
                detail="MAPTIS Test #71234: A-rated flammability at 14.7 psia air",
            )
        ]
    )


@pytest.fixture
def category_iii_routing():
    """A routing result indicating Category III."""
    return RoutingResult(
        category="III",
        rule_id="CAT3-ALL-A-NONHAB",
        citation="NASA-STD-6016C Table 2",
        applied_standard="NASA-STD-6016C",
    )


# ---------------------------------------------------------------------------
# Count verification
# ---------------------------------------------------------------------------

class TestCountVerification:
    def test_count_verification(self, checker, ten_approved_items):
        """When the draft says '10 approved precedents' and the evidence
        set actually contains 10 approved precedents, the claim should
        be VERIFIED."""
        claim = DraftClaim(
            text="10 approved precedents support this usage",
            claim_type="COUNT",
            asserted_count=10,
            asserted_outcome="APPROVED",
        )
        verdict = checker.check_claim(claim, ten_approved_items)

        assert verdict.result == ClaimVerdict.VERIFIED

    def test_count_mismatch(self, checker, eight_approved_items):
        """When the draft says '10 approved precedents' but only 8 exist,
        the claim must be UNVERIFIED.  This catches LLM hallucination
        of inflated counts."""
        claim = DraftClaim(
            text="10 approved precedents support this usage",
            claim_type="COUNT",
            asserted_count=10,
            asserted_outcome="APPROVED",
        )
        verdict = checker.check_claim(claim, eight_approved_items)

        assert verdict.result == ClaimVerdict.UNVERIFIED
        assert verdict.actual_count == 8


# ---------------------------------------------------------------------------
# Rating verification
# ---------------------------------------------------------------------------

class TestRatingVerification:
    def test_rating_verification(self, checker, flamm_a_evidence):
        """A draft statement 'FLAMM rating: A' that matches the test data
        should be VERIFIED."""
        claim = DraftClaim(
            text="FLAMM rating: A",
            claim_type="RATING",
            asserted_rating="A",
            asserted_test_type="FLAMM",
        )
        verdict = checker.check_claim(claim, flamm_a_evidence)

        assert verdict.result == ClaimVerdict.VERIFIED


# ---------------------------------------------------------------------------
# MUA number verification
# ---------------------------------------------------------------------------

class TestMuaNumberVerification:
    def test_mua_number_verification(self, checker, ten_approved_items):
        """When the draft cites a specific MUA number that exists in the
        evidence set, the citation is VERIFIED."""
        claim = DraftClaim(
            text="As documented in MUA-MSFC-2023-0005",
            claim_type="MUA_CITATION",
            cited_mua="MUA-MSFC-2023-0005",
        )
        verdict = checker.check_claim(claim, ten_approved_items)

        assert verdict.result == ClaimVerdict.VERIFIED

    def test_mua_number_missing(self, checker, eight_approved_items):
        """When the draft cites a MUA number that does NOT appear in the
        evidence set, the citation is UNVERIFIED.  This catches
        fabricated MUA references."""
        claim = DraftClaim(
            text="As documented in MUA-MSFC-2023-9999",
            claim_type="MUA_CITATION",
            cited_mua="MUA-MSFC-2023-9999",
        )
        verdict = checker.check_claim(claim, eight_approved_items)

        assert verdict.result == ClaimVerdict.UNVERIFIED


# ---------------------------------------------------------------------------
# Judgment tagging
# ---------------------------------------------------------------------------

class TestJudgmentTagging:
    def test_judgment_tagging(self, checker, ten_approved_items):
        """Subjective language like 'demonstrates acceptable performance'
        is not a verifiable fact.  The fact checker should tag it as
        JUDGMENT so that the reviewer knows it is an assessment, not
        a data point."""
        claim = DraftClaim(
            text="The material demonstrates acceptable performance in this environment",
            claim_type="ASSERTION",
        )
        verdict = checker.check_claim(claim, ten_approved_items)

        assert verdict.result == ClaimVerdict.JUDGMENT


# ---------------------------------------------------------------------------
# Category verification
# ---------------------------------------------------------------------------

class TestCategoryVerification:
    def test_category_verification(
        self, checker, ten_approved_items, category_iii_routing
    ):
        """When the draft states 'Category III' and the routing result
        confirms Category III, the claim is VERIFIED."""
        claim = DraftClaim(
            text="This material usage falls under Category III",
            claim_type="CATEGORY",
            asserted_category="III",
        )
        verdict = checker.check_claim(
            claim,
            ten_approved_items,
            routing=category_iii_routing,
        )

        assert verdict.result == ClaimVerdict.VERIFIED
