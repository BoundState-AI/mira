#!/usr/bin/env python3
"""
Module: Closure Path Base
Purpose: Abstract base class for closure path implementations

BoundState AI 2026
Version: 2.0.0
Classification: BoundState Proprietary

Defines the interface for closure path implementations.
Each path must implement check_eligibility() and generate_artifact().

Compliance: NASA-STD-8739.8B, SWE-013, SWE-033
Safety Critical: False
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import TYPE_CHECKING, Any, Optional

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from ..models import (
        EnvironmentDefinition,
        MaterialEntry,
        NonconformanceSignal,
        PlanGeneratorSession,
    )
    from ..models.artifacts import GeneratedArtifact

__version__ = "2.0.0"
__safety_critical__ = False


class ClosurePathResult(BaseModel):
    """
    Result of closure path eligibility check.

    Captures the deterministic evaluation of whether a closure path
    is available for a given gap.
    """

    path_id: str
    """Closure path identifier."""

    eligible: bool
    """Whether this path is eligible."""

    rationale: str
    """Explanation for eligibility determination."""

    citation: str
    """NASA-STD-6016C citation for this path."""

    required_inputs: list[str] = Field(default_factory=list)
    """Input fields required to execute this path."""

    provided_inputs: dict[str, Any] = Field(default_factory=dict)
    """Inputs already provided."""

    missing_inputs: list[str] = Field(default_factory=list)
    """Inputs still needed."""

    output_artifact: str
    """What artifact this path produces."""

    confidence: float = 1.0
    """Confidence in eligibility determination (0-1)."""

    evaluated_at: datetime = Field(default_factory=datetime.now)
    """When eligibility was evaluated."""

    # For display
    path_title: str = ""
    """Human-readable path name."""

    path_description: str = ""
    """Description of what this path does."""

    model_config = {"extra": "forbid", "populate_by_name": True}


class ClosurePathBase(ABC):
    """
    Abstract base class for closure path implementations.

    Each closure path represents a "Senior Engineer Move" -
    a deterministic way to resolve a nonconformance.

    Subclasses must implement:
    - check_eligibility(): Determine if path is available
    - generate_artifact(): Produce the closure documentation
    """

    # Class-level attributes (override in subclass)
    path_id: str = "BASE"
    path_title: str = "Base Closure Path"
    path_description: str = "Abstract base class"
    citation: str = "NASA-STD-6016C"
    required_inputs: list[str] = []
    output_artifact: str = "closure_artifact"

    @abstractmethod
    def check_eligibility(
        self,
        gap: "NonconformanceSignal",
        material: "MaterialEntry",
        environment: "EnvironmentDefinition",
        session: "PlanGeneratorSession",
    ) -> ClosurePathResult:
        """
        Check if this closure path is eligible.

        This is a DETERMINISTIC check based on:
        - Gap type (must match path applicability)
        - Material properties (mass, area, mounting, etc.)
        - Environment conditions
        - Session state (aggregations, etc.)

        Args:
            gap: The nonconformance to resolve.
            material: The material with the gap.
            environment: The environment definition.
            session: Full session context.

        Returns:
            ClosurePathResult with eligibility and rationale.
        """
        pass

    def generate_artifact(
        self,
        gap: "NonconformanceSignal",
        inputs: dict[str, Any],
        session: "PlanGeneratorSession",
    ) -> "GeneratedArtifact":
        """
        Generate the closure artifact.

        Override in subclasses that produce artifacts (e.g., MUA documents).
        Default implementation returns a JSON summary.

        Args:
            gap: The nonconformance being closed.
            inputs: User-provided inputs for closure.
            session: Full session context.

        Returns:
            GeneratedArtifact with closure documentation.
        """
        from ..models.artifacts import ArtifactType, GeneratedArtifact
        import json

        content = {
            "path_id": self.path_id,
            "gap_id": gap.nonconformance_id,
            "citation": self.citation,
            "inputs": inputs,
            "generated_at": datetime.now().isoformat(),
        }

        return GeneratedArtifact(
            artifact_type=ArtifactType.GAP_REPORT_JSON,
            format="json",
            content_bytes=json.dumps(content, indent=2).encode(),
            filename=f"closure_{self.path_id.lower()}_{gap.nonconformance_id[:8]}.json",
            source="closure_path",
        )

    def _build_result(
        self,
        eligible: bool,
        rationale: str,
        provided_inputs: Optional[dict[str, Any]] = None,
        confidence: float = 1.0,
    ) -> ClosurePathResult:
        """Helper to build a consistent result."""
        provided = provided_inputs or {}
        missing = [inp for inp in self.required_inputs if inp not in provided]

        return ClosurePathResult(
            path_id=self.path_id,
            eligible=eligible,
            rationale=rationale,
            citation=self.citation,
            required_inputs=self.required_inputs,
            provided_inputs=provided,
            missing_inputs=missing,
            output_artifact=self.output_artifact,
            confidence=confidence,
            path_title=self.path_title,
            path_description=self.path_description,
        )
