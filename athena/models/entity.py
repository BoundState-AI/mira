#!/usr/bin/env python3
"""
Module: Entity
Purpose: ATHENA Entity Models.

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
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from athena.models.enums import EntityType, EntityLinkStatus
from athena.models.evidence import Evidence


class EntityMention(BaseModel):
    """Single mention of entity in document."""
    mention_id: UUID = Field(default_factory=uuid4)
    text: str
    normalized_text: str
    document_id: UUID
    page: int
    evidence: Evidence
    entity_type: EntityType
    confidence: float = Field(..., ge=0.0, le=1.0)
    context: str | None = None


class EntityRelation(BaseModel):
    """Relationship between entities."""
    relation_id: UUID = Field(default_factory=uuid4)
    source_entity_id: UUID
    target_entity_id: UUID
    relation_type: str               # "works_on", "located_at", "part_of"
    confidence: float = Field(..., ge=0.0, le=1.0)
    evidence_documents: list[UUID] = Field(default_factory=list)
    status: EntityLinkStatus = EntityLinkStatus.PROPOSED


class EntityLink(BaseModel):
    """Proposed/approved link between mentions (same entity)."""
    link_id: UUID = Field(default_factory=uuid4)
    mention_ids: list[UUID] = Field(default_factory=list)
    canonical_entity_id: UUID | None = None
    confidence: float = Field(..., ge=0.0, le=1.0)
    evidence_type: str               # "exact_match"|"fuzzy_match"|"cooccurrence"
    evidence_details: dict[str, Any] = Field(default_factory=dict)
    status: EntityLinkStatus = EntityLinkStatus.PROPOSED
    proposed_at: datetime = Field(default_factory=datetime.utcnow)
    reviewed_by: str | None = None
    reviewed_at: datetime | None = None
    review_notes: str | None = None


class Entity(BaseModel):
    """Resolved canonical entity."""
    entity_id: UUID = Field(default_factory=uuid4)
    entity_type: EntityType
    canonical_name: str
    aliases: list[str] = Field(default_factory=list)
    mentions: list[EntityMention] = Field(default_factory=list)
    mention_count: int = 0
    first_seen: datetime
    last_seen: datetime
    relationships: list[EntityRelation] = Field(default_factory=list)
    attributes: dict[str, Any] = Field(default_factory=dict)
    confidence: float = Field(..., ge=0.0, le=1.0)
    validation_status: str = "unvalidated"
    validated_by: str | None = None
