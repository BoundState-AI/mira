#!/usr/bin/env python3
"""
Module: Closure Models
Purpose: Closure decisions and accepted open gaps for M&P Plan Generator V2

BoundState AI 2026
Version: 2.0.0
Classification: BoundState Proprietary

Implements Fran Fix #8: Accepted open gaps

Compliance: NASA-STD-8739.8B, SWE-013, SWE-033
Safety Critical: False
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any, Optional

from pydantic import BaseModel, Field

from mira.compliance.models.evidence import EvidenceRef

__version__ = "2.0.0"
__safety_critical__ = False


class InvalidationTrigger(BaseModel):
    """
    What causes a closure option to become ineligible.

    Fran Fix #5: Explicit invalidation triggers.
    """

    field: str
    """Field that triggers invalidation (e.g., 'material.MAT001.mass_g')."""

    condition: str
    """Condition type: 'changes', 'exceeds_threshold', 'becomes_null'."""

    threshold: Optional[float] = None
    """Threshold value if condition is 'exceeds_threshold'."""

    model_config = {"extra": "forbid", "populate_by_name": True}


class ClosureOption(BaseModel):
    """
    A single closure path option with explicit dependencies.

    Fran Fix #5: "You created invalidation_triggers but never defined how
    they're generated."
    """

    path: str
    """Closure path identifier: 'MINOR_QUANTITY', 'CONFIGURATION_ANALYSIS', etc."""

    eligible: bool
    """Whether this option is currently eligible."""

    citation: str
    """NASA-STD-6016 citation for this closure path."""

    rationale: str
    """Rationale for eligibility determination."""

    # Required inputs
    required_inputs: list[str] = Field(default_factory=list)
    """Input fields required to select this path."""

    # Output
    output_artifact: str
    """What artifact this path produces."""

    # Dependencies (Fran Fix #5)
    depends_on: list[str] = Field(default_factory=list)
    """Field names this option depends on."""

    invalidation_triggers: list[InvalidationTrigger] = Field(default_factory=list)
    """What invalidates this option's eligibility."""

    # Evidence
    eligibility_evidence: Optional[EvidenceRef] = None
    """Evidence for eligibility determination."""

    model_config = {"extra": "forbid", "populate_by_name": True}


class ClosureDecision(BaseModel):
    """
    User closure choice for a nonconformance.
    """

    decision_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    """Unique identifier for this decision."""

    gap_id: str
    """ID of the nonconformance being closed."""

    selected_path: str
    """Selected closure path."""

    provided_inputs: dict[str, Any]
    """Inputs provided for the selected path."""

    decision_rationale: str
    """User's rationale for this decision."""

    decided_by: str
    """Who made this decision."""

    decided_at: datetime = Field(default_factory=datetime.now)
    """When decision was made."""

    available_options: list[dict[str, Any]]
    """Options that were available when decision was made."""

    source: str
    """Source of decision (e.g., 'interactive', 'api')."""

    model_config = {"extra": "forbid", "populate_by_name": True}


class AcceptedOpenGap(BaseModel):
    """
    Gap accepted as open for generation.

    V2: Allows plan generation with known open items.
    These will be flagged in the output document.

    Fran Fix #8: "Can't generate with open gaps" -> accepted_open status.

    Compliance: SWE-013 (acceptance tracking).
    """

    gap_id: str
    """ID of the gap being accepted."""

    gap_type: str
    """Type of gap: 'deficiency' or 'nonconformance'."""

    # Acceptance details
    accepted_by: str
    """Who accepted this gap as open."""

    accepted_at: datetime = Field(default_factory=datetime.now)
    """When acceptance occurred."""

    acceptance_rationale: str
    """Rationale for accepting this gap as open."""

    # Tracking
    owner: str
    """Who is responsible for closing this gap."""

    due_date: date
    """When this gap must be closed."""

    risk_statement: str
    """Risk statement for having this gap open."""

    # Output flag
    flag_in_output: bool = True
    """Whether to flag this in generated documents."""

    model_config = {"extra": "forbid", "populate_by_name": True}


class OperationalConstraint(BaseModel):
    """
    Derived operational constraint from compliance evaluation.
    """

    constraint_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    """Unique identifier for this constraint."""

    description: str
    """Human-readable description of the constraint."""

    affected_material: Optional[str] = None
    """Material ID this constraint affects."""

    source_gap: Optional[str] = None
    """Gap ID that generated this constraint."""

    source: str
    """Source of this constraint."""

    model_config = {"extra": "forbid", "populate_by_name": True}
