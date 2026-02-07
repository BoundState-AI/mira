#!/usr/bin/env python3
"""
Module: Minor Quantity Aggregation Models
Purpose: Zone-based aggregation for M&P Plan Generator V2

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

import uuid
from typing import Optional

from pydantic import BaseModel, Field

from mira.compliance.models.evidence import EvidenceRef

__version__ = "2.0.0"
__safety_critical__ = False


class MinorQuantityGroup(BaseModel):
    """
    Aggregation group for minor quantity calculation.

    Materials are grouped by environment, ignition source proximity,
    and physical adjacency for aggregate limit checking.

    Fran Fix #4: "Oversimplified minor quantity" -> aggregate by zone.

    NASA reviewers check aggregation and interaction, not just per-material.
    """

    group_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    """Unique identifier for this group."""

    # Grouping keys
    environment_id: str
    """Environment zone for this group."""

    ignition_source_class: str
    """Ignition source proximity: 'none', 'low_energy', 'high_energy'."""

    adjacency_group: str
    """Adjacency identifier for co-located materials."""

    # Members
    material_ids: list[str] = Field(default_factory=list)
    """Materials in this group."""

    # Aggregated values
    total_mass_g: float = 0.0
    """Total mass of all materials in group (grams)."""

    total_surface_area_cm2: float = 0.0
    """Total exposed surface area in group (cm^2)."""

    # Eligibility
    eligible: bool = False
    """Whether this group is eligible for minor quantity exception."""

    eligibility_rationale: str = ""
    """Rationale for eligibility determination."""

    # Evidence (MPR 44(c) citation)
    evidence: Optional[EvidenceRef] = None
    """Evidence for minor quantity determination."""

    model_config = {"extra": "forbid", "populate_by_name": True}


class GroupingAssumption(BaseModel):
    """
    Assumption about material grouping that needs user confirmation.

    When the system cannot determine grouping automatically,
    it generates an assumption that requires user validation.
    """

    assumption_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    """Unique identifier for this assumption."""

    description: str
    """Description of the assumption being made."""

    materials_involved: list[str] = Field(default_factory=list)
    """Material IDs involved in this assumption."""

    assumed_value: bool
    """The assumed grouping (True = grouped together)."""

    confirmed: bool = False
    """Whether user has confirmed this assumption."""

    confirmed_by: Optional[str] = None
    """Who confirmed this assumption."""

    model_config = {"extra": "forbid", "populate_by_name": True}


class MinorQuantityAggregation(BaseModel):
    """
    Complete minor quantity analysis.

    Fran: "NASA reviewers don't just check mass/area; they check
    aggregation and interaction."

    This model captures the full zone-based aggregation with
    grouping assumptions that may need user confirmation.

    Compliance: SWE-013 (minor quantity tracking).
    """

    # Groupings
    groups: list[MinorQuantityGroup] = Field(default_factory=list)
    """All minor quantity groups."""

    # Grouping assumptions that need confirmation
    grouping_assumptions: list[GroupingAssumption] = Field(default_factory=list)
    """Assumptions that need user validation."""

    # Overall program totals (for reviewer awareness)
    program_total_mass_g: float = 0.0
    """Total mass across all groups (grams)."""

    program_total_area_cm2: float = 0.0
    """Total surface area across all groups (cm^2)."""

    # Evidence for methodology
    methodology_evidence: Optional[EvidenceRef] = None
    """Evidence for the aggregation methodology used."""

    model_config = {"extra": "forbid", "populate_by_name": True}

    def get_group_for_material(
        self,
        material_id: str,
        environment_id: str,
    ) -> Optional[MinorQuantityGroup]:
        """
        Find the group containing a specific material in an environment.

        Args:
            material_id: Material to find.
            environment_id: Environment to search in.

        Returns:
            The group containing the material, or None.
        """
        for group in self.groups:
            if (
                group.environment_id == environment_id
                and material_id in group.material_ids
            ):
                return group
        return None

    def is_material_eligible(
        self,
        material_id: str,
        environment_id: str,
    ) -> tuple[bool, str]:
        """
        Check if a material is eligible for minor quantity exception.

        Args:
            material_id: Material to check.
            environment_id: Environment to check in.

        Returns:
            Tuple of (eligible, rationale).
        """
        group = self.get_group_for_material(material_id, environment_id)
        if group is None:
            return False, "Material not in any minor quantity group"
        return group.eligible, group.eligibility_rationale

    def has_unconfirmed_assumptions(self) -> bool:
        """Check if there are unconfirmed grouping assumptions."""
        return any(not a.confirmed for a in self.grouping_assumptions)
