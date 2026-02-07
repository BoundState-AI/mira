#!/usr/bin/env python3
"""
Module: Session
Purpose: Interactive MIUL builder session management.

BoundState AI 2025
Version: 1.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Fran OpenAI 5 <noreply@openai.com>
Co-Authored-By: Grok 4.0 <noreply@x.ai>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: SWE-013 (Data requirements), SWE-033 (Requirements Traceability)
Safety Critical: True
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import List, Literal, Optional

from pydantic import BaseModel, Field

__all__ = [
    "SessionState",
    "PartStatus",
    "ResolutionType",
    "UseEnvironmentInput",
    "PartResolution",
    "MIULSession",
]

__safety_critical__ = True


class SessionState(str, Enum):
    """MIUL builder session state.

    Tracks progression through the 4-step workflow.
    """

    SETUP = "setup"           # Step 1: Configure program/environment
    UPLOADING = "uploading"   # Files being uploaded
    EXTRACTING = "extracting" # Processing files to extract parts
    ENRICHING = "enriching"   # Querying MAPTIS for ratings
    REVIEW = "review"         # Step 3: Rationale assignment
    COMPLETE = "complete"     # Step 4: Export done
    ERROR = "error"           # Something failed


class PartStatus(str, Enum):
    """Status of individual part in MIUL.

    Determines what action (if any) is needed for each part.
    """

    OK = "ok"                          # All ratings acceptable (A or B)
    NEEDS_REVIEW = "needs_review"      # Has gaps but rationale possible
    NEEDS_ACTION = "needs_action"      # Prohibited (X) or requires MUA
    RESOLVED = "resolved"              # User assigned rationale
    MUA_REQUIRED = "mua_required"      # Flagged for MUA generation
    PENDING_TEST = "pending_test"      # Awaiting batch/lot testing


class ResolutionType(str, Enum):
    """How user resolved a rating gap.

    Two-path workflow:
    - Technical rationale (no MUA needed)
    - MUA request (new or existing)
    """

    TECHNICAL_RATIONALE = "technical_rationale"    # Direct code (403, 404, etc.)
    NEW_MUA_REQUESTED = "new_mua_requested"        # Generate new MUA
    EXISTING_MUA_LINKED = "existing_mua_linked"    # Reference existing MUA
    TESTING_REQUESTED = "testing_requested"        # Batch/lot test needed
    SUBSTITUTION_NEEDED = "substitution_needed"    # Material must be changed
    ENGINEERING_REVIEW = "engineering_review"      # Escalate to engineering


class UseEnvironmentInput(BaseModel):
    """User input for environment parameters.

    Default values represent SLS standard environment.
    """

    model_config = {"extra": "forbid", "populate_by_name": True}

    use_sls_default: bool = Field(
        True,
        description="Use SLS default environment parameters",
    )
    min_pressure_psia: float = Field(
        0.0,
        ge=0,
        description="Minimum pressure in psia",
    )
    max_pressure_psia: float = Field(
        14.7,
        ge=0,
        description="Maximum pressure in psia",
    )
    min_temperature_f: float = Field(
        0.0,
        description="Minimum temperature in Fahrenheit",
    )
    max_temperature_f: float = Field(
        120.0,
        description="Maximum temperature in Fahrenheit",
    )
    media: List[str] = Field(
        default_factory=lambda: ["Air", "Vacuum"],
        description="Fluid media present",
    )
    o2_percent: float = Field(
        20.9,
        ge=0,
        le=100,
        description="Oxygen percentage",
    )


class PartResolution(BaseModel):
    """User's resolution for a part with rating gap.

    Records the rationale code or MUA reference selected by engineer.
    Invariant: confirmed must be True for rationale_code resolutions.
    """

    model_config = {"extra": "forbid"}

    part_index: int = Field(..., description="Index of part in MIUL tree")
    rating_type: str = Field(
        ...,
        description="Rating type (FLAM, SCC, CORR, TVS, TOX, FS)",
    )
    resolution_type: ResolutionType = Field(
        ...,
        description="How the gap was resolved",
    )

    # For technical_rationale
    rationale_code: Optional[str] = Field(
        None,
        description="Selected rationale code (e.g., '403')",
    )
    rationale_text: Optional[str] = Field(
        None,
        description="Full rationale text for documentation",
    )

    # For existing_mua_linked or after new MUA approved
    mua_number: Optional[str] = Field(
        None,
        description="MUA number (e.g., 'MUA-2024-0042')",
    )
    mua_category: Optional[Literal["I", "II"]] = Field(
        None,
        description="MUA category",
    )

    # Documentation
    notes: Optional[str] = Field(
        None,
        description="Engineer notes for audit trail",
    )
    confirmed: bool = Field(
        False,
        description="Engineer confirmed rationale applicability",
    )
    resolved_by: Optional[str] = Field(
        None,
        description="User who resolved the gap",
    )
    resolved_at: Optional[datetime] = Field(
        None,
        description="When resolution was applied",
    )


class MIULSession(BaseModel):
    """Interactive MIUL builder session.

    Tracks state through the multi-step workflow.
    Invariant: Cannot proceed to review without at least one uploaded file.
    """

    model_config = {"extra": "forbid"}

    # === Session Identity ===
    session_id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description="Unique session identifier",
    )
    created_at: datetime = Field(
        default_factory=datetime.utcnow,
        description="When session was created",
    )
    updated_at: datetime = Field(
        default_factory=datetime.utcnow,
        description="Last modification time",
    )

    # === Step 1: Setup ===
    program: Optional[str] = Field(
        None,
        description="Program name (e.g., 'SLS Block 1B')",
    )
    end_item: Optional[str] = Field(
        None,
        description="End item name (e.g., 'Payload Bay Camera')",
    )
    miul_acronym: Optional[str] = Field(
        None,
        min_length=2,
        max_length=10,
        description="MIUL acronym (e.g., 'PBC')",
    )
    environment: UseEnvironmentInput = Field(
        default_factory=UseEnvironmentInput,
        description="Environment parameters",
    )

    # === Step 2: Extraction ===
    state: SessionState = Field(
        SessionState.SETUP,
        description="Current workflow state",
    )
    uploaded_files: List[str] = Field(
        default_factory=list,
        description="Names of uploaded files",
    )
    total_parts: int = Field(
        0,
        ge=0,
        description="Total parts extracted",
    )
    enriched_parts: int = Field(
        0,
        ge=0,
        description="Parts with MAPTIS data",
    )

    # === Step 3: Review ===
    parts_ok: int = Field(
        0,
        ge=0,
        description="Parts with acceptable ratings",
    )
    parts_needs_review: int = Field(
        0,
        ge=0,
        description="Parts needing rationale",
    )
    parts_needs_action: int = Field(
        0,
        ge=0,
        description="Parts needing MUA or substitution",
    )
    parts_resolved: int = Field(
        0,
        ge=0,
        description="Parts resolved by user",
    )
    resolutions: List[PartResolution] = Field(
        default_factory=list,
        description="User's resolution decisions",
    )

    # === Provenance ===
    source: str = Field(
        "miul_builder",
        description="Origin of session data",
    )

    def add_resolution(self, resolution: PartResolution) -> None:
        """Record user's resolution for a part.

        Invariant: Updates timestamp and resolution count atomically.
        """
        resolution.resolved_at = datetime.utcnow()
        self.resolutions.append(resolution)
        self.parts_resolved += 1
        self.updated_at = datetime.utcnow()

    def get_resolution(
        self,
        part_index: int,
        rating_type: str,
    ) -> Optional[PartResolution]:
        """Find existing resolution for a part/rating combination.

        Args:
            part_index: Index of part in MIUL tree
            rating_type: Rating type (FLAM, SCC, etc.)

        Returns:
            PartResolution if found, None otherwise
        """
        for resolution in self.resolutions:
            if (
                resolution.part_index == part_index
                and resolution.rating_type == rating_type
            ):
                return resolution
        return None

    @property
    def completion_percent(self) -> float:
        """Calculate review completion percentage.

        Returns:
            Percentage of items requiring attention that have been resolved
        """
        needs_attention = self.parts_needs_review + self.parts_needs_action
        if needs_attention == 0:
            return 100.0
        return (self.parts_resolved / needs_attention) * 100

    @property
    def can_export(self) -> bool:
        """Check if session is ready for export.

        Requires:
        - State is REVIEW
        - All items needing attention are resolved
        """
        return (
            self.state == SessionState.REVIEW
            and self.completion_percent >= 100.0
        )

    @property
    def summary(self) -> dict:
        """Return summary statistics for display."""
        return {
            "session_id": self.session_id,
            "program": self.program,
            "end_item": self.end_item,
            "state": self.state.value,
            "total_parts": self.total_parts,
            "enriched_parts": self.enriched_parts,
            "parts_ok": self.parts_ok,
            "parts_needs_review": self.parts_needs_review,
            "parts_needs_action": self.parts_needs_action,
            "parts_resolved": self.parts_resolved,
            "completion_percent": round(self.completion_percent, 1),
            "can_export": self.can_export,
            "uploaded_files": len(self.uploaded_files),
        }
