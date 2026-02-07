#!/usr/bin/env python3
"""
Module: Minor Quantity Aggregation Engine
Purpose: Zone-based aggregation for minor quantity closure path

BoundState AI 2026
Version: 2.0.0
Classification: BoundState Proprietary

Implements Fran Fix #4: Minor quantity aggregation by zone

Fran: "NASA reviewers don't just check mass/area; they check
aggregation and interaction."

Compliance: NASA-STD-8739.8B, SWE-013, SWE-033
Safety Critical: False
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from mira.compliance.models.enums import SourceType
from mira.compliance.models.evidence import EvidenceRef

from ..models import (
    GroupingAssumption,
    MinorQuantityAggregation,
    MinorQuantityGroup,
    PlanGeneratorSession,
)

LOGGER = logging.getLogger(__name__)

__version__ = "2.0.0"
__safety_critical__ = False

# Minor quantity thresholds per MPR 44(c)
MINOR_QTY_MASS_LIMIT_G = 45.0
MINOR_QTY_AREA_LIMIT_CM2 = 13.0


class MinorQuantityEngine:
    """
    Engine for minor quantity aggregation analysis.

    Fran Fix #4: "Oversimplified minor quantity" -> aggregate by zone.

    Materials are grouped by:
    - Environment zone
    - Ignition source proximity
    - Physical adjacency

    Group totals determine minor quantity eligibility, not per-material.
    """

    def __init__(
        self,
        mass_limit_g: float = MINOR_QTY_MASS_LIMIT_G,
        area_limit_cm2: float = MINOR_QTY_AREA_LIMIT_CM2,
    ):
        """
        Initialize the minor quantity engine.

        Args:
            mass_limit_g: Mass limit in grams (default: 45g per MPR 44(c)).
            area_limit_cm2: Area limit in cm^2 (default: 13cm^2 per MPR 44(c)).
        """
        self.mass_limit_g = mass_limit_g
        self.area_limit_cm2 = area_limit_cm2

    def create_groups(
        self,
        session: PlanGeneratorSession,
    ) -> list[MinorQuantityGroup]:
        """
        Create aggregation groups from session data.

        Groups materials by environment and adjacency.

        Args:
            session: Plan generator session.

        Returns:
            List of minor quantity groups.
        """
        groups = {}

        for usage in session.material_environment_usages:
            material = session.get_material(usage.material_id)
            if not material:
                continue

            # Determine grouping key
            env_id = usage.environment_id
            ignition_class = usage.ignition_source_proximity or "none"
            adjacency = usage.adjacency_group or "default"

            group_key = f"{env_id}:{ignition_class}:{adjacency}"

            if group_key not in groups:
                groups[group_key] = MinorQuantityGroup(
                    environment_id=env_id,
                    ignition_source_class=ignition_class,
                    adjacency_group=adjacency,
                )

            group = groups[group_key]
            group.material_ids.append(material.id)

            # Add mass/area if available
            if material.mass_g:
                group.total_mass_g += material.mass_g
            if material.surface_area_cm2:
                group.total_surface_area_cm2 += material.surface_area_cm2

        return list(groups.values())

    def evaluate_group_eligibility(
        self,
        group: MinorQuantityGroup,
    ) -> None:
        """
        Evaluate minor quantity eligibility for a group.

        Updates the group's eligible and eligibility_rationale fields.

        Args:
            group: Group to evaluate.
        """
        mass_ok = group.total_mass_g <= self.mass_limit_g
        area_ok = group.total_surface_area_cm2 <= self.area_limit_cm2

        if mass_ok and area_ok:
            group.eligible = True
            group.eligibility_rationale = (
                f"Group total {group.total_mass_g:.1f}g <= {self.mass_limit_g}g "
                f"and {group.total_surface_area_cm2:.1f}cm² <= {self.area_limit_cm2}cm²"
            )
        else:
            group.eligible = False
            reasons = []
            if not mass_ok:
                reasons.append(
                    f"mass {group.total_mass_g:.1f}g > {self.mass_limit_g}g limit"
                )
            if not area_ok:
                reasons.append(
                    f"area {group.total_surface_area_cm2:.1f}cm² > {self.area_limit_cm2}cm² limit"
                )
            group.eligibility_rationale = f"Exceeds limit: {'; '.join(reasons)}"

        # Add evidence reference
        group.evidence = EvidenceRef(
            source_type=SourceType.STANDARD,
            source_id="NASA-STD-6016C",
            source_version="Rev C w/Change 2",
            locator="Section 4.2.1.1, MPR 44(c)",
            confidence=1.0,
            confidence_basis="Direct standard reference",
            retrieved_at=datetime.now(),
            retrieval_method="minor_quantity_engine",
        )

    def detect_grouping_assumptions(
        self,
        session: PlanGeneratorSession,
    ) -> list[GroupingAssumption]:
        """
        Detect grouping assumptions that need user confirmation.

        Args:
            session: Plan generator session.

        Returns:
            List of grouping assumptions needing confirmation.
        """
        assumptions = []

        # Check for materials without explicit adjacency
        for usage in session.material_environment_usages:
            if usage.adjacency_group is None:
                material = session.get_material(usage.material_id)
                if not material:
                    continue

                # Find other materials in same environment
                same_env = [
                    u
                    for u in session.material_environment_usages
                    if u.environment_id == usage.environment_id
                    and u.material_id != usage.material_id
                ]

                if same_env:
                    other_materials = [
                        session.get_material(u.material_id)
                        for u in same_env
                        if session.get_material(u.material_id)
                    ]

                    assumptions.append(
                        GroupingAssumption(
                            description=(
                                f"Are {material.name} and "
                                f"{other_materials[0].name if other_materials else 'other materials'} "
                                f"co-located in the same zone?"
                            ),
                            materials_involved=[material.id]
                            + [m.id for m in other_materials[:3]],
                            assumed_value=True,  # Conservatively assume grouped
                        )
                    )

        return assumptions

    def run(
        self,
        session: PlanGeneratorSession,
    ) -> MinorQuantityAggregation:
        """
        Run minor quantity aggregation analysis.

        Args:
            session: Plan generator session.

        Returns:
            MinorQuantityAggregation with all groups and assumptions.
        """
        LOGGER.info("Running minor quantity aggregation")

        # Create groups
        groups = self.create_groups(session)

        # Evaluate eligibility for each group
        for group in groups:
            self.evaluate_group_eligibility(group)

        # Detect grouping assumptions
        assumptions = self.detect_grouping_assumptions(session)

        # Calculate program totals
        total_mass = sum(g.total_mass_g for g in groups)
        total_area = sum(g.total_surface_area_cm2 for g in groups)

        # Create methodology evidence
        methodology_evidence = EvidenceRef(
            source_type=SourceType.STANDARD,
            source_id="NASA-STD-6016C",
            source_version="Rev C w/Change 2",
            locator="Section 4.2.1.1, MPR 44(c)",
            quote=(
                "Materials used in quantities less than 45 grams "
                "and having less than 13 cm² of exposed surface area..."
            ),
            confidence=1.0,
            confidence_basis="Direct standard reference",
            retrieved_at=datetime.now(),
            retrieval_method="minor_quantity_engine",
        )

        aggregation = MinorQuantityAggregation(
            groups=groups,
            grouping_assumptions=assumptions,
            program_total_mass_g=total_mass,
            program_total_area_cm2=total_area,
            methodology_evidence=methodology_evidence,
        )

        LOGGER.info(
            f"Minor quantity analysis complete: "
            f"{len(groups)} groups, "
            f"{len([g for g in groups if g.eligible])} eligible, "
            f"{len(assumptions)} assumptions"
        )

        return aggregation


def get_minor_quantity_engine() -> MinorQuantityEngine:
    """Get a minor quantity engine instance."""
    return MinorQuantityEngine()
