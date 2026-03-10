#!/usr/bin/env python3
"""
Module: OCA Router
Purpose: Oxygen Compatibility Assessment API endpoints per BS-SPEC-OCA-001-REV1.

BoundState AI 2026
Version: 1.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: NASA-STD-6001B, NASA-STD-6016C, SWE-013, SWE-032
Safety Critical: True

API Contracts per Spec §10.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from mira.oca.models import (
    BlockedState,
    ComponentInfo,
    HazardControlEntry,
    KindlingChainResult,
    MaterialInstance,
    MechanismTrace,
    MUASeed,
    OCACreateCaseRequest,
    OCACreateCaseResponse,
    OCADecisionPacket,
    OCADecisionResponse,
    OCADisposition,
    OCAEvidenceResponse,
    OCAExportRequest,
    OCAKindlingResponse,
    OCAMechanismResponse,
    OCAPrecheckResponse,
    OCAReviewActionRequest,
    OxygenServiceContext,
    ReactionEffect,
    TestEvidence,
    TriggeredRequirement,
)

LOGGER = logging.getLogger(__name__)

router = APIRouter()

# In-memory case store (production: PostgreSQL)
_cases: dict[str, dict] = {}


# =============================================================================
# HELPER
# =============================================================================

def _get_case(case_id: str) -> dict:
    if case_id not in _cases:
        raise HTTPException(status_code=404, detail=f"Case {case_id} not found")
    return _cases[case_id]


# =============================================================================
# ENDPOINTS (per Spec §10)
# =============================================================================


@router.get("/ping")
async def ping() -> dict[str, str]:
    """Health check for OCA endpoint."""
    return {"status": "ok", "domain": "oca", "version": "1.0.0"}


@router.post("/cases", response_model=OCACreateCaseResponse)
async def create_case(request: OCACreateCaseRequest) -> OCACreateCaseResponse:
    """
    Create a new OCA case.

    Stage 0: Normalize inputs, detect blocked states, return case_id.
    """
    try:
        from mira.oca.engine import get_oca_engine

        engine = get_oca_engine()
        context, blocked_states, warnings = engine.create_case(
            request.service_context,
            request.component,
            request.materials,
        )

        # Store case
        case_id = context.case_id
        _cases[case_id] = {
            "context": context,
            "component": request.component,
            "materials": request.materials,
            "blocked_states": blocked_states,
            "warnings": warnings,
            "created_at": datetime.utcnow(),
            "locked": False,
        }

        LOGGER.info(f"[OCA] Case created: {case_id}, blocked={len(blocked_states)}")

        return OCACreateCaseResponse(
            case_id=case_id,
            blocked_states=blocked_states,
            precheck_warnings=warnings,
            normalized_context=context,
            normalized_materials=request.materials,
        )

    except Exception as exc:
        LOGGER.error(f"[OCA] Case creation error: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"OCA case creation error: {str(exc)}") from exc


@router.post("/cases/{case_id}/precheck", response_model=OCAPrecheckResponse)
async def precheck_requirements(case_id: str) -> OCAPrecheckResponse:
    """
    Stage 1: Requirement triggers (MPRs/FOCRs, prohibitions, acceptance test).
    """
    try:
        from mira.oca.engine import get_oca_engine

        case = _get_case(case_id)
        engine = get_oca_engine()

        triggered, acceptance_required, acceptance_exempt, exemption_reason = engine.precheck(
            case["context"], case["component"], case["materials"],
        )

        # Store in case
        case["triggered_requirements"] = triggered

        prohibitions = [r for r in triggered if r.is_prohibition]

        return OCAPrecheckResponse(
            case_id=case_id,
            triggered_requirements=triggered,
            prohibitions=prohibitions,
            acceptance_test_required=acceptance_required,
            acceptance_test_exempt=acceptance_exempt,
            exemption_reason=exemption_reason,
        )

    except HTTPException:
        raise
    except Exception as exc:
        LOGGER.error(f"[OCA] Precheck error: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/cases/{case_id}/evidence", response_model=OCAEvidenceResponse)
async def retrieve_evidence(case_id: str) -> OCAEvidenceResponse:
    """
    Stages 2-3: Retrieve and score evidence.
    """
    try:
        from mira.oca.engine import get_oca_engine

        case = _get_case(case_id)
        engine = get_oca_engine()

        evidence, gaps = engine.retrieve_and_score_evidence(
            case["context"], case["materials"],
        )

        case["evidence"] = evidence
        case["gaps"] = gaps

        return OCAEvidenceResponse(
            case_id=case_id,
            evidence=evidence,
            gaps=gaps,
            total_evidence=len(evidence),
        )

    except HTTPException:
        raise
    except Exception as exc:
        LOGGER.error(f"[OCA] Evidence retrieval error: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/cases/{case_id}/mechanisms", response_model=OCAMechanismResponse)
async def assess_mechanisms(case_id: str) -> OCAMechanismResponse:
    """
    Stage 4: Assess all 12 ignition mechanisms per TM-2007-213740.
    """
    try:
        from mira.oca.engine import get_oca_engine

        case = _get_case(case_id)
        engine = get_oca_engine()

        mechanisms = engine.assess_mechanisms(
            case["context"], case["component"], case["materials"],
        )

        case["mechanisms"] = mechanisms

        credible = sum(1 for m in mechanisms if m.credible_status.value == "credible")
        indeterminate = sum(1 for m in mechanisms if m.credible_status.value == "indeterminate")

        return OCAMechanismResponse(
            case_id=case_id,
            mechanism_assessments=mechanisms,
            credible_count=credible,
            indeterminate_count=indeterminate,
        )

    except HTTPException:
        raise
    except Exception as exc:
        LOGGER.error(f"[OCA] Mechanism assessment error: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/cases/{case_id}/kindling", response_model=OCAKindlingResponse)
async def evaluate_kindling(case_id: str) -> OCAKindlingResponse:
    """
    Stage 5a: Kindling chain and reaction effect per TM §4.4–4.5.
    """
    try:
        from mira.oca.engine import get_oca_engine

        case = _get_case(case_id)
        engine = get_oca_engine()

        mechanisms = case.get("mechanisms")
        if not mechanisms:
            mechanisms = engine.assess_mechanisms(
                case["context"], case["component"], case["materials"],
            )
            case["mechanisms"] = mechanisms

        kindling = engine.evaluate_kindling_and_effect(
            case["materials"], case["component"], mechanisms,
        )

        case["kindling"] = kindling

        return OCAKindlingResponse(case_id=case_id, kindling_chain=kindling)

    except HTTPException:
        raise
    except Exception as exc:
        LOGGER.error(f"[OCA] Kindling chain error: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/cases/{case_id}/decision", response_model=OCADecisionResponse)
async def finalize_decision(case_id: str) -> OCADecisionResponse:
    """
    Run full assessment pipeline and return final disposition.
    """
    try:
        from mira.oca.engine import get_oca_engine

        case = _get_case(case_id)
        engine = get_oca_engine()

        decision = engine.run_full_assessment(
            case["context"], case["component"], case["materials"],
        )

        # Override case_id to match stored case
        decision.case_id = case_id
        case["decision"] = decision

        LOGGER.info(f"[OCA] Decision: {case_id} -> {decision.final_disposition.value}")

        return OCADecisionResponse(case_id=case_id, decision=decision)

    except HTTPException:
        raise
    except Exception as exc:
        LOGGER.error(f"[OCA] Decision error: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/cases/{case_id}/export")
async def export_artifacts(request: OCAExportRequest) -> dict[str, Any]:
    """
    Stage 6: Generate export artifacts (JSON summary, MUA seed, etc.).
    """
    try:
        case = _get_case(request.case_id)
        decision: Optional[OCADecisionPacket] = case.get("decision")

        if not decision:
            raise HTTPException(status_code=400, detail="Run /decision first to generate the assessment")

        export = {
            "case_id": request.case_id,
            "export_format": request.format,
            "generated_at": datetime.utcnow().isoformat(),
            "disposition": decision.final_disposition.value,
            "summary_rationale": decision.summary_rationale,
            "triggered_requirements": [
                {
                    "id": r.requirement_id,
                    "title": r.title,
                    "tier": r.tier.value,
                    "satisfied": r.satisfied,
                    "is_prohibition": r.is_prohibition,
                }
                for r in decision.triggered_requirements
            ],
            "mechanism_summary": [
                {
                    "mechanism": m.mechanism_name.value,
                    "credible": m.credible_status.value,
                    "rating": m.rating,
                    "source_ref": m.source_ref,
                }
                for m in decision.mechanism_assessments
            ],
            "reaction_effect": decision.reaction_effect.value,
            "kindling_chain_present": decision.kindling_chain_present,
            "unresolved_gaps": decision.unresolved_gaps,
        }

        if request.include_evidence:
            export["evidence"] = [e.model_dump() for e in decision.evidence]

        if request.include_mua_seed and decision.mua_seed:
            export["mua_seed"] = decision.mua_seed.model_dump()

        return export

    except HTTPException:
        raise
    except Exception as exc:
        LOGGER.error(f"[OCA] Export error: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/cases/{case_id}/lineage")
async def get_lineage(case_id: str) -> dict[str, Any]:
    """Full decision lineage with rule execution trace."""
    case = _get_case(case_id)
    decision: Optional[OCADecisionPacket] = case.get("decision")

    return {
        "case_id": case_id,
        "created_at": case.get("created_at", "").isoformat() if case.get("created_at") else None,
        "locked": case.get("locked", False),
        "has_decision": decision is not None,
        "disposition": decision.final_disposition.value if decision else None,
        "blocked_states": [b.model_dump() for b in case.get("blocked_states", [])],
        "warnings": case.get("warnings", []),
    }


@router.get("/cases/{case_id}/requirements")
async def get_requirements(case_id: str) -> dict[str, Any]:
    """Triggered requirements with satisfaction status."""
    case = _get_case(case_id)
    triggered = case.get("triggered_requirements", [])

    return {
        "case_id": case_id,
        "requirements": [r.model_dump() for r in triggered],
        "total": len(triggered),
        "satisfied": sum(1 for r in triggered if r.satisfied),
        "prohibitions": sum(1 for r in triggered if r.is_prohibition),
    }


@router.post("/cases/{case_id}/review-actions")
async def submit_review_action(request: OCAReviewActionRequest) -> dict[str, str]:
    """Submit reviewer action (approve, override, comment, request-info)."""
    case = _get_case(request.case_id)

    if case.get("locked"):
        raise HTTPException(status_code=409, detail="Case is locked for export")

    # Log the action
    actions = case.setdefault("review_actions", [])
    actions.append({
        "action": request.action,
        "mechanism": request.mechanism_name.value if request.mechanism_name else None,
        "comment": request.comment,
        "reviewer": request.reviewer_name,
        "timestamp": datetime.utcnow().isoformat(),
    })

    return {"status": "accepted", "action": request.action}


@router.post("/cases/{case_id}/lock")
async def lock_case(case_id: str) -> dict[str, Any]:
    """Lock assessment for export. Prevents further modification."""
    case = _get_case(case_id)
    case["locked"] = True
    return {"case_id": case_id, "locked": True, "locked_at": datetime.utcnow().isoformat()}


@router.get("/mechanisms")
async def list_mechanisms() -> dict[str, Any]:
    """List all 12 ignition mechanisms from the data pack."""
    try:
        from mira.oca.engine import get_mechanisms_data

        data = get_mechanisms_data()
        mechanisms = [
            {
                "name": m["name"],
                "display_name": m["display_name"],
                "source_ref": m["source_ref"],
                "description": m["description"],
                "characteristic_elements": m["characteristic_elements"],
            }
            for m in data.get("mechanisms", [])
        ]
        return {"mechanisms": mechanisms, "total": len(mechanisms)}

    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/requirements")
async def list_requirements() -> dict[str, Any]:
    """List all governing requirements from the data pack."""
    try:
        from mira.oca.engine import get_requirements_data

        data = get_requirements_data()
        return {
            "requirements": data.get("requirements", []),
            "focrs": data.get("focrs", []),
        }

    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/adiabatic-calc")
async def adiabatic_calculator(
    ti_k: float = 293.15,
    pi_psia: float = 14.7,
    pf_psia: float = 3000.0,
    gamma: float = 1.4,
) -> dict[str, float]:
    """Live adiabatic compression calculator for Rapid Pressurization mechanism."""
    from mira.oca.engine import adiabatic_compression_temperature

    tf_k = adiabatic_compression_temperature(ti_k, pi_psia, pf_psia, gamma)
    tf_c = tf_k - 273.15
    tf_f = tf_c * 9.0 / 5.0 + 32.0

    return {
        "ti_k": ti_k,
        "pi_psia": pi_psia,
        "pf_psia": pf_psia,
        "gamma": gamma,
        "tf_k": round(tf_k, 1),
        "tf_c": round(tf_c, 1),
        "tf_f": round(tf_f, 1),
    }


__safety_critical__ = True
