#!/usr/bin/env python3
"""
Module: Substitution Closure Path
Purpose: MPR 44(a) - Alternative A-rated material substitution

BoundState AI 2026
Version: 2.0.0
Classification: BoundState Proprietary

Implements MPR 44(a) substitution exception:
"An alternative material with equivalent functional properties
and an A-rating for the use environment may be substituted."

Key Rules (from Fran Fix #4):
1. Substitute must have A-rating for same use conditions
2. Functional equivalence must be demonstrated
3. May require form-fit-function analysis
4. Design change may be required

Compliance: NASA-STD-8739.8B, SWE-013, SWE-033
Safety Critical: False
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from mira.compliance.models.enums import FailureMode

from .base import ClosurePathBase, ClosurePathResult

if TYPE_CHECKING:
    from ..models import (
        EnvironmentDefinition,
        MaterialEntry,
        NonconformanceSignal,
        PlanGeneratorSession,
    )

__version__ = "2.0.0"
__safety_critical__ = False


class SubstitutionPath(ClosurePathBase):
    """
    MPR 44(a) - Material Substitution.

    Materials not meeting requirements may be replaced with
    alternative A-rated materials that provide equivalent function.

    Citation: NASA-STD-6016C Section 4.2.4.3(a)

    This path requires:
    - Identification of candidate substitute material
    - Verification of A-rating at use conditions
    - Functional equivalence analysis
    - Design impact assessment
    """

    path_id = "SUBSTITUTION"
    path_title = "Material Substitution"
    path_description = "Replace with A-rated alternative material"
    citation = "NASA-STD-6016C Section 4.2.4.3(a)"
    required_inputs = [
        "substitute_material_name",
        "substitute_maptis_code",
        "functional_equivalence_rationale",
        "design_impact_assessment",
    ]
    output_artifact = "substitution_analysis"

    def check_eligibility(
        self,
        gap: "NonconformanceSignal",
        material: "MaterialEntry",
        environment: "EnvironmentDefinition",
        session: "PlanGeneratorSession",
    ) -> ClosurePathResult:
        """
        Check if material substitution is eligible.

        Substitution is always potentially eligible for any gap type,
        as it replaces the non-conforming material entirely.

        The eligibility depends on:
        1. Availability of suitable alternative materials
        2. Design flexibility to accommodate substitution
        3. Cost/schedule constraints (not evaluated here)

        Returns:
            ClosurePathResult with eligibility determination.
        """
        provided_inputs = {}

        # Substitution is broadly applicable - works for most gap types
        applicable_gap_types = [
            FailureMode.FLAM,  # Flammability
            FailureMode.OFFGAS,  # Offgassing
            FailureMode.SCC,  # Stress corrosion cracking
            FailureMode.HE,  # Hydrogen embrittlement
            FailureMode.COMPAT,  # Compatibility
        ]

        gap_type_value = gap.gap_type.value if hasattr(gap.gap_type, "value") else str(gap.gap_type)

        # Check if gap type is one we can substitute for
        if gap.gap_type not in applicable_gap_types:
            return self._build_result(
                eligible=False,
                rationale=f"Substitution not typically applicable for gap type '{gap_type_value}'. "
                "Consider other closure paths.",
                confidence=0.8,
            )

        # Check if session has candidate substitutes identified
        has_candidates = False
        if hasattr(session, "substitute_candidates") and session.substitute_candidates:
            candidates = session.substitute_candidates.get(material.id, [])
            if candidates:
                has_candidates = True
                provided_inputs["candidate_count"] = len(candidates)
                provided_inputs["candidates"] = [c.get("name", "Unknown") for c in candidates[:3]]

        # Check material application for substitution feasibility
        application = material.application.lower() if material.application else ""

        # Some applications are more amenable to substitution
        flexible_applications = [
            "adhesive",
            "sealant",
            "coating",
            "lubricant",
            "thermal interface",
            "insulation",
            "tape",
            "wire insulation",
        ]

        is_flexible = any(app in application for app in flexible_applications)
        provided_inputs["application"] = material.application
        provided_inputs["flexible_application"] = is_flexible

        if has_candidates:
            return self._build_result(
                eligible=True,
                rationale=f"ELIGIBLE: Candidate substitutes identified. "
                f"{provided_inputs['candidate_count']} alternative(s) available. "
                "Requires functional equivalence verification and design impact assessment.",
                provided_inputs=provided_inputs,
                confidence=0.9,
            )
        elif is_flexible:
            return self._build_result(
                eligible=True,
                rationale=f"LIKELY ELIGIBLE: Application '{material.application}' typically allows "
                "material substitution. Search MAPTIS for A-rated alternatives at "
                f"O2={environment.o2_pct}%, {environment.pressure_psia} psia.",
                provided_inputs=provided_inputs,
                confidence=0.7,
            )
        else:
            return self._build_result(
                eligible=True,
                rationale="POTENTIALLY ELIGIBLE: Material substitution is possible but may require "
                "design changes. Identify A-rated alternatives and assess functional equivalence. "
                "Consider form-fit-function impact.",
                provided_inputs=provided_inputs,
                confidence=0.5,
            )
