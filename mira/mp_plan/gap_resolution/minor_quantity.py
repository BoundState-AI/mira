#!/usr/bin/env python3
"""
Module: Minor Quantity Closure Path
Purpose: MPR 44(c) - Minor quantity exception implementation

BoundState AI 2026
Version: 2.0.0
Classification: BoundState Proprietary

Implements MPR 44(c) minor quantity exception:
"Materials may be used if total mass <45g AND surface area <13cm²
in aggregated zone"

Key Rules (from Fran Fix #4):
1. Aggregation is by ZONE, not per-material
2. NASA reviewers check aggregation and interaction
3. Materials in same ignition source proximity are grouped
4. Mass AND area must BOTH be under thresholds

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


class MinorQuantityPath(ClosurePathBase):
    """
    MPR 44(c) - Minor quantity exception.

    Materials not meeting flammability requirements may be used if
    the total aggregated mass and surface area in a zone are below
    the threshold values.

    Thresholds (NASA-STD-6016C Section 4.2.4.3(c)):
    - Mass: < 45 grams
    - Surface Area: < 13 cm²

    IMPORTANT: These are AGGREGATED totals for materials in the same
    ignition source proximity zone, not per-material limits.
    """

    path_id = "MINOR_QUANTITY"
    path_title = "Minor Quantity Exception"
    path_description = "Materials below mass/area thresholds in aggregated zone"
    citation = "NASA-STD-6016C Section 4.2.4.3(c)"
    required_inputs = ["mass_g", "surface_area_cm2", "adjacency_group"]
    output_artifact = "minor_quantity_analysis"

    # MPR 44(c) thresholds
    MASS_THRESHOLD_G = 45.0
    AREA_THRESHOLD_CM2 = 13.0

    def check_eligibility(
        self,
        gap: "NonconformanceSignal",
        material: "MaterialEntry",
        environment: "EnvironmentDefinition",
        session: "PlanGeneratorSession",
    ) -> ClosurePathResult:
        """
        Check if minor quantity exception is eligible.

        Eligibility requires:
        1. Gap must be a flammability gap (FLAM)
        2. Material must have mass and surface area defined
        3. Aggregated zone totals must be under thresholds

        Returns:
            ClosurePathResult with eligibility determination.
        """
        # Rule 1: Only applies to flammability gaps
        if gap.gap_type != FailureMode.FLAM:
            return self._build_result(
                eligible=False,
                rationale=f"Minor quantity exception only applies to flammability gaps. "
                f"This gap is type '{gap.gap_type.value if hasattr(gap.gap_type, 'value') else gap.gap_type}'.",
                confidence=1.0,
            )

        # Rule 2: Material must have mass and area defined
        provided_inputs = {}

        if material.mass_g is not None:
            provided_inputs["mass_g"] = material.mass_g

        if material.surface_area_cm2 is not None:
            provided_inputs["surface_area_cm2"] = material.surface_area_cm2

        # Check if we have the required data
        if material.mass_g is None or material.surface_area_cm2 is None:
            missing = []
            if material.mass_g is None:
                missing.append("mass_g")
            if material.surface_area_cm2 is None:
                missing.append("surface_area_cm2")

            return self._build_result(
                eligible=False,
                rationale=f"Cannot evaluate minor quantity - missing: {', '.join(missing)}. "
                f"Provide mass (g) and surface area (cm²) to check eligibility.",
                provided_inputs=provided_inputs,
                confidence=0.0,
            )

        # Rule 3: Check aggregation if available
        if session.minor_quantity_aggregation:
            agg = session.minor_quantity_aggregation
            group = agg.get_group_for_material(material.id, environment.environment_id)

            if group:
                provided_inputs["adjacency_group"] = group.adjacency_group
                provided_inputs["group_total_mass_g"] = group.total_mass_g
                provided_inputs["group_total_area_cm2"] = group.total_surface_area_cm2

                # Check aggregated thresholds
                mass_ok = group.total_mass_g < self.MASS_THRESHOLD_G
                area_ok = group.total_surface_area_cm2 < self.AREA_THRESHOLD_CM2

                if mass_ok and area_ok:
                    return self._build_result(
                        eligible=True,
                        rationale=f"ELIGIBLE: Aggregated zone totals are below thresholds. "
                        f"Mass: {group.total_mass_g:.1f}g < {self.MASS_THRESHOLD_G}g, "
                        f"Area: {group.total_surface_area_cm2:.1f}cm² < {self.AREA_THRESHOLD_CM2}cm². "
                        f"Group: {group.adjacency_group} ({len(group.material_ids)} materials).",
                        provided_inputs=provided_inputs,
                        confidence=1.0,
                    )
                else:
                    reasons = []
                    if not mass_ok:
                        reasons.append(
                            f"mass {group.total_mass_g:.1f}g >= {self.MASS_THRESHOLD_G}g"
                        )
                    if not area_ok:
                        reasons.append(
                            f"area {group.total_surface_area_cm2:.1f}cm² >= {self.AREA_THRESHOLD_CM2}cm²"
                        )

                    return self._build_result(
                        eligible=False,
                        rationale=f"NOT ELIGIBLE: Aggregated zone totals exceed thresholds. "
                        f"{'; '.join(reasons)}. "
                        f"Consider substitution or configuration analysis.",
                        provided_inputs=provided_inputs,
                        confidence=1.0,
                    )

        # Rule 4: No aggregation - check individual material (conservative)
        mass_ok = material.mass_g < self.MASS_THRESHOLD_G
        area_ok = material.surface_area_cm2 < self.AREA_THRESHOLD_CM2

        if mass_ok and area_ok:
            return self._build_result(
                eligible=True,
                rationale=f"LIKELY ELIGIBLE (pending zone aggregation): "
                f"Individual material is below thresholds. "
                f"Mass: {material.mass_g:.1f}g < {self.MASS_THRESHOLD_G}g, "
                f"Area: {material.surface_area_cm2:.1f}cm² < {self.AREA_THRESHOLD_CM2}cm². "
                f"Final eligibility depends on aggregated zone totals.",
                provided_inputs=provided_inputs,
                confidence=0.7,  # Lower confidence without aggregation
            )
        else:
            reasons = []
            if not mass_ok:
                reasons.append(f"mass {material.mass_g:.1f}g >= {self.MASS_THRESHOLD_G}g")
            if not area_ok:
                reasons.append(
                    f"area {material.surface_area_cm2:.1f}cm² >= {self.AREA_THRESHOLD_CM2}cm²"
                )

            return self._build_result(
                eligible=False,
                rationale=f"NOT ELIGIBLE: Individual material exceeds thresholds ({'; '.join(reasons)}). "
                f"Consider substitution, configuration analysis, or heat sink path.",
                provided_inputs=provided_inputs,
                confidence=1.0,
            )
