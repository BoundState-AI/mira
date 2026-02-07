"""P0 safety-fix tests for the CURRENT v6 verdict consensus logic.

These tests codify the C3 (multi-record consensus) safety invariants.
The v6 bug was that the verdict engine only examined the *first* matching
record rather than the top-5, which meant a single favorable record could
mask conflicting evidence from other sources.

C3 invariant: The verdict must consider the top-5 most-relevant records
and apply appropriate penalties when those records conflict.

  - HARD conflict (COMPATIBLE vs INCOMPATIBLE): 0.4x penalty.
  - SOFT conflict (mixed letter ratings, same general direction): 0.7x.
  - Single-record fallback: when only 1 record exists, no consensus
    check is needed and no penalty applies.
"""

import pytest

from mira.mua.v6.verdict_consensus import (
    VerdictEngine,
    EvidenceRecord,
    VerdictResult,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def engine():
    return VerdictEngine()


def _record(outcome, rating="A", relevance=0.9, source="MAPTIS"):
    """Helper to create an EvidenceRecord with sensible defaults."""
    return EvidenceRecord(
        source=source,
        material="6061-T6",
        outcome=outcome,
        rating=rating,
        relevance_score=relevance,
    )


@pytest.fixture
def five_compatible():
    """Five records that all agree: COMPATIBLE with A-rating."""
    return [_record("COMPATIBLE", rating="A", relevance=0.95 - i * 0.02)
            for i in range(5)]


@pytest.fixture
def hard_conflict_set():
    """Top-5 records containing a hard conflict: 3 COMPATIBLE vs
    2 INCOMPATIBLE."""
    return [
        _record("COMPATIBLE", rating="A", relevance=0.95),
        _record("COMPATIBLE", rating="A", relevance=0.93),
        _record("COMPATIBLE", rating="B", relevance=0.90),
        _record("INCOMPATIBLE", rating="D", relevance=0.88, source="PRECEDENT"),
        _record("INCOMPATIBLE", rating="D", relevance=0.85, source="BOK"),
    ]


@pytest.fixture
def soft_conflict_set():
    """Top-5 records with mixed ratings but same general direction."""
    return [
        _record("COMPATIBLE", rating="A", relevance=0.95),
        _record("COMPATIBLE", rating="A", relevance=0.93),
        _record("COMPATIBLE", rating="B", relevance=0.90),
        _record("COMPATIBLE", rating="C", relevance=0.88),
        _record("COMPATIBLE", rating="B", relevance=0.85),
    ]


@pytest.fixture
def single_record():
    """Only one evidence record available."""
    return [_record("COMPATIBLE", rating="A", relevance=0.95)]


# ---------------------------------------------------------------------------
# C3: multi-record consensus
# ---------------------------------------------------------------------------

class TestMultiRecordConsensus:
    def test_c3_multi_record_consensus(self, engine, five_compatible):
        """The verdict engine must examine the top-5 records, not just
        the first.  When all 5 agree (COMPATIBLE, A-rated), the
        verdict should be COMPATIBLE with no penalty applied."""
        result = engine.compute_verdict(five_compatible)

        assert result.verdict == "COMPATIBLE"
        assert result.records_examined >= 5
        assert result.consensus_penalty == 1.0  # no penalty


# ---------------------------------------------------------------------------
# C3: hard conflict penalty
# ---------------------------------------------------------------------------

class TestHardConflictPenalty:
    def test_c3_hard_conflict_penalty(self, engine, hard_conflict_set):
        """When the top-5 records contain COMPATIBLE vs INCOMPATIBLE
        outcomes (a hard conflict), the verdict engine must apply a
        0.4x consensus penalty.

        This was the core C3 bug: looking only at the first record
        would return COMPATIBLE with no penalty, completely masking
        the 2 INCOMPATIBLE records."""
        result = engine.compute_verdict(hard_conflict_set)

        assert result.records_examined >= 5
        assert result.consensus_penalty == pytest.approx(0.4, abs=0.05), (
            f"Expected 0.4x hard-conflict penalty, "
            f"got {result.consensus_penalty}"
        )
        assert result.conflict_type == "HARD"


# ---------------------------------------------------------------------------
# C3: soft conflict penalty
# ---------------------------------------------------------------------------

class TestSoftConflictPenalty:
    def test_c3_soft_conflict_penalty(self, engine, soft_conflict_set):
        """When the top-5 records all say COMPATIBLE but carry mixed
        ratings (A, B, C), this is a soft conflict -- the direction is
        consistent but the strength varies.  A 0.7x penalty applies."""
        result = engine.compute_verdict(soft_conflict_set)

        assert result.records_examined >= 5
        assert result.consensus_penalty == pytest.approx(0.7, abs=0.05), (
            f"Expected 0.7x soft-conflict penalty, "
            f"got {result.consensus_penalty}"
        )
        assert result.conflict_type == "SOFT"


# ---------------------------------------------------------------------------
# Single-record fallback
# ---------------------------------------------------------------------------

class TestSingleRecordFallback:
    def test_c3_single_record_fallback(self, engine, single_record):
        """When only 1 record exists, no consensus check is possible.
        The engine should use that record directly with no penalty
        and records_examined == 1."""
        result = engine.compute_verdict(single_record)

        assert result.records_examined == 1
        assert result.consensus_penalty == 1.0  # no penalty
        assert result.conflict_type is None
