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

from mira.mua.v7.confidence import calculate_evidence_strength
from mira.mua.v7.models import (
    ConflictFound,
    ConflictSeverity,
    DeterminationStatus,
    EnvironmentSpec,
    EnvelopeResult,
    EvidenceStrengthBand,
    GapIdentified,
    MaterialResolution,
    OverlapStatus,
    PrecedentMatch,
    ResolutionStatus,
    TestDataRecord,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_precedent(
    determination=DeterminationStatus.APPROVED,
    relevance=0.8,
    mua_suffix="0001",
):
    """Create a minimal PrecedentMatch fixture."""
    return PrecedentMatch(
        mua_number=f"MUA-MSFC-2024-{mua_suffix}",
        material_designation="6061-T6",
        determination=determination,
        environment_description="Cabin rack brackets, SLS Block 1B",
        relevance_score=relevance,
    )


def _make_test_data(test_class="FLAMM", rating="A", is_current=True):
    """Create a minimal TestDataRecord fixture."""
    return TestDataRecord(
        test_class=test_class,
        rating=rating,
        is_current=is_current,
    )


def _all_class_test_data(rating="A", is_current=True):
    """Create test data covering all 6 required test classes."""
    classes = ["FLAMM", "SCC", "CORR", "TVS", "TOX", "FS"]
    return [
        TestDataRecord(test_class=c, rating=rating, is_current=is_current)
        for c in classes
    ]


def _full_envelope():
    """Return an EnvelopeResult indicating 100% coverage (all WITHIN)."""
    return EnvelopeResult(
        overall_status=OverlapStatus.WITHIN,
        o2_status=OverlapStatus.WITHIN,
        pressure_status=OverlapStatus.WITHIN,
        temp_status=OverlapStatus.WITHIN,
        coverage_ratio=1.0,
    )


def _partial_envelope():
    """Return an EnvelopeResult with partial coverage."""
    return EnvelopeResult(
        overall_status=OverlapStatus.PARTIAL,
        o2_status=OverlapStatus.WITHIN,
        pressure_status=OverlapStatus.PARTIAL,
        temp_status=OverlapStatus.WITHIN,
        coverage_ratio=0.6,
    )


def _resolved_material():
    """Return a resolved MaterialResolution."""
    return MaterialResolution(
        input_text="6061-T6",
        status=ResolutionStatus.RESOLVED,
        material_code="MAT-A96061",
        resolved_name="6061-T6 Aluminum",
    )


def _unresolved_material():
    """Return an unresolved MaterialResolution."""
    return MaterialResolution(
        input_text="unknown alloy",
        status=ResolutionStatus.UNRESOLVED,
    )


def _standard_environment():
    """Return a standard (non-hydrogen, non-enriched-O2, non-cryogenic) environment."""
    return EnvironmentSpec(
        o2_percent=20.9,
        pressure_psia=14.7,
        temp_min_f=60.0,
        temp_max_f=120.0,
        medium="Air",
        location="habitable",
        application="Cabin rack brackets",
    )


def _hydrogen_environment():
    """Return a hydrogen-service environment."""
    return EnvironmentSpec(
        o2_percent=0.0,
        pressure_psia=3000.0,
        temp_min_f=-200.0,
        temp_max_f=150.0,
        medium="GH2",
        location="non_habitable",
        application="Hydrogen fuel line brackets",
    )


def _base_strong_packet():
    """Return a base packet that should produce STRONG evidence."""
    return dict(
        supporting_precedents=[
            _make_precedent(mua_suffix=f"{i:04d}") for i in range(12)
        ],
        conflicting_precedents=[],
        test_data=_all_class_test_data(rating="A", is_current=True),
        envelope=_full_envelope(),
        conflicts=[],
        gaps=[],
        material=_resolved_material(),
        environment=_standard_environment(),
    )


# ---------------------------------------------------------------------------
# Band classification
# ---------------------------------------------------------------------------


class TestBandClassification:
    def test_strong_evidence(self):
        """12 supporting precedents, current A-rated test data across all
        6 classes, and full envelope coverage should produce STRONG."""
        result = calculate_evidence_strength(**_base_strong_packet())
        assert result.band == EvidenceStrengthBand.STRONG

    def test_moderate_evidence(self):
        """3 precedents with partial envelope and only FLAMM test data
        should land in the MODERATE band."""
        packet = dict(
            supporting_precedents=[
                _make_precedent(mua_suffix=f"{i:04d}") for i in range(3)
            ],
            conflicting_precedents=[],
            test_data=[_make_test_data("FLAMM", "B", True)],
            envelope=_partial_envelope(),
            conflicts=[],
            gaps=[],
            material=_resolved_material(),
            environment=_standard_environment(),
        )
        result = calculate_evidence_strength(**packet)
        assert result.band == EvidenceStrengthBand.MODERATE

    def test_weak_evidence(self):
        """A single low-relevance precedent with expired test data and
        no envelope should produce a WEAK band."""
        packet = dict(
            supporting_precedents=[
                _make_precedent(relevance=0.3, mua_suffix="0001")
            ],
            conflicting_precedents=[],
            test_data=[_make_test_data("FLAMM", "C", is_current=False)],
            envelope=None,
            conflicts=[],
            gaps=[],
            material=_resolved_material(),
            environment=_standard_environment(),
        )
        result = calculate_evidence_strength(**packet)
        assert result.band == EvidenceStrengthBand.WEAK

    def test_insufficient_evidence(self):
        """Zero precedents and no test data with a SOFT conflict to
        reduce consistency must yield INSUFFICIENT -- there is
        literally no evidence to support a use determination."""
        # A soft conflict reduces consistency to 0.7.  With zero
        # evidence in all other components the weighted sum is
        # 0.15 * 0.7 = 0.105 < 0.15 -> INSUFFICIENT.
        conflict = ConflictFound(
            conflict_id="test-insuff-1",
            severity=ConflictSeverity.SOFT,
            source_a="src-a",
            source_b="src-b",
            description="Minor divergence",
            recommendation="Review",
        )
        packet = dict(
            supporting_precedents=[],
            conflicting_precedents=[],
            test_data=[],
            envelope=None,
            conflicts=[conflict],
            gaps=[],
            material=_resolved_material(),
            environment=_standard_environment(),
        )
        result = calculate_evidence_strength(**packet)
        assert result.band == EvidenceStrengthBand.INSUFFICIENT


# ---------------------------------------------------------------------------
# C2 safety fix: missing data == 0.0, not 0.5
# ---------------------------------------------------------------------------


class TestMissingDataZero:
    def test_insufficient_data_envelope_dim_scores_zero(self):
        """When an envelope dimension has INSUFFICIENT_DATA status, its
        score must be 0.0. The old v6 bug defaulted missing values to
        0.5 which could silently inflate confidence."""
        envelope = EnvelopeResult(
            overall_status=OverlapStatus.WITHIN,
            o2_status=OverlapStatus.WITHIN,
            pressure_status=OverlapStatus.INSUFFICIENT_DATA,
            temp_status=OverlapStatus.WITHIN,
            coverage_ratio=0.6,
        )
        packet = dict(
            supporting_precedents=[
                _make_precedent(mua_suffix=f"{i:04d}") for i in range(3)
            ],
            conflicting_precedents=[],
            test_data=_all_class_test_data(),
            envelope=envelope,
            conflicts=[],
            gaps=[],
            material=_resolved_material(),
            environment=_standard_environment(),
        )
        result = calculate_evidence_strength(**packet)

        # The envelope_coverage component detail should show pressure=0.00
        env_detail = result.components["envelope_coverage"]["detail"]
        assert "pressure=0.00" in env_detail


# ---------------------------------------------------------------------------
# Saturation: many weak records cannot game the score
# ---------------------------------------------------------------------------


class TestSaturation:
    def test_saturation(self):
        """20 weak (low-relevance) precedents must NOT push the composite
        score into the STRONG band. The saturating exponential prevents
        quantity from substituting for quality."""
        weak_precedents = [
            _make_precedent(
                determination=DeterminationStatus.CONDITIONAL,
                relevance=0.15,
                mua_suffix=f"{i:04d}",
            )
            for i in range(20)
        ]
        packet = dict(
            supporting_precedents=weak_precedents,
            conflicting_precedents=[],
            test_data=[_make_test_data("FLAMM", "C", is_current=False)],
            envelope=_partial_envelope(),
            conflicts=[],
            gaps=[],
            material=_resolved_material(),
            environment=_standard_environment(),
        )
        result = calculate_evidence_strength(**packet)
        assert result.band != EvidenceStrengthBand.STRONG


# ---------------------------------------------------------------------------
# Penalties
# ---------------------------------------------------------------------------


class TestPenalties:
    def test_conflict_penalty(self):
        """A HARD conflict must apply a 0.4 consistency raw score."""
        conflict = ConflictFound(
            conflict_id="test-conflict-1",
            severity=ConflictSeverity.HARD,
            source_a="MAPTIS",
            source_b="BOK",
            description="MAPTIS rates D; BOK records approval",
            recommendation="Review required",
        )
        packet = _base_strong_packet()
        packet["conflicts"] = [conflict]
        result = calculate_evidence_strength(**packet)

        # Consistency raw score should be 0.4 due to HARD conflict
        assert result.components["consistency"]["raw"] == pytest.approx(0.4)

    def test_gap_penalty(self):
        """A critical gap must apply an exponential penalty that reduces
        the overall score relative to a no-gap baseline."""
        gap = GapIdentified(
            gap_id="test-gap-1",
            dimension="o2",
            description="No ignition data for O2 > 30% environment",
            severity="critical",
            requires_review=False,
        )
        packet_no_gap = _base_strong_packet()
        packet_with_gap = _base_strong_packet()
        packet_with_gap["gaps"] = [gap]

        score_clean = calculate_evidence_strength(**packet_no_gap)
        score_gap = calculate_evidence_strength(**packet_with_gap)

        assert score_gap.score < score_clean.score
        # Gap penalty factor should be < 1.0
        assert score_gap.penalties["gap_severity"]["factor"] < 1.0

    def test_unresolved_material_penalty(self):
        """When the material is UNRESOLVED, the material_resolution penalty
        should be 0.5, halving the overall score."""
        packet_resolved = _base_strong_packet()
        packet_unresolved = _base_strong_packet()
        packet_unresolved["material"] = _unresolved_material()

        result_resolved = calculate_evidence_strength(**packet_resolved)
        result_unresolved = calculate_evidence_strength(**packet_unresolved)

        # Penalty factor should be exactly 0.5
        assert result_unresolved.penalties["material_resolution"]["factor"] == pytest.approx(0.5)
        # Score should be approximately half
        assert result_unresolved.score == pytest.approx(
            result_resolved.score * 0.5, rel=0.05
        )

    def test_h2_missing_pressure_zero(self):
        """In hydrogen service, missing pressure data is safety-critical.
        The scorer must apply a 0.0 critical_field penalty, forcing the
        overall score to 0.0."""
        envelope = EnvelopeResult(
            overall_status=OverlapStatus.WITHIN,
            o2_status=OverlapStatus.WITHIN,
            pressure_status=OverlapStatus.INSUFFICIENT_DATA,
            temp_status=OverlapStatus.WITHIN,
            coverage_ratio=0.5,
        )
        packet = dict(
            supporting_precedents=[
                _make_precedent(mua_suffix=f"{i:04d}") for i in range(12)
            ],
            conflicting_precedents=[],
            test_data=_all_class_test_data(),
            envelope=envelope,
            conflicts=[],
            gaps=[],
            material=_resolved_material(),
            environment=_hydrogen_environment(),
        )
        result = calculate_evidence_strength(**packet)

        # Critical field penalty should be 0.0
        assert result.penalties["critical_field"]["factor"] == 0.0
        # Overall score forced to 0.0
        assert result.score == 0.0
        assert result.band == EvidenceStrengthBand.INSUFFICIENT


# ---------------------------------------------------------------------------
# Component breakdown
# ---------------------------------------------------------------------------


class TestComponentBreakdown:
    def test_component_breakdown_keys(self):
        """The scorer must return the expected component keys in the
        breakdown dict."""
        result = calculate_evidence_strength(**_base_strong_packet())

        expected_keys = {
            "precedent_support",
            "test_coverage",
            "envelope_coverage",
            "currency",
            "consistency",
        }
        assert expected_keys == set(result.components.keys())

    def test_component_breakdown_structure(self):
        """Each component must have raw, weight, weighted, and detail fields."""
        result = calculate_evidence_strength(**_base_strong_packet())

        for name, info in result.components.items():
            assert "raw" in info, f"Component '{name}' missing 'raw'"
            assert "weight" in info, f"Component '{name}' missing 'weight'"
            assert "weighted" in info, f"Component '{name}' missing 'weighted'"
            assert "detail" in info, f"Component '{name}' missing 'detail'"
            assert 0.0 <= info["raw"] <= 1.0, (
                f"Component '{name}' raw={info['raw']} out of range"
            )

    def test_penalty_breakdown_keys(self):
        """The scorer must return the expected penalty keys."""
        result = calculate_evidence_strength(**_base_strong_packet())

        expected_keys = {"gap_severity", "material_resolution", "critical_field"}
        assert expected_keys == set(result.penalties.keys())

        for name, info in result.penalties.items():
            assert "factor" in info, f"Penalty '{name}' missing 'factor'"
            assert "reason" in info, f"Penalty '{name}' missing 'reason'"

    def test_explanation_is_nonempty(self):
        """The result must include a non-empty explanation string."""
        result = calculate_evidence_strength(**_base_strong_packet())
        assert isinstance(result.explanation, str)
        assert len(result.explanation) > 0


# ---------------------------------------------------------------------------
# Issue-scoped test coverage
# ---------------------------------------------------------------------------


class TestIssueScopedCoverage:
    def test_issue_scope_excludes_unrequested_classes(self):
        """When explicit issue_codes are provided, test coverage should only
        score relevant test classes (e.g., no TOX penalty when TOX/OFFGAS
        are not in scope)."""
        packet = dict(
            supporting_precedents=[_make_precedent(mua_suffix="0001")],
            conflicting_precedents=[],
            test_data=[
                _make_test_data("FLAMM", "A", True),
                _make_test_data("SCC", "B", True),
            ],
            envelope=_partial_envelope(),
            conflicts=[],
            gaps=[],
            material=_resolved_material(),
            environment=_standard_environment(),
            issue_codes=["FLAM", "O2_COMPAT", "SCC"],
        )
        result = calculate_evidence_strength(**packet)
        detail = result.components["test_coverage"]["detail"]

        assert "FLAMM:" in detail
        assert "SCC:" in detail
        assert "TOX:" not in detail
        assert "CORR:" not in detail
        assert "TVS:" not in detail
        assert "FS:" not in detail

    def test_default_scope_still_uses_all_classes_when_unspecified(self):
        """Without explicit issue_codes, legacy six-class scoring remains."""
        packet = dict(
            supporting_precedents=[_make_precedent(mua_suffix="0002")],
            conflicting_precedents=[],
            test_data=[_make_test_data("FLAMM", "A", True)],
            envelope=_partial_envelope(),
            conflicts=[],
            gaps=[],
            material=_resolved_material(),
            environment=_standard_environment(),
        )
        result = calculate_evidence_strength(**packet)
        detail = result.components["test_coverage"]["detail"]

        assert "FLAMM:" in detail
        assert "TOX:" in detail
        assert "SCC:" in detail
