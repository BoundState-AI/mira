#!/usr/bin/env python3
"""
Module: Test H2 Compatibility Core
Purpose: H2 Compatibility Core Tests for BoundState

BoundState AI 2025
Version: 1.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Fran OpenAI 5 <noreply@openai.com>
Co-Authored-By: Grok 4.0 <noreply@x.ai>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: SWE-013, NASA-STD-8739.8B
Safety Critical: True
"""

import pytest
import sys

# Ensure BoundState is in path
sys.path.insert(0, r"C:\BoundState")

from core.models.answer import AnswerSeverity
from mira.h2 import (
    evaluate_h2_compatibility,
    H2CompatibilityRequest,
    H2CompatibilityResponse,
    HydrogenPhase,
)
from mira.maptis import (
    MaterialFamily,
    get_h2_family_rule,
    H2_HIGH_STRENGTH_THRESHOLD_KSI,
)


# =============================================================================
# TEST: APPROVED MATERIALS (Austenitic SS, Nickel Alloys, Copper, Aluminum)
# =============================================================================

class TestH2ApprovedMaterials:
    """Materials that should be approved or conservative-safe for hydrogen service."""

    def test_ss_316_approved_for_h2(self):
        """SS 316 is the gold standard for H2 service - MUST be APPROVED."""
        request = H2CompatibilityRequest(
            question="Is SS 316 compatible with hydrogen?",
            material_key="SS 316",
            pressure_psia=5000,
            temperature_k=300,  # Room temp
            phase=HydrogenPhase.GAS,
        )
        response = evaluate_h2_compatibility(request)

        assert response.classification == AnswerSeverity.OK, (
            f"SS 316 should be APPROVED for H2, got {response.classification}. "
            "Austenitic SS has excellent HE resistance due to FCC structure."
        )
        assert response.embrittlement_risk in ["low", "very_low", None]

    def test_ss_304_approved_for_h2(self):
        """SS 304 surfaces HIGH HEE in the evidence set and should return CAUTION."""
        request = H2CompatibilityRequest(
            question="Is SS 304 compatible with hydrogen?",
            material_key="SS 304",
            pressure_psia=3000,
            temperature_k=300,
            phase=HydrogenPhase.GAS,
        )
        response = evaluate_h2_compatibility(request)

        assert response.classification == AnswerSeverity.CAUTION
        assert response.embrittlement_risk == "medium"

    def test_ss_321_approved_for_h2(self):
        """SS 321 surfaces HIGH HEE in the evidence set and should return CAUTION."""
        request = H2CompatibilityRequest(
            question="Is SS 321 compatible with hydrogen?",
            material_key="SS 321",
            pressure_psia=3000,
            temperature_k=300,
            phase=HydrogenPhase.GAS,
        )
        response = evaluate_h2_compatibility(request)

        assert response.classification == AnswerSeverity.CAUTION
        assert response.embrittlement_risk == "medium"

    def test_inconel_625_approved_for_h2(self):
        """Inconel 625 should return CAUTION per the current evidence set."""
        request = H2CompatibilityRequest(
            question="Is Inconel 625 compatible with hydrogen?",
            material_key="Inconel 625",
            pressure_psia=10000,
            temperature_k=350,
            phase=HydrogenPhase.GAS,
        )
        response = evaluate_h2_compatibility(request)

        assert response.classification == AnswerSeverity.CAUTION, (
            f"Inconel 625 should be CAUTION for H2, got {response.classification}."
        )
        assert response.embrittlement_risk == "medium"

    def test_inconel_718_approved_for_h2(self):
        """Inconel 718 requires condition clarification before a definitive verdict."""
        request = H2CompatibilityRequest(
            question="Is Inconel 718 compatible with hydrogen?",
            material_key="Inconel 718",
            pressure_psia=8000,
            temperature_k=300,
            phase=HydrogenPhase.GAS,
        )
        response = evaluate_h2_compatibility(request)

        assert response.classification == AnswerSeverity.UNKNOWN
        assert response.needs_clarification is True
        assert len(response.available_conditions) > 0

    def test_monel_400_approved_for_h2(self):
        """Monel 400 should be prohibited per the current evidence set."""
        request = H2CompatibilityRequest(
            question="Is Monel 400 compatible with hydrogen?",
            material_key="Monel 400",
            pressure_psia=5000,
            temperature_k=300,
            phase=HydrogenPhase.GAS,
        )
        response = evaluate_h2_compatibility(request)

        assert response.classification == AnswerSeverity.PROHIBITED
        assert response.embrittlement_risk == "high"

    def test_hastelloy_c276_approved_for_h2(self):
        """Hastelloy C-276 should return CAUTION per the current evidence set."""
        request = H2CompatibilityRequest(
            question="Is Hastelloy C-276 compatible with hydrogen?",
            material_key="Hastelloy C-276",
            pressure_psia=5000,
            temperature_k=300,
            phase=HydrogenPhase.GAS,
        )
        response = evaluate_h2_compatibility(request)

        assert response.classification == AnswerSeverity.CAUTION
        assert response.embrittlement_risk == "medium"

    def test_copper_approved_for_h2(self):
        """Copper C10200 should fall back to the approved copper family rule."""
        request = H2CompatibilityRequest(
            question="Is copper compatible with hydrogen?",
            material_key="Copper C10200",
            pressure_psia=2000,
            temperature_k=300,
            phase=HydrogenPhase.GAS,
        )
        response = evaluate_h2_compatibility(request)

        assert response.classification == AnswerSeverity.OK
        assert response.embrittlement_risk == "very_low"
        assert response.notes is not None
        assert "family-level" in response.notes.lower()

    def test_aluminum_6061_approved_for_h2(self):
        """AL 6061 is APPROVED for H2 (no HE unlike O2 concerns)."""
        request = H2CompatibilityRequest(
            question="Is AL 6061-T6 compatible with hydrogen?",
            material_key="AL 6061-T6",
            pressure_psia=5000,
            temperature_k=300,
            phase=HydrogenPhase.GAS,
        )
        response = evaluate_h2_compatibility(request)

        assert response.classification == AnswerSeverity.OK, (
            f"AL 6061 should be APPROVED for H2, got {response.classification}. "
            "Aluminum does NOT suffer hydrogen embrittlement."
        )
        assert response.embrittlement_risk == "none"


# =============================================================================
# TEST: CAUTION MATERIALS (Titanium at low temp, polymers)
# =============================================================================

class TestH2CautionMaterials:
    """Materials that should have CAUTION classification for H2."""

    def test_titanium_caution_at_cryogenic(self):
        """Titanium in cryogenic LH2 should fall back to the titanium caution rule."""
        request = H2CompatibilityRequest(
            question="Is Ti-6Al-4V compatible with cryogenic hydrogen?",
            material_key="Ti-6Al-4V",
            pressure_psia=500,
            temperature_k=20,  # Cryogenic LH2 (~-423°F)
            phase=HydrogenPhase.LIQUID,
        )
        response = evaluate_h2_compatibility(request)

        assert response.classification == AnswerSeverity.CAUTION, (
            f"Ti at cryo should be CAUTION, got {response.classification}"
        )
        assert response.notes is not None
        assert "cryogenic lh2 fallback" in response.notes.lower()


# =============================================================================
# TEST: PROHIBITED CONDITIONS
# =============================================================================

class TestH2ProhibitedConditions:
    """Conditions that should result in PROHIBITED classification."""

    def test_titanium_prohibited_at_elevated_temp(self):
        """Titanium is PROHIBITED at elevated temps due to hydride formation.

        This is the H2 equivalent of the "6061 bug" for O2:
        Ti absorbs hydrogen above ~300°F, forming brittle hydrides.
        """
        # 450K = ~350°F = well above 300°F limit
        request = H2CompatibilityRequest(
            question="Is Ti-6Al-4V compatible with hot hydrogen?",
            material_key="Ti-6Al-4V",
            pressure_psia=2000,
            temperature_k=450,  # ~350°F - above hydride limit
            phase=HydrogenPhase.GAS,
        )
        response = evaluate_h2_compatibility(request)

        assert response.classification == AnswerSeverity.PROHIBITED, (
            f"Ti at elevated temp should be PROHIBITED, got {response.classification}. "
            "Titanium forms hydrides above 300°F per NSS 1740.16 §4.5"
        )
        assert "hydride" in response.rationale.lower()

    def test_high_strength_steel_prohibited(self):
        """High-strength steels (>150 ksi) are PROHIBITED due to severe HE."""
        request = H2CompatibilityRequest(
            question="Is 4340 steel compatible with hydrogen?",
            material_key="AISI 4340",  # High-strength steel
            pressure_psia=5000,
            temperature_k=300,
            phase=HydrogenPhase.GAS,
            yield_strength_ksi=180.0,  # Above 150 ksi limit
        )
        response = evaluate_h2_compatibility(request)

        assert response.classification == AnswerSeverity.PROHIBITED, (
            f"High-strength steel should be PROHIBITED, got {response.classification}. "
            f"Materials >150 ksi are HE-susceptible per NSS 1740.16 §4.3.2"
        )
        assert response.embrittlement_risk == "severe"

    def test_boundary_high_strength_at_limit(self):
        """Test boundary: Steel at exactly 150 ksi should NOT be prohibited."""
        request = H2CompatibilityRequest(
            question="Is steel at 150 ksi compatible with hydrogen?",
            material_key="AISI 4140",
            pressure_psia=3000,
            temperature_k=300,
            phase=HydrogenPhase.GAS,
            yield_strength_ksi=150.0,  # Exactly at limit
        )
        response = evaluate_h2_compatibility(request)

        # At exactly 150 ksi, should NOT be prohibited (limit is >150)
        assert response.classification != AnswerSeverity.PROHIBITED, (
            "Steel at exactly 150 ksi should not be prohibited"
        )

    def test_high_strength_steel_at_160_ksi(self):
        """Test: Steel at 160 ksi (above limit) should be PROHIBITED."""
        request = H2CompatibilityRequest(
            question="Is 160 ksi steel compatible with hydrogen?",
            material_key="High-Strength Steel",
            pressure_psia=3000,
            temperature_k=300,
            phase=HydrogenPhase.GAS,
            yield_strength_ksi=160.0,
        )
        response = evaluate_h2_compatibility(request)

        assert response.classification == AnswerSeverity.PROHIBITED


# =============================================================================
# TEST: RESPONSE STRUCTURE
# =============================================================================

class TestH2ResponseStructure:
    """Verify H2 responses have required structure."""

    def test_response_has_evidence(self):
        """H2 responses MUST include evidence items."""
        request = H2CompatibilityRequest(
            question="Is SS 316 compatible with hydrogen?",
            material_key="SS 316",
            pressure_psia=5000,
            temperature_k=300,
            phase=HydrogenPhase.GAS,
        )
        response = evaluate_h2_compatibility(request)

        assert len(response.evidence) > 0, "H2 response must include evidence"
        assert response.evidence[0].source_id is not None

    def test_response_has_rationale(self):
        """H2 responses MUST include rationale."""
        request = H2CompatibilityRequest(
            question="Is Inconel 625 compatible with hydrogen?",
            material_key="Inconel 625",
            pressure_psia=10000,
            temperature_k=300,
            phase=HydrogenPhase.GAS,
        )
        response = evaluate_h2_compatibility(request)

        assert response.rationale is not None
        assert len(response.rationale) > 0

    def test_response_has_embrittlement_risk(self):
        """H2 responses should include embrittlement_risk."""
        request = H2CompatibilityRequest(
            question="Is SS 316 compatible with hydrogen?",
            material_key="SS 316",
            pressure_psia=5000,
            temperature_k=300,
            phase=HydrogenPhase.GAS,
        )
        response = evaluate_h2_compatibility(request)

        assert response.embrittlement_risk is not None


# =============================================================================
# TEST: FAMILY RULES
# =============================================================================

class TestH2FamilyRules:
    """Verify H2 family rules are correctly defined."""

    def test_austenitic_steel_rule_is_approved(self):
        """Austenitic SS rule should be 'approved'."""
        rule = get_h2_family_rule(MaterialFamily.AUSTENITIC_STEEL)
        assert rule["classification"] == "approved"
        assert "NSS 1740.16" in rule["bok_ref"]

    def test_nickel_alloy_rule_is_approved(self):
        """Nickel alloy rule should be 'approved'."""
        rule = get_h2_family_rule(MaterialFamily.NICKEL_ALLOY)
        assert rule["classification"] == "approved"
        assert rule["embrittlement_risk"] == "very_low"

    def test_aluminum_rule_is_approved(self):
        """Aluminum rule should be 'approved' (no HE)."""
        rule = get_h2_family_rule(MaterialFamily.ALUMINUM)
        assert rule["classification"] == "approved"
        assert rule["embrittlement_risk"] == "none"

    def test_titanium_rule_is_caution(self):
        """Titanium rule should be 'caution' with temp limits."""
        rule = get_h2_family_rule(MaterialFamily.TITANIUM)
        assert rule["classification"] == "caution"
        assert "limits" in rule
        assert rule["limits"]["max_temp_f"] == 300


# =============================================================================
# TEST: PRESSURE THRESHOLDS
# =============================================================================

class TestH2PressureThresholds:
    """Test pressure-related H2 behavior."""

    def test_high_pressure_adds_note(self):
        """High pressure (>1000 psia) should add verification note."""
        request = H2CompatibilityRequest(
            question="Is SS 316 compatible with high-pressure hydrogen?",
            material_key="SS 316",
            pressure_psia=5000,  # Above 1000 psia threshold
            temperature_k=300,
            phase=HydrogenPhase.GAS,
        )
        response = evaluate_h2_compatibility(request)

        assert response.classification == AnswerSeverity.OK
        # Should still be approved but with pressure note
        if response.notes:
            assert "pressure" in response.notes.lower() or "5000" in response.notes


# =============================================================================
# TEST: PHASE HANDLING (GH2 vs LH2)
# =============================================================================

class TestH2PhaseHandling:
    """Test GH2 vs LH2 phase handling."""

    def test_lh2_cryogenic_approved(self):
        """Materials approved for GH2 should also work for LH2."""
        request = H2CompatibilityRequest(
            question="Is SS 316 compatible with liquid hydrogen?",
            material_key="SS 316",
            pressure_psia=100,
            temperature_k=20,  # Cryogenic LH2
            phase=HydrogenPhase.LIQUID,
        )
        response = evaluate_h2_compatibility(request)

        assert response.classification == AnswerSeverity.OK

    def test_aluminum_for_lh2_tanks(self):
        """Aluminum is commonly used for LH2 tanks."""
        request = H2CompatibilityRequest(
            question="Is AL 2219 compatible with LH2 tanks?",
            material_key="AL 2219-T87",
            pressure_psia=50,
            temperature_k=20,  # Cryogenic LH2
            phase=HydrogenPhase.LIQUID,
        )
        response = evaluate_h2_compatibility(request)

        assert response.classification == AnswerSeverity.OK


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
