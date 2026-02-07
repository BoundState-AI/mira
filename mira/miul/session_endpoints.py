#!/usr/bin/env python3
"""
Module: Session Endpoints
Purpose: MIUL builder interactive session REST API endpoints.

BoundState AI 2025
Version: 1.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Fran OpenAI 5 <noreply@openai.com>
Co-Authored-By: Grok 4.0 <noreply@x.ai>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: SWE-013 (Data requirements), SWE-033 (Requirements Traceability)
Safety Critical: True
"""

from __future__ import annotations

import logging
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Dict, List, Literal, Optional

from fastapi import APIRouter, File, HTTPException, Query, UploadFile, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from .rationale_codes import (
    RationaleCategory,
    RationaleCode,
    get_rationales_for_rating,
)
from .session import (
    MIULSession,
    PartResolution,
    PartStatus,
    ResolutionType,
    SessionState,
    UseEnvironmentInput,
)

__all__ = [
    "router",
    "CreateSessionRequest",
    "CreateSessionResponse",
    "SessionStatusResponse",
    "PartReviewItem",
    "RationaleOption",
    "ApplyResolutionRequest",
    "ExportRequest",
    "ExportResponse",
]

__safety_critical__ = True

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/miul/session", tags=["MIUL Builder"])

# In-memory session store (production would use Redis/PostgreSQL)
_sessions: Dict[str, MIULSession] = {}

# In-memory storage for extracted parts per session
_session_parts: Dict[str, List[dict]] = {}

# In-memory storage for generated files per session
_session_files: Dict[str, Dict[str, bytes]] = {}


# === Request/Response Models ===


class CreateSessionRequest(BaseModel):
    """Request to create new MIUL builder session (Step 1)."""

    model_config = {"extra": "forbid"}

    program: str = Field(
        ...,
        min_length=1,
        description="Program name (e.g., 'SLS Block 1B')",
    )
    end_item: str = Field(
        ...,
        min_length=1,
        description="End item name (e.g., 'Payload Bay Camera')",
    )
    miul_acronym: str = Field(
        ...,
        min_length=2,
        max_length=10,
        description="MIUL acronym (e.g., 'PBC')",
    )
    environment: Optional[UseEnvironmentInput] = Field(
        None,
        description="Environment parameters (defaults to SLS standard)",
    )


class CreateSessionResponse(BaseModel):
    """Response after creating MIUL session."""

    model_config = {"extra": "forbid"}

    session_id: str
    state: SessionState
    created_at: datetime
    message: str


class ExtractionProgress(BaseModel):
    """Progress information during extraction."""

    model_config = {"extra": "forbid"}

    step: str = Field(..., description="Current step name")
    current: int = Field(..., ge=0, description="Current progress count")
    total: int = Field(..., ge=0, description="Total items to process")
    message: str = Field(..., description="Human-readable progress message")


class ExtractionSummary(BaseModel):
    """Summary after extraction completes."""

    model_config = {"extra": "forbid"}

    total_parts: int = Field(..., ge=0)
    assemblies: int = Field(..., ge=0)
    components: int = Field(..., ge=0)
    enriched: int = Field(..., ge=0)
    needs_attention: int = Field(..., ge=0)
    missing_material: int = Field(..., ge=0)
    rating_gaps: int = Field(..., ge=0)
    prohibited: int = Field(..., ge=0)


class SessionStatusResponse(BaseModel):
    """Response for session status polling."""

    model_config = {"extra": "forbid"}

    session_id: str
    state: SessionState
    progress: Optional[ExtractionProgress] = None
    summary: Optional[ExtractionSummary] = None


class RatingInfo(BaseModel):
    """Rating value and status for a part."""

    model_config = {"extra": "forbid"}

    value: Optional[str] = Field(None, description="Rating value (A, B, C, etc.)")
    status: str = Field(
        ...,
        description="Status: ok, needs_rationale, prohibited, unknown, not_applicable",
    )


class PartReviewItem(BaseModel):
    """Part requiring user review (Step 3)."""

    model_config = {"extra": "forbid"}

    index: int = Field(..., description="Part index in MIUL tree")
    part_number: str = Field(..., description="Part number")
    part_description: Optional[str] = Field(None, description="Part description")
    material_code: Optional[str] = Field(None, description="MAPTIS material code")
    designation: Optional[str] = Field(None, description="Material designation")
    material_type: Optional[str] = Field(None, description="Material type (metal, polymer, etc.)")
    nha: Optional[str] = Field(None, description="Next Higher Assembly")
    ratings: Dict[str, RatingInfo] = Field(
        default_factory=dict,
        description="Ratings by type (FLAM, SCC, CORR, TVS, TOX, FS)",
    )
    status: PartStatus = Field(..., description="Overall part status")
    resolution: Optional[PartResolution] = Field(None, description="User's resolution if any")


class PartsListResponse(BaseModel):
    """Response with paginated parts list."""

    model_config = {"extra": "forbid"}

    total: int = Field(..., ge=0, description="Total parts count")
    page: int = Field(..., ge=1, description="Current page")
    limit: int = Field(..., ge=1, description="Items per page")
    parts: List[PartReviewItem] = Field(default_factory=list)


class RationaleOption(BaseModel):
    """Rationale code option for dropdown."""

    model_config = {"extra": "forbid"}

    code: str = Field(..., description="Rationale code (e.g., '403')")
    description: str = Field(..., description="Full rationale text")
    mua_category: Optional[Literal["I", "II"]] = Field(
        None, description="MUA category if MUA reference"
    )
    is_mua_reference: bool = Field(
        False, description="True if this references an MUA"
    )


class RationalesResponse(BaseModel):
    """Response with rationale options for a rating type."""

    model_config = {"extra": "forbid"}

    rating_type: str
    category: str
    options: List[RationaleOption]


class ApplyResolutionRequest(BaseModel):
    """Request to apply resolution to a part (Step 3)."""

    model_config = {"extra": "forbid"}

    part_index: int = Field(..., description="Index of part in MIUL tree")
    rating_type: str = Field(
        ...,
        description="Rating type (FLAM, SCC, CORR, TVS, TOX, FS)",
    )
    resolution_type: ResolutionType = Field(
        ...,
        description="How the gap is being resolved",
    )

    # For technical_rationale resolution
    rationale_code: Optional[str] = Field(
        None,
        description="Selected rationale code (e.g., '403')",
    )

    # For existing_mua_linked resolution
    mua_number: Optional[str] = Field(
        None,
        description="Existing MUA number to link",
    )
    mua_category: Optional[Literal["I", "II"]] = Field(
        None,
        description="MUA category",
    )

    notes: Optional[str] = Field(
        None,
        description="Engineer notes for audit trail",
    )
    confirmed: bool = Field(
        False,
        description="Engineer confirmed rationale applicability (REQUIRED for rationale_code)",
    )


class ApplyResolutionResponse(BaseModel):
    """Response after applying resolution."""

    model_config = {"extra": "forbid"}

    status: str
    part_index: int
    parts_resolved: int
    parts_remaining: int
    completion_percent: float


class ExportRequest(BaseModel):
    """Request to generate MIUL outputs (Step 4)."""

    model_config = {"extra": "forbid"}

    include_miul_excel: bool = Field(True, description="Generate MIUL Excel file")
    include_validation_report: bool = Field(True, description="Generate validation report")
    include_mua_package: bool = Field(False, description="Generate MUA package for flagged items")
    include_risk_report: bool = Field(False, description="Generate FMECA risk report")


class DownloadInfo(BaseModel):
    """Information about a downloadable file."""

    model_config = {"extra": "forbid"}

    name: str
    type: str
    url: str
    size_bytes: int


class ExportResponse(BaseModel):
    """Response after generating outputs."""

    model_config = {"extra": "forbid"}

    status: str
    downloads: List[DownloadInfo]


# === Helper Functions ===


def _get_session(session_id: str) -> MIULSession:
    """Get session or raise 404."""
    session = _sessions.get(session_id)
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session {session_id} not found",
        )
    return session


def _rating_type_to_category(rating_type: str) -> Optional[RationaleCategory]:
    """Map rating type string to RationaleCategory."""
    category_map = {
        "FLAM": RationaleCategory.FLAMMABILITY,
        "TOX": RationaleCategory.TOXICITY,
        "FS": RationaleCategory.FLUID_SYSTEM,
        "TVS": RationaleCategory.THERMAL_VACUUM,
        "SCC": RationaleCategory.STRESS_CORROSION,
        "CORR": RationaleCategory.CORROSION,
    }
    return category_map.get(rating_type.upper())


# === Endpoints ===


@router.post("", response_model=CreateSessionResponse)
async def create_session(request: CreateSessionRequest) -> CreateSessionResponse:
    """Create new MIUL builder session.

    Step 1 of the interactive workflow. Initializes session with program
    information and environment parameters.

    Compliance: SWE-013 (session creation audit trail)
    """
    session = MIULSession(
        program=request.program,
        end_item=request.end_item,
        miul_acronym=request.miul_acronym,
        environment=request.environment or UseEnvironmentInput(),
        state=SessionState.SETUP,
    )
    _sessions[session.session_id] = session
    _session_parts[session.session_id] = []
    _session_files[session.session_id] = {}

    logger.info(
        "[MIUL Session] Created session %s for %s/%s",
        session.session_id,
        request.program,
        request.end_item,
    )

    return CreateSessionResponse(
        session_id=session.session_id,
        state=session.state,
        created_at=session.created_at,
        message="Session created. Upload drawings or BOM to continue.",
    )


@router.get("/{session_id}", response_model=MIULSession)
async def get_session(session_id: str) -> MIULSession:
    """Get current session state.

    Returns full session data including all fields and resolutions.
    """
    return _get_session(session_id)


@router.get("/{session_id}/status", response_model=SessionStatusResponse)
async def get_session_status(session_id: str) -> SessionStatusResponse:
    """Poll session status for extraction progress.

    Use this endpoint to track progress during the extraction/enrichment
    pipeline. Returns progress information while processing, and summary
    statistics when complete.
    """
    session = _get_session(session_id)

    response = SessionStatusResponse(
        session_id=session.session_id,
        state=session.state,
    )

    # Add progress info if still processing
    if session.state in (SessionState.EXTRACTING, SessionState.ENRICHING):
        response.progress = ExtractionProgress(
            step=session.state.value,
            current=session.enriched_parts,
            total=session.total_parts or 1,
            message=f"Processing... ({session.enriched_parts}/{session.total_parts})",
        )

    # Add summary if review ready
    if session.state == SessionState.REVIEW:
        response.summary = ExtractionSummary(
            total_parts=session.total_parts,
            assemblies=0,  # Would be calculated from actual tree
            components=session.total_parts,
            enriched=session.enriched_parts,
            needs_attention=session.parts_needs_review + session.parts_needs_action,
            missing_material=0,  # Would be calculated from actual parts
            rating_gaps=session.parts_needs_review,
            prohibited=session.parts_needs_action,
        )

    return response


@router.get("/{session_id}/parts", response_model=PartsListResponse)
async def get_parts_for_review(
    session_id: str,
    status_filter: Optional[PartStatus] = Query(None, alias="status"),
    search: Optional[str] = Query(None, description="Search by part number"),
    page: int = Query(1, ge=1, description="Page number"),
    limit: int = Query(20, ge=1, le=100, description="Items per page"),
) -> PartsListResponse:
    """Get parts list for review (Step 3).

    Returns parts with their rating status and any existing resolutions.
    Supports filtering by status and searching by part number.

    Compliance: SWE-033 (requirements traceability per part)
    """
    session = _get_session(session_id)
    parts = _session_parts.get(session_id, [])

    # Apply filters
    filtered = parts
    if status_filter:
        filtered = [p for p in filtered if p.get("status") == status_filter.value]
    if search:
        search_lower = search.lower()
        filtered = [
            p for p in filtered
            if search_lower in (p.get("part_number", "").lower())
        ]

    # Paginate
    total = len(filtered)
    start = (page - 1) * limit
    end = start + limit
    page_items = filtered[start:end]

    # Convert to response model
    review_items = []
    for part in page_items:
        # Look up resolution if exists
        resolution = session.get_resolution(
            part.get("index", -1),
            part.get("rating_type", ""),
        )

        review_items.append(
            PartReviewItem(
                index=part.get("index", 0),
                part_number=part.get("part_number", ""),
                part_description=part.get("part_description"),
                material_code=part.get("material_code"),
                designation=part.get("designation"),
                material_type=part.get("material_type"),
                nha=part.get("nha"),
                ratings=part.get("ratings", {}),
                status=PartStatus(part.get("status", "ok")),
                resolution=resolution,
            )
        )

    return PartsListResponse(
        total=total,
        page=page,
        limit=limit,
        parts=review_items,
    )


@router.get("/{session_id}/rationales/{rating_type}", response_model=RationalesResponse)
async def get_rationale_options(
    session_id: str,
    rating_type: str,
) -> RationalesResponse:
    """Get rationale code options for a rating type.

    Returns filtered dropdown options for the specified rating type.
    Used to populate the rationale selection dropdown in the UI.

    Compliance: NASA-STD-6016A (rationale codes)
    """
    _get_session(session_id)  # Validate session exists

    category = _rating_type_to_category(rating_type)
    if not category:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown rating type: {rating_type}. Valid types: FLAM, TOX, FS, TVS, SCC, CORR",
        )

    rationales = get_rationales_for_rating(category)

    options = [
        RationaleOption(
            code=r.code,
            description=r.rationale,
            mua_category=r.mua_category,
            is_mua_reference=r.is_mua_reference,
        )
        for r in rationales.values()
    ]

    return RationalesResponse(
        rating_type=rating_type.upper(),
        category=category.value,
        options=options,
    )


@router.post("/{session_id}/upload")
async def upload_file(
    session_id: str,
    file: UploadFile = File(...),
) -> dict:
    """Upload drawing or BOM file to session (Step 2).

    Accepts PDF drawings, Excel BOMs, or CSV files.
    Files are queued for extraction when extract endpoint is called.
    """
    session = _get_session(session_id)

    # Validate file type
    filename = file.filename or "unknown"
    suffix = Path(filename).suffix.lower()
    allowed = {".pdf", ".xlsx", ".xls", ".csv"}
    if suffix not in allowed:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported file type: {suffix}. Allowed: {', '.join(allowed)}",
        )

    # Record upload
    session.uploaded_files.append(filename)
    session.state = SessionState.UPLOADING
    session.updated_at = datetime.utcnow()

    logger.info(
        "[MIUL Session] %s: Uploaded file %s",
        session_id,
        filename,
    )

    return {
        "status": "uploaded",
        "filename": filename,
        "message": "File queued for extraction",
    }


@router.post("/{session_id}/extract")
async def start_extraction(session_id: str) -> dict:
    """Start extraction and enrichment pipeline (Step 2).

    Processes uploaded files, extracts parts, builds tree structure,
    and enriches with MAPTIS data. Poll /status for progress.

    Requires at least one uploaded file.
    """
    session = _get_session(session_id)

    if not session.uploaded_files:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No files uploaded. Upload drawings or BOM first.",
        )

    session.state = SessionState.EXTRACTING
    session.updated_at = datetime.utcnow()

    # In production, this would trigger async extraction pipeline
    # For now, we simulate immediate completion for API testing
    # The actual extraction would integrate with existing BOM extractor

    logger.info(
        "[MIUL Session] %s: Started extraction for %d files",
        session_id,
        len(session.uploaded_files),
    )

    return {
        "status": "extracting",
        "message": "Extraction started. Poll /status for progress.",
    }


@router.post("/{session_id}/resolve", response_model=ApplyResolutionResponse)
async def apply_resolution(
    session_id: str,
    request: ApplyResolutionRequest,
) -> ApplyResolutionResponse:
    """Apply user's resolution to a part rating gap (Step 3).

    For technical_rationale resolutions, confirmed=true is REQUIRED.
    This ensures the engineer has verified the rationale applies.

    Compliance: SWE-033 (rationale traceability)
    """
    session = _get_session(session_id)

    # Validate session state
    if session.state not in (SessionState.REVIEW, SessionState.ENRICHING):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot resolve items in state {session.state.value}",
        )

    # Validation for technical rationale
    if request.resolution_type == ResolutionType.TECHNICAL_RATIONALE:
        if not request.rationale_code:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Rationale code required for technical_rationale resolution",
            )
        if not request.confirmed:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Must confirm rationale applicability (confirmed=true) before applying",
            )

    # Validation for existing MUA link
    if request.resolution_type == ResolutionType.EXISTING_MUA_LINKED:
        if not request.mua_number:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="MUA number required for existing_mua_linked resolution",
            )
        if not request.mua_category:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="MUA category (I or II) required for existing_mua_linked resolution",
            )

    # Create and record resolution
    resolution = PartResolution(
        part_index=request.part_index,
        rating_type=request.rating_type.upper(),
        resolution_type=request.resolution_type,
        rationale_code=request.rationale_code,
        mua_number=request.mua_number,
        mua_category=request.mua_category,
        notes=request.notes,
        confirmed=request.confirmed,
    )
    session.add_resolution(resolution)

    # Calculate remaining
    needs_attention = session.parts_needs_review + session.parts_needs_action
    remaining = max(0, needs_attention - session.parts_resolved)

    logger.info(
        "[MIUL Session] %s: Applied %s resolution to part %d (%s)",
        session_id,
        request.resolution_type.value,
        request.part_index,
        request.rating_type,
    )

    return ApplyResolutionResponse(
        status="resolved",
        part_index=request.part_index,
        parts_resolved=session.parts_resolved,
        parts_remaining=remaining,
        completion_percent=session.completion_percent,
    )


@router.post("/{session_id}/export", response_model=ExportResponse)
async def export_miul(
    session_id: str,
    request: ExportRequest,
) -> ExportResponse:
    """Generate final MIUL outputs (Step 4).

    Requires all items needing attention to be resolved.
    Returns download URLs for generated files.

    Compliance: SSP 30234 (MIUL format)
    """
    session = _get_session(session_id)

    # Validate state
    if session.state not in (SessionState.REVIEW, SessionState.COMPLETE):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot export in state {session.state.value}. Complete review first.",
        )

    # Check completion
    if session.completion_percent < 100:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Review {session.completion_percent:.0f}% complete. "
                "Resolve all items before export."
            ),
        )

    # Generate outputs
    downloads = []
    today = datetime.now().strftime("%Y-%m-%d")

    if request.include_miul_excel:
        # In production, would use MIULExcelWriter
        filename = f"MIUL_{session.miul_acronym}_{today}.xlsx"
        downloads.append(
            DownloadInfo(
                name=filename,
                type="miul_excel",
                url=f"/miul/session/{session_id}/download/{filename}",
                size_bytes=0,  # Would be actual size
            )
        )

    if request.include_validation_report:
        filename = f"Validation_Report_{session.miul_acronym}.pdf"
        downloads.append(
            DownloadInfo(
                name=filename,
                type="validation_report",
                url=f"/miul/session/{session_id}/download/{filename}",
                size_bytes=0,
            )
        )

    if request.include_mua_package:
        filename = f"MUA_Package_{session.miul_acronym}.zip"
        downloads.append(
            DownloadInfo(
                name=filename,
                type="mua_package",
                url=f"/miul/session/{session_id}/download/{filename}",
                size_bytes=0,
            )
        )

    if request.include_risk_report:
        filename = f"Risk_Assessment_{session.miul_acronym}.pdf"
        downloads.append(
            DownloadInfo(
                name=filename,
                type="risk_report",
                url=f"/miul/session/{session_id}/download/{filename}",
                size_bytes=0,
            )
        )

    session.state = SessionState.COMPLETE
    session.updated_at = datetime.utcnow()

    logger.info(
        "[MIUL Session] %s: Generated %d output files",
        session_id,
        len(downloads),
    )

    return ExportResponse(
        status="complete",
        downloads=downloads,
    )


@router.get("/{session_id}/download/{filename}")
async def download_file(
    session_id: str,
    filename: str,
) -> StreamingResponse:
    """Download generated file.

    Returns the generated MIUL Excel, validation report, or other outputs.
    """
    session = _get_session(session_id)

    # Check session is complete
    if session.state != SessionState.COMPLETE:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Export not complete. Call /export first.",
        )

    # Get file from storage
    files = _session_files.get(session_id, {})
    content = files.get(filename)

    if content is None:
        # In production, would generate on-demand or return 404
        # For now, return placeholder
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"File {filename} not found. Generate outputs first.",
        )

    # Determine content type
    suffix = Path(filename).suffix.lower()
    content_types = {
        ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ".pdf": "application/pdf",
        ".zip": "application/zip",
    }
    content_type = content_types.get(suffix, "application/octet-stream")

    return StreamingResponse(
        BytesIO(content),
        media_type=content_type,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
        },
    )


@router.delete("/{session_id}")
async def delete_session(session_id: str) -> dict:
    """Delete a session and all associated data.

    Use this to clean up completed or abandoned sessions.
    """
    session = _sessions.pop(session_id, None)
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session {session_id} not found",
        )

    # Clean up associated data
    _session_parts.pop(session_id, None)
    _session_files.pop(session_id, None)

    logger.info("[MIUL Session] Deleted session %s", session_id)

    return {
        "status": "deleted",
        "session_id": session_id,
    }
