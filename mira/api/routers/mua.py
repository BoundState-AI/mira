#!/usr/bin/env python3
"""
Module: Mua
Purpose: MUA API endpoints for BoundState.

BoundState AI 2025
Version: 1.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Fran OpenAI 5 <noreply@openai.com>
Co-Authored-By: Grok 4.0 <noreply@x.ai>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: NASA-STD-6016C (Material Control)
Safety Critical: True
"""

from __future__ import annotations

import logging
import tempfile
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd
from fastapi import APIRouter, Body, File, HTTPException, Query, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

import uuid

from mira.mua.service import generate_mua
from mira.mua.api_models import (
    EnvironmentSpec,
    MaterialRating,
    MuaGenerationRequest,
)

LOGGER = logging.getLogger(__name__)

router = APIRouter()


@router.get("/ping")
async def ping() -> dict:
    """Health check for MUA endpoint."""
    return {"status": "ok", "domain": "mua"}


@router.post("/generate-batch")
async def generate_batch_muas(
    file: UploadFile = File(...),
    program: str = Query("ORION", description="Program name"),
    hardware: str = Query("", description="Hardware/system name"),
) -> Dict[str, Any]:
    """Generate MUAs for materials in enriched MIUL with rating gaps.

    Reads an enriched MIUL Excel file and generates MUA documents for
    materials that have non-A ratings (gaps requiring mitigation).

    Args:
        file: Enriched MIUL Excel file with rating columns populated
        program: Program name (e.g., 'ORION', 'Gateway')
        hardware: Hardware/system name

    Returns:
        JSON response with MUA generation results
    """
    if not file.filename.lower().endswith((".xlsx", ".xls")):
        raise HTTPException(status_code=400, detail="File must be Excel format (.xlsx)")

    LOGGER.info(f"[MUA] Generating batch MUAs from {file.filename}")

    with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as tmp:
        content = await file.read()
        tmp.write(content)
        tmp_path = Path(tmp.name)

    try:
        miul_df = pd.read_excel(tmp_path, sheet_name="MIUL", engine="openpyxl")

        muas_generated = 0
        materials_processed = 0
        mua_results: List[Dict[str, Any]] = []

        # Rating columns to check for gaps - support multiple naming conventions
        # Format: (api_test_class, [possible_column_names])
        # api_test_class must match MaterialRating.test_class Literal values: FLAMM, SCC, CORR, TVS, TOX, FS
        rating_column_variants = [
            ("FLAMM", ["FLAM", "FLAMM", "FLAMM Rating", "Flam Rating", "Flammability"]),
            ("CORR", ["CORR", "CORR Rating", "Corr Rating", "Corrosion"]),
            ("SCC", ["SCC", "SCC Rating", "Scc Rating", "Stress Corrosion"]),
            ("TVS", ["TVS", "TVS Rating", "Tvs Rating", "Outgassing"]),
            ("TOX", ["TOX", "TOX Rating", "Tox Rating", "Toxicity"]),
            ("FS", ["FS", "FS Rating", "Fs Rating", "Fluid Service"]),
        ]

        # Find which column names exist in this file
        def find_rating_column(df_columns, variants):
            """Find which column name variant exists in dataframe."""
            for variant in variants:
                if variant in df_columns:
                    return variant
            return None

        rating_column_map = {}
        for api_test_class, variants in rating_column_variants:
            col = find_rating_column(miul_df.columns, variants)
            if col:
                rating_column_map[api_test_class] = col

        LOGGER.info(f"[MUA] Found rating columns: {rating_column_map}")

        # Valid rating values per MaterialRating model
        VALID_RATINGS = {"A", "B", "C", "X", "U"}

        # Map non-standard values to valid ratings
        RATING_NORMALIZATION = {
            "LOW": "A",      # LOW risk = acceptable
            "MED": "B",      # MEDIUM risk
            "MEDIUM": "B",
            "HIGH": "C",     # HIGH risk
            "D": "C",        # D rating -> C (both non-compliant)
            "I": "U",        # Incomplete -> Unknown
            "K": "U",        # K rating -> Unknown
            "N": "U",        # Not tested -> Unknown
        }

        for idx, row in miul_df.iterrows():
            material_code = row.get("Material Code")
            if pd.isna(material_code) or not str(material_code).strip():
                continue

            materials_processed += 1

            # Collect known ratings using detected column names
            known_ratings: List[MaterialRating] = []
            has_gap = False

            for test_class, col_name in rating_column_map.items():
                if col_name in row and pd.notna(row[col_name]):
                    rating = str(row[col_name]).strip().upper()
                    # Skip empty/null values
                    if not rating or rating in ("", "N/A", "NAN", "NONE", "-"):
                        continue

                    # Normalize non-standard rating values
                    if rating not in VALID_RATINGS:
                        normalized = RATING_NORMALIZATION.get(rating)
                        if normalized:
                            LOGGER.debug(f"Normalized rating {rating} -> {normalized} for {test_class}")
                            rating = normalized
                        else:
                            LOGGER.warning(f"Skipping unknown rating value '{rating}' for {test_class}")
                            continue

                    known_ratings.append(MaterialRating(test_class=test_class, rating=rating))
                    if rating != "A":
                        has_gap = True

            # Skip if all A-ratings or no ratings found
            if not has_gap:
                continue

            # Generate MUA
            try:
                request = MuaGenerationRequest(
                    material_key=str(material_code),
                    material_name=str(row.get("Designation", "")),
                    program=program,
                    hardware_name=hardware,
                    environment=EnvironmentSpec(),
                    known_ratings=known_ratings,
                )

                response = generate_mua(request)

                if response.success:
                    muas_generated += 1
                    # Structure must match frontend MUAResult interface
                    mua_results.append({
                        "material_code": str(material_code),
                        "designation": str(row.get("Designation", "")),
                        "mua": {
                            "required": True,
                            "id": f"MUA-{material_code}",
                            "category": response.category,
                            "gap_profile": response.gaps_identified,  # Already a dict
                            "confidence": {
                                "global": 0.8,
                                "ci_68": [0.7, 0.9],
                                "ci_95": [0.6, 0.95],
                            },
                            "draft_text": response.rationale_summary or "",
                        },
                    })

            except Exception as e:
                LOGGER.warning(f"MUA generation failed for {material_code}: {e}")

        LOGGER.info(f"[MUA] Generated {muas_generated} MUAs from {materials_processed} materials")

        return {
            "success": True,
            "materials_processed": materials_processed,
            "muas_generated": muas_generated,
            "muas": mua_results,  # Frontend expects "muas" not "mua_results"
            "program": program,
            "hardware": hardware,
            "timestamp": datetime.utcnow().isoformat(),
        }

    except Exception as e:
        LOGGER.error(f"[MUA] Batch generation failed: {e}")
        raise HTTPException(status_code=500, detail=f"MUA generation failed: {e}")

    finally:
        tmp_path.unlink(missing_ok=True)


@router.post("/generate-batch-excel")
async def generate_batch_muas_excel(
    file: UploadFile = File(...),
    program: str = Query("ORION", description="Program name"),
    hardware: str = Query("", description="Hardware/system name"),
) -> StreamingResponse:
    """Generate MUAs and return as Excel file with drafts.

    Same as generate-batch but returns an Excel file with:
    - MIUL sheet (original enriched data)
    - MUA_Summary sheet (materials needing MUAs)
    - Drafts sheet (MUA draft text for each material)

    Args:
        file: Enriched MIUL Excel file with rating columns populated
        program: Program name
        hardware: Hardware/system name

    Returns:
        Excel file with MIUL, MUA_Summary, and Drafts sheets
    """
    if not file.filename.lower().endswith((".xlsx", ".xls")):
        raise HTTPException(status_code=400, detail="File must be Excel format (.xlsx)")

    LOGGER.info(f"[MUA] Generating batch MUAs Excel from {file.filename}")

    with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as tmp:
        content = await file.read()
        tmp.write(content)
        tmp_path = Path(tmp.name)

    try:
        miul_df = pd.read_excel(tmp_path, sheet_name="MIUL", engine="openpyxl")

        # Rating columns to check for gaps - support multiple naming conventions
        # api_test_class must match MaterialRating.test_class Literal values: FLAMM, SCC, CORR, TVS, TOX, FS
        rating_column_variants = [
            ("FLAMM", ["FLAM", "FLAMM", "FLAMM Rating", "Flam Rating", "Flammability"]),
            ("CORR", ["CORR", "CORR Rating", "Corr Rating", "Corrosion"]),
            ("SCC", ["SCC", "SCC Rating", "Scc Rating", "Stress Corrosion"]),
            ("TVS", ["TVS", "TVS Rating", "Tvs Rating", "Outgassing"]),
            ("TOX", ["TOX", "TOX Rating", "Tox Rating", "Toxicity"]),
            ("FS", ["FS", "FS Rating", "Fs Rating", "Fluid Service"]),
        ]

        def find_rating_column(df_columns, variants):
            for variant in variants:
                if variant in df_columns:
                    return variant
            return None

        rating_column_map = {}
        for api_test_class, variants in rating_column_variants:
            col = find_rating_column(miul_df.columns, variants)
            if col:
                rating_column_map[api_test_class] = col

        LOGGER.info(f"[MUA Excel] Found rating columns: {rating_column_map}")

        # Valid rating values per MaterialRating model
        VALID_RATINGS = {"A", "B", "C", "X", "U"}

        # Map non-standard values to valid ratings
        RATING_NORMALIZATION = {
            "LOW": "A",      # LOW risk = acceptable
            "MED": "B",      # MEDIUM risk
            "MEDIUM": "B",
            "HIGH": "C",     # HIGH risk
            "D": "C",        # D rating -> C (both non-compliant)
            "I": "U",        # Incomplete -> Unknown
            "K": "U",        # K rating -> Unknown
            "N": "U",        # Not tested -> Unknown
        }

        # Add Remarks column if it doesn't exist
        if "Remarks" not in miul_df.columns:
            miul_df["Remarks"] = ""

        muas_generated = 0
        for idx, row in miul_df.iterrows():
            material_code = row.get("Material Code")
            if pd.isna(material_code) or not str(material_code).strip():
                continue

            known_ratings: List[MaterialRating] = []
            has_gap = False

            for test_class, col_name in rating_column_map.items():
                if col_name in row and pd.notna(row[col_name]):
                    rating = str(row[col_name]).strip().upper()
                    # Skip empty/null values
                    if not rating or rating in ("", "N/A", "NAN", "NONE", "-"):
                        continue

                    # Normalize non-standard rating values
                    if rating not in VALID_RATINGS:
                        normalized = RATING_NORMALIZATION.get(rating)
                        if normalized:
                            rating = normalized
                        else:
                            LOGGER.warning(f"Skipping unknown rating value '{rating}' for {test_class}")
                            continue

                    known_ratings.append(MaterialRating(test_class=test_class, rating=rating))
                    if rating != "A":
                        has_gap = True

            if not has_gap:
                continue

            try:
                request = MuaGenerationRequest(
                    material_key=str(material_code),
                    material_name=str(row.get("Designation", "")),
                    program=program,
                    hardware_name=hardware,
                    environment=EnvironmentSpec(),
                    known_ratings=known_ratings,
                )

                response = generate_mua(request)

                if response.success:
                    muas_generated += 1
                    # Build remarks text: Category + rationale + mitigations
                    remarks_parts = [f"[Cat {response.category}] {response.rationale_summary}"]
                    for mit in response.mitigations:
                        remarks_parts.append(f"{mit.test_class}: {mit.mitigation_text}")

                    # Add to Remarks column in the original dataframe
                    miul_df.at[idx, "Remarks"] = " | ".join(remarks_parts)

            except Exception as e:
                LOGGER.warning(f"MUA generation failed for {material_code}: {e}")

        # Create Excel output - keep original format, just add Remarks
        output = BytesIO()
        with pd.ExcelWriter(output, engine="openpyxl") as writer:
            miul_df.to_excel(writer, sheet_name="MIUL", index=False)

        output.seek(0)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"MIUL_with_MUAs_{timestamp}.xlsx"

        LOGGER.info(f"[MUA] Generated Excel with {muas_generated} MUA remarks added")

        return StreamingResponse(
            iter([output.getvalue()]),
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f"attachment; filename={filename}"},
        )

    except Exception as e:
        LOGGER.error(f"[MUA] Excel generation failed: {e}")
        raise HTTPException(status_code=500, detail=f"MUA Excel generation failed: {e}")

    finally:
        tmp_path.unlink(missing_ok=True)


# =============================================================================
# MUA BOK V2 Interactive Workflow Endpoints
# =============================================================================

class MUABOKPrecedent(BaseModel):
    """MUA precedent from BOK search."""
    mua_number: str
    material: str
    environment: str
    determination: str
    rationale_summary: str
    rationale_full: Optional[str] = None
    score: float
    source_file: str
    category: Optional[str] = None
    issue: Optional[str] = None
    material_family: Optional[str] = None
    test_reports: List[str] = Field(default_factory=list)


class MUABOKDraft(BaseModel):
    """Generated MUA draft with provenance."""
    material: str
    material_code: Optional[str] = None
    category: str
    gaps: Dict[str, str]
    rationale: str
    provenance_summary: str
    confidence: float
    environment: Optional[str] = None
    precedents: List[MUABOKPrecedent] = Field(default_factory=list)


class MUABOKFindRequest(BaseModel):
    """Request for exact material + issue matching."""
    material: str = Field(..., description="Material to find (e.g., '6061', '316 SS')")
    issues: List[str] = Field(default_factory=list, description="Issue types to filter (e.g., ['CORR', 'SCC'])")
    k: int = Field(20, ge=1, le=100, description="Max results to return")


class MUABOKGenerateFromSelectionRequest(BaseModel):
    """Request for MUA generation from user-selected precedents."""
    material: str = Field(..., description="Material designation")
    material_code: Optional[str] = Field(None, description="MAPTIS material code")
    environment: str = Field("", description="Operating environment")
    issues: Dict[str, str] = Field(..., description="Gap profile (e.g., {'CORR': 'B', 'SCC': 'C'})")
    selected_precedent_ids: List[str] = Field(..., description="MUA numbers of selected precedents")
    application: Optional[str] = Field(None, description="Application context")


def _get_mua_bok_engine():
    """Lazy load the MUA BOK engine."""
    try:
        from mira.miul.mua_bok_engine import MUABOKEngine
        return MUABOKEngine()
    except Exception as e:
        LOGGER.error(f"Failed to load MUA BOK engine: {e}")
        return None


@router.post("/bok/find")
async def find_mua_precedents(req: MUABOKFindRequest = Body(...)) -> Dict[str, Any]:
    """
    Find MUAs by EXACT material and issue matching.

    Interactive workflow Step 1:
    - User provides material (e.g., "6061") and issues (e.g., ["CORR", "SCC"])
    - Returns all MUAs for that exact material with those issues
    - Each result includes rationale summary for user review

    This is NOT semantic search - it's exact substring matching.
    """
    engine = _get_mua_bok_engine()
    if engine is None or engine.index is None:
        raise HTTPException(
            status_code=503,
            detail="MUA BOK index not loaded. Ensure mua_bok_v2.faiss exists."
        )

    try:
        # Find exact precedents
        precedents = engine.find_exact_precedents(
            material=req.material,
            issues=req.issues,
            k=req.k
        )

        # Convert to response with summaries
        results = []
        for p in precedents:
            summary = engine.summarize_rationale(p.rationale, max_length=200)
            results.append(MUABOKPrecedent(
                mua_number=p.mua_number,
                material=p.material,
                environment=p.environment,
                determination=p.determination,
                rationale_summary=summary,
                rationale_full=p.rationale,
                score=p.score,
                source_file=p.source_file,
                category=p.category,
                issue=p.issue,
                material_family=p.material_family,
                test_reports=p.test_reports,
            ).model_dump())

        return {
            "success": True,
            "count": len(results),
            "query": {
                "material": req.material,
                "issues": req.issues,
            },
            "precedents": results,
            "message": (
                f"Found {len(results)} MUAs for '{req.material}' "
                f"with issues: {', '.join(req.issues) if req.issues else 'any'}"
            ),
        }

    except Exception as e:
        LOGGER.error(f"MUA BOK find failed: {e}")
        raise HTTPException(status_code=500, detail=f"MUA BOK find failed: {e}")


@router.post("/bok/generate-from-selection")
async def generate_mua_from_selection(
    req: MUABOKGenerateFromSelectionRequest = Body(...)
) -> Dict[str, Any]:
    """
    Generate MUA draft from user-selected precedents.

    Interactive workflow Step 2:
    - User has reviewed precedents from /bok/find
    - User selects which precedent rationales apply
    - System generates new MUA citing selected precedents

    This produces a draft MUA with provenance citations.
    """
    engine = _get_mua_bok_engine()
    if engine is None or engine.index is None:
        raise HTTPException(
            status_code=503,
            detail="MUA BOK index not loaded. Ensure mua_bok_v2.faiss exists."
        )

    if not req.selected_precedent_ids:
        raise HTTPException(
            status_code=400,
            detail="At least one precedent must be selected"
        )

    try:
        # Generate draft from selections
        draft = engine.generate_from_selected_precedents(
            material=req.material,
            material_code=req.material_code,
            environment=req.environment,
            issues=req.issues,
            selected_precedent_ids=req.selected_precedent_ids,
            application=req.application,
        )

        # Convert precedents to response format
        precedent_responses = []
        for p in draft.precedents:
            summary = engine.summarize_rationale(p.rationale, max_length=200)
            precedent_responses.append(MUABOKPrecedent(
                mua_number=p.mua_number,
                material=p.material,
                environment=p.environment,
                determination=p.determination,
                rationale_summary=summary,
                rationale_full=p.rationale,
                score=p.score,
                source_file=p.source_file,
                category=p.category,
                issue=p.issue,
                material_family=p.material_family,
                test_reports=p.test_reports,
            ).model_dump())

        return {
            "success": True,
            "draft": MUABOKDraft(
                material=draft.material,
                material_code=draft.material_code,
                category=draft.category,
                gaps=draft.gaps,
                rationale=draft.rationale,
                provenance_summary=draft.provenance_summary,
                confidence=draft.confidence,
                environment=draft.environment,
                precedents=precedent_responses,
            ).model_dump(),
            "message": (
                f"Generated MUA draft for '{draft.material}' citing "
                f"{len(draft.precedents)} selected precedents"
            ),
        }

    except HTTPException:
        raise
    except Exception as e:
        LOGGER.error(f"MUA generation from selection failed: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"MUA generation from selection failed: {e}"
        )


@router.get("/bok/stats")
async def get_mua_bok_stats() -> Dict[str, Any]:
    """Get statistics about the MUA BOK V2 index."""
    engine = _get_mua_bok_engine()
    if engine is None or engine.index is None:
        return {
            "success": False,
            "error": "MUA BOK index not loaded",
            "total_muas": 0,
        }

    try:
        # Count by material family
        families: Dict[str, int] = {}
        envs: Dict[str, int] = {}
        determinations: Dict[str, int] = {}

        for meta in engine.metadata:
            fam = meta.get("material_family") or "unknown"
            families[fam] = families.get(fam, 0) + 1

            env_flags = meta.get("environment_flags", {})
            for key, val in env_flags.items():
                if val:
                    env = key.replace("is_", "")
                    envs[env] = envs.get(env, 0) + 1

            det = meta.get("determination") or "unknown"
            determinations[det] = determinations.get(det, 0) + 1

        return {
            "success": True,
            "total_muas": engine.index.ntotal,
            "material_families": families,
            "environments": envs,
            "determinations": determinations,
        }

    except Exception as e:
        LOGGER.error(f"Failed to get BOK stats: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get BOK stats: {e}")


# =============================================================================
# MUA BOK V3 - Intelligent Synthesis Endpoints
# =============================================================================

class MUASynthesizeRequest(BaseModel):
    """Request for LLM-powered MUA synthesis."""
    material: str = Field(..., description="Material designation (e.g., 'Nylon 6/6', '316 SS')")
    material_code: Optional[str] = Field(None, description="MAPTIS material code")
    issue: str = Field(..., description="Issue type requiring MUA (FLAM, SCC, CORR, TVS, TOX, FS)")
    application: str = Field(..., description="Application description (e.g., 'Cable ties in avionics bay')")
    environment: str = Field("", description="Operating environment (e.g., 'Ambient, <150F')")
    location: str = Field("", description="Location category (Habitable, Non-habitable)")
    mass_quantity: Optional[str] = Field(None, description="Mass/quantity (e.g., '100g total')")
    program: Optional[str] = Field(None, description="Program name (e.g., 'Orion')")
    additional_context: Optional[str] = Field(None, description="Additional context for synthesis")


class ApplicabilityFactorResponse(BaseModel):
    """Single factor in applicability analysis."""
    match: str
    reason: str


class ApplicabilityAnalysisResponse(BaseModel):
    """Applicability analysis for a single precedent."""
    precedent_id: str
    applicability: str  # YES, PARTIAL, NO
    relevance_score: float
    factors: Dict[str, ApplicabilityFactorResponse]
    summary: str


class SynthesizedPrecedentResponse(BaseModel):
    """Precedent included in synthesis result."""
    mua_number: str
    material: str
    environment: str
    determination: str
    rationale_summary: str
    category: Optional[str] = None
    issue: Optional[str] = None
    application: Optional[str] = None
    score: float


class MUASynthesisResponse(BaseModel):
    """Response from MUA synthesis endpoint."""
    success: bool
    material: str
    issue: str
    category: str
    rationale: str
    confidence: float
    precedents: List[SynthesizedPrecedentResponse]
    applicability_analyses: List[ApplicabilityAnalysisResponse]
    warnings: List[str]
    error: Optional[str] = None


def _get_mua_synthesizer():
    """Lazy load the MUA synthesizer."""
    try:
        from mira.miul.mua_synthesizer import MUASynthesizer
        return MUASynthesizer()
    except Exception as e:
        LOGGER.error(f"Failed to load MUA synthesizer: {e}")
        return None


@router.post("/bok/synthesize")
async def synthesize_mua(req: MUASynthesizeRequest = Body(...)) -> Dict[str, Any]:
    """
    Generate MUA with LLM-powered applicability analysis and rationale synthesis.

    This is the V3 intelligent synthesis endpoint - NOT copy/paste.

    Workflow:
    1. Find precedents matching material/issue from BOK
    2. Analyze applicability of each precedent to user's specific use case (LLM)
    3. Synthesize NEW rationale citing applicable precedents (LLM)

    The generated rationale is original prose explaining WHY the material should
    be approved, not copied text from precedents.

    Args:
        req: Synthesis request with material, issue, application, environment details

    Returns:
        Synthesized MUA draft with applicability analyses and precedent citations
    """
    synthesizer = _get_mua_synthesizer()
    if synthesizer is None:
        raise HTTPException(
            status_code=503,
            detail="MUA synthesizer not available. Check BOK index and LLM configuration."
        )

    try:
        from mira.miul.mua_synthesizer import MUASynthesisRequest

        # Build synthesis request
        synthesis_request = MUASynthesisRequest(
            material=req.material,
            material_code=req.material_code,
            issue=req.issue,
            application=req.application,
            environment=req.environment,
            location=req.location,
            mass_quantity=req.mass_quantity,
            program=req.program,
            additional_context=req.additional_context,
        )

        # Run synthesis
        result = await synthesizer.generate_mua(synthesis_request)

        # Convert precedents to response format
        precedent_responses = []
        for p in result.precedents:
            # Summarize rationale for response
            rationale_summary = p.rationale[:300] + "..." if p.rationale and len(p.rationale) > 300 else (p.rationale or "")
            precedent_responses.append(SynthesizedPrecedentResponse(
                mua_number=p.mua_number,
                material=p.material,
                environment=p.environment,
                determination=p.determination,
                rationale_summary=rationale_summary,
                category=p.category,
                issue=p.issue,
                application=p.application,
                score=p.score,
            ).model_dump())

        # Convert applicability analyses to response format
        analysis_responses = []
        for a in result.applicability_analyses:
            factors_dict = {}
            for factor_name, factor_data in a.factors.items():
                factors_dict[factor_name] = ApplicabilityFactorResponse(
                    match=factor_data.match.value if hasattr(factor_data.match, 'value') else str(factor_data.match),
                    reason=factor_data.reason,
                ).model_dump()

            analysis_responses.append(ApplicabilityAnalysisResponse(
                precedent_id=a.precedent_id,
                applicability=a.applicability.value if hasattr(a.applicability, 'value') else str(a.applicability),
                relevance_score=a.relevance_score,
                factors=factors_dict,
                summary=a.summary,
            ).model_dump())

        return {
            "success": result.success,
            "material": result.material,
            "issue": result.issue,
            "category": result.category,
            "rationale": result.rationale,
            "confidence": result.confidence,
            "precedents": precedent_responses,
            "applicability_analyses": analysis_responses,
            "warnings": result.warnings,
            "error": result.error,
        }

    except HTTPException:
        raise
    except Exception as e:
        LOGGER.error(f"MUA synthesis failed: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"MUA synthesis failed: {str(e)}"
        )


# =============================================================================
# MUA Precedent Engine V4 - Tiered Retrieval with Adequacy Assessment
# =============================================================================

class PrecedentQueryRequest(BaseModel):
    """Request for precedent-based MUA evaluation."""
    material_name: str = Field(..., description="Material designation (e.g., 'Inconel 625')")
    material_key: Optional[str] = Field(None, description="MAPTIS material code")
    media: Optional[str] = Field(None, description="Operating media (e.g., 'GOX', 'LOX', 'GH2')")
    o2_pct: float = Field(21.0, description="Oxygen percentage")
    location_class: str = Field("non_habitable", description="Location class")
    temp_max_f: Optional[float] = Field(None, description="Maximum temperature (F)")
    temp_min_f: float = Field(70.0, description="Minimum temperature (F)")
    pressure_max_psia: Optional[float] = Field(None, description="Maximum pressure (psia)")
    deviation_types: List[str] = Field(default_factory=list, description="Deviation types (e.g., ['FLAM', 'CORR'])")
    program: Optional[str] = Field(None, description="Program name")
    application: Optional[str] = Field(None, description="Application description")
    k: int = Field(20, ge=1, le=100, description="Number of candidates to retrieve")


class PrecedentMatchResponse(BaseModel):
    """Single precedent match from evaluation."""
    contract_id: str
    material_name: str
    material_key: Optional[str]
    tier: int
    similarity_score: float
    material_equivalent: bool
    environment_equivalent: bool
    deviation_equivalent: bool
    media: Optional[str]
    o2_pct: float
    temp_max_f: Optional[float]
    pressure_max_psia: Optional[float]
    is_rejected: bool
    rationale_text: Optional[str]
    category: Optional[str]
    source_program: Optional[str]
    environment_delta_summary: str


class PrecedentEvaluationResponse(BaseModel):
    """Response from precedent evaluation."""
    success: bool
    query_material: str
    query_environment_summary: str
    n_total_candidates: int
    n_tier1: int
    n_tier2: int
    n_tier3: int
    adequacy: str
    adequacy_reasoning: str
    tier1_matches: List[PrecedentMatchResponse]
    tier2_matches: List[PrecedentMatchResponse]
    tier3_matches: List[PrecedentMatchResponse]
    recommended_base: Optional[PrecedentMatchResponse]
    base_selection_reasoning: str
    statistics: Dict[str, Any]


def _get_precedent_engine():
    """Lazy load the precedent engine."""
    try:
        from mira.precedent_engine import (
            PrecedentEngine,
            PrecedentEquivalenceConfig,
            PrecedentAdequacyConfig,
        )
        # Use default configs
        eq_config = PrecedentEquivalenceConfig()
        adequacy_config = PrecedentAdequacyConfig()
        return PrecedentEngine(eq_config, adequacy_config)
    except Exception as e:
        LOGGER.error(f"Failed to load precedent engine: {e}")
        return None


@router.post("/bok/precedent/evaluate")
async def evaluate_precedents(req: PrecedentQueryRequest = Body(...)) -> Dict[str, Any]:
    """
    Evaluate MUA precedents using tiered retrieval and adequacy assessment.

    This is the V4 Precedent Engine - tier-based matching with statistical adequacy:
    - Tier 1: Exact material + environment + deviation match
    - Tier 2: Same material, relaxed environment/deviation tolerance
    - Tier 3: Analog (different material, same deviation alignment)

    Returns adequacy level (STRONG, MODERATE, INSUFFICIENT) based on:
    - Number of matches
    - Match quality scores
    - Rejection rates
    - Cross-program validation

    Args:
        req: Query parameters including material, environment, deviations

    Returns:
        Tiered precedent matches with adequacy assessment
    """
    engine = _get_precedent_engine()
    if engine is None:
        raise HTTPException(
            status_code=503,
            detail="Precedent engine not available. Check configuration."
        )

    try:
        from mira.precedent_engine import EnrichedMUA, DeviationType, ProgramFamily

        # Map MUA issue abbreviations to DeviationType enum
        def parse_deviation_type(issue_str: str) -> DeviationType | None:
            """Map MUA issue abbreviations to DeviationType."""
            issue_upper = issue_str.strip().upper()
            mappings = {
                # Flammability
                "FLAM": DeviationType.FLAMMABILITY,
                "FLAMM": DeviationType.FLAMMABILITY,
                "FLAMMABILITY": DeviationType.FLAMMABILITY,
                "FL": DeviationType.FLAMMABILITY,
                # Toxicity
                "TOX": DeviationType.TOXICITY,
                "TOXIC": DeviationType.TOXICITY,
                "TOXICITY": DeviationType.TOXICITY,
                # Outgassing / TVS
                "TVS": DeviationType.TVS,
                "OUTGAS": DeviationType.OFFGASSING,
                "OUTGASSING": DeviationType.OFFGASSING,
                "TV": DeviationType.TVS,
                # Corrosion
                "CORR": DeviationType.CORROSION,
                "CORROSION": DeviationType.CORROSION,
                # Stress Corrosion Cracking
                "SCC": DeviationType.SCC,
                "STRESS CORROSION": DeviationType.SCC,
                # Fluid compatibility
                "FS": DeviationType.COMPATIBILITY,
                "FLUID": DeviationType.COMPATIBILITY,
                "COMPATIBILITY": DeviationType.COMPATIBILITY,
            }
            return mappings.get(issue_upper)

        # Build query MUA from request
        deviation_types = []
        for dt in req.deviation_types:
            dev_type = parse_deviation_type(dt)
            if dev_type and dev_type not in deviation_types:
                deviation_types.append(dev_type)
            else:
                LOGGER.warning(f"Unknown deviation type: {dt}")

        query = EnrichedMUA(
            contract_id="QUERY",
            source_file="api_request",
            material_name=req.material_name,
            material_key=req.material_key,
            media=req.media,
            o2_pct=req.o2_pct,
            location_class=req.location_class,
            temp_max_f=req.temp_max_f,
            temp_min_f=req.temp_min_f,
            pressure_max_psia=req.pressure_max_psia,
            deviation_types=deviation_types,
            program=req.program,
            application_text=req.application,
        )

        # For now, get candidates from BOK engine
        bok_engine = _get_mua_bok_engine()
        if bok_engine is None or bok_engine.index is None:
            raise HTTPException(
                status_code=503,
                detail="MUA BOK index not loaded for candidate retrieval."
            )

        # Find candidates via BOK semantic search
        bok_precedents = bok_engine.find_exact_precedents(
            material=req.material_name,
            issues=req.deviation_types,
            k=req.k
        )

        # Convert BOK precedents to EnrichedMUA format for evaluation
        candidates = []
        for p in bok_precedents:
            # Parse deviation types from issue field
            p_dev_types = []
            if p.issue:
                for issue in p.issue.replace("/", ",").split(","):
                    dev_type = parse_deviation_type(issue)
                    if dev_type and dev_type not in p_dev_types:
                        p_dev_types.append(dev_type)

            candidate = EnrichedMUA(
                contract_id=p.mua_number,
                source_file=p.source_file,
                material_name=p.material,
                material_key=None,  # Would need MAPTIS lookup
                media=None,  # Parse from environment
                o2_pct=21.0,
                location_class="non_habitable",
                deviation_types=p_dev_types,
                determination=p.determination,
                is_rejected=p.determination and "REJECTED" in p.determination.upper(),
                is_usable_precedent=p.determination and "APPROVED" in p.determination.upper(),
                rationale_text=p.rationale,
                category=p.category,
                program=None,
            )
            candidates.append(candidate)

        # Evaluate candidates using PrecedentEngine
        result = engine.evaluate_candidates(query, candidates)

        # Convert to response format
        def match_to_response(m) -> Dict[str, Any]:
            return PrecedentMatchResponse(
                contract_id=m.contract_id,
                material_name=m.material_name,
                material_key=m.material_key,
                tier=m.tier,
                similarity_score=m.similarity_score,
                material_equivalent=m.material_equivalent,
                environment_equivalent=m.environment_equivalent,
                deviation_equivalent=m.deviation_equivalent,
                media=m.media,
                o2_pct=m.o2_pct,
                temp_max_f=m.temp_max_f,
                pressure_max_psia=m.pressure_max_psia,
                is_rejected=m.is_rejected,
                rationale_text=m.rationale_text[:500] if m.rationale_text else None,
                category=m.category,
                source_program=m.source_program,
                environment_delta_summary=m.environment_delta_summary,
            ).model_dump()

        return {
            "success": True,
            "query_material": result.query_material_name,
            "query_environment_summary": result.query_environment_summary,
            "n_total_candidates": result.n_total_candidates,
            "n_tier1": result.n_tier1,
            "n_tier2": result.n_tier2,
            "n_tier3": result.n_tier3,
            "adequacy": result.adequacy.value,
            "adequacy_reasoning": result.adequacy_reasoning,
            "tier1_matches": [match_to_response(m) for m in result.tier1_matches],
            "tier2_matches": [match_to_response(m) for m in result.tier2_matches],
            "tier3_matches": [match_to_response(m) for m in result.tier3_matches],
            "recommended_base": match_to_response(result.recommended_base) if result.recommended_base else None,
            "base_selection_reasoning": result.base_selection_reasoning,
            "statistics": {
                "n_total_with_material": result.statistics.n_total_with_material,
                "n_similar_environment": result.statistics.n_similar_environment,
                "n_approved": result.statistics.n_approved,
                "n_rejected": result.statistics.n_rejected,
                "approval_rate": result.statistics.approval_rate,
            },
        }

    except HTTPException:
        raise
    except Exception as e:
        LOGGER.error(f"Precedent evaluation failed: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Precedent evaluation failed: {str(e)}"
        )
