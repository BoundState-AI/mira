#!/usr/bin/env python3
"""
Module: Answer
Purpose: Core answer models for BoundState.

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
from typing import List, Optional

from pydantic import BaseModel, Field


class AnswerSeverity(str, Enum):
    """Severity / strictness of an answer."""

    OK = "ok"
    CAUTION = "caution"
    PROHIBITED = "prohibited"
    UNKNOWN = "unknown"


class EvidenceItem(BaseModel):
    """Minimal reference to evidence supporting an answer."""

    source_id: str = Field(
        description="Identifier for the evidence source (e.g. document ID).",
    )
    location: Optional[str] = Field(
        default=None,
        description="Location within the source (e.g. section, page).",
    )
    summary: Optional[str] = Field(
        default=None,
        description="Short description of why this evidence is relevant.",
    )


class EngineAnswer(BaseModel):
    """Generic answer produced by the core engine."""

    classification: AnswerSeverity = Field(
        description="Overall severity / compatibility classification.",
    )
    rationale: str = Field(
        description="Short explanation suitable for UI.",
    )
    evidence: List[EvidenceItem] = Field(
        default_factory=list,
        description="Evidence items supporting this answer.",
    )
    notes: Optional[str] = Field(
        default=None,
        description="Optional extra notes or caveats.",
    )
