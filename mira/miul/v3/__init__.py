#!/usr/bin/env python3
"""
MIUL Builder v3 - Enhanced Material Extraction

Combines best approaches from v1 and v2:
- Vision-based extraction with anti-hallucination rules
- Aggressive NOTES parsing for MSFC drawings
- OCR correction for common misreads
- EPL material column extraction
- Material Specification validation (rejects OCR garbage)
- Part number OCR correction (MER70570 -> MER07570, etc.)
- Designation cleanup (removes vendor/supplier pollution)

BoundState AI 2025
"""

from .extract import (
    extract_drawing_page,
    extract_package,
    V3_EXTRACTION_PROMPT,
)
from .ocr_correction import (
    correct_ocr_errors,
    clean_material_spec,
    clean_designation,
    correct_part_number,
    validate_epl_row,
    is_valid_material_spec,
    lookup_standard_part_material,
)

__all__ = [
    "extract_drawing_page",
    "extract_package",
    "V3_EXTRACTION_PROMPT",
    "correct_ocr_errors",
    "clean_material_spec",
    "clean_designation",
    "correct_part_number",
    "validate_epl_row",
    "is_valid_material_spec",
    "lookup_standard_part_material",
]
