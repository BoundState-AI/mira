#!/usr/bin/env python3
"""
Module: Test MIUL Pair Builder
Purpose: Regression tests for v4 pair-row MIUL tree semantics.
"""

from __future__ import annotations

import importlib.util
import os
from typing import Any, Dict
from pathlib import Path


def _load_pair_builder():
    root = Path(__file__).resolve().parents[2]
    module_path = root / "mira" / "miul" / "production" / "pair_builder.py"
    spec = importlib.util.spec_from_file_location("pair_builder_under_test", module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_pair_builder = _load_pair_builder()
build_miul_from_pair_rows = _pair_builder.build_miul_from_pair_rows
build_pair_rows_from_v4_extraction = _pair_builder.build_pair_rows_from_v4_extraction
validate_miul_tree_against_dt = _pair_builder.validate_miul_tree_against_dt


def _first_row_for_part(df, part_number: str):
    match = df[df["Part Number"].fillna("").astype(str).str.upper() == part_number.upper()]
    assert not match.empty, f"Missing row for part number: {part_number}"
    return match.iloc[0]


def _index_by_part(df) -> Dict[str, int]:
    out: Dict[str, int] = {}
    data = df[df["Index"].fillna(0).astype(int) >= 3]
    for _, row in data.sort_values("Index").iterrows():
        pn = str(row.get("Part Number") or "").strip().upper()
        if pn and pn not in out:
            out[pn] = int(row["Index"])
    return out


def test_pair_builder_nha_semantics_tree_vs_subpart():
    dt_json: Dict[str, Any] = {
        "top_level": "MER07540-001",
        "tree": [
            {"drawing_number": "MER07543-001", "parent": "", "title": "Parent Assembly"},
            {"drawing_number": "MER07545-001", "parent": "MER07543-001", "title": "Child Assembly"},
        ],
    }

    pair_rows = [
        {
            "part_number": "MER07543-001",
            "source_drawing": "MER07540-001",
            "part_description": "Parent Assembly",
            "designation": "",
            "material_spec": "",
            "process_spec": "",
            "material_form": "",
        },
        {
            # Source drawing is intentionally wrong to ensure tree parent comes from DT.
            "part_number": "MER07545-001",
            "source_drawing": "MER07576-001",
            "part_description": "Child Assembly",
            "designation": "",
            "material_spec": "",
            "process_spec": "",
            "material_form": "",
        },
        {
            "part_number": "NAS1149E0432R",
            "source_drawing": "MER07545-001",
            "part_description": "Washer",
            "designation": "CRES",
            "material_spec": "ASTM A240",
            "process_spec": "",
            "material_form": "",
        },
    ]

    df = build_miul_from_pair_rows(pair_rows, dt_json, project="DMLLV")
    idx_map = _index_by_part(df)

    # Header bootstrap rows
    row1 = _first_row_for_part(df[df["Index"] == 1], "MER07540")
    row2 = _first_row_for_part(df[df["Index"] == 2], "MER07540")
    assert int(row1["Parent"]) == 0
    assert int(row2["Parent"]) == 0
    assert str(row2["NHA"]) == "MER07540"

    # Tree assemblies: NHA must equal MIUL acronym and Parent follows DT tree.
    parent_assembly = _first_row_for_part(df, "MER07543-001")
    child_assembly = _first_row_for_part(df, "MER07545-001")
    assert str(parent_assembly["NHA"]) == "MER07540"
    assert str(child_assembly["NHA"]) == "MER07540"
    assert int(parent_assembly["Parent"]) == 2
    assert int(child_assembly["Parent"]) == idx_map["MER07543-001"]

    # Subpart rows: NHA must be blank and Parent points to containing assembly.
    washer = _first_row_for_part(df, "NAS1149E0432R")
    assert str(washer["NHA"] or "") == ""
    assert int(washer["Parent"]) == idx_map["MER07545-001"]

    # Sentinel exists.
    sentinel = df[df["Index"] == -1]
    assert len(sentinel) == 1


def test_pair_builder_regression_mer07573_branch_parent_links():
    dt_json: Dict[str, Any] = {
        "top_level": "MER07540-001",
        "tree": [
            {"drawing_number": "MER07573-001", "parent": "MER07540-001", "title": "Branch Parent"},
            {"drawing_number": "MER07581-001", "parent": "MER07573-001", "title": "Child 81"},
            {"drawing_number": "MER07582-001", "parent": "MER07573-001", "title": "Child 82"},
            {"drawing_number": "MER07577-001", "parent": "MER07573-001", "title": "Child 77"},
            {"drawing_number": "MER07583-001", "parent": "MER07573-001", "title": "Child 83"},
        ],
    }

    pair_rows = [
        {
            "part_number": "MER07573-001",
            "source_drawing": "MER07550-001",
            "part_description": "Branch Parent",
            "designation": "",
            "material_spec": "",
            "process_spec": "",
            "material_form": "",
        },
        # These intentionally carry the wrong source drawing to reproduce the bug.
        {
            "part_number": "MER07581-001",
            "source_drawing": "MER07576-001",
            "part_description": "Child 81",
            "designation": "",
            "material_spec": "",
            "process_spec": "",
            "material_form": "",
        },
        {
            "part_number": "MER07582-001",
            "source_drawing": "MER07576-001",
            "part_description": "Child 82",
            "designation": "",
            "material_spec": "",
            "process_spec": "",
            "material_form": "",
        },
        {
            "part_number": "MER07577-001",
            "source_drawing": "MER07576-001",
            "part_description": "Child 77",
            "designation": "",
            "material_spec": "",
            "process_spec": "",
            "material_form": "",
        },
        {
            "part_number": "MER07583-001",
            "source_drawing": "MER07576-001",
            "part_description": "Child 83",
            "designation": "",
            "material_spec": "",
            "process_spec": "",
            "material_form": "",
        },
    ]

    df = build_miul_from_pair_rows(pair_rows, dt_json, project="DMLLV")
    idx_map = _index_by_part(df)
    expected_parent_idx = idx_map["MER07573-001"]

    for child in ("MER07581-001", "MER07582-001", "MER07577-001", "MER07583-001"):
        row = _first_row_for_part(df, child)
        assert int(row["Parent"]) == expected_parent_idx
        assert int(row["Parent"]) != 2
        assert str(row["NHA"]) == "MER07540"


def test_pair_builder_includes_dt_skeleton_even_when_pair_rows_missing():
    dt_json: Dict[str, Any] = {
        "top_level": "MER07540-001",
        "tree": [
            {"drawing_number": "MER07543-001", "parent": "MER07540-001", "title": "Parent Assembly"},
            {"drawing_number": "MER07545-001", "parent": "MER07543-001", "title": "Child Assembly"},
            {"drawing_number": "MER07546-001", "parent": "MER07543-001", "title": "Sibling Assembly"},
        ],
    }

    # Pair rows only contain one assembly and one subpart.
    pair_rows = [
        {
            "part_number": "MER07545-001",
            "source_drawing": "MER07543-001",
            "part_description": "Child Assembly",
            "designation": "",
            "material_spec": "",
            "process_spec": "",
            "material_form": "",
        },
        {
            "part_number": "NAS1149E0432R",
            "source_drawing": "MER07545-001",
            "part_description": "Washer",
            "designation": "CRES",
            "material_spec": "ASTM A240",
            "process_spec": "",
            "material_form": "",
        },
    ]

    df = build_miul_from_pair_rows(pair_rows, dt_json, project="DMLLV")
    idx_map = _index_by_part(df)

    # Missing DT assemblies must still exist in output.
    assert "MER07543-001" in idx_map
    assert "MER07545-001" in idx_map
    assert "MER07546-001" in idx_map

    row_7543 = _first_row_for_part(df, "MER07543-001")
    row_7545 = _first_row_for_part(df, "MER07545-001")
    row_7546 = _first_row_for_part(df, "MER07546-001")
    assert int(row_7543["Parent"]) == 2
    assert int(row_7545["Parent"]) == idx_map["MER07543-001"]
    assert int(row_7546["Parent"]) == idx_map["MER07543-001"]
    assert str(row_7543["NHA"]) == "MER07540"
    assert str(row_7545["NHA"]) == "MER07540"
    assert str(row_7546["NHA"]) == "MER07540"


def test_tree_validator_detects_parent_mismatch():
    dt_json: Dict[str, Any] = {
        "top_level": "MER07540-001",
        "tree": [
            {"drawing_number": "MER07543-001", "parent": "MER07540-001", "title": "Parent Assembly"},
            {"drawing_number": "MER07545-001", "parent": "MER07543-001", "title": "Child Assembly"},
        ],
    }

    pair_rows = [
        {
            "part_number": "MER07543-001",
            "source_drawing": "MER07540-001",
            "part_description": "Parent Assembly",
            "designation": "",
            "material_spec": "",
            "process_spec": "",
            "material_form": "",
        },
        {
            "part_number": "MER07545-001",
            "source_drawing": "MER07543-001",
            "part_description": "Child Assembly",
            "designation": "",
            "material_spec": "",
            "process_spec": "",
            "material_form": "",
        },
    ]

    df = build_miul_from_pair_rows(pair_rows, dt_json, project="DMLLV")
    child_idx = int(_first_row_for_part(df, "MER07545-001")["Index"])
    # Force a bad parent to simulate regression.
    df.loc[df["Index"] == child_idx, "Parent"] = 2

    validation = validate_miul_tree_against_dt(df, dt_json)
    assert validation["valid"] is False
    assert len(validation["parent_mismatches"]) == 1
    assert validation["parent_mismatches"][0]["part_number"] == "MER07545-001"


def test_pair_rows_can_be_built_from_drawing_packages():
    old = os.environ.get("MIUL_V4_USE_DRAWING_PACKAGES")
    os.environ["MIUL_V4_USE_DRAWING_PACKAGES"] = "1"
    try:
        class FakeExtraction:
            materials = []
            drawing_packages = [
                {
                    "drawing_number": "MER07543-001",
                    "materials": [
                        {
                            "part_number": "NAS1149E0432R",
                            "part_description": "Washer",
                            "designation": "CRES",
                            "material_spec": "ASTM A240",
                            "process_spec": "",
                            "material_form": "",
                            "source_file": "MER07543-001_DRW.pdf",
                            "source_page": 2,
                            "confidence": {
                                "designation": 0.9,
                                "material_spec": 0.7,
                                "process_spec": 0.0,
                                "material_form": 0.0,
                            },
                        }
                    ],
                }
            ]

        dt_json = {
            "top_level": "MER07540-001",
            "tree": [{"drawing_number": "MER07543-001", "parent": "MER07540-001", "title": "Parent"}],
        }
        pair_rows = build_pair_rows_from_v4_extraction(FakeExtraction(), review_data=None, dt_json=dt_json)
        assert len(pair_rows) == 1
        assert pair_rows[0]["part_number"] == "NAS1149E0432R"
        assert pair_rows[0]["source_drawing"] == "MER07543-001"
    finally:
        if old is None:
            os.environ.pop("MIUL_V4_USE_DRAWING_PACKAGES", None)
        else:
            os.environ["MIUL_V4_USE_DRAWING_PACKAGES"] = old


def test_pair_rows_prune_blank_duplicate_sources_when_identity_exists():
    old = os.environ.get("MIUL_V4_USE_DRAWING_PACKAGES")
    os.environ["MIUL_V4_USE_DRAWING_PACKAGES"] = "1"
    try:
        class FakeExtraction:
            materials = []
            drawing_packages = [
                {
                    "drawing_number": "GPE-A200-B",
                    "materials": [
                        {
                            "part_number": "GPE-206-1",
                            "part_description": "Guide Pin",
                            "designation": "",
                            "material_spec": "",
                            "process_spec": "",
                            "material_form": "",
                            "source_file": "GPE-A200-B.pdf",
                            "source_page": 1,
                            "confidence": {"designation": 0.0},
                        }
                    ],
                },
                {
                    "drawing_number": "GPE-206-A",
                    "materials": [
                        {
                            "part_number": "GPE-206-1",
                            "part_description": "Guide Pin",
                            "designation": "15-5PH CRES",
                            "material_spec": "SAE AMS 5659",
                            "process_spec": "",
                            "material_form": "BAR",
                            "source_file": "GPE-206-A.pdf",
                            "source_page": 2,
                            "confidence": {
                                "designation": 1.0,
                                "material_spec": 0.9,
                                "material_form": 0.9,
                            },
                        }
                    ],
                },
            ]

        dt_json = {
            "top_level": "GPE-A000-1",
            "tree": [{"drawing_number": "GPE-206-1/2", "parent": "GPE-A200-1", "title": "Guide Pin"}],
        }
        pair_rows = build_pair_rows_from_v4_extraction(FakeExtraction(), review_data=None, dt_json=dt_json)
        rows = [r for r in pair_rows if r["part_number"] == "GPE-206-1"]
        assert len(rows) == 1
        assert rows[0]["designation"] == "15-5PH CRES"
        assert rows[0]["source_drawing"] == "GPE-206-A"
    finally:
        if old is None:
            os.environ.pop("MIUL_V4_USE_DRAWING_PACKAGES", None)
        else:
            os.environ["MIUL_V4_USE_DRAWING_PACKAGES"] = old


def test_structured_builder_maps_dt_node_to_canonical_part_variant():
    dt_json: Dict[str, Any] = {
        "top_level": "GPE-A000-1",
        "tree": [
            {"drawing_number": "GPE-A200-1", "parent": "GPE-A000-1", "title": "Backplate Assembly"},
            {"drawing_number": "GPE-206-1/2", "parent": "GPE-A200-1", "title": "Guide Pin"},
        ],
    }

    pair_rows = [
        {
            "part_number": "GPE-206-1",
            "source_drawing": "GPE-206-A",
            "part_description": "Guide Pin, Round",
            "designation": "15-5PH CRES",
            "material_spec": "SAE AMS 5659",
            "process_spec": "",
            "material_form": "BAR",
        },
    ]

    df = build_miul_from_pair_rows(pair_rows, dt_json, project="GPE")
    row = _first_row_for_part(df, "GPE-206-1/2")
    assert str(row["Designation"]) == "15-5PH CRES"
    assert str(row["Material Specification"]) == "SAE AMS 5659"


def test_builder_supports_no_dt_json_with_degraded_hierarchy():
    pair_rows = [
        {
            "part_number": "GPE-VALVE-001",
            "source_drawing": "GPE-VALVE-001",
            "part_description": "Valve Body",
            "designation": "INCONEL 718",
            "material_spec": "AMS 5662",
            "process_spec": "",
            "material_form": "BAR",
        },
        {
            "part_number": "NAS1149E0432R",
            "source_drawing": "GPE-VALVE-001",
            "part_description": "Washer",
            "designation": "CRES",
            "material_spec": "ASTM A240",
            "process_spec": "",
            "material_form": "",
        },
    ]

    df = build_miul_from_pair_rows(pair_rows, dt_json={}, project="GPE")
    idx_map = _index_by_part(df)

    assert "GPE-VALVE-001" in idx_map
    assert "NAS1149E0432R" in idx_map
    assert int(_first_row_for_part(df, "GPE-VALVE-001")["Parent"]) == 2
    assert int(_first_row_for_part(df, "NAS1149E0432R")["Parent"]) == 2
    assert str(_first_row_for_part(df, "GPE-VALVE-001")["NHA"] or "") == ""
    assert str(_first_row_for_part(df, "NAS1149E0432R")["NHA"] or "") == ""

    validation = validate_miul_tree_against_dt(df, {})
    assert validation["valid"] is True
    assert validation["missing_nodes"] == []
    assert validation["parent_mismatches"] == []


def test_builder_no_dt_groups_rows_by_source_drawing():
    pair_rows = [
        {
            "part_number": "PART-B1",
            "source_drawing": "DWG-B",
            "part_description": "Part B1",
            "designation": "MAT-B1",
            "material_spec": "",
            "process_spec": "",
            "material_form": "",
        },
        {
            "part_number": "PART-A1",
            "source_drawing": "DWG-A",
            "part_description": "Part A1",
            "designation": "MAT-A1",
            "material_spec": "",
            "process_spec": "",
            "material_form": "",
        },
        {
            "part_number": "PART-B2",
            "source_drawing": "DWG-B",
            "part_description": "Part B2",
            "designation": "MAT-B2",
            "material_spec": "",
            "process_spec": "",
            "material_form": "",
        },
        {
            "part_number": "PART-A2",
            "source_drawing": "DWG-A",
            "part_description": "Part A2",
            "designation": "MAT-A2",
            "material_spec": "",
            "process_spec": "",
            "material_form": "",
        },
    ]

    df = build_miul_from_pair_rows(pair_rows, dt_json={}, project="GPE")
    data = df[df["Index"].fillna(0).astype(int) >= 3].copy()
    ordered_sources = [str(v or "").strip() for v in data.sort_values("Index")["Drawing Source"].tolist()]
    assert ordered_sources == ["DWG-A", "DWG-A", "DWG-B", "DWG-B"]


def test_part_number_match_keys_include_variant_and_core_forms():
    match_keys = _pair_builder._part_number_match_keys  # noqa: SLF001

    # Keep core two-segment IDs stable.
    assert match_keys("MER07543-001") == {"MER07543-001"}
    assert match_keys("GPE-103") == {"GPE-103"}

    # Variant forms should include both original and trimmed keys.
    assert {"GPE-103-1", "GPE-103"}.issubset(match_keys("GPE-103-1"))
    assert {"GPE-206-1/2", "GPE-206"}.issubset(match_keys("GPE-206-1/2"))


def test_source_drawing_from_file_uses_dt_matching_not_first_underscore_token():
    source_from_file = _pair_builder._source_drawing_from_file  # noqa: SLF001

    source = source_from_file(
        "ce8206ee__GPE-206-A_(GUIDE_PIN_DRAWING).pdf",
        dt_lookup={"GPE-A200-1", "GPE-206-1/2"},
    )
    assert source == "GPE-206-1/2"


def test_source_drawing_from_file_keeps_candidate_when_dt_match_is_ambiguous():
    source_from_file = _pair_builder._source_drawing_from_file  # noqa: SLF001

    source = source_from_file(
        "GPE-010-A (TOP PLATE DRAWING).pdf",
        dt_lookup={"GPE-010-1", "GPE-010-2"},
    )
    assert source == "GPE-010-A"
