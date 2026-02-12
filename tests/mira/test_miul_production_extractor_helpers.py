#!/usr/bin/env python3
"""
Module: Test MIUL Production Extractor Helpers
Purpose: Guard filename/drawing-number matching rules used by MIUL v4 extractor.
"""

from __future__ import annotations

from pathlib import Path

from mira.miul.production import extractor


def test_extract_drawing_number_prefers_dt_match_over_filename_prefix_noise():
    dt_json = {
        "tree": [
            {"drawing_number": "GPE-A200-1", "parent": "GPE-A000-1", "type": "ASSEMBLY"},
            {"drawing_number": "GPE-206-1/2", "parent": "GPE-A200-1", "type": "DETAIL"},
        ]
    }

    drawing = extractor._extract_drawing_number(  # noqa: SLF001
        Path("ce8206ee__GPE-206-A_(GUIDE_PIN_DRAWING).pdf"),
        dt_json=dt_json,
    )
    assert drawing == "GPE-206-1/2"


def test_extract_drawing_number_keeps_candidate_when_dt_variant_match_is_ambiguous():
    dt_json = {
        "tree": [
            {"drawing_number": "GPE-010-1", "parent": "GPE-A000-1"},
            {"drawing_number": "GPE-010-2", "parent": "GPE-A000-1"},
        ]
    }

    drawing = extractor._extract_drawing_number(  # noqa: SLF001
        Path("GPE-010-A (TOP PLATE DRAWING).pdf"),
        dt_json=dt_json,
    )
    assert drawing == "GPE-010-A"


def test_extract_drawing_number_handles_standard_drw_filename():
    drawing = extractor._extract_drawing_number(  # noqa: SLF001
        Path("MER07545-001_DRW_-_12_RELEASED.pdf"),
        dt_json=None,
    )
    assert drawing == "MER07545-001"


def test_get_dt_context_accepts_variant_form_of_drawing_number():
    dt_json = {
        "tree": [
            {
                "drawing_number": "GPE-A200-1",
                "parent": "GPE-A000-1",
                "title": "Backplate Assembly",
                "type": "ASSEMBLY",
            },
            {
                "drawing_number": "GPE-206-1/2",
                "parent": "GPE-A200-1",
                "title": "Guide Pin",
                "type": "DETAIL",
            },
        ]
    }

    context = extractor._get_dt_context(dt_json, "GPE-206-A")  # noqa: SLF001
    assert context is not None
    assert context["drawing_number"] == "GPE-206-1/2"
    assert context["parent"] == "GPE-A200-1"


def test_fallback_epl_materials_from_page_text_extracts_parts_when_header_present():
    page_text = """
    ENGINEERING PARTS LIST
    IMER07616-001
    B
    BODY
    TITANIUM 6AL-4V
    NAS1587-5C
    -
    COUNTERSUNK WASHER
    321 OR 347 CRES
    """

    rows = extractor._fallback_epl_materials_from_page_text(  # noqa: SLF001
        page_text=page_text,
        source_file="IMER07614A.pdf",
        page_number=2,
    )

    parts = {row.part_number for row in rows}
    assert "IMER07616-001" in parts
    assert "NAS1587-5C" in parts
    assert all(row.source_page == 2 for row in rows)


def test_fallback_epl_materials_from_page_text_extracts_no_dash_and_sae_mil_part_numbers():
    page_text = """
    ENGINEERING PARTS LIST
    93043A327
    -
    HEX NUT
    A286 CRES
    SAE J514 4-2 070120S
    -
    FITTING
    300 SERIES CRES
    MIL-PRF-27617G
    -
    LUBRICANT
    TYPE I, II, III
    """

    rows = extractor._fallback_epl_materials_from_page_text(  # noqa: SLF001
        page_text=page_text,
        source_file="IMER07614A.pdf",
        page_number=2,
    )
    by_pn = {row.part_number: row for row in rows}

    assert "93043A327" in by_pn
    assert "SAE J514 4-2 070120S" in by_pn
    assert "MIL-PRF-27617G" in by_pn
    assert by_pn["93043A327"].part_description == "HEX NUT"
    assert by_pn["MIL-PRF-27617G"].designation == "TYPE I, II, III"


def test_fallback_epl_materials_from_page_text_requires_epl_header():
    page_text = """
    NOTES
    1. MATERIAL SHALL CONFORM TO MIL-PRF-27407D.
    IMER07616-001
    BODY
    """

    rows = extractor._fallback_epl_materials_from_page_text(  # noqa: SLF001
        page_text=page_text,
        source_file="IMER07614A.pdf",
        page_number=2,
    )
    assert rows == []
