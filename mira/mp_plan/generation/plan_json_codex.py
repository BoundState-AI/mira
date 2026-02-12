#!/usr/bin/env python3
"""
Module: M&P Plan JSON Generator (Codex)
Purpose: Structured, reusable JSON artifact for M&P Plan v2
"""

from __future__ import annotations

import json
from datetime import date, datetime
from typing import Any

from ..models import PlanGeneratorSession

__version__ = "2.1.0-codex"
__safety_critical__ = False


def _json_default_codex(obj: Any) -> Any:
    """
    Fallback JSON serializer for datetime/date and pydantic-like objects.
    """
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    model_dump = getattr(obj, "model_dump", None)
    if callable(model_dump):
        return model_dump(mode="json")
    raise TypeError(f"Object of type {obj.__class__.__name__} is not JSON serializable")


def _determination_rollup(determinations: list[dict[str, Any]]) -> dict[str, int]:
    rollup = {
        "total": len(determinations),
        "applicable": 0,
        "not_applicable": 0,
        "compliant": 0,
        "compliant_with_constraints": 0,
        "noncompliant": 0,
        "unknown": 0,
        "needs_review": 0,
    }
    for d in determinations:
        app = d.get("applicability_status")
        status = d.get("status")
        if app == "applicable":
            rollup["applicable"] += 1
        if status == "not_applicable":
            rollup["not_applicable"] += 1
        if status == "compliant":
            rollup["compliant"] += 1
        elif status == "compliant_with_constraints":
            rollup["compliant_with_constraints"] += 1
        elif status == "noncompliant":
            rollup["noncompliant"] += 1
        elif status == "unknown":
            rollup["unknown"] += 1
        if d.get("needs_review"):
            rollup["needs_review"] += 1
    return rollup


def generate_mp_plan_json_codex(session: PlanGeneratorSession) -> dict[str, Any]:
    """Generate a reusable JSON representation of the M&P plan session."""
    determinations = list(session.mpr_determinations or [])
    rollup = _determination_rollup(determinations)

    closed_ids = {d.gap_id for d in session.closure_decisions}
    accepted_ids = {a.gap_id for a in session.accepted_open_gaps}
    open_nonconformances = [
        n
        for n in session.nonconformances
        if n.nonconformance_id not in closed_ids and n.nonconformance_id not in accepted_ids
    ]

    return {
        "schema_version": __version__,
        "generated_at": datetime.now().isoformat(),
        "session": {
            "session_id": session.session_id,
            "program_name": session.program_name,
            "program_phase": session.program_phase,
            "policy_pack_id": session.policy_pack_id,
            "created_at": session.created_at.isoformat(),
            "updated_at": session.updated_at.isoformat(),
        },
        "source_precedence": [
            "dt_json",
            "drawing_ocr_extract",
            "miul_import",
            "human_input",
        ],
        "environments": [env.model_dump(mode="json") for env in session.environments],
        "materials": [mat.model_dump(mode="json") for mat in session.materials],
        "maptis_resolutions": [res.model_dump(mode="json") for res in session.maptis_resolutions],
        "applicability_matrix": session.applicability_matrix or {},
        "mpr_determinations": determinations,
        "deficiencies": [d.model_dump(mode="json") for d in session.deficiencies],
        "nonconformances": [n.model_dump(mode="json") for n in session.nonconformances],
        "closure_decisions": [c.model_dump(mode="json") for c in session.closure_decisions],
        "accepted_open_gaps": [a.model_dump(mode="json") for a in session.accepted_open_gaps],
        "minor_quantity_aggregation": (
            session.minor_quantity_aggregation.model_dump(mode="json")
            if session.minor_quantity_aggregation
            else None
        ),
        "review": {
            "blocking_questions": [q.model_dump(mode="json") for q in session.blocking_questions],
            "user_decisions": [u.model_dump(mode="json") for u in session.user_decisions],
        },
        "statistics": {
            "materials": len(session.materials),
            "environments": len(session.environments),
            "nonconformances_open": len(open_nonconformances),
            "nonconformances_closed": len(session.closure_decisions),
            "nonconformances_accepted_open": len(session.accepted_open_gaps),
            "determinations": rollup,
        },
    }


def generate_mp_plan_json_bytes_codex(session: PlanGeneratorSession) -> bytes:
    """Generate UTF-8 encoded JSON bytes for download."""
    return json.dumps(
        generate_mp_plan_json_codex(session),
        indent=2,
        default=_json_default_codex,
    ).encode("utf-8")
