#!/usr/bin/env python3
"""
Module: Policy Pack Models
Purpose: Center/program-specific configuration for M&P Plan Generator V2

BoundState AI 2026
Version: 2.0.0
Classification: BoundState Proprietary

Implements Fran Fix #6: Policy pack configuration

Enables center/program tailoring without code changes.

Compliance: NASA-STD-8739.8B, SWE-013, SWE-033
Safety Critical: False
"""

from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field

from mira.compliance.models.evidence import EvidenceRef

__version__ = "2.0.0"
__safety_critical__ = False


class RoutingThreshold(BaseModel):
    """
    Threshold with mandatory evidence.

    Used for configurable limits (e.g., O2%, pressure) that
    drive routing decisions.
    """

    parameter: str
    """Parameter name (e.g., 'o2_pct', 'pressure_psia')."""

    operator: str
    """Comparison operator: 'gt', 'gte', 'lt', 'lte', 'eq'."""

    value: float
    """Threshold value."""

    evidence: Optional[EvidenceRef] = None
    """Evidence for this threshold."""

    model_config = {"extra": "forbid", "populate_by_name": True}

    def evaluate(self, actual_value: float) -> bool:
        """Evaluate whether actual_value meets the threshold."""
        ops = {
            "gt": lambda a, b: a > b,
            "gte": lambda a, b: a >= b,
            "lt": lambda a, b: a < b,
            "lte": lambda a, b: a <= b,
            "eq": lambda a, b: a == b,
        }
        return ops.get(self.operator, lambda a, b: False)(actual_value, self.value)


class ClosurePathRule(BaseModel):
    """
    Rule for when a closure path is allowed.

    Enables center-specific closure path restrictions.
    """

    closure_path: str
    """Closure path name (e.g., 'MINOR_QUANTITY')."""

    conditions: dict[str, Any]
    """Conditions for allowing this path."""

    allowed: bool
    """Whether path is allowed when conditions match."""

    evidence: Optional[EvidenceRef] = None
    """Evidence for this rule."""

    model_config = {"extra": "forbid", "populate_by_name": True}


class ReviewerHeuristic(BaseModel):
    """
    Heuristic for predicting reviewer questions.

    Based on center-specific reviewer patterns.
    """

    trigger_condition: str
    """Condition that triggers this heuristic."""

    predicted_question: str
    """Question the reviewer is likely to ask."""

    recommended_evidence: str
    """Evidence recommended to preemptively address."""

    model_config = {"extra": "forbid", "populate_by_name": True}


class PolicyPack(BaseModel):
    """
    Data-driven policy configuration.

    Fran Fix #6: "Hardcoded tribal knowledge" -> PolicyPack YAML.

    Enables center/program tailoring without code changes.
    All thresholds and rules include evidence references.

    Compliance: SWE-013 (configurable policy).
    """

    policy_pack_id: str
    """Unique identifier for this policy pack."""

    name: str
    """Human-readable name."""

    version: str
    """Version string."""

    # Applicability
    applicable_centers: list[str] = Field(default_factory=list)
    """NASA centers this pack applies to (e.g., ['MSFC', 'JSC'])."""

    applicable_programs: list[str] = Field(default_factory=list)
    """Programs this pack applies to (e.g., ['HLS', 'Gateway'])."""

    # Vehicle environment presets
    vehicle_environments: dict[str, dict[str, Any]] = Field(default_factory=dict)
    """Vehicle environment presets (tribal knowledge)."""

    vehicle_environment_evidence: dict[str, EvidenceRef] = Field(default_factory=dict)
    """Evidence for vehicle environment values."""

    # Hardware type implications
    hardware_type_implications: dict[str, dict[str, bool]] = Field(default_factory=dict)
    """Hardware type -> MPR applicability implications."""

    hardware_type_evidence: dict[str, EvidenceRef] = Field(default_factory=dict)
    """Evidence for hardware type implications."""

    # Threshold overrides
    threshold_overrides: dict[str, RoutingThreshold] = Field(default_factory=dict)
    """Parameter -> threshold overrides."""

    # Closure path rules
    closure_path_rules: list[ClosurePathRule] = Field(default_factory=list)
    """Rules for closure path eligibility."""

    # Reviewer heuristics
    reviewer_heuristics: list[ReviewerHeuristic] = Field(default_factory=list)
    """Heuristics for predicting reviewer questions."""

    # Metadata
    created_at: datetime = Field(default_factory=datetime.now)
    """When pack was created."""

    created_by: str = ""
    """Who created this pack."""

    approved_by: Optional[str] = None
    """Who approved this pack for use."""

    approved_at: Optional[datetime] = None
    """When pack was approved."""

    # Hash for cache validation
    content_hash: str = ""
    """SHA-256 hash of pack content."""

    model_config = {"extra": "forbid", "populate_by_name": True}

    def compute_hash(self) -> str:
        """Compute content hash for cache validation."""
        # Hash key configuration fields
        content = f"{self.policy_pack_id}:{self.version}:{self.vehicle_environments}:{self.threshold_overrides}"
        return hashlib.sha256(content.encode()).hexdigest()

    def get_threshold(self, parameter: str) -> Optional[RoutingThreshold]:
        """Get threshold override for a parameter."""
        return self.threshold_overrides.get(parameter)

    def is_closure_path_allowed(
        self,
        path: str,
        context: dict[str, Any],
    ) -> tuple[bool, str]:
        """
        Check if a closure path is allowed in given context.

        Args:
            path: Closure path name.
            context: Context dict with conditions.

        Returns:
            Tuple of (allowed, rationale).
        """
        for rule in self.closure_path_rules:
            if rule.closure_path != path:
                continue

            # Check if conditions match
            conditions_match = all(
                context.get(k) == v for k, v in rule.conditions.items()
            )

            if conditions_match:
                return rule.allowed, f"Per policy rule: {rule.conditions}"

        # Default: allowed
        return True, "No restricting rule found"
