"""Tests for matchmaker MIUL batch import grouping."""

from __future__ import annotations

from io import BytesIO

import pandas as pd
import pytest

from mira.mua.matchmaker import batch


def _workbook_bytes(frame: pd.DataFrame, sheet_name: str = "MIUL") -> bytes:
    buffer = BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        frame.to_excel(writer, sheet_name=sheet_name, index=False)
    return buffer.getvalue()


def test_parse_miul_upload_generic_filters_nan_and_bundles_material(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(batch, "_parse_with_trigger_buckets", lambda *_args, **_kwargs: [])

    frame = pd.DataFrame(
        [
            {
                "Material Code": 10392,
                "Material Designation": "A286",
                "Environment": "GH2",
                "Part Number": "PN-001",
                "Part Description": "Hydrogen bracket",
                "Max Pressure": 5000,
                "Min Temperature": -423,
                "Max Temperature": 120,
            },
            {
                "Material Code": 10392,
                "Material Designation": "A286",
                "Environment": "GH2",
                "Part Number": "PN-002",
                "Part Description": "Hydrogen clamp",
                "Max Pressure": 6000,
                "Min Temperature": -400,
                "Max Temperature": 110,
            },
            {
                "Material Code": None,
                "Material Designation": "nan",
                "Environment": "AIR",
                "Part Number": "PN-003",
                "Part Description": "SPRING",
            },
        ]
    )

    groups = batch.parse_miul_upload(_workbook_bytes(frame), "sample.xlsx")

    assert len(groups) == 1
    assert groups[0]["material_input"] == "A286"
    assert groups[0]["part_count"] == 2
    assert groups[0]["environment"]["pressure_psia"] == 6000.0
    assert "PN-001" in groups[0]["sample_part_numbers"]
    assert "PN-002" in groups[0]["sample_part_numbers"]


def test_parse_miul_upload_uses_trigger_bucket_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    analysis = {
        "part_triggers": [
            {
                "material_code": "10392",
                "designation": "A286",
                "part_number": "PN-001",
                "part_description": "Hydrogen bracket",
                "environment": "GH2",
                "triggers": [{"issue": "FS", "rating": "U"}],
            }
        ]
    }
    bucket_payload = {
        "material_signature_buckets": [
            {
                "bucket_id": "10392::FS:U::GH2",
                "material_code": "10392",
                "environment": "GH2",
                "part_count": 1,
                "designations": {"A286": 1},
                "temp_min_f": -423,
                "temp_max_f": 120,
                "pressure_max_psia": 5000,
            }
        ]
    }

    monkeypatch.setattr(
        "mira.miul.mua_trigger_analyzer.analyze_miul_bytes",
        lambda *_args, **_kwargs: analysis,
    )
    monkeypatch.setattr(
        "mira.miul.mua_trigger_analyzer.build_trigger_buckets",
        lambda *_args, **_kwargs: bucket_payload,
    )

    groups = batch.parse_miul_upload(b"unused-by-mock", "sample.xlsx")

    assert len(groups) == 1
    assert groups[0]["material_input"] == "A286"
    assert groups[0]["part_count"] == 1
    assert groups[0]["environment"]["medium"] == "HYDROGEN"
    assert groups[0]["sample_part_numbers"] == ["PN-001"]


def test_parse_miul_upload_generic_derives_trigger_signature_and_skips_header_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(batch, "_parse_with_trigger_buckets", lambda *_args, **_kwargs: [])

    frame = pd.DataFrame(
        [
            {
                "Part Number": "DMLLV",
                "Part Description": "DMLLV Material Identification Usage List",
                "Nomenclature": "DMLLV Material Identification Usage List",
                "Designation": None,
                "Environment": None,
                "FLAM": None,
                "SCC": None,
                "FS": None,
            },
            {
                "Part Number": "PN-001",
                "Part Description": "Hydrogen bracket",
                "Nomenclature": "Hydrogen bracket",
                "Designation": "A286",
                "Environment": "GH2",
                "FLAM": "U",
                "SCC": "U",
                "FS": "A",
                "Max Pressure": 5000,
                "Min Temperature": -423,
            },
            {
                "Part Number": "PN-002",
                "Part Description": "Hydrogen clamp",
                "Nomenclature": "Hydrogen clamp",
                "Designation": "A286",
                "Environment": "GH2",
                "FLAM": "U",
                "SCC": "U",
                "FS": "A",
                "Max Pressure": 4800,
                "Min Temperature": -400,
            },
            {
                "Part Number": "MER07540-001",
                "Part Description": "MER07540-001",
                "Nomenclature": "MER07540-001",
                "Designation": None,
                "Environment": "GH2",
                "FLAM": "U",
                "SCC": "U",
                "FS": "U",
            },
        ]
    )

    groups = batch.parse_miul_upload(_workbook_bytes(frame), "sample.xlsx")

    assert len(groups) == 1
    assert groups[0]["material_input"] == "A286"
    assert groups[0]["part_count"] == 2
    assert groups[0]["trigger_signature"] == "FLAM:U|SCC:U"
