#!/usr/bin/env python3
"""
Module: Review
Purpose: ATHENA Review Queue Models.

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
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from athena.models.enums import BoundarySignal, EntityType
from athena.models.evidence import Evidence
from athena.models.entity import EntityLink, EntityMention


class BoundaryCandidate(BaseModel):
    """Candidate document boundary."""
    after_page: int
    signals: list[BoundarySignal] = Field(default_factory=list)
    confidence: float = Field(..., ge=0.0, le=1.0)
    evidence: Evidence | None = None


class BoundaryReviewItem(BaseModel):
    """Boundary review queue item - file pointers only."""
    review_id: UUID = Field(default_factory=uuid4)
    batch_id: str
    source_file: str
    candidate: BoundaryCandidate
    page_image_paths: list[str] = Field(default_factory=list)  # S3 paths
    page_image_urls: list[str] | None = None  # Signed URLs (on request)
    page_numbers: list[int] = Field(default_factory=list)
    status: str = "pending"
    reviewed_by: str | None = None
    reviewed_at: datetime | None = None
    notes: str | None = None


class EntityReviewItem(BaseModel):
    """Entity review queue item - file pointers only."""
    review_id: UUID = Field(default_factory=uuid4)
    link: EntityLink
    mentions: list[EntityMention] = Field(default_factory=list)
    evidence_snippet_paths: list[str] = Field(default_factory=list)
    evidence_snippet_urls: list[str] | None = None
    entity_type: EntityType
    suggested_canonical: str
    priority: int = 0
    created_at: datetime = Field(default_factory=datetime.utcnow)
