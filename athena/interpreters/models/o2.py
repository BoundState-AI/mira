#!/usr/bin/env python3
"""
Module: O2
Purpose: ATHENA O2 Interpreter Models.

BoundState AI 2025
Version: 1.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Fran OpenAI 5 <noreply@openai.com>
Co-Authored-By: Grok 4.0 <noreply@x.ai>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: SWE-032, SWE-033
Safety Critical: True
"""

from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, computed_field

__all__ = ["FlammabilityRecord", "OxygenPhase", "IgnitionTestType"]
__safety_critical__ = True


class OxygenPhase(str, Enum):
    """Oxygen phase for testing."""
    GOX = "gox"      # Gaseous oxygen
    LOX = "lox"      # Liquid oxygen
    UNKNOWN = "unknown"


class IgnitionTestType(str, Enum):
    """Types of ignition/flammability tests."""
    PROMOTED_IGNITION = "promoted_ignition"
    MECHANICAL_IMPACT = "mechanical_impact"
    PARTICLE_IMPACT = "particle_impact"
    PNEUMATIC_IMPACT = "pneumatic_impact"
    FRICTION = "friction"
    AUTOIGNITION = "autoignition"
    OTHER = "other"


class FlammabilityRecord(BaseModel):
    """
    Single oxygen compatibility/flammability data record.

    Represents one row of O2 compatibility data extracted from a table.
    """
    model_config = {"extra": "forbid"}

    # Source tracking
    record_id: str
    table_id: str
    row_index: int

    # Material identification
    material_name: str
    material_uns: Optional[str] = None
    material_spec: Optional[str] = None
    material_form: Optional[str] = None
    material_condition: Optional[str] = None

    # Environment (SI units)
    pressure_pa: Optional[float] = None       # Pressure in Pascals
    temperature_k: Optional[float] = None     # Temperature in Kelvin
    oxygen_phase: OxygenPhase = OxygenPhase.UNKNOWN

    # Flammability properties
    ignition_temperature_k: Optional[float] = None  # Auto-ignition temp, Kelvin
    burn_rate_mm_s: Optional[float] = None          # Burn rate, mm/s
    heat_of_combustion_j_g: Optional[float] = None  # Heat of combustion, J/g

    # Test results
    test_type: Optional[IgnitionTestType] = None
    test_result: Optional[str] = None         # Pass/Fail or description
    reactions_observed: Optional[int] = None  # Number of reactions in test

    # Compatibility rating
    compatibility_class: Optional[str] = None  # A, B, C, D or similar

    # Reference
    reference: Optional[str] = None

    # Notes
    notes: Optional[str] = None

    # Quality
    extraction_confidence: float = 1.0

    @computed_field
    @property
    def is_complete(self) -> bool:
        """Check if record has minimum required data."""
        return bool(
            self.material_name
            and (
                self.compatibility_class is not None
                or self.test_result is not None
                or self.ignition_temperature_k is not None
            )
        )

    @property
    def is_compatible(self) -> Optional[bool]:
        """
        Determine if material is O2 compatible.

        Returns:
            True if compatible, False if not, None if unknown
        """
        if self.compatibility_class:
            # A is typically best, D is worst
            return self.compatibility_class.upper() in ("A", "B")

        if self.test_result:
            result_lower = self.test_result.lower()
            if "pass" in result_lower or "compatible" in result_lower:
                return True
            if "fail" in result_lower or "incompatible" in result_lower:
                return False

        return None

    @property
    def risk_level(self) -> str:
        """
        Categorize O2 compatibility risk.

        Returns:
            'low', 'medium', 'high', or 'unknown'
        """
        if self.compatibility_class:
            cls = self.compatibility_class.upper()
            if cls == "A":
                return "low"
            elif cls == "B":
                return "medium"
            elif cls in ("C", "D"):
                return "high"

        if self.is_compatible is True:
            return "low"
        elif self.is_compatible is False:
            return "high"

        return "unknown"
