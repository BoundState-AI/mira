#!/usr/bin/env python3
"""
Module: Query
Purpose: Core query models for BoundState.

BoundState AI 2025
Version: 1.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Fran OpenAI 5 <noreply@openai.com>
Co-Authored-By: Grok 4.0 <noreply@x.ai>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: SWE-013, NASA-STD-8739.8B
Safety Critical: False
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field


class EnvironmentType(str, Enum):
    """Generic environment types for compatibility questions."""

    OXYGEN = "oxygen"
    HYDROGEN = "hydrogen"


class QueryContext(BaseModel):
    """Structured context for an engineering query.

    NOTE: This is intentionally generic. Domain code (MIRA, Aegis, etc.)
    can subclass/extend it, but logic should rely on validated IDs/properties,
    not on fuzzy material name matching.
    """

    application_id: Optional[str] = Field(
        default=None,
        description="Optional application or use-case identifier.",
    )
    material_key: Optional[str] = Field(
        default=None,
        description="Canonical material identifier (e.g. MAPTIS key, internal ID).",
    )
    environment: Optional[EnvironmentType] = Field(
        default=None,
        description="High-level environment (oxygen, hydrogen, etc.).",
    )
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Extra structured context (program, spec set, etc.).",
    )


class EngineeringQuery(BaseModel):
    """Core query envelope used by the engine."""

    question: str = Field(
        description="Natural-language question as asked by the user.",
    )
    context: QueryContext = Field(
        default_factory=QueryContext,
        description="Structured context extracted from the question or provided upstream.",
    )
