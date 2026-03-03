"""Tests for MUA v7 conflict detection.

The conflict detector examines all collected evidence for a material-use
scenario and identifies contradictions between sources.  Conflicts are
classified as:

  HARD -- Direct contradiction (e.g. APPROVED vs REJECTED, or a D-rating
          in MAPTIS paired with an APPROVED precedent).  These require
          explicit human disposition.
  SOFT -- Divergent but not directly contradictory signals (e.g.
          APPROVED vs CONDITIONAL within-supporting, or a C-rating
          paired with an APPROVED precedent).

Each conflict must carry a human-readable description that uses
hedging language ("may", "appears to") rather than definitive assertions.
"""

import pytest

from mira.mua.v7.conflict_detector import detect_conflicts
from mira.mua.v7.models import (
    ConflictSeverity,
    DeterminationStatus,
    PrecedentMatch,
    TestDataRecord,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def approved_precedent():
    """A precedent MUA where the material was approved."""
    return PrecedentMatch(
        mua_number="MUA-MSFC-2023-0042",
        material_designation="6061-T6",
        determination=DeterminationStatus.APPROVED,
        environment_description="Cabin rack brackets, SLS Block 1B",
        relevance_score=0.9,
    )


@pytest.fixture
def rejected_precedent():
    """A precedent MUA where the same material was rejected in an
    overlapping environment (shares keywords with approved_precedent)."""
    return PrecedentMatch(
        mua_number="MUA-MSFC-2022-0118",
        material_designation="6061-T6",
        determination=DeterminationStatus.REJECTED,
        environment_description="Cabin payload bay application, SLS Block 1B",
        relevance_score=0.85,
    )


@pytest.fixture
def conditional_precedent():
    """A supporting precedent with CONDITIONAL determination."""
    return PrecedentMatch(
        mua_number="MUA-MSFC-2023-0099",
        material_designation="6061-T6",
        determination=DeterminationStatus.CONDITIONAL,
        environment_description="Cabin rack brackets, SLS Block 2",
        relevance_score=0.75,
    )


@pytest.fixture
def maptis_d_rating():
    """A MAPTIS record showing a D (fail) flammability rating."""
    return TestDataRecord(
        test_class="FLAMM",
        rating="D",
        report_number="54821",
        is_current=True,
    )


@pytest.fixture
def maptis_a_rating():
    """A MAPTIS record showing an A (best) flammability rating."""
    return TestDataRecord(
        test_class="FLAMM",
        rating="A",
        report_number="61203",
        is_current=True,
    )


@pytest.fixture
def maptis_c_rating():
    """A MAPTIS record with a C (ambiguous) rating."""
    return TestDataRecord(
        test_class="FLAMM",
        rating="C",
        report_number="58392",
        is_current=True,
    )


@pytest.fixture
def same_family_approved():
    """A precedent with a same-family material (6061-T651) that was approved."""
    return PrecedentMatch(
        mua_number="MUA-MSFC-2023-0200",
        material_designation="6061-T651",
        material_family="aluminum",
        determination=DeterminationStatus.APPROVED,
        environment_description="Structural bracket, SLS",
        relevance_score=0.7,
    )


@pytest.fixture
def same_family_rejected():
    """A precedent with a same-family material (6061-T4) that was rejected."""
    return PrecedentMatch(
        mua_number="MUA-MSFC-2022-0300",
        material_designation="6061-T4",
        material_family="aluminum",
        determination=DeterminationStatus.REJECTED,
        environment_description="Panel mount, SLS",
        relevance_score=0.6,
    )


# ---------------------------------------------------------------------------
# No conflicts
# ---------------------------------------------------------------------------


class TestNoConflicts:
    def test_all_evidence_agrees(self, approved_precedent, maptis_a_rating):
        """When all evidence points in the same direction (approved
        precedent, A-rated test), the detector should return an empty
        conflict list."""
        supporting = [approved_precedent]
        conflicting = []
        test_data = [maptis_a_rating]
        conflicts = detect_conflicts(supporting, conflicting, test_data)

        assert conflicts == []

    def test_empty_inputs(self):
        """No evidence at all should produce no conflicts."""
        conflicts = detect_conflicts([], [], [])
        assert conflicts == []


# ---------------------------------------------------------------------------
# Hard conflicts
# ---------------------------------------------------------------------------


class TestHardConflicts:
    def test_supporting_vs_conflicting(
        self, approved_precedent, rejected_precedent
    ):
        """An APPROVED supporting and a REJECTED conflicting precedent
        with overlapping environments constitute a HARD conflict."""
        supporting = [approved_precedent]
        conflicting = [rejected_precedent]
        conflicts = detect_conflicts(supporting, conflicting, [])

        assert len(conflicts) >= 1
        hard = [c for c in conflicts if c.severity == ConflictSeverity.HARD]
        assert len(hard) >= 1

    def test_maptis_d_vs_approved_precedent(
        self, approved_precedent, maptis_d_rating
    ):
        """A D-rating in MAPTIS combined with an APPROVED precedent is a
        HARD conflict: the test data says the material failed, but a
        prior MUA approved it."""
        supporting = [approved_precedent]
        conflicting = []
        test_data = [maptis_d_rating]
        conflicts = detect_conflicts(supporting, conflicting, test_data)

        assert len(conflicts) >= 1
        hard = [c for c in conflicts if c.severity == ConflictSeverity.HARD]
        assert len(hard) >= 1

    def test_hard_conflicts_sorted_first(
        self, approved_precedent, rejected_precedent, maptis_c_rating
    ):
        """Conflicts should be sorted with HARD first."""
        supporting = [approved_precedent]
        conflicting = [rejected_precedent]
        # C-rating + APPROVED should be SOFT, APPROVED vs REJECTED should be HARD
        test_data = [maptis_c_rating]
        conflicts = detect_conflicts(supporting, conflicting, test_data)

        if len(conflicts) >= 2:
            # First conflict should be HARD
            assert conflicts[0].severity == ConflictSeverity.HARD


# ---------------------------------------------------------------------------
# Soft conflicts
# ---------------------------------------------------------------------------


class TestSoftConflicts:
    def test_approved_vs_conditional_within_supporting(
        self, approved_precedent, conditional_precedent
    ):
        """APPROVED vs CONDITIONAL within the supporting set should be
        detected as a SOFT conflict."""
        supporting = [approved_precedent, conditional_precedent]
        conflicting = []
        test_data = []
        conflicts = detect_conflicts(supporting, conflicting, test_data)

        assert len(conflicts) >= 1
        soft = [c for c in conflicts if c.severity == ConflictSeverity.SOFT]
        assert len(soft) >= 1

    def test_same_family_contradictory_outcomes(
        self, same_family_approved, same_family_rejected
    ):
        """Materials in the same family with contradictory determinations
        should produce a SOFT conflict."""
        supporting = [same_family_approved]
        conflicting = [same_family_rejected]
        test_data = []
        conflicts = detect_conflicts(supporting, conflicting, test_data)

        # Should have at least one SOFT for same-family contradiction
        # (may also have a HARD for supporting-vs-conflicting)
        soft = [c for c in conflicts if c.severity == ConflictSeverity.SOFT]
        assert len(soft) >= 1

    def test_maptis_c_rating_vs_approved(
        self, approved_precedent, maptis_c_rating
    ):
        """A C-rating (ambiguous) paired with an APPROVED precedent should
        be detected as a SOFT conflict."""
        supporting = [approved_precedent]
        conflicting = []
        test_data = [maptis_c_rating]
        conflicts = detect_conflicts(supporting, conflicting, test_data)

        assert len(conflicts) >= 1
        soft = [c for c in conflicts if c.severity == ConflictSeverity.SOFT]
        assert len(soft) >= 1


# ---------------------------------------------------------------------------
# Description quality
# ---------------------------------------------------------------------------


class TestDescriptionQuality:
    def test_conflict_uses_hedging_language(
        self, approved_precedent, rejected_precedent
    ):
        """Conflict descriptions must use hedging language ('may',
        'appears', 'could', 'suggests', 'indicates') rather than
        definitive assertions."""
        supporting = [approved_precedent]
        conflicting = [rejected_precedent]
        conflicts = detect_conflicts(supporting, conflicting, [])

        assert len(conflicts) >= 1
        desc = conflicts[0].description.lower()
        hedging_words = ["may", "appears", "could", "suggests", "indicates"]
        assert any(word in desc for word in hedging_words), (
            f"Conflict description lacks hedging language: "
            f"'{conflicts[0].description}'"
        )

    def test_recommendation_is_nonempty(
        self, approved_precedent, rejected_precedent
    ):
        """Each conflict must have a non-empty recommendation."""
        supporting = [approved_precedent]
        conflicting = [rejected_precedent]
        conflicts = detect_conflicts(supporting, conflicting, [])

        assert len(conflicts) >= 1
        for c in conflicts:
            assert isinstance(c.recommendation, str)
            assert len(c.recommendation) > 0

    def test_conflict_id_format(
        self, approved_precedent, rejected_precedent
    ):
        """Each conflict must have an ID matching the CFT-XXXXXXXXXXXX format."""
        supporting = [approved_precedent]
        conflicting = [rejected_precedent]
        conflicts = detect_conflicts(supporting, conflicting, [])

        assert len(conflicts) >= 1
        for c in conflicts:
            assert c.conflict_id.startswith("CFT-")
            assert len(c.conflict_id) == 16  # "CFT-" + 12 hex chars


# ---------------------------------------------------------------------------
# Non-overlapping environments: no false positives
# ---------------------------------------------------------------------------


class TestNonOverlappingEnvironments:
    def test_non_overlapping_environments_no_false_positive(self):
        """Precedents with completely non-overlapping environments (no
        shared keywords, one enriched O2 and one not, pressure ranges
        differing by >2x, and different materials/families) should NOT
        produce false-positive precedent-vs-precedent conflicts."""
        # Use completely different materials (different families) and
        # unique keywords with no word overlap, one enriched O2 and one
        # ambient, pressure ranges >2x apart.
        prec_a = PrecedentMatch(
            mua_number="MUA-MSFC-2024-0001",
            material_designation="Inconel-718",
            material_family="nickel_superalloy",
            determination=DeterminationStatus.APPROVED,
            environment_description="cryogenic turbopump assembly",
            o2_percent=30.0,  # enriched
            pressure_psia=6000.0,
            relevance_score=0.9,
        )
        prec_b = PrecedentMatch(
            mua_number="MUA-MSFC-2024-0002",
            material_designation="PTFE-GF30",
            material_family="fluoropolymer",
            determination=DeterminationStatus.REJECTED,
            environment_description="ambient habitat ventilation duct",
            o2_percent=21.0,  # not enriched
            pressure_psia=14.7,
            relevance_score=0.85,
        )
        supporting = [prec_a]
        conflicting = [prec_b]

        conflicts = detect_conflicts(supporting, conflicting, [])

        # The environment overlap heuristic should rule out a conflict
        # because there are no shared keywords, O2 ranges differ
        # (one enriched, one not), and pressure ranges differ by >2x.
        # Material families are also different so no same-family conflict.
        precedent_conflicts = [
            c for c in conflicts
            if prec_a.mua_number in (c.source_a, c.source_b)
            and prec_b.mua_number in (c.source_a, c.source_b)
        ]
        assert len(precedent_conflicts) == 0
