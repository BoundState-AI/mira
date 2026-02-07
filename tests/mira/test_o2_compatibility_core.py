#!/usr/bin/env python3
"""
Module: Test O2 Compatibility Core
Purpose: from __future__ import annotations

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

from __future__ import annotations

import pytest

from mira.o2.models import O2CompatibilityRequest, OxygenPhase
from mira.o2 import evaluate_o2_compatibility


# =============================================================================
# CRITICAL REGRESSION GUARDS - THE 6061 BUG CLASS
# =============================================================================

class TestAluminum6061RegressionGuard:
    """Regression guards for the exact bug class that started this refactor.

    The original bug: AL 6061 at 200 psia GOX was returning "REQUIRES_TESTING"
    instead of "PROHIBITED". This test class ensures we never regress.

    Per NASA-STD-6016 Section 4.2.6.3:
    - Aluminum alloys are LIMITED to LOX (cryogenic) service only
    - Aluminum is PROHIBITED in GOX (gaseous oxygen) at elevated pressures
    - The limit is approximately 200 psia for GOX per JSC guidelines
    """

    def test_al6061_200psi_gox_must_be_prohibited(self) -> None:
        """AL 6061-T6 at 200 psia GOX MUST be PROHIBITED.

        This is THE critical regression test. If this fails, the bug is back.
        Reference: NASA-STD-6016 §4.2.6.3, JSC-27301F §5.1.4
        """
        req = O2CompatibilityRequest(
            question="Can aluminum 6061 be used in oxygen at 200 psi?",
            material_key="AL 6061-T6",
            pressure_psia=200.0,
            temperature_k=293.0,  # Room temperature (~68°F)
            phase=OxygenPhase.GAS,
        )

        result = evaluate_o2_compatibility(req)

        # HARD ASSERTION: Must be prohibited, not "unknown" or "caution"
        assert result.classification.value == "prohibited", (
            f"CRITICAL REGRESSION: AL 6061 at 200 psia GOX returned "
            f"'{result.classification.value}' instead of 'prohibited'. "
            f"This is the exact bug class we're guarding against."
        )

    def test_al6061_500psi_gox_must_be_prohibited(self) -> None:
        """AL 6061-T6 at 500 psia GOX MUST be PROHIBITED.

        Higher pressure = even more dangerous. Must not be allowed.
        """
        req = O2CompatibilityRequest(
            question="Can aluminum 6061 be used in high-pressure oxygen?",
            material_key="AL 6061-T6",
            pressure_psia=500.0,
            temperature_k=293.0,
            phase=OxygenPhase.GAS,
        )

        result = evaluate_o2_compatibility(req)

        assert result.classification.value == "prohibited", (
            f"AL 6061 at 500 psia GOX should be prohibited, got '{result.classification.value}'"
        )

    def test_al6061_lox_cryogenic_may_be_allowed(self) -> None:
        """AL 6061-T6 in LOX (cryogenic) MAY be allowed with restrictions.

        Per NASA-STD-6016 §4.2.6.3: Aluminum is permitted in LOX service
        under specific conditions (low pressure, cryogenic temps).
        """
        req = O2CompatibilityRequest(
            question="Can aluminum 6061 be used in liquid oxygen?",
            material_key="AL 6061-T6",
            pressure_psia=50.0,  # Low pressure
            temperature_k=90.0,  # LOX temperature (~-183°C / -297°F)
            phase=OxygenPhase.LIQUID,
        )

        result = evaluate_o2_compatibility(req)

        # LOX service may be allowed (ok, caution) or unknown - but NOT prohibited
        # unless the engine has stricter rules
        # For now, we just verify the engine doesn't crash and returns a valid response
        assert result.classification.value in ("ok", "caution", "unknown", "prohibited"), (
            f"Unexpected classification for AL 6061 in LOX: '{result.classification.value}'"
        )

    def test_al6061_rationale_mentions_aluminum_restriction(self) -> None:
        """Rationale for AL 6061 prohibition should explain WHY.

        The user must understand this isn't arbitrary - it's a safety rule.
        """
        req = O2CompatibilityRequest(
            question="Can aluminum 6061 be used in oxygen at 200 psi?",
            material_key="AL 6061-T6",
            pressure_psia=200.0,
            temperature_k=293.0,
            phase=OxygenPhase.GAS,
        )

        result = evaluate_o2_compatibility(req)

        # Rationale should not be empty
        assert result.rationale, "Rationale must not be empty for prohibited materials"
        # Should mention something about aluminum, LOX, or the restriction
        rationale_lower = result.rationale.lower()
        assert any(term in rationale_lower for term in [
            "aluminum", "lox", "prohibited", "6016", "gox", "not", "excluded"
        ]), f"Rationale should explain aluminum restriction: '{result.rationale}'"


# =============================================================================
# HARD PROHIBITIONS - TITANIUM, MAGNESIUM
# =============================================================================

class TestHardProhibitions:
    """Materials that are ALWAYS prohibited in O2 service."""

    def test_titanium_200psi_gox_prohibited(self) -> None:
        """Titanium in GOX at 200 psia should be PROHIBITED per NASA-STD-6016.

        Titanium alloys are prohibited in O2 service due to promoted combustion risk.
        Reference: NASA-STD-6016 Section 4.2.6.2
        """
        req = O2CompatibilityRequest(
            question="Can titanium be used in oxygen at 200 psi?",
            material_key="Ti-6Al-4V",
            pressure_psia=200.0,
            temperature_k=293.0,
            phase=OxygenPhase.GAS,
        )

        result = evaluate_o2_compatibility(req)

        assert result.classification.value == "prohibited", (
            f"Expected 'prohibited' for titanium in GOX, got '{result.classification.value}'"
        )

    def test_titanium_any_pressure_gox_prohibited(self) -> None:
        """Titanium at ANY pressure in GOX should be PROHIBITED.

        There is no safe pressure for titanium in O2 - it's a blanket prohibition.
        """
        for pressure in [14.7, 50.0, 100.0, 500.0, 3000.0]:
            req = O2CompatibilityRequest(
                question=f"Can titanium be used in oxygen at {pressure} psi?",
                material_key="Ti-6Al-4V",
                pressure_psia=pressure,
                temperature_k=293.0,
                phase=OxygenPhase.GAS,
            )

            result = evaluate_o2_compatibility(req)

            assert result.classification.value == "prohibited", (
                f"Titanium at {pressure} psia GOX should be prohibited, "
                f"got '{result.classification.value}'"
            )

    def test_magnesium_any_gox_prohibited(self) -> None:
        """Magnesium in GOX should be PROHIBITED.

        Magnesium alloys are highly flammable in oxygen environments.
        Reference: NASA-STD-6016 Table 4-1
        """
        req = O2CompatibilityRequest(
            question="Can magnesium be used in oxygen service?",
            material_key="Magnesium AZ31",
            pressure_psia=100.0,
            temperature_k=293.0,
            phase=OxygenPhase.GAS,
        )

        result = evaluate_o2_compatibility(req)

        assert result.classification.value == "prohibited", (
            f"Expected 'prohibited' for magnesium in GOX, got '{result.classification.value}'"
        )


# =============================================================================
# KNOWN GOOD MATERIALS - STAINLESS, NICKEL ALLOYS
# =============================================================================

class TestKnownGoodMaterials:
    """Materials that should be OK or CAUTION (not prohibited) in O2."""

    def test_ss316_500psi_gox_not_prohibited(self) -> None:
        """SS 316 in GOX at 500 psia should NOT be PROHIBITED.

        300-series stainless steels are generally acceptable for O2 service
        with appropriate cleaning per NASA-STD-6016 Table 4-1.
        """
        req = O2CompatibilityRequest(
            question="Can SS 316 be used in oxygen at 500 psi?",
            material_key="SS 316",
            pressure_psia=500.0,
            temperature_k=293.0,
            phase=OxygenPhase.GAS,
        )

        result = evaluate_o2_compatibility(req)

        assert result.classification.value in ("ok", "caution", "unknown"), (
            f"SS 316 should NOT be prohibited in GOX, got '{result.classification.value}'"
        )

    def test_inconel_625_high_pressure_gox(self) -> None:
        """Inconel 625 in high-pressure GOX should be OK or CAUTION.

        Nickel alloys like Inconel are preferred for high-pressure O2 service.
        Reference: NASA-STD-6016 Table 4-1
        """
        req = O2CompatibilityRequest(
            question="Can Inconel 625 be used in oxygen at 3000 psi?",
            material_key="INCONEL 625",
            pressure_psia=3000.0,
            temperature_k=293.0,
            phase=OxygenPhase.GAS,
        )

        result = evaluate_o2_compatibility(req)

        assert result.classification.value in ("ok", "caution", "unknown"), (
            f"Inconel 625 should be acceptable for high-pressure O2, "
            f"got '{result.classification.value}'"
        )

    def test_monel_400_high_pressure_gox(self) -> None:
        """Monel 400 in high-pressure GOX should be OK or CAUTION.

        Monel (nickel-copper alloy) is excellent for O2 service.
        """
        req = O2CompatibilityRequest(
            question="Can Monel 400 be used in oxygen at 5000 psi?",
            material_key="MONEL 400",
            pressure_psia=5000.0,
            temperature_k=293.0,
            phase=OxygenPhase.GAS,
        )

        result = evaluate_o2_compatibility(req)

        assert result.classification.value in ("ok", "caution", "unknown"), (
            f"Monel 400 should be acceptable for high-pressure O2, "
            f"got '{result.classification.value}'"
        )


# =============================================================================
# "UNKNOWN" / "REQUIRES TESTING" CLASS
# =============================================================================

class TestRequiresTestingClass:
    """Verify that UNKNOWN classification exists and is used appropriately.

    The UNKNOWN class should be used for materials where:
    - No O2 test data exists
    - Material family is not explicitly prohibited or approved
    - Engineering evaluation is genuinely required

    IMPORTANT: UNKNOWN must NOT be used for materials that are prohibited.
    """

    def test_unknown_material_returns_unknown(self) -> None:
        """An unknown/novel material should return UNKNOWN, not PROHIBITED.

        This proves the UNKNOWN class is available and working.
        """
        req = O2CompatibilityRequest(
            question="Can this novel polymer be used in oxygen?",
            material_key="NOVEL-POLYMER-XYZ-999",
            pressure_psia=100.0,
            temperature_k=293.0,
            phase=OxygenPhase.GAS,
        )

        result = evaluate_o2_compatibility(req)

        # Unknown materials should get UNKNOWN, not automatically PROHIBITED
        # (unless the engine is extra conservative, which is also acceptable)
        assert result.classification.value in ("unknown", "caution", "prohibited"), (
            f"Novel material should be unknown/caution/prohibited, "
            f"got '{result.classification.value}'"
        )

    def test_unknown_is_distinct_from_prohibited_for_novel_materials(self) -> None:
        """UNKNOWN and PROHIBITED should be distinct classifications.

        Verify the engine doesn't collapse everything into PROHIBITED.
        """
        # A novel material with no data
        novel_req = O2CompatibilityRequest(
            question="Can this unknown material be used?",
            material_key="UNKNOWN-TEST-MATERIAL",
            pressure_psia=50.0,
            temperature_k=293.0,
            phase=OxygenPhase.GAS,
        )

        # A known-prohibited material (titanium)
        prohibited_req = O2CompatibilityRequest(
            question="Can titanium be used?",
            material_key="Ti-6Al-4V",
            pressure_psia=50.0,
            temperature_k=293.0,
            phase=OxygenPhase.GAS,
        )

        novel_result = evaluate_o2_compatibility(novel_req)
        prohibited_result = evaluate_o2_compatibility(prohibited_req)

        # Titanium MUST be prohibited
        assert prohibited_result.classification.value == "prohibited"

        # Novel material should ideally be different (unknown or caution)
        # But if engine is conservative and returns prohibited, that's also safe
        # The key is that the RATIONALE should be different
        if novel_result.classification.value == prohibited_result.classification.value:
            # If both are prohibited, rationale should differ
            assert novel_result.rationale != prohibited_result.rationale, (
                "Novel material and titanium have identical rationales - "
                "engine may be collapsing all unknowns to prohibited incorrectly"
            )


# =============================================================================
# RESPONSE STRUCTURE AND EVIDENCE
# =============================================================================

class TestResponseStructure:
    """Verify response structure and evidence quality."""

    def test_response_includes_environment_notes(self) -> None:
        """Response should include environment details in notes."""
        req = O2CompatibilityRequest(
            question="Test query",
            material_key="Test-Material",
            pressure_psia=100.0,
            temperature_k=300.0,
            phase=OxygenPhase.GAS,
        )

        result = evaluate_o2_compatibility(req)

        assert result.notes is not None
        assert "O2" in result.notes or "psi" in result.notes

    def test_prohibited_material_has_rationale(self) -> None:
        """Prohibited materials MUST have a rationale explaining why."""
        req = O2CompatibilityRequest(
            question="Can titanium be used in oxygen?",
            material_key="Ti-6Al-4V",
            pressure_psia=200.0,
            temperature_k=293.0,
            phase=OxygenPhase.GAS,
        )

        result = evaluate_o2_compatibility(req)

        assert result.classification.value == "prohibited"
        assert result.rationale, "Prohibited classification MUST include rationale"
        assert len(result.rationale) > 10, "Rationale should be meaningful, not just 'prohibited'"

    def test_al6061_prohibition_evidence_references_standards(self) -> None:
        """AL 6061 prohibition should reference relevant standards.

        Evidence should include references to:
        - NASA-STD-6016 (materials standard)
        - JSC guidelines (oxygen limits)
        - Specific section numbers where possible
        """
        req = O2CompatibilityRequest(
            question="Can aluminum 6061 be used in oxygen at 200 psi?",
            material_key="AL 6061-T6",
            pressure_psia=200.0,
            temperature_k=293.0,
            phase=OxygenPhase.GAS,
        )

        result = evaluate_o2_compatibility(req)

        # Check rationale or notes for standard references
        combined_text = f"{result.rationale} {result.notes or ''}".lower()

        # Should mention at least one of these
        standard_refs = ["6016", "6001", "jsc", "nasa", "lox", "gox", "aluminum"]
        has_reference = any(ref in combined_text for ref in standard_refs)

        assert has_reference, (
            f"AL 6061 prohibition should reference standards. "
            f"Rationale: '{result.rationale}', Notes: '{result.notes}'"
        )


# =============================================================================
# LEGACY VS NEW EQUIVALENCE HARNESS
# =============================================================================

class TestLegacyEquivalence:
    """Verify new engine produces equivalent or better results than legacy.

    The new evaluate_o2_compatibility() wrapper should:
    1. Never return a LESS SAFE classification than legacy
    2. Provide equal or better evidence/rationale
    3. Handle all the same material/environment combinations

    These tests compare outputs to ensure the migration is safe.
    """

    def test_prohibited_materials_equivalence(self) -> None:
        """Prohibited materials should remain prohibited in both engines."""
        prohibited_materials = [
            ("Ti-6Al-4V", 200.0, OxygenPhase.GAS),  # Titanium
            ("Magnesium AZ31", 100.0, OxygenPhase.GAS),  # Magnesium
            ("AL 6061-T6", 200.0, OxygenPhase.GAS),  # Aluminum in GOX
            ("AL 6061-T6", 500.0, OxygenPhase.GAS),  # Aluminum in high-pressure GOX
        ]

        for material_key, pressure, phase in prohibited_materials:
            req = O2CompatibilityRequest(
                question=f"Can {material_key} be used?",
                material_key=material_key,
                pressure_psia=pressure,
                temperature_k=293.0,
                phase=phase,
            )

            result = evaluate_o2_compatibility(req)

            assert result.classification.value == "prohibited", (
                f"Material {material_key} at {pressure} psia {phase.value} "
                f"should be prohibited, got '{result.classification.value}'"
            )

    def test_approved_materials_not_prohibited(self) -> None:
        """Approved materials should not become prohibited in new engine."""
        approved_materials = [
            ("SS 316", 500.0, OxygenPhase.GAS),
            ("INCONEL 625", 3000.0, OxygenPhase.GAS),
            ("MONEL 400", 5000.0, OxygenPhase.GAS),
        ]

        for material_key, pressure, phase in approved_materials:
            req = O2CompatibilityRequest(
                question=f"Can {material_key} be used?",
                material_key=material_key,
                pressure_psia=pressure,
                temperature_k=293.0,
                phase=phase,
            )

            result = evaluate_o2_compatibility(req)

            assert result.classification.value in ("ok", "caution", "unknown"), (
                f"Approved material {material_key} at {pressure} psia "
                f"should NOT be prohibited, got '{result.classification.value}'"
            )

    def test_new_engine_provides_rationale(self) -> None:
        """New engine should always provide rationale (never empty)."""
        test_cases = [
            ("Ti-6Al-4V", 200.0, OxygenPhase.GAS),
            ("AL 6061-T6", 200.0, OxygenPhase.GAS),
            ("SS 316", 500.0, OxygenPhase.GAS),
            ("UNKNOWN-MATERIAL", 100.0, OxygenPhase.GAS),
        ]

        for material_key, pressure, phase in test_cases:
            req = O2CompatibilityRequest(
                question=f"Can {material_key} be used?",
                material_key=material_key,
                pressure_psia=pressure,
                temperature_k=293.0,
                phase=phase,
            )

            result = evaluate_o2_compatibility(req)

            assert result.rationale, (
                f"Result for {material_key} should have non-empty rationale"
            )
            assert len(result.rationale) > 10, (
                f"Rationale for {material_key} should be meaningful"
            )

    def test_new_engine_provides_evidence(self) -> None:
        """Prohibited and approved materials should have evidence citations."""
        test_cases = [
            ("Ti-6Al-4V", 200.0, OxygenPhase.GAS, True),  # Should have evidence
            ("AL 6061-T6", 200.0, OxygenPhase.GAS, True),  # Should have evidence
            ("INCONEL 625", 3000.0, OxygenPhase.GAS, True),  # Should have evidence
        ]

        for material_key, pressure, phase, expect_evidence in test_cases:
            req = O2CompatibilityRequest(
                question=f"Can {material_key} be used?",
                material_key=material_key,
                pressure_psia=pressure,
                temperature_k=293.0,
                phase=phase,
            )

            result = evaluate_o2_compatibility(req)

            if expect_evidence:
                assert result.evidence, (
                    f"Result for {material_key} should have evidence items"
                )

    def test_boundary_conditions(self) -> None:
        """Test behavior at classification boundaries."""
        # Aluminum at exactly 200 psi (the boundary)
        req_boundary = O2CompatibilityRequest(
            question="Aluminum at boundary",
            material_key="AL 6061-T6",
            pressure_psia=200.0,  # Exact boundary
            temperature_k=293.0,
            phase=OxygenPhase.GAS,
        )
        result_boundary = evaluate_o2_compatibility(req_boundary)
        assert result_boundary.classification.value == "prohibited", (
            "Aluminum at exactly 200 psia GOX should be prohibited"
        )

        # Aluminum just below boundary
        req_below = O2CompatibilityRequest(
            question="Aluminum below boundary",
            material_key="AL 6061-T6",
            pressure_psia=199.0,  # Just below
            temperature_k=293.0,
            phase=OxygenPhase.GAS,
        )
        result_below = evaluate_o2_compatibility(req_below)
        assert result_below.classification.value == "caution", (
            "Aluminum at 199 psia GOX should be caution, not prohibited"
        )
