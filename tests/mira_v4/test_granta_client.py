#!/usr/bin/env python3
"""
Test Module: Dirty Data Threshold and Filter Relaxation (granta_client.py)
Purpose: AC-R3 dirty data classification tests -- 5/5 dirty data test cases.

BoundState AI 2026
Compliance: SWE-032, NASA-STD-8739.8B

Tests cover:
    - Tier classification at exact thresholds and interior points
    - Boundary testing at CLEAN/DEGRADED (10%/11%) and DEGRADED/REFUSE (30%/31%)
    - Empty-record edge case
    - Mixed-record fraction computation
    - User message generation for DEGRADED and REFUSE tiers
    - Dirty record preservation (annotate_dirty_records keeps all records)
    - Filter relaxation proposals for temperature, pressure, and absent fields
"""

import sys
sys.path.insert(0, r"C:\BoundState")

import pytest

from mira_v4.models import DirtyDataTier, EvidenceRow
from mira_v4.granta_client import DirtyDataClassifier, FilterRelaxer


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_records(total: int, dirty_count: int) -> list:
    """Build a list of EvidenceRow with the given total and dirty count."""
    records = []
    for i in range(total):
        is_dirty = i < dirty_count
        records.append(
            EvidenceRow(
                record_id=f"REC-{i:04d}",
                source="MAPTIS",
                dirty_flag=is_dirty,
                dirty_fields=["flammability"] if is_dirty else [],
            )
        )
    return records


# ===========================================================================
# 1. Tier classification -- interior points
# ===========================================================================


class TestClassifyInteriorPoints:
    """Verify classify() at representative interior values."""

    def test_classify_clean(self):
        """5% dirty -> CLEAN tier."""
        classifier = DirtyDataClassifier()
        assert classifier.classify(0.05) == DirtyDataTier.CLEAN

    def test_classify_degraded(self):
        """20% dirty -> DEGRADED tier."""
        classifier = DirtyDataClassifier()
        assert classifier.classify(0.20) == DirtyDataTier.DEGRADED

    def test_classify_refuse(self):
        """40% dirty -> REFUSE tier."""
        classifier = DirtyDataClassifier()
        assert classifier.classify(0.40) == DirtyDataTier.REFUSE


# ===========================================================================
# 2. Boundary testing -- exact transition points
# ===========================================================================


class TestClassifyBoundaries:
    """Boundary testing at tier transition thresholds.

    CLEAN  : 0 - 10%   (0.00 - 0.10 inclusive)
    DEGRADED: 11 - 30%  (0.11 - 0.30 inclusive -- note: >0.10)
    REFUSE  : > 30%     (> 0.30)
    """

    def test_classify_boundary_clean_degraded(self):
        """10% -> CLEAN, 11% -> DEGRADED."""
        classifier = DirtyDataClassifier()
        assert classifier.classify(0.10) == DirtyDataTier.CLEAN, (
            "10% (exactly at CLEAN_THRESHOLD) must be CLEAN"
        )
        assert classifier.classify(0.11) == DirtyDataTier.DEGRADED, (
            "11% (just above CLEAN_THRESHOLD) must be DEGRADED"
        )

    def test_classify_boundary_degraded_refuse(self):
        """30% -> DEGRADED, 31% -> REFUSE."""
        classifier = DirtyDataClassifier()
        assert classifier.classify(0.30) == DirtyDataTier.DEGRADED, (
            "30% (exactly at DEGRADED_THRESHOLD) must be DEGRADED"
        )
        assert classifier.classify(0.31) == DirtyDataTier.REFUSE, (
            "31% (just above DEGRADED_THRESHOLD) must be REFUSE"
        )


# ===========================================================================
# 3. compute_dirty_fraction
# ===========================================================================


class TestComputeDirtyFraction:
    """Verify fraction computation including edge cases."""

    def test_compute_dirty_fraction_no_records(self):
        """Empty record list returns 0.0 (not a division-by-zero error)."""
        classifier = DirtyDataClassifier()
        assert classifier.compute_dirty_fraction([]) == 0.0

    def test_compute_dirty_fraction_mixed_records(self):
        """3 dirty out of 10 -> 0.30."""
        classifier = DirtyDataClassifier()
        records = _make_records(total=10, dirty_count=3)
        fraction = classifier.compute_dirty_fraction(records)
        assert fraction == pytest.approx(0.30, abs=1e-9)


# ===========================================================================
# 4. classify_records -- user-facing messages
# ===========================================================================


class TestClassifyRecordsMessages:
    """Verify that classify_records generates appropriate user messages."""

    def test_classify_records_generates_user_message_degraded(self):
        """DEGRADED tier must produce a non-None user_message about incomplete results."""
        classifier = DirtyDataClassifier()
        # 3 dirty / 10 total = 30% -> DEGRADED
        records = _make_records(total=10, dirty_count=3)
        result = classifier.classify_records(records, property_name="tensile_strength")

        assert result.tier == DirtyDataTier.DEGRADED
        assert result.user_message is not None
        assert "non-typed data" in result.user_message
        assert "3" in result.user_message  # dirty count mentioned
        assert "10" in result.user_message  # total count mentioned

    def test_classify_records_generates_user_message_refuse(self):
        """REFUSE tier must produce a non-None user_message with property name."""
        classifier = DirtyDataClassifier()
        # 4 dirty / 10 total = 40% -> REFUSE
        records = _make_records(total=10, dirty_count=4)
        result = classifier.classify_records(records, property_name="flammability")

        assert result.tier == DirtyDataTier.REFUSE
        assert result.user_message is not None
        assert "flammability" in result.user_message
        assert "Manual review" in result.user_message


# ===========================================================================
# 5. annotate_dirty_records -- preservation guarantee
# ===========================================================================


class TestAnnotateDirtyRecords:
    """Dirty records are NEVER dropped -- annotated list must contain all."""

    def test_annotate_dirty_records_preserves_all(self):
        """Output length == input length. Both clean and dirty records present."""
        classifier = DirtyDataClassifier()
        records = _make_records(total=10, dirty_count=4)
        annotated = classifier.annotate_dirty_records(records)

        # Same total count
        assert len(annotated) == 10, "All records (clean + dirty) must be preserved"

        # Dirty records still flagged
        dirty_annotated = [r for r in annotated if r.dirty_flag]
        clean_annotated = [r for r in annotated if not r.dirty_flag]
        assert len(dirty_annotated) == 4
        assert len(clean_annotated) == 6

        # Verify original record IDs are all present
        original_ids = {r.record_id for r in records}
        annotated_ids = {r.record_id for r in annotated}
        assert original_ids == annotated_ids


# ===========================================================================
# 6. FilterRelaxer -- suggest_relaxations
# ===========================================================================


class TestSuggestRelaxations:
    """Verify relaxation proposals per BuildSpec Section 3.4."""

    def test_suggest_relaxations_temperature(self):
        """Temperature filter present -> proposal with 10% widening."""
        relaxer = FilterRelaxer()
        filters = {"temperature_c": 500.0}
        proposals = relaxer.suggest_relaxations(filters, zero_result_field="temperature_c")

        assert len(proposals) == 1
        p = proposals[0]
        assert p.field == "temperature_c"
        assert p.relaxation_pct == 0.10
        # Single value 500 -> range [500 - 50, 500 + 50] = [450, 550]
        assert p.relaxed_value["min"] == pytest.approx(450.0, abs=1e-4)
        assert p.relaxed_value["max"] == pytest.approx(550.0, abs=1e-4)

    def test_suggest_relaxations_pressure(self):
        """Pressure filter present -> proposal with 10% widening."""
        relaxer = FilterRelaxer()
        filters = {"pressure_kpa": 1000.0}
        proposals = relaxer.suggest_relaxations(filters, zero_result_field="pressure_kpa")

        assert len(proposals) == 1
        p = proposals[0]
        assert p.field == "pressure_kpa"
        assert p.relaxation_pct == 0.10
        assert p.relaxed_value["min"] == pytest.approx(900.0, abs=1e-4)
        assert p.relaxed_value["max"] == pytest.approx(1100.0, abs=1e-4)

    def test_suggest_relaxations_empty_when_no_rules_match(self):
        """Filters with no matching relaxation rules -> empty proposals."""
        relaxer = FilterRelaxer()
        filters = {"material_family": "Nickel Alloy"}
        proposals = relaxer.suggest_relaxations(filters, zero_result_field="material_family")

        assert proposals == []
