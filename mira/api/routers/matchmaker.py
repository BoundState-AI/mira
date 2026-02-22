"""MUA Matchmaker v8 API router."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Any, Literal, Optional

from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field

from mira.mua.matchmaker.adapters import resolve_material
from mira.mua.matchmaker.batch import bulk_apply_cat3_code, parse_miul_upload
from mira.mua.matchmaker.matcher import (
    auto_detect_issues,
    determine_category,
    environment_banners,
    is_auto_scope_issue,
    normalize_manual_status,
    run_precedent_match,
)
from mira.mua.matchmaker.models import (
    EnvironmentSpec,
    ExportBlocker,
    ExportMissingField,
    ExportMode,
    ExportValidationResponse,
    IssueCode,
    IssueOutcome,
    IssueState,
    IssueStatus,
    MatchmakerEvent,
    MatchmakerSession,
    SessionSummary,
    normalize_issue_code,
)
from mira.mua.matchmaker.question_engine import (
    evaluate_answers,
    get_next_question,
    load_rule_pack,
)
from mira.mua.matchmaker.session import MatchmakerSessionStore

logger = logging.getLogger(__name__)

router = APIRouter(tags=["MUA Matchmaker v8"])

_RULE_PACK = load_rule_pack()
_RULE_PACK_VERSION = f"{_RULE_PACK['rule_pack_id']}/{_RULE_PACK['version']}"
_STORE = MatchmakerSessionStore()


class CreateSessionRequest(BaseModel):
    material: str = Field(..., min_length=1)
    environment: EnvironmentSpec
    application_description: str = ""
    deviation_type: Literal["material_selection", "manufacturing_nonconformance"] = (
        "material_selection"
    )
    user: Optional[str] = None


class SessionListResponse(BaseModel):
    sessions: list[SessionSummary]
    total: int
    rule_pack_version: str


class IssueQuestionResponse(BaseModel):
    issue: str
    status: IssueStatus
    outcome: Optional[IssueOutcome] = None
    selected_code: Optional[str] = None
    candidate_codes: list[str] = Field(default_factory=list)
    next_question: Optional[dict[str, Any]] = None
    answers: dict[str, Any] = Field(default_factory=dict)
    manual_required: bool = False
    manual_message: Optional[str] = None


class IssueAnswerRequest(BaseModel):
    question_id: Optional[str] = None
    answer: Optional[Any] = None
    answers: dict[str, Any] = Field(default_factory=dict)
    selected_code: Optional[str] = None


class MatchResponse(BaseModel):
    issue: str
    matches: list[dict[str, Any]]
    phrases: list[dict[str, Any]]
    conflicts: list[dict[str, Any]]
    total: int


class RationaleRequest(BaseModel):
    rationale: Optional[str] = None
    selected_phrases: list[str] = Field(default_factory=list)
    manual_disposition: Optional[str] = None


class BatchImportResponse(BaseModel):
    filename: str
    groups: int
    created_sessions: list[str]


class BulkApplyRequest(BaseModel):
    session_ids: list[str] = Field(default_factory=list)
    issue: str
    code: str
    confirmation: str


@router.get("/ping")
async def ping() -> dict[str, Any]:
    return {"status": "ok", "domain": "mua-matchmaker-v8", "rule_pack": _RULE_PACK_VERSION}


@router.post("/sessions", response_model=MatchmakerSession)
async def create_session(request: CreateSessionRequest) -> MatchmakerSession:
    material = resolve_material(request.material)
    issues: dict[str, IssueState] = {}

    redirected = request.deviation_type == "manufacturing_nonconformance"
    redirect_reason = None
    if redirected:
        redirect_reason = "Manufacturing nonconformance routed to MRB/DR (MPR 29)."
    else:
        issues = auto_detect_issues(
            material=material,
            environment=request.environment,
            application_description=request.application_description,
        )

    session = MatchmakerSession(
        session_id=str(uuid.uuid4()),
        rule_pack_version=_RULE_PACK_VERSION,
        material_input=request.material,
        material_resolution=material,
        environment=request.environment,
        application_description=request.application_description or request.environment.application,
        issues=issues,
        banners=environment_banners(request.environment, material),
        nonconformance_redirected=redirected,
        redirect_reason=redirect_reason,
    )
    session.events.append(
        MatchmakerEvent(
            action="session_created",
            note=f"user={request.user or 'unknown'}; deviation={request.deviation_type}",
            rule_pack_version=_RULE_PACK_VERSION,
        )
    )
    if not redirected:
        _auto_seed_issue_answers(session)
        _refresh_category(session)
    _STORE.create(session)
    return session


@router.get("/sessions", response_model=SessionListResponse)
async def list_sessions() -> SessionListResponse:
    sessions = _STORE.list()
    return SessionListResponse(
        sessions=sessions,
        total=len(sessions),
        rule_pack_version=_RULE_PACK_VERSION,
    )


@router.get("/sessions/{sid}", response_model=MatchmakerSession)
async def get_session(sid: str) -> MatchmakerSession:
    return _require_session(sid)


@router.delete("/sessions/{sid}")
async def delete_session(sid: str) -> dict[str, Any]:
    deleted = _STORE.delete(sid)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Session not found: {sid}")
    return {"session_id": sid, "deleted": True}


@router.get("/sessions/{sid}/issues/{issue}/questions", response_model=IssueQuestionResponse)
async def get_issue_questions(sid: str, issue: str) -> IssueQuestionResponse:
    session = _require_session(sid)
    state, issue_key = _require_issue(session, issue)
    return _build_issue_question_response(issue_key, state)


@router.post("/sessions/{sid}/issues/{issue}/answer", response_model=IssueQuestionResponse)
async def submit_issue_answer(sid: str, issue: str, request: IssueAnswerRequest) -> IssueQuestionResponse:
    session = _require_session(sid)
    state, issue_key = _require_issue(session, issue)
    if state.out_of_scope:
        raise HTTPException(status_code=400, detail="Issue is manual_required and does not accept tree answers.")

    if request.question_id is not None:
        state.answers[request.question_id] = request.answer
        state.last_question_id = request.question_id
        session.events.append(
            MatchmakerEvent(
                action="answer_submitted",
                issue=issue_key,
                question=request.question_id,
                answer=request.answer,
                rule_pack_version=_RULE_PACK_VERSION,
            )
        )

    for question_id, value in request.answers.items():
        state.answers[question_id] = value
        state.last_question_id = question_id
        session.events.append(
            MatchmakerEvent(
                action="answer_submitted",
                issue=issue_key,
                question=question_id,
                answer=value,
                rule_pack_version=_RULE_PACK_VERSION,
            )
        )

    _apply_evaluation(issue_key, state, selected_code=request.selected_code, session=session)
    session.issues[issue_key] = state
    _refresh_category(session)
    _STORE.save(session)
    return _build_issue_question_response(issue_key, state)


@router.post("/sessions/{sid}/issues/{issue}/match", response_model=MatchResponse)
async def run_issue_match(sid: str, issue: str) -> MatchResponse:
    session = _require_session(sid)
    state, issue_key = _require_issue(session, issue)
    if state.out_of_scope:
        raise HTTPException(status_code=400, detail="Cannot run matching for manual_required issue.")

    canonical = normalize_issue_code(issue_key)
    matches, phrases, conflicts = run_precedent_match(
        material=session.material_resolution,
        environment=session.environment,
        issue=canonical,
    )

    state.matches = matches
    state.phrases = phrases
    state.conflicts = conflicts
    state.status = IssueStatus.IN_PROGRESS if state.status == IssueStatus.PENDING else state.status
    session.events.append(
        MatchmakerEvent(
            action="match_run",
            issue=issue_key,
            note=f"matches={len(matches)} conflicts={len(conflicts)}",
            rule_pack_version=_RULE_PACK_VERSION,
        )
    )
    session.issues[issue_key] = state
    _STORE.save(session)

    return MatchResponse(
        issue=issue_key,
        matches=[m.model_dump(mode="json") for m in matches],
        phrases=[p.model_dump(mode="json") for p in phrases],
        conflicts=[c.model_dump(mode="json") for c in conflicts],
        total=len(matches),
    )


@router.post("/sessions/{sid}/issues/{issue}/rationale", response_model=IssueState)
async def save_issue_rationale(sid: str, issue: str, request: RationaleRequest) -> IssueState:
    session = _require_session(sid)
    state, issue_key = _require_issue(session, issue)

    if state.out_of_scope:
        if not (request.manual_disposition or "").strip():
            raise HTTPException(
                status_code=400,
                detail="manual_disposition is required for manual_required issues.",
            )
        state.manual_disposition = request.manual_disposition.strip()
        session.events.append(
            MatchmakerEvent(
                action="manual_disposition_saved",
                issue=issue_key,
                note=state.manual_disposition,
                rule_pack_version=_RULE_PACK_VERSION,
            )
        )
        session.issues[issue_key] = state
        _STORE.save(session)
        return state

    parts: list[str] = []
    if request.selected_phrases:
        parts.extend([p.strip() for p in request.selected_phrases if p and p.strip()])
    if request.rationale and request.rationale.strip():
        parts.append(request.rationale.strip())
    state.rationale = "\n".join(parts).strip() if parts else None

    if state.outcome == IssueOutcome.CAT_I_II and state.rationale:
        state.status = IssueStatus.DONE
    elif state.outcome == IssueOutcome.CAT_I_II:
        state.status = IssueStatus.IN_PROGRESS

    session.events.append(
        MatchmakerEvent(
            action="rationale_saved",
            issue=issue_key,
            note=f"length={len(state.rationale or '')}",
            rule_pack_version=_RULE_PACK_VERSION,
        )
    )
    session.issues[issue_key] = state
    _refresh_category(session)
    _STORE.save(session)
    return state


@router.post("/batch/import-miul", response_model=BatchImportResponse)
async def import_miul(file: UploadFile = File(...)) -> BatchImportResponse:
    contents = await file.read()
    groups = parse_miul_upload(contents, file.filename)
    created_ids: list[str] = []

    for group in groups:
        payload = CreateSessionRequest(
            material=group["material_input"],
            environment=EnvironmentSpec.model_validate(group["environment"]),
            application_description="; ".join(group.get("sample_descriptions") or []),
        )
        created = await create_session(payload)
        trigger_signature = str(group.get("trigger_signature") or "").strip()
        if trigger_signature:
            if _auto_seed_from_trigger_signature(created, trigger_signature):
                _refresh_category(created)
                _STORE.save(created)
        created_ids.append(created.session_id)

    return BatchImportResponse(
        filename=file.filename,
        groups=len(groups),
        created_sessions=created_ids,
    )


@router.post("/batch/bulk-apply")
async def bulk_apply(request: BulkApplyRequest) -> dict[str, Any]:
    if not request.session_ids:
        raise HTTPException(status_code=400, detail="session_ids is required")
    try:
        result = bulk_apply_cat3_code(
            store=_STORE,
            session_ids=request.session_ids,
            issue=request.issue,
            code=request.code,
            confirmation=request.confirmation,
            rule_pack_version=_RULE_PACK_VERSION,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return result


@router.get("/sessions/{sid}/export")
async def export_session(
    sid: str,
    mode: ExportMode = Query(default=ExportMode.DRAFT),
) -> dict[str, Any]:
    session = _require_session(sid)
    _refresh_category(session)
    _STORE.save(session)

    validation = _validate_export(session, mode)
    response = validation.model_dump(mode="json")
    response["rule_pack_version"] = session.rule_pack_version
    response["generated_at"] = datetime.utcnow().isoformat()

    if not validation.export_ready:
        response.setdefault(
            "suggestion",
            "Use mode=draft for current state, or resolve blockers for board-ready export.",
        )
        return response

    response["form_text"] = _render_form_text(session, mode)
    return response


def _require_session(sid: str) -> MatchmakerSession:
    session = _STORE.get(sid)
    if session is None:
        raise HTTPException(status_code=404, detail=f"Session not found: {sid}")
    session.issues = {k: normalize_manual_status(v) for k, v in session.issues.items()}
    changed = _ensure_required_issues(session)
    if _auto_seed_issue_answers(session):
        changed = True
    if changed:
        _refresh_category(session)
        _STORE.save(session)
    return session


def _require_issue(session: MatchmakerSession, issue: str) -> tuple[IssueState, str]:
    issue_key = issue.strip().upper()
    if is_auto_scope_issue(issue_key):
        issue_key = normalize_issue_code(issue_key).value

    state = session.issues.get(issue_key)
    if state is None:
        raise HTTPException(status_code=404, detail=f"Issue not found in session: {issue_key}")
    return state, issue_key


def _build_issue_question_response(issue_key: str, state: IssueState) -> IssueQuestionResponse:
    if state.out_of_scope:
        return IssueQuestionResponse(
            issue=issue_key,
            status=state.status,
            outcome=state.outcome,
            selected_code=state.selected_code,
            candidate_codes=state.candidate_codes,
            next_question=None,
            answers=state.answers,
            manual_required=True,
            manual_message=(
                f"MANUAL REVIEW REQUIRED. This issue ({issue_key}) is not covered by "
                f"MIRA automated trees. Applicable requirement: {state.requirement_ref or 'N/A'}."
            ),
        )

    next_question = get_next_question(issue_key, state.answers, _RULE_PACK)
    return IssueQuestionResponse(
        issue=issue_key,
        status=state.status,
        outcome=state.outcome,
        selected_code=state.selected_code,
        candidate_codes=state.candidate_codes,
        next_question=next_question,
        answers=state.answers,
        manual_required=False,
    )


def _apply_evaluation(
    issue_key: str,
    state: IssueState,
    selected_code: Optional[str],
    session: MatchmakerSession,
) -> None:
    evaluation = evaluate_answers(issue_key, state.answers, _RULE_PACK)

    if evaluation.status == "PASS":
        state.outcome = IssueOutcome.PASS
        state.status = IssueStatus.DONE
        state.selected_code = None
        state.candidate_codes = []
        state.answers.pop("_resolved_cat3_code", None)
        return

    if evaluation.status == "CAT_III":
        state.outcome = IssueOutcome.CAT_III
        state.candidate_codes = [evaluation.code] if evaluation.code else []
        selected = selected_code or state.selected_code or evaluation.code
        if selected and selected in state.candidate_codes:
            state.selected_code = selected
            state.status = IssueStatus.DONE
            state.answers["_resolved_cat3_code"] = selected
            session.events.append(
                MatchmakerEvent(
                    action="code_resolved",
                    issue=issue_key,
                    code=selected,
                    rule_pack_version=_RULE_PACK_VERSION,
                )
            )
        else:
            state.status = IssueStatus.IN_PROGRESS
            state.answers.pop("_resolved_cat3_code", None)
        return

    if evaluation.status == "MULTIPLE_CAT3":
        state.outcome = IssueOutcome.CAT_III
        state.candidate_codes = evaluation.candidate_codes
        if selected_code and selected_code in state.candidate_codes:
            state.selected_code = selected_code
            state.status = IssueStatus.DONE
            state.answers["_resolved_cat3_code"] = selected_code
            session.events.append(
                MatchmakerEvent(
                    action="code_resolved",
                    issue=issue_key,
                    code=selected_code,
                    rule_pack_version=_RULE_PACK_VERSION,
                )
            )
        else:
            state.status = IssueStatus.IN_PROGRESS
            state.answers.pop("_resolved_cat3_code", None)
        return

    if evaluation.status == "CAT_I_II":
        state.outcome = IssueOutcome.CAT_I_II
        state.status = IssueStatus.DONE if (state.rationale or "").strip() else IssueStatus.IN_PROGRESS
        state.answers.pop("_resolved_cat3_code", None)
        return

    state.status = IssueStatus.IN_PROGRESS


def _refresh_category(session: MatchmakerSession) -> None:
    category, reasons = determine_category(session.environment, session.issues)
    session.category = category
    session.category_reasons = reasons


def _validate_export(session: MatchmakerSession, mode: ExportMode) -> ExportValidationResponse:
    blockers: list[ExportBlocker] = []
    missing_fields: list[ExportMissingField] = []

    issues = list(session.issues.values())
    done_issues = [i for i in issues if i.status == IssueStatus.DONE]
    manual_issues = [i for i in issues if i.status == IssueStatus.MANUAL_REQUIRED]

    if mode == ExportMode.DRAFT:
        if not done_issues:
            blockers.append(
                ExportBlocker(
                    status=IssueStatus.PENDING,
                    reason="At least one issue must be done before draft export.",
                )
            )
        if not session.application_description.strip():
            missing_fields.append(
                ExportMissingField(
                    field="application_description",
                    reason="Draft will include placeholder for missing application description.",
                )
            )
        return ExportValidationResponse(
            export_ready=len(blockers) == 0,
            mode=mode,
            blockers=blockers,
            missing_fields=missing_fields,
        )

    # Board-ready validation.
    if session.material_resolution.status.value != "resolved":
        missing_fields.append(
            ExportMissingField(
                field="material_resolution",
                reason="Material must be resolved for board-ready export.",
            )
        )
    if not (session.material_resolution.material_code or "").strip():
        missing_fields.append(
            ExportMissingField(
                field="material_code",
                reason="MAPTIS material code is required for board-ready export.",
            )
        )
    if not session.application_description.strip():
        missing_fields.append(
            ExportMissingField(
                field="application_description",
                reason="Required Appendix D field is empty.",
            )
        )
    if session.category is None:
        missing_fields.append(
            ExportMissingField(
                field="category",
                reason="Category must be deterministically resolved before board-ready export.",
            )
        )

    for issue_name, issue in session.issues.items():
        if is_auto_scope_issue(issue_name):
            if issue.status != IssueStatus.DONE:
                blockers.append(
                    ExportBlocker(
                        issue=issue_name,
                        status=issue.status,
                        reason="Issue not complete.",
                    )
                )
            if issue.outcome == IssueOutcome.CAT_I_II and not (issue.rationale or "").strip():
                missing_fields.append(
                    ExportMissingField(
                        issue=normalize_issue_code(issue_name),
                        field="rationale",
                        reason="Rationale required for Cat I/II issue.",
                    )
                )
            if issue.outcome == IssueOutcome.CAT_III and not (issue.selected_code or "").strip():
                missing_fields.append(
                    ExportMissingField(
                        issue=normalize_issue_code(issue_name),
                        field="selected_code",
                        reason="Rationale code must be confirmed for Cat III issue.",
                    )
                )
        elif issue.status == IssueStatus.MANUAL_REQUIRED and not (issue.manual_disposition or "").strip():
            blockers.append(
                ExportBlocker(
                    issue=issue_name,
                    status=issue.status,
                    reason="Manual disposition not entered.",
                )
            )

    if manual_issues:
        for issue in manual_issues:
            if not (issue.manual_disposition or "").strip():
                blockers.append(
                    ExportBlocker(
                        issue=issue.issue,
                        status=IssueStatus.MANUAL_REQUIRED,
                        reason="Manual disposition required for board-ready export.",
                    )
                )

    return ExportValidationResponse(
        export_ready=(len(blockers) == 0 and len(missing_fields) == 0),
        mode=mode,
        blockers=_dedupe_blockers(blockers),
        missing_fields=missing_fields,
        suggestion=(
            "Use mode=draft for current state, or resolve blockers"
            if blockers or missing_fields
            else None
        ),
    )


def _render_form_text(session: MatchmakerSession, mode: ExportMode) -> str:
    lines: list[str] = []
    lines.append("JSC MATERIALS USAGE AGREEMENT")
    lines.append("Per JSC 27301F Appendix B/D")
    lines.append("")
    lines.append(f"MUA NUMBER: MUA-{session.session_id[:8].upper()}")
    lines.append(f"CATEGORY: {(session.category.value if session.category else 'N/A')}")
    if mode == ExportMode.DRAFT:
        lines.append("WATERMARK: DRAFT - NOT FOR BOARD SUBMISSION")
    lines.append("")
    lines.append(f"MATERIAL: {session.material_resolution.resolved_name or session.material_input}")
    lines.append(f"MAPTIS CODE: {session.material_resolution.material_code or '[REQUIRED: material_code]'}")
    lines.append("ENVIRONMENT:")
    lines.append(f"  Location: {session.environment.location}")
    lines.append(f"  Media: {session.environment.medium}")
    lines.append(f"  O2%: {session.environment.o2_percent}")
    lines.append(f"  Pressure (psia): {session.environment.pressure_psia}")
    lines.append(
        f"  Temperature (F): {session.environment.temp_min_f} to {session.environment.temp_max_f}"
    )
    lines.append("")
    lines.append(
        "APPLICATION: "
        + (
            session.application_description.strip()
            if session.application_description.strip()
            else "[REQUIRED: application_description]"
        )
    )
    lines.append("")
    lines.append("ISSUES RESOLVED BY APPENDIX E CODE:")
    for issue in session.issues.values():
        if issue.outcome == IssueOutcome.CAT_III:
            lines.append(f"  - {issue.issue}: Code {issue.selected_code or '[REQUIRED: selected_code]'}")

    lines.append("")
    lines.append("ISSUES REQUIRING MUA DISPOSITION:")
    for issue in session.issues.values():
        if issue.outcome == IssueOutcome.CAT_I_II:
            text = issue.rationale or "[REQUIRED: rationale]"
            lines.append(f"  - {issue.issue}: {text}")

    lines.append("")
    lines.append("MANUAL M&P DISPOSITION (OUT OF SCOPE):")
    for issue in session.issues.values():
        if issue.out_of_scope:
            text = issue.manual_disposition or "[REQUIRED: manual_disposition]"
            lines.append(f"  - {issue.issue} ({issue.requirement_ref or 'N/A'}): {text}")

    lines.append("")
    lines.append(f"Rule Pack: {session.rule_pack_version}")
    lines.append(f"Generated: {datetime.utcnow().isoformat()}")
    return "\n".join(lines)


def _ensure_required_issues(session: MatchmakerSession) -> bool:
    required = (
        IssueCode.FLAM,
        IssueCode.CORR,
        IssueCode.SCC,
        IssueCode.TVS,
        IssueCode.O2,
        IssueCode.HEE,
        IssueCode.FLUID,
    )
    changed = False
    for issue_code in required:
        if issue_code.value not in session.issues:
            session.issues[issue_code.value] = IssueState(issue=issue_code.value)
            changed = True

    if session.environment.location.lower() == "habitable" and IssueCode.TOX.value not in session.issues:
        session.issues[IssueCode.TOX.value] = IssueState(issue=IssueCode.TOX.value)
        changed = True

    return changed


def _auto_seed_issue_answers(session: MatchmakerSession) -> bool:
    """Seed deterministic gate answers from environment and evaluate outcomes.

    This avoids every issue showing as pending on load while preserving
    user-entered answers/rationales (existing answers are never overwritten).
    """

    changed = False
    medium = (session.environment.medium or "").upper()
    o2_trigger = medium in {"GOX", "LOX", "O2", "OXYGEN", "ENRICHED_AIR", "ENRICHED_O2"} or session.environment.o2_percent >= 23.5
    h2_trigger = medium in {"GH2", "LH2", "HYDROGEN", "H2"}
    fluid_trigger = _needs_fluid_compatibility(session.environment.medium)
    habitable = session.environment.location.lower() == "habitable"

    seeds: dict[str, tuple[str, str]] = {
        IssueCode.O2.value: ("Q0", "Yes" if o2_trigger else "No"),
        IssueCode.HEE.value: ("Q0", "Yes" if h2_trigger else "No"),
        IssueCode.FLUID.value: ("Q0", "Yes" if fluid_trigger else "No"),
        IssueCode.TOX.value: ("Q1", "Yes" if habitable else "No"),
    }

    for issue_key, (question_id, answer) in seeds.items():
        state = session.issues.get(issue_key)
        if state is None or state.out_of_scope:
            continue
        if question_id in state.answers:
            continue

        state.answers[question_id] = answer
        state.last_question_id = question_id
        session.events.append(
            MatchmakerEvent(
                action="auto_answer_seeded",
                issue=issue_key,
                question=question_id,
                answer=answer,
                note="Derived from environment at load time",
                rule_pack_version=_RULE_PACK_VERSION,
            )
        )
        _apply_evaluation(issue_key, state, selected_code=None, session=session)
        session.issues[issue_key] = state
        changed = True

    for issue_key, state in session.issues.items():
        if state.out_of_scope or not is_auto_scope_issue(issue_key):
            continue
        if state.status == IssueStatus.PENDING:
            state.status = IssueStatus.IN_PROGRESS
            changed = True

    return changed


def _needs_fluid_compatibility(medium: str) -> bool:
    text = (medium or "").upper().strip()
    if text in {"", "AIR", "STANDARD_AIR", "CABIN_AIR"}:
        return False
    keywords = ("HYDRAZINE", "MMH", "UDMH", "NTO", "N2O4", "PROPELLANT", "OXIDIZER", "FUEL")
    return any(keyword in text for keyword in keywords) or text not in {"AIR", ""}


def _auto_seed_from_trigger_signature(session: MatchmakerSession, trigger_signature: str) -> bool:
    """Apply MIUL trigger signature to pre-resolve rating-based domains."""

    ratings = _parse_trigger_signature(trigger_signature)
    if not ratings:
        return False

    changed = False
    rating_domains = (
        IssueCode.FLAM,
        IssueCode.SCC,
        IssueCode.CORR,
        IssueCode.TVS,
        IssueCode.TOX,
        IssueCode.FLUID,
    )

    for issue_code in rating_domains:
        key = issue_code.value
        state = session.issues.get(key)
        if state is None or state.out_of_scope:
            continue

        rating = ratings.get(issue_code)
        if rating:
            if issue_code == IssueCode.FLAM and state.answers.get("Q1") is None:
                state.answers["Q1"] = rating
                state.last_question_id = "Q1"
                _apply_evaluation(key, state, selected_code=None, session=session)
                changed = True
                session.issues[key] = state
                continue

            if state.outcome == IssueOutcome.PASS:
                state.outcome = None
                state.selected_code = None
                state.candidate_codes = []
                state.answers.pop("_resolved_cat3_code", None)
            if state.status != IssueStatus.IN_PROGRESS:
                state.status = IssueStatus.IN_PROGRESS
                changed = True
            trigger_note = f"MIUL trigger rating: {rating}"
            if trigger_note not in state.warnings:
                state.warnings.append(trigger_note)
                changed = True
            session.issues[key] = state
            continue

        if state.outcome is None:
            state.outcome = IssueOutcome.PASS
            state.status = IssueStatus.DONE
            state.selected_code = None
            state.candidate_codes = []
            state.answers.pop("_resolved_cat3_code", None)
            session.issues[key] = state
            changed = True

    if changed:
        session.events.append(
            MatchmakerEvent(
                action="miul_signature_applied",
                note=trigger_signature,
                rule_pack_version=_RULE_PACK_VERSION,
            )
        )
    return changed


def _parse_trigger_signature(trigger_signature: str) -> dict[IssueCode, str]:
    mapping = {
        "FLAM": IssueCode.FLAM,
        "SCC": IssueCode.SCC,
        "CORR": IssueCode.CORR,
        "TVS": IssueCode.TVS,
        "TOX": IssueCode.TOX,
        "OFFGAS": IssueCode.TOX,
        "FS": IssueCode.FLUID,
        "FLUID": IssueCode.FLUID,
    }
    out: dict[IssueCode, str] = {}
    for token in str(trigger_signature or "").split("|"):
        piece = token.strip()
        if ":" not in piece:
            continue
        raw_issue, raw_rating = piece.split(":", 1)
        issue = mapping.get(raw_issue.strip().upper())
        rating = raw_rating.strip().upper()
        if issue is None or not rating:
            continue
        out[issue] = rating
    return out


def _dedupe_blockers(blockers: list[ExportBlocker]) -> list[ExportBlocker]:
    seen: set[str] = set()
    unique: list[ExportBlocker] = []
    for blocker in blockers:
        key = f"{blocker.issue}|{blocker.status}|{blocker.reason}"
        if key in seen:
            continue
        seen.add(key)
        unique.append(blocker)
    return unique
