#!/usr/bin/env python3
"""
Test Module: Schema Validation Automation (schema_validation.py)
Purpose: AC-R7 drift detection tests -- 3/3 planted drift scenarios.

BoundState AI 2026
Compliance: SWE-032, NASA-STD-8739.8B

Tests cover:
    - Identical schemas -> passed, no changes
    - New field detected -> WARN severity, still passes
    - Removed field detected -> FAIL severity, does not pass
    - Type change detected -> FAIL severity, does not pass
    - Name change detected -> WARN severity (fuzzy match)
    - requires_faiss_rebuild on REMOVED_FIELD
    - requires_regression on any change
    - 3 parametrised planted drift scenarios for AC-R7
"""

import sys
sys.path.insert(0, r"C:\BoundState")

import pytest

from mira_v4.models import SchemaChangeType
from mira_v4.schema_validation import SchemaValidator


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

_BASELINE_SCHEMA = {
    "material_name": "string",
    "tensile_strength": "float",
    "yield_strength": "float",
    "elongation": "float",
    "density": "float",
    "thermal_conductivity": "float",
    "test_temperature": "float",
    "test_pressure": "float",
    "flammability_rating": "string",
}

_VALIDATOR = SchemaValidator()


# ===========================================================================
# 1. Identical schemas
# ===========================================================================


class TestIdenticalSchemas:
    """No changes when expected and live are identical."""

    def test_identical_schemas_pass(self):
        """Identical schemas -> passed=True, no changes."""
        result = _VALIDATOR.compare_schemas(
            expected_schema=_BASELINE_SCHEMA,
            live_schema=dict(_BASELINE_SCHEMA),
            schema_version="1.0.0",
        )
        assert result.passed is True
        assert len(result.changes) == 0
        assert result.requires_faiss_rebuild is False
        assert result.requires_regression is False


# ===========================================================================
# 2. New field (WARN, still passes)
# ===========================================================================


class TestNewField:
    """A field present in live but not expected -> WARN."""

    def test_new_field_detected(self):
        """New field 'hardness' in live -> WARN, passed still True."""
        live = dict(_BASELINE_SCHEMA)
        live["hardness"] = "float"

        result = _VALIDATOR.compare_schemas(
            expected_schema=_BASELINE_SCHEMA,
            live_schema=live,
            schema_version="1.1.0",
        )
        assert result.passed is True  # WARN does not fail
        assert any(
            c.change_type == SchemaChangeType.NEW_FIELD and c.field_name == "hardness"
            for c in result.changes
        )
        # WARN severity
        new_field_changes = [
            c for c in result.changes if c.change_type == SchemaChangeType.NEW_FIELD
        ]
        assert all(c.severity == "WARN" for c in new_field_changes)


# ===========================================================================
# 3. Removed field (FAIL, does not pass)
# ===========================================================================


class TestRemovedField:
    """A field present in expected but missing from live -> FAIL."""

    def test_removed_field_detected(self):
        """Removed field 'flammability_rating' -> FAIL, passed=False."""
        live = dict(_BASELINE_SCHEMA)
        del live["flammability_rating"]

        result = _VALIDATOR.compare_schemas(
            expected_schema=_BASELINE_SCHEMA,
            live_schema=live,
            schema_version="1.2.0",
        )
        assert result.passed is False
        assert any(
            c.change_type == SchemaChangeType.REMOVED_FIELD
            and c.field_name == "flammability_rating"
            for c in result.changes
        )
        removed_changes = [
            c for c in result.changes if c.change_type == SchemaChangeType.REMOVED_FIELD
        ]
        assert all(c.severity == "FAIL" for c in removed_changes)


# ===========================================================================
# 4. Type change (FAIL, does not pass)
# ===========================================================================


class TestTypeChange:
    """A field exists in both but type differs -> FAIL."""

    def test_type_change_detected(self):
        """tensile_strength type float -> string -> FAIL, passed=False."""
        live = dict(_BASELINE_SCHEMA)
        live["tensile_strength"] = "string"

        result = _VALIDATOR.compare_schemas(
            expected_schema=_BASELINE_SCHEMA,
            live_schema=live,
            schema_version="1.3.0",
        )
        assert result.passed is False
        assert any(
            c.change_type == SchemaChangeType.TYPE_CHANGE
            and c.field_name == "tensile_strength"
            and c.old_value == "float"
            and c.new_value == "string"
            for c in result.changes
        )


# ===========================================================================
# 5. Name change (WARN, fuzzy match)
# ===========================================================================


class TestNameChange:
    """A field is removed and a similar field appears -> NAME_CHANGE (WARN)."""

    def test_name_change_detected(self):
        """'tensile_strength' removed, 'tensile_strenght' added -> NAME_CHANGE WARN.
        The two names share high character-level similarity (> 0.80)."""
        live = dict(_BASELINE_SCHEMA)
        del live["tensile_strength"]
        live["tensile_strenght"] = "float"  # plausible typo rename

        result = _VALIDATOR.compare_schemas(
            expected_schema=_BASELINE_SCHEMA,
            live_schema=live,
            schema_version="1.4.0",
        )
        # Should be classified as NAME_CHANGE, not REMOVED + NEW
        name_changes = [
            c for c in result.changes if c.change_type == SchemaChangeType.NAME_CHANGE
        ]
        assert len(name_changes) >= 1
        nc = name_changes[0]
        assert nc.severity == "WARN"
        assert nc.old_value == "tensile_strength"
        assert nc.new_value == "tensile_strenght"
        # NAME_CHANGE is WARN, so passed should still be True
        assert result.passed is True


# ===========================================================================
# 6. requires_faiss_rebuild
# ===========================================================================


class TestRequiresFaissRebuild:
    """FAISS rebuild required on REMOVED_FIELD or TYPE_CHANGE."""

    def test_requires_faiss_rebuild_on_removed_field(self):
        live = dict(_BASELINE_SCHEMA)
        del live["density"]

        result = _VALIDATOR.compare_schemas(
            expected_schema=_BASELINE_SCHEMA,
            live_schema=live,
            schema_version="1.5.0",
        )
        assert result.requires_faiss_rebuild is True


# ===========================================================================
# 7. requires_regression on any change
# ===========================================================================


class TestRequiresRegression:
    """Any change at all triggers the 50-query regression flag."""

    def test_requires_regression_on_any_change(self):
        """Even a WARN-only change (new field) triggers regression."""
        live = dict(_BASELINE_SCHEMA)
        live["new_metric"] = "float"

        result = _VALIDATOR.compare_schemas(
            expected_schema=_BASELINE_SCHEMA,
            live_schema=live,
            schema_version="1.6.0",
        )
        assert result.requires_regression is True


# ===========================================================================
# 8. AC-R7 planted drift scenarios (3 / 3 parametrised)
# ===========================================================================


_DRIFT_SCENARIOS = [
    pytest.param(
        # Scenario 1: A field is removed from live schema
        {
            "live_mutation": lambda s: {k: v for k, v in s.items() if k != "elongation"},
            "expected_change_type": SchemaChangeType.REMOVED_FIELD,
            "expected_field": "elongation",
            "expected_passed": False,
            "expected_faiss_rebuild": True,
        },
        id="drift_1_removed_field_elongation",
    ),
    pytest.param(
        # Scenario 2: A field type changes from float to string
        {
            "live_mutation": lambda s: {**s, "yield_strength": "string"},
            "expected_change_type": SchemaChangeType.TYPE_CHANGE,
            "expected_field": "yield_strength",
            "expected_passed": False,
            "expected_faiss_rebuild": True,
        },
        id="drift_2_type_change_yield_strength",
    ),
    pytest.param(
        # Scenario 3: A field is renamed (old removed, similar new added)
        {
            "live_mutation": lambda s: {
                **{k: v for k, v in s.items() if k != "thermal_conductivity"},
                "thermal_conductivty": "float",  # plausible typo
            },
            "expected_change_type": SchemaChangeType.NAME_CHANGE,
            "expected_field": "thermal_conductivity",
            "expected_passed": True,  # NAME_CHANGE is WARN
            "expected_faiss_rebuild": False,
        },
        id="drift_3_name_change_thermal_conductivity",
    ),
]


class TestPlantedDriftScenarios:
    """AC-R7: 3/3 planted drift detection scenarios."""

    @pytest.mark.parametrize("scenario", _DRIFT_SCENARIOS)
    def test_planted_drift(self, scenario):
        """Each drift scenario must detect the expected change type and flags."""
        live_mutation = scenario["live_mutation"]
        live = live_mutation(dict(_BASELINE_SCHEMA))

        result = _VALIDATOR.compare_schemas(
            expected_schema=_BASELINE_SCHEMA,
            live_schema=live,
            schema_version="drift-test",
        )

        # Correct change type detected for the expected field
        matching = [
            c for c in result.changes
            if c.change_type == scenario["expected_change_type"]
            and c.field_name == scenario["expected_field"]
        ]
        assert len(matching) >= 1, (
            f"Expected {scenario['expected_change_type'].value} for field "
            f"'{scenario['expected_field']}' but found changes: "
            f"{[(c.field_name, c.change_type.value) for c in result.changes]}"
        )

        # Correct passed flag
        assert result.passed is scenario["expected_passed"], (
            f"Expected passed={scenario['expected_passed']} "
            f"but got passed={result.passed}"
        )

        # Correct FAISS rebuild flag
        assert result.requires_faiss_rebuild is scenario["expected_faiss_rebuild"], (
            f"Expected requires_faiss_rebuild={scenario['expected_faiss_rebuild']} "
            f"but got {result.requires_faiss_rebuild}"
        )

        # All drift scenarios must trigger regression
        assert result.requires_regression is True
