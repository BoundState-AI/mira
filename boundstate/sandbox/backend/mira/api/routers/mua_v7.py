"""MUA v7 API Router.

FastAPI router for the NASA Material Usage Agreement (MUA) v7 generation
pipeline.  Implements a five-step wizard workflow:

    Step 1 -- Resolve Material   (POST /resolve-material)
    Step 2 -- Investigate        (POST /investigate)
    Step 3 -- Review Decisions   (POST /review-decisions)
    Step 4 -- Generate Draft     (POST /generate-draft)
    Step 5 -- Finalize           (POST /finalize)

Plus session management (GET/DELETE), a qualification-plan generator for
novel materials, and a usage-analytics endpoint.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from mira.mua.v7.models import (
    CategoryRoutingResult,
    Center,
    EvidenceStrengthBand,
    FinalizedMUA,
    InvestigationResult,
    MUADraft,
    ReviewDecisions,
    SessionStatus,
    StepName,
    # Request / Response models
    ResolveMaterialRequest,
    ResolveMaterialResponse,
    InvestigateRequest,
    InvestigateResponse,
    SaveReviewRequest,
    SaveReviewResponse,
    GenerateDraftRequest,
    GenerateDraftResponse,
    FinalizeRequest,
    FinalizeResponse,
    QualificationPlanRequest,
    QualificationPlanResponse,
)
from mira.mua.v7.material_resolver import resolve_material
from mira.mua.v7.session import SessionManager
from mira.mua.v7.investigator import MUAInvestigator
from mira.mua.v7.draft_renderer import DraftRenderer
from mira.mua.v7.fact_checker import FactChecker
from mira.mua.v7.category_router import CategoryRouter
from mira.mua.v7.qualification_plan import QualificationPlanGenerator

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

router = APIRouter(prefix="/api/mua/v7", tags=["MUA v7"])

# ---------------------------------------------------------------------------
# Module-level service instances
# ---------------------------------------------------------------------------

session_manager = SessionManager()
investigator = MUAInvestigator()
draft_renderer = DraftRenderer()
fact_checker = FactChecker()
category_router = CategoryRouter()
qualification_plan_generator = QualificationPlanGenerator()

# ---------------------------------------------------------------------------
# Router-local response models (not part of the core domain model layer)
# ---------------------------------------------------------------------------


class SessionSummary(BaseModel):
    """Lightweight session summary returned by the list endpoint.

    Omits bulky investigation data and draft content to keep the
    response compact for dashboard views.
    """

    session_id: str
    current_step: StepName
    status: SessionStatus
    material_input: Optional[str] = None
    center: Optional[Center] = None
    created_by: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class SessionListResponse(BaseModel):
    """Response for the session list endpoint."""

    sessions: list[SessionSummary]
    total: int


class SessionDetailResponse(BaseModel):
    """Full session state for the resume endpoint."""

    session_id: str
    current_step: StepName
    status: SessionStatus
    material_input: Optional[str] = None
    center: Optional[Center] = None
    created_by: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    investigation: Optional[InvestigationResult] = None
    review_decisions: Optional[ReviewDecisions] = None
    draft: Optional[MUADraft] = None
    finalized_mua: Optional[FinalizedMUA] = None


class DeleteSessionResponse(BaseModel):
    """Confirmation that a session was abandoned."""

    session_id: str
    status: SessionStatus


class StatsResponse(BaseModel):
    """Usage analytics response."""

    total_sessions: int = 0
    sessions_by_status: dict[str, int] = Field(default_factory=dict)
    avg_completion_time_seconds: Optional[float] = None
    sessions_finalized_last_30d: int = 0
    most_common_materials: list[dict] = Field(default_factory=list)
    most_common_centers: list[dict] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Step 1: Resolve Material
# ---------------------------------------------------------------------------


@router.post(
    "/resolve-material",
    response_model=ResolveMaterialResponse,
    summary="Step 1: Resolve a free-text material string",
)
async def resolve_material_endpoint(
    request: ResolveMaterialRequest,
) -> ResolveMaterialResponse:
    """Resolve a free-text material designation to a canonical MAPTIS record.

    Attempts exact match, alias resolution, AMS/AISI/UNS spec lookup, and
    fuzzy matching in that order.  Returns a ``MaterialResolution`` with
    status (RESOLVED / FUZZY / UNRESOLVED) and any suggestions.
    """
    logger.info("Step 1 -- resolve-material: input='%s'", request.material)

    try:
        resolution = resolve_material(request.material)
    except Exception:
        logger.exception(
            "Unexpected error resolving material '%s'", request.material
        )
        raise HTTPException(
            status_code=500,
            detail="Internal error during material resolution.",
        )

    logger.info(
        "Step 1 -- resolve-material: status=%s, code=%s",
        resolution.status,
        resolution.material_code,
    )
    return ResolveMaterialResponse(resolution=resolution)


# ---------------------------------------------------------------------------
# Step 2: Investigate
# ---------------------------------------------------------------------------


@router.post(
    "/investigate",
    response_model=InvestigateResponse,
    summary="Step 2: Full evidence gathering",
)
async def investigate_endpoint(
    request: InvestigateRequest,
) -> InvestigateResponse:
    """Run the full investigation pipeline for a material/environment pair.

    Gathers precedent MUAs, MAPTIS test data, performs envelope overlap
    analysis, identifies gaps and conflicts, and calculates preliminary
    evidence strength and category routing.

    The session must exist and be at the DEFINE or INVESTIGATE step.
    """
    logger.info(
        "Step 2 -- investigate: session_id=%s, material='%s', center=%s",
        request.session_id,
        request.material,
        request.center,
    )

    # Validate session state.
    session = session_manager.get_session(request.session_id)
    if session is None:
        raise HTTPException(
            status_code=404,
            detail=f"Session '{request.session_id}' not found.",
        )

    current_step = session_manager.get_current_step(request.session_id)
    if current_step not in (StepName.DEFINE, StepName.INVESTIGATE):
        raise HTTPException(
            status_code=400,
            detail=(
                f"Session is at step '{current_step}'. "
                f"Investigation requires DEFINE or INVESTIGATE step."
            ),
        )

    # Run the investigation.
    try:
        investigation_result: InvestigationResult = investigator.investigate(
            material=request.material,
            environment=request.environment,
            process_params=request.process_params,
            center=request.center,
        )
    except Exception:
        logger.exception(
            "Investigation failed for session '%s'", request.session_id
        )
        raise HTTPException(
            status_code=500,
            detail="Internal error during investigation.",
        )

    # Store results and advance step.
    session_manager.store_investigation(
        request.session_id, investigation_result
    )
    session_manager.advance_step(request.session_id, StepName.INVESTIGATE)

    logger.info(
        "Step 2 -- investigate: completed for session '%s'. "
        "precedents=%d supporting + %d conflicting, gaps=%d, conflicts=%d, "
        "strength=%s",
        request.session_id,
        len(investigation_result.supporting_precedents),
        len(investigation_result.conflicting_precedents),
        len(investigation_result.gaps),
        len(investigation_result.conflicts),
        investigation_result.evidence_strength.band,
    )

    return InvestigateResponse(
        session_id=request.session_id,
        investigation=investigation_result,
    )


# ---------------------------------------------------------------------------
# Step 3: Review Decisions
# ---------------------------------------------------------------------------


@router.post(
    "/review-decisions",
    response_model=SaveReviewResponse,
    summary="Step 3: Save engineer review decisions",
)
async def review_decisions_endpoint(
    request: SaveReviewRequest,
) -> SaveReviewResponse:
    """Save the reviewing engineer's decisions on precedents, gaps, and conflicts.

    Validates that all flagged items have been addressed (completion gate)
    and silently detects divergence when the engineer's selections oppose
    the evidence strength band determined during investigation.
    """
    logger.info(
        "Step 3 -- review-decisions: session_id=%s", request.session_id
    )

    # Validate session state.
    session = session_manager.get_session(request.session_id)
    if session is None:
        raise HTTPException(
            status_code=404,
            detail=f"Session '{request.session_id}' not found.",
        )

    current_step = session_manager.get_current_step(request.session_id)
    if current_step not in (StepName.INVESTIGATE, StepName.REVIEW):
        raise HTTPException(
            status_code=400,
            detail=(
                f"Session is at step '{current_step}'. "
                f"Review requires INVESTIGATE or REVIEW step."
            ),
        )

    # Retrieve the investigation to validate completeness.
    investigation = session_manager.get_investigation(request.session_id)
    if investigation is None:
        raise HTTPException(
            status_code=400,
            detail="No investigation found for this session. Run Step 2 first.",
        )

    # --- Completion gate: all flagged items must have decisions ---
    decisions = request.decisions

    # Count required items from the investigation.
    total_precedents = len(investigation.supporting_precedents) + len(
        investigation.conflicting_precedents
    )
    total_gaps = len(
        [g for g in investigation.gaps if g.requires_review]
    )
    total_conflicts = len(investigation.conflicts)

    reviewed_precedent_ids = {
        d.mua_number for d in decisions.precedent_decisions
    }
    reviewed_gap_ids = {d.gap_id for d in decisions.gap_decisions}
    reviewed_conflict_ids = {
        d.conflict_id for d in decisions.conflict_decisions
    }

    # Count how many items are still unreviewed.
    all_precedent_ids = {
        p.mua_number for p in investigation.supporting_precedents
    } | {p.mua_number for p in investigation.conflicting_precedents}
    all_gap_ids = {
        g.gap_id for g in investigation.gaps if g.requires_review
    }
    all_conflict_ids = {c.conflict_id for c in investigation.conflicts}

    unreviewed_precedents = all_precedent_ids - reviewed_precedent_ids
    unreviewed_gaps = all_gap_ids - reviewed_gap_ids
    unreviewed_conflicts = all_conflict_ids - reviewed_conflict_ids

    unreviewed_count = (
        len(unreviewed_precedents)
        + len(unreviewed_gaps)
        + len(unreviewed_conflicts)
    )

    all_items_reviewed = unreviewed_count == 0
    decisions.all_items_reviewed = all_items_reviewed

    # --- Divergence detection ---
    # Divergence occurs when the engineer's aggregate decision direction
    # (mostly EXCLUDE on supporting precedents, or mostly INCLUDE on
    # conflicting ones) opposes the investigation's evidence strength band.
    evidence_band = investigation.evidence_strength.band
    divergence_detected = _detect_divergence(
        decisions, investigation, evidence_band
    )
    decisions.divergence_detected = divergence_detected

    if divergence_detected:
        decisions.divergence_rationale = (
            "Engineer review selections diverge from the "
            f"'{evidence_band}' evidence strength band. "
            "This divergence has been recorded in the audit trail."
        )
        logger.warning(
            "Step 3 -- divergence detected in session '%s': "
            "band=%s, engineer decisions diverge.",
            request.session_id,
            evidence_band,
        )

    # Store decisions and advance step.
    session_manager.store_review_decisions(request.session_id, decisions)
    session_manager.advance_step(request.session_id, StepName.REVIEW)

    can_generate_draft = all_items_reviewed

    logger.info(
        "Step 3 -- review-decisions: session '%s' saved. "
        "all_reviewed=%s, divergence=%s, unreviewed=%d",
        request.session_id,
        all_items_reviewed,
        divergence_detected,
        unreviewed_count,
    )

    return SaveReviewResponse(
        session_id=request.session_id,
        can_generate_draft=can_generate_draft,
        unreviewed_count=unreviewed_count,
    )


# ---------------------------------------------------------------------------
# Step 4: Generate Draft
# ---------------------------------------------------------------------------


@router.post(
    "/generate-draft",
    response_model=GenerateDraftResponse,
    summary="Step 4: Generate MUA document draft",
)
async def generate_draft_endpoint(
    request: GenerateDraftRequest,
) -> GenerateDraftResponse:
    """Generate the MUA document draft from reviewed evidence.

    Routes the material to a NASA MUA category (I / II / III), renders
    the document sections, and runs fact-checking against cited evidence.

    Requires all flagged items to have been reviewed in Step 3.
    """
    logger.info(
        "Step 4 -- generate-draft: session_id=%s", request.session_id
    )

    # Validate session state.
    session = session_manager.get_session(request.session_id)
    if session is None:
        raise HTTPException(
            status_code=404,
            detail=f"Session '{request.session_id}' not found.",
        )

    current_step = session_manager.get_current_step(request.session_id)
    if current_step != StepName.REVIEW:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Session is at step '{current_step}'. "
                f"Draft generation requires REVIEW step."
            ),
        )

    # All items must be reviewed before draft generation.
    review_decisions = session_manager.get_review_decisions(request.session_id)
    if review_decisions is None:
        raise HTTPException(
            status_code=400,
            detail="No review decisions found. Complete Step 3 first.",
        )

    if not review_decisions.all_items_reviewed:
        raise HTTPException(
            status_code=400,
            detail=(
                "Not all flagged items have been reviewed. "
                "Complete all review decisions before generating a draft."
            ),
        )

    investigation = session_manager.get_investigation(request.session_id)
    if investigation is None:
        raise HTTPException(
            status_code=400,
            detail="No investigation found for this session.",
        )

    # Step 4a: Route to MUA category.
    try:
        routing_result: CategoryRoutingResult = category_router.route(
            investigation=investigation,
            review_decisions=review_decisions,
        )
    except Exception:
        logger.exception(
            "Category routing failed for session '%s'", request.session_id
        )
        raise HTTPException(
            status_code=500,
            detail="Internal error during category routing.",
        )

    # Step 4b: Render the draft document.
    try:
        draft: MUADraft = draft_renderer.render(
            investigation=investigation,
            review_decisions=review_decisions,
            routing_result=routing_result,
        )
    except Exception:
        logger.exception(
            "Draft rendering failed for session '%s'", request.session_id
        )
        raise HTTPException(
            status_code=500,
            detail="Internal error during draft rendering.",
        )

    # Step 4c: Fact-check the draft.
    try:
        fact_check_results = fact_checker.check_draft(
            draft=draft,
            investigation=investigation,
        )
        draft.fact_check_results = fact_check_results
    except Exception:
        logger.exception(
            "Fact-checking failed for session '%s'", request.session_id
        )
        raise HTTPException(
            status_code=500,
            detail="Internal error during fact-checking.",
        )

    # Store draft and advance step.
    session_manager.store_draft(request.session_id, draft)
    session_manager.advance_step(request.session_id, StepName.DRAFT)
    session_manager.update_status(
        request.session_id, SessionStatus.DRAFT_SAVED
    )

    logger.info(
        "Step 4 -- generate-draft: session '%s' draft generated. "
        "category=%s, sections=%d, fact_checks=%d",
        request.session_id,
        draft.category,
        len(draft.sections),
        len(draft.fact_check_results),
    )

    return GenerateDraftResponse(
        session_id=request.session_id,
        draft=draft,
    )


# ---------------------------------------------------------------------------
# Step 5: Finalize
# ---------------------------------------------------------------------------


@router.post(
    "/finalize",
    response_model=FinalizeResponse,
    summary="Step 5: Lock and export the MUA",
)
async def finalize_endpoint(
    request: FinalizeRequest,
) -> FinalizeResponse:
    """Finalize the MUA: lock the document, record the reviewer, build the
    audit trail, and optionally generate export text.

    Once finalized, the session is immutable and cannot be modified.
    """
    logger.info(
        "Step 5 -- finalize: session_id=%s, reviewer='%s', format='%s'",
        request.session_id,
        request.reviewer,
        request.export_format,
    )

    # Validate session state.
    session = session_manager.get_session(request.session_id)
    if session is None:
        raise HTTPException(
            status_code=404,
            detail=f"Session '{request.session_id}' not found.",
        )

    current_step = session_manager.get_current_step(request.session_id)
    if current_step != StepName.DRAFT:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Session is at step '{current_step}'. "
                f"Finalization requires DRAFT step."
            ),
        )

    # Gather all session artifacts.
    investigation = session_manager.get_investigation(request.session_id)
    review_decisions = session_manager.get_review_decisions(request.session_id)
    draft = session_manager.get_draft(request.session_id)

    if investigation is None or review_decisions is None or draft is None:
        raise HTTPException(
            status_code=400,
            detail="Session is missing required artifacts for finalization.",
        )

    # Build the audit trail.
    finalized_at = datetime.utcnow()
    audit_trail = _build_audit_trail(
        session_id=request.session_id,
        investigation=investigation,
        review_decisions=review_decisions,
        draft=draft,
        reviewer=request.reviewer,
        finalized_at=finalized_at,
    )

    # Determine the routing result from the draft category.
    routing_result = CategoryRoutingResult(category=draft.category)

    # Construct the finalized MUA.
    finalized_mua = FinalizedMUA(
        session_id=request.session_id,
        mua_id=draft.mua_id,
        material=investigation.material,
        environment=investigation.environment,
        category=routing_result,
        evidence_strength=investigation.evidence_strength,
        draft=draft,
        reviewer=request.reviewer,
        finalized_at=finalized_at,
        applied_standard_version="NASA-STD-6016C",
        dependency_links=[
            w.cited_mua for w in investigation.dependency_warnings
        ],
        center=investigation.material.material_code
        and Center.MSFC
        or Center.MSFC,
        audit_trail=audit_trail,
    )

    # Generate export text if requested.
    export_text: Optional[str] = None
    if request.export_format:
        try:
            export_text = _generate_export_text(
                finalized_mua, request.export_format
            )
        except Exception:
            logger.exception(
                "Export text generation failed for session '%s'",
                request.session_id,
            )
            raise HTTPException(
                status_code=500,
                detail="Internal error generating export text.",
            )

    # Advance step and mark session as finalized.
    session_manager.store_finalized_mua(request.session_id, finalized_mua)
    session_manager.advance_step(request.session_id, StepName.FINALIZE)
    session_manager.update_status(
        request.session_id, SessionStatus.FINALIZED
    )

    logger.info(
        "Step 5 -- finalize: session '%s' finalized by '%s' at %s.",
        request.session_id,
        request.reviewer,
        finalized_at.isoformat(),
    )

    return FinalizeResponse(
        session_id=request.session_id,
        mua=finalized_mua,
        export_text=export_text,
    )


# ---------------------------------------------------------------------------
# Session CRUD
# ---------------------------------------------------------------------------


@router.get(
    "/session/{session_id}",
    response_model=SessionDetailResponse,
    summary="Resume a session",
)
async def get_session_endpoint(session_id: str) -> SessionDetailResponse:
    """Retrieve full session state for resuming an in-progress MUA workflow."""
    logger.info("GET session: session_id=%s", session_id)

    session = session_manager.get_session(session_id)
    if session is None:
        raise HTTPException(
            status_code=404,
            detail=f"Session '{session_id}' not found.",
        )

    return SessionDetailResponse(
        session_id=session_id,
        current_step=session_manager.get_current_step(session_id),
        status=session_manager.get_status(session_id),
        material_input=session_manager.get_material_input(session_id),
        center=session_manager.get_center(session_id),
        created_by=session_manager.get_created_by(session_id),
        created_at=session_manager.get_created_at(session_id),
        updated_at=session_manager.get_updated_at(session_id),
        investigation=session_manager.get_investigation(session_id),
        review_decisions=session_manager.get_review_decisions(session_id),
        draft=session_manager.get_draft(session_id),
        finalized_mua=session_manager.get_finalized_mua(session_id),
    )


@router.get(
    "/sessions",
    response_model=SessionListResponse,
    summary="List user sessions",
)
async def list_sessions_endpoint(
    created_by: Optional[str] = Query(
        default=None, description="Filter by session creator"
    ),
    status: Optional[SessionStatus] = Query(
        default=None, description="Filter by session status"
    ),
) -> SessionListResponse:
    """List MUA sessions, optionally filtered by creator and/or status.

    Returns lightweight summaries without full investigation data.
    """
    logger.info(
        "GET sessions: created_by=%s, status=%s", created_by, status
    )

    try:
        sessions = session_manager.list_sessions(
            created_by=created_by, status=status
        )
    except Exception:
        logger.exception("Failed to list sessions")
        raise HTTPException(
            status_code=500,
            detail="Internal error listing sessions.",
        )

    summaries = [
        SessionSummary(
            session_id=s.session_id,
            current_step=s.current_step,
            status=s.status,
            material_input=getattr(s, "material_input", None),
            center=getattr(s, "center", None),
            created_by=getattr(s, "created_by", None),
            created_at=getattr(s, "created_at", None),
            updated_at=getattr(s, "updated_at", None),
        )
        for s in sessions
    ]

    return SessionListResponse(sessions=summaries, total=len(summaries))


@router.delete(
    "/session/{session_id}",
    response_model=DeleteSessionResponse,
    summary="Abandon a session",
)
async def delete_session_endpoint(
    session_id: str,
) -> DeleteSessionResponse:
    """Mark a session as ABANDONED.

    Abandoned sessions are retained for audit purposes but cannot be
    resumed or modified further.
    """
    logger.info("DELETE session: session_id=%s", session_id)

    session = session_manager.get_session(session_id)
    if session is None:
        raise HTTPException(
            status_code=404,
            detail=f"Session '{session_id}' not found.",
        )

    current_status = session_manager.get_status(session_id)
    if current_status == SessionStatus.FINALIZED:
        raise HTTPException(
            status_code=400,
            detail="Cannot abandon a finalized session.",
        )

    if current_status == SessionStatus.ABANDONED:
        raise HTTPException(
            status_code=400,
            detail="Session is already abandoned.",
        )

    session_manager.update_status(session_id, SessionStatus.ABANDONED)

    logger.info("Session '%s' marked as ABANDONED.", session_id)

    return DeleteSessionResponse(
        session_id=session_id,
        status=SessionStatus.ABANDONED,
    )


# ---------------------------------------------------------------------------
# Qualification Plan (novel materials)
# ---------------------------------------------------------------------------


@router.post(
    "/qualification-plan",
    response_model=QualificationPlanResponse,
    summary="Generate qualification test plan for a novel material",
)
async def qualification_plan_endpoint(
    request: QualificationPlanRequest,
) -> QualificationPlanResponse:
    """Generate a qualification test plan for a novel material that has
    zero precedents in the MUA corpus.

    Returns recommended tests, conditions, applicable standards, and a
    human-readable output plan.
    """
    logger.info(
        "qualification-plan: material='%s'", request.material
    )

    try:
        plan = qualification_plan_generator.generate(
            material=request.material,
            environment=request.environment,
        )
    except Exception:
        logger.exception(
            "Qualification plan generation failed for material '%s'",
            request.material,
        )
        raise HTTPException(
            status_code=500,
            detail="Internal error generating qualification plan.",
        )

    logger.info(
        "qualification-plan: generated for '%s'. tests=%d, standards=%d",
        request.material,
        len(plan.required_tests),
        len(plan.applicable_standards),
    )

    return plan


# ---------------------------------------------------------------------------
# Stats / Analytics
# ---------------------------------------------------------------------------


@router.get(
    "/stats",
    response_model=StatsResponse,
    summary="Usage analytics",
)
async def stats_endpoint() -> StatsResponse:
    """Return aggregate usage analytics for the MUA v7 pipeline.

    Includes session counts by status, average completion time,
    most commonly queried materials, and center distribution.
    """
    logger.info("GET stats")

    try:
        raw_stats = session_manager.get_stats()
    except Exception:
        logger.exception("Failed to retrieve stats")
        raise HTTPException(
            status_code=500,
            detail="Internal error retrieving analytics.",
        )

    return StatsResponse(
        total_sessions=raw_stats.get("total_sessions", 0),
        sessions_by_status=raw_stats.get("sessions_by_status", {}),
        avg_completion_time_seconds=raw_stats.get(
            "avg_completion_time_seconds"
        ),
        sessions_finalized_last_30d=raw_stats.get(
            "sessions_finalized_last_30d", 0
        ),
        most_common_materials=raw_stats.get("most_common_materials", []),
        most_common_centers=raw_stats.get("most_common_centers", []),
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _detect_divergence(
    decisions: ReviewDecisions,
    investigation: InvestigationResult,
    evidence_band: EvidenceStrengthBand,
) -> bool:
    """Detect whether the engineer's review decisions diverge from the
    evidence strength band.

    Divergence is flagged when:
    - The evidence band is STRONG or MODERATE but the engineer excludes
      a majority of supporting precedents.
    - The evidence band is WEAK or INSUFFICIENT but the engineer includes
      a majority of conflicting precedents as supporting.

    This is a silent annotation for the audit trail -- it does NOT block
    the workflow.

    Args:
        decisions: The engineer's review selections.
        investigation: The investigation result containing the evidence.
        evidence_band: The computed evidence strength band.

    Returns:
        True if divergence is detected, False otherwise.
    """
    from mira.mua.v7.models import ReviewDecisionType

    if not decisions.precedent_decisions:
        return False

    # Build lookup of decisions by MUA number.
    decision_map = {
        d.mua_number: d.decision for d in decisions.precedent_decisions
    }

    # Count how supporting precedents were treated.
    supporting_mua_numbers = {
        p.mua_number for p in investigation.supporting_precedents
    }
    excluded_supporting = sum(
        1
        for mua_num, dec in decision_map.items()
        if mua_num in supporting_mua_numbers
        and dec == ReviewDecisionType.EXCLUDE
    )
    total_supporting_reviewed = sum(
        1
        for mua_num in decision_map
        if mua_num in supporting_mua_numbers
    )

    # Count how conflicting precedents were treated.
    conflicting_mua_numbers = {
        p.mua_number for p in investigation.conflicting_precedents
    }
    included_conflicting = sum(
        1
        for mua_num, dec in decision_map.items()
        if mua_num in conflicting_mua_numbers
        and dec == ReviewDecisionType.INCLUDE_SUPPORTING
    )
    total_conflicting_reviewed = sum(
        1
        for mua_num in decision_map
        if mua_num in conflicting_mua_numbers
    )

    # Check for divergence based on evidence band.
    if evidence_band in (
        EvidenceStrengthBand.STRONG,
        EvidenceStrengthBand.MODERATE,
    ):
        # Strong/moderate evidence but engineer excludes majority of support.
        if (
            total_supporting_reviewed > 0
            and excluded_supporting > total_supporting_reviewed / 2
        ):
            return True

    if evidence_band in (
        EvidenceStrengthBand.WEAK,
        EvidenceStrengthBand.INSUFFICIENT,
    ):
        # Weak/insufficient evidence but engineer includes conflicts as support.
        if (
            total_conflicting_reviewed > 0
            and included_conflicting > total_conflicting_reviewed / 2
        ):
            return True

    return False


def _build_audit_trail(
    *,
    session_id: str,
    investigation: InvestigationResult,
    review_decisions: ReviewDecisions,
    draft: MUADraft,
    reviewer: str,
    finalized_at: datetime,
) -> dict:
    """Build a structured audit trail dictionary for the finalized MUA.

    Captures key decision points, evidence statistics, and divergence
    information for post-hoc review.

    Args:
        session_id: The session identifier.
        investigation: The investigation result.
        review_decisions: The engineer's review decisions.
        draft: The generated draft.
        reviewer: Reviewer identifier.
        finalized_at: Timestamp of finalization.

    Returns:
        A dictionary containing the audit trail.
    """
    return {
        "session_id": session_id,
        "finalized_at": finalized_at.isoformat(),
        "reviewer": reviewer,
        "evidence_summary": {
            "supporting_precedents": len(
                investigation.supporting_precedents
            ),
            "conflicting_precedents": len(
                investigation.conflicting_precedents
            ),
            "test_records": len(investigation.test_data),
            "gaps_identified": len(investigation.gaps),
            "conflicts_identified": len(investigation.conflicts),
            "evidence_strength_band": investigation.evidence_strength.band,
            "evidence_strength_score": investigation.evidence_strength.score,
            "is_novel_material": investigation.is_novel_material,
        },
        "review_summary": {
            "precedent_decisions": len(
                review_decisions.precedent_decisions
            ),
            "gap_decisions": len(review_decisions.gap_decisions),
            "conflict_decisions": len(
                review_decisions.conflict_decisions
            ),
            "all_items_reviewed": review_decisions.all_items_reviewed,
            "divergence_detected": review_decisions.divergence_detected,
            "divergence_rationale": review_decisions.divergence_rationale,
        },
        "draft_summary": {
            "mua_id": draft.mua_id,
            "category": draft.category,
            "sections_count": len(draft.sections),
            "fact_checks_total": len(draft.fact_check_results),
            "fact_checks_verified": sum(
                1
                for fc in draft.fact_check_results
                if fc.status == "verified"
            ),
            "fact_checks_judgment": sum(
                1
                for fc in draft.fact_check_results
                if fc.status == "judgment"
            ),
            "fact_checks_unverified": sum(
                1
                for fc in draft.fact_check_results
                if fc.status == "unverified"
            ),
            "cited_precedents": draft.cited_precedents,
        },
        "banners": investigation.banners,
        "dependency_warnings": [
            {
                "cited_mua": w.cited_mua,
                "depends_on": w.depends_on,
                "warning": w.warning,
            }
            for w in investigation.dependency_warnings
        ],
    }


def _generate_export_text(
    finalized_mua: FinalizedMUA,
    export_format: str,
) -> str:
    """Generate a plain-text export of the finalized MUA.

    Args:
        finalized_mua: The finalized MUA record.
        export_format: The requested format (currently only "text" supported).

    Returns:
        A formatted text export of the MUA.

    Raises:
        ValueError: If the export format is not supported.
    """
    if export_format != "text":
        raise ValueError(f"Unsupported export format: '{export_format}'")

    lines: list[str] = []
    lines.append("=" * 72)
    lines.append("NASA MATERIAL USAGE AGREEMENT (MUA)")
    lines.append("=" * 72)
    lines.append("")
    lines.append(f"MUA ID:             {finalized_mua.mua_id}")
    lines.append(f"Session ID:         {finalized_mua.session_id}")
    lines.append(f"Material:           {finalized_mua.material.input_text}")

    if finalized_mua.material.material_code:
        lines.append(
            f"MAPTIS Code:        {finalized_mua.material.material_code}"
        )

    lines.append(f"Category:           {finalized_mua.category.category}")
    lines.append(
        f"Evidence Strength:  {finalized_mua.evidence_strength.band} "
        f"({finalized_mua.evidence_strength.score:.2f})"
    )
    lines.append(f"Center:             {finalized_mua.center}")
    lines.append(
        f"Applied Standard:   {finalized_mua.applied_standard_version}"
    )
    lines.append(f"Reviewer:           {finalized_mua.reviewer}")
    lines.append(
        f"Finalized:          {finalized_mua.finalized_at.isoformat()}"
    )
    lines.append("")
    lines.append("-" * 72)
    lines.append("ENVIRONMENT")
    lines.append("-" * 72)
    env = finalized_mua.environment
    lines.append(f"Medium:             {env.medium}")
    lines.append(f"O2 Percent:         {env.o2_percent}%")
    lines.append(f"Pressure:           {env.pressure_psia} psia")
    lines.append(
        f"Temperature Range:  {env.temp_min_f} degF to {env.temp_max_f} degF"
    )
    lines.append(f"Location:           {env.location}")
    lines.append(f"Application:        {env.application}")
    lines.append("")

    # Document sections.
    for section in finalized_mua.draft.sections:
        lines.append("-" * 72)
        lines.append(
            f"Section {section.section_number}: {section.title}"
        )
        lines.append("-" * 72)
        lines.append(section.content)
        lines.append("")

    # Dependency links.
    if finalized_mua.dependency_links:
        lines.append("-" * 72)
        lines.append("DEPENDENCY LINKS")
        lines.append("-" * 72)
        for link in finalized_mua.dependency_links:
            lines.append(f"  - {link}")
        lines.append("")

    lines.append("=" * 72)
    lines.append("END OF DOCUMENT")
    lines.append("=" * 72)

    return "\n".join(lines)
