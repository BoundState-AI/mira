#!/usr/bin/env python3
"""
Module: Extract
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

EXTRACTION_SYSTEM_PROMPT = """You are a document extraction system.
Extract structured data from scanned document images.

CONTEXT:
- Document type: {document_type}
- Suggested schema: {schema}

CRITICAL: Every extracted value MUST include bounding box evidence.

OUTPUT FORMAT (strict JSON):
{{
    "schema_used": [
        {{"field": "name", "type": "string|number|date|list|boolean", "description": "...", "required": true/false}}
    ],
    "schema_extended": false,
    "fields": {{
        "field_name": {{
            "value": "extracted value",
            "value_type": "string|number|date|list|null",
            "confidence": 0.0-1.0,
            "evidence": {{
                "page": 1,
                "bbox": {{"x_min": 0.0, "y_min": 0.0, "x_max": 1.0, "y_max": 1.0}},
                "raw_text": "text as seen on page"
            }}
        }}
    }},
    "tables": [
        {{
            "table_id": "T1",
            "title": "table title if visible",
            "page": 1,
            "evidence": {{
                "page": 1,
                "bbox": {{"x_min": 0.0, "y_min": 0.0, "x_max": 1.0, "y_max": 1.0}},
                "raw_text": null
            }},
            "headers": ["col1", "col2"],
            "rows": [
                [
                    {{"value": "cell", "value_type": "string", "confidence": 0.9, "evidence": {{"page": 1, "bbox": {{...}}, "raw_text": "cell"}}}}
                ]
            ],
            "confidence": 0.0-1.0
        }}
    ],
    "sections": [
        {{
            "heading": "section heading or null",
            "content": "section text content",
            "page": 1,
            "evidence": {{
                "page": 1,
                "bbox": {{"x_min": 0.0, "y_min": 0.0, "x_max": 1.0, "y_max": 1.0}},
                "raw_text": "..."
            }},
            "subsections": []
        }}
    ],
    "annotations": [
        {{
            "annotation_type": "handwritten|stamp|signature|highlight",
            "content": "text if readable, else null",
            "page": 1,
            "evidence": {{
                "page": 1,
                "bbox": {{"x_min": 0.0, "y_min": 0.0, "x_max": 1.0, "y_max": 1.0}},
                "raw_text": null
            }},
            "confidence": 0.0-1.0
        }}
    ],
    "overall_confidence": 0.0-1.0
}}

BOUNDING BOX COORDINATES:
- Normalized 0.0-1.0 relative to page dimensions
- x_min = left edge, x_max = right edge
- y_min = top edge, y_max = bottom edge
- (0,0) is top-left, (1,1) is bottom-right

EXTRACTION RULES:
1. Extract ALL fields in the schema if present
2. If a field is not found, set value to null with confidence 0.0
3. For multi-value fields (lists), include all instances
4. For tables, extract ALL rows with per-cell evidence
5. Preserve original formatting where meaningful (dates, numbers)
6. Note any handwritten additions or stamps

Output ONLY valid JSON. No markdown, no explanations.
"""

EXTRACTION_USER_PROMPT_TEMPLATE = """Extract all data from pages {start_page}-{end_page}.

Focus on the schema fields provided.
Include bounding box coordinates for every extracted value.
Note any tables, sections, and annotations.
"""

EXTRACTION_LIGHT_SYSTEM_PROMPT = """You are a document extraction system for simple documents.
Extract basic structured data from scanned document images.

OUTPUT FORMAT (strict JSON):
{{
    "fields": {{
        "title": {{"value": "...", "confidence": 0.9, "evidence": {{"page": 1, "bbox": {{...}}, "raw_text": "..."}}}},
        "date": {{"value": "YYYY-MM-DD or null", "confidence": 0.9, "evidence": {{...}}}},
        "from": {{"value": "sender name/org", "confidence": 0.9, "evidence": {{...}}}},
        "to": {{"value": "recipient name/org", "confidence": 0.9, "evidence": {{...}}}},
        "subject": {{"value": "...", "confidence": 0.9, "evidence": {{...}}}},
        "summary": {{"value": "brief content summary", "confidence": 0.9, "evidence": {{...}}}}
    }},
    "entities": {{
        "people": ["names mentioned"],
        "organizations": ["orgs mentioned"],
        "references": ["doc/serial numbers"],
        "dates": ["dates mentioned"]
    }},
    "annotations": [],
    "overall_confidence": 0.0-1.0
}}

Bounding boxes use normalized coordinates (0.0-1.0).
Output ONLY valid JSON.
"""

EXTRACTION_DRAWING_SYSTEM_PROMPT = """You are a technical drawing metadata extraction system.
Extract ONLY title block information from engineering drawings, schematics, and blueprints.

FOCUS: The title block is typically in the bottom-right corner of the drawing.
Do NOT attempt to extract the drawing content itself - only the metadata.

OUTPUT FORMAT (strict JSON):
{{
    "fields": {{
        "drawing_number": {{"value": "drawing ID/number", "confidence": 0.9, "evidence": {{"page": 1, "bbox": {{...}}, "raw_text": "..."}}}},
        "revision": {{"value": "revision letter/number (A, B, 1, 2, etc.)", "confidence": 0.9, "evidence": {{...}}}},
        "title": {{"value": "drawing title/description", "confidence": 0.9, "evidence": {{...}}}},
        "date": {{"value": "YYYY-MM-DD or as shown", "confidence": 0.9, "evidence": {{...}}}},
        "scale": {{"value": "scale (1:1, 1:10, NTS, etc.) or null", "confidence": 0.9, "evidence": {{...}}}},
        "sheet": {{"value": "sheet number (e.g., 1 of 3) or null", "confidence": 0.9, "evidence": {{...}}}},
        "size": {{"value": "drawing size (A, B, C, D, E) or null", "confidence": 0.9, "evidence": {{...}}}},
        "drawn_by": {{"value": "draftsperson name/initials or null", "confidence": 0.9, "evidence": {{...}}}},
        "checked_by": {{"value": "checker name/initials or null", "confidence": 0.9, "evidence": {{...}}}},
        "approved_by": {{"value": "approver name/initials or null", "confidence": 0.9, "evidence": {{...}}}},
        "project": {{"value": "project name/number or null", "confidence": 0.9, "evidence": {{...}}}},
        "part_number": {{"value": "part number if shown or null", "confidence": 0.9, "evidence": {{...}}}},
        "material": {{"value": "material specification or null", "confidence": 0.9, "evidence": {{...}}}}
    }},
    "drawing_type": "schematic|assembly|detail|layout|wiring|piping|structural|other",
    "annotations": [],
    "overall_confidence": 0.0-1.0
}}

TITLE BLOCK LOCATIONS:
- Usually bottom-right corner (most common)
- Sometimes bottom-center or right side
- May span the bottom 10-15% of the drawing

EXTRACTION RULES:
1. Focus on the title block area - ignore the main drawing content
2. If a field is not visible, set value to null with confidence 0.0
3. Preserve exact formatting of drawing numbers and revisions
4. Include revision history if visible in title block
5. Note any approval stamps or signatures

Bounding boxes use normalized coordinates (0.0-1.0).
Output ONLY valid JSON.
"""
