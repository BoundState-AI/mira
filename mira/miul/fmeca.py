#!/usr/bin/env python3
"""
Module: Fmeca
Purpose: FMECA models and RPN calculator per GSFC-HDBK-8004.

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

import logging
from enum import IntEnum
from typing import List, Optional

from pydantic import BaseModel, Field, field_validator, model_validator
import uuid

__all__ = [
    "SeverityRating",
    "OccurrenceRating",
    "DetectionRating",
    "FailureType",
    "FMECAEntry",
    "RPNResult",
    "calculate_rpn",
    "failure_type_from_criticality",
]

__safety_critical__ = True

logger = logging.getLogger(__name__)


class SeverityRating(IntEnum):
    """GSFC-HDBK-8004 Table 1 Severity ratings.

    Measures consequence magnitude of failure effect.
    """

    VERY_VERY_LOW = 0  # Noncredible/highly implausible
    VERY_LOW = 1       # Minor impact to lower priority objectives
    LOW = 2            # Minor impact, margin up to 10%
    MODERATE = 3       # Moderate impact, margin up to 25%
    HIGH = 4           # Major impact but minimum success achievable
    VERY_HIGH = 5      # Minimum mission success not achievable

    @classmethod
    def from_failure_type(cls, failure_type: FailureType) -> SeverityRating:
        """Map failure type to severity rating per GSFC-HDBK-8004."""
        mapping = {
            FailureType.TYPE_1SC: cls.VERY_HIGH,
            FailureType.TYPE_1: cls.VERY_HIGH,
            FailureType.TYPE_2S: cls.HIGH,
            FailureType.TYPE_2: cls.HIGH,
            FailureType.TYPE_3: cls.MODERATE,
            FailureType.TYPE_4: cls.LOW,
            FailureType.TYPE_4T: cls.VERY_LOW,
            FailureType.TYPE_5: cls.VERY_VERY_LOW,
        }
        return mapping.get(failure_type, cls.MODERATE)


class OccurrenceRating(IntEnum):
    """GSFC-HDBK-8004 Table 1 Occurrence ratings.

    Probability of failure occurrence.
    """

    VERY_VERY_LOW = 0  # PF <= 0.001
    VERY_LOW = 1       # 0.001 < PF <= 0.02
    LOW = 2            # 0.02 < PF <= 0.15
    MODERATE = 3       # 0.15 < PF <= 0.25
    HIGH = 4           # 0.25 < PF <= 0.50
    VERY_HIGH = 5      # PF > 0.50

    @classmethod
    def from_probability(cls, probability: float) -> OccurrenceRating:
        """Convert failure probability to occurrence rating."""
        if probability <= 0.001:
            return cls.VERY_VERY_LOW
        if probability <= 0.02:
            return cls.VERY_LOW
        if probability <= 0.15:
            return cls.LOW
        if probability <= 0.25:
            return cls.MODERATE
        if probability <= 0.50:
            return cls.HIGH
        return cls.VERY_HIGH


class DetectionRating(IntEnum):
    """GSFC-HDBK-8004 Table 1 Detection/Prevention ratings.

    Ability to detect failure before effect manifests.
    """

    NONE = 1           # No detection/prevention capability
    REMOTE = 2         # Remote chance of detection
    LOW_MODERATE = 3   # Low to moderate detection capability
    MODERATE_HIGH = 4  # Moderate to high detection capability
    CERTAIN = 5        # Certain detection/prevention

    @classmethod
    def from_screens(
        cls,
        screen_a_pass: Optional[bool],
        screen_b_pass: Optional[bool],
    ) -> DetectionRating:
        """Derive detection rating from SSP 30234 redundancy screens.

        Screen A: Can redundant item be checked without ORU removal?
        Screen B: Is failure detectable by flight/ground crew?
        """
        if screen_a_pass is None and screen_b_pass is None:
            return cls.LOW_MODERATE  # Unknown - conservative default

        a_pass = screen_a_pass if screen_a_pass is not None else False
        b_pass = screen_b_pass if screen_b_pass is not None else False

        if a_pass and b_pass:
            return cls.CERTAIN
        if a_pass or b_pass:
            return cls.MODERATE_HIGH
        return cls.REMOTE


class FailureType(IntEnum):
    """GSFC-HDBK-8004 Failure Type classifications."""

    TYPE_1SC = 1  # Critical + Single Point Failure + Safety
    TYPE_1 = 2    # Critical + Single Point Failure
    TYPE_2S = 3   # Critical + Safety
    TYPE_2 = 4    # Critical
    TYPE_3 = 5    # Significant
    TYPE_4 = 6    # Minor
    TYPE_4T = 7   # Temporary
    TYPE_5 = 8    # Insignificant

    @property
    def description(self) -> str:
        """Return description for this failure type."""
        descriptions = {
            FailureType.TYPE_1SC: "Critical + SPF + Safety hazard",
            FailureType.TYPE_1: "Critical + Single Point Failure",
            FailureType.TYPE_2S: "Critical + Safety hazard",
            FailureType.TYPE_2: "Critical failure",
            FailureType.TYPE_3: "Significant degradation",
            FailureType.TYPE_4: "Minor impact",
            FailureType.TYPE_4T: "Temporary/recoverable",
            FailureType.TYPE_5: "Insignificant",
        }
        return descriptions.get(self, "Unknown")


class FMECAEntry(BaseModel):
    """Single FMECA worksheet entry.

    Combines SSP 30234 FMEA data with GSFC-HDBK-8004 criticality analysis.

    Compliance: SWE-013, SWE-033
    """

    model_config = {"extra": "forbid", "populate_by_name": True}

    # === Identification ===
    fmea_number: str = Field(..., min_length=1, alias="FMEANumber")
    item_name: str = Field(..., alias="ItemName")
    item_part_number: str = Field(..., alias="ItemPartNumber")

    # === Failure Mode ===
    failure_mode_code: str = Field(..., alias="FailureModeCode")
    failure_mode_text: str = Field("", alias="FailureModeText")
    failure_causes: List[str] = Field(default_factory=list, alias="FailureCauses")

    # === Effects ===
    effect_local: str = Field("", alias="EffectLocal")
    effect_next_assembly: str = Field("", alias="EffectNextAssembly")
    effect_end_item: str = Field("", alias="EffectEndItem")
    effect_crew_iss: str = Field("", alias="EffectCrewISS")

    # === SSP 30234 Criticality ===
    ssp_criticality: str = Field(..., alias="SSPCriticality")
    is_critical_item: bool = Field(False, alias="IsCriticalItem")

    # === Redundancy Screens (SSP 30234 5.13.5) ===
    screen_a_prelaunch: Optional[bool] = Field(None, alias="ScreenAPrelaunch")
    screen_a_onorbit: Optional[bool] = Field(None, alias="ScreenAOnOrbit")
    screen_b_flight: Optional[bool] = Field(None, alias="ScreenBFlight")
    screen_b_ground: Optional[bool] = Field(None, alias="ScreenBGround")
    screen_c: Optional[bool] = Field(None, alias="ScreenC")

    # === Time Estimates ===
    time_to_detect_hours: Optional[float] = Field(None, ge=0, alias="TimeToDetectHours")
    time_to_effect_hours: Optional[float] = Field(None, ge=0, alias="TimeToEffectHours")

    # === FMECA Ratings (GSFC-HDBK-8004) ===
    failure_type: Optional[FailureType] = Field(None, alias="FailureType")
    severity: Optional[SeverityRating] = Field(None, alias="Severity")
    occurrence: Optional[OccurrenceRating] = Field(None, alias="Occurrence")
    detection: Optional[DetectionRating] = Field(None, alias="Detection")
    failure_probability: Optional[float] = Field(None, ge=0, le=1, alias="FailureProbability")

    # === Hazard Reference ===
    hazard_report_number: Optional[str] = Field(None, alias="HazardReportNumber")
    hazard_created: bool = Field(False, alias="HazardCreated")

    # === Provenance ===
    source: str = Field(..., description="Data source for audit trail")

    @field_validator("ssp_criticality", mode="before")
    @classmethod
    def normalize_criticality(cls, v: str) -> str:
        """Normalize criticality code format."""
        if v is None:
            raise ValueError("SSP criticality is required")
        return str(v).upper().strip()

    @model_validator(mode="after")
    def derive_fmeca_ratings(self) -> FMECAEntry:
        """Auto-derive FMECA ratings if not explicitly provided."""
        # Derive failure type from SSP criticality
        if self.failure_type is None:
            self.failure_type = failure_type_from_criticality(
                self.ssp_criticality,
                self.hazard_created,
            )

        # Derive severity from failure type
        if self.severity is None and self.failure_type is not None:
            self.severity = SeverityRating.from_failure_type(self.failure_type)

        # Derive occurrence from probability if provided
        if self.occurrence is None and self.failure_probability is not None:
            self.occurrence = OccurrenceRating.from_probability(self.failure_probability)

        # Derive detection from screens
        if self.detection is None:
            screen_a = self.screen_a_prelaunch or self.screen_a_onorbit
            screen_b = self.screen_b_flight or self.screen_b_ground
            self.detection = DetectionRating.from_screens(screen_a, screen_b)

        return self

    @property
    def can_calculate_rpn(self) -> bool:
        """Check if all RPN components are available."""
        return all([
            self.severity is not None,
            self.occurrence is not None,
            self.detection is not None,
        ])

    @property
    def screens_pass(self) -> bool:
        """Check if all applicable redundancy screens pass."""
        screens = [
            self.screen_a_prelaunch,
            self.screen_a_onorbit,
            self.screen_b_flight,
            self.screen_b_ground,
            self.screen_c,
        ]
        applicable = [s for s in screens if s is not None]
        if not applicable:
            return True  # No screens defined
        return all(applicable)


class RPNResult(BaseModel):
    """Risk Priority Number calculation result.

    RPN = Severity x Occurrence x Detection (inverted)

    Per GSFC-HDBK-8004, lower detection capability = higher risk.
    We invert the detection scale: (6 - detection) so that
    poor detection increases RPN.
    """

    model_config = {"extra": "forbid"}

    rpn: int = Field(..., ge=0, le=150, description="Risk Priority Number")
    severity: int = Field(..., ge=0, le=5)
    occurrence: int = Field(..., ge=0, le=5)
    detection: int = Field(..., ge=1, le=5)
    detection_inverted: int = Field(..., ge=1, le=5)

    risk_level: str = Field(..., description="Qualitative risk level")
    requires_action: bool = Field(..., description="RPN exceeds action threshold")
    rationale: str = Field(..., description="Explanation of calculation")

    @classmethod
    def calculate(
        cls,
        severity: SeverityRating,
        occurrence: OccurrenceRating,
        detection: DetectionRating,
        action_threshold: int = 40,
    ) -> RPNResult:
        """Calculate RPN from component ratings.

        Args:
            severity: Consequence magnitude (0-5)
            occurrence: Failure probability (0-5)
            detection: Detection capability (1-5, higher = better)
            action_threshold: RPN above this requires corrective action

        Returns:
            RPNResult with calculated values and risk assessment
        """
        # Invert detection: 1 (none) -> 5, 5 (certain) -> 1
        detection_inverted = 6 - detection.value

        rpn = severity.value * occurrence.value * detection_inverted

        # Determine risk level
        if rpn == 0:
            risk_level = "Negligible"
        elif rpn <= 20:
            risk_level = "Low"
        elif rpn <= 40:
            risk_level = "Moderate"
        elif rpn <= 80:
            risk_level = "High"
        else:
            risk_level = "Critical"

        rationale = (
            f"S({severity.value}) x O({occurrence.value}) x D({detection_inverted}) = {rpn}. "
            f"Severity: {severity.name}, Occurrence: {occurrence.name}, "
            f"Detection: {detection.name} (inverted to {detection_inverted})."
        )

        return cls(
            rpn=rpn,
            severity=severity.value,
            occurrence=occurrence.value,
            detection=detection.value,
            detection_inverted=detection_inverted,
            risk_level=risk_level,
            requires_action=rpn > action_threshold,
            rationale=rationale,
        )


def calculate_rpn(entry: FMECAEntry, action_threshold: int = 40) -> Optional[RPNResult]:
    """Calculate RPN for an FMECA entry.

    Returns None if required ratings are missing.
    """
    if not entry.can_calculate_rpn:
        logger.warning(
            "[FMECA] Cannot calculate RPN for %s: missing ratings (S=%s, O=%s, D=%s)",
            entry.fmea_number,
            entry.severity,
            entry.occurrence,
            entry.detection,
        )
        return None

    return RPNResult.calculate(
        severity=entry.severity,
        occurrence=entry.occurrence,
        detection=entry.detection,
        action_threshold=action_threshold,
    )


def failure_type_from_criticality(
    ssp_criticality: str,
    has_safety_hazard: bool = False,
) -> FailureType:
    """Map SSP 30234 criticality to GSFC-HDBK-8004 failure type.

    Args:
        ssp_criticality: SSP 30234 code (1, 1R, 1S, 2, etc.)
        has_safety_hazard: Whether failure creates safety hazard

    Returns:
        Appropriate FailureType classification
    """
    crit = ssp_criticality.upper().strip()

    # Category 1 - Loss of station/life
    if crit == "1":
        return FailureType.TYPE_1SC if has_safety_hazard else FailureType.TYPE_1
    if crit == "1S":
        return FailureType.TYPE_1SC
    if crit in ("1R", "1SR"):
        return FailureType.TYPE_2S if has_safety_hazard else FailureType.TYPE_2

    # Category 2 - Loss of mission
    if crit == "2":
        return FailureType.TYPE_2S if has_safety_hazard else FailureType.TYPE_2
    if crit in ("2R", "2N", "2NR"):
        return FailureType.TYPE_3

    # Category 3 - All others
    if crit == "3":
        return FailureType.TYPE_4

    # Unknown - conservative default
    logger.warning("[FMECA] Unknown criticality code '%s', defaulting to TYPE_3", crit)
    return FailureType.TYPE_3
