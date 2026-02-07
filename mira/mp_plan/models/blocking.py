#!/usr/bin/env python3
"""
Module: Blocking Question Models
Purpose: User interaction for M&P Plan Generator V2

BoundState AI 2026
Version: 2.0.0
Classification: BoundState Proprietary

Compliance: NASA-STD-8739.8B, SWE-013, SWE-033
Safety Critical: False
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field

__version__ = "2.0.0"
__safety_critical__ = False


class BlockingQuestionType(str, Enum):
    """Types of blocking questions."""

    MATERIAL_AMBIGUOUS = "material_ambiguous"
    """Material cannot be resolved to MAPTIS code."""

    ENVIRONMENT_MISSING = "environment_missing"
    """No environment defined for session."""

    QUANTITY_MISSING = "quantity_missing"
    """Mass/surface area needed for minor quantity."""

    STRUCTURAL_UNCLEAR = "structural_unclear"
    """Hardware structure is unclear."""

    COTS_CRITICALITY = "cots_criticality"
    """COTS criticality determination needed."""

    CLOSURE_SELECTION = "closure_selection"
    """User must select closure path for nonconformance."""

    TAILORING_APPROVAL = "tailoring_approval"
    """Tailoring decision needs approval."""

    PRECEDENT_VALIDATION = "precedent_validation"
    """Precedent usage needs validation."""

    GROUPING_CONFIRMATION = "grouping_confirmation"
    """Material grouping assumption needs confirmation."""


class BlockingQuestion(BaseModel):
    """
    Blocking question that must be answered before proceeding.

    Questions are generated from gaps in the session state,
    not from a scripted flow.
    """

    question_id: str
    """Unique identifier for this question."""

    question_type: BlockingQuestionType
    """Type of question being asked."""

    question_text: str
    """The question to display to the user."""

    context: str
    """Additional context about why this question is being asked."""

    # Blocked items
    blocked_decisions: list[str]
    """Decision node IDs blocked by this question."""

    # Answer options
    options: list[str] = Field(default_factory=list)
    """Available answer options (empty for free-text)."""

    default_option: Optional[str] = None
    """Default option if any."""

    required: bool = True
    """Whether this question must be answered."""

    validator: Optional[str] = None
    """Name of validator function for free-text answers."""

    # Source tracking
    source_gap_id: Optional[str] = None
    """Gap ID that generated this question."""

    source_mpr: Optional[str] = None
    """MPR ID related to this question."""

    source: str
    """Source that generated this question."""

    model_config = {"extra": "forbid", "populate_by_name": True}


class UserDecision(BaseModel):
    """
    Logged user decision for a blocking question.
    """

    decision_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    """Unique identifier for this decision."""

    question_id: str
    """ID of the question being answered."""

    decision: str
    """The user's answer."""

    rationale: str
    """User's rationale for this decision."""

    decided_by: str
    """Who made this decision."""

    decided_at: datetime = Field(default_factory=datetime.now)
    """When decision was made."""

    source: str
    """Source of decision (e.g., 'interactive', 'api', 'cli')."""

    model_config = {"extra": "forbid", "populate_by_name": True}
