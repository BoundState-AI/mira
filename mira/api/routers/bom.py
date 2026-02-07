#!/usr/bin/env python3
"""
Module: Bom
Purpose: BOM API endpoints for BoundState.

BoundState AI 2025
Version: 1.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Fran OpenAI 5 <noreply@openai.com>
Co-Authored-By: Grok 4.0 <noreply@x.ai>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: NASA-CSET, SWE-013, SWE-032
Safety Critical: True
"""

from __future__ import annotations

import logging
import tempfile
from io import BytesIO
from pathlib import Path

import pandas as pd
from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
import uuid

LOGGER = logging.getLogger(__name__)

router = APIRouter()


@router.get("/ping")
async def ping() -> dict:
    """Health check for BOM endpoint."""
    return {"status": "ok", "domain": "bom"}


@router.post("/convert-to-miul")
async def convert_bom_to_miul(
    file: UploadFile = File(...),
) -> StreamingResponse:
    """Convert BOM file (Excel/CSV) to MIUL format.

    Reads a BOM file and converts it to MIUL Excel format with
    standard columns for enrichment.

    Args:
        file: Excel (.xlsx, .xls) or CSV (.csv) BOM file

    Returns:
        Excel file with MIUL structure
    """
    filename = file.filename.lower()
    if not filename.endswith((".xlsx", ".xls", ".csv", ".txt")):
        raise HTTPException(
            status_code=400,
            detail="File must be Excel (.xlsx, .xls) or CSV (.csv, .txt)",
        )

    LOGGER.info(f"[BOM] Converting BOM from {file.filename}")

    with tempfile.NamedTemporaryFile(suffix=Path(filename).suffix, delete=False) as tmp:
        content = await file.read()
        tmp.write(content)
        tmp_path = Path(tmp.name)

    try:
        # Read BOM file
        if filename.endswith((".xlsx", ".xls")):
            bom_df = pd.read_excel(tmp_path, engine="openpyxl")
        else:
            # Try different delimiters for text files
            try:
                bom_df = pd.read_csv(tmp_path)
            except Exception:
                bom_df = pd.read_csv(tmp_path, delimiter="\t")

        LOGGER.info(f"[BOM] Read {len(bom_df)} rows, columns: {list(bom_df.columns)}")

        # Convert to MIUL format
        miul_df = _convert_bom_dataframe_to_miul(bom_df)

        # Create Excel output
        output = BytesIO()
        with pd.ExcelWriter(output, engine="openpyxl") as writer:
            miul_df.to_excel(writer, sheet_name="MIUL", index=False)

        output.seek(0)

        LOGGER.info(f"[BOM] Generated MIUL with {len(miul_df)} rows")

        return StreamingResponse(
            iter([output.getvalue()]),
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": "attachment; filename=MIUL_from_BOM.xlsx"},
        )

    except Exception as e:
        LOGGER.error(f"[BOM] Conversion failed: {e}")
        raise HTTPException(status_code=500, detail=f"BOM conversion failed: {e}")

    finally:
        tmp_path.unlink(missing_ok=True)


def _convert_bom_dataframe_to_miul(bom_df: pd.DataFrame) -> pd.DataFrame:
    """Convert BOM DataFrame to MIUL format.

    Attempts to detect and map common BOM column names to MIUL columns.

    Args:
        bom_df: Input BOM DataFrame

    Returns:
        MIUL-formatted DataFrame
    """
    # Standard MIUL columns
    miul_columns = [
        "Line Item",
        "Part Number",
        "Nomenclature",
        "Material Code",
        "Designation",
        "Material Spec.",
        "Quantity",
        "Drawing",
        "Parent",
        "Usage Notes",
        "FLAMM Rating",
        "CORR Rating",
        "SCC Rating",
        "TVS Rating",
        "TOX Rating",
        "FS Rating",
    ]

    # Column mapping patterns (BOM column name -> MIUL column)
    column_mappings = {
        "Part Number": ["part number", "part_number", "part no", "pn", "part", "item"],
        "Quantity": ["quantity", "qty", "count", "amount"],
        "Nomenclature": ["nomenclature", "name", "description", "desc", "title"],
        "Material Code": ["material code", "material_code", "matl code", "mat code", "material"],
        "Designation": ["designation", "alloy", "spec", "specification"],
        "Material Spec.": ["material spec", "material_spec", "spec", "specification"],
        "Drawing": ["drawing", "dwg", "drawing no", "drawing number"],
        "Parent": ["parent", "parent assy", "assembly", "assy"],
    }

    # Normalize column names for matching
    bom_cols_lower = {col.lower().strip(): col for col in bom_df.columns}

    # Create MIUL DataFrame
    miul_df = pd.DataFrame(columns=miul_columns)

    # Map columns
    for miul_col, patterns in column_mappings.items():
        for pattern in patterns:
            if pattern in bom_cols_lower:
                original_col = bom_cols_lower[pattern]
                miul_df[miul_col] = bom_df[original_col]
                LOGGER.debug(f"Mapped '{original_col}' -> '{miul_col}'")
                break

    # Add line numbers
    if len(bom_df) > 0:
        miul_df["Line Item"] = range(1, len(bom_df) + 1)

    # Initialize empty columns
    for col in miul_columns:
        if col not in miul_df.columns:
            miul_df[col] = ""

    return miul_df[miul_columns]


__safety_critical__ = True  # NASA SWE-032 compliance
