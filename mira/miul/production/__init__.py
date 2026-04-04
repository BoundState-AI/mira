"""
MIUL Production Pipeline.

Import heavy production helpers lazily so API startup can use lightweight
session/storage utilities without requiring Excel-export dependencies.

BoundState AI 2025-2026
"""

from __future__ import annotations

from importlib import import_module

_EXTRACTOR_EXPORTS = {
    "ExtractionResult",
    "ExtractedMaterial",
    "ExtractionEvidence",
    "MIULVisionExtractor",
    "identify_review_items",
}
_SESSION_EXPORTS = {"V4Session", "get_session", "list_sessions", "get_session_root"}
_PAIR_BUILDER_EXPORTS = {
    "build_pair_rows_from_v4_extraction",
    "build_miul_from_pair_rows",
    "build_parts_json_for_summary",
    "validate_miul_tree_against_dt",
}

__all__ = [
    *_EXTRACTOR_EXPORTS,
    *_SESSION_EXPORTS,
    *_PAIR_BUILDER_EXPORTS,
]


def __getattr__(name: str):
    if name in _EXTRACTOR_EXPORTS:
        module = import_module(".extractor", __name__)
        return getattr(module, name)
    if name in _SESSION_EXPORTS:
        module = import_module(".session", __name__)
        return getattr(module, name)
    if name in _PAIR_BUILDER_EXPORTS:
        module = import_module(".pair_builder", __name__)
        return getattr(module, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
