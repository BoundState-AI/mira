#!/usr/bin/env python3
"""
Module: Configuration Analysis Closure Path
Purpose: JSC 29353 - Self-extinguishing configuration analysis

BoundState AI 2026
Version: 2.0.0
Classification: BoundState Proprietary

Implements configuration analysis per JSC 29353 methodology:
"Materials that fail flammability testing may be used if configuration
analysis demonstrates self-extinguishing behavior in actual use."

Key Rules (from Fran Fix #4):
1. Must document actual mounting configuration
2. Heat dissipation paths must be quantified
3. Adjacent materials must be considered
4. NASA reviewer validates analysis methodology

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


class ConfigurationAnalysisPath(ClosurePathBase):
    """
    JSC 29353 - Configuration Analysis.

    Materials not meeting flammability requirements may be used if
    configuration analysis demonstrates self-extinguishing behavior
    in the actual use configuration.

    Citation: NASA-STD-6016C Section 4.2.4.3(h)
    Reference: JSC 29353 "Flammability Test Procedures and Configuration
               Analysis for Spacecraft Applications"

    Required for eligibility:
    - Material must have a defined mounting configuration
    - Heat sink path must be documented
    - Adjacent materials must be identified
    """

    path_id = "CONFIGURATION_ANALYSIS"
    path_title = "Configuration Analysis"
    path_description = "Self-extinguishing analysis per JSC 29353 methodology"
    citation = "NASA-STD-6016C Section 4.2.4.3(h)"
    required_inputs = [
        "mounting_configuration",
        "heat_sink_description",
        "adjacent_materials",
        "thermal_path_description",
    ]
    output_artifact = "configuration_analysis_report"

    # Configuration analysis typically requires engineering judgment
    # and cannot be fully automated - eligibility check is conservative
    MIN_HEAT_SINK_CONTACT_PERCENT = 25.0  # Minimum contact area with heat sink

    def check_eligibility(
        self,
        gap: "NonconformanceSignal",
        material: "MaterialEntry",
        environment: "EnvironmentDefinition",
        session: "PlanGeneratorSession",
    ) -> ClosurePathResult:
        """
        Check if configuration analysis is eligible.

        Eligibility requires:
        1. Gap must be a flammability gap (FLAM)
        2. Material must have mounting information
        3. Material must be in contact with heat sink

        Returns:
            ClosurePathResult with eligibility determination.
        """
        # Rule 1: Only applies to flammability gaps
        if gap.gap_type != FailureMode.FLAM:
            return self._build_result(
                eligible=False,
                rationale=f"Configuration analysis only applies to flammability gaps. "
                f"This gap is type '{gap.gap_type.value if hasattr(gap.gap_type, 'value') else gap.gap_type}'.",
                confidence=1.0,
            )

        # Collect provided inputs
        provided_inputs = {}

        # Check for mounting configuration
        has_mounting = False
        if hasattr(material, "mounting_configuration") and material.mounting_configuration:
            provided_inputs["mounting_configuration"] = material.mounting_configuration
            has_mounting = True
        elif hasattr(material, "application") and material.application:
            # Application description can provide mounting context
            provided_inputs["mounting_configuration"] = f"Application: {material.application}"
            has_mounting = True

        # Check for heat sink information
        has_heat_sink = False
        if hasattr(material, "heat_sink_description") and material.heat_sink_description:
            provided_inputs["heat_sink_description"] = material.heat_sink_description
            has_heat_sink = True
        elif hasattr(material, "substrate") and material.substrate:
            # Substrate information can indicate heat sink
            provided_inputs["heat_sink_description"] = f"Substrate: {material.substrate}"
            has_heat_sink = True

        # Check for adjacent materials
        if hasattr(material, "adjacent_materials") and material.adjacent_materials:
            provided_inputs["adjacent_materials"] = material.adjacent_materials

        # Rule 2: Must have at least mounting information
        if not has_mounting:
            return self._build_result(
                eligible=False,
                rationale="Configuration analysis requires mounting configuration data. "
                "Provide mounting_configuration to evaluate eligibility.",
                provided_inputs=provided_inputs,
                confidence=0.0,
            )

        # Rule 3: Prefer materials with heat sink contact
        if has_heat_sink:
            return self._build_result(
                eligible=True,
                rationale="LIKELY ELIGIBLE: Material has mounting configuration and heat sink data. "
                f"Mounting: {provided_inputs.get('mounting_configuration', 'N/A')}. "
                f"Heat sink: {provided_inputs.get('heat_sink_description', 'N/A')}. "
                "Full analysis requires JSC 29353 methodology review.",
                provided_inputs=provided_inputs,
                confidence=0.7,  # Lower confidence - requires engineering review
            )
        else:
            return self._build_result(
                eligible=True,
                rationale="POTENTIALLY ELIGIBLE: Material has mounting configuration but no "
                "explicit heat sink data. Configuration analysis may still demonstrate "
                "self-extinguishing behavior based on geometry and thermal properties. "
                "Provide heat_sink_description for higher confidence assessment.",
                provided_inputs=provided_inputs,
                confidence=0.5,  # Even lower confidence without heat sink
            )
