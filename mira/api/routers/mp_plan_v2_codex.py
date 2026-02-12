#!/usr/bin/env python3
"""
Module: M&P Plan API Router v2 (Codex)
Purpose: Versioned API for full-index, HITL-first M&P Plan generation
"""

from __future__ import annotations

import logging
import math
from datetime import date, datetime, timedelta
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, field_validator

from mira.mp_plan.compute_loop_codex import (
    apply_user_decision_codex,
    can_generate_codex,
    generate_blocking_questions_codex,
    run_compute_loop_codex,
)
from mira.mp_plan.generation.mp_plan_docx_codex import generate_mp_plan_docx_codex
from mira.mp_plan.generation.plan_json_codex import (
    generate_mp_plan_json_bytes_codex,
    generate_mp_plan_json_codex,
)
from mira.mp_plan.models import AcceptedOpenGap, ArtifactType, ClosureDecision, GeneratedArtifact, UserDecision

# Lazy imports to avoid circular dependencies
SessionManager = None
get_session_manager = None

LOGGER = logging.getLogger(__name__)

router = APIRouter()

__version__ = "2.1.0-codex"
__safety_critical__ = False


QUICK_ACTION_CATALOG = {
    "ADD_TEST_CITATION": {
        "label": "Add Test Citation",
        "description": "Attach test evidence covering the actual use conditions.",
    },
    "ADD_ANALYSIS_CITATION": {
        "label": "Add Analysis Citation",
        "description": "Attach signed engineering analysis tied to requirement text.",
    },
    "ADD_STANDARD_CITATION": {
        "label": "Add Standard Citation",
        "description": "Attach governing standard/spec + implementation evidence.",
    },
    "ROUTE_TO_CLOSURE": {
        "label": "Route To Closure",
        "description": "Treat unresolved item as closure-required and select path.",
    },
    "ACCEPT": {
        "label": "Accept",
        "description": "Accept determination as currently supported.",
    },
    "ACCEPT_WITH_CONSTRAINT": {
        "label": "Accept With Constraint",
        "description": "Accept conditional use and keep cited constraints.",
    },
    "FLAG_FOR_EDIT": {
        "label": "Flag For Edit",
        "description": "Mark for additional review/edit by the team.",
    },
    "NEEDS_TEST": {
        "label": "Needs Test",
        "description": "Request additional testing before final acceptance.",
    },
}


def _get_manager():
    global SessionManager, get_session_manager
    if get_session_manager is None:
        from mira.mp_plan.session_manager import (
            SessionManager as _SessionManager,
            get_session_manager as _get_session_manager,
        )

        SessionManager = _SessionManager
        get_session_manager = _get_session_manager
    return get_session_manager()


class CreateSessionRequest(BaseModel):
    program_name: Optional[str] = None
    program_phase: Optional[str] = None
    policy_pack_id: Optional[str] = None
    vehicle_preset: Optional[str] = None

    model_config = {"extra": "forbid"}


class AddEnvironmentRequest(BaseModel):
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
        if not isinstance(v, (int, float)) or math.isnan(v) or math.isinf(v):
            raise ValueError("Value must be finite")
        return v


class AddMaterialRequest(BaseModel):
    name: str
    application: str
    quantity: int = Field(default=1, ge=1, le=2147483647)
    maptis_code: Optional[str] = None
    mass_g: Optional[float] = None
    surface_area_cm2: Optional[float] = None

    model_config = {"extra": "forbid"}


class AddMaterialsBatchRequest(BaseModel):
    materials: list[AddMaterialRequest]

    model_config = {"extra": "forbid"}


class SubmitAnswerRequest(BaseModel):
    question_id: str
    answer: str
    rationale: str = ""

    model_config = {"extra": "forbid"}


class ClosureDecisionRequest(BaseModel):
    gap_id: str
    selected_path: str
    rationale: str
    provided_inputs: dict[str, Any] = Field(default_factory=dict)

    model_config = {"extra": "forbid"}


class AcceptOpenGapRequest(BaseModel):
    gap_id: str
    rationale: str
    owner: str
    due_date: Optional[str] = None
    risk_statement: str = ""

    model_config = {"extra": "forbid"}


class GenerateRequest(BaseModel):
    artifacts: list[str] = Field(default_factory=lambda: ["mp_plan_docx", "mp_plan_json"])

    model_config = {"extra": "forbid"}


@router.get("/ping")
async def ping() -> dict[str, Any]:
    return {"status": "ok", "domain": "mp_plan_v2_codex", "version": __version__}


@router.post("/sessions")
async def create_session(
    request: CreateSessionRequest,
    manager=Depends(_get_manager),
) -> dict[str, Any]:
    session = manager.create_session(
        program_name=request.program_name,
        program_phase=request.program_phase,
        policy_pack_id=request.policy_pack_id,
        vehicle_preset=request.vehicle_preset,
    )
    manager.update_session(session)
    return {
        "session_id": session.session_id,
        "program_name": session.program_name,
        "created_at": session.created_at.isoformat(),
        "updated_at": session.updated_at.isoformat(),
    }


@router.get("/sessions/{session_id}")
async def get_session(session_id: str, manager=Depends(_get_manager)) -> dict[str, Any]:
    session = manager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")
    return session.model_dump()


@router.get("/sessions")
async def list_sessions(manager=Depends(_get_manager)) -> dict[str, Any]:
    sessions = manager.list_sessions()
    return {"sessions": sessions, "count": len(sessions)}


@router.delete("/sessions/{session_id}")
async def delete_session(session_id: str, manager=Depends(_get_manager)) -> dict[str, Any]:
    if not manager.delete_session(session_id):
        raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")
    return {"status": "deleted", "session_id": session_id}


@router.post("/sessions/{session_id}/environment")
async def add_environment(
    session_id: str,
    request: AddEnvironmentRequest,
    manager=Depends(_get_manager),
) -> dict[str, Any]:
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
    manager=Depends(_get_manager),
) -> dict[str, Any]:
    session = manager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")

    created = []
    for item in request.materials:
        material = manager.add_material(
            session_id=session_id,
            name=item.name,
            application=item.application,
            quantity=item.quantity,
            maptis_code=item.maptis_code,
            mass_g=item.mass_g,
            surface_area_cm2=item.surface_area_cm2,
        )
        if material:
            created.append(material.model_dump())

    return {"materials": created, "count": len(created)}


@router.post("/sessions/{session_id}/compute")
async def run_compute(session_id: str, manager=Depends(_get_manager)) -> dict[str, Any]:
    session = manager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")

    session = run_compute_loop_codex(session, max_iterations=1)
    manager.update_session(session)

    can_generate, blockers = can_generate_codex(session)
    hitl_required = sum(1 for d in session.mpr_determinations if d.get("hitl_required"))
    return {
        "status": "computed",
        "can_generate": can_generate,
        "blockers": blockers,
        "materials": len(session.materials),
        "environments": len(session.environments),
        "determinations": len(session.mpr_determinations),
        "deficiencies": len(session.deficiencies),
        "nonconformances": len(session.nonconformances),
        "hitl_required": hitl_required,
        "blocking_questions": [q.model_dump() for q in session.blocking_questions],
    }


@router.get("/sessions/{session_id}/questions")
async def get_blocking_questions(session_id: str, manager=Depends(_get_manager)) -> dict[str, Any]:
    session = manager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")

    session.blocking_questions = generate_blocking_questions_codex(session)
    manager.update_session(session)
    return {
        "questions": [q.model_dump() for q in session.blocking_questions],
        "count": len(session.blocking_questions),
    }


@router.get("/sessions/{session_id}/citation-helper/{determination_id}")
async def get_citation_helper(
    session_id: str,
    determination_id: str,
    manager=Depends(_get_manager),
) -> dict[str, Any]:
    """
    Return one-click citation helper payload for a determination.
    """
    session = manager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")

    det = next(
        (d for d in session.mpr_determinations if d.get("determination_id") == determination_id),
        None,
    )
    if not det:
        raise HTTPException(
            status_code=404,
            detail=f"Determination not found: {determination_id}",
        )

    helper = det.get("citation_helper") or {}
    actions = []
    for token in helper.get("quick_actions", []):
        info = QUICK_ACTION_CATALOG.get(token, {"label": token, "description": ""})
        actions.append(
            {
                "action_token": token,
                "label": info["label"],
                "description": info["description"],
            }
        )

    return {
        "session_id": session_id,
        "determination_id": determination_id,
        "mpr_id": det.get("mpr_id"),
        "mpr_title": det.get("mpr_title"),
        "mpr_section": det.get("mpr_section"),
        "status": det.get("status"),
        "human_meaning": det.get("human_meaning"),
        "human_action": det.get("human_action"),
        "citation_helper": helper,
        "quick_actions": actions,
    }


@router.post("/sessions/{session_id}/answer")
async def submit_answer(
    session_id: str,
    request: SubmitAnswerRequest,
    manager=Depends(_get_manager),
) -> dict[str, Any]:
    session = manager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")

    question = next(
        (q for q in session.blocking_questions if q.question_id == request.question_id),
        None,
    )
    if not question:
        raise HTTPException(status_code=404, detail=f"Question not found: {request.question_id}")

    session.user_decisions.append(
        UserDecision(
            question_id=request.question_id,
            decision=request.answer,
            rationale=request.rationale,
            decided_by="api_user",
            source="api",
        )
    )
    apply_user_decision_codex(session, question, request.answer, request.rationale)
    session = run_compute_loop_codex(session, max_iterations=1)
    manager.update_session(session)

    can_generate, blockers = can_generate_codex(session)
    return {
        "status": "applied",
        "can_generate": can_generate,
        "blockers": blockers,
        "remaining_questions": len(session.blocking_questions),
    }


@router.post("/sessions/{session_id}/closure")
async def submit_closure(
    session_id: str,
    request: ClosureDecisionRequest,
    manager=Depends(_get_manager),
) -> dict[str, Any]:
    session = manager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")

    nc = next((n for n in session.nonconformances if n.nonconformance_id == request.gap_id), None)
    if not nc:
        raise HTTPException(status_code=404, detail=f"Gap not found: {request.gap_id}")

    session.closure_decisions.append(
        ClosureDecision(
            gap_id=request.gap_id,
            selected_path=request.selected_path.upper(),
            provided_inputs=request.provided_inputs,
            decision_rationale=request.rationale,
            decided_by="api_user",
            decided_at=datetime.now(),
            available_options=[],
            source="api",
        )
    )
    manager.update_session(session)
    can_generate, blockers = can_generate_codex(session)
    return {
        "status": "closure_recorded",
        "gap_id": request.gap_id,
        "can_generate": can_generate,
        "blockers": blockers,
    }


@router.post("/sessions/{session_id}/accept-open")
async def accept_open_gap(
    session_id: str,
    request: AcceptOpenGapRequest,
    manager=Depends(_get_manager),
) -> dict[str, Any]:
    session = manager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")

    nc = next((n for n in session.nonconformances if n.nonconformance_id == request.gap_id), None)
    if not nc:
        raise HTTPException(status_code=404, detail=f"Gap not found: {request.gap_id}")

    if request.due_date:
        try:
            due_date = date.fromisoformat(request.due_date)
        except ValueError:
            due_date = date.today() + timedelta(days=30)
    else:
        due_date = date.today() + timedelta(days=30)

    session.accepted_open_gaps.append(
        AcceptedOpenGap(
            gap_id=request.gap_id,
            gap_type="nonconformance",
            accepted_by="api_user",
            acceptance_rationale=request.rationale,
            owner=request.owner,
            due_date=due_date,
            risk_statement=request.risk_statement or "Risk accepted pending closure package.",
        )
    )
    manager.update_session(session)
    can_generate, blockers = can_generate_codex(session)
    return {
        "status": "accepted_open",
        "gap_id": request.gap_id,
        "owner": request.owner,
        "due_date": due_date.isoformat(),
        "can_generate": can_generate,
        "blockers": blockers,
    }


@router.post("/sessions/{session_id}/reopen-gap/{gap_id}")
async def reopen_gap(
    session_id: str,
    gap_id: str,
    manager=Depends(_get_manager),
) -> dict[str, Any]:
    """
    Reopen a previously closed/accepted gap so users can return recursively.
    """
    session = manager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")

    before_closure = len(session.closure_decisions)
    before_accept = len(session.accepted_open_gaps)
    session.closure_decisions = [c for c in session.closure_decisions if c.gap_id != gap_id]
    session.accepted_open_gaps = [a for a in session.accepted_open_gaps if a.gap_id != gap_id]

    gap = next((n for n in session.nonconformances if n.nonconformance_id == gap_id), None)
    for det in session.mpr_determinations:
        if not gap:
            continue
        if det.get("material_id") != gap.material_id:
            continue
        if det.get("environment_id") != gap.environment_id:
            continue
        if gap.affected_mprs and det.get("mpr_id") not in set(gap.affected_mprs):
            continue
        det["needs_review"] = True
        det["hitl_required"] = True
        det.pop("human_review", None)

    manager.update_session(session)
    return {
        "status": "reopened",
        "gap_id": gap_id,
        "closure_removed": before_closure - len(session.closure_decisions),
        "acceptance_removed": before_accept - len(session.accepted_open_gaps),
    }


@router.post("/sessions/{session_id}/generate")
async def generate_artifacts(
    session_id: str,
    request: GenerateRequest,
    manager=Depends(_get_manager),
) -> dict[str, Any]:
    session = manager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")

    can_generate, blockers = can_generate_codex(session)
    if not can_generate:
        raise HTTPException(status_code=400, detail=f"Cannot generate: {', '.join(blockers)}")

    artifacts: list[dict[str, Any]] = []
    for name in request.artifacts:
        if name == "mp_plan_docx":
            content = generate_mp_plan_docx_codex(session)
            artifact = GeneratedArtifact(
                artifact_type=ArtifactType.MP_PLAN_DOCX,
                format="docx",
                content_bytes=content,
                source="mp_plan_v2_codex",
            )
            session.generated_artifacts.append(artifact)
            artifacts.append(
                {
                    "name": name,
                    "artifact_id": artifact.artifact_id,
                    "format": "docx",
                    "size_bytes": len(content),
                }
            )
        elif name == "mp_plan_json":
            content = generate_mp_plan_json_bytes_codex(session)
            artifact = GeneratedArtifact(
                artifact_type=ArtifactType.RUN_MANIFEST_JSON,
                format="json",
                content_bytes=content,
                source="mp_plan_v2_codex",
            )
            session.generated_artifacts.append(artifact)
            artifacts.append(
                {
                    "name": name,
                    "artifact_id": artifact.artifact_id,
                    "format": "json",
                    "size_bytes": len(content),
                }
            )

    manager.update_session(session)
    return {"status": "generated", "artifacts": artifacts}


@router.get("/sessions/{session_id}/download/{artifact_id}")
async def download_artifact(
    session_id: str,
    artifact_id: str,
    manager=Depends(_get_manager),
) -> StreamingResponse:
    session = manager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")

    artifact = next((a for a in session.generated_artifacts if a.artifact_id == artifact_id), None)
    if not artifact or artifact.content_bytes is None:
        raise HTTPException(status_code=404, detail=f"Artifact not found: {artifact_id}")

    mime = {
        "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "json": "application/json",
    }.get(artifact.format, "application/octet-stream")

    filename = f"{artifact.artifact_type.value}_{session_id[:8]}.{artifact.format}"
    return StreamingResponse(
        iter([artifact.content_bytes]),
        media_type=mime,
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@router.get("/sessions/{session_id}/export/mp-plan-json")
async def export_mp_plan_json(
    session_id: str,
    manager=Depends(_get_manager),
) -> dict[str, Any]:
    session = manager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")
    return generate_mp_plan_json_codex(session)
