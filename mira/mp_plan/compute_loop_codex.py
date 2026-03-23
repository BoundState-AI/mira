#!/usr/bin/env python3
"""
Module: Compute Loop (Codex)
Purpose: Dynamic HITL compute-question-recompute loop for M&P Plan v2
"""

from __future__ import annotations

import hashlib
import logging
import math
from datetime import date, datetime, timedelta
from typing import Callable, Optional

from mira.compliance.models.enums import FailureMode, GapSeverity

from .engines.applicability_codex import ApplicabilityEngineCodex
from .engines.compliance_eval_codex import (
    STATUS_NONCOMPLIANT,
    STATUS_UNKNOWN,
    ComplianceEvaluationEngineCodex,
)
from .engines.data_acquisition import DataAcquisitionEngine
from .engines.minor_quantity import MinorQuantityEngine
from .models import (
    AcceptedOpenGap,
    BlockingQuestion,
    BlockingQuestionType,
    ClosureDecision,
    EnvironmentDefinition,
    NonconformanceSignal,
    PlanGeneratorSession,
    UserDecision,
)
from .policy import PolicyPack, create_default_policy_pack

LOGGER = logging.getLogger(__name__)

__version__ = "2.1.0-codex"
__safety_critical__ = False

MODE_TO_FAILURE_MODE = {
    "flam": FailureMode.FLAM,
    "o2_prohibited": FailureMode.O2_PROHIBITED,
    "o2_restricted": FailureMode.O2_RESTRICTED,
    "offgas": FailureMode.OFFGAS,
    "tvs": FailureMode.TVS,
    "tox": FailureMode.TOX,
    "hee": FailureMode.HEE,
    "scc": FailureMode.SCC,
    "corr": FailureMode.CORR,
    "fs": FailureMode.FS,
}


def compute_question_id_codex(obj_id: str, suffix: str) -> str:
    return hashlib.sha256(f"{obj_id}:{suffix}".encode("utf-8")).hexdigest()[:32]


def _review_is_resolved(det: dict) -> bool:
    review = det.get("human_review") or {}
    return bool(review.get("resolved"))


def _review_priority(det: dict) -> tuple[int, float]:
    return (
        int(det.get("review_priority", 0)),
        -float(det.get("confidence", 0.0)),
    )


def _clean_sentence(text: str) -> str:
    s = (text or "").strip()
    while ".." in s:
        s = s.replace("..", ".")
    return s


def _select_hitl_targets(
    session: PlanGeneratorSession,
    min_ratio: float = 0.14,
    max_ratio: float = 0.20,
) -> set[str]:
    """
    Select determinations requiring HITL in this compute cycle.

    Strategy:
    - Always include unresolved noncompliant and unknown determinations.
    - Then include highest-risk constrained/low-confidence determinations
      until the dynamic ratio target is met.
    """
    applicable = [
        d
        for d in session.mpr_determinations
        if d.get("applicability_status") == "applicable"
    ]
    if not applicable:
        return set()

    unresolved_candidates = [
        d
        for d in applicable
        if d.get("needs_review") and not _review_is_resolved(d)
    ]

    force_include = {
        d["determination_id"]
        for d in unresolved_candidates
        if d.get("status") in {STATUS_NONCOMPLIANT, STATUS_UNKNOWN}
    }

    uncertain_ratio = len(unresolved_candidates) / max(len(applicable), 1)
    target_ratio = min(max_ratio, max(min_ratio, min_ratio + (max_ratio - min_ratio) * uncertain_ratio))
    target_count = max(1, math.ceil(len(applicable) * target_ratio))

    ranked = sorted(unresolved_candidates, key=_review_priority, reverse=True)
    selected = set(force_include)

    for det in ranked:
        if len(selected) >= target_count:
            break
        selected.add(det["determination_id"])

    return selected


def _det_key(det: dict) -> str:
    return "|".join(
        [
            str(det.get("material_id", "")),
            str(det.get("environment_id", "")),
            str(det.get("mpr_id", "")),
        ]
    )


def _capture_review_state(determinations: list[dict]) -> dict[str, dict]:
    cache: dict[str, dict] = {}
    for det in determinations:
        key = _det_key(det)
        cache[key] = {
            "human_review": det.get("human_review"),
            "hitl_required": det.get("hitl_required"),
            "needs_review": det.get("needs_review"),
            "citation_request": det.get("citation_request"),
            "route_to_closure": det.get("route_to_closure"),
            "human_citation": det.get("human_citation"),
            "user_citations": det.get("user_citations"),
        }
    return cache


def _merge_review_state(determinations: list[dict], cache: dict[str, dict]) -> None:
    for det in determinations:
        state = cache.get(_det_key(det))
        if not state:
            continue
        for field, value in state.items():
            if value is not None:
                det[field] = value
        review_state = state.get("human_review")
        if isinstance(review_state, dict) and review_state.get("resolved"):
            # Preserve human-resolved items across recompute unless explicit re-open.
            det["needs_review"] = False


def _citation_request_label(token: str) -> str:
    token = (token or "").strip().upper()
    if token == "ADD_TEST_CITATION":
        return "test citation"
    if token == "ADD_ANALYSIS_CITATION":
        return "analysis citation"
    if token == "ADD_STANDARD_CITATION":
        return "standard/spec citation"
    return "citation"


def _resolved_material_ids(session: PlanGeneratorSession) -> set[str]:
    return {resolution.material_id for resolution in session.maptis_resolutions}


def _unresolved_materials(session: PlanGeneratorSession) -> list:
    resolved_ids = _resolved_material_ids(session)
    return [material for material in session.materials if material.id not in resolved_ids]


def _inject_route_to_closure_nonconformances(session: PlanGeneratorSession) -> None:
    existing_ids = {n.nonconformance_id for n in session.nonconformances}
    for det in session.mpr_determinations:
        if not det.get("route_to_closure"):
            continue
        if det.get("applicability_status") != "applicable":
            continue
        if det.get("status") == STATUS_NONCOMPLIANT:
            # Already has deterministic NC path.
            continue
        det_id = str(det.get("determination_id", ""))
        if not det_id:
            continue
        nc_id = f"manual_{det_id[:20]}"
        if nc_id in existing_ids:
            continue

        mode = next(iter(det.get("related_failure_modes", []) or []), "flam")
        gap_type = MODE_TO_FAILURE_MODE.get(mode, FailureMode.MISSING_INPUT)
        nc = NonconformanceSignal(
            nonconformance_id=nc_id,
            gap_type=gap_type,
            failing_requirement=f"{det.get('mpr_id', '')} {det.get('mpr_title', '')}".strip(),
            failing_value=det.get("failing_value"),
            required_value=det.get("required_value") or "Closure decision required",
            material_id=str(det.get("material_id", "")),
            environment_id=str(det.get("environment_id", "")),
            affected_mprs=[str(det.get("mpr_id", ""))] if det.get("mpr_id") else [],
            severity=GapSeverity.HIGH if det.get("status") == STATUS_UNKNOWN else GapSeverity.MEDIUM,
            confidence=float(det.get("confidence", 0.5)),
            evidence_refs=[],
            source_adapter="compute_loop_codex",
        )
        session.nonconformances.append(nc)
        existing_ids.add(nc_id)


def can_generate_codex(session: PlanGeneratorSession) -> tuple[bool, list[str]]:
    """
    Codex generation gate.

    Allows generation with accepted open gaps, but blocks unresolved
    required HITL reviews and unresolved MAPTIS materials.
    """
    blockers: list[str] = []

    if not session.environments:
        blockers.append("No environments defined")
    if not session.materials:
        blockers.append("No materials entered")

    unresolved = _unresolved_materials(session)
    if unresolved:
        blockers.append(f"{len(unresolved)} materials not resolved in MAPTIS")

    # Upstream session setup and material-resolution blockers take priority over
    # downstream review load. Do not force HITL or closure work until the
    # material identity/data foundation is complete.
    if blockers:
        return False, blockers

    closed_ids = {d.gap_id for d in session.closure_decisions}
    accepted_ids = {a.gap_id for a in session.accepted_open_gaps}
    open_nonconformances = [
        n
        for n in session.nonconformances
        if n.nonconformance_id not in closed_ids and n.nonconformance_id not in accepted_ids
    ]
    if open_nonconformances:
        blockers.append(
            f"{len(open_nonconformances)} nonconformances without closure or acceptance"
        )

    unresolved_hitl = [
        d
        for d in session.mpr_determinations
        if d.get("hitl_required") and not _review_is_resolved(d)
    ]
    if unresolved_hitl:
        blockers.append(f"{len(unresolved_hitl)} HITL determinations pending review")

    return len(blockers) == 0, blockers


def generate_blocking_questions_codex(
    session: PlanGeneratorSession,
    policy_pack: Optional[PolicyPack] = None,
) -> list[BlockingQuestion]:
    """Generate blocking questions with dynamic HITL targeting."""
    questions: list[BlockingQuestion] = []
    policy = policy_pack or create_default_policy_pack()

    if not session.environments:
        questions.append(
            BlockingQuestion(
                question_id="env_missing",
                question_type=BlockingQuestionType.ENVIRONMENT_MISSING,
                question_text="Select the target vehicle/environment for this M&P plan.",
                context="Required to evaluate MPR applicability and compliance.",
                blocked_decisions=["all_applicability", "all_compliance"],
                options=list(policy.vehicle_environments.keys()) + ["CUSTOM"],
                source="compute_loop_codex",
            )
        )
        return questions

    unresolved_materials = _unresolved_materials(session)
    unresolved_ids = {material.id for material in unresolved_materials}
    for material in unresolved_materials:
        if material.id not in unresolved_ids:
            continue
        qid = compute_question_id_codex(material.id, "resolution")
        msg = (
            f"Provide MAPTIS code for material '{material.name}'."
            if not material.maptis_code
            else f"MAPTIS code '{material.maptis_code}' could not be resolved for '{material.name}'. Provide a valid code."
        )
        questions.append(
            BlockingQuestion(
                question_id=qid,
                question_type=BlockingQuestionType.MATERIAL_AMBIGUOUS,
                question_text=msg,
                context=f"Application: {material.application}",
                blocked_decisions=[f"resolution:{material.id}"],
                source_gap_id=material.id,
                source="compute_loop_codex",
            )
        )

    if questions:
        for det in session.mpr_determinations:
            det["hitl_required"] = False
        return questions

    selected_hitl_ids = _select_hitl_targets(session)
    for det in session.mpr_determinations:
        det_id = det.get("determination_id")
        if not det_id:
            continue
        det["hitl_required"] = det_id in selected_hitl_ids

    for det in session.mpr_determinations:
        det_id = det.get("determination_id")
        if not det_id:
            continue
        if not det.get("hitl_required"):
            continue
        if _review_is_resolved(det):
            continue
        citation_request = det.get("citation_request")
        if isinstance(citation_request, dict):
            request_type = str(citation_request.get("requested_type", "ADD_TEST_CITATION"))
            label = _citation_request_label(request_type)
            qid = compute_question_id_codex(det_id, "citation")
            questions.append(
                BlockingQuestion(
                    question_id=qid,
                    question_type=BlockingQuestionType.PRECEDENT_VALIDATION,
                    question_text=(
                        f"Provide {label} for part '{det.get('material_name')}' in "
                        f"'{det.get('environment_name')}' for {det.get('mpr_id')}."
                    ),
                    context=(
                        "Enter the citation as free text. Suggested format: "
                        "'<document/report id> | <section/page> | <evidence statement>'. "
                        "Example: 'TR-2026-114 | Sec 5.2 | Passes NASA-STD-6001 test at 30% O2, 14.7 psia'."
                    ),
                    blocked_decisions=[det_id],
                    options=[],
                    source_gap_id=det_id,
                    source_mpr=det.get("mpr_id"),
                    source="citation_request",
                )
            )
            continue
        qid = compute_question_id_codex(det_id, "review")
        citations = det.get("citations", [])
        citation_text = ", ".join(citations[:2]) if citations else "No citations attached"
        meaning = _clean_sentence(det.get("human_meaning", det.get("review_reason", "")))
        action = _clean_sentence(det.get("human_action", "Review and decide."))
        reason = _clean_sentence(det.get("review_reason", ""))
        helper = det.get("citation_helper") or {}
        helper_actions = helper.get("quick_actions") or []
        helper_summary = ""
        if helper:
            helper_summary = (
                f"Section family: {helper.get('section_family', 'general')} | "
                f"Quick actions: {', '.join(helper_actions)}"
            )
        options = helper_actions if helper_actions else ["ACCEPT", "FLAG_FOR_EDIT", "NEEDS_TEST"]
        questions.append(
            BlockingQuestion(
                question_id=qid,
                question_type=BlockingQuestionType.TAILORING_APPROVAL,
                question_text=(
                    f"Review this requirement for part '{det.get('material_name')}' "
                    f"in '{det.get('environment_name')}': "
                    f"{det.get('mpr_id')} {det.get('mpr_title', '')}".strip()
                ),
                context=(
                    f"Status: {det.get('status')}.\n"
                    f"What this means: {meaning or reason}\n"
                    f"Why flagged: {reason}\n"
                    f"Evidence on file: {citation_text}\n"
                    f"What you should do: {action}\n"
                    f"{helper_summary}".strip()
                ),
                blocked_decisions=[det_id],
                options=options,
                source_mpr=det.get("mpr_id"),
                source="compute_loop_codex",
            )
        )

    closed_ids = {d.gap_id for d in session.closure_decisions}
    accepted_ids = {a.gap_id for a in session.accepted_open_gaps}
    for nc in session.nonconformances:
        if nc.nonconformance_id in closed_ids or nc.nonconformance_id in accepted_ids:
            continue
        material = session.get_material(nc.material_id)
        environment = session.get_environment(nc.environment_id)
        qid = compute_question_id_codex(nc.nonconformance_id, "closure")
        questions.append(
            BlockingQuestion(
                question_id=qid,
                question_type=BlockingQuestionType.CLOSURE_SELECTION,
                question_text=(
                    f"Select closure path for {material.name if material else nc.material_id} "
                    f"({nc.gap_type.value.upper()}) in "
                    f"{environment.name if environment else nc.environment_id}."
                ),
                context=(
                    f"Requirement: {nc.failing_requirement}. "
                    f"Failing value: {nc.failing_value}. "
                    f"Required: {nc.required_value}."
                ),
                blocked_decisions=[f"closure:{nc.nonconformance_id}"],
                options=[
                    "MINOR_QUANTITY",
                    "CONFIGURATION_ANALYSIS",
                    "HEAT_SINK",
                    "SUBSTITUTION",
                    "TEST_PROGRAM",
                    "FULL_MUA",
                    "ACCEPT_OPEN",
                ],
                source_gap_id=nc.nonconformance_id,
                source_mpr=(nc.affected_mprs[0] if nc.affected_mprs else None),
                source="compute_loop_codex",
            )
        )

    if session.minor_quantity_aggregation:
        for assumption in session.minor_quantity_aggregation.grouping_assumptions:
            if assumption.confirmed:
                continue
            qid = compute_question_id_codex(assumption.assumption_id, "grouping")
            questions.append(
                BlockingQuestion(
                    question_id=qid,
                    question_type=BlockingQuestionType.GROUPING_CONFIRMATION,
                    question_text=assumption.description,
                    context="Minor quantity aggregation requires adjacency confirmation.",
                    blocked_decisions=[f"minor_qty_assumption:{assumption.assumption_id}"],
                    options=["YES", "NO"],
                    source_gap_id=assumption.assumption_id,
                    source="compute_loop_codex",
                )
            )

    return questions


def apply_user_decision_codex(
    session: PlanGeneratorSession,
    question: BlockingQuestion,
    answer: str,
    rationale: str,
    policy_pack: Optional[PolicyPack] = None,
) -> None:
    """Apply a user decision to the codex session state."""
    policy = policy_pack or create_default_policy_pack()

    if question.question_type == BlockingQuestionType.ENVIRONMENT_MISSING:
        preset = policy.vehicle_environments.get(answer.upper())
        if preset:
            session.environments.append(
                EnvironmentDefinition(
                    name=preset["name"],
                    o2_pct=preset["o2_pct"],
                    pressure_psia=preset["pressure_psia"],
                    temp_range_c=tuple(preset["temp_range_c"]),
                    habitable=preset["habitable"],
                    vacuum_exposure=preset.get("vacuum_exposure", False),
                    lunar_dust=preset.get("lunar_dust", False),
                    phase=preset.get("phase", "nominal"),
                    source=preset.get("source", "policy_pack"),
                )
            )
        return

    if question.question_type == BlockingQuestionType.MATERIAL_AMBIGUOUS:
        material_id = question.source_gap_id
        for material in session.materials:
            if material.id == material_id:
                material.maptis_code = answer.strip()
                break
        return

    if question.source == "citation_request":
        det_id = question.blocked_decisions[0] if question.blocked_decisions else None
        if not det_id:
            return
        citation_text = answer.strip()
        for det in session.mpr_determinations:
            if det.get("determination_id") != det_id:
                continue
            request_meta = det.get("citation_request") or {}
            request_type = str(request_meta.get("requested_type", "ADD_TEST_CITATION"))

            if not citation_text:
                det["human_review"] = {
                    "resolved": False,
                    "answer": request_type,
                    "rationale": rationale or "Citation required.",
                    "reviewed_at": datetime.now().isoformat(),
                }
                det["needs_review"] = True
                return

            user_citations = list(det.get("user_citations") or [])
            if citation_text not in user_citations:
                user_citations.append(citation_text)
            det["user_citations"] = user_citations

            det["human_citation"] = {
                "type": request_type,
                "text": citation_text,
                "provided_at": datetime.now().isoformat(),
                "rationale": rationale,
            }
            det.pop("citation_request", None)
            det["human_review"] = {
                "resolved": True,
                "answer": request_type,
                "rationale": rationale or citation_text,
                "reviewed_at": datetime.now().isoformat(),
            }
            det["needs_review"] = False
            return

    if question.question_type == BlockingQuestionType.TAILORING_APPROVAL:
        det_id = question.blocked_decisions[0] if question.blocked_decisions else None
        if not det_id:
            return
        answer_token = answer.strip().upper()
        for det in session.mpr_determinations:
            if det.get("determination_id") != det_id:
                continue
            det["human_review"] = {
                "resolved": answer_token
                in {
                    "ACCEPT",
                    "ACCEPT_WITH_CONSTRAINT",
                    "FLAG_FOR_EDIT",
                    "NEEDS_TEST",
                    "ROUTE_TO_CLOSURE",
                },
                "answer": answer,
                "rationale": rationale,
                "reviewed_at": datetime.now().isoformat(),
            }
            if answer_token in {"ADD_TEST_CITATION", "ADD_ANALYSIS_CITATION", "ADD_STANDARD_CITATION"}:
                det["citation_request"] = {
                    "requested_type": answer_token,
                    "requested_at": datetime.now().isoformat(),
                    "rationale": rationale or "Reviewer requested additional citation.",
                }
                det["needs_review"] = True
                det["human_review"]["resolved"] = False
                break
            if answer_token in {"NEEDS_TEST", "ROUTE_TO_CLOSURE"}:
                det["route_to_closure"] = True
                det["needs_review"] = False
                break
            if answer_token in {"ACCEPT", "ACCEPT_WITH_CONSTRAINT", "FLAG_FOR_EDIT"}:
                det["needs_review"] = False
            break
        return

    if question.question_type == BlockingQuestionType.CLOSURE_SELECTION:
        if answer.upper() == "ACCEPT_OPEN":
            session.accepted_open_gaps.append(
                AcceptedOpenGap(
                    gap_id=question.source_gap_id or "",
                    gap_type="nonconformance",
                    accepted_by="api_user",
                    acceptance_rationale=rationale or "Accepted as open by reviewer",
                    owner="TBD",
                    due_date=date.today() + timedelta(days=30),
                    risk_statement="Risk accepted pending closure package.",
                )
            )
            return

        session.closure_decisions.append(
            ClosureDecision(
                gap_id=question.source_gap_id or "",
                selected_path=answer.upper(),
                provided_inputs={},
                decision_rationale=rationale,
                decided_by="api_user",
                decided_at=datetime.now(),
                available_options=[{"path": opt} for opt in question.options],
                source="compute_loop_codex",
            )
        )
        return

    if question.question_type == BlockingQuestionType.GROUPING_CONFIRMATION:
        if not session.minor_quantity_aggregation:
            return
        for assumption in session.minor_quantity_aggregation.grouping_assumptions:
            if assumption.assumption_id != question.source_gap_id:
                continue
            assumption.confirmed = True
            assumption.confirmed_by = "api_user"
            assumption.assumed_value = answer.strip().upper() == "YES"
            break


def run_compute_loop_codex(
    session: PlanGeneratorSession,
    policy_pack: Optional[PolicyPack] = None,
    answer_callback: Optional[Callable[[BlockingQuestion], tuple[str, str]]] = None,
    max_iterations: int = 20,
) -> PlanGeneratorSession:
    """
    Run codex compute loop:
    compute -> generate questions -> apply user answers (optional) -> recompute.
    """
    policy = policy_pack or create_default_policy_pack()
    data_engine = DataAcquisitionEngine()
    applicability_engine = ApplicabilityEngineCodex()
    compliance_engine = ComplianceEvaluationEngineCodex()
    minor_qty_engine = MinorQuantityEngine()

    try:
        for iteration in range(1, max_iterations + 1):
            LOGGER.info("Codex compute loop iteration %d", iteration)
            review_cache = _capture_review_state(session.mpr_determinations)

            # Engine A: resolve + deficiencies + usage mappings
            resolutions, data_defs, _new_mappings = data_engine.run(session)
            session.maptis_resolutions = resolutions

            # Engine B: full-index applicability
            if session.materials and session.environments:
                session.applicability_matrix = applicability_engine.run(session)
            else:
                session.applicability_matrix = {}

            # Engine C: full-index compliance
            eval_defs, nonconformances, determinations = compliance_engine.run(session)
            session.nonconformances = nonconformances
            _merge_review_state(determinations, review_cache)
            session.mpr_determinations = determinations
            _inject_route_to_closure_nonconformances(session)

            # Merge deficiencies from acquisition + compliance
            merged_defs = {}
            for d in data_defs + eval_defs:
                key = (
                    d.deficiency_type,
                    d.missing_field,
                    d.material_id or "",
                    d.environment_id or "",
                )
                merged_defs[key] = d
            session.deficiencies = list(merged_defs.values())

            # Minor quantity analysis
            if session.nonconformances:
                session.minor_quantity_aggregation = minor_qty_engine.run(session)

            session.blocking_questions = generate_blocking_questions_codex(session, policy)
            session.updated_at = datetime.now()

            if not session.blocking_questions:
                break

            if answer_callback is None:
                break

            for question in list(session.blocking_questions):
                answer, rationale = answer_callback(question)
                session.user_decisions.append(
                    UserDecision(
                        question_id=question.question_id,
                        decision=answer,
                        rationale=rationale,
                        decided_by="interactive_user",
                        source="compute_loop_codex",
                    )
                )
                apply_user_decision_codex(session, question, answer, rationale, policy)

        return session
    finally:
        data_engine.close()
