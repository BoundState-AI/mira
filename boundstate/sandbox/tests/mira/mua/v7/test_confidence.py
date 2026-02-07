"""Tests for MUA v7 evidence-strength (confidence) calculation.

The confidence scorer converts raw evidence (precedents, test data,
envelope coverage, material resolution quality) into a composite score
that maps to one of four bands: STRONG, MODERATE, WEAK, INSUFFICIENT.

Critical safety invariants tested here:

* C2 fix -- missing data scores as 0.0, never 0.5.
* Saturation -- many weak precedents cannot game the score to STRONG.
* Hard conflicts apply a 0.4x consistency penalty.
* Critical gaps apply an exponential penalty.
* Unresolved material applies a 0.5x multiplier.
* Missing pressure in H2 service forces a 0.0 multiplier (guaranteed REVIEW).
"""

import pytest

from mira.mua.v7.confidence import (
    ConfidenceBand,
    ConfidenceScorer,
    EvidencePacket,
    Precedent,
    TestDataRecord,
    EnvelopeCoverage,
    GapDescriptor,
    ConflictDescriptor,
    MaterialResolutionInfo,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_precedent(outcome="APPROVED", age_years=1):
    """Create a minimal Precedent fixture."""
    return Precedent(
        mua_number=f"MUA-MSFC-2024-{age_years:04d}",
        material="6061-T6",
        outcome=outcome,
        age_years=age_years,
    )


def _make_test_data(expired=False):
    """Create a minimal TestDataRecord fixture."""
    return TestDataRecord(
        test_type="FLAMM",
        rating="A",
        source="MAPTIS",
        expired=expired,
    )


def _full_envelope():
    """Return an EnvelopeCoverage indicating 100 % coverage."""
    return EnvelopeCoverage(
        temp_covered=True,
        pressure_covered=True,
        o2_covered=True,
        coverage_fraction=1.0,
    )


def _partial_envelope():
    """Return an EnvelopeCoverage indicating partial (~60 %) coverage."""
    return EnvelopeCoverage(
        temp_covered=True,
        pressure_covered=False,
        o2_covered=True,
        coverage_fraction=0.6,
    )


# ---------------------------------------------------------------------------
# Band classification
# ---------------------------------------------------------------------------

class TestBandClassification:
    def test_strong_evidence(self):
        """12 supporting precedents, current test data, and full envelope
        coverage should produce a STRONG confidence band."""
        packet = EvidencePacket(
            precedents=[_make_precedent() for _ in range(12)],
            test_data=[_make_test_data()],
            envelope=_full_envelope(),
            conflicts=[],
            gaps=[],
            material_info=MaterialResolutionInfo(resolved=True),
        )
        scorer = ConfidenceScorer()
        result = scorer.score(packet)

        assert result.band == ConfidenceBand.STRONG

    def test_moderate_evidence(self):
        """5 precedents with partial envelope coverage should land in the
        MODERATE band."""
        packet = EvidencePacket(
            precedents=[_make_precedent() for _ in range(5)],
            test_data=[_make_test_data()],
            envelope=_partial_envelope(),
            conflicts=[],
            gaps=[],
            material_info=MaterialResolutionInfo(resolved=True),
        )
        scorer = ConfidenceScorer()
        result = scorer.score(packet)

        assert result.band == ConfidenceBand.MODERATE

    def test_weak_evidence(self):
        """A single precedent with expired test data should produce a WEAK
        band."""
        packet = EvidencePacket(
            precedents=[_make_precedent(age_years=8)],
            test_data=[_make_test_data(expired=True)],
            envelope=_partial_envelope(),
            conflicts=[],
            gaps=[],
            material_info=MaterialResolutionInfo(resolved=True),
        )
        scorer = ConfidenceScorer()
        result = scorer.score(packet)

        assert result.band == ConfidenceBand.WEAK

    def test_insufficient_evidence(self):
        """Zero precedents and no test data must be INSUFFICIENT -- there
        is literally no evidence to support a use determination."""
        packet = EvidencePacket(
            precedents=[],
            test_data=[],
            envelope=_partial_envelope(),
            conflicts=[],
            gaps=[],
            material_info=MaterialResolutionInfo(resolved=True),
        )
        scorer = ConfidenceScorer()
        result = scorer.score(packet)

        assert result.band == ConfidenceBand.INSUFFICIENT


# ---------------------------------------------------------------------------
# C2 safety fix: missing data == 0.0, not 0.5
# ---------------------------------------------------------------------------

class TestMissingDataZero:
    def test_missing_data_zero_not_half(self):
        """When pressure data is missing from the envelope, the pressure
        component of the score MUST be 0.0.  The old v6 bug defaulted
        missing values to 0.5 which could silently inflate confidence."""
        envelope = EnvelopeCoverage(
            temp_covered=True,
            pressure_covered=False,
            o2_covered=True,
            coverage_fraction=0.6,
        )
        packet = EvidencePacket(
            precedents=[_make_precedent() for _ in range(3)],
            test_data=[_make_test_data()],
            envelope=envelope,
            conflicts=[],
            gaps=[],
            material_info=MaterialResolutionInfo(resolved=True),
        )
        scorer = ConfidenceScorer()
        result = scorer.score(packet)

        # The pressure component must be zero, not the 0.5 default
        assert result.component_scores["pressure"] == 0.0


# ---------------------------------------------------------------------------
# Saturation: many weak records cannot game the score
# ---------------------------------------------------------------------------

class TestSaturation:
    def test_saturation(self):
        """20 very old, weak precedents must NOT push the composite score
        into the STRONG band.  The saturation function should prevent
        quantity from substituting for quality."""
        weak_precedents = [_make_precedent(age_years=10) for _ in range(20)]
        packet = EvidencePacket(
            precedents=weak_precedents,
            test_data=[_make_test_data(expired=True)],
            envelope=_partial_envelope(),
            conflicts=[],
            gaps=[],
            material_info=MaterialResolutionInfo(resolved=True),
        )
        scorer = ConfidenceScorer()
        result = scorer.score(packet)

        assert result.band != ConfidenceBand.STRONG


# ---------------------------------------------------------------------------
# Penalties
# ---------------------------------------------------------------------------

class TestPenalties:
    def test_conflict_penalty(self):
        """A hard conflict (e.g. one source says APPROVED while another
        says REJECTED) must apply a 0.4x multiplier to the consistency
        component."""
        conflict = ConflictDescriptor(
            severity="HARD",
            source_a="MAPTIS",
            source_b="BOK",
            description="MAPTIS rates D; BOK records approval",
        )
        packet = EvidencePacket(
            precedents=[_make_precedent() for _ in range(10)],
            test_data=[_make_test_data()],
            envelope=_full_envelope(),
            conflicts=[conflict],
            gaps=[],
            material_info=MaterialResolutionInfo(resolved=True),
        )
        scorer = ConfidenceScorer()
        result = scorer.score(packet)

        # Consistency component should be reduced by the 0.4x multiplier
        assert result.component_scores["consistency"] <= 0.4

    def test_gap_penalty(self):
        """A critical gap (e.g. no ignition data for an oxygen-enriched
        environment) must apply an exponential penalty that materially
        reduces the overall score."""
        gap = GapDescriptor(
            severity="CRITICAL",
            description="No ignition data for O2 > 30 % environment",
        )
        # Start with otherwise-strong evidence
        packet_no_gap = EvidencePacket(
            precedents=[_make_precedent() for _ in range(12)],
            test_data=[_make_test_data()],
            envelope=_full_envelope(),
            conflicts=[],
            gaps=[],
            material_info=MaterialResolutionInfo(resolved=True),
        )
        packet_with_gap = EvidencePacket(
            precedents=[_make_precedent() for _ in range(12)],
            test_data=[_make_test_data()],
            envelope=_full_envelope(),
            conflicts=[],
            gaps=[gap],
            material_info=MaterialResolutionInfo(resolved=True),
        )
        scorer = ConfidenceScorer()
        score_clean = scorer.score(packet_no_gap)
        score_gap = scorer.score(packet_with_gap)

        assert score_gap.composite < score_clean.composite

    def test_unresolved_material_penalty(self):
        """When the material resolver could not resolve the input, the
        overall score receives a 0.5x multiplier because we cannot be
        confident the evidence actually pertains to the requested
        material."""
        packet = EvidencePacket(
            precedents=[_make_precedent() for _ in range(10)],
            test_data=[_make_test_data()],
            envelope=_full_envelope(),
            conflicts=[],
            gaps=[],
            material_info=MaterialResolutionInfo(resolved=False),
        )
        scorer = ConfidenceScorer()
        result = scorer.score(packet)

        # The composite should be halved relative to the same packet
        # with a resolved material
        packet_resolved = EvidencePacket(
            precedents=[_make_precedent() for _ in range(10)],
            test_data=[_make_test_data()],
            envelope=_full_envelope(),
            conflicts=[],
            gaps=[],
            material_info=MaterialResolutionInfo(resolved=True),
        )
        result_resolved = scorer.score(packet_resolved)

        assert result.composite == pytest.approx(
            result_resolved.composite * 0.5, rel=0.05
        )

    def test_h2_missing_pressure_zero(self):
        """In hydrogen service, missing pressure data is a safety-critical
        gap.  The scorer must apply a 0.0 multiplier -- effectively
        forcing the result to REVIEW regardless of other evidence."""
        envelope = EnvelopeCoverage(
            temp_covered=True,
            pressure_covered=False,
            o2_covered=True,
            coverage_fraction=0.5,
            medium="GH2",
        )
        packet = EvidencePacket(
            precedents=[_make_precedent() for _ in range(12)],
            test_data=[_make_test_data()],
            envelope=envelope,
            conflicts=[],
            gaps=[],
            material_info=MaterialResolutionInfo(resolved=True),
        )
        scorer = ConfidenceScorer()
        result = scorer.score(packet)

        # 0.0 multiplier on the pressure dimension forces overall
        # composite low enough to require REVIEW
        assert result.component_scores["pressure"] == 0.0
        assert result.band in (ConfidenceBand.WEAK, ConfidenceBand.INSUFFICIENT)


# ---------------------------------------------------------------------------
# Component breakdown
# ---------------------------------------------------------------------------

class TestComponentBreakdown:
    def test_component_breakdown(self):
        """The scorer must return a per-component breakdown so that
        reviewers can see which evidence dimensions are strong vs weak."""
        packet = EvidencePacket(
            precedents=[_make_precedent() for _ in range(5)],
            test_data=[_make_test_data()],
            envelope=_full_envelope(),
            conflicts=[],
            gaps=[],
            material_info=MaterialResolutionInfo(resolved=True),
        )
        scorer = ConfidenceScorer()
        result = scorer.score(packet)

        expected_components = {
            "precedent",
            "test_data",
            "envelope",
            "consistency",
            "pressure",
        }
        assert expected_components.issubset(set(result.component_scores.keys()))
        for value in result.component_scores.values():
            assert 0.0 <= value <= 1.0
