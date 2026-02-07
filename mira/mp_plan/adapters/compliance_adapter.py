#!/usr/bin/env python3
"""
Module: Compliance Evaluation Adapter
Purpose: Wraps ComplianceConductor for V2 session integration

BoundState AI 2026
Version: 2.0.0
Classification: BoundState Proprietary

This adapter transforms between V2 session models and the
existing ComplianceConductor interface, implementing the
V2 gap type split (Deficiency vs Nonconformance).

Compliance: NASA-STD-8739.8B, SWE-013, SWE-033
Safety Critical: False
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from mira.compliance.models.enums import GapTrigger
from mira.compliance.models.gaps import GapSignal

from ..models import (
    DeficiencySignal,
    EnvironmentDefinition,
    MaterialEntry,
    MaterialResolutionResult,
    NonconformanceSignal,
    PlanGeneratorSession,
    split_gap_signals,
)

LOGGER = logging.getLogger(__name__)

__version__ = "2.0.0"
__safety_critical__ = False


class ComplianceEvaluationAdapter:
    """
    Adapts ComplianceConductor to V2 session model.

    This adapter:
    - Transforms V2 session state to ComplianceConductor input
    - Runs compliance evaluation
    - Splits GapSignals into DeficiencySignal/NonconformanceSignal (V2)
    - Returns MPR determinations and split gaps
    """

    def __init__(self):
        """Initialize the adapter."""
        self._conductor = None

    def _get_conductor(self):
        """Lazy-load the compliance conductor."""
        if self._conductor is None:
            try:
                from mira.compliance.conductor import ComplianceConductor
                from mira.compliance.models.mpr import create_mpr_index_from_yaml
                from mira.compliance.models.policy import ConductorPolicy

                # Load MPR index and policy
                # TODO: Make paths configurable
                self._conductor = ComplianceConductor()
            except ImportError as e:
                LOGGER.warning(f"Could not import ComplianceConductor: {e}")
                self._conductor = None
        return self._conductor

    def evaluate_material_in_environment(
        self,
        material: MaterialEntry,
        resolution: MaterialResolutionResult,
        environment: EnvironmentDefinition,
    ) -> tuple[list[GapSignal], list[dict[str, Any]]]:
        """
        Evaluate a single material in a specific environment.

        Args:
            material: Material entry.
            resolution: MAPTIS resolution for the material.
            environment: Environment to evaluate in.

        Returns:
            Tuple of (gap_signals, mpr_determinations).
        """
        gaps = []
        determinations = []

        # Check flammability against O2 concentration
        if environment.o2_pct > 23.5:
            # High O2 environment - check flammability rating
            if resolution.flam_rating not in ("A", "B"):
                from mira.compliance.models.enums import (
                    FailureMode,
                    GapSeverity,
                    GapTrigger,
                )

                gap = GapSignal(
                    gap_id=f"FLAM:{material.id}:{environment.environment_id}",
                    gap_type=FailureMode.FLAM,
                    trigger=GapTrigger.RATING_NON_A,
                    trigger_parameter="flam_rating",
                    material_id=material.id,
                    environment_id=environment.environment_id,
                    failing_rating=resolution.flam_rating,
                    severity=(
                        GapSeverity.CRITICAL
                        if resolution.flam_rating in ("X", "D")
                        else GapSeverity.HIGH
                    ),
                    confidence=0.95,
                    summary=f"Flammability rating {resolution.flam_rating} in {environment.o2_pct}% O2",
                    source_adapter="compliance_adapter",
                    suggested_basis="test",
                )
                gaps.append(gap)

        # Check TVS/outgassing
        if resolution.tvs_rating not in ("A",):
            from mira.compliance.models.enums import (
                FailureMode,
                GapSeverity,
                GapTrigger,
            )

            gap = GapSignal(
                gap_id=f"TVS:{material.id}:{environment.environment_id}",
                gap_type=FailureMode.TVS,
                trigger=GapTrigger.RATING_NON_A,
                trigger_parameter="tvs_rating",
                material_id=material.id,
                environment_id=environment.environment_id,
                failing_rating=resolution.tvs_rating,
                severity=GapSeverity.MEDIUM,
                confidence=0.9,
                summary=f"TVS rating {resolution.tvs_rating}",
                source_adapter="compliance_adapter",
                suggested_basis="test",
            )
            gaps.append(gap)

        return gaps, determinations

    def evaluate_session(
        self,
        session: PlanGeneratorSession,
    ) -> tuple[list[DeficiencySignal], list[NonconformanceSignal], list[dict[str, Any]]]:
        """
        Run full compliance evaluation on a session.

        Args:
            session: V2 Plan Generator session.

        Returns:
            Tuple of (deficiencies, nonconformances, mpr_determinations).
        """
        all_gaps = []
        all_determinations = []

        # Evaluate each material in each of its environments
        for usage in session.material_environment_usages:
            material = session.get_material(usage.material_id)
            resolution = session.get_resolution(usage.material_id)
            environment = session.get_environment(usage.environment_id)

            if not material or not environment:
                continue

            if not resolution:
                # Create deficiency for unresolved material
                from mira.compliance.models.enums import (
                    FailureMode,
                    GapSeverity,
                    GapTrigger,
                )

                gap = GapSignal(
                    gap_id=f"MISSING:{material.id}",
                    gap_type=FailureMode.MISSING_INPUT,
                    trigger=GapTrigger.MISSING_DATA,
                    trigger_parameter="maptis_resolution",
                    material_id=material.id,
                    severity=GapSeverity.HIGH,
                    confidence=1.0,
                    summary=f"Material {material.name} not resolved in MAPTIS",
                    source_adapter="compliance_adapter",
                    suggested_basis="not_applicable",
                )
                all_gaps.append(gap)
                continue

            # Evaluate material in environment
            gaps, determinations = self.evaluate_material_in_environment(
                material, resolution, environment
            )
            all_gaps.extend(gaps)
            all_determinations.extend(determinations)

        # Split gaps into V2 types
        deficiencies, nonconformances = split_gap_signals(all_gaps)

        return deficiencies, nonconformances, all_determinations


def get_compliance_adapter() -> ComplianceEvaluationAdapter:
    """Get a compliance evaluation adapter instance."""
    return ComplianceEvaluationAdapter()
