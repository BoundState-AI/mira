#!/usr/bin/env python3
"""
Module: Enriched
Purpose: [Automatically migrated - needs manual review]

BoundState AI 2025
Version: 1.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Fran OpenAI 5 <noreply@openai.com>
Co-Authored-By: Grok 4.0 <noreply@x.ai>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: SWE-013, NASA-STD-6016
Safety Critical: True
"""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field

from mira.precedent_engine.models.enums import DeviationType, ProgramFamily
import uuid


class EnrichedMUA(BaseModel):
    """
    MUA record after enrichment, ready for precedent matching.

    Transformations applied:
    - Multi-material split (one record per material)
    - Environment normalized (media, o2_pct derived)
    - Issue classified into DeviationType enums
    - Material key resolved via MAPTIS
    - Program family derived from project name

    IMPORTANT: This model uses extra="forbid" for strict validation.
    All fields must be explicitly defined.
    """

    model_config = {"extra": "forbid"}

    # Identity
    contract_id: str  # from mua_number
    source_file: str

    # Material (single material after explosion)
    material_name: str
    material_key: str | None = None  # from MAPTIS join or generated hash
    specification: str | None = None
    manufacturer: str | None = None
    trade_name: str | None = None

    # Environment (normalized)
    media: str | None = None  # GOX, LOX, Vacuum, Air, GH2, LH2, etc.
    o2_pct: float = 21.0
    location_class: Literal["habitable", "non_habitable"] = "non_habitable"

    temp_max_f: float | None = None
    temp_min_f: float = 70.0  # derived from environment context
    pressure_max_psia: float | None = None
    pressure_min_psia: float = 0.0

    # Classification
    category: Literal["I", "II", "III"] | None = None
    determination: str | None = None
    is_rejected: bool = False
    is_usable_precedent: bool = True

    # Supersession tracking
    # Supersession occurs when a newer MUA replaces an older one for the same material/application
    is_superseded: bool = False
    superseded_by: str | None = None  # contract_id of superseding MUA
    supersedes: list[str] = Field(default_factory=list)  # contract_ids this MUA supersedes
    revision_number: int | None = None  # Rev number if available (0, 1, 2, etc.)

    # Deviations (classified from issue text via LLM)
    deviation_types: list[DeviationType] = Field(default_factory=list)
    issue_text: str | None = None

    # Rationale (key for synthesis)
    rationale_text: str | None = None
    application_text: str | None = None

    # Program context
    program: str | None = None
    program_family: ProgramFamily = ProgramFamily.OTHER

    # Test data
    test_reports: list[str] = Field(default_factory=list)
    flammability_rating: str | None = None  # from MAPTIS join

    # Quality
    parse_confidence: float = 1.0
    extraction_mode: str | None = None

    # Multi-material tracking
    is_multi_material_source: bool = False
    source_material_index: int = 0

    # Clustering (optional, from HDBSCAN)
    precedent_family: int | None = None

    # Approval date (for recency weighting)
    approval_date: date | None = None
