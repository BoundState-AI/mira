#!/usr/bin/env python3
"""Unit tests for MUA v10 router MAPTIS designation fallback."""

from __future__ import annotations

import asyncio
import importlib.util
import io
import os
import sys
import types
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi import HTTPException
from starlette.datastructures import UploadFile

PROJECT_ROOT = Path(__file__).resolve().parents[2]
ROUTER_PATH = PROJECT_ROOT / "mira" / "api" / "routers" / "mua_v10.py"

sys.path.insert(0, str(PROJECT_ROOT))

spec = importlib.util.spec_from_file_location("boundstate_mua_v10_router", ROUTER_PATH)
assert spec and spec.loader
mua_v10_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mua_v10_module)

PipelineResult = mua_v10_module.PipelineResult


def _request(**overrides):
    payload = {
        "maptis_code": None,
        "material_designation": "",
        "material_class": None,
        "media": "GH2",
        "environment": "non-habitable",
        "o2_percent": None,
        "batch_verified": False,
        "ratings": {"FS": "U"},
        "part_numbers": [],
        "part_count": 1,
        "project": "",
        "system": "",
        "material_specification": None,
        "pressure": "",
        "temperature": "",
    }
    payload.update(overrides)
    return SimpleNamespace(**payload)


def _stub_pipeline_result(maptis_code: str = "10392") -> PipelineResult:
    return PipelineResult(
        maptis_code=maptis_code,
        material_designation="A286 CRES",
        total_flags=1,
    )


@patch.object(mua_v10_module, "process_miul_row")
def test_classify_row_accepts_explicit_maptis_code(mock_process):
    mock_process.return_value = _stub_pipeline_result("10392")

    request = _request(
        maptis_code="10392",
        material_designation="A286 CRES",
        material_class="metal",
        media="GH2",
        ratings={"FS": "U"},
    )

    result = asyncio.run(mua_v10_module.classify_row(request))

    assert result.maptis_code == "10392"
    assert mock_process.call_args.kwargs["maptis_code"] == "10392"


@patch.object(mua_v10_module, "process_miul_row")
def test_classify_row_ignores_null_or_blank_ratings(mock_process):
    mock_process.return_value = _stub_pipeline_result("10392")

    request = _request(
        maptis_code="10392",
        material_designation="A286 CRES",
        material_class="metal",
        media="LH2",
        ratings={
            "FLAM": None,
            "FS": "C",
            "TOX": "",
            "TVS": "   ",
            "SCC": None,
            "CORR": None,
        },
    )

    result = asyncio.run(mua_v10_module.classify_row(request))

    assert result.maptis_code == "10392"
    assert mock_process.call_args.kwargs["ratings"] == {"FS": "C"}


@patch.object(mua_v10_module, "process_miul_row")
@patch.object(mua_v10_module, "_resolve_maptis_code_or_raise")
def test_classify_row_uses_resolved_maptis_code_when_blank(mock_resolve, mock_process):
    mock_resolve.return_value = "55962"
    mock_process.return_value = _stub_pipeline_result("55962")

    request = _request(
        material_designation="INCONEL 718",
        material_class="metal",
        media="GH2",
        ratings={"FLAM": "I"},
    )

    result = asyncio.run(mua_v10_module.classify_row(request))

    assert result.maptis_code == "55962"
    assert mock_resolve.call_count == 1
    assert mock_process.call_args.kwargs["maptis_code"] == "55962"


def test_resolve_maptis_requires_code_or_designation():
    with pytest.raises(HTTPException) as exc_info:
        mua_v10_module._resolve_maptis_code_or_raise(None, "")

    assert exc_info.value.status_code == 400
    assert "Provide maptis_code or material_designation" in str(exc_info.value.detail)


def test_resolve_maptis_from_designation_uses_first_candidate():
    fake_lookup_module = types.ModuleType("mira.miul.material_code_lookup")
    fake_lookup_module.get_lookup_service = lambda: SimpleNamespace(
        lookup_by_designation=lambda _: [
            SimpleNamespace(material_code="55962"),
            SimpleNamespace(material_code="10392"),
        ]
    )

    with patch.dict(sys.modules, {"mira.miul.material_code_lookup": fake_lookup_module}):
        resolved = mua_v10_module._resolve_maptis_code_or_raise(None, "INCONEL 718")
    assert resolved == "55962"


def test_resolve_maptis_uses_offline_fallback_when_lookup_raises():
    fake_lookup_module = types.ModuleType("mira.miul.material_code_lookup")

    class _Service:
        @staticmethod
        def lookup_by_designation(_: str):
            raise RuntimeError("database unavailable")

    fake_lookup_module.get_lookup_service = lambda: _Service()

    env = dict(os.environ)
    env["MUA_V10_ALLOW_OFFLINE_LOOKUP"] = "1"
    with patch.dict(sys.modules, {"mira.miul.material_code_lookup": fake_lookup_module}):
        with patch.dict(os.environ, env, clear=False):
            resolved = mua_v10_module._resolve_maptis_code_or_raise(None, "A286 CRES")
    assert resolved == "10392"


@patch.object(mua_v10_module, "process_miul_row")
def test_process_miul_workbook_uses_non_a_ratings(mock_process):
    pd = pytest.importorskip("pandas")

    df = pd.DataFrame(
        [
            {
                "Line Number": 1,
                "Part Number": "MER07581-001",
                "Material Code": "10392",
                "Designation": "A286 CRES",
                "Fluid Type": "GH2",
                "Environment": "non-habitable",
                "FLAM": "A",
                "FS": "U",
                "SCC": "A",
            },
            {
                "Line Number": 2,
                "Part Number": "MER07581-002",
                "Material Code": "10392",
                "Designation": "A286 CRES",
                "Fluid Type": "GH2",
                "Environment": "non-habitable",
                "FLAM": "A",
                "FS": "A",
                "SCC": "A",
            },
        ]
    )

    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        df.to_excel(writer, sheet_name="MIUL", index=False)
    buffer.seek(0)

    mock_process.return_value = _stub_pipeline_result("10392")
    upload = UploadFile(filename="completed_miul.xlsx", file=io.BytesIO(buffer.getvalue()))

    response = asyncio.run(
        mua_v10_module.process_miul_workbook(
            file=upload,
            media_override=None,
            environment_override=None,
            project="DMLLV",
            system="Valve",
            max_rows=200,
        )
    )

    assert response.processed_rows == 1
    assert response.skipped_rows == 1
    assert response.results[0].ratings == {"FS": "U"}
    assert response.results[0].maptis_code == "10392"
    assert mock_process.call_count == 1
