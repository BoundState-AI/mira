#!/usr/bin/env python3
"""
Module: Test Program Closure Path
Purpose: MPR 44(i) - Additional testing at use conditions

BoundState AI 2026
Version: 2.0.0
Classification: BoundState Proprietary

Implements MPR 44(i) test program exception:
"Materials may be used if additional testing demonstrates
acceptable performance at actual use conditions."

Key Rules (from Fran Fix #4):
1. Test must be at actual use conditions (O2%, pressure, temp)
2. Test must be per NASA-STD-6001 methodology
3. Results must demonstrate A-rating at use conditions
4. New test data creates precedent for future use

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


class TestProgramPath(ClosurePathBase):
    """
    MPR 44(i) - Test Program.

    Materials not meeting requirements at standard test conditions
    may be retested at actual use conditions to demonstrate compliance.

    Citation: NASA-STD-6016C Section 4.2.4.3(i)

    This path requires:
    - Definition of actual use conditions
    - Test plan per NASA-STD-6001
    - Test execution and reporting
    - A-rating demonstration at use conditions
    """

    path_id = "TEST_PROGRAM"
    path_title = "Additional Testing"
    path_description = "Test at actual use conditions per NASA-STD-6001"
    citation = "NASA-STD-6016C Section 4.2.4.3(i)"
    required_inputs = [
        "test_o2_pct",
        "test_pressure_psia",
        "test_temp_c",
        "test_methodology",
        "test_facility",
        "estimated_duration_weeks",
    ]
    output_artifact = "test_program_plan"

    # Test deltas that trigger this path
    O2_DELTA_THRESHOLD = 2.0  # % absolute difference
    PRESSURE_DELTA_THRESHOLD = 1.0  # psia absolute difference

    def check_eligibility(
        self,
        gap: "NonconformanceSignal",
        material: "MaterialEntry",
        environment: "EnvironmentDefinition",
        session: "PlanGeneratorSession",
    ) -> ClosurePathResult:
        """
        Check if additional testing is eligible.

        Testing is most appropriate when:
        1. Gap is due to test condition mismatch (test O2 < use O2)
        2. Material has favorable properties but wasn't tested at use conditions
        3. New test data would benefit multiple programs

        Returns:
            ClosurePathResult with eligibility determination.
        """
        provided_inputs = {}

        # Test program typically for flammability/offgassing where conditions matter
        applicable_gap_types = [
            FailureMode.FLAM,
            FailureMode.OFFGAS,
            FailureMode.COMPAT,
        ]

        if gap.gap_type not in applicable_gap_types:
            return self._build_result(
                eligible=False,
                rationale=f"Test program typically not applicable for gap type "
                f"'{gap.gap_type.value if hasattr(gap.gap_type, 'value') else gap.gap_type}'. "
                "Testing is most effective for flammability and offgassing gaps.",
                confidence=1.0,
            )

        # Check if this is a test condition mismatch
        test_o2 = None
        use_o2 = environment.o2_pct

        # Get test O2 from material resolution if available
        if hasattr(material, "test_o2_pct") and material.test_o2_pct is not None:
            test_o2 = material.test_o2_pct
            provided_inputs["test_o2_pct"] = test_o2
            provided_inputs["use_o2_pct"] = use_o2

        # Check for MAPTIS resolution data
        resolution = None
        for res in session.resolution_results:
            if res.material_id == material.id:
                resolution = res
                break

        if resolution and hasattr(resolution, "maptis_record") and resolution.maptis_record:
            record = resolution.maptis_record
            if hasattr(record, "test_o2_pct") and record.test_o2_pct is not None:
                test_o2 = record.test_o2_pct
                provided_inputs["test_o2_pct"] = test_o2
                provided_inputs["maptis_source"] = True

        provided_inputs["use_environment"] = {
            "o2_pct": environment.o2_pct,
            "pressure_psia": environment.pressure_psia,
            "temp_range_c": environment.temp_range_c,
        }

        # Determine eligibility based on test delta
        if test_o2 is not None:
            o2_delta = use_o2 - test_o2
            provided_inputs["o2_delta"] = o2_delta

            if o2_delta > 0:
                # Use O2 exceeds test O2 - testing at use conditions could resolve
                return self._build_result(
                    eligible=True,
                    rationale=f"RECOMMENDED: Use O2 ({use_o2}%) exceeds test O2 ({test_o2}%) "
                    f"by {o2_delta:.1f}%. Testing at use conditions per NASA-STD-6001 "
                    "could demonstrate A-rating and close this gap. "
                    "New test data would establish precedent.",
                    provided_inputs=provided_inputs,
                    confidence=0.9,
                )
            else:
                # Test O2 >= use O2, gap is likely due to other factors
                return self._build_result(
                    eligible=True,
                    rationale=f"POTENTIALLY ELIGIBLE: Test O2 ({test_o2}%) meets or exceeds "
                    f"use O2 ({use_o2}%). Gap may be due to other test condition differences. "
                    "Additional testing could address specific failure mode.",
                    provided_inputs=provided_inputs,
                    confidence=0.6,
                )
        else:
            # No test data available - testing is definitely needed
            return self._build_result(
                eligible=True,
                rationale="ELIGIBLE: No existing test data at use conditions. "
                f"Testing at O2={use_o2}%, {environment.pressure_psia} psia "
                "per NASA-STD-6001 would establish compliance baseline.",
                provided_inputs=provided_inputs,
                confidence=0.8,
            )
