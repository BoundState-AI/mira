#!/usr/bin/env python3
"""
Module:   Init  
Purpose: ATHENA Extraction Layer.

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

__safety_critical__ = True

from athena.extraction.extractor import TableExtractor, extract_tables
from athena.extraction.detector import TableDetector
from athena.extraction.transcriber import TableTranscriber
from athena.extraction.prompts import TABLE_EXTRACTION_PROMPT, TABLE_DETECTION_PROMPT
from athena.extraction.standards_extractor import (
    StandardsExtractor,
    StandardsExtractionResult,
    extract_standards,
)

__all__ = [
    "TableExtractor",
    "TableDetector",
    "TableTranscriber",
    "extract_tables",
    "StandardsExtractor",
    "StandardsExtractionResult",
    "extract_standards",
    "TABLE_EXTRACTION_PROMPT",
    "TABLE_DETECTION_PROMPT",
]
