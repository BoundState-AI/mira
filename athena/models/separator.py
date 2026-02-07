#!/usr/bin/env python3
"""
Module: Separator
Purpose: [Automatically migrated - needs manual review]

BoundState AI 2025
Version: 4.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Fran OpenAI 5 <noreply@openai.com>
Co-Authored-By: Grok 4.0 <noreply@x.ai>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: SWE-032, NASA-STD-8739.8B
Safety Critical: True
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class SeparatorResult(BaseModel):
    """Parsed separator sheet from barcode + handwritten fields.

    Separator sheets use barcodes for deterministic boundary detection.
    Handwritten metadata provides folder context without affecting detection.
    """
    separator_id: str                              # UUID from barcode
    confidence: float = 1.0                        # Always 1.0 for barcode match
    folder_name: str | None = None
    date_range_start: str | None = None            # ISO date
    date_range_end: str | None = None              # ISO date
    doc_count_expected: int | None = None
    notes: str | None = None
    scanned_by: str | None = None
    scan_date: str | None = None


class FolderSegment(BaseModel):
    """Documents between two separators.

    A folder segment represents all pages between consecutive separator sheets.
    This provides deterministic document boundary detection.
    """
    segment_id: UUID = Field(default_factory=uuid4)
    batch_id: str
    separator: SeparatorResult                     # Opening separator metadata
    page_range: tuple[int, int]                    # (start, end) in source PDF, 1-indexed
    page_count: int
    document_count_detected: int = 0               # After triage
    documents: list[UUID] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    processing_complete: bool = False
