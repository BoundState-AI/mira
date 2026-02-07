"""Tests for MUA v7 conflict detection.

The conflict detector examines all collected evidence for a material-use
scenario and identifies contradictions between sources.  Conflicts are
classified as:

  HARD -- Direct contradiction (e.g. APPROVED vs REJECTED, or a D-rating
          in MAPTIS paired with an APPROVED precedent).  These require
          explicit human disposition.
  SOFT -- Divergent but not directly contradictory signals (e.g.
          different letter ratings that still point in the same general
          direction).

Each conflict must carry a human-readable description that uses
hedging language ("may", "appears to") rather than definitive assertions.
"""

import pytest

from mira.mua.v7.conflict_detector import (
    ConflictDetector,
    ConflictSeverity,
    EvidenceRecord,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def detector():
    return ConflictDetector()


@pytest.fixture
def approved_precedent():
    """A precedent MUA where the material was approved."""
    return EvidenceRecord(
        source="PRECEDENT",
        material="6061-T6",
        outcome="APPROVED",
        rating=None,
        mua_number="MUA-MSFC-2023-0042",
        detail="Approved for cabin rack brackets, SLS Block 1B",
    )


@pytest.fixture
def rejected_precedent():
    """A precedent MUA where the same material was rejected."""
    return EvidenceRecord(
        source="PRECEDENT",
        material="6061-T6",
        outcome="REJECTED",
        rating=None,
        mua_number="MUA-MSFC-2022-0118",
        detail="Rejected for O2-enriched payload bay application",
    )


@pytest.fixture
def maptis_d_rating():
    """A MAPTIS record showing a D (fail) flammability rating."""
    return EvidenceRecord(
        source="MAPTIS",
        material="6061-T6",
        outcome=None,
        rating="D",
        mua_number=None,
        detail="MAPTIS Test #54821: Upward flame propagation, D rating",
    )


@pytest.fixture
def maptis_a_rating():
    """A MAPTIS record showing an A (best) flammability rating."""
    return EvidenceRecord(
        source="MAPTIS",
        material="6061-T6",
        outcome=None,
        rating="A",
        mua_number=None,
        detail="MAPTIS Test #61203: No ignition at 14.7 psia air, A rating",
    )


@pytest.fixture
def bok_approved():
    """A Body of Knowledge (BOK) record indicating approval."""
    return EvidenceRecord(
        source="BOK",
        material="6061-T6",
        outcome="APPROVED",
        rating=None,
        mua_number=None,
        detail="BOK: Widely used in non-habitable aluminum structure",
    )


@pytest.fixture
def maptis_poor_rating():
    """A MAPTIS record with a C (poor) rating."""
    return EvidenceRecord(
        source="MAPTIS",
        material="6061-T6",
        outcome=None,
        rating="C",
        mua_number=None,
        detail="MAPTIS Test #58392: Marginal pass, C rating at 25 % O2",
    )


@pytest.fixture
def maptis_b_rating():
    """A MAPTIS record showing a B flammability rating."""
    return EvidenceRecord(
        source="MAPTIS",
        material="6061-T6",
        outcome=None,
        rating="B",
        mua_number=None,
        detail="MAPTIS Test #59001: Self-extinguishing within 6 in, B rating",
    )


# ---------------------------------------------------------------------------
# No conflicts
# ---------------------------------------------------------------------------

class TestNoConflicts:
    def test_no_conflicts(self, detector, approved_precedent, maptis_a_rating):
        """When all evidence points in the same direction (approved
        precedent, A-rated test), the detector should return an empty
        conflict list."""
        records = [approved_precedent, maptis_a_rating]
        conflicts = detector.detect(records)

        assert conflicts == []


# ---------------------------------------------------------------------------
# Hard conflicts
# ---------------------------------------------------------------------------

class TestHardConflicts:
    def test_supporting_vs_conflicting(
        self, detector, approved_precedent, rejected_precedent
    ):
        """An APPROVED and a REJECTED precedent for the same material
        constitute a HARD conflict that must be surfaced to the
        reviewer."""
        records = [approved_precedent, rejected_precedent]
        conflicts = detector.detect(records)

        assert len(conflicts) >= 1
        hard = [c for c in conflicts if c.severity == ConflictSeverity.HARD]
        assert len(hard) >= 1

    def test_maptis_vs_precedent(
        self, detector, approved_precedent, maptis_d_rating
    ):
        """A D-rating in MAPTIS combined with an APPROVED precedent is a
        HARD conflict: the test data says the material failed, but a
        prior MUA approved it (possibly under different conditions)."""
        records = [approved_precedent, maptis_d_rating]
        conflicts = detector.detect(records)

        assert len(conflicts) >= 1
        hard = [c for c in conflicts if c.severity == ConflictSeverity.HARD]
        assert len(hard) >= 1

    def test_cross_source_conflict(
        self, detector, maptis_poor_rating, bok_approved
    ):
        """When MAPTIS shows a poor (C) rating but the BOK records the
        material as approved, this cross-source disagreement should be
        detected as a conflict."""
        records = [maptis_poor_rating, bok_approved]
        conflicts = detector.detect(records)

        assert len(conflicts) >= 1


# ---------------------------------------------------------------------------
# Soft conflicts
# ---------------------------------------------------------------------------

class TestSoftConflicts:
    def test_soft_conflict(self, detector, maptis_a_rating, maptis_b_rating):
        """An A-rating and a B-rating are not contradictory (both indicate
        some level of passing), but the discrepancy is noteworthy.  This
        should be classified as a SOFT conflict."""
        records = [maptis_a_rating, maptis_b_rating]
        conflicts = detector.detect(records)

        assert len(conflicts) >= 1
        soft = [c for c in conflicts if c.severity == ConflictSeverity.SOFT]
        assert len(soft) >= 1


# ---------------------------------------------------------------------------
# Description quality
# ---------------------------------------------------------------------------

class TestDescriptionQuality:
    def test_conflict_description(
        self, detector, approved_precedent, rejected_precedent
    ):
        """Conflict descriptions must be human-readable and use hedging
        language ('may', 'appears to', 'could indicate') rather than
        definitive assertions, because the system is surfacing evidence
        -- not making the final determination."""
        records = [approved_precedent, rejected_precedent]
        conflicts = detector.detect(records)

        assert len(conflicts) >= 1
        desc = conflicts[0].description.lower()
        hedging_words = ["may", "appears", "could", "suggests", "indicates"]
        assert any(word in desc for word in hedging_words), (
            f"Conflict description lacks hedging language: '{conflicts[0].description}'"
        )
