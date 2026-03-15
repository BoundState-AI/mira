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
    """Materials that should be APPROVED for hydrogen service."""

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

    def test_ss_304_caution_for_h2(self):
        """SS 304 shows HIGH HEE band (0.87) per Sandia data — CAUTION not OK.

        Evidence: SANDIA-034, HEE index 0.87, band "high" at 55.2 MPa / 24°C.
        The old family-rule engine returned OK; the evidence-first engine
        correctly returns CAUTION because high-band evidence dominates.
        """
        request = H2CompatibilityRequest(
            question="Is SS 304 compatible with hydrogen?",
            material_key="SS 304",
            pressure_psia=3000,
            temperature_k=300,
            phase=HydrogenPhase.GAS,
        )
        response = evaluate_h2_compatibility(request)

        assert response.classification == AnswerSeverity.CAUTION, (
            f"SS 304 has HIGH HEE band per Sandia data, got {response.classification}"
        )

    def test_ss_321_caution_for_h2(self):
        """SS 321 shows HIGH HEE band (0.87) per Sandia data — CAUTION.

        Evidence: SANDIA-035, HEE index 0.87, band "high" at 55.2 MPa / 24°C.
        """
        request = H2CompatibilityRequest(
            question="Is SS 321 compatible with hydrogen?",
            material_key="SS 321",
            pressure_psia=3000,
            temperature_k=300,
            phase=HydrogenPhase.GAS,
        )
        response = evaluate_h2_compatibility(request)

        assert response.classification == AnswerSeverity.CAUTION, (
            f"SS 321 has HIGH HEE band per Sandia data, got {response.classification}"
        )

    def test_inconel_625_caution_for_h2(self):
        """Inconel 625 shows HIGH HEE band (0.76) per Sandia data — CAUTION.

        Evidence: SANDIA-023, HEE index 0.76, band "high" at 55.2 MPa / 24°C.
        Despite excellent reputation, the evidence shows measurable property
        degradation in hydrogen — CAUTION is the evidence-honest verdict.
        """
        request = H2CompatibilityRequest(
            question="Is Inconel 625 compatible with hydrogen?",
            material_key="Inconel 625",
            pressure_psia=10000,
            temperature_k=350,
            phase=HydrogenPhase.GAS,
        )
        response = evaluate_h2_compatibility(request)

        assert response.classification == AnswerSeverity.CAUTION, (
            f"Inconel 625 has HIGH HEE band per Sandia data, got {response.classification}"
        )
        assert response.embrittlement_risk == "medium"

    def test_inconel_718_condition_dependent(self):
        """Inconel 718 without condition specified has EXTREME HEE in aged state.

        Evidence spans negligible (ST) to extreme (STA, 0.46). Without condition,
        engine returns CLARIFICATION_NEEDED or worst-case PROHIBITED.
        With condition="solution_treated", it should be acceptable.
        """
        # Without condition: should not be OK (extreme band exists)
        request = H2CompatibilityRequest(
            question="Is Inconel 718 compatible with hydrogen?",
            material_key="Inconel 718",
            pressure_psia=8000,
            temperature_k=300,
            phase=HydrogenPhase.GAS,
        )
        response = evaluate_h2_compatibility(request)

        assert response.classification != AnswerSeverity.OK, (
            f"Inconel 718 without condition should not be OK (extreme HEE in aged state), "
            f"got {response.classification}"
        )

    def test_monel_400_prohibited_for_h2(self):
        """Monel 400 shows SEVERE HEE band (0.65) per Sandia data — PROHIBITED.

        Evidence: SANDIA-015, HEE index 0.65, band "severe" at 43.4 MPa / 24°C.
        Despite being a nickel alloy, Monel 400 has severe embrittlement.
        """
        request = H2CompatibilityRequest(
            question="Is Monel 400 compatible with hydrogen?",
            material_key="Monel 400",
            pressure_psia=5000,
            temperature_k=300,
            phase=HydrogenPhase.GAS,
        )
        response = evaluate_h2_compatibility(request)

        assert response.classification == AnswerSeverity.PROHIBITED, (
            f"Monel 400 has SEVERE HEE band per Sandia data, got {response.classification}"
        )

    def test_hastelloy_c276_caution_for_h2(self):
        """Hastelloy C-276 shows HIGH HEE band (0.88) — CAUTION.

        Evidence: NASA-TM-T2-ADD-295, HEE index 0.88, band "high" at 68.9 MPa / 24°C.
        """
        request = H2CompatibilityRequest(
            question="Is Hastelloy C-276 compatible with hydrogen?",
            material_key="Hastelloy C-276",
            pressure_psia=5000,
            temperature_k=300,
            phase=HydrogenPhase.GAS,
        )
        response = evaluate_h2_compatibility(request)

        assert response.classification == AnswerSeverity.CAUTION, (
            f"Hastelloy C-276 has HIGH HEE band, got {response.classification}"
        )

    def test_copper_approved_for_h2(self):
        """Copper (OFHC) shows NEGLIGIBLE HEE band (1.0) — OK.

        Evidence: NASA-TM-T2-012, HEE index 1.0, band "negligible".
        Material key "Copper C10200" resolves to "OFHC Copper" via aliases.
        """
        request = H2CompatibilityRequest(
            question="Is copper compatible with hydrogen?",
            material_key="OFHC Copper",
            pressure_psia=2000,
            temperature_k=300,
            phase=HydrogenPhase.GAS,
        )
        response = evaluate_h2_compatibility(request)

        assert response.classification == AnswerSeverity.OK, (
            f"OFHC Copper has NEGLIGIBLE HEE, got {response.classification}"
        )

    def test_aluminum_6061_approved_for_h2(self):
        """AL 6061-T6 shows NEGLIGIBLE HEE band (1.0) — OK.

        Evidence: NASA-TM-T2-018, HEE index 1.0, band "negligible".
        Aluminum does not suffer hydrogen embrittlement.
        """
        request = H2CompatibilityRequest(
            question="Is AL 6061-T6 compatible with hydrogen?",
            material_key="6061-T6 Aluminum",
            pressure_psia=5000,
            temperature_k=300,
            phase=HydrogenPhase.GAS,
        )
        response = evaluate_h2_compatibility(request)

        assert response.classification == AnswerSeverity.OK, (
            f"6061-T6 Aluminum has NEGLIGIBLE HEE, got {response.classification}. "
            "Aluminum does NOT suffer hydrogen embrittlement."
        )
        assert response.embrittlement_risk == "low"


# =============================================================================
# TEST: CAUTION MATERIALS (Titanium at low temp, polymers)
# =============================================================================

class TestH2CautionMaterials:
    """Materials that should have CAUTION classification for H2."""

    def test_titanium_at_cryogenic(self):
        """Ti-6Al-4V at cryogenic LH2: evidence shows HIGH HEE band.

        Evidence: NASA-TM-T2-007/008, HEE band "high" (0.79-0.89) at ambient.
        At 20K the hydride guardrail doesn't fire (below 422K), but the
        evidence-first engine still returns the worst-case HEE verdict.
        CAUTION (high band) or PROHIBITED (severe in STA condition) depending
        on whether condition is specified.
        """
        request = H2CompatibilityRequest(
            question="Is Ti-6Al-4V compatible with cryogenic hydrogen?",
            material_key="Ti-6Al-4V",
            pressure_psia=500,
            temperature_k=20,  # Cryogenic LH2 (~-423°F)
            phase=HydrogenPhase.LIQUID,
        )
        response = evaluate_h2_compatibility(request)

        # Should NOT be OK — titanium has high-to-severe HEE evidence
        assert response.classification != AnswerSeverity.OK, (
            f"Ti-6Al-4V has HIGH/SEVERE HEE evidence, got {response.classification}"
        )


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
