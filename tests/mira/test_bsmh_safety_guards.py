#!/usr/bin/env python3
"""
Targeted regression tests for BSMH safety-critical guardrails.
"""

from __future__ import annotations

from mira.bsmh.bouncer import _extract_materials, heuristic_bouncer
from mira.bsmh.rules_engine import build_rule_decision
from mira.bsmh.service import _normalize_safety_context, _partition_materials_for_requested


def _material(
    *,
    designation: str,
    total_tests: int = 0,
    mua_count: int = 0,
    oxygen_compatible: bool = False,
    oxygen_rating: str = "NO_RATING",
    oxygen_rating_present: bool = False,
    fluid_compat: int = 0,
) -> dict:
    return {
        "material_key": 1,
        "designation": designation,
        "total_tests": total_tests,
        "mua_count": mua_count,
        "oxygen_compatible": oxygen_compatible,
        "oxygen_rating": oxygen_rating,
        "oxygen_rating_present": oxygen_rating_present,
        "test_counts": {"fluid_compatibility": fluid_compat},
        "latest_test_year": 2024,
    }


def test_safety_context_normalization_handles_enum_string() -> None:
    assert _normalize_safety_context("SafetyContext.OXYGEN") == "oxygen"
    assert _normalize_safety_context("SafetyContext.HYDROGEN") == "hydrogen"
    assert _normalize_safety_context("oxygen_service") == "oxygen"
    assert _normalize_safety_context(None) == "general"


def test_oxygen_without_rating_is_incompatible() -> None:
    packet = build_rule_decision(
        [
            _material(
                designation="AL 6061-T6",
                total_tests=12,
                mua_count=10,
                oxygen_compatible=False,
                oxygen_rating="NO_RATING",
                oxygen_rating_present=False,
            )
        ],
        safety_context="oxygen",
        min_evidence_rows=2,
    )
    assert packet.verdict == "INCOMPATIBLE"
    assert packet.materials[0].verdict == "INCOMPATIBLE"


def test_titanium_family_is_blocked_in_oxygen() -> None:
    packet = build_rule_decision(
        [
            _material(
                designation="TI-6AL-4V",
                total_tests=20,
                mua_count=5,
                oxygen_compatible=True,
                oxygen_rating="A_OR_B",
                oxygen_rating_present=True,
            )
        ],
        safety_context="oxygen",
        min_evidence_rows=2,
    )
    assert packet.verdict == "INCOMPATIBLE"
    assert packet.materials[0].verdict == "INCOMPATIBLE"


def test_hydrogen_requires_dedicated_signal_for_compatible() -> None:
    packet = build_rule_decision(
        [
            _material(
                designation="316L",
                total_tests=8,
                mua_count=50,
                oxygen_compatible=False,
                fluid_compat=0,
            )
        ],
        safety_context="hydrogen",
        min_evidence_rows=2,
    )
    assert packet.verdict in {"CONDITIONAL", "INSUFFICIENT_DATA"}
    assert packet.materials[0].verdict in {"CONDITIONAL", "INSUFFICIENT_DATA"}
    warning_text = " ".join(packet.materials[0].warnings).lower()
    assert "hydrogen-specific test data" in warning_text
    assert "signal" not in warning_text


def test_bouncer_extracts_comparison_materials() -> None:
    materials = _extract_materials(
        "Compare 316L and Inconel 625 for hydrogen service at -423°F."
    )
    assert "316L" in materials
    assert "Inconel 625" in materials


def test_bouncer_does_not_treat_environment_as_material() -> None:
    materials = _extract_materials("Give a conservative recommendation for high-pressure GOX use.")
    assert "GOX" not in [m.upper() for m in materials]
    assert materials == []


def test_bouncer_accepts_maptis_evidence_lookup_directive() -> None:
    result = heuristic_bouncer("List MAPTIS evidence for CRES 316L and Inconel 625 side-by-side.")
    assert result.status == "accepted"
    assert result.structured_query is not None
    materials_upper = [m.upper() for m in result.structured_query.materials]
    assert "316L" in materials_upper
    assert "INCONEL 625" in materials_upper


def test_bouncer_accepts_incomplete_hydrogen_directive() -> None:
    result = heuristic_bouncer("For 316L in hydrogen, provide verdict, confidence, and warnings only.")
    assert result.status == "accepted"
    assert result.structured_query is not None
    assert result.structured_query.intent in {"general", "lookup", "compatibility_check"}


def test_partition_primary_vs_associated_for_requested_material() -> None:
    materials = [
        {"material_key": 1, "designation": "INCONEL 718 BAR AGED"},
        {"material_key": 2, "designation": "INCONEL 718 AS CAST"},
        {"material_key": 3, "designation": "AL 6061-T6 BRAZED WITH INCONEL 718 FILLER"},
        {"material_key": 4, "designation": "INCOLOY 88 WELDED TO INCONEL 718"},
    ]
    primary, associated = _partition_materials_for_requested(materials, ["Inconel 718"])
    assert [m["material_key"] for m in primary] == [1, 2]
    assert [m["material_key"] for m in associated] == [3, 4]


def test_rule_packet_records_primary_aggregation_scope() -> None:
    packet = build_rule_decision(
        [
            _material(
                designation="INCONEL 718 BAR AGED",
                total_tests=29,
                mua_count=27,
                oxygen_compatible=True,
                oxygen_rating="A_OR_B",
                oxygen_rating_present=True,
            )
        ],
        safety_context="oxygen",
        aggregation_scope="primary_only",
        primary_material_count=1,
        associated_material_count=2,
        requested_materials=["Inconel 718"],
        missing_requested_materials=[],
    )
    assert packet.aggregation_scope == "primary_only"
    assert packet.primary_material_count == 1
    assert packet.associated_material_count == 2
    assert "aggregation_scope:primary_only" in packet.rules_applied


def test_hydrogen_requires_bok_for_compatible_when_enabled() -> None:
    packet = build_rule_decision(
        [
            _material(
                designation="INCONEL 625 BAR",
                total_tests=12,
                mua_count=20,
                oxygen_compatible=True,
                oxygen_rating="A_OR_B",
                oxygen_rating_present=True,
                fluid_compat=3,
            )
        ],
        safety_context="hydrogen",
        require_h2_bok=True,
        bok_evidence=[],
        requested_materials=["Inconel 625"],
    )
    assert packet.verdict in {"CONDITIONAL", "INSUFFICIENT_DATA"}
    assert packet.bok_context_used is False
    assert "guard:require_h2_bok_for_compatible" in packet.rules_applied


def test_confidence_uses_best_requested_material_evidence() -> None:
    materials = [
        _material(
            designation="INCONEL 625 BAR",
            total_tests=6,
            mua_count=27,
            oxygen_compatible=True,
            oxygen_rating="A_OR_B",
            oxygen_rating_present=True,
            fluid_compat=2,
        ),
        _material(
            designation="INCONEL 625 CASTING",
            total_tests=0,
            mua_count=27,
            oxygen_compatible=False,
            fluid_compat=0,
        ),
        _material(
            designation="STAINLESS STEEL 316L (CRES 316L) BAR ANNEALED",
            total_tests=5,
            mua_count=114,
            oxygen_compatible=True,
            oxygen_rating="A_OR_B",
            oxygen_rating_present=True,
            fluid_compat=1,
        ),
        _material(
            designation="STAINLESS STEEL 316L (CRES 316L) CASTING",
            total_tests=0,
            mua_count=114,
            oxygen_compatible=False,
            fluid_compat=0,
        ),
    ]
    packet = build_rule_decision(
        materials,
        safety_context="hydrogen",
        requested_materials=["316L", "Inconel 625"],
        require_h2_bok=False,
    )
    assert "confidence_aggregation:requested_best_of_family" in packet.rules_applied
    assert packet.confidence >= 0.5
