#!/usr/bin/env python3
"""
Module: Boundary
Purpose: ATHENA Boundary Detection Prompts.

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

BOUNDARY_CONFIRMATION_PROMPT = """Analyze consecutive pages for document boundary.

Is there a document boundary between these pages (page 2 starts a NEW document)?

OUTPUT (strict JSON only):
{
    "is_boundary": true/false,
    "confidence": 0.0-1.0,
    "additional_signals": ["letterhead_change", "date_discontinuity", "form_number_change", "classification_change"],
    "reasoning": "brief explanation"
}

SIGNALS TO LOOK FOR:
- letterhead_change: Different logo, letterhead, or header
- page_numbering_reset: Page number restarts at 1
- date_discontinuity: Large date gap (different year, month)
- form_number_change: Different form number or type
- orientation_change: Portrait/landscape switch
- classification_change: Different classification marking
- barcode_divider: Separator sheet with barcode

DECISION RULES:
- is_boundary = true if the second page clearly starts a new document
- is_boundary = false if pages are part of the same document
- High confidence (>0.8) only if multiple signals present
- A single signal alone is usually not enough

Output ONLY valid JSON. No markdown, no explanations.
"""

PAGE_NUMBER_DETECTION_PROMPT = """Analyze this footer region for page numbering.

OUTPUT (strict JSON only):
{
    "has_page_number": true/false,
    "page_number": null or integer,
    "format": "simple|of_total|roman|none",
    "confidence": 0.0-1.0
}

EXAMPLES:
- "Page 1" -> {"has_page_number": true, "page_number": 1, "format": "simple"}
- "Page 3 of 10" -> {"has_page_number": true, "page_number": 3, "format": "of_total"}
- "iii" -> {"has_page_number": true, "page_number": 3, "format": "roman"}
- No visible number -> {"has_page_number": false, "page_number": null, "format": "none"}

Output ONLY valid JSON.
"""

LETTERHEAD_COMPARISON_PROMPT = """Compare the headers/letterheads of these two page images.

OUTPUT (strict JSON only):
{
    "same_letterhead": true/false,
    "confidence": 0.0-1.0,
    "differences": ["list of observed differences"],
    "reasoning": "brief explanation"
}

Look for:
- Logo/emblem changes
- Organization name changes
- Address/contact info changes
- Header layout changes
- Classification marking changes

Output ONLY valid JSON.
"""
