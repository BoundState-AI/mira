#!/usr/bin/env python3
"""
Module: Document
Purpose: ATHENA Document Models.

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

from athena.models.enums import (
    DocumentStatus,
    RoutingDecision,
    QualityIssue,
)
from athena.models.evidence import (
    Evidence,
    ExtractedValue,
)


class FieldSpec(BaseModel):
    """Schema field specification."""
    field: str
    type: str                        # "string"|"number"|"date"|"list"|"boolean"
    description: str
    required: bool = False
    validation_pattern: str | None = None


class EntityBag(BaseModel):
    """Container for preliminary entity extraction."""
    equipment: list[str] = Field(default_factory=list)
    people: list[str] = Field(default_factory=list)
    locations: list[str] = Field(default_factory=list)
    organizations: list[str] = Field(default_factory=list)
    references: list[str] = Field(default_factory=list)
    dates: list[str] = Field(default_factory=list)
    materials: list[str] = Field(default_factory=list)


class DocumentSection(BaseModel):
    """Hierarchical document section."""
    heading: str | None = None
    content: str
    page: int
    evidence: Evidence
    subsections: list["DocumentSection"] = Field(default_factory=list)


class Annotation(BaseModel):
    """Non-text annotation."""
    annotation_type: str             # "handwritten"|"stamp"|"signature"|"highlight"
    content: str | None = None
    page: int
    evidence: Evidence
    confidence: float = Field(..., ge=0.0, le=1.0)


class ProcessingEvent(BaseModel):
    """Single event in processing log."""
    event_id: UUID = Field(default_factory=uuid4)
    stage: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    status: str                      # "started"|"completed"|"failed"|"skipped"
    duration_ms: int | None = None
    error: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)
    tokens_used: int = 0
    cost_usd: float = 0.0


class TriageResult(BaseModel):
    """Complete triage output."""
    document_type: str
    document_subtype: str | None = None
    date_detected: str | None = None
    language: str = "en"
    entities: EntityBag = Field(default_factory=EntityBag)
    quality_score: float = Field(..., ge=0.0, le=1.0)
    quality_issues: list[QualityIssue] = Field(default_factory=list)
    suggested_schema: list[FieldSpec] = Field(default_factory=list)
    confidence: float = Field(..., ge=0.0, le=1.0)
    routing: RoutingDecision
    routing_reason: str
    recommended_dpi: int = 200
    model_used: str
    tokens_in: int
    tokens_out: int
    latency_ms: int
    cost_usd: float
    pages_analyzed: list[int] = Field(default_factory=list)


class ExtractedTable(BaseModel):
    """Table with per-cell evidence."""
    table_id: str
    title: str | None = None
    page: int
    evidence: Evidence
    headers: list[str] = Field(default_factory=list)
    rows: list[list[ExtractedValue]] = Field(default_factory=list)
    confidence: float = Field(..., ge=0.0, le=1.0)


class ExtractionResult(BaseModel):
    """Complete extraction output with evidence."""
    schema_used: list[FieldSpec] = Field(default_factory=list)
    schema_extended: bool = False
    fields: dict[str, ExtractedValue] = Field(default_factory=dict)
    tables: list[ExtractedTable] = Field(default_factory=list)
    sections: list[DocumentSection] = Field(default_factory=list)
    annotations: list[Annotation] = Field(default_factory=list)
    overall_confidence: float = Field(..., ge=0.0, le=1.0)
    field_confidences: dict[str, float] = Field(default_factory=dict)
    evidence_coverage: float
    model_used: str
    tokens_in: int
    tokens_out: int
    latency_ms: int
    cost_usd: float
    pages_processed: list[int] = Field(default_factory=list)
    dpi_used: int


class Document(BaseModel):
    """Core document entity."""
    document_id: UUID = Field(default_factory=uuid4)
    tenant_id: str
    batch_id: str
    source_file: str
    source_path: str
    source_hash: str                 # SHA256 of original
    source_dpi: int | None = None
    page_range: tuple[int, int]      # (start, end) 1-indexed
    page_count: int
    status: DocumentStatus = DocumentStatus.PENDING
    quality_score: float | None = None
    routing: RoutingDecision | None = None
    triage_result: TriageResult | None = None
    extraction_result: ExtractionResult | None = None
    cluster_id: str | None = None
    linked_entities: list[UUID] = Field(default_factory=list)
    related_documents: list[UUID] = Field(default_factory=list)
    embedding: list[float] | None = None
    embedding_model: str | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    pipeline_version: str
    processing_log: list[ProcessingEvent] = Field(default_factory=list)
    total_cost_usd: float = 0.0
