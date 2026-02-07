#!/usr/bin/env python3
"""
Module: Gap Resolution
Purpose: Closure path implementations for M&P Plan Generator V2

BoundState AI 2026
Version: 2.0.0
Classification: BoundState Proprietary

Implements the "Senior Engineer Moves" - deterministic closure paths
for resolving nonconformances per NASA-STD-6016C.

Closure Paths:
- MINOR_QUANTITY: MPR 44(c) - mass/area threshold check
- CONFIGURATION_ANALYSIS: JSC 29353 - self-extinguishing in config
- HEAT_SINK: MPR 44(g) - bonded to metal heat sink
- SUBSTITUTION: Alternative A-rated material
- TEST_PROGRAM: Additional testing at use conditions
- FULL_MUA: Full Material Usage Agreement

Compliance: NASA-STD-8739.8B, SWE-013, SWE-033
Safety Critical: False
"""

from .base import ClosurePathBase, ClosurePathResult
from .minor_quantity import MinorQuantityPath
from .configuration import ConfigurationAnalysisPath
from .heat_sink import HeatSinkPath
from .substitution import SubstitutionPath
from .test_program import TestProgramPath
from .full_mua import FullMUAPath

__version__ = "2.0.0"
__safety_critical__ = False

__all__ = [
    "ClosurePathBase",
    "ClosurePathResult",
    "MinorQuantityPath",
    "ConfigurationAnalysisPath",
    "HeatSinkPath",
    "SubstitutionPath",
    "TestProgramPath",
    "FullMUAPath",
    "CLOSURE_PATH_REGISTRY",
    "get_available_paths",
    "check_all_paths",
]


# Registry of all closure paths - order matters for presentation
# Paths are listed in order of preference (least invasive first)
CLOSURE_PATH_REGISTRY = {
    "MINOR_QUANTITY": MinorQuantityPath,
    "CONFIGURATION_ANALYSIS": ConfigurationAnalysisPath,
    "HEAT_SINK": HeatSinkPath,
    "SUBSTITUTION": SubstitutionPath,
    "TEST_PROGRAM": TestProgramPath,
    "FULL_MUA": FullMUAPath,
}


def get_available_paths() -> list[str]:
    """Get list of available closure path IDs."""
    return list(CLOSURE_PATH_REGISTRY.keys())


def check_all_paths(
    gap,
    material,
    environment,
    session,
) -> list[ClosurePathResult]:
    """
    Check all closure paths for eligibility.

    Args:
        gap: NonconformanceSignal to resolve.
        material: MaterialEntry with the gap.
        environment: EnvironmentDefinition for evaluation.
        session: PlanGeneratorSession with full context.

    Returns:
        List of ClosurePathResult for each path.
    """
    results = []
    for path_id, path_class in CLOSURE_PATH_REGISTRY.items():
        path = path_class()
        result = path.check_eligibility(gap, material, environment, session)
        results.append(result)
    return results
