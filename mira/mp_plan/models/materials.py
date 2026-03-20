#!/usr/bin/env python3
"""
Module: Material Models
Purpose: Material entry and resolution models for M&P Plan Generator V2

BoundState AI 2026
Version: 2.0.0
Classification: BoundState Proprietary

Compliance: NASA-STD-8739.8B, SWE-013, SWE-033
Safety Critical: False
"""

from __future__ import annotations

import uuid
from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator

__version__ = "2.0.0"
__safety_critical__ = False


class MaterialEntry(BaseModel):
    """
    Canonical material entry from BOM or user input.

    Represents a material before MAPTIS resolution.
    """

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    """Unique identifier for this material entry."""

    name: str
    """Material name as entered."""

    application: str
    """Application/use case for this material."""

    quantity: int = Field(ge=1, le=2147483647)
    """Number of items using this material (1 to 2^31-1)."""

    # Physical properties (for minor quantity)
    mass_g: Optional[float] = None
    """Mass in grams."""

    surface_area_cm2: Optional[float] = None
    """Exposed surface area in cm^2."""

    # Specification
    spec: Optional[str] = None
    """Material specification (e.g., 'AMS 5643')."""

    maptis_code: Optional[str] = None
    """MAPTIS material code if known."""

    # Context
    location: Optional[str] = None
    """Location in hardware."""

    function: Optional[str] = None
    """Functional role."""

    source: str
    """Source of this entry (e.g., 'bom_upload', 'manual_entry')."""

    model_config = {"extra": "forbid", "populate_by_name": True}


class MaterialResolutionResult(BaseModel):
    """
    MAPTIS resolution output for a material.

    Contains the resolved MAPTIS code and ratings.
    """

    material_id: str
    """ID of the MaterialEntry this resolves."""

    maptis_code: str
    """Resolved MAPTIS material code."""

    # Ratings
    flam_rating: str
    """Flammability rating (A/B/C/D/X/U)."""

    tvs_rating: str
    """TVS outgassing rating."""

    tox_rating: str
    """Toxicity rating."""

    scc_rating: Optional[str] = None
    """Stress corrosion cracking rating (1/2/3/U) per MSFC-STD-3029A.
    1 = highly resistant, 2 = moderate, 3 = susceptible, U = unknown."""

    corr_rating: Optional[str] = None
    """Corrosion rating (A/B/C/U). A = resistant, C = susceptible."""

    # Test conditions
    test_o2_pct: float
    """O2 percentage in test conditions."""

    test_pressure_psia: Optional[float] = None
    """Test pressure in psia."""

    test_temp_c: Optional[float] = None
    """Test temperature in Celsius."""

    test_report_ref: Optional[str] = None
    """Reference to test report."""

    source: str
    """Source of resolution (e.g., 'maptis_direct', 'enrichment_service')."""

    model_config = {"extra": "forbid", "populate_by_name": True}


class COTSItem(BaseModel):
    """
    COTS (Commercial Off-The-Shelf) component details.

    COTS items may have different compliance paths.
    """

    name: str
    """COTS item name."""

    is_mission_critical: bool
    """Whether this COTS item is mission-critical."""

    rationale: str
    """Rationale for COTS criticality determination."""

    source: str
    """Source of COTS information."""

    model_config = {"extra": "forbid", "populate_by_name": True}


class HardwareContext(BaseModel):
    """
    Hardware-specific context driving applicability decisions.
    """

    hardware_type: str
    """Type of hardware (e.g., 'valve', 'seal', 'structure')."""

    crew_contact: bool
    """Whether hardware has crew contact."""

    ignition_sources: list[str] = Field(default_factory=list)
    """List of potential ignition sources."""

    cots_flags: dict[str, bool] = Field(default_factory=dict)
    """COTS-related flags."""

    source: str
    """Source of hardware context."""

    model_config = {"extra": "forbid", "populate_by_name": True}


class OrgChart(BaseModel):
    """
    Organization structure for approvals.
    """

    lead_org: str
    """Lead organization."""

    technical_authority: str
    """Technical authority contact."""

    panel_members: list[dict[str, str]]
    """M&P panel members."""

    source: str
    """Source of org chart information."""

    model_config = {"extra": "forbid", "populate_by_name": True}
