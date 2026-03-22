#!/usr/bin/env python3
"""
Module: M&P Plan API Router
Purpose: REST API endpoints for M&P Plan Generator V2

BoundState AI 2026
Version: 2.0.0
Classification: BoundState Proprietary

API Endpoints:
- Session Management: Create, get, delete sessions
- Data Entry: Add environments, materials
- Compute Loop: Run compute, get questions, submit answers
- Generation: Generate artifacts, download files

Compliance: NASA-STD-8739.8B, SWE-013, SWE-033
Safety Critical: False
"""

from __future__ import annotations

import logging
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Any, Optional

import math

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, field_validator

from mira.api.auth import authorize_owner_or_admin, get_request_user

# Lazy imports to avoid circular dependencies
SessionManager = None
get_session_manager = None

LOGGER = logging.getLogger(__name__)

router = APIRouter()

__version__ = "2.0.0"
__safety_critical__ = False


# -----------------------------------------------------------------------------
# Dependency injection with lazy loading
# -----------------------------------------------------------------------------


def _get_manager():
    """Dependency injection for session manager (lazy load)."""
    global SessionManager, get_session_manager
    if get_session_manager is None:
        from mira.mp_plan.session_manager import (
            SessionManager as _SessionManager,
            get_session_manager as _get_session_manager,
        )
        SessionManager = _SessionManager
        get_session_manager = _get_session_manager
    return get_session_manager()


def _require_session_for_request(
    session_id: str,
    http_request: Request,
    manager: Any,
):
    session = manager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")
    authorize_owner_or_admin(http_request, session.owner_username, resource_label="mp plan session")
    return session


# -----------------------------------------------------------------------------
# Request/Response Models
# -----------------------------------------------------------------------------


class CreateSessionRequest(BaseModel):
    """Request to create a new session."""

    program_name: Optional[str] = None
    program_phase: Optional[str] = None
    policy_pack_id: Optional[str] = None
    vehicle_preset: Optional[str] = None

    model_config = {"extra": "forbid"}


class SessionResponse(BaseModel):
    """Session summary response."""

    session_id: str
    program_name: Optional[str] = None
    created_at: str
    updated_at: str
    material_count: int = 0
    environment_count: int = 0
    nonconformance_count: int = 0
    blocking_question_count: int = 0
    can_generate: bool = False
    blockers: list[str] = Field(default_factory=list)

    model_config = {"extra": "forbid"}


class AddEnvironmentRequest(BaseModel):
    """Request to add an environment."""

    name: str
    o2_pct: float = Field(..., gt=0, le=100)
    pressure_psia: float = Field(..., gt=0)
    temp_min_c: float
    temp_max_c: float
    habitable: bool
    vacuum_exposure: bool = False
    lunar_dust: bool = False

    model_config = {"extra": "forbid"}

    @field_validator("o2_pct", "pressure_psia", "temp_min_c", "temp_max_c", mode="before")
    @classmethod
    def validate_finite(cls, v: float) -> float:
        """Ensure float values are finite (not NaN or infinity)."""
        if v is None:
            return v
        if not isinstance(v, (int, float)):
            raise ValueError("Value must be a number")
        if math.isnan(v) or math.isinf(v):
            raise ValueError("Value must be finite (not NaN or infinity)")
        return v


class AddMaterialRequest(BaseModel):
    """Request to add a material."""

    name: str
    application: str
    quantity: int = Field(default=1, ge=1, le=2147483647)
    maptis_code: Optional[str] = None
    mass_g: Optional[float] = None
    surface_area_cm2: Optional[float] = None

    model_config = {"extra": "forbid"}


class AddMaterialsBatchRequest(BaseModel):
    """Request to add multiple materials."""

    materials: list[AddMaterialRequest]

    model_config = {"extra": "forbid"}


class SubmitAnswerRequest(BaseModel):
    """Request to submit an answer to a blocking question."""

    question_id: str
    answer: str
    rationale: str = ""

    model_config = {"extra": "forbid"}


class ClosureDecisionRequest(BaseModel):
    """Request to submit a closure decision."""

    gap_id: str
    selected_path: str
    rationale: str
    provided_inputs: dict[str, Any] = Field(default_factory=dict)

    model_config = {"extra": "forbid"}


class AcceptOpenGapRequest(BaseModel):
    """Request to accept a gap as open."""

    gap_id: str
    rationale: str
    owner: str
    due_date: Optional[str] = None
    risk_statement: str = ""

    model_config = {"extra": "forbid"}


class GenerateRequest(BaseModel):
    """Request to generate artifacts."""

    artifacts: list[str] = Field(
        default_factory=lambda: ["mp_plan_docx", "miul_xlsx", "review_packet"]
    )

    model_config = {"extra": "forbid"}


# -----------------------------------------------------------------------------
# Health Check
# -----------------------------------------------------------------------------


@router.get("/ping")
async def ping() -> dict:
    """Health check for M&P Plan endpoint."""
    return {"status": "ok", "domain": "mp_plan", "version": __version__}


# -----------------------------------------------------------------------------
# Session Management
# -----------------------------------------------------------------------------


@router.post("/sessions", response_model=SessionResponse)
async def create_session(
    request: CreateSessionRequest,
    http_request: Request,
    manager=Depends(_get_manager),
) -> SessionResponse:
    """
    Create a new M&P Plan session.

    Args:
        request: Session creation parameters.
        manager: Injected session manager.

    Returns:
        Session summary.
    """
    actor = get_request_user(http_request)
    session = manager.create_session(
        program_name=request.program_name,
        program_phase=request.program_phase,
        policy_pack_id=request.policy_pack_id,
        vehicle_preset=request.vehicle_preset,
        owner_username=actor.username if actor else None,
    )

    can_generate, blockers = session.can_generate()

    return SessionResponse(
        session_id=session.session_id,
        program_name=session.program_name,
        created_at=session.created_at.isoformat(),
        updated_at=session.updated_at.isoformat(),
        material_count=len(session.materials),
        environment_count=len(session.environments),
        nonconformance_count=len(session.nonconformances),
        blocking_question_count=len(session.blocking_questions),
        can_generate=can_generate,
        blockers=blockers,
    )


@router.get("/sessions/{session_id}")
async def get_session(
    session_id: str,
    http_request: Request,
    manager=Depends(_get_manager),
) -> dict:
    """
    Get session state.

    Args:
        session_id: Session identifier.
        manager: Injected session manager.

    Returns:
        Full session state.
    """
    session = _require_session_for_request(session_id, http_request, manager)
    return session.model_dump()


@router.delete("/sessions/{session_id}")
async def delete_session(
    session_id: str,
    http_request: Request,
    manager=Depends(_get_manager),
) -> dict:
    """
    Delete a session.

    Args:
        session_id: Session identifier.
        manager: Injected session manager.

    Returns:
        Deletion confirmation.
    """
    session = manager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")

    authorize_owner_or_admin(http_request, session.owner_username, resource_label="mp plan session")

    if manager.delete_session(session_id):
        return {"status": "deleted", "session_id": session_id}
    raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")


@router.get("/sessions")
async def list_sessions(
    http_request: Request,
    manager=Depends(_get_manager),
) -> dict:
    """
    List all sessions.

    Args:
        manager: Injected session manager.

    Returns:
        List of session summaries.
    """
    summaries = manager.list_sessions()
    actor = get_request_user(http_request)
    if actor is not None and not actor.is_admin:
        actor_name = (actor.username or actor.email or "").strip().lower()
        filtered: list[dict[str, Any]] = []
        for summary in summaries:
            session = manager.get_session(summary["session_id"])
            if session and (session.owner_username or "").strip().lower() == actor_name:
                filtered.append(summary)
        summaries = filtered
    return {"sessions": summaries, "count": len(summaries)}


# -----------------------------------------------------------------------------
# Data Entry
# -----------------------------------------------------------------------------


@router.post("/sessions/{session_id}/environment")
async def add_environment(
    session_id: str,
    request: AddEnvironmentRequest,
    http_request: Request,
    manager=Depends(_get_manager),
) -> dict:
    """
    Add an environment to a session.

    Args:
        session_id: Session identifier.
        request: Environment parameters.
        manager: Injected session manager.

    Returns:
        Created environment.
    """
    _require_session_for_request(session_id, http_request, manager)
    env = manager.add_environment(
        session_id=session_id,
        name=request.name,
        o2_pct=request.o2_pct,
        pressure_psia=request.pressure_psia,
        temp_range_c=(request.temp_min_c, request.temp_max_c),
        habitable=request.habitable,
        vacuum_exposure=request.vacuum_exposure,
        lunar_dust=request.lunar_dust,
    )

    if not env:
        raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")

    return env.model_dump()


@router.post("/sessions/{session_id}/materials")
async def add_materials(
    session_id: str,
    request: AddMaterialsBatchRequest,
    http_request: Request,
    manager=Depends(_get_manager),
) -> dict:
    """
    Add materials to a session (batch).

    Args:
        session_id: Session identifier.
        request: Materials to add.
        manager: Injected session manager.

    Returns:
        Created materials.
    """
    _require_session_for_request(session_id, http_request, manager)
    created = []
    for mat_req in request.materials:
        material = manager.add_material(
            session_id=session_id,
            name=mat_req.name,
            application=mat_req.application,
            quantity=mat_req.quantity,
            maptis_code=mat_req.maptis_code,
            mass_g=mat_req.mass_g,
            surface_area_cm2=mat_req.surface_area_cm2,
        )
        if material:
            created.append(material.model_dump())

    if not created:
        raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")

    return {"materials": created, "count": len(created)}


@router.post("/sessions/{session_id}/resolve")
async def resolve_materials(
    session_id: str,
    http_request: Request,
    manager=Depends(_get_manager),
) -> dict:
    """
    Resolve materials to MAPTIS data.

    Args:
        session_id: Session identifier.
        manager: Injected session manager.

    Returns:
        Resolution results.
    """
    from mira.mp_plan.engines import DataAcquisitionEngine

    session = _require_session_for_request(session_id, http_request, manager)

    engine = DataAcquisitionEngine()
    try:
        resolutions, deficiencies, mappings = engine.run(session)
        manager.update_session(session)

        return {
            "resolved": len(resolutions),
            "deficiencies": len(deficiencies),
            "mappings_created": len(mappings),
        }
    finally:
        engine.close()


# -----------------------------------------------------------------------------
# Compute Loop
# -----------------------------------------------------------------------------


@router.get("/sessions/{session_id}/questions")
async def get_blocking_questions(
    session_id: str,
    http_request: Request,
    manager=Depends(_get_manager),
) -> dict:
    """
    Get blocking questions for a session.

    Args:
        session_id: Session identifier.
        manager: Injected session manager.

    Returns:
        Blocking questions.
    """
    from mira.mp_plan.compute_loop import generate_blocking_questions

    session = _require_session_for_request(session_id, http_request, manager)

    questions = generate_blocking_questions(session)
    session.blocking_questions = questions
    manager.update_session(session)

    return {
        "questions": [q.model_dump() for q in questions],
        "count": len(questions),
    }


@router.post("/sessions/{session_id}/answer")
async def submit_answer(
    session_id: str,
    request: SubmitAnswerRequest,
    http_request: Request,
    manager=Depends(_get_manager),
) -> dict:
    """
    Submit an answer to a blocking question.

    Args:
        session_id: Session identifier.
        request: Answer submission.
        manager: Injected session manager.

    Returns:
        Updated session state.
    """
    from mira.mp_plan.compute_loop import apply_user_decision
    from mira.mp_plan.models import UserDecision

    session = _require_session_for_request(session_id, http_request, manager)

    # Find the question
    question = next(
        (q for q in session.blocking_questions if q.question_id == request.question_id),
        None,
    )
    if not question:
        raise HTTPException(
            status_code=404,
            detail=f"Question not found: {request.question_id}",
        )

    # Record decision
    decision = UserDecision(
        question_id=request.question_id,
        decision=request.answer,
        rationale=request.rationale,
        decided_by="api_user",
        source="api",
    )
    session.user_decisions.append(decision)

    # Apply decision
    apply_user_decision(session, question, request.answer, request.rationale)
    manager.update_session(session)

    can_generate, blockers = session.can_generate()

    return {
        "status": "applied",
        "can_generate": can_generate,
        "blockers": blockers,
    }


@router.post("/sessions/{session_id}/closure")
async def submit_closure(
    session_id: str,
    request: ClosureDecisionRequest,
    http_request: Request,
    manager=Depends(_get_manager),
) -> dict:
    """
    Submit a closure decision for a nonconformance.

    Args:
        session_id: Session identifier.
        request: Closure decision.
        manager: Injected session manager.

    Returns:
        Updated session state.
    """
    from mira.mp_plan.models import ClosureDecision

    session = _require_session_for_request(session_id, http_request, manager)

    # Verify gap exists
    nc = next(
        (n for n in session.nonconformances if n.nonconformance_id == request.gap_id),
        None,
    )
    if not nc:
        raise HTTPException(status_code=404, detail=f"Gap not found: {request.gap_id}")

    # Create closure decision
    closure = ClosureDecision(
        gap_id=request.gap_id,
        selected_path=request.selected_path,
        provided_inputs=request.provided_inputs,
        decision_rationale=request.rationale,
        decided_by="api_user",
        decided_at=datetime.now(),
        available_options=[],
        source="api",
    )
    session.closure_decisions.append(closure)
    manager.update_session(session)

    can_generate, blockers = session.can_generate()

    return {
        "status": "closure_recorded",
        "gap_id": request.gap_id,
        "selected_path": request.selected_path,
        "can_generate": can_generate,
        "blockers": blockers,
    }


@router.post("/sessions/{session_id}/accept-open")
async def accept_open_gap(
    session_id: str,
    request: AcceptOpenGapRequest,
    http_request: Request,
    manager=Depends(_get_manager),
) -> dict:
    """
    Accept a gap as open with tracking.

    Args:
        session_id: Session identifier.
        request: Acceptance parameters.
        manager: Injected session manager.

    Returns:
        Updated session state.
    """
    from datetime import date, timedelta
    from mira.mp_plan.models import AcceptedOpenGap

    session = _require_session_for_request(session_id, http_request, manager)

    # Verify gap exists
    nc = next(
        (n for n in session.nonconformances if n.nonconformance_id == request.gap_id),
        None,
    )
    if not nc:
        raise HTTPException(status_code=404, detail=f"Gap not found: {request.gap_id}")

    # Parse due date
    due_date = None
    if request.due_date:
        try:
            due_date = date.fromisoformat(request.due_date)
        except ValueError:
            due_date = date.today() + timedelta(days=30)
    else:
        due_date = date.today() + timedelta(days=30)

    # Create accepted gap record
    accepted = AcceptedOpenGap(
        gap_id=request.gap_id,
        gap_type="nonconformance",
        accepted_by="api_user",
        accepted_at=datetime.now(),
        acceptance_rationale=request.rationale,
        owner=request.owner,
        due_date=due_date,
        risk_statement=request.risk_statement,
    )
    session.accepted_open_gaps.append(accepted)
    manager.update_session(session)

    can_generate, blockers = session.can_generate()

    return {
        "status": "accepted_open",
        "gap_id": request.gap_id,
        "owner": request.owner,
        "due_date": due_date.isoformat(),
        "can_generate": can_generate,
        "blockers": blockers,
    }


@router.post("/sessions/{session_id}/compute")
async def run_compute(
    session_id: str,
    http_request: Request,
    manager=Depends(_get_manager),
) -> dict:
    """
    Run the full compute loop.

    This executes one iteration of the compute-question-recompute loop.
    Returns blocking questions if user input is required.

    Args:
        session_id: Session identifier.
        manager: Injected session manager.

    Returns:
        Compute results with any blocking questions.
    """
    from mira.mp_plan.compute_loop import run_compute_loop

    session = _require_session_for_request(session_id, http_request, manager)

    # Run compute loop (without callback - will return at first blocking question)
    session = run_compute_loop(session, max_iterations=1)
    manager.update_session(session)

    can_generate, blockers = session.can_generate()

    return {
        "status": "computed",
        "can_generate": can_generate,
        "blockers": blockers,
        "blocking_questions": [q.model_dump() for q in session.blocking_questions],
        "nonconformances": len(session.nonconformances),
        "deficiencies": len(session.deficiencies),
    }


# -----------------------------------------------------------------------------
# Generation
# -----------------------------------------------------------------------------


@router.post("/sessions/{session_id}/generate")
async def generate_artifacts(
    session_id: str,
    request: GenerateRequest,
    http_request: Request,
    manager=Depends(_get_manager),
) -> dict:
    """
    Generate artifacts for a session.

    Args:
        session_id: Session identifier.
        request: Generation parameters.
        manager: Injected session manager.

    Returns:
        Generation results with artifact IDs.
    """
    from mira.mp_plan.generation import (
        generate_mp_plan_docx,
        generate_miul_xlsx,
        generate_review_packet,
    )
    from mira.mp_plan.models import GeneratedArtifact, ArtifactType

    session = _require_session_for_request(session_id, http_request, manager)

    can_generate, blockers = session.can_generate()
    if not can_generate:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot generate: {', '.join(blockers)}",
        )

    generated = []

    for artifact_name in request.artifacts:
        try:
            if artifact_name == "mp_plan_docx":
                content = generate_mp_plan_docx(session)
                artifact = GeneratedArtifact(
                    artifact_type=ArtifactType.MP_PLAN,
                    format="docx",
                    content_bytes=content,
                    source="api_generation",
                )
                session.generated_artifacts.append(artifact)
                generated.append({
                    "name": artifact_name,
                    "artifact_id": artifact.artifact_id,
                    "format": "docx",
                    "size_bytes": len(content),
                })

            elif artifact_name == "miul_xlsx":
                content = generate_miul_xlsx(session)
                artifact = GeneratedArtifact(
                    artifact_type=ArtifactType.MIUL,
                    format="xlsx",
                    content_bytes=content,
                    source="api_generation",
                )
                session.generated_artifacts.append(artifact)
                generated.append({
                    "name": artifact_name,
                    "artifact_id": artifact.artifact_id,
                    "format": "xlsx",
                    "size_bytes": len(content),
                })

            elif artifact_name == "review_packet":
                packet = generate_review_packet(session)
                # Store as JSON
                content = packet.model_dump_json(indent=2).encode()
                artifact = GeneratedArtifact(
                    artifact_type=ArtifactType.REVIEW_PACKET,
                    format="json",
                    content_bytes=content,
                    source="api_generation",
                )
                session.generated_artifacts.append(artifact)
                generated.append({
                    "name": artifact_name,
                    "artifact_id": artifact.artifact_id,
                    "format": "json",
                    "size_bytes": len(content),
                })

        except Exception as e:
            LOGGER.error(f"Failed to generate {artifact_name}: {e}")
            generated.append({
                "name": artifact_name,
                "error": str(e),
            })

    manager.update_session(session)

    return {
        "status": "generated",
        "artifacts": generated,
    }


@router.get("/sessions/{session_id}/download/{artifact_id}")
async def download_artifact(
    session_id: str,
    artifact_id: str,
    http_request: Request,
    manager=Depends(_get_manager),
) -> StreamingResponse:
    """
    Download a generated artifact.

    Args:
        session_id: Session identifier.
        artifact_id: Artifact identifier.
        manager: Injected session manager.

    Returns:
        Artifact file stream.
    """
    session = _require_session_for_request(session_id, http_request, manager)

    # Find artifact
    artifact = next(
        (a for a in session.generated_artifacts if a.artifact_id == artifact_id),
        None,
    )
    if not artifact:
        raise HTTPException(status_code=404, detail=f"Artifact not found: {artifact_id}")

    # Determine content type and filename
    content_types = {
        "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "json": "application/json",
        "pdf": "application/pdf",
    }
    content_type = content_types.get(artifact.format, "application/octet-stream")

    filename = f"{artifact.artifact_type.value}_{session_id[:8]}.{artifact.format}"

    return StreamingResponse(
        iter([artifact.content_bytes]),
        media_type=content_type,
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@router.get("/sessions/{session_id}/review-packet")
async def get_review_packet(
    session_id: str,
    http_request: Request,
    manager=Depends(_get_manager),
) -> dict:
    """
    Get review packet for a session.

    Args:
        session_id: Session identifier.
        manager: Injected session manager.

    Returns:
        Review packet data.
    """
    from mira.mp_plan.generation import generate_review_packet

    session = _require_session_for_request(session_id, http_request, manager)

    packet = generate_review_packet(session)
    return packet.model_dump()


# -----------------------------------------------------------------------------
# Reference Data
# -----------------------------------------------------------------------------


@router.get("/policy-packs")
async def list_policy_packs() -> dict:
    """
    List available policy packs.

    Returns:
        Available policy packs.
    """
    from mira.mp_plan.policy import create_default_policy_pack

    default = create_default_policy_pack()

    return {
        "policy_packs": [
            {
                "policy_pack_id": default.policy_pack_id,
                "name": default.name,
                "version": default.version,
                "applicable_centers": default.applicable_centers,
                "applicable_programs": default.applicable_programs,
            }
        ],
    }


@router.get("/vehicle-presets")
async def list_vehicle_presets() -> dict:
    """
    List available vehicle environment presets.

    Returns:
        Available vehicle presets.
    """
    from mira.mp_plan.policy import create_default_policy_pack

    default = create_default_policy_pack()

    presets = []
    for name, config in default.vehicle_environments.items():
        presets.append({
            "preset_id": name,
            "name": config.get("name", name),
            "o2_pct": config.get("o2_pct"),
            "pressure_psia": config.get("pressure_psia"),
            "habitable": config.get("habitable"),
        })

    return {"presets": presets}


@router.get("/closure-paths")
async def list_closure_paths() -> dict:
    """
    List available closure paths.

    Returns information about all implemented closure paths
    and their requirements.

    Returns:
        Available closure paths.
    """
    from mira.mp_plan.gap_resolution import CLOSURE_PATH_REGISTRY

    paths = []
    for path_id, path_class in CLOSURE_PATH_REGISTRY.items():
        instance = path_class()
        paths.append({
            "path_id": path_id,
            "title": instance.path_title,
            "description": instance.path_description,
            "citation": instance.citation,
            "required_inputs": instance.required_inputs,
            "output_artifact": instance.output_artifact,
        })

    return {"closure_paths": paths, "count": len(paths)}


@router.get("/sessions/{session_id}/closure-options/{gap_id}")
async def get_closure_options(
    session_id: str,
    gap_id: str,
    http_request: Request,
    manager=Depends(_get_manager),
) -> dict:
    """
    Get closure path options for a specific gap.

    Evaluates all available closure paths and returns eligibility status
    for each one based on the current session state.

    Args:
        session_id: Session identifier.
        gap_id: Gap identifier.
        manager: Injected session manager.

    Returns:
        Available closure options with eligibility status.
    """
    from mira.mp_plan.gap_resolution import check_all_paths

    session = _require_session_for_request(session_id, http_request, manager)

    # Find the gap
    gap = next(
        (n for n in session.nonconformances if n.nonconformance_id == gap_id),
        None,
    )
    if not gap:
        raise HTTPException(status_code=404, detail=f"Gap not found: {gap_id}")

    # Find the material
    material = next(
        (m for m in session.materials if m.id == gap.material_id),
        None,
    )
    if not material:
        raise HTTPException(status_code=404, detail=f"Material not found for gap: {gap_id}")

    # Find the environment
    environment = next(
        (e for e in session.environments if e.environment_id == gap.environment_id),
        None,
    )
    if not environment:
        raise HTTPException(status_code=404, detail=f"Environment not found for gap: {gap_id}")

    # Check all closure paths
    results = check_all_paths(gap, material, environment, session)

    return {
        "gap_id": gap_id,
        "material_name": material.name,
        "environment_name": environment.name,
        "options": [r.model_dump() for r in results],
        "eligible_count": sum(1 for r in results if r.eligible),
        "total_count": len(results),
    }


@router.get("/sessions/{session_id}/applicability-matrix")
async def get_applicability_matrix(
    session_id: str,
    http_request: Request,
    manager=Depends(_get_manager),
) -> dict:
    """
    Get the applicability matrix for a session.

    Returns a matrix showing which MPRs apply to which materials
    in each environment.

    Args:
        session_id: Session identifier.
        manager: Injected session manager.

    Returns:
        Applicability matrix data.
    """
    session = _require_session_for_request(session_id, http_request, manager)

    # Build matrix from determinations
    matrix_rows = []
    for det in session.mpr_determinations:
        material = next(
            (m for m in session.materials if m.id == det.material_id),
            None,
        )
        environment = next(
            (e for e in session.environments if e.environment_id == det.environment_id),
            None,
        )

        matrix_rows.append({
            "material_id": det.material_id,
            "material_name": material.name if material else "Unknown",
            "environment_id": det.environment_id,
            "environment_name": environment.name if environment else "Unknown",
            "mpr_id": det.mpr_id,
            "mpr_title": det.mpr_title,
            "applicable": det.applicable,
            "rationale": det.rationale,
            "evidence": det.evidence.model_dump() if det.evidence else None,
        })

    # Group by material
    materials_summary = {}
    for row in matrix_rows:
        mat_id = row["material_id"]
        if mat_id not in materials_summary:
            materials_summary[mat_id] = {
                "material_name": row["material_name"],
                "total_mprs": 0,
                "applicable_mprs": 0,
            }
        materials_summary[mat_id]["total_mprs"] += 1
        if row["applicable"]:
            materials_summary[mat_id]["applicable_mprs"] += 1

    return {
        "session_id": session_id,
        "matrix": matrix_rows,
        "materials_summary": list(materials_summary.values()),
        "total_determinations": len(matrix_rows),
    }


@router.get("/sessions/{session_id}/gap-register")
async def get_gap_register(
    session_id: str,
    http_request: Request,
    manager=Depends(_get_manager),
) -> dict:
    """
    Get the gap register for a session.

    Returns all deficiencies and nonconformances with their
    current status and closure information.

    Args:
        session_id: Session identifier.
        manager: Injected session manager.

    Returns:
        Gap register data.
    """
    session = _require_session_for_request(session_id, http_request, manager)

    deficiencies = []
    for d in session.deficiencies:
        material = next(
            (m for m in session.materials if m.id == d.material_id),
            None,
        )
        deficiencies.append({
            "deficiency_id": d.deficiency_id,
            "material_id": d.material_id,
            "material_name": material.name if material else "Unknown",
            "field_name": d.field_name,
            "severity": d.severity.value if hasattr(d.severity, "value") else str(d.severity),
            "description": d.description,
            "resolved": d.resolved,
        })

    nonconformances = []
    for nc in session.nonconformances:
        material = next(
            (m for m in session.materials if m.id == nc.material_id),
            None,
        )
        environment = next(
            (e for e in session.environments if e.environment_id == nc.environment_id),
            None,
        )
        # Check if closure exists
        closure = next(
            (c for c in session.closure_decisions if c.gap_id == nc.nonconformance_id),
            None,
        )
        # Check if accepted open
        accepted = next(
            (a for a in session.accepted_open_gaps if a.gap_id == nc.nonconformance_id),
            None,
        )

        status = "open"
        if closure:
            status = f"closed:{closure.selected_path}"
        elif accepted:
            status = "accepted_open"

        nonconformances.append({
            "nonconformance_id": nc.nonconformance_id,
            "material_id": nc.material_id,
            "material_name": material.name if material else "Unknown",
            "environment_id": nc.environment_id,
            "environment_name": environment.name if environment else "Unknown",
            "gap_type": nc.gap_type.value if hasattr(nc.gap_type, "value") else str(nc.gap_type),
            "mpr_id": nc.mpr_id,
            "severity": nc.severity.value if hasattr(nc.severity, "value") else str(nc.severity),
            "description": nc.description,
            "status": status,
            "closure_path": closure.selected_path if closure else None,
        })

    return {
        "session_id": session_id,
        "deficiencies": deficiencies,
        "nonconformances": nonconformances,
        "deficiency_count": len(deficiencies),
        "nonconformance_count": len(nonconformances),
        "open_count": sum(1 for nc in nonconformances if nc["status"] == "open"),
        "closed_count": sum(1 for nc in nonconformances if nc["status"].startswith("closed")),
        "accepted_open_count": sum(1 for nc in nonconformances if nc["status"] == "accepted_open"),
    }


# -----------------------------------------------------------------------------
# Export Downloads
# -----------------------------------------------------------------------------


@router.get("/sessions/{session_id}/export/applicability-matrix")
async def download_applicability_matrix(
    session_id: str,
    http_request: Request,
    manager=Depends(_get_manager),
) -> StreamingResponse:
    """
    Download applicability matrix as Excel file.

    Args:
        session_id: Session identifier.
        manager: Injected session manager.

    Returns:
        Excel file stream.
    """
    from mira.mp_plan.generation import generate_applicability_matrix_xlsx

    session = _require_session_for_request(session_id, http_request, manager)

    content = generate_applicability_matrix_xlsx(session)
    filename = f"applicability_matrix_{session_id[:8]}.xlsx"

    return StreamingResponse(
        iter([content]),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@router.get("/sessions/{session_id}/export/gap-register")
async def download_gap_register(
    session_id: str,
    http_request: Request,
    manager=Depends(_get_manager),
) -> StreamingResponse:
    """
    Download gap register as Excel file.

    Args:
        session_id: Session identifier.
        manager: Injected session manager.

    Returns:
        Excel file stream.
    """
    from mira.mp_plan.generation import generate_gap_register_xlsx

    session = _require_session_for_request(session_id, http_request, manager)

    content = generate_gap_register_xlsx(session)
    filename = f"gap_register_{session_id[:8]}.xlsx"

    return StreamingResponse(
        iter([content]),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@router.get("/sessions/{session_id}/export/manifest")
async def download_manifest(
    session_id: str,
    http_request: Request,
    manager=Depends(_get_manager),
) -> StreamingResponse:
    """
    Download session manifest as JSON file.

    Args:
        session_id: Session identifier.
        manager: Injected session manager.

    Returns:
        JSON file stream.
    """
    from mira.mp_plan.generation import generate_manifest_json

    session = _require_session_for_request(session_id, http_request, manager)

    content = generate_manifest_json(session)
    filename = f"session_manifest_{session_id[:8]}.json"

    return StreamingResponse(
        iter([content]),
        media_type="application/json",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@router.get("/maptis-search")
async def search_maptis_codes(
    q: str = Query(..., min_length=2, description="Material name to search for"),
    limit: int = Query(5, ge=1, le=20, description="Maximum results"),
) -> dict:
    """
    Search MAPTIS for material codes by material name.

    This endpoint helps users find the correct MAPTIS code for their materials
    by searching the database using fuzzy matching and UNS normalization.

    Args:
        q: Material name to search (e.g., "kapton", "inconel 625", "316L")
        limit: Maximum number of results to return

    Returns:
        List of matching materials with codes and confidence scores.
    """
    try:
        from mira.miul.material_code_lookup import get_lookup_service

        service = get_lookup_service()
        matches = service.lookup_by_designation(q)

        results = []
        for match in matches[:limit]:
            results.append({
                "material_code": match.material_code,
                "designation": match.designation,
                "confidence": match.confidence,
                "method": match.method,
                "score": match.score,
            })

        return {
            "query": q,
            "results": results,
            "count": len(results),
        }

    except Exception as e:
        LOGGER.error(f"MAPTIS search error: {e}")
        # Return empty results rather than error - DB may not be available
        return {
            "query": q,
            "results": [],
            "count": 0,
            "error": "Material lookup service unavailable",
        }
