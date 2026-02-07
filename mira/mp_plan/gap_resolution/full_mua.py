#!/usr/bin/env python3
"""
Module: Full MUA Closure Path
Purpose: MPR 44(j) - Full Material Usage Agreement

BoundState AI 2026
Version: 2.0.0
Classification: BoundState Proprietary

Implements MPR 44(j) full MUA exception:
"A Material Usage Agreement may be generated documenting
rationale for use despite non-compliance."

Key Rules (from Fran Fix #4):
1. MUA requires formal risk acceptance
2. Must document rationale, mitigations, constraints
3. Requires approval authority signature
4. Creates operational constraints for flight hardware
5. Last resort when other paths are not viable

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


class FullMUAPath(ClosurePathBase):
    """
    MPR 44(j) - Full Material Usage Agreement.

    When no other closure path is viable, a formal MUA documents
    the rationale for using non-compliant material with risk acceptance.

    Citation: NASA-STD-6016C Section 4.2.4.3(j)

    This is typically the path of last resort as it:
    - Requires formal risk documentation
    - Creates operational constraints
    - Requires approval authority signature
    - May impact flight readiness reviews
    """

    path_id = "FULL_MUA"
    path_title = "Material Usage Agreement"
    path_description = "Formal risk acceptance with documented rationale"
    citation = "NASA-STD-6016C Section 4.2.4.3(j)"
    required_inputs = [
        "use_rationale",
        "risk_assessment",
        "mitigation_measures",
        "operational_constraints",
        "approval_authority",
    ]
    output_artifact = "mua_document"

    def check_eligibility(
        self,
        gap: "NonconformanceSignal",
        material: "MaterialEntry",
        environment: "EnvironmentDefinition",
        session: "PlanGeneratorSession",
    ) -> ClosurePathResult:
        """
        Check if Full MUA is eligible.

        Full MUA is always available as a fallback, but should be
        considered only when other paths are not viable.

        Eligibility is determined by:
        1. Other closure paths have been evaluated and rejected
        2. Material is critical to design (no substitutes)
        3. Risk can be documented and mitigated

        Returns:
            ClosurePathResult with eligibility determination.
        """
        provided_inputs = {}

        # MUA applies to all gap types
        gap_type_value = gap.gap_type.value if hasattr(gap.gap_type, "value") else str(gap.gap_type)
        provided_inputs["gap_type"] = gap_type_value

        # Check if other paths have been evaluated
        other_paths_checked = False
        other_eligible_paths = []

        # Look for closure evaluations in session
        if hasattr(session, "closure_evaluations"):
            for eval_result in session.closure_evaluations.get(gap.nonconformance_id, []):
                if eval_result.path_id != "FULL_MUA":
                    other_paths_checked = True
                    if eval_result.eligible:
                        other_eligible_paths.append(eval_result.path_id)

        provided_inputs["other_paths_checked"] = other_paths_checked
        provided_inputs["other_eligible_paths"] = other_eligible_paths

        # Collect material context
        provided_inputs["material_name"] = material.name
        provided_inputs["application"] = material.application

        if material.maptis_code:
            provided_inputs["maptis_code"] = material.maptis_code

        # MUA categories based on gap type
        mua_category = self._determine_mua_category(gap.gap_type, environment)
        provided_inputs["mua_category"] = mua_category

        # Always eligible but with appropriate guidance
        if other_eligible_paths:
            return self._build_result(
                eligible=True,
                rationale=f"AVAILABLE BUT OTHER PATHS PREFERRED: Full MUA is available, "
                f"but {len(other_eligible_paths)} other closure path(s) are also eligible: "
                f"{', '.join(other_eligible_paths)}. Consider those options first as they "
                "may have lower approval burden.",
                provided_inputs=provided_inputs,
                confidence=0.5,  # Lower confidence to indicate preference for other paths
            )
        elif other_paths_checked:
            return self._build_result(
                eligible=True,
                rationale=f"RECOMMENDED: Other closure paths evaluated and not viable. "
                f"Full MUA ({mua_category}) is appropriate for this gap. "
                "Document use rationale, risk assessment, and mitigation measures. "
                "Will require approval authority signature.",
                provided_inputs=provided_inputs,
                confidence=0.9,
            )
        else:
            return self._build_result(
                eligible=True,
                rationale=f"ELIGIBLE: Full MUA ({mua_category}) is available for this gap. "
                "Recommend evaluating MINOR_QUANTITY, CONFIGURATION_ANALYSIS, HEAT_SINK, "
                "SUBSTITUTION, and TEST_PROGRAM paths first. MUA requires formal risk "
                "acceptance and approval authority signature.",
                provided_inputs=provided_inputs,
                confidence=0.6,
            )

    def _determine_mua_category(
        self,
        gap_type: FailureMode,
        environment: "EnvironmentDefinition",
    ) -> str:
        """Determine the MUA category based on gap type and environment."""
        # MUA categories per NASA-STD-6016C
        if gap_type == FailureMode.FLAM:
            if environment.o2_pct > 30:
                return "Category A - High O2 Flammability"
            elif environment.o2_pct > 23.5:
                return "Category B - Elevated O2 Flammability"
            else:
                return "Category C - Standard Flammability"
        elif gap_type == FailureMode.OFFGAS:
            return "Category D - Offgassing/Toxicity"
        elif gap_type == FailureMode.SCC:
            return "Category E - Stress Corrosion"
        elif gap_type == FailureMode.HE:
            return "Category F - Hydrogen Embrittlement"
        elif gap_type == FailureMode.COMPAT:
            return "Category G - Compatibility"
        else:
            return "Category H - General Non-Compliance"
