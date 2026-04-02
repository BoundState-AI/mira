"""
MIUL production package.

Keep imports lazy so session/state helpers do not require the heavy
extractor stack at import time.
"""

from __future__ import annotations

from importlib import import_module

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


_EXPORT_MAP = {
    "ExtractionResult": (".extractor", "ExtractionResult"),
    "ExtractedMaterial": (".extractor", "ExtractedMaterial"),
    "ExtractionEvidence": (".extractor", "ExtractionEvidence"),
    "MIULVisionExtractor": (".extractor", "MIULVisionExtractor"),
    "identify_review_items": (".extractor", "identify_review_items"),
    "V4Session": (".session", "V4Session"),
    "get_session": (".session", "get_session"),
    "list_sessions": (".session", "list_sessions"),
    "get_session_root": (".session", "get_session_root"),
    "build_pair_rows_from_v4_extraction": (".pair_builder", "build_pair_rows_from_v4_extraction"),
    "build_miul_from_pair_rows": (".pair_builder", "build_miul_from_pair_rows"),
    "build_parts_json_for_summary": (".pair_builder", "build_parts_json_for_summary"),
    "validate_miul_tree_against_dt": (".pair_builder", "validate_miul_tree_against_dt"),
}


def __getattr__(name: str):
    try:
        module_name, attr_name = _EXPORT_MAP[name]
    except KeyError as exc:
        raise AttributeError(name) from exc

    module = import_module(module_name, __name__)
    value = getattr(module, attr_name)
    globals()[name] = value
    return value
