#!/usr/bin/env python3
"""
Module: Miul
Purpose: MIUL API Router for BoundState.

BoundState AI 2025
Version: 1.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Fran OpenAI 5 <noreply@openai.com>
Co-Authored-By: Grok 4.0 <noreply@x.ai>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: SWE-032 (Data validation), SWE-033 (Requirements Traceability)
Safety Critical: True
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shutil
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
from fastapi import APIRouter, Body, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import Response, StreamingResponse

from mira.api.auth import authorize_owner_or_admin, get_request_user

# Lazy imports for enrichment workflow - only loaded when /enrich or /gaps called
MIULWorkflow = None
get_miul_workflow = None

LOGGER = logging.getLogger(__name__)

router = APIRouter()

XLSX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
XLSM_MEDIA_TYPE = "application/vnd.ms-excel.sheet.macroEnabled.12"
DT_EDITOR_MAX_ITERATIONS = max(1, int(os.getenv("DT_EDITOR_MAX_ITERATIONS", "1")))


def _get_workflow():
    """Dependency injection for enrichment workflow (lazy load)."""
    global MIULWorkflow, get_miul_workflow
    if get_miul_workflow is None:
        from mira.miul.workflow import MIULWorkflow as _MIULWorkflow, get_miul_workflow as _get_miul_workflow
        MIULWorkflow = _MIULWorkflow
        get_miul_workflow = _get_miul_workflow
    return get_miul_workflow()


@router.get("/ping")
async def ping() -> dict:
    """Health check for MIUL endpoint."""
    return {"status": "ok", "domain": "miul"}


@router.post("/extract-dt")
async def extract_drawing_tree_endpoint(
    dt_file: UploadFile = File(...),
    max_iterations: int = Form(1),
) -> dict:
    """Extract Drawing Tree hierarchy from PDF.

    Takes a Drawing Tree PDF and returns the extracted hierarchy JSON.
    Uses v3 vision extraction with validation loop.

    This endpoint is designed for the DT Editor UI - upload PDF,
    get JSON back for visual verification and correction.

    Args:
        dt_file: Drawing Tree PDF file
        max_iterations: Max validation/correction iterations (interactive route clamps to 1)

    Returns:
        JSON with 'top_level' and 'tree' (flat format with parent pointers)
    """
    from mira.miul.v3.extract import extract_drawing_tree, VisionClient

    if not dt_file.filename or not dt_file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="File must be a PDF")

    LOGGER.info(f"[DT Extract] Starting extraction: {dt_file.filename}")

    temp_dir = Path(tempfile.mkdtemp())

    try:
        # Save uploaded PDF
        content = await dt_file.read()
        pdf_path = temp_dir / dt_file.filename
        pdf_path.write_bytes(content)

        effective_iterations = max(1, min(max_iterations, DT_EDITOR_MAX_ITERATIONS))
        if effective_iterations != max_iterations:
            LOGGER.info(
                "[DT Extract] Clamping requested iterations from %s to %s for interactive editor responsiveness",
                max_iterations,
                effective_iterations,
            )

        # Run v3 DT extraction
        client = VisionClient()
        result = extract_drawing_tree(pdf_path, client, max_iterations=effective_iterations)

        if not result or not result.get("tree"):
            raise HTTPException(
                status_code=422,
                detail="Failed to extract hierarchy from PDF. Check that this is a Drawing Tree document."
            )

        LOGGER.info(
            f"[DT Extract] Success: {len(result.get('tree', []))} entries, "
            f"top_level={result.get('top_level', 'N/A')}"
        )

        return result

    except HTTPException:
        raise
    except Exception as e:
        LOGGER.error(f"[DT Extract] Error: {e}")
        raise HTTPException(status_code=500, detail=f"Extraction failed: {e}")

    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def _require_pdf_upload(upload: UploadFile, *, field_name: str) -> None:
    """Reject blank or non-PDF uploads on legacy MIUL aliases."""
    if not upload.filename or not upload.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail=f"{field_name} must be a PDF")


def _require_pdf_uploads(uploads: List[UploadFile], *, field_name: str) -> None:
    """Reject non-PDF uploads and require at least one file."""
    if not uploads:
        raise HTTPException(status_code=400, detail=f"{field_name} requires at least one PDF")
    for upload in uploads:
        _require_pdf_upload(upload, field_name=field_name)


@router.post("/fast-extract")
async def fast_extract_miul(
    drawings: List[UploadFile] = File(...),
    project: str = Form(""),
    min_pressure: str = Form("0"),
    max_pressure: str = Form("14.7"),
    min_temperature: str = Form("0"),
    max_temperature: str = Form("120"),
    o2_concentration: str = Form("20.9"),
    service_media: str = Form("Air"),
) -> StreamingResponse:
    """Legacy alias for the fast multi-PDF MIUL extraction path."""
    _require_pdf_uploads(drawings, field_name="drawings")
    return await extract_miul_v3(
        drawings=drawings,
        drawing_tree=None,
        nha_overrides=None,
        project=project,
        min_pressure=min_pressure,
        max_pressure=max_pressure,
        min_temperature=min_temperature,
        max_temperature=max_temperature,
        o2_concentration=o2_concentration,
        service_media=service_media,
        use_2phase=True,
    )


@router.post("/msfc-extract")
async def msfc_extract_miul(
    drawings: List[UploadFile] = File(None),
    drawing_tree: UploadFile = File(None),
    project: str = Form(""),
    min_pressure: str = Form("0"),
    max_pressure: str = Form("14.7"),
    min_temperature: str = Form("0"),
    max_temperature: str = Form("120"),
    o2_concentration: str = Form("20.9"),
    service_media: str = Form("Air"),
) -> StreamingResponse:
    """Legacy alias for MSFC-oriented MIUL extraction."""
    drawing_list = list(drawings or [])
    if drawing_tree is None and not drawing_list:
        raise HTTPException(status_code=400, detail="Provide drawings or a drawing tree PDF")
    if drawing_tree is not None:
        _require_pdf_upload(drawing_tree, field_name="drawing_tree")
        if not drawing_list:
            drawing_list = [drawing_tree]
            drawing_tree = None
    if drawing_list:
        _require_pdf_uploads(drawing_list, field_name="drawings")
    return await extract_miul_v3(
        drawings=drawing_list,
        drawing_tree=drawing_tree,
        nha_overrides=None,
        project=project,
        min_pressure=min_pressure,
        max_pressure=max_pressure,
        min_temperature=min_temperature,
        max_temperature=max_temperature,
        o2_concentration=o2_concentration,
        service_media=service_media,
        use_2phase=True,
    )


@router.post("/dmllv-extract")
async def dmllv_extract_miul(
    drawings: List[UploadFile] = File(...),
    project: str = Form(""),
    min_pressure: str = Form("0"),
    max_pressure: str = Form("14.7"),
    min_temperature: str = Form("0"),
    max_temperature: str = Form("120"),
    o2_concentration: str = Form("20.9"),
    service_media: str = Form("Air"),
) -> StreamingResponse:
    """Legacy alias for DMLLV extraction callers."""
    _require_pdf_uploads(drawings, field_name="drawings")
    return await extract_miul_v3(
        drawings=drawings,
        drawing_tree=None,
        nha_overrides=None,
        project=project,
        min_pressure=min_pressure,
        max_pressure=max_pressure,
        min_temperature=min_temperature,
        max_temperature=max_temperature,
        o2_concentration=o2_concentration,
        service_media=service_media,
        use_2phase=True,
    )


@router.post("/enrich")
async def enrich_miul(
    file: UploadFile = File(...),
    workflow: Optional["MIULWorkflow"] = None,
) -> StreamingResponse:
    """Enrich MIUL Excel with MAPTIS ratings.

    Takes a base MIUL Excel and populates rating columns from MAPTIS.
    CRITICAL: Preserves exact file format - modifies cells in-place without
    changing column order, widths, styles, filters, or any other formatting.

    Args:
        file: Excel file with MIUL sheet containing Material Code column
        workflow: Optional workflow instance for tests or internal reuse.

    Returns:
        Enriched Excel file with rating columns populated (identical format to input)
    """
    from io import BytesIO

    input_name = file.filename or "MIUL.xlsx"
    input_suffix = Path(input_name).suffix.lower()
    if input_suffix not in (".xlsx", ".xlsm"):
        raise HTTPException(status_code=400, detail="File must be .xlsx or .xlsm format")
    if workflow is None:
        workflow = _get_workflow()

    LOGGER.info(f"[MIUL] Enriching MIUL from {input_name}")

    tmp_path = None
    try:
        from openpyxl import load_workbook

        # Save uploaded file
        tmp_suffix = ".xlsm" if input_suffix == ".xlsm" else ".xlsx"
        with tempfile.NamedTemporaryFile(suffix=tmp_suffix, delete=False) as tmp:
            content = await file.read()
            tmp.write(content)
            tmp_path = Path(tmp.name)

        # Always strip VBA projects/macros from returned enrichment files.
        wb = load_workbook(tmp_path, keep_vba=False)
        sheet_name = "MIUL" if "MIUL" in wb.sheetnames else ("Sheet1" if "Sheet1" in wb.sheetnames else wb.sheetnames[0])
        ws = wb[sheet_name]

        # Read worksheet into DataFrame for enrichment logic.
        source_df = pd.read_excel(tmp_path, sheet_name=sheet_name, engine="openpyxl")
        original_columns = list(source_df.columns)

        miul_required = {"Designation", "Material Code", "FLAM", "SCC", "CORR", "TVS", "TOX", "FS"}
        opiv_required = {"Designation", "Material Code", "FLAMM Rating", "SCC Rating", "CORR Rating", "TVS Rating", "TOX Rating", "FS Rating"}

        schema = None
        if miul_required.issubset(set(original_columns)):
            schema = "miul"
            working_df = source_df.copy()
        elif opiv_required.issubset(set(original_columns)):
            schema = "opiv"
            working_df = pd.DataFrame(index=source_df.index)
            working_df["Designation"] = source_df["Designation"]
            working_df["Material Code"] = source_df["Material Code"]
            working_df["FLAM"] = source_df["FLAMM Rating"]
            working_df["SCC"] = source_df["SCC Rating"]
            working_df["CORR"] = source_df["CORR Rating"]
            working_df["TVS"] = source_df["TVS Rating"]
            working_df["TOX"] = source_df["TOX Rating"]
            working_df["FS"] = source_df["FS Rating"]
            if "Material Spec." in source_df.columns:
                working_df["Material Specification"] = source_df["Material Spec."]
            if "Process Spec." in source_df.columns:
                working_df["Process Specification"] = source_df["Process Spec."]
        else:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"Sheet '{sheet_name}' does not match supported MIUL formats. "
                    "Expected either standard MIUL columns (FLAM/SCC/CORR/TVS/TOX/FS) "
                    "or OPIV template columns (FLAMM Rating/SCC Rating/CORR Rating/TVS Rating/TOX Rating/FS Rating)."
                ),
            )

        # Build column name -> index mapping (1-based for openpyxl)
        col_name_to_idx = {col: i + 1 for i, col in enumerate(original_columns)}

        # Run enrichment on normalized working dataframe.
        working_df, codes_found, quarantine = workflow.lookup_material_codes(working_df)
        working_df, stats = workflow.fetch_ratings(working_df)

        LOGGER.info(
            f"[MIUL] Enrichment: {stats.get('enriched_count', 0)}/{stats.get('total_materials', 0)} "
            f"({stats.get('coverage_pct', 0):.1f}%), {len(quarantine)} quarantined"
        )

        # Write updates back into original worksheet to preserve formatting.
        if schema == "opiv":
            update_map = {
                "Material Code": "Material Code",
                "FLAM": "FLAMM Rating",
                "SCC": "SCC Rating",
                "CORR": "CORR Rating",
                "TVS": "TVS Rating",
                "TOX": "TOX Rating",
                "FS": "FS Rating",
            }
        else:
            update_map = {
                "Material Code": "Material Code",
                "FLAM": "FLAM",
                "SCC": "SCC",
                "CORR": "CORR",
                "TVS": "TVS",
                "TOX": "TOX",
                "FS": "FS",
            }

        filled_counts: Dict[str, int] = {}

        for source_col, target_col in update_map.items():
            if target_col not in col_name_to_idx or source_col not in working_df.columns:
                continue
            col_idx = col_name_to_idx[target_col]
            filled_count = 0

            for row_idx, value in enumerate(working_df[source_col], start=2):  # Row 2+ (1 is header)
                output_value = None
                if source_col == "Material Code":
                    if workflow.is_usable_material_code(value):
                        output_value = workflow._normalize_material_code(value)
                else:
                    if pd.notna(value):
                        text = str(value).strip()
                        if text:
                            output_value = text

                ws.cell(row=row_idx, column=col_idx, value=output_value)
                if output_value is not None:
                    filled_count += 1
            filled_counts[target_col] = filled_count

        if codes_found == 0 and int(stats.get("enriched_count", 0) or 0) == 0:
            LOGGER.warning(
                "[MIUL] Enrichment produced no new material codes or MAPTIS rows. "
                "Check Designation values and material code mappings."
            )

        # Save modified workbook to BytesIO
        output = BytesIO()
        wb.save(output)
        output.seek(0)

        out_name = f"{Path(input_name).stem}_enriched.xlsx"
        headers = {
            "Content-Disposition": f"attachment; filename={out_name}",
            "X-Codes-Found": str(codes_found),
            "X-Quarantine-Count": str(len(quarantine)),
            "X-Materials-With-Codes": str(filled_counts.get("Material Code", 0)),
            "X-Ratings-Enriched": str(int(stats.get("enriched_count", 0) or 0)),
            "X-Ratings-Added": str(int(stats.get("total_ratings_added", 0) or 0)),
            "X-Rating-Coverage-Pct": f"{float(stats.get('coverage_pct', 0.0) or 0.0):.1f}",
        }

        return StreamingResponse(
            iter([output.getvalue()]),
            media_type=XLSX_MEDIA_TYPE,
            headers=headers,
        )

    except HTTPException:
        raise
    except Exception as e:
        LOGGER.error(f"[MIUL] Enrichment failed: {e}")
        raise HTTPException(status_code=500, detail=f"Enrichment failed: {e}")

    finally:
        if tmp_path:
            tmp_path.unlink(missing_ok=True)


@router.get("/gaps")
async def get_rating_gaps(
    file: UploadFile = File(...),
    workflow: Optional["MIULWorkflow"] = None,
) -> dict:
    """Get parts with rating gaps that need rationale selection.

    Args:
        file: Excel file with enriched MIUL
        workflow: Optional workflow instance for tests or internal reuse.

    Returns:
        List of parts needing rationale
    """
    input_name = file.filename or "MIUL.xlsx"
    input_suffix = Path(input_name).suffix.lower()
    if input_suffix not in (".xlsx", ".xlsm"):
        raise HTTPException(status_code=400, detail="File must be .xlsx or .xlsm format")
    if workflow is None:
        workflow = _get_workflow()

    tmp_path = None
    try:
        from openpyxl import load_workbook

        tmp_suffix = ".xlsm" if input_suffix == ".xlsm" else ".xlsx"
        with tempfile.NamedTemporaryFile(suffix=tmp_suffix, delete=False) as tmp:
            content = await file.read()
            tmp.write(content)
            tmp_path = Path(tmp.name)

        wb = load_workbook(tmp_path, keep_vba=(input_suffix == ".xlsm"))
        sheet_name = "MIUL" if "MIUL" in wb.sheetnames else ("Sheet1" if "Sheet1" in wb.sheetnames else wb.sheetnames[0])

        source_df = pd.read_excel(tmp_path, sheet_name=sheet_name, engine="openpyxl")
        cols = set(source_df.columns)
        if {"FLAMM Rating", "SCC Rating", "CORR Rating", "TVS Rating", "TOX Rating", "FS Rating"}.issubset(cols):
            miul_df = pd.DataFrame(index=source_df.index)
            miul_df["FLAM"] = source_df["FLAMM Rating"]
            miul_df["SCC"] = source_df["SCC Rating"]
            miul_df["CORR"] = source_df["CORR Rating"]
            miul_df["TVS"] = source_df["TVS Rating"]
            miul_df["TOX"] = source_df["TOX Rating"]
            miul_df["FS"] = source_df["FS Rating"]
            miul_df["Line Number"] = source_df["Index"] if "Index" in source_df.columns else source_df.index + 1
            miul_df["Detail Drawing"] = source_df["Dwg Source"] if "Dwg Source" in source_df.columns else ""
            miul_df["Designation"] = source_df["Designation"] if "Designation" in source_df.columns else ""
            miul_df["Material Code"] = source_df["Material Code"] if "Material Code" in source_df.columns else ""
        else:
            miul_df = source_df

        # Ignore blank template rows to avoid false gap reports.
        if "Part Number" in source_df.columns:
            part_mask = source_df["Part Number"].fillna("").astype(str).str.strip() != ""
            miul_df = miul_df[part_mask]

        gaps = workflow.identify_rating_gaps(miul_df)

        return {
            "total_parts": len(miul_df),
            "parts_with_gaps": len(gaps),
            "parts": gaps,
        }

    finally:
        if tmp_path:
            tmp_path.unlink(missing_ok=True)


@router.post("/extract")
@router.post("/v1-extract")  # Alias for explicit v1 request
async def extract_miul(
    drawings: List[UploadFile] = File(...),
    drawing_tree: UploadFile = File(None),
    root_drawing: str = Form(None),
    project: str = Form(""),
    min_pressure: str = Form("0"),
    max_pressure: str = Form("14.7"),
    min_temperature: str = Form("0"),
    max_temperature: str = Form("120"),
    o2_concentration: str = Form("20.9"),
    service_media: str = Form("Air"),
    skip_vision: bool = Form(False),
) -> StreamingResponse:
    """MIUL v1 Extraction - Drawing Tree as Single Source of Truth.

    DT-first pipeline where the Drawing Tree PDF defines the complete hierarchy.
    Detail drawings provide materials only (no hierarchy inference).

    Pipeline Steps:
    1. Parse -DT PDF with AI Vision -> hierarchy + all assemblies
    2. Parse detail drawings -> materials only
    3. Merge: DT skeleton + materials -> complete MIUL
    4. Export to MAPTIS-compliant Excel

    Args:
        drawings: PDF files containing engineering drawings
        drawing_tree: Drawing Tree PDF (REQUIRED for hierarchy)
        root_drawing: Optional explicit root drawing number (unused in v1)
        project: Project name / MIUL identifier
        min_pressure: Minimum operating pressure (psia) - stored in metadata
        max_pressure: Maximum operating pressure (psia) - stored in metadata
        min_temperature: Minimum operating temperature (degF) - stored in metadata
        max_temperature: Maximum operating temperature (degF) - stored in metadata
        o2_concentration: Oxygen concentration (%) - stored in metadata
        service_media: Service media/fluid type - stored in metadata
        skip_vision: If True, skip vision API (not supported in v1)

    Returns:
        Excel file with MIUL data.
    """
    from io import BytesIO
    from mira.miul.v1_archive.dt_miul_builder import DTMIULBuilder

    if not drawings:
        raise HTTPException(status_code=400, detail="No PDF files provided")

    # V1 requires Drawing Tree
    if not drawing_tree or not drawing_tree.filename:
        raise HTTPException(
            status_code=400,
            detail="Drawing Tree PDF is required. Upload it in the 'Drawing Tree' field."
        )

    LOGGER.info(f"[MIUL-V1] Starting DT-first pipeline: {len(drawings)} PDF(s), DT={drawing_tree.filename}")

    temp_dir = Path(tempfile.mkdtemp())

    try:
        # Save Drawing Tree
        dt_content = await drawing_tree.read()
        dt_path = temp_dir / drawing_tree.filename
        dt_path.write_bytes(dt_content)
        LOGGER.info(f"[MIUL-V1] Drawing Tree saved: {drawing_tree.filename}")

        # Save uploaded detail drawings
        for drawing in drawings:
            if not drawing.filename or not drawing.filename.lower().endswith(".pdf"):
                continue
            content = await drawing.read()
            file_path = temp_dir / drawing.filename
            file_path.write_bytes(content)

        # Count actual PDFs (excluding DT)
        pdf_count = len([p for p in temp_dir.glob("*.pdf") if p != dt_path])
        LOGGER.info(f"[MIUL-V1] Saved {pdf_count} detail drawing PDFs")

        # Derive project name if not provided
        if not project:
            # Try to extract from DT filename (e.g., "MER07540-DT.DRW_-.6.pdf" -> "MER07540")
            dt_stem = dt_path.stem
            if "-DT" in dt_stem.upper():
                project = dt_stem.split("-DT")[0].split("-")[0]
            else:
                first_pdf = next((p for p in temp_dir.glob("*.pdf") if p != dt_path), None)
                if first_pdf:
                    project = first_pdf.stem.split("(")[0].strip().replace(" ", "-")
            if not project:
                project = "MIUL"

        LOGGER.info(f"[MIUL-V1] Running V1 pipeline: project={project}")

        # Run V1 DT-first pipeline
        builder = DTMIULBuilder(miul_number=project, project=project)
        output_excel = builder.build(
            dt_pdf_path=dt_path,
            drawing_dir=temp_dir,
            output_path=temp_dir / f"MIUL_{project}.xlsx",
            extract_epl=True,
            strict_validation=False,
        )

        LOGGER.info(f"[MIUL-V1] Pipeline complete: {output_excel}")

        # Read Excel output
        output = BytesIO()
        with open(output_excel, "rb") as f:
            output.write(f.read())
        output.seek(0)

        # Build response headers
        response_headers = {
            "Content-Disposition": f"attachment; filename=MIUL_{project}.xlsx",
            "X-Pipeline-Version": "v1",
            "X-Project": project,
        }

        return StreamingResponse(
            iter([output.getvalue()]),
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers=response_headers,
        )

    except HTTPException:
        raise
    except Exception as e:
        LOGGER.error(f"[MIUL-V1] Extraction failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"MIUL v1 extraction failed: {e}")

    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


@router.post("/v3-extract")
async def extract_miul_v3(
    drawings: List[UploadFile] = File(...),
    drawing_tree: UploadFile = File(None),
    nha_overrides: UploadFile = File(None),
    project: str = Form(""),
    min_pressure: str = Form("0"),
    max_pressure: str = Form("14.7"),
    min_temperature: str = Form("0"),
    max_temperature: str = Form("120"),
    o2_concentration: str = Form("20.9"),
    service_media: str = Form("Air"),
    use_2phase: bool = Form(True),
) -> StreamingResponse:
    """MIUL v3 Extraction - 2-Phase Pipeline with Enhanced Material Search.

    2-Phase Pipeline Architecture:
    - Phase 1: DT PDF -> DT JSON (hierarchy only, source of truth)
    - Phase 2: Drawing PDFs -> Parts JSON (materials/specs)
    - Phase 3: Merge DT JSON + Parts JSON -> MIUL Excel

    V3 enhancements:
    - Multi-location material extraction (title block, notes, flags, EPL)
    - OCR error correction
    - Material Specification validation
    - Part number OCR correction
    - Designation cleanup (vendor pollution removal)
    - Material Form inference from specs
    - Generic project prefix detection (MER, GPE, ABC, etc.)

    NHA Assignment Priority:
    1. Manual NHA overrides (from JSON file) - highest authority
    2. Drawing Tree (DT) extraction - authoritative for project parts
    3. EPL inference - only for standard hardware (MS, NAS, AN)

    Args:
        drawings: PDF files containing engineering drawings (including DT if not separate)
        drawing_tree: Optional separate Drawing Tree PDF (if not in drawings list)
        nha_overrides: Optional JSON file with manual NHA overrides
            Format: {"child_pn": "parent_pn", ...}
        project: Project name / MIUL identifier
        min_pressure: Minimum operating pressure (psia)
        max_pressure: Maximum operating pressure (psia)
        min_temperature: Minimum operating temperature (deg F)
        max_temperature: Maximum operating temperature (deg F)
        o2_concentration: Oxygen concentration (%)
        service_media: Service media/fluid type
        use_2phase: If True, use new 2-phase pipeline (default). If False, use legacy single-pass.

    Returns:
        Excel file with MIUL data (MAPTIS-compliant formatting).
    """
    from io import BytesIO
    from mira.miul.v3.builder import (
        MIULBuilderV3,
        build_miul_2phase,
        EnvironmentConfig,
        _export_miul_excel,
    )

    # Build environment config from form parameters
    env_config = EnvironmentConfig(
        max_temp=float(max_temperature),
        min_temp=float(min_temperature),
        max_pressure=float(max_pressure),
        min_pressure=float(min_pressure),
        fluid_type=service_media,
        environment=f"{service_media}, VAC" if service_media != "Air" else "Air, VAC",
        o2_percent=float(o2_concentration),
    )
    LOGGER.info(
        f"[MIUL-V3] Environment: {env_config.fluid_type}, "
        f"{env_config.min_temp}degF-{env_config.max_temp}degF, "
        f"{env_config.min_pressure}-{env_config.max_pressure} psia"
    )

    if not drawings:
        raise HTTPException(status_code=400, detail="No PDF files provided")

    LOGGER.info(f"[MIUL-V3] Starting v3 pipeline: {len(drawings)} PDF(s), 2phase={use_2phase}")

    temp_dir = Path(tempfile.mkdtemp())

    try:
        # Save uploaded drawings
        for drawing in drawings:
            if not drawing.filename or not drawing.filename.lower().endswith(".pdf"):
                continue
            content = await drawing.read()
            file_path = temp_dir / drawing.filename
            file_path.write_bytes(content)

        # Save separate Drawing Tree if provided (PDF or pre-extracted JSON)
        dt_json_preloaded = None
        if drawing_tree and drawing_tree.filename:
            dt_content = await drawing_tree.read()
            dt_filename_lower = drawing_tree.filename.lower()

            if dt_filename_lower.endswith(".json"):
                # Pre-extracted DT JSON from DT Editor - use directly
                dt_json_preloaded = temp_dir / "dt_tree.json"
                dt_json_preloaded.write_bytes(dt_content)
                LOGGER.info(f"[MIUL-V3] Pre-extracted DT JSON loaded: {drawing_tree.filename}")
            else:
                # PDF file - save for extraction
                dt_path = temp_dir / drawing_tree.filename
                dt_path.write_bytes(dt_content)
                LOGGER.info(f"[MIUL-V3] Drawing Tree PDF saved: {drawing_tree.filename}")

        pdf_count = len(list(temp_dir.glob("*.pdf")))
        LOGGER.info(f"[MIUL-V3] Saved {pdf_count} drawing PDFs")

        # Save NHA overrides if provided
        nha_override_path = None
        if nha_overrides and nha_overrides.filename:
            nha_content = await nha_overrides.read()
            nha_override_path = temp_dir / "nha_overrides.json"
            nha_override_path.write_bytes(nha_content)
            LOGGER.info(f"[MIUL-V3] NHA overrides saved: {nha_overrides.filename}")

        # Derive project name if not provided
        if not project:
            first_pdf = next(temp_dir.glob("*.pdf"), None)
            if first_pdf:
                # e.g., "MER07540-001.DRW_-.11_RELEASED.pdf" -> "MER07540"
                stem = first_pdf.stem
                project = stem.split("-")[0].split(".")[0].strip()
            if not project:
                project = "MIUL"

        LOGGER.info(f"[MIUL-V3] Running V3 pipeline: project={project}, 2phase={use_2phase}")

        # Define output paths for intermediate JSONs (useful for debugging)
        # If we pre-loaded DT JSON, use that path; otherwise use default
        dt_json_path = dt_json_preloaded if dt_json_preloaded else (temp_dir / "dt_tree.json")
        parts_json_path = temp_dir / "parts.json"
        output_excel = temp_dir / f"MIUL_{project}_v3.xlsx"

        if use_2phase:
            # NEW: 2-Phase Pipeline
            LOGGER.info("[MIUL-V3] Using 2-phase pipeline (DT JSON + Parts JSON -> MIUL)")
            if dt_json_preloaded:
                LOGGER.info("[MIUL-V3] Using pre-extracted DT JSON (skipping vision extraction)")
            df, stats = build_miul_2phase(
                directory=temp_dir,
                output_excel=output_excel,
                dt_json_path=dt_json_path,
                parts_json_path=parts_json_path,
                environment=env_config,
                project_name=project,
            )
            dt_entries = stats.get("dt_entries", 0)
            parts_found = stats.get("parts_found", 0)
            drawings_extracted = stats.get("drawings_extracted", 0)
            materials_found = stats.get("materials_found", 0)
            issues = stats.get("issues", [])

            # Calculate confidence from DT
            dt_confidence = "HIGH" if dt_entries > 0 else "NONE"
            if issues:
                dt_confidence = "MEDIUM" if dt_entries > 10 else "LOW"

            response_headers = {
                "Content-Disposition": f"attachment; filename=MIUL_{project}_v3.xlsx",
                "X-Pipeline-Version": "v3-2phase",
                "X-Project": project,
                "X-MIUL-Count": str(len(df)),
                "X-DT-Entries": str(dt_entries),
                "X-DT-Confidence": dt_confidence,
                "X-Parts-Found": str(parts_found),
                "X-Drawing-Count": str(drawings_extracted),
                "X-Materials-Found": str(materials_found),
                "X-Manual-Override-Used": "true" if nha_override_path else "false",
            }

        else:
            # Legacy: Single-pass V3 pipeline
            LOGGER.info("[MIUL-V3] Using legacy single-pass pipeline")
            builder = MIULBuilderV3()
            builder.extract_directory(temp_dir, nha_override_path=nha_override_path)
            df = builder.build_miul()
            _export_miul_excel(
                df,
                output_excel,
                project,
                builder.dt_tree if isinstance(builder.dt_tree, dict) else {},
                {"parts": {}, "drawings": {}},
                environment=env_config,
            )

            # Export inventory JSON for debugging
            inventory_path = temp_dir / f"{project}_inventory_v3.json"
            builder.export_inventory(inventory_path)

            # Export auto-generated NHA overrides
            auto_overrides_path = temp_dir / f"{project}_nha_overrides_auto.json"
            builder.export_nha_overrides(auto_overrides_path, project=project)
            dt_confidence = builder._calculate_dt_confidence()

            materials_found = df["Designation"].notna().sum() if "Designation" in df.columns else 0
            auto_overrides = builder.generate_nha_overrides_from_dt()

            response_headers = {
                "Content-Disposition": f"attachment; filename=MIUL_{project}_v3.xlsx",
                "X-Pipeline-Version": "v3-legacy",
                "X-Project": project,
                "X-MIUL-Count": str(len(df)),
                "X-DT-Confidence": dt_confidence,
                "X-NHA-Override-Count": str(len(auto_overrides)),
                "X-Manual-Override-Used": "true" if nha_override_path else "false",
                "X-Drawing-Count": str(len(builder.drawings)),
                "X-Materials-Found": str(materials_found),
            }

        LOGGER.info(
            f"[MIUL-V3] Pipeline complete: {len(df)} rows, {output_excel}"
        )

        # Read Excel output
        with open(output_excel, "rb") as f:
            content = f.read()

        # Also save to persistent location for manual retrieval if download fails
        persistent_path = Path("C:/BoundState/temp") / f"MIUL_{project}_v3.xlsx"
        persistent_path.parent.mkdir(parents=True, exist_ok=True)
        with open(persistent_path, "wb") as f:
            f.write(content)
        LOGGER.info(f"[MIUL-V3] Also saved to: {persistent_path}")

        # Use Response (not StreamingResponse) to ensure Content-Length is set
        # This fixes proxy issues with binary file downloads
        return Response(
            content=content,
            media_type=XLSX_MEDIA_TYPE,
            headers=response_headers,
        )

    except HTTPException:
        raise
    except Exception as e:
        LOGGER.error(f"[MIUL-V3] Extraction failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"MIUL v3 extraction failed: {e}")

    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


# =============================================================================
# V4 Endpoints -- Sonnet Vision + HITL Review Pipeline
# =============================================================================

# Lazy imports for v4 modules
_V4Extractor = None
_V4Session = None


def _get_v4_extractor():
    """Lazy-load v4 vision extractor."""
    global _V4Extractor
    if _V4Extractor is None:
        from mira.miul.production.extractor import MIULVisionExtractor
        _V4Extractor = MIULVisionExtractor
    return _V4Extractor()


def _get_v4_session(extraction_id: str):
    """Lazy-load v4 session manager."""
    global _V4Session
    if _V4Session is None:
        from mira.miul.production.session import V4Session
        _V4Session = V4Session
    return _V4Session(extraction_id)


def _authorize_v4_session(http_request: Request, session) -> None:
    authorize_owner_or_admin(
        http_request,
        session.get_owner_username(),
        resource_label="miul extraction session",
    )


def _is_blank_value(value: Any) -> bool:
    """Return True for None/empty/nan-like values."""
    if value is None:
        return True
    text = str(value).strip()
    return text == "" or text.lower() == "nan"


def _env_flag(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def _normalize_v4_part_number(part_number: Any) -> str:
    """Normalize OCR part numbers for dedupe and matching."""
    pn = str(part_number or "").strip().upper()
    pn = re.sub(r"\s+", " ", pn)
    # Common OCR artifact: append Find number to PN ("EH-22-C86 6.")
    pn = re.sub(r"\s+\d+\.$", "", pn)
    return pn


def _extract_drawing_number_from_source(source_file: str) -> str:
    """Extract drawing number from source filename."""
    if not source_file:
        return ""
    stem = Path(source_file).stem
    for sep in (".DRW", "_DRW", "_drw", "_Drw"):
        if sep in stem:
            return stem.split(sep)[0].upper()
    return (stem.split("_")[0] if "_" in stem else stem).upper()


def _material_worst_confidence(material: Any) -> float:
    """Compute lowest confidence for a material sighting."""
    confidence = getattr(material, "confidence", None) or {}
    if not confidence:
        return 0.0
    try:
        return min(float(v or 0.0) for v in confidence.values())
    except (TypeError, ValueError):
        return 0.0


def _select_best_field_value(
    materials: List[Any],
    field_name: str,
) -> Tuple[str, float]:
    """Pick highest-confidence non-empty value for a field across sightings."""
    best_value = ""
    best_conf = -1.0
    for material in materials:
        raw_value = getattr(material, field_name, None)
        if _is_blank_value(raw_value):
            continue
        confidence = getattr(material, "confidence", None) or {}
        try:
            score = float(confidence.get(field_name, 0.0) or 0.0)
        except (TypeError, ValueError):
            score = 0.0
        if score > best_conf:
            best_conf = score
            best_value = str(raw_value).strip()
    return best_value, (best_conf if best_conf >= 0.0 else 0.0)


def _is_noise_v4_material(part_number: str, description: str, quantity: Any) -> bool:
    """Filter obvious non-parts from extraction stream."""
    pn = _normalize_v4_part_number(part_number)
    desc = str(description or "").upper()
    qty = str(quantity or "").strip().upper()

    if not pn:
        return True
    if pn.startswith("NOTE") or re.fullmatch(r"NOTE-?\d+", pn):
        return True
    if re.fullmatch(r"\d+\.?", pn):
        return True
    # ICD docs are references, not MIUL parts.
    if pn.endswith("-ICD"):
        return True
    if qty == "AR" and any(token in desc for token in ("LUBRICANT", "GREASE", "OIL")):
        return True
    return False


def _default_project_from_dt(dt_json: Dict[str, Any], extraction_id: str) -> str:
    """Infer a stable project identifier from DT top-level drawing number."""
    top_level = str((dt_json or {}).get("top_level") or "").strip().upper()
    if not top_level:
        return f"MIUL_V4_{extraction_id[:8]}"

    # MER07540-001 -> MER07540
    match = re.match(r"^([A-Z]+\d+)", top_level)
    if match:
        return match.group(1)

    # GPE-A000-1 -> GPE-A000
    match = re.match(r"^([A-Z0-9-]+?)(?:-\d+)?$", top_level)
    if match:
        return match.group(1)

    return top_level


def _build_parts_json_from_v4_extraction(
    extraction_result: Any,
    review_data: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """Convert reviewed v4 extraction into v3 merge-compatible parts_json."""
    grouped: Dict[str, List[Any]] = {}
    for material in extraction_result.materials:
        pn = _normalize_v4_part_number(getattr(material, "part_number", ""))
        desc = str(getattr(material, "part_description", "") or "")
        qty = getattr(material, "quantity", "")
        if _is_noise_v4_material(pn, desc, qty):
            continue
        grouped.setdefault(pn, []).append(material)

    dt_tree = (extraction_result.dt_context or {}).get("tree", [])
    dt_lookup = {
        _normalize_v4_part_number(node.get("drawing_number", "")): node
        for node in dt_tree
        if node.get("drawing_number")
    }

    review_overrides: Dict[str, Dict[str, Any]] = {}
    if review_data:
        for item in review_data.get("review_items", []):
            pn = _normalize_v4_part_number(item.get("part_number", ""))
            if pn:
                review_overrides[pn] = item

    parts: Dict[str, Dict[str, Any]] = {}
    drawings: Dict[str, Dict[str, Any]] = {}

    for pn, sightings in grouped.items():
        sightings_sorted = sorted(sightings, key=_material_worst_confidence, reverse=True)
        primary = sightings_sorted[0]

        chosen_fields: Dict[str, str] = {}
        for field_name in ("designation", "material_spec", "process_spec", "uns_code", "material_form"):
            chosen_fields[field_name], _ = _select_best_field_value(sightings_sorted, field_name)

        # Human-reviewed values are authoritative for corrected/accepted items.
        review_item = review_overrides.get(pn)
        if review_item:
            review_fields = review_item.get("fields", {})
            for field_name in ("designation", "material_spec", "process_spec", "uns_code", "material_form"):
                reviewed_value = (review_fields.get(field_name) or {}).get("value")
                if not _is_blank_value(reviewed_value):
                    chosen_fields[field_name] = str(reviewed_value).strip()

        description = str(getattr(primary, "part_description", "") or "").strip()
        source_file = str(getattr(primary, "source_file", "") or "")
        source_drawing = _extract_drawing_number_from_source(source_file)
        if not source_drawing and pn in dt_lookup:
            source_drawing = pn

        parts[pn] = {
            "description": description,
            "material": chosen_fields.get("designation", ""),
            "material_spec": chosen_fields.get("material_spec", ""),
            "process_spec": chosen_fields.get("process_spec", ""),
            "uns": chosen_fields.get("uns_code", ""),
            "source_drawing": source_drawing,
        }

        dt_node = dt_lookup.get(pn)
        if dt_node:
            drawings[pn] = {
                "title": str(dt_node.get("title") or description or "").strip(),
                "revision": "",
                "material": chosen_fields.get("designation", ""),
                "material_spec": chosen_fields.get("material_spec", ""),
                "process_spec": chosen_fields.get("process_spec", ""),
                "uns": chosen_fields.get("uns_code", ""),
                "drawing_type": str(dt_node.get("type") or "DETAIL").upper(),
            }

    return {
        "parts": parts,
        "drawings": drawings,
    }


def _run_extraction_background(
    extraction_id: str,
    pdf_paths: List[Path],
    dt_json: dict,
    temp_dir: Path,
) -> None:
    """Background worker: runs Sonnet extraction and writes results to session.

    This runs in a separate thread via asyncio.to_thread so the HTTP response
    returns immediately and the frontend polls /v4/extract/{id}/status.
    """
    from mira.miul.production.session import V4Session
    session = V4Session(extraction_id)

    try:
        session.set_status("extracting", "Running OCR scan...", progress=5)

        extractor = _get_v4_extractor()
        result = extractor.extract_from_files(pdf_paths, dt_json)

        # Override the extraction_id so it matches what we told the frontend
        result.extraction_id = extraction_id

        session.set_status("saving", "Saving results...", progress=90)
        session.save_extraction(result)

        review = session.load_review()
        summary = result.summary

        session.set_status(
            "complete",
            f"{summary.get('total_materials', 0)} materials extracted",
            progress=100,
            summary=summary,
        )

        LOGGER.info(
            f"[MIUL-V4] Extraction complete: {summary.get('total_materials', 0)} materials, "
            f"{summary.get('needs_review', 0)} need review"
        )

    except Exception as e:
        LOGGER.error(f"[MIUL-V4] Background extraction failed: {e}", exc_info=True)
        session.set_status("failed", str(e), progress=0, error=str(e))

    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


# =============================================================================
# V4 Session Management
# =============================================================================

@router.get("/v4/sessions")
async def list_v4_sessions(http_request: Request, limit: int = 20) -> dict:
    """List recent v4 extraction sessions for session resume UI."""
    from mira.miul.production.session import list_sessions
    sessions = list_sessions(limit=limit)
    actor = get_request_user(http_request)
    if actor is not None and not actor.is_admin:
        actor_name = (actor.username or actor.email or "").strip().lower()
        sessions = [
            item for item in sessions
            if (_get_v4_session(item["extraction_id"]).get_owner_username() or "").strip().lower() == actor_name
        ]
    return {"sessions": sessions}


@router.delete("/v4/sessions/{extraction_id}")
async def delete_v4_session(extraction_id: str, http_request: Request) -> dict:
    """Delete a v4 session (sensitive-build purge).

    Removes all session files (extraction, review, audit, status).
    Used when the user toggled 'sensitive build' to prevent data persistence.
    """
    from mira.miul.production.session import get_session_root

    session = _get_v4_session(extraction_id)
    _authorize_v4_session(http_request, session)

    session_dir = get_session_root() / extraction_id
    if not session_dir.exists():
        raise HTTPException(status_code=404, detail="Session not found")
    try:
        shutil.rmtree(session_dir)
    except OSError as e:
        raise HTTPException(status_code=500, detail=f"Failed to delete session: {e}")
    return {"deleted": True, "extraction_id": extraction_id}


# =============================================================================
# V4 Extraction Pipeline
# =============================================================================

@router.post("/v4/extract")
async def extract_miul_v4(
    http_request: Request,
    drawings: List[UploadFile] = File(...),
    drawing_tree_json: UploadFile = File(None),
    project: str = Form(""),
) -> dict:
    """V4 MIUL Extraction -- Sonnet Vision with 2-pass gap-filling.

    Returns immediately with an extraction_id. The actual extraction runs
    in the background. Frontend polls GET /v4/extract/{id}/status until
    status == "complete", then loads review items.

    This prevents proxy ECONNRESET from long-running Sonnet API calls
    (extraction takes 5-10 minutes for 20 PDFs).
    """
    if not drawings:
        raise HTTPException(status_code=400, detail="No PDF files provided")

    LOGGER.info(
        f"[MIUL-V4] Starting extraction: {len(drawings)} PDFs, "
        f"DT={(drawing_tree_json.filename if drawing_tree_json and drawing_tree_json.filename else 'none')}"
    )

    # Generate extraction ID upfront so we can return it immediately
    import uuid
    extraction_id = str(uuid.uuid4())

    # Create session directory and set initial status
    from mira.miul.production.session import V4Session
    session = V4Session(extraction_id)
    actor = get_request_user(http_request)
    session.set_owner_username(actor.username if actor else None)
    session.set_status("uploading", "Receiving files...", progress=1)

    # Save files to a persistent temp dir (NOT cleaned up until background worker finishes)
    temp_dir = Path(tempfile.mkdtemp())

    try:
        # Load DT JSON if provided; allow no-DT mode for degraded hierarchy builds.
        dt_json: Dict[str, Any] = {}
        if drawing_tree_json and drawing_tree_json.filename:
            dt_content = await drawing_tree_json.read()
            try:
                parsed = json.loads(dt_content)
            except json.JSONDecodeError:
                raise HTTPException(status_code=400, detail="Invalid DT JSON file")

            if not isinstance(parsed, dict):
                raise HTTPException(status_code=400, detail="DT JSON must be a JSON object")
            dt_json = parsed
        else:
            LOGGER.warning(
                "[MIUL-V4] No DT JSON provided; extraction will continue in degraded hierarchy mode."
            )

        # Save drawing PDFs to temp directory
        pdf_paths = []
        for drawing in drawings:
            if not drawing.filename or not drawing.filename.lower().endswith(".pdf"):
                continue
            content = await drawing.read()
            file_path = temp_dir / drawing.filename
            file_path.write_bytes(content)
            pdf_paths.append(file_path)

        LOGGER.info(f"[MIUL-V4] Saved {len(pdf_paths)} drawing PDFs to {temp_dir}")

        session.set_status("extracting", "Starting Sonnet Vision extraction...", progress=5)

        # Fire off extraction in background thread -- returns immediately
        asyncio.get_event_loop().run_in_executor(
            None,  # default ThreadPoolExecutor
            _run_extraction_background,
            extraction_id,
            pdf_paths,
            dt_json,
            temp_dir,
        )

        return {
            "extraction_id": extraction_id,
            "project": project,
            "status": "extracting",
            "dt_mode": "with_tree" if dt_json.get("tree") else "no_tree",
        }

    except HTTPException:
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise
    except Exception as e:
        shutil.rmtree(temp_dir, ignore_errors=True)
        LOGGER.error(f"[MIUL-V4] Extraction setup failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"MIUL v4 extraction failed: {e}")


@router.get("/v4/extract/{extraction_id}/status")
async def get_v4_extraction_status(extraction_id: str, http_request: Request) -> dict:
    """Poll extraction status. Frontend calls this every few seconds.

    Returns:
        status: "uploading" | "extracting" | "saving" | "complete" | "failed"
        progress: 0-100
        message: human-readable progress
        summary: (only when complete) extraction summary
        error: (only when failed) error message
    """
    session = _get_v4_session(extraction_id)
    _authorize_v4_session(http_request, session)
    return session.get_status()


@router.get("/v4/extract/{extraction_id}")
async def get_v4_extraction(extraction_id: str, http_request: Request) -> dict:
    """Get v4 extraction result by ID."""
    session = _get_v4_session(extraction_id)
    _authorize_v4_session(http_request, session)
    if not session.exists:
        raise HTTPException(status_code=404, detail=f"Extraction {extraction_id} not found")

    result = session.load_extraction()
    review = session.load_review()

    # Normalize summary keys: old sessions used "total_rows", frontend expects "total_materials"
    review_summary = review.get("summary", {}) if review else {}
    if "total_rows" in review_summary and "total_materials" not in review_summary:
        review_summary["total_materials"] = review_summary.pop("total_rows")

    return {
        "extraction_id": extraction_id,
        "summary": result.summary if result else {},
        "review_summary": review_summary,
        "status": review.get("status", "unknown") if review else "unknown",
    }


@router.get("/v4/extract/{extraction_id}/review")
async def get_v4_review_items(
    extraction_id: str,
    http_request: Request,
    confidence: Optional[str] = None,
    field: Optional[str] = None,
    status: Optional[str] = None,
) -> dict:
    """Get review items for a v4 extraction, with optional filters.

    Args:
        extraction_id: Extraction UUID
        confidence: Filter by confidence level ("low", "medium")
        field: Filter by field name ("designation", "material_spec", etc.)
        status: Filter by status ("open", "corrected", "accepted")
    """
    session = _get_v4_session(extraction_id)
    _authorize_v4_session(http_request, session)
    if not session.exists:
        raise HTTPException(status_code=404, detail=f"Extraction {extraction_id} not found")

    items = session.get_review_items(
        confidence_filter=confidence,
        field_filter=field,
        status_filter=status,
    )

    review = session.load_review()

    # Normalize summary keys: old sessions used "total_rows", frontend expects "total_materials"
    raw_summary = review.get("summary", {}) if review else {}
    if "total_rows" in raw_summary and "total_materials" not in raw_summary:
        raw_summary["total_materials"] = raw_summary.pop("total_rows")

    return {
        "extraction_id": extraction_id,
        "summary": raw_summary,
        "status": review.get("status", "unknown") if review else "unknown",
        "items": items,
        "count": len(items),
    }


@router.get("/v4/extract/{extraction_id}/materials")
async def get_v4_material_list(extraction_id: str, http_request: Request) -> dict:
    """Get the 'grocery list' -- unique material values across all extracted parts.

    Used to populate dropdowns in the review UI so engineers pick from
    known materials instead of free-typing. If 6061-T6 appears on 15 parts,
    it shows up once in the list.
    """
    session = _get_v4_session(extraction_id)
    _authorize_v4_session(http_request, session)
    if not session.exists:
        raise HTTPException(status_code=404, detail=f"Extraction {extraction_id} not found")

    result = session.load_extraction()
    if not result:
        return {"extraction_id": extraction_id, "materials": {}}

    # Normalize designations through alloy normalizer so variants collapse:
    #   "18-8 SS", "18-8 STAINLESS", "CRES 18-8" --> one canonical entry
    try:
        from mira.miul.alloy_normalizer import normalize_alloy
        has_normalizer = True
    except ImportError:
        has_normalizer = False

    # Collect unique non-null values for each material field
    spec_set: set = set()
    proc_set: set = set()
    uns_set: set = set()
    form_set: set = set()

    # For designations: canonical_name -> best raw string (highest confidence)
    desig_map: dict = {}  # canonical -> (raw_value, confidence)

    for mat in result.materials:
        if mat.designation:
            raw = mat.designation.strip()
            conf = mat.confidence.get("designation", 0.5)

            if has_normalizer:
                try:
                    norm = normalize_alloy(raw)
                    # Use UNS as dedup key when resolved (S30400 collapses
                    # "304 SS" and "18-8 STAINLESS" into one entry)
                    key = norm.uns or norm.canonical_name or raw.upper()
                except Exception:
                    key = raw.upper()
            else:
                key = raw.upper()

            # Keep the highest-confidence version of each canonical designation
            if key not in desig_map or conf > desig_map[key][1]:
                desig_map[key] = (raw, conf)

        if mat.material_spec:
            spec_set.add(mat.material_spec.strip())
        if mat.process_spec:
            proc_set.add(mat.process_spec.strip())
        if mat.uns_code:
            uns_set.add(mat.uns_code.strip())
        if mat.material_form:
            form_set.add(mat.material_form.strip().upper())

    # Extract just the best raw strings from the deduped designation map
    desig_list = sorted(raw for raw, _ in desig_map.values())

    return {
        "extraction_id": extraction_id,
        "materials": {
            "designation": desig_list,
            "material_spec": sorted(spec_set),
            "process_spec": sorted(proc_set),
            "uns_code": sorted(uns_set),
            "material_form": sorted(form_set),
        },
    }


@router.get("/v4/extract/{extraction_id}/drawings")
async def get_v4_drawing_list(extraction_id: str, http_request: Request) -> dict:
    """Get extracted drawing packages for the review-stage remove flow."""
    session = _get_v4_session(extraction_id)
    _authorize_v4_session(http_request, session)
    if not session.exists:
        raise HTTPException(status_code=404, detail=f"Extraction {extraction_id} not found")

    drawings = session.list_drawings()
    return {
        "extraction_id": extraction_id,
        "count": len(drawings),
        "drawings": drawings,
    }


@router.delete("/v4/extract/{extraction_id}/drawings/{drawing_id}")
async def remove_v4_drawing(
    extraction_id: str,
    drawing_id: str,
    http_request: Request,
    reviewer: str = "",
    reason: str = "",
) -> dict:
    """Remove a drawing from an extracted session and regenerate review data."""
    session = _get_v4_session(extraction_id)
    _authorize_v4_session(http_request, session)
    if not session.exists:
        raise HTTPException(status_code=404, detail=f"Extraction {extraction_id} not found")

    result = session.remove_drawing(drawing_id=drawing_id, reviewer=reviewer, reason=reason)
    if not result.get("removed"):
        detail = result.get("error") or f"Drawing {drawing_id} not found"
        raise HTTPException(status_code=404, detail=detail)

    review = session.load_review() or {}
    review_summary = review.get("summary", {})
    if "total_rows" in review_summary and "total_materials" not in review_summary:
        review_summary["total_materials"] = review_summary.pop("total_rows")

    drawings = session.list_drawings()
    return {
        "extraction_id": extraction_id,
        "drawing_id": drawing_id,
        "removed": True,
        "summary": review_summary,
        "review_status": review.get("status", "unknown"),
        "drawings": drawings,
        **{k: v for k, v in result.items() if k != "removed"},
    }


@router.delete("/v4/extract/{extraction_id}/parts/{part_number:path}")
async def remove_v4_part(
    extraction_id: str,
    part_number: str,
    http_request: Request,
    reviewer: str = "",
    reason: str = "",
) -> dict:
    """Remove a part from an extracted session and regenerate review data."""
    session = _get_v4_session(extraction_id)
    _authorize_v4_session(http_request, session)
    if not session.exists:
        raise HTTPException(status_code=404, detail=f"Extraction {extraction_id} not found")

    result = session.remove_part(part_number=part_number, reviewer=reviewer, reason=reason)
    if not result.get("removed"):
        detail = result.get("error") or f"Part {part_number} not found"
        raise HTTPException(status_code=404, detail=detail)

    review = session.load_review() or {}
    review_summary = review.get("summary", {})
    if "total_rows" in review_summary and "total_materials" not in review_summary:
        review_summary["total_materials"] = review_summary.pop("total_rows")

    drawings = session.list_drawings()
    return {
        "extraction_id": extraction_id,
        "part_number": part_number,
        "removed": True,
        "summary": review_summary,
        "review_status": review.get("status", "unknown"),
        "drawings": drawings,
        **{k: v for k, v in result.items() if k != "removed"},
    }


@router.post("/v4/extract/{extraction_id}/review/{part_number}")
async def submit_v4_correction(
    extraction_id: str,
    part_number: str,
    http_request: Request,
    corrections: dict = Body(..., embed=True),
    reviewer: str = Body("", embed=True),
) -> dict:
    """Submit a human correction for a flagged review item.

    Frontend sends JSON: { "corrections": { field: value }, "reviewer": "engineer" }

    Args:
        extraction_id: Extraction UUID
        part_number: Part number to correct
        corrections: Dict of field_name -> corrected_value
        reviewer: Who made the correction
    """
    session = _get_v4_session(extraction_id)
    _authorize_v4_session(http_request, session)
    if not session.exists:
        raise HTTPException(status_code=404, detail=f"Extraction {extraction_id} not found")

    if not corrections:
        raise HTTPException(status_code=400, detail="No corrections provided")

    item = session.submit_correction(part_number, corrections, reviewer)
    if item is None:
        raise HTTPException(status_code=404, detail=f"Part {part_number} not found in review")

    return {"status": "corrected", "part_number": part_number, "item": item}


@router.post("/v4/extract/{extraction_id}/review/{part_number:path}/accept")
async def accept_v4_item(
    extraction_id: str,
    part_number: str,
    http_request: Request,
    reason: str = Form(""),
    reviewer: str = Form(""),
) -> dict:
    """Accept a flagged review item as-is (no correction needed).

    Args:
        extraction_id: Extraction UUID
        part_number: Part number to accept
        reason: Why accepting without correction
        reviewer: Who accepted
    """
    session = _get_v4_session(extraction_id)
    _authorize_v4_session(http_request, session)
    if not session.exists:
        raise HTTPException(status_code=404, detail=f"Extraction {extraction_id} not found")

    item = session.accept_item(part_number, reviewer, reason)
    if item is None:
        raise HTTPException(status_code=404, detail=f"Part {part_number} not found in review")

    return {"status": "accepted", "part_number": part_number, "item": item}


@router.post("/v4/extract/{extraction_id}/approve")
async def approve_v4_build(
    extraction_id: str,
    http_request: Request,
    reviewer: str = Form(...),
) -> dict:
    """Approve a v4 extraction for MIUL build.

    Checks all review items are resolved (corrected or accepted).
    Must be approved before /v4/build can be called.

    Args:
        extraction_id: Extraction UUID
        reviewer: Who is approving the build
    """
    session = _get_v4_session(extraction_id)
    _authorize_v4_session(http_request, session)
    if not session.exists:
        raise HTTPException(status_code=404, detail=f"Extraction {extraction_id} not found")

    approval = session.approve_build(reviewer)
    if not approval.get("approved"):
        return {
            "approved": False,
            "message": approval.get("message", "Unresolved items remain"),
            "unresolved_count": approval.get("unresolved_count", 0),
            "unresolved_parts": approval.get("unresolved_parts", []),
        }

    return {
        "approved": True,
        "approved_by": approval["approved_by"],
        "approved_at": approval["approved_at"],
        "extraction_id": extraction_id,
    }


@router.post("/v4/build")
async def build_miul_v4(
    http_request: Request,
    extraction_id: str = Form(...),
    project: str = Form(""),
    max_temp: float = Form(120.0),
    min_temp: float = Form(0.0),
    max_pressure: float = Form(14.7),
    min_pressure: float = Form(0.0),
    fluid_type: str = Form("Air"),
    environment: str = Form("Air, VAC"),
    o2_percent: float = Form(20.9),
) -> Response:
    """Build base MIUL from an approved v4 extraction (no enrichment).

    Produces a 40-column MAPTIS-compliant Excel with environment parameters.
    When DT context is present, tree/NHA/parent structure is DT-driven.
    When DT is missing, build runs in degraded hierarchy mode.

    ONLY works after extraction is approved via /v4/extract/{id}/approve.

    Args:
        extraction_id: Extraction UUID (must be approved)
        project: Project name for Excel output
        max_temp: Max operating temperature (deg F)
        min_temp: Min operating temperature (deg F)
        max_pressure: Max operating pressure (psia)
        min_pressure: Min operating pressure (psia)
        fluid_type: Service media (Air, O2, H2, etc.)
        environment: Environment description (e.g. "Air, VAC")
        o2_percent: Oxygen concentration (%)

    Returns:
        MAPTIS-compliant Excel file (base MIUL, no enrichment).
    """
    session = _get_v4_session(extraction_id)
    _authorize_v4_session(http_request, session)
    if not session.exists:
        raise HTTPException(status_code=404, detail=f"Extraction {extraction_id} not found")

    if not session.is_approved:
        raise HTTPException(
            status_code=409,
            detail="Extraction not yet approved. Review all items and call /v4/extract/{id}/approve first."
        )

    LOGGER.info(f"[MIUL-V4] Building MIUL from approved extraction: {extraction_id}")

    try:
        from mira.miul.v3.builder import _export_miul_excel, EnvironmentConfig
        from mira.miul.production.pair_builder import (
            build_miul_from_pair_rows,
            build_pair_rows_from_v4_extraction,
            build_parts_json_for_summary,
            validate_miul_tree_against_dt,
        )

        result = session.load_extraction()
        if not result:
            raise HTTPException(status_code=500, detail="Could not load extraction data")

        dt_json = result.dt_context if isinstance(result.dt_context, dict) else {}
        has_dt_tree = bool(dt_json.get("tree"))
        if not has_dt_tree:
            LOGGER.warning(
                "[MIUL-V4] No DT tree context for extraction %s; building in degraded hierarchy mode.",
                extraction_id,
            )

        review = session.load_review() or {}
        pair_rows = build_pair_rows_from_v4_extraction(result, review, dt_json=dt_json)

        if not project:
            project = _default_project_from_dt(dt_json, extraction_id)

        # Build environment config from form params
        env_config = EnvironmentConfig(
            max_temp=max_temp,
            min_temp=min_temp,
            max_pressure=max_pressure,
            min_pressure=min_pressure,
            fluid_type=fluid_type,
            environment=environment,
            o2_percent=o2_percent,
        )

        # Build MIUL at (Part Number, Drawing Source) granularity.
        # DT remains authoritative for NHA relationships.
        miul_df = build_miul_from_pair_rows(
            pair_rows,
            dt_json,
            project,
            environment=env_config,
        )
        parts_json_for_summary = build_parts_json_for_summary(pair_rows, dt_json)

        validation = (
            validate_miul_tree_against_dt(miul_df, dt_json)
            if has_dt_tree
            else {
                "valid": True,
                "skipped": True,
                "reason": "No DT tree context provided",
            }
        )
        enforce_tree_validation = _env_flag("MIUL_V4_ENFORCE_TREE_VALIDATION", True)
        if has_dt_tree and enforce_tree_validation and not validation.get("valid", False):
            LOGGER.error(
                "[MIUL-V4] Tree validation failed for extraction %s: missing=%d extra=%d "
                "parent_mismatches=%d tree_nha_mismatches=%d subpart_nha_mismatches=%d",
                extraction_id,
                len(validation.get("missing_nodes", [])),
                len(validation.get("extra_tree_nodes", [])),
                len(validation.get("parent_mismatches", [])),
                len(validation.get("tree_nha_mismatches", [])),
                len(validation.get("subpart_nha_mismatches", [])),
            )
            raise HTTPException(
                status_code=422,
                detail={
                    "message": "Built MIUL tree does not match DT structure.",
                    "validation": validation,
                    "rollback_hint": (
                        "Set MIUL_V4_ENFORCE_TREE_VALIDATION=0 to bypass temporarily, "
                        "or MIUL_V4_STRUCTURAL_TREE_MODE=legacy for rollback mode."
                    ),
                },
            )

        LOGGER.info(
            f"[MIUL-V4] Pair build: {len(pair_rows)} pair rows -> "
            f"{len(miul_df)} MIUL rows (env: {fluid_type}, {min_temp}-{max_temp}F, "
            f"{min_pressure}-{max_pressure} psia)"
        )

        # Export with v3 MAPTIS formatting and summary sheet (NO enrichment).
        # Use /enrich endpoint separately to add material codes + ratings.
        export_dir = Path(tempfile.mkdtemp())
        export_path = export_dir / f"MIUL_{project}_v4.xlsx"
        try:
            _export_miul_excel(
                miul_df,
                export_path,
                project,
                dt_json,
                parts_json_for_summary,
                environment=env_config,
            )
            excel_bytes = export_path.read_bytes()
        finally:
            shutil.rmtree(export_dir, ignore_errors=True)

        # Also save to persistent location for manual retrieval
        persistent_path = Path("C:/BoundState/temp") / f"MIUL_{project}_v4.xlsx"
        persistent_path.parent.mkdir(parents=True, exist_ok=True)
        persistent_path.write_bytes(excel_bytes)
        LOGGER.info(f"[MIUL-V4] Build complete: {len(miul_df)} rows -> {persistent_path}")

        return Response(
            content=excel_bytes,
            media_type=XLSX_MEDIA_TYPE,
            headers={
                "Content-Disposition": f"attachment; filename=MIUL_{project}_v4.xlsx",
                "X-Pipeline-Version": "v4-hybrid",
                "X-Project": project,
                "X-MIUL-Count": str(len(miul_df)),
                "X-Extraction-ID": extraction_id,
                "X-V4-Tree-Mode": str(os.getenv("MIUL_V4_STRUCTURAL_TREE_MODE", "deterministic")),
                "X-V4-Package-Mode": "on" if _env_flag("MIUL_V4_USE_DRAWING_PACKAGES", True) else "off",
                "X-V4-DT-Context": "provided" if has_dt_tree else "missing",
                "X-V4-Tree-Validation-Enforced": "on" if (has_dt_tree and enforce_tree_validation) else "off",
                "X-V4-Tree-Validation-Pass": (
                    "yes" if validation.get("valid", False) else ("n/a" if not has_dt_tree else "no")
                ),
            },
        )

    except HTTPException:
        raise
    except Exception as e:
        LOGGER.error(f"[MIUL-V4] Build failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"MIUL v4 build failed: {e}")
