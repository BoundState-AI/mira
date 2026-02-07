#!/usr/bin/env python3
"""
Module:   Init  
Purpose: ATHENA Extraction Prompts.

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

from athena.extraction.prompts.h2 import (
    H2_TABLE_EXTRACTION_PROMPT,
    H2_ENRICHMENT_PROMPT,
    H2_CONTEXT_FIELDS,
)

__all__ = [
    "H2_TABLE_EXTRACTION_PROMPT",
    "H2_ENRICHMENT_PROMPT",
    "H2_CONTEXT_FIELDS",
]
