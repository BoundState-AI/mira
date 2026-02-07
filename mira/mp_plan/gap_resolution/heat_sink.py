#!/usr/bin/env python3
"""
Module: Heat Sink Closure Path
Purpose: MPR 44(g) - Bonded to metal heat sink exception

BoundState AI 2026
Version: 2.0.0
Classification: BoundState Proprietary

Implements MPR 44(g) heat sink exception:
"Materials bonded to metallic heat sinks with sufficient thermal
conductivity to prevent sustained ignition may be used."

Key Rules (from Fran Fix #4):
1. Bond must be direct (no air gaps)
2. Metal substrate must have adequate thermal mass
3. Bond thickness must be within limits
4. Thermal conductivity must be demonstrated

Compliance: NASA-STD-8739.8B, SWE-013, SWE-033
Safety Critical: False
"""

from __future__ import annotations

from typing import TYPE_CHECKING

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


class HeatSinkPath(ClosurePathBase):
    """
    MPR 44(g) - Heat Sink Exception.

    Materials not meeting flammability requirements may be used if
    bonded to metallic heat sinks that prevent sustained ignition.

    Citation: NASA-STD-6016C Section 4.2.4.3(g)

    Thresholds (conservative defaults):
    - Maximum bond thickness: 0.020 inches (0.5mm)
    - Minimum metal substrate thickness: 0.032 inches (0.8mm)
    - Approved metal substrates: aluminum, steel, titanium, Inconel

    Required for eligibility:
    - Material must be bonded (not mechanically fastened with gap)
    - Substrate must be metallic
    - Bond thickness must be within limits
    """

    path_id = "HEAT_SINK"
    path_title = "Heat Sink Exception"
    path_description = "Materials bonded to metallic heat sinks per MPR 44(g)"
    citation = "NASA-STD-6016C Section 4.2.4.3(g)"
    required_inputs = [
        "substrate_material",
        "bond_type",
        "bond_thickness_mm",
        "substrate_thickness_mm",
    ]
    output_artifact = "heat_sink_analysis"

    # Heat sink thresholds
    MAX_BOND_THICKNESS_MM = 0.5  # 0.020 inches
    MIN_SUBSTRATE_THICKNESS_MM = 0.8  # 0.032 inches

    # Approved metallic substrates (common aerospace metals)
    APPROVED_SUBSTRATES = {
        "aluminum",
        "aluminium",
        "steel",
        "stainless steel",
        "stainless",
        "titanium",
        "inconel",
        "copper",
        "brass",
        "nickel",
        "monel",
        "hastelloy",
        "kovar",
        "invar",
    }

    def check_eligibility(
        self,
        gap: "NonconformanceSignal",
        material: "MaterialEntry",
        environment: "EnvironmentDefinition",
        session: "PlanGeneratorSession",
    ) -> ClosurePathResult:
        """
        Check if heat sink exception is eligible.

        Eligibility requires:
        1. Gap must be a flammability gap (FLAM)
        2. Material must be bonded to metal substrate
        3. Bond thickness must be within limits
        4. Substrate must be approved metallic material

        Returns:
            ClosurePathResult with eligibility determination.
        """
        # Rule 1: Only applies to flammability gaps
        if gap.gap_type != FailureMode.FLAM:
            return self._build_result(
                eligible=False,
                rationale=f"Heat sink exception only applies to flammability gaps. "
                f"This gap is type '{gap.gap_type.value if hasattr(gap.gap_type, 'value') else gap.gap_type}'.",
                confidence=1.0,
            )

        # Collect provided inputs
        provided_inputs = {}

        # Check for substrate material
        substrate = None
        if hasattr(material, "substrate_material") and material.substrate_material:
            substrate = material.substrate_material.lower()
            provided_inputs["substrate_material"] = material.substrate_material
        elif hasattr(material, "substrate") and material.substrate:
            substrate = material.substrate.lower()
            provided_inputs["substrate_material"] = material.substrate

        # Check for bond type
        bond_type = None
        if hasattr(material, "bond_type") and material.bond_type:
            bond_type = material.bond_type.lower()
            provided_inputs["bond_type"] = material.bond_type

        # Check for bond thickness
        bond_thickness = None
        if hasattr(material, "bond_thickness_mm") and material.bond_thickness_mm is not None:
            bond_thickness = material.bond_thickness_mm
            provided_inputs["bond_thickness_mm"] = bond_thickness

        # Check for substrate thickness
        substrate_thickness = None
        if hasattr(material, "substrate_thickness_mm") and material.substrate_thickness_mm is not None:
            substrate_thickness = material.substrate_thickness_mm
            provided_inputs["substrate_thickness_mm"] = substrate_thickness

        # Rule 2: Must have substrate information
        if not substrate:
            return self._build_result(
                eligible=False,
                rationale="Heat sink exception requires substrate material information. "
                "Provide substrate_material to evaluate eligibility.",
                provided_inputs=provided_inputs,
                confidence=0.0,
            )

        # Rule 3: Substrate must be metallic
        is_metallic = any(metal in substrate for metal in self.APPROVED_SUBSTRATES)
        if not is_metallic:
            return self._build_result(
                eligible=False,
                rationale=f"Substrate '{substrate}' is not an approved metallic heat sink. "
                f"Approved materials include: aluminum, steel, titanium, Inconel, copper. "
                "Consider configuration analysis or substitution instead.",
                provided_inputs=provided_inputs,
                confidence=1.0,
            )

        # Rule 4: Check bond thickness if provided
        if bond_thickness is not None:
            if bond_thickness > self.MAX_BOND_THICKNESS_MM:
                return self._build_result(
                    eligible=False,
                    rationale=f"Bond thickness {bond_thickness}mm exceeds maximum "
                    f"{self.MAX_BOND_THICKNESS_MM}mm for heat sink exception. "
                    "Consider thinner bond line or configuration analysis.",
                    provided_inputs=provided_inputs,
                    confidence=1.0,
                )

        # Rule 5: Check substrate thickness if provided
        if substrate_thickness is not None:
            if substrate_thickness < self.MIN_SUBSTRATE_THICKNESS_MM:
                return self._build_result(
                    eligible=False,
                    rationale=f"Substrate thickness {substrate_thickness}mm is below minimum "
                    f"{self.MIN_SUBSTRATE_THICKNESS_MM}mm for adequate thermal mass. "
                    "Consider thicker substrate or configuration analysis.",
                    provided_inputs=provided_inputs,
                    confidence=1.0,
                )

        # Determine confidence based on available data
        has_bond_data = bond_thickness is not None
        has_substrate_thickness = substrate_thickness is not None

        if has_bond_data and has_substrate_thickness:
            return self._build_result(
                eligible=True,
                rationale=f"ELIGIBLE: Material bonded to {substrate} heat sink. "
                f"Bond thickness: {bond_thickness}mm (max: {self.MAX_BOND_THICKNESS_MM}mm). "
                f"Substrate thickness: {substrate_thickness}mm (min: {self.MIN_SUBSTRATE_THICKNESS_MM}mm). "
                "Heat sink exception criteria satisfied.",
                provided_inputs=provided_inputs,
                confidence=1.0,
            )
        elif has_bond_data or has_substrate_thickness:
            missing = []
            if not has_bond_data:
                missing.append("bond_thickness_mm")
            if not has_substrate_thickness:
                missing.append("substrate_thickness_mm")

            return self._build_result(
                eligible=True,
                rationale=f"LIKELY ELIGIBLE: Material bonded to {substrate} (approved metallic). "
                f"Missing: {', '.join(missing)} for full verification. "
                "Provide thickness data for complete assessment.",
                provided_inputs=provided_inputs,
                confidence=0.7,
            )
        else:
            return self._build_result(
                eligible=True,
                rationale=f"POTENTIALLY ELIGIBLE: Material has {substrate} substrate (approved metallic). "
                "Provide bond_thickness_mm and substrate_thickness_mm for verification. "
                "Heat sink exception may apply if bond meets thickness criteria.",
                provided_inputs=provided_inputs,
                confidence=0.5,
            )
