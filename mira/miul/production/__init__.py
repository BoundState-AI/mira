"""
MIUL Production Pipeline.

The production-grade MIUL builder combining:
- Sonnet Vision extraction (OCR + vision)
- Human-in-the-loop review
- DT-based tree construction
- MAPTIS-compliant Excel export

BoundState AI 2025-2026
"""

from .extractor import (
    ExtractionResult,
    ExtractedMaterial,
    ExtractionEvidence,
    MIULVisionExtractor,
    identify_review_items,
)
from .session import V4Session, get_session, list_sessions, get_session_root
from .pair_builder import (
    build_pair_rows_from_v4_extraction,
    build_miul_from_pair_rows,
    build_parts_json_for_summary,
    validate_miul_tree_against_dt,
)

__all__ = [
    "ExtractionResult",
    "ExtractedMaterial",
    "ExtractionEvidence",
    "MIULVisionExtractor",
    "identify_review_items",
    "V4Session",
    "get_session",
    "list_sessions",
    "get_session_root",
    "build_pair_rows_from_v4_extraction",
    "build_miul_from_pair_rows",
    "build_parts_json_for_summary",
    "validate_miul_tree_against_dt",
]
