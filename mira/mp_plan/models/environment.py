#!/usr/bin/env python3
"""
Module: Environment Models
Purpose: Multi-environment support for M&P Plan Generator V2

BoundState AI 2026
Version: 2.0.0
Classification: BoundState Proprietary

Implements Fran Fix #2: Multi-environment support

Compliance: NASA-STD-8739.8B, SWE-013, SWE-033
Safety Critical: False
"""

from __future__ import annotations

import uuid
from typing import Optional

import math

from pydantic import BaseModel, Field, field_validator, model_validator

from mira.compliance.models.evidence import EvidenceRef

__version__ = "2.0.0"
__safety_critical__ = False


class EnvironmentDefinition(BaseModel):
    """
    Single environment zone definition.

    V2: Session has list of environments, not single environment.
    Each material can be used in multiple environments.

    Compliance: SWE-033 (environmental requirements).
    """

    environment_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    """Unique identifier for this environment."""

    name: str
    """Human-readable name (e.g., 'ISS Habitable Volume', 'EVA Suit')."""

    # Environmental parameters
    o2_pct: float = Field(..., gt=0, le=100)
    """Oxygen concentration percentage."""

    pressure_psia: float = Field(..., gt=0)
    """Pressure in psia."""

    temp_range_c: tuple[float, float]
    """Temperature range in Celsius (min, max)."""

    habitable: bool
    """Whether this is a crew-occupied space."""

    vacuum_exposure: bool = False
    """Whether exposed to space vacuum."""

    lunar_dust: bool = False
    """Whether exposed to lunar dust."""

    # Phase/condition
    phase: str = "nominal"
    """Operational phase: 'nominal', 'contingency', 'ground_ops'."""

    # Evidence
    source_evidence: Optional[EvidenceRef] = None
    """Evidence for environment parameters."""

    source: str
    """Source document for environment definition (e.g., 'SSP 30233')."""

    model_config = {"extra": "forbid", "populate_by_name": True}

    @field_validator("o2_pct", "pressure_psia", mode="before")
    @classmethod
    def validate_finite(cls, v: float) -> float:
        """Ensure float values are finite (not NaN or infinity)."""
        if v is None:
            return v
        if not isinstance(v, (int, float)):
            raise ValueError("Value must be a number")
        if math.isnan(v) or math.isinf(v):
            raise ValueError("Value must be finite (not NaN or infinity)")
        return v

    @model_validator(mode="after")
    def validate_temp_range(self) -> EnvironmentDefinition:
        """Ensure min temp < max temp."""
        if self.temp_range_c[0] >= self.temp_range_c[1]:
            raise ValueError("Min temp must be less than max temp")
        return self


class MaterialEnvironmentUsage(BaseModel):
    """
    Material usage in specific environment.

    V2: Links material to environment with adjacency info for aggregation.
    Enables per-environment compliance evaluation.

    Compliance: SWE-033 (usage context).
    """

    material_id: str
    """ID of the material being used."""

    environment_id: str
    """ID of the environment where material is used."""

    location: str
    """Specific location within the environment zone."""

    # Exposure characteristics
    continuous_exposure: bool = True
    """Whether material is continuously exposed to environment."""

    exposure_duration_hours: Optional[float] = None
    """Duration of exposure if not continuous."""

    # Adjacency (for minor quantity aggregation - Fran Fix #4)
    adjacency_group: Optional[str] = None
    """Group ID for co-located materials."""

    ignition_source_proximity: Optional[str] = None
    """Proximity to ignition source: 'none', 'adjacent', 'contact'."""

    model_config = {"extra": "forbid", "populate_by_name": True}
