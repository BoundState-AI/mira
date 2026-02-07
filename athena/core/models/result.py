#!/usr/bin/env python3
"""
Module: Result
Purpose: ExtractionResult Model.

BoundState AI 2025
Version: 1.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Fran OpenAI 5 <noreply@openai.com>
Co-Authored-By: Grok 4.0 <noreply@x.ai>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: SWE-032, SWE-033
Safety Critical: True
"""

from __future__ import annotations

from pydantic import BaseModel, Field, computed_field

from athena.core.models.grid import TableGrid

__all__ = ["ExtractionResult"]
__safety_critical__ = True


class ExtractionResult(BaseModel):
    """Result of extracting tables from one or more documents."""
    model_config = {"extra": "forbid"}

    extraction_id: str
    extraction_timestamp: str
    extractor_version: str = "1.5.0"

    source_paths: list[str]
    source_hashes: list[str]

    tables: list[TableGrid] = Field(default_factory=list)

    # Stats
    documents_processed: int = 0
    pages_scanned: int = 0
    tables_found_pdfplumber: int = 0
    tables_found_vision_fallback: int = 0
    table_grids_transcribed: int = 0
    tables_failed: int = 0

    # Cost tracking
    api_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0

    @computed_field
    @property
    def estimated_cost_usd(self) -> float:
        """Estimate API cost (Haiku pricing)."""
        input_cost = self.input_tokens * 0.80 / 1_000_000
        output_cost = self.output_tokens * 4.00 / 1_000_000
        return round(input_cost + output_cost, 4)

    failed_documents: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)

    @computed_field
    @property
    def success_rate(self) -> float:
        """Percentage of tables successfully extracted."""
        total = self.table_grids_transcribed + self.tables_failed
        if total == 0:
            return 0.0
        return round(self.table_grids_transcribed / total, 4)
