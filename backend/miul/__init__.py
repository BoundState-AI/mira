#!/usr/bin/env python3
"""
MIUL v3 Module - Vision-based drawing extraction.
BoundState AI 2025
Version: 3.0.0

Full MIUL functionality for Railway deployment.
"""

import logging

_LOGGER = logging.getLogger(__name__)

# Core extraction (always available - only needs anthropic)
from .extract import (
    VisionClient,
    extract_drawing_page,
    extract_drawing_tree,
    extract_parts_json,
    extract_package,
    pdf_to_images,
    postprocess_extraction,
    V3_EXTRACTION_PROMPT,
)

# OCR correction (standard library only)
from .ocr_correction import (
    correct_ocr_errors,
    correct_part_number,
    clean_material_spec,
    clean_designation,
    extract_material_from_notes,
    normalize_designation,
    normalize_material_spec,
    lookup_standard_part_material,
    validate_epl_row,
    is_invalid_part_number,
    get_invalid_reason,
)

# Builder (requires pandas, openpyxl - optional)
try:
    from .builder import (
        MIULBuilderV3,
        build_miul_from_directory,
        build_miul_2phase,
        merge_dt_and_parts,
        MIUL_COLUMNS,
        MAPTIS_COLUMNS,
    )
    BUILDER_AVAILABLE = True
except ImportError as e:
    _LOGGER.warning(f"MIUL Builder not available (missing pandas/openpyxl): {e}")
    BUILDER_AVAILABLE = False
    MIULBuilderV3 = None
    build_miul_from_directory = None
    build_miul_2phase = None
    merge_dt_and_parts = None
    MIUL_COLUMNS = []
    MAPTIS_COLUMNS = []

__all__ = [
    # extract.py
    "VisionClient",
    "extract_drawing_page",
    "extract_drawing_tree",
    "extract_parts_json",
    "extract_package",
    "pdf_to_images",
    "postprocess_extraction",
    "V3_EXTRACTION_PROMPT",
    # ocr_correction.py
    "correct_ocr_errors",
    "correct_part_number",
    "clean_material_spec",
    "clean_designation",
    "extract_material_from_notes",
    "normalize_designation",
    "normalize_material_spec",
    "lookup_standard_part_material",
    "validate_epl_row",
    "is_invalid_part_number",
    "get_invalid_reason",
    # builder.py (optional - requires pandas/openpyxl)
    "BUILDER_AVAILABLE",
    "MIULBuilderV3",
    "build_miul_from_directory",
    "build_miul_2phase",
    "merge_dt_and_parts",
    "MIUL_COLUMNS",
    "MAPTIS_COLUMNS",
]

__safety_critical__ = True
