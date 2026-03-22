#!/usr/bin/env python3
"""
Module: Plan Generator Session Model
Purpose: Main session state container for M&P Plan Generator V2

BoundState AI 2026
Version: 2.0.0
Classification: BoundState Proprietary

Implements all V2 features:
- Multi-environment support (Fran Fix #2)
- Split gap types (Fran Fix #7)
- Accepted open gaps (Fran Fix #8)
- Decision graph (Fran Fix #5, #12)
- Computation context (Fran Fix #10)
- LLM draft isolation (Fran Fix #11)

Compliance: NASA-STD-8739.8B, SWE-013, SWE-033
Safety Critical: False
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field, model_validator

from .aggregation import MinorQuantityAggregation
from .artifacts import GeneratedArtifact
from .blocking import BlockingQuestion, UserDecision
from .closure import AcceptedOpenGap, ClosureDecision, OperationalConstraint
from .context import ComputationContext
from .draft import DraftTextBox
from .environment import EnvironmentDefinition, MaterialEnvironmentUsage
from .gaps import DeficiencySignal, NonconformanceSignal
from .graph import DecisionGraph
from .materials import (
    COTSItem,
    HardwareContext,
    MaterialEntry,
    MaterialResolutionResult,
    OrgChart,
)

__version__ = "2.0.0"
__safety_critical__ = False


class PlanGeneratorSession(BaseModel):
    """
    Complete session state for M&P Plan Generator V2.

    This is the main container for all session data, implementing
    all 13 Fran corrections from the V2 specification.

    Changes from V1:
    - Multi-environment support (list of EnvironmentDefinition)
    - Split gap types (DeficiencySignal vs NonconformanceSignal)
    - Accepted open gaps (can generate with known gaps)
    - Decision graph (explicit dependency tracking)
    - Policy pack reference
    - Computation context with full hashes
    - LLM draft isolation (DraftTextBox)

    Compliance: SWE-013 (traceability), SWE-033 (persistence).
    """

    model_config = {"extra": "forbid", "populate_by_name": True}

    # -------------------------------------------------------------------------
    # Identity
    # -------------------------------------------------------------------------
    session_id: str
    """Unique session identifier."""

    created_at: datetime = Field(default_factory=datetime.now)
    """When session was created."""

    updated_at: datetime = Field(default_factory=datetime.now)
    """When session was last updated."""

    owner_username: Optional[str] = None
    """Authenticated username that owns this session."""

    source: str = "interactive_session"
    """Source of session creation."""

    # -------------------------------------------------------------------------
    # Program Context
    # -------------------------------------------------------------------------
    program_name: Optional[str] = None
    """Program name (e.g., 'ISS', 'HLS', 'Orion')."""

    program_phase: Optional[str] = None
    """Program phase (e.g., 'CDR', 'PDR', 'Flight')."""

    lead_organization: Optional[str] = None
    """Lead organization."""

    # -------------------------------------------------------------------------
    # Policy Pack (V2 - Fran Fix #6)
    # -------------------------------------------------------------------------
    policy_pack_id: Optional[str] = None
    """ID of the policy pack to use."""

    # -------------------------------------------------------------------------
    # Environments (V2 - Fran Fix #2: Multi-environment)
    # -------------------------------------------------------------------------
    environments: list[EnvironmentDefinition] = Field(default_factory=list)
    """List of environment definitions."""

    # -------------------------------------------------------------------------
    # Hardware Context
    # -------------------------------------------------------------------------
    hardware_context: Optional[HardwareContext] = None
    """Hardware-specific context."""

    # -------------------------------------------------------------------------
    # Materials
    # -------------------------------------------------------------------------
    materials: list[MaterialEntry] = Field(default_factory=list)
    """List of materials in the session."""

    maptis_resolutions: list[MaterialResolutionResult] = Field(default_factory=list)
    """MAPTIS resolution results for materials."""

    # -------------------------------------------------------------------------
    # Material-Environment Mappings (V2 - Fran Fix #2)
    # -------------------------------------------------------------------------
    material_environment_usages: list[MaterialEnvironmentUsage] = Field(
        default_factory=list
    )
    """Material usage in specific environments."""

    # -------------------------------------------------------------------------
    # COTS Assessment
    # -------------------------------------------------------------------------
    cots_items: list[COTSItem] = Field(default_factory=list)
    """COTS items requiring special handling."""

    # -------------------------------------------------------------------------
    # Organization
    # -------------------------------------------------------------------------
    org_chart: Optional[OrgChart] = None
    """Organization structure for approvals."""

    # -------------------------------------------------------------------------
    # Applicability
    # -------------------------------------------------------------------------
    applicability_matrix: Optional[dict[str, dict[str, Any]]] = None
    """MPR applicability matrix (mpr_id -> decision dict)."""

    # -------------------------------------------------------------------------
    # Compliance
    # -------------------------------------------------------------------------
    mpr_determinations: list[dict[str, Any]] = Field(default_factory=list)
    """MPR compliance determinations."""

    # -------------------------------------------------------------------------
    # Gaps (V2 - Fran Fix #7: Split types)
    # -------------------------------------------------------------------------
    deficiencies: list[DeficiencySignal] = Field(default_factory=list)
    """Deficiencies (missing data that blocks decisions)."""

    nonconformances: list[NonconformanceSignal] = Field(default_factory=list)
    """Nonconformances (evidence indicates failure)."""

    # -------------------------------------------------------------------------
    # Minor Quantity Aggregation (V2 - Fran Fix #4)
    # -------------------------------------------------------------------------
    minor_quantity_aggregation: Optional[MinorQuantityAggregation] = None
    """Minor quantity aggregation analysis."""

    # -------------------------------------------------------------------------
    # Constraints
    # -------------------------------------------------------------------------
    constraints: list[OperationalConstraint] = Field(default_factory=list)
    """Operational constraints derived from evaluation."""

    # -------------------------------------------------------------------------
    # Closure (V2 - Fran Fix #8)
    # -------------------------------------------------------------------------
    closure_decisions: list[ClosureDecision] = Field(default_factory=list)
    """Closure decisions for nonconformances."""

    accepted_open_gaps: list[AcceptedOpenGap] = Field(default_factory=list)
    """Gaps accepted as open for generation."""

    # -------------------------------------------------------------------------
    # Draft Text Boxes (V2 - Fran Fix #11: LLM isolation)
    # -------------------------------------------------------------------------
    draft_text_boxes: list[DraftTextBox] = Field(default_factory=list)
    """LLM-generated drafts (isolated from decisions)."""

    # -------------------------------------------------------------------------
    # Blocking Questions
    # -------------------------------------------------------------------------
    blocking_questions: list[BlockingQuestion] = Field(default_factory=list)
    """Current blocking questions."""

    # -------------------------------------------------------------------------
    # User Decisions
    # -------------------------------------------------------------------------
    user_decisions: list[UserDecision] = Field(default_factory=list)
    """Logged user decisions."""

    # -------------------------------------------------------------------------
    # Decision Graph (V2 - Fran Fix #5, #12)
    # -------------------------------------------------------------------------
    decision_graph: Optional[DecisionGraph] = None
    """Dependency graph for recompute."""

    # -------------------------------------------------------------------------
    # Computation Context (V2 - Fran Fix #10)
    # -------------------------------------------------------------------------
    computation_context: Optional[ComputationContext] = None
    """Version context for cache validation."""

    # -------------------------------------------------------------------------
    # Generated Artifacts
    # -------------------------------------------------------------------------
    generated_artifacts: list[GeneratedArtifact] = Field(default_factory=list)
    """Records of generated files."""

    # -------------------------------------------------------------------------
    # Validators
    # -------------------------------------------------------------------------
    @model_validator(mode="after")
    def validate_session(self) -> PlanGeneratorSession:
        """Validate session consistency."""
        # Check closure decisions reference valid nonconformances
        nonconformance_ids = {n.nonconformance_id for n in self.nonconformances}
        for decision in self.closure_decisions:
            if decision.gap_id not in nonconformance_ids:
                raise ValueError(
                    f"Closure decision for unknown nonconformance: {decision.gap_id}"
                )

        # Check accepted open gaps reference valid gaps
        deficiency_ids = {d.deficiency_id for d in self.deficiencies}
        all_gap_ids = nonconformance_ids | deficiency_ids
        for accepted in self.accepted_open_gaps:
            if accepted.gap_id not in all_gap_ids:
                raise ValueError(f"Accepted open gap unknown: {accepted.gap_id}")

        return self

    # -------------------------------------------------------------------------
    # Methods
    # -------------------------------------------------------------------------
    def can_generate(self) -> tuple[bool, list[str]]:
        """
        Check if session is ready for artifact generation.

        V2: Allows generation with accepted open gaps.

        Returns:
            Tuple of (can_generate, list of blockers).
        """
        blockers = []

        if not self.environments:
            blockers.append("No environments defined")

        if not self.materials:
            blockers.append("No materials entered")

        # Check for unresolved materials
        resolved_ids = {r.material_id for r in self.maptis_resolutions}
        unresolved = [m for m in self.materials if m.id not in resolved_ids]
        if unresolved:
            blockers.append(f"{len(unresolved)} materials not resolved in MAPTIS")

        # Check for blocking deficiencies (without conservative default)
        blocking_deficiencies = [
            d for d in self.deficiencies if not d.conservative_default_available
        ]
        if blocking_deficiencies:
            blockers.append(f"{len(blocking_deficiencies)} blocking deficiencies")

        # V2: Nonconformances need closure OR acceptance
        closed_ids = {d.gap_id for d in self.closure_decisions}
        accepted_ids = {a.gap_id for a in self.accepted_open_gaps}
        open_nonconformances = [
            n
            for n in self.nonconformances
            if n.nonconformance_id not in closed_ids
            and n.nonconformance_id not in accepted_ids
        ]
        if open_nonconformances:
            blockers.append(
                f"{len(open_nonconformances)} nonconformances without closure or acceptance"
            )

        return len(blockers) == 0, blockers

    def get_environment(self, environment_id: str) -> Optional[EnvironmentDefinition]:
        """Get environment by ID."""
        for env in self.environments:
            if env.environment_id == environment_id:
                return env
        return None

    def get_material(self, material_id: str) -> Optional[MaterialEntry]:
        """Get material by ID."""
        for mat in self.materials:
            if mat.id == material_id:
                return mat
        return None

    def get_resolution(self, material_id: str) -> Optional[MaterialResolutionResult]:
        """Get MAPTIS resolution for a material."""
        for res in self.maptis_resolutions:
            if res.material_id == material_id:
                return res
        return None

    def get_usages_for_material(self, material_id: str) -> list[MaterialEnvironmentUsage]:
        """Get all environment usages for a material."""
        return [u for u in self.material_environment_usages if u.material_id == material_id]

    def get_usages_for_environment(self, environment_id: str) -> list[MaterialEnvironmentUsage]:
        """Get all material usages in an environment."""
        return [u for u in self.material_environment_usages if u.environment_id == environment_id]
