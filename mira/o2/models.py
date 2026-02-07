#!/usr/bin/env python3
"""
Module: Models
Purpose: Oxygen compatibility request/response models for MIRA under BoundState.

BoundState AI 2025
Version: 1.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Fran OpenAI 5 <noreply@openai.com>
Co-Authored-By: Grok 4.0 <noreply@x.ai>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: NASA-CSET, SWE-013, SWE-032
Safety Critical: False
"""

from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field

from core.models.answer import AnswerSeverity, EngineAnswer
import uuid


class OxygenPhase(str, Enum):
    """Phase of oxygen for the query."""

    GAS = "gox"
    LIQUID = "lox"


class O2CompatibilityRequest(BaseModel):
    """Structured request for an oxygen compatibility evaluation.

    NOTE: material_key should be a validated identifier into the material
    repository (MAPTIS, internal catalog, etc.), not a free-text name.
    """

    question: str = Field(
        description="Raw natural-language question, if provided.",
    )
    material_key: str = Field(
        description="Canonical material identifier (e.g. MAPTIS ID, spec key).",
    )
    pressure_psia: float = Field(
        description="Operating pressure in psia.",
    )
    temperature_k: float = Field(
        description="Operating temperature in kelvin.",
    )
    phase: OxygenPhase = Field(
        description="Oxygen phase (gas or liquid).",
    )
    application_id: Optional[str] = Field(
        default=None,
        description="Optional application identifier (subsystem/component).",
    )


class O2CompatibilityResponse(EngineAnswer):
    """Specialization of EngineAnswer for oxygen compatibility."""

    classification: AnswerSeverity = Field(
        description="Oxygen compatibility classification.",
    )
    # Later: add limit_pressure_psia, limit_temperature_k, etc. if needed.
