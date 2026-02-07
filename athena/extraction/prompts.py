#!/usr/bin/env python3
"""
Module: Prompts
Purpose: ATHENA Vision Prompts.

BoundState AI 2025
Version: 1.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Fran OpenAI 5 <noreply@openai.com>
Co-Authored-By: Grok 4.0 <noreply@x.ai>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: SWE-032
Safety Critical: True
"""

from __future__ import annotations

__all__ = ["TABLE_EXTRACTION_PROMPT", "TABLE_DETECTION_PROMPT"]
__safety_critical__ = True


TABLE_EXTRACTION_PROMPT = """Extract ALL tables from this document page as JSON.

For each table, return:
{
  "cells": [
    {"r": 0, "c": 0, "text": "cell content"},
    ...
  ],
  "row_count": N,
  "col_count": N
}

Rules:
- r = row index (0-based)
- c = column index (0-based)
- Include ALL rows, even if table has no visible borders
- Empty cells: text = null or ""

Return JSON only."""


TABLE_DETECTION_PROMPT = """Find all tables in this page image.

Tables may be:
1. BORDERED - visible lines/grid separating cells
2. BORDERLESS - text aligned in columns without visible lines (glossaries, acronym lists, property lists)

For each table, return its bounding box as [x0, y0, x1, y1] in pixels from top-left origin.

Return JSON:
{
  "tables": [
    {"bbox": [100, 200, 500, 600], "table_type": "bordered", "description": "Materials properties table"},
    {"bbox": [100, 700, 500, 900], "table_type": "borderless", "description": "Acronym glossary"}
  ]
}

RULES:
- Find ALL tables - both bordered AND borderless
- BORDERLESS tables are common: glossaries, acronym lists, two-column definitions
- For borderless tables, estimate bbox from the full text region
- bbox is [left, top, right, bottom] in pixels from top-left corner
- Include ALL rows of the table in the bbox (don't cut off early)
- If no tables found, return {"tables": []}

Return ONLY the JSON object."""
