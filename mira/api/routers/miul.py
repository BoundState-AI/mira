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
import shutil
import tempfile
from pathlib import Path
from typing import List, Optional

import pandas as pd
from fastapi import APIRouter, Body, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import Response, StreamingResponse

# Lazy imports for enrichment workflow - only loaded when /enrich or /gaps called
MIULWorkflow = None
get_miul_workflow = None

LOGGER = logging.getLogger(__name__)

router = APIRouter()


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
    max_iterations: int = Form(3),
) -> dict:
    """Extract Drawing Tree hierarchy from PDF.

    Takes a Drawing Tree PDF and returns the extracted hierarchy JSON.
    Uses v3 vision extraction with validation loop.

    This endpoint is designed for the DT Editor UI - upload PDF,
    get JSON back for visual verification and correction.

    Args:
        dt_file: Drawing Tree PDF file
        max_iterations: Max validation/correction iterations (default 3)

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

        # Run v3 DT extraction
        client = VisionClient()
        result = extract_drawing_tree(pdf_path, client, max_iterations=max_iterations)

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


@router.post("/enrich")
async def enrich_miul(
    file: UploadFile = File(...),
    workflow: MIULWorkflow = Depends(_get_workflow),
) -> StreamingResponse:
    """Enrich MIUL Excel with MAPTIS ratings.

    Takes a base MIUL Excel and populates rating columns from MAPTIS.
    CRITICAL: Preserves exact file format - modifies cells in-place without
    changing column order, widths, styles, filters, or any other formatting.

    Args:
        file: Excel file with MIUL sheet containing Material Code column
        workflow: Injected workflow instance

    Returns:
        Enriched Excel file with rating columns populated (identical format to input)
    """
    from io import BytesIO
    from openpyxl import load_workbook

    if not file.filename.lower().endswith((".xlsx", ".xls")):
        raise HTTPException(status_code=400, detail="File must be Excel format")

    LOGGER.info(f"[MIUL] Enriching MIUL from {file.filename}")

    tmp_path = None
    try:
        # Save uploaded file
        with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as tmp:
            content = await file.read()
            tmp.write(content)
            tmp_path = Path(tmp.name)

        # Read MIUL sheet into DataFrame for processing
        miul_df = pd.read_excel(tmp_path, sheet_name="MIUL", engine="openpyxl")
        original_columns = list(miul_df.columns)

        # Build column name -> index mapping (1-based for openpyxl)
        col_name_to_idx = {col: i + 1 for i, col in enumerate(original_columns)}

        # Run enrichment steps (2-4) on DataFrame
        miul_df, codes_found, quarantine = workflow.lookup_material_codes(miul_df)
        miul_df, stats = workflow.fetch_ratings(miul_df)

        LOGGER.info(
            f"[MIUL] Enrichment: {stats.get('enriched_count', 0)}/{stats.get('total_materials', 0)} "
            f"({stats.get('coverage_pct', 0):.1f}%), {len(quarantine)} quarantined"
        )

        # NOW: Modify original file in-place to preserve ALL formatting
        wb = load_workbook(tmp_path)
        ws = wb["MIUL"]

        # Update cells that changed (Material Code and rating columns)
        # Only update columns that exist in original file
        update_cols = ["Material Code", "FLAM", "SCC", "CORR", "TVS", "TOX", "FS"]

        for col_name in update_cols:
            if col_name not in col_name_to_idx:
                continue
            col_idx = col_name_to_idx[col_name]

            for row_idx, value in enumerate(miul_df[col_name], start=2):  # Row 2+ (1 is header)
                if pd.notna(value) and str(value).strip():
                    ws.cell(row=row_idx, column=col_idx, value=str(value))

        # Save modified workbook to BytesIO
        output = BytesIO()
        wb.save(output)
        output.seek(0)

        return StreamingResponse(
            iter([output.getvalue()]),
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": "attachment; filename=MIUL_enriched.xlsx"},
        )

    except Exception as e:
        LOGGER.error(f"[MIUL] Enrichment failed: {e}")
        raise HTTPException(status_code=500, detail=f"Enrichment failed: {e}")

    finally:
        if tmp_path:
            tmp_path.unlink(missing_ok=True)


@router.get("/gaps")
async def get_rating_gaps(
    file: UploadFile = File(...),
    workflow: MIULWorkflow = Depends(_get_workflow),
) -> dict:
    """Get parts with rating gaps that need rationale selection.

    Args:
        file: Excel file with enriched MIUL
        workflow: Injected workflow instance

    Returns:
        List of parts needing rationale
    """
    if not file.filename.lower().endswith((".xlsx", ".xls")):
        raise HTTPException(status_code=400, detail="File must be Excel format")

    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as tmp:
            content = await file.read()
            tmp.write(content)
            tmp_path = Path(tmp.name)

        miul_df = pd.read_excel(tmp_path, sheet_name="MIUL", engine="openpyxl")
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
    from mira.miul.v3.builder import MIULBuilderV3, build_miul_2phase, EnvironmentConfig

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
            builder.export_to_excel(df, output_excel, project=project)

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
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
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
        from mira.miul.vision_extractor import MIULVisionExtractor
        _V4Extractor = MIULVisionExtractor
    return _V4Extractor()


def _get_v4_session(extraction_id: str):
    """Lazy-load v4 session manager."""
    global _V4Session
    if _V4Session is None:
        from mira.miul.v4_session import V4Session
        _V4Session = V4Session
    return _V4Session(extraction_id)


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
    from mira.miul.v4_session import V4Session
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
async def list_v4_sessions(limit: int = 20) -> dict:
    """List recent v4 extraction sessions for session resume UI."""
    from mira.miul.v4_session import list_sessions
    sessions = list_sessions(limit=limit)
    return {"sessions": sessions}


@router.delete("/v4/sessions/{extraction_id}")
async def delete_v4_session(extraction_id: str) -> dict:
    """Delete a v4 session (sensitive-build purge).

    Removes all session files (extraction, review, audit, status).
    Used when the user toggled 'sensitive build' to prevent data persistence.
    """
    from mira.miul.v4_session import get_session_root

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
    drawings: List[UploadFile] = File(...),
    drawing_tree_json: UploadFile = File(...),
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

    if not drawing_tree_json or not drawing_tree_json.filename:
        raise HTTPException(
            status_code=400,
            detail="Drawing Tree JSON is required. Use the DT Editor to extract it first."
        )

    LOGGER.info(
        f"[MIUL-V4] Starting extraction: {len(drawings)} PDFs, "
        f"DT={drawing_tree_json.filename}"
    )

    # Generate extraction ID upfront so we can return it immediately
    import uuid
    extraction_id = str(uuid.uuid4())

    # Create session directory and set initial status
    from mira.miul.v4_session import V4Session
    session = V4Session(extraction_id)
    session.set_status("uploading", "Receiving files...", progress=1)

    # Save files to a persistent temp dir (NOT cleaned up until background worker finishes)
    temp_dir = Path(tempfile.mkdtemp())

    try:
        # Load DT JSON
        dt_content = await drawing_tree_json.read()
        try:
            dt_json = json.loads(dt_content)
        except json.JSONDecodeError:
            raise HTTPException(status_code=400, detail="Invalid DT JSON file")

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
        }

    except HTTPException:
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise
    except Exception as e:
        shutil.rmtree(temp_dir, ignore_errors=True)
        LOGGER.error(f"[MIUL-V4] Extraction setup failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"MIUL v4 extraction failed: {e}")


@router.get("/v4/extract/{extraction_id}/status")
async def get_v4_extraction_status(extraction_id: str) -> dict:
    """Poll extraction status. Frontend calls this every few seconds.

    Returns:
        status: "uploading" | "extracting" | "saving" | "complete" | "failed"
        progress: 0-100
        message: human-readable progress
        summary: (only when complete) extraction summary
        error: (only when failed) error message
    """
    session = _get_v4_session(extraction_id)
    return session.get_status()


@router.get("/v4/extract/{extraction_id}")
async def get_v4_extraction(extraction_id: str) -> dict:
    """Get v4 extraction result by ID."""
    session = _get_v4_session(extraction_id)
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
async def get_v4_material_list(extraction_id: str) -> dict:
    """Get the 'grocery list' -- unique material values across all extracted parts.

    Used to populate dropdowns in the review UI so engineers pick from
    known materials instead of free-typing. If 6061-T6 appears on 15 parts,
    it shows up once in the list.
    """
    session = _get_v4_session(extraction_id)
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


@router.post("/v4/extract/{extraction_id}/review/{part_number}")
async def submit_v4_correction(
    extraction_id: str,
    part_number: str,
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
    if not session.exists:
        raise HTTPException(status_code=404, detail=f"Extraction {extraction_id} not found")

    if not corrections:
        raise HTTPException(status_code=400, detail="No corrections provided")

    item = session.submit_correction(part_number, corrections, reviewer)
    if item is None:
        raise HTTPException(status_code=404, detail=f"Part {part_number} not found in review")

    return {"status": "corrected", "part_number": part_number, "item": item}


@router.post("/v4/extract/{extraction_id}/review/{part_number}/accept")
async def accept_v4_item(
    extraction_id: str,
    part_number: str,
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
    if not session.exists:
        raise HTTPException(status_code=404, detail=f"Extraction {extraction_id} not found")

    item = session.accept_item(part_number, reviewer, reason)
    if item is None:
        raise HTTPException(status_code=404, detail=f"Part {part_number} not found in review")

    return {"status": "accepted", "part_number": part_number, "item": item}


@router.post("/v4/extract/{extraction_id}/approve")
async def approve_v4_build(
    extraction_id: str,
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
    extraction_id: str = Form(...),
    project: str = Form(""),
) -> Response:
    """Build final MIUL from an approved v4 extraction.

    Phase 3 of the v4 pipeline. Takes approved extraction data and runs it
    through the existing enrichment pipeline: material code lookup -> MAPTIS
    ratings -> MIULTree construction -> Excel export.

    ONLY works after extraction is approved via /v4/extract/{id}/approve.

    Args:
        extraction_id: Extraction UUID (must be approved)
        project: Project name for Excel output

    Returns:
        MAPTIS-compliant Excel file.
    """
    session = _get_v4_session(extraction_id)
    if not session.exists:
        raise HTTPException(status_code=404, detail=f"Extraction {extraction_id} not found")

    if not session.is_approved:
        raise HTTPException(
            status_code=409,
            detail="Extraction not yet approved. Review all items and call /v4/extract/{id}/approve first."
        )

    LOGGER.info(f"[MIUL-V4] Building MIUL from approved extraction: {extraction_id}")

    try:
        result = session.load_extraction()
        if not result:
            raise HTTPException(status_code=500, detail="Could not load extraction data")

        # Build MIUL using existing workflow pipeline
        workflow = _get_workflow()

        # Convert extraction materials to DataFrame for existing pipeline
        rows = []
        for mat in result.materials:
            rows.append({
                "Part Number": mat.part_number,
                "Description": mat.part_description,
                "Designation": mat.designation or "",
                "Material Specification": mat.material_spec or "",
                "Process Specification": mat.process_spec or "",
                "Material Form": mat.material_form or "",
                "NHA": mat.nha or "",
                "Quantity": mat.quantity,
            })

        miul_df = pd.DataFrame(rows)

        if not project:
            project = f"MIUL_V4_{extraction_id[:8]}"

        # Run enrichment pipeline (reuse existing workflow)
        miul_df, codes_found, quarantine = workflow.lookup_material_codes(miul_df)
        miul_df, stats = workflow.fetch_ratings(miul_df)

        LOGGER.info(
            f"[MIUL-V4] Enrichment: {stats.get('enriched_count', 0)}/{stats.get('total_materials', 0)} "
            f"({stats.get('coverage_pct', 0):.1f}%)"
        )

        # Export to Excel (returns BytesIO buffer)
        excel_buffer = workflow.export_to_excel(miul_df)

        LOGGER.info(f"[MIUL-V4] Build complete: {len(miul_df)} rows exported")

        return Response(
            content=excel_buffer.getvalue(),
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={
                "Content-Disposition": f"attachment; filename=MIUL_{project}_v4.xlsx",
                "X-Pipeline-Version": "v4",
                "X-Project": project,
                "X-MIUL-Count": str(len(miul_df)),
                "X-Extraction-ID": extraction_id,
            },
        )

    except HTTPException:
        raise
    except Exception as e:
        LOGGER.error(f"[MIUL-V4] Build failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"MIUL v4 build failed: {e}")
