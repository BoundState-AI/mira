#!/usr/bin/env python3
"""
Test Module: BuildSpec Appendix A Stress Tests ST-7 through ST-12
Purpose: End-to-end stress tests exercising multiple MIRA v4 subsystems.

BoundState AI 2026
Compliance: SWE-013, SWE-032, SWE-033, NASA-STD-8739.8B, NASA-STD-6016 S4.2.1

Stress tests:
    ST-7:  Batch oxygen query with missing required fields -> REFUSE
    ST-8:  45% dirty flammability records -> REFUSE for flammability; clean records visible
    ST-9:  Identical query hash determinism; snapshot hash differs
    ST-10: Sonnet misclassification caught by intent guardrail; 0.05 penalty
    ST-11: Heritage NO veto when pressure mismatch (200 psi vs 6000 psi)
    ST-12: Heritage veto when pressure overlaps (5500 psi vs 6000 psi)
"""

import sys
sys.path.insert(0, r"C:\BoundState")

import time

import pytest

from mira_v4.models import (
    BatchGateAction,
    DirtyDataTier,
    EnvironmentSpec,
    EvidenceRow,
    HeritageVetoType,
    ParsedQuery,
    SafetyContext,
)
from mira_v4.batch_safety import BatchSafetyGate
from mira_v4.granta_client import DirtyDataClassifier
from mira_v4.heritage_veto import HeritageVetoEngine, PRESSURE_OVERLAP_FACTOR
from mira_v4.intent_guardrail import DISAGREEMENT_PENALTY, IntentGuardrail
from mira_v4.provenance import ProvenanceCalculator


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _psi_to_kpa(psi: float) -> float:
    """Convert psi to kPa (1 psi = 6.89476 kPa)."""
    return psi * 6.89476


def _make_evidence_rows(total: int, dirty_count: int, dirty_field: str = "flammability") -> list:
    """Build EvidenceRow list with specified dirty count."""
    rows = []
    for i in range(total):
        is_dirty = i < dirty_count
        rows.append(
            EvidenceRow(
                record_id=f"STRESS-REC-{i:04d}",
                source="MAPTIS",
                dirty_flag=is_dirty,
                dirty_fields=[dirty_field] if is_dirty else [],
                test_year=2023,
            )
        )
    return rows


def _make_heritage_record(
    failure_id: str,
    material_key: str,
    temperature_c: float,
    pressure_kpa: float,
    fluid_medium: str,
    description: str = "heritage failure",
) -> dict:
    """Build a heritage failure record dict."""
    return {
        "failure_id": failure_id,
        "material_key": material_key,
        "failure_environment": {
            "temperature_c": temperature_c,
            "pressure_kpa": pressure_kpa,
            "fluid_medium": fluid_medium,
        },
        "failure_description": description,
    }


# ===========================================================================
# ST-7: Batch oxygen missing fields -> REFUSE
# ===========================================================================


class TestST7BatchOxygenMissingFields:
    """ST-7: Batch query 'Can I use Inconel 718 in oxygen service?' with
    no pressure/temperature/O2%. Must REFUSE."""

    def test_ST7_batch_oxygen_missing_fields(self):
        """Oxygen context detected from query text, but pressure, temperature,
        and O2% are all missing. Batch safety gate must REFUSE."""
        gate = BatchSafetyGate()

        query = ParsedQuery(
            raw_query="Can I use Inconel 718 in oxygen service?",
            intent="compatibility_query",
            safety_context=SafetyContext.GENERAL,  # Let gate detect from text
            environment=EnvironmentSpec(),  # All fields None
            material_key="Inconel-718",
            batch_mode=True,
        )

        result = gate.check(query)

        # Gate should detect OXYGEN context from query text
        assert result.safety_context == SafetyContext.OXYGEN, (
            f"Expected OXYGEN context detected from query text, got {result.safety_context}"
        )
        # Must REFUSE because required fields are missing
        assert result.action == BatchGateAction.REFUSE, (
            f"Expected REFUSE for oxygen context with missing fields, got {result.action}"
        )
        # Missing fields should include o2_pct, pressure_kpa, temperature_c
        assert "o2_pct" in result.missing_fields
        assert "pressure_kpa" in result.missing_fields
        assert "temperature_c" in result.missing_fields


# ===========================================================================
# ST-8: 45% dirty data -> REFUSE for flammability
# ===========================================================================


class TestST8DirtyDataRefuse:
    """ST-8: Query where 45% of records have dirty flammability field.
    Must REFUSE for flammability property. Clean records still visible."""

    def test_ST8_dirty_data_refuse_45pct(self):
        """45% dirty -> REFUSE tier. Clean records remain in annotated output."""
        classifier = DirtyDataClassifier()

        # 45 dirty out of 100
        records = _make_evidence_rows(total=100, dirty_count=45, dirty_field="flammability")

        # Classify
        result = classifier.classify_records(records, property_name="flammability")

        assert result.tier == DirtyDataTier.REFUSE, (
            f"Expected REFUSE for 45% dirty, got {result.tier}"
        )
        assert result.dirty_fraction == pytest.approx(0.45, abs=1e-9)
        assert "flammability" in result.user_message

        # Clean records must still be visible after annotation
        annotated = classifier.annotate_dirty_records(records)
        assert len(annotated) == 100, "All 100 records must be preserved"
        clean_annotated = [r for r in annotated if not r.dirty_flag]
        assert len(clean_annotated) == 55, "55 clean records must remain visible"


# ===========================================================================
# ST-9: Identical query hash determinism
# ===========================================================================


class TestST9QueryHashDeterminism:
    """ST-9: Same query twice, 5 seconds apart. query_hash identical,
    snapshot_hash differs (because snapshot includes timestamp)."""

    def test_ST9_identical_query_hash_determinism(self):
        """query_hash is deterministic; snapshot_hash is NOT."""
        calc = ProvenanceCalculator()

        filters = {
            "material_family": "Nickel Alloy",
            "temperature_c": -183.0,
            "pressure_kpa": 3447.0,
            "fluid_medium": "LOX",
        }
        record_ids = ["REC-001", "REC-002", "REC-003"]
        schema_version = "1.0.0"

        # First computation
        prov1 = calc.create_provenance(
            filters=filters,
            record_ids=record_ids,
            schema_version=schema_version,
        )

        # Wait 5 seconds for timestamp difference
        time.sleep(5)

        # Second computation with identical inputs (but different timestamp)
        prov2 = calc.create_provenance(
            filters=filters,
            record_ids=record_ids,
            schema_version=schema_version,
        )

        # query_hash must be identical (deterministic)
        assert prov1.query_hash == prov2.query_hash, (
            "query_hash must be deterministic: same filters -> same hash"
        )

        # snapshot_hash must differ (includes timestamp)
        assert prov1.snapshot_hash != prov2.snapshot_hash, (
            "snapshot_hash must differ because it includes the timestamp"
        )

        # Both hashes are 64-char hex (SHA-256)
        assert len(prov1.query_hash) == 64
        assert len(prov2.snapshot_hash) == 64


# ===========================================================================
# ST-10: Sonnet misclassification caught
# ===========================================================================


class TestST10SonnetMisclassification:
    """ST-10: Sonnet classifies LOX valve query as general_search.
    Guardrail catches, uses safety-critical intent. 0.05 penalty."""

    def test_ST10_sonnet_misclassification_caught(self):
        """Guardrail must catch general_search for a LOX safety query."""
        guardrail = IntentGuardrail()

        resolved, disagreement = guardrail.validate(
            sonnet_intent="general_search",
            raw_query="What materials are compatible with LOX valve service at 600 psi?",
        )

        # Must escalate to a safety-relevant intent
        assert resolved in ("compatibility_query", "risk_query"), (
            f"Expected safety intent, got '{resolved}'"
        )

        # Must detect disagreement
        assert disagreement is not None, "Disagreement must be detected"
        assert disagreement.sonnet_intent == "general_search"
        assert disagreement.chosen_intent == resolved

        # Must apply 0.05 penalty
        assert disagreement.penalty_applied == pytest.approx(DISAGREEMENT_PENALTY)


# ===========================================================================
# ST-11: Heritage NO veto -- pressure mismatch
# ===========================================================================


class TestST11HeritageNoVeto:
    """ST-11: SS 316L in LOX at 200 psi, heritage failure at 6000 psi.
    Pressure doesn't overlap (200 << 0.8 * 6000 = 4800). NO veto."""

    def test_ST11_heritage_no_veto_pressure_mismatch(self):
        """200 psi query vs 6000 psi failure: ratio = 0.033 < 0.80. NO veto."""
        engine = HeritageVetoEngine()

        query_env = EnvironmentSpec(
            temperature_c=-183.0,
            pressure_kpa=_psi_to_kpa(200),
            fluid_medium="LOX",
        )
        heritage_records = [
            _make_heritage_record(
                failure_id="HF-ST11",
                material_key="SS-316L",
                temperature_c=-183.0,
                pressure_kpa=_psi_to_kpa(6000),
                fluid_medium="LOX",
                description="Ignition failure in LOX at 6000 psi",
            ),
        ]

        result = engine.check_heritage(
            material_key="SS-316L",
            query_env=query_env,
            heritage_records=heritage_records,
            safety_context=SafetyContext.OXYGEN,
        )

        # Verify pressure arithmetic
        threshold_kpa = PRESSURE_OVERLAP_FACTOR * _psi_to_kpa(6000)
        query_kpa = _psi_to_kpa(200)
        assert query_kpa < threshold_kpa, (
            f"Sanity: {query_kpa:.1f} kPa should be < {threshold_kpa:.1f} kPa"
        )

        # NO veto because pressure does not overlap
        assert result.vetoed is False, (
            "200 psi vs 6000 psi failure: pressure does not overlap, must NOT veto"
        )
        assert result.requires_acknowledgment is False


# ===========================================================================
# ST-12: Heritage veto -- pressure overlap
# ===========================================================================


class TestST12HeritageVetoPressureOverlap:
    """ST-12: SS 316L in LOX at 5500 psi, heritage failure at 6000 psi.
    Pressure overlaps (5500 >= 0.8 * 6000 = 4800). Veto applies,
    mandatory acknowledgment."""

    def test_ST12_heritage_veto_pressure_overlap(self):
        """5500 psi query vs 6000 psi failure: ratio = 0.917 >= 0.80. Veto."""
        engine = HeritageVetoEngine()

        query_env = EnvironmentSpec(
            temperature_c=-183.0,
            pressure_kpa=_psi_to_kpa(5500),
            fluid_medium="LOX",
        )
        heritage_records = [
            _make_heritage_record(
                failure_id="HF-ST12",
                material_key="SS-316L",
                temperature_c=-183.0,
                pressure_kpa=_psi_to_kpa(6000),
                fluid_medium="LOX",
                description="Ignition failure in LOX at 6000 psi",
            ),
        ]

        result = engine.check_heritage(
            material_key="SS-316L",
            query_env=query_env,
            heritage_records=heritage_records,
            safety_context=SafetyContext.OXYGEN,
        )

        # Verify pressure arithmetic
        threshold_kpa = PRESSURE_OVERLAP_FACTOR * _psi_to_kpa(6000)
        query_kpa = _psi_to_kpa(5500)
        assert query_kpa >= threshold_kpa, (
            f"Sanity: {query_kpa:.1f} kPa should be >= {threshold_kpa:.1f} kPa"
        )

        # Veto MUST apply
        assert result.vetoed is True, (
            "5500 psi vs 6000 psi failure: pressure overlaps, must veto"
        )
        assert result.veto_type == HeritageVetoType.SAFETY_CRITICAL
        assert result.requires_acknowledgment is True, (
            "Oxygen context with heritage veto requires mandatory acknowledgment"
        )
        assert "HF-ST12" in result.heritage_failure_ids
