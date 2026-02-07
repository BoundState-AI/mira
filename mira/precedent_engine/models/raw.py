#!/usr/bin/env python3
"""
Module: Raw
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

from typing import Literal

from pydantic import BaseModel, Field


class RawMUARecord(BaseModel):
    """
    Direct mapping from parsed MUA JSONL output.

    This is the raw extraction before enrichment. Multi-material designations
    have not yet been split, environment strings have not been normalized,
    and issue text has not been classified into deviation types.

    IMPORTANT: This model uses extra="ignore" to handle unexpected fields
    from various extraction pipelines.
import uuid
    """

    model_config = {"extra": "ignore"}

    # Extraction metadata
    file: str
    success: bool
    time_seconds: float
    confidence: float
    extraction_mode: str | None = None

    # Identity
    mua_number: str
    category: Literal["I", "II", "III"] | None = None
    determination: str | None = None

    # Material (messy, may be multi-material)
    material_designation: str | None = None
    specification: str | None = Field(default=None, alias="material_specification")
    manufacturer: str | None = None
    trade_name: str | None = None

    # Environment
    environment: str | None = None  # "GOX", "Vacuum", "Cabin Air", etc.
    location: str | None = None  # "Habitable", "Nonhabitable"
    max_pressure: float | None = None
    pressure_units: str | None = None
    max_temperature_f: float | None = None
    # NOTE: min_temperature_f NOT in source data - derived during enrichment

    # Content
    application: str | None = None
    rationale: str | None = None
    issue: str | None = None

    # Supporting docs
    test_reports: list[str] = Field(default_factory=list)
