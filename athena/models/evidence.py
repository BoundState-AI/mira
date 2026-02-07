#!/usr/bin/env python3
"""
Module: Evidence
Purpose: from datetime import datetime

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

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class BoundingBox(BaseModel):
    """Normalized coordinates (0.0-1.0) within page."""
    x_min: float = Field(..., ge=0.0, le=1.0)
    y_min: float = Field(..., ge=0.0, le=1.0)
    x_max: float = Field(..., ge=0.0, le=1.0)
    y_max: float = Field(..., ge=0.0, le=1.0)

    @property
    def width(self) -> float:
        """Width of the bounding box."""
        return self.x_max - self.x_min

    @property
    def height(self) -> float:
        """Height of the bounding box."""
        return self.y_max - self.y_min

    @property
    def area(self) -> float:
        """Area of the bounding box."""
        return self.width * self.height

    def contains(self, x: float, y: float) -> bool:
        """Check if a point is within the bounding box."""
        return self.x_min <= x <= self.x_max and self.y_min <= y <= self.y_max

    def overlaps(self, other: "BoundingBox") -> bool:
        """Check if this bounding box overlaps with another."""
        return not (
            self.x_max < other.x_min or
            self.x_min > other.x_max or
            self.y_max < other.y_min or
            self.y_min > other.y_max
        )


class Evidence(BaseModel):
    """Links extracted value to source location. REQUIRED for all extractions."""
    page: int                                    # 1-indexed
    bbox: BoundingBox
    snippet_hash: str                            # SHA256 of cropped region
    snippet_path: str | None = None              # Path in file store
    raw_text: str | None = None                  # Vision text from region
    confidence: float = Field(..., ge=0.0, le=1.0)
    additional_regions: list["Evidence"] = Field(default_factory=list)


class ExtractedValue(BaseModel):
    """Single extracted field with mandatory evidence."""
    value: Any
    value_type: str                              # "string"|"number"|"date"|"list"|"null"
    evidence: Evidence                           # REQUIRED - cannot be None
    confidence: float = Field(..., ge=0.0, le=1.0)
    extraction_method: str = "vision"            # "vision"|"manual"
    validated: bool = False
    validated_by: str | None = None
    validated_at: datetime | None = None


class EvidencePolicy(BaseModel):
    """Evidence requirements - clarifies mandatory vs targets."""

    # HARD REQUIREMENT: Every ExtractedValue MUST have Evidence
    # Enforced by Pydantic - cannot create without evidence
    extracted_values_require_evidence: bool = True  # Always True

    # SOFT TARGET: % of schema fields with bbox evidence
    # Some fields legitimately missing from document
    target_evidence_coverage: float = 0.95

    # TARGET: % with high-quality evidence (bbox + snippet)
    target_high_quality_evidence: float = 0.90
