#!/usr/bin/env python3
"""
Module: Applicability Engine (Engine B)
Purpose: MPR applicability determination

BoundState AI 2026
Version: 2.0.0
Classification: BoundState Proprietary

Engine B responsibilities:
- Determine which MPRs apply to each material/environment
- Use MPRIndex (not hardcoded count!)
- Track applicability decisions with evidence

Fran Fix #1: MPR count from index, not hardcoded "213"

Compliance: NASA-STD-8739.8B, SWE-013, SWE-033
Safety Critical: False
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Optional

from mira.compliance.models.enums import ApplicabilityStatus

from ..models import (
    DecisionGraph,
    EnvironmentDefinition,
    HardwareContext,
    MaterialEntry,
    MaterialResolutionResult,
    PlanGeneratorSession,
)

LOGGER = logging.getLogger(__name__)

__version__ = "2.0.0"
__safety_critical__ = False


class ApplicabilityEngine:
    """
    Engine B: MPR Applicability Determination.

    Responsible for:
    - Loading MPR index (not hardcoded!)
    - Determining which MPRs apply to each material/environment
    - Tracking applicability decisions in the decision graph

    Fran Fix #1: "Hardcoded '213 MPRs'" -> use len(mpr_index.mprs)
    """

    def __init__(self, mpr_index: Optional[Any] = None):
        """
        Initialize the applicability engine.

        Args:
            mpr_index: Optional MPR index. Loaded from YAML if not provided.
        """
        self._mpr_index = mpr_index
        self._loaded = False

    def _ensure_loaded(self) -> None:
        """Ensure MPR index is loaded."""
        if self._loaded:
            return

        if self._mpr_index is None:
            try:
                from mira.compliance.models.mpr import create_mpr_index_from_yaml

                # Try to load from default location
                self._mpr_index = create_mpr_index_from_yaml()
                LOGGER.info(f"Loaded MPR index with {self.mpr_count} MPRs")
            except Exception as e:
                LOGGER.warning(f"Could not load MPR index: {e}")
                self._mpr_index = None

        self._loaded = True

    @property
    def mpr_count(self) -> int:
        """
        Get MPR count from index.

        Fran Fix #1: Never hardcode "213" - always derive from index.
        """
        self._ensure_loaded()
        if self._mpr_index is None:
            return 0
        return len(self._mpr_index.mprs) if hasattr(self._mpr_index, "mprs") else 0

    def determine_applicability(
        self,
        material: MaterialEntry,
        resolution: MaterialResolutionResult,
        environment: EnvironmentDefinition,
        hardware_context: Optional[HardwareContext] = None,
    ) -> dict[str, dict[str, Any]]:
        """
        Determine MPR applicability for a material/environment pair.

        Args:
            material: Material entry.
            resolution: MAPTIS resolution.
            environment: Environment definition.
            hardware_context: Optional hardware context.

        Returns:
            Dict mapping MPR ID to applicability decision.
        """
        self._ensure_loaded()

        applicability = {}

        # Basic applicability rules based on environment
        is_high_o2 = environment.o2_pct > 23.5
        is_habitable = environment.habitable
        is_vacuum = environment.vacuum_exposure

        # Example MPR applicability rules
        # In production, this would use the full MPR index

        # MPR 44 - Flammability
        if is_high_o2:
            applicability["MPR_44"] = {
                "status": ApplicabilityStatus.APPLICABLE.value,
                "rationale": f"O2 concentration {environment.o2_pct}% > 23.5%",
                "triggered_by": "o2_pct",
            }
        else:
            applicability["MPR_44"] = {
                "status": ApplicabilityStatus.NOT_APPLICABLE_BY_CONDITION.value,
                "rationale": f"O2 concentration {environment.o2_pct}% <= 23.5%",
                "triggered_by": "o2_pct",
            }

        # MPR 67 - Outgassing (TVS)
        if is_vacuum or is_habitable:
            applicability["MPR_67"] = {
                "status": ApplicabilityStatus.APPLICABLE.value,
                "rationale": "Vacuum exposure or habitable volume",
                "triggered_by": "vacuum_exposure" if is_vacuum else "habitable",
            }

        # MPR 89 - Toxicity
        if is_habitable:
            applicability["MPR_89"] = {
                "status": ApplicabilityStatus.APPLICABLE.value,
                "rationale": "Habitable volume - crew exposure possible",
                "triggered_by": "habitable",
            }

        return applicability

    def build_applicability_matrix(
        self,
        session: PlanGeneratorSession,
    ) -> dict[str, dict[str, Any]]:
        """
        Build complete applicability matrix for session.

        Args:
            session: Plan generator session.

        Returns:
            Applicability matrix (mpr_id -> decision dict).
        """
        LOGGER.info(
            f"Building applicability matrix for {len(session.materials)} materials"
        )

        matrix = {}

        for usage in session.material_environment_usages:
            material = session.get_material(usage.material_id)
            resolution = session.get_resolution(usage.material_id)
            environment = session.get_environment(usage.environment_id)

            if not material or not environment:
                continue

            # Get applicability for this material/environment
            key = f"{material.id}:{environment.environment_id}"

            if resolution:
                applicability = self.determine_applicability(
                    material=material,
                    resolution=resolution,
                    environment=environment,
                    hardware_context=session.hardware_context,
                )
                matrix[key] = applicability
            else:
                # Mark as unknown without resolution
                matrix[key] = {
                    "MPR_ALL": {
                        "status": "unknown",
                        "rationale": "Material not resolved in MAPTIS",
                    }
                }

        LOGGER.info(f"Built applicability matrix with {len(matrix)} entries")
        return matrix

    def update_decision_graph(
        self,
        graph: DecisionGraph,
        session: PlanGeneratorSession,
    ) -> None:
        """
        Add applicability nodes to decision graph.

        Args:
            graph: Decision graph to update.
            session: Plan generator session.
        """
        for usage in session.material_environment_usages:
            material = session.get_material(usage.material_id)
            environment = session.get_environment(usage.environment_id)

            if not material or not environment:
                continue

            # Add applicability node
            node_id = graph.add_node(
                node_type="applicability",
                object_id=f"{material.id}:{environment.environment_id}",
                object_type="ApplicabilityDecision",
                depends_on=[
                    f"material:{material.id}",
                    f"environment:{environment.environment_id}",
                ],
                derived_from_fields=[
                    f"environment.{environment.environment_id}.o2_pct",
                    f"environment.{environment.environment_id}.habitable",
                    f"environment.{environment.environment_id}.vacuum_exposure",
                ],
            )

            # Add edges
            graph.add_edge(
                from_node=f"material:{material.id}",
                to_node=node_id,
                edge_type="depends_on",
            )
            graph.add_edge(
                from_node=f"environment:{environment.environment_id}",
                to_node=node_id,
                edge_type="depends_on",
            )

    def run(
        self,
        session: PlanGeneratorSession,
    ) -> dict[str, dict[str, Any]]:
        """
        Run applicability determination.

        Args:
            session: Plan generator session.

        Returns:
            Applicability matrix.
        """
        # Build matrix
        matrix = self.build_applicability_matrix(session)

        # Update session
        session.applicability_matrix = matrix

        # Update decision graph if present
        if session.decision_graph:
            self.update_decision_graph(session.decision_graph, session)

        return matrix


def get_applicability_engine() -> ApplicabilityEngine:
    """Get an applicability engine instance."""
    return ApplicabilityEngine()
