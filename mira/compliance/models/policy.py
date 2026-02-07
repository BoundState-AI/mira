#!/usr/bin/env python3
"""
Module: Policy Models
Purpose: Environment classification and conductor behavior policies

BoundState AI 2025
Version: 2.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Fran OpenAI 5 <noreply@openai.com>
Co-Authored-By: Grok 4.0 <noreply@x.ai>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: NASA-STD-8739.8B, SWE-013, SWE-033
Safety Critical: True
"""

# Copyright © 2025 BoundState AI. All Rights Reserved.
# Classification: BoundState Proprietary
# License: Evaluation Use Only - Authorized Pilot Program
"""
NASA-STD-6016C Compliance Module - Policy Models

EnvironmentPolicy: Environment classification and routing rules.
ConductorPolicy: Policy flags that control conductor behavior.

Fran Fix #3: CAUTION action depends on context (habitable vs non-habitable).

Compliance: NASA-STD-8739.8B, SWE-013, SWE-033

Author: BoundState Team
Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Fran OpenAI <noreply@openai.com>
Co-Authored-By: Grok <noreply@x.ai>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI
"""

__version__ = "2.0.0"
__safety_critical__ = True

from typing import Optional

from pydantic import BaseModel, Field

from mira.compliance.models.enums import EnvironmentType, MUACategory, RequiredAction


class EnvironmentDefinition(BaseModel):
    """
    Environment definition for compliance analysis.

    Captures all relevant environmental parameters for routing
    and compliance decisions.
    """

    environment_id: str
    """Unique identifier for this environment."""

    environment_type: EnvironmentType
    """Primary environment classification."""

    description: str
    """Human-readable description."""

    # Oxygen parameters
    is_oxygen_enriched: bool = False
    """Whether O2 concentration > 23.5%."""

    oxygen_pct: float = Field(default=21.0, ge=0.0, le=100.0)
    """Oxygen concentration percentage."""

    # Pressure parameters
    pressure_psia: Optional[float] = None
    """Operating pressure in psia."""

    pressure_is_high: bool = False
    """Whether pressure is considered high (>300 kPa typically)."""

    # Temperature parameters
    temperature_min_f: Optional[float] = None
    """Minimum temperature in Fahrenheit."""

    temperature_max_f: Optional[float] = None
    """Maximum temperature in Fahrenheit."""

    is_cryogenic: bool = False
    """Whether environment includes cryogenic temperatures (<-150°C)."""

    # Crew/habitat parameters
    is_habitable: bool = False
    """Whether environment is crew-occupied."""

    is_breathing_atmosphere: bool = False
    """Whether this is breathable atmosphere (offgassing concerns)."""

    # Hydrogen parameters (for H2 routing)
    is_hydrogen_service: bool = False
    """Whether environment involves hydrogen."""

    hydrogen_phase: Optional[str] = None
    """H2 phase if applicable (GH2, LH2)."""

    # Fluid parameters
    fluid_medium: Optional[str] = None
    """Fluid medium if applicable (LOX, GOX, GH2, etc.)."""

    model_config = {"extra": "forbid"}

    def get_mua_category(self) -> MUACategory:
        """
        Determine MUA category based on environment.

        Category I: High-risk (LOX, GOX >25%, P>300kPa)
        Category II: Medium-risk (Standard oxygen environments)
        Category III: Low-risk/specialized (Non-habitable)
        """
        # Category I: High-risk oxygen environments
        if self.fluid_medium in {"LOX", "lox"}:
            return MUACategory.CATEGORY_1
        if self.oxygen_pct > 25.0:
            return MUACategory.CATEGORY_1
        if self.pressure_is_high and self.is_oxygen_enriched:
            return MUACategory.CATEGORY_1

        # Category III: Non-habitable, specialized
        if not self.is_habitable:
            return MUACategory.CATEGORY_3

        # Category II: Everything else
        return MUACategory.CATEGORY_2


class EnvironmentPolicy(BaseModel):
    """
    Policy for environment-based routing decisions.

    Determines which twins to invoke for each environment type.
    """

    version: str = "1.0.0"
    """Policy version for audit trail."""

    # O2 routing thresholds
    o2_enriched_threshold_pct: float = 23.5
    """O2 percentage threshold for enriched classification."""

    o2_high_pressure_threshold_kpa: float = 300.0
    """Pressure threshold for high-pressure O2."""

    # H2 routing thresholds
    h2_high_pressure_threshold_mpa: float = 10.0
    """Pressure threshold for high-pressure H2."""

    h2_cryogenic_threshold_c: float = -150.0
    """Temperature threshold for cryogenic H2."""

    model_config = {"extra": "forbid"}

    def requires_o2_twin(self, env: EnvironmentDefinition) -> bool:
        """Check if environment requires O2 twin evaluation."""
        return (
            env.environment_type == EnvironmentType.OXYGEN
            or env.is_oxygen_enriched
            or env.fluid_medium in {"LOX", "lox", "GOX", "gox"}
        )

    def requires_h2_twin(self, env: EnvironmentDefinition) -> bool:
        """Check if environment requires H2 twin evaluation."""
        return (
            env.environment_type == EnvironmentType.HYDROGEN
            or env.is_hydrogen_service
            or env.fluid_medium in {"GH2", "gh2", "LH2", "lh2"}
        )


class ConductorPolicy(BaseModel):
    """
    Policy flags that control conductor behavior.

    Fran Fix #3: CAUTION action depends on context.
    """

    version: str = "1.0.0"
    """Policy version for audit trail."""

    # CAUTION handling (Fran Fix #3)
    caution_requires_mua_when_habitable: bool = True
    """Whether CAUTION in habitable environments requires MUA."""

    caution_requires_mua_when_o2_enriched: bool = True
    """Whether CAUTION in O2-enriched environments requires MUA."""

    caution_requires_mua_threshold_o2_pct: float = 23.5
    """O2 threshold above which CAUTION requires MUA."""

    # H2 token match risk handling
    h2_token_risk_confidence_penalty: float = 0.1
    """Confidence penalty when H2 token match risk is flagged."""

    h2_token_risk_requires_review: bool = True
    """Whether H2 token match risk requires human review."""

    # Severity thresholds
    critical_severity_forces_mua: bool = True
    """Whether CRITICAL severity always requires MUA."""

    high_severity_forces_mua: bool = True
    """Whether HIGH severity always requires MUA."""

    # Unknown handling
    unknown_requires_data_before_mua: bool = True
    """Whether UNKNOWN status requires data before MUA can be generated."""

    model_config = {"extra": "forbid"}

    def get_caution_action(
        self,
        is_habitable: bool,
        o2_pct: float,
        has_constraints: bool,
    ) -> RequiredAction:
        """
        Determine required action for CAUTION classification.

        Fran Fix #3: Returns GENERATE_MUA or ADD_CONSTRAINTS_SECTION
        based on context.

        Args:
            is_habitable: Whether environment is crew-occupied
            o2_pct: Oxygen concentration percentage
            has_constraints: Whether operational constraints exist

        Returns:
            RequiredAction enum value
        """
        requires_mua = False

        # Habitable environments require MUA for CAUTION
        if is_habitable and self.caution_requires_mua_when_habitable:
            requires_mua = True

        # O2-enriched environments require MUA for CAUTION
        if o2_pct >= self.caution_requires_mua_threshold_o2_pct:
            if self.caution_requires_mua_when_o2_enriched:
                requires_mua = True

        if requires_mua:
            return RequiredAction.GENERATE_MUA
        elif has_constraints:
            return RequiredAction.ADD_CONSTRAINTS_SECTION
        else:
            return RequiredAction.ENGINEERING_REVIEW

    def get_required_action_for_severity(
        self,
        severity: str,
        is_habitable: bool = False,
        o2_pct: float = 21.0,
        has_constraints: bool = False,
    ) -> RequiredAction:
        """
        Get required action based on severity and context.

        Args:
            severity: Gap severity (critical, high, medium, low)
            is_habitable: Whether environment is crew-occupied
            o2_pct: Oxygen concentration percentage
            has_constraints: Whether operational constraints exist

        Returns:
            RequiredAction enum value
        """
        severity_lower = severity.lower()

        if severity_lower == "critical":
            if self.critical_severity_forces_mua:
                return RequiredAction.GENERATE_MUA
            return RequiredAction.SUBSTITUTE_MATERIAL

        if severity_lower == "high":
            if self.high_severity_forces_mua:
                return RequiredAction.GENERATE_MUA
            return RequiredAction.ENGINEERING_REVIEW

        if severity_lower == "medium":
            return self.get_caution_action(is_habitable, o2_pct, has_constraints)

        # Low severity
        if has_constraints:
            return RequiredAction.ADD_CONSTRAINTS_SECTION
        return RequiredAction.NONE


class PolicyRoutingDecision(BaseModel):
    """
    Record of routing decision for audit trail.

    Captures which twins were invoked and why.
    """

    material_id: str
    """Material being evaluated."""

    environment_id: str
    """Environment being evaluated."""

    route_to_o2: bool = False
    """Whether O2 twin was invoked."""

    route_to_o2_reason: Optional[str] = None
    """Why O2 twin was invoked (or not)."""

    route_to_h2: bool = False
    """Whether H2 twin was invoked."""

    route_to_h2_reason: Optional[str] = None
    """Why H2 twin was invoked (or not)."""

    route_to_mua: bool = False
    """Whether MUA generation was triggered."""

    route_to_mua_reason: Optional[str] = None
    """Why MUA was triggered."""

    policy_version: str
    """Version of policy used for routing."""

    model_config = {"extra": "forbid"}
