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

Co-Authored-By: Atlas (OpenAI GPT-5) <noreply@openai.com>
"""

from __future__ import annotations

import asyncio
import logging
import math
import re
from collections import Counter
from datetime import datetime
from functools import lru_cache
from typing import Optional

from fastapi import APIRouter, File, HTTPException, Query, Request, UploadFile
from pydantic import BaseModel, Field

from mira.api.auth import authorize_owner_or_admin, get_request_user
from mira.mua.v7.models import (
    CategoryRoutingResult,
    Center,
    EvidenceStrengthBand,
    FinalizedMUA,
    InvestigationResult,
    MaterialResolution,
    MUADraft,
    ReviewDecisions,
    SessionStatus,
    StepName,
    # Request / Response models
    ResolveMaterialRequest,
    ResolveMaterialResponse,
    InvestigateRequest,
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

from mira.api.routers.mua_v7_models import (
    SessionSummary,
    SessionListResponse,
    SessionDetailResponse,
    DeleteSessionResponse,
    StatsResponse,
    InvestigateKickoffResponse,
    InvestigationStatusResponse,
    MIULImportBucket,
    MIULImportResponse,
    MaterialIntelRequest,
    MaterialStatsItem,
    MaterialCoverageStats,
    MaterialIntelCandidate,
    MaterialDisambiguationOption,
    MaterialDisambiguationQuestion,
    MaterialIntelResponse,
    PreviewIssuesRequest,
    IssueCodeInfo,
    PreviewIssuesResponse,
    _FORM_PATTERNS,
    _CONDITION_PATTERN,
    _TEMPER_PATTERN,
    _MATERIAL_KEYWORD_PATTERN,
    _ISSUE_LABELS,
)
from mira.api.routers.mua_v7_helpers import (
    issues_from_signature as _issues_from_signature,
    suggest_environment_from_bucket as _suggest_environment_from_bucket,
    category_hint_for_bucket as _category_hint_for_bucket,
    classify_medium_text as _classify_medium_text,
    get_db_params_cached as _get_db_params_cached,
    open_maptis_connection as _open_maptis_connection,
    lookup_fs_media_context as _lookup_fs_media_context,
    usage_medium_class as _usage_medium_class,
    adjust_fs_issue_scope as _adjust_fs_issue_scope,
    infer_env_type as _infer_env_type,
    detect_divergence as _detect_divergence,
    build_audit_trail as _build_audit_trail,
    generate_export_text as _generate_export_text,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

router = APIRouter(tags=["MUA v7"])

# ---------------------------------------------------------------------------
# Module-level service instances
# ---------------------------------------------------------------------------

session_manager = SessionManager()
investigator = MUAInvestigator()
draft_renderer = DraftRenderer()
fact_checker = FactChecker()
category_router = CategoryRouter()
qualification_plan_generator = QualificationPlanGenerator()

# In-progress investigation tracking (transient, not persisted).
# Keyed by session_id.  Cleaned up after status is consumed.
# Protected by _progress_lock to prevent race conditions when
# concurrent requests read/write investigation state.
_investigation_progress: dict[str, dict] = {}
_progress_lock = asyncio.Lock()

# Minimum explicit human-review share across precedent decisions.
# WHY 0.20: At least 20% of precedent decisions must be explicitly reviewed
# by the engineer (not auto-accepted). Below this threshold the wizard
# flags "rubber-stamping" in the audit trail. Calibrated with MSFC M&P
# engineers — 20% catches inattentive reviews without blocking batch workflows.
_MIN_HITL_PRECEDENT_FRACTION = 0.20

# ---------------------------------------------------------------------------
# Router-local response models — extracted to mua_v7_models.py
# ---------------------------------------------------------------------------



# MIUL/env/DB helpers — extracted to mua_v7_helpers.py



async def _require_owned_session(session_id: str, http_request: Request):
    session = await session_manager.aget_session(session_id)
    if session is None:
        raise HTTPException(
            status_code=404,
            detail=f"Session '{session_id}' not found.",
        )
    authorize_owner_or_admin(
        http_request,
        getattr(session, "created_by", None),
        resource_label="mua v7 session",
    )
    return session



# FS media context, usage_medium_class, adjust_fs_issue_scope — extracted to mua_v7_helpers.py



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
# Step 1a: Material Intel (candidate differences + precedent coverage)
# ---------------------------------------------------------------------------



# MaterialIntel models and regex patterns — extracted to mua_v7_models.py




def _canonicalize_label(text: str) -> str:
    return re.sub(r"[^A-Z0-9]+", "", (text or "").upper())


def _infer_family_from_text(text: str) -> Optional[str]:
    upper = (text or "").upper()
    if any(k in upper for k in ("STAINLESS", "CRES", "SST")):
        return "stainless"
    if any(k in upper for k in ("ALUMINUM", "ALUMINIUM")):
        return "aluminum"
    if any(k in upper for k in ("TITANIUM", "TI-")):
        return "titanium"
    if any(k in upper for k in ("INCONEL", "HASTELLOY", "MONEL", "NICKEL")):
        return "nickel"
    if "STEEL" in upper:
        return "steel"
    return None


def _infer_form(designation: str) -> Optional[str]:
    for form, pattern in _FORM_PATTERNS:
        if pattern.search(designation or ""):
            return form
    return None


def _infer_condition(designation: str) -> Optional[str]:
    text = designation or ""
    temper = _TEMPER_PATTERN.search(text)
    if temper:
        return temper.group(1).upper()
    cond = _CONDITION_PATTERN.search(text)
    if cond:
        return cond.group(1).upper()
    return None


def _is_mixed_record(text: str) -> bool:
    if "/" not in (text or ""):
        return False
    parts = [p.strip() for p in text.split("/") if p.strip()]
    if len(parts) < 2:
        return False
    signal_parts = sum(1 for p in parts if _MATERIAL_KEYWORD_PATTERN.search(p))
    return signal_parts >= 2


def _extract_search_tokens(designation: str) -> list[str]:
    tokens: list[str] = []
    text = (designation or "").upper()

    for uns in re.findall(r"\b[ACGKMNRSTW]\d{5}\b", text):
        tokens.append(uns)

    for token in re.findall(r"\b(A-?286|[1-9]\d{2,4}[A-Z]?)\b", text):
        if token in {"2026"}:
            continue
        tokens.append(token)

    seen: set[str] = set()
    deduped: list[str] = []
    for token in tokens:
        if token not in seen:
            seen.add(token)
            deduped.append(token)
    return deduped[:5]


def _family_sql_pattern(family: Optional[str]) -> Optional[str]:
    fam = (family or "").lower()
    if fam == "stainless":
        return r"\y(STAINLESS|CRES|SST|SS)\y"
    if fam == "aluminum":
        return r"\y(ALUMINUM|ALUMINIUM|AL)\y"
    if fam == "nickel":
        return r"\y(INCONEL|HASTELLOY|MONEL|NICKEL)\y"
    if fam == "titanium":
        return r"\y(TITANIUM|TI)\y"
    if fam == "steel":
        return r"\ySTEEL\y"
    return None


def _estimate_mua_coverage(
    cursor,
    *,
    material_code: str,
    designation: str,
    family: Optional[str],
) -> MaterialCoverageStats:
    """Estimate precedent coverage by matching candidate identity to precedent text."""
    if not material_code and not designation:
        return MaterialCoverageStats(query_mode="none")

    token_clauses: list[str] = []
    params: list[str] = []

    if material_code:
        token_clauses.append(
            "(COALESCE(specification, '') ILIKE %s OR COALESCE(material_designation, '') ILIKE %s)"
        )
        params.extend([f"%{material_code}%", f"%{material_code}%"])

    for token in _extract_search_tokens(designation):
        pattern = rf"\y{re.escape(token)}\y"
        token_clauses.append(
            "(COALESCE(material_designation, '') ~* %s OR COALESCE(specification, '') ~* %s)"
        )
        params.extend([pattern, pattern])

    if not token_clauses:
        return MaterialCoverageStats(query_mode="none")

    where_sql = "(" + " OR ".join(token_clauses) + ")"
    fam_pattern = _family_sql_pattern(family)
    if fam_pattern:
        where_sql += " AND (COALESCE(material_family, '') ~* %s OR COALESCE(material_designation, '') ~* %s)"
        params.extend([fam_pattern, fam_pattern])

    cursor.execute(
        f"""
        SELECT mua_number, determination, issues, env_type
        FROM mua_precedents_v7
        WHERE {where_sql}
        LIMIT 2000
        """,
        params,
    )
    rows = cursor.fetchall() or []

    determination_counts = Counter((row.get("determination") or "UNKNOWN").upper() for row in rows)
    issue_counts: Counter[str] = Counter()
    env_counts: Counter[str] = Counter()
    for row in rows:
        for issue in row.get("issues") or []:
            issue_counts[str(issue)] += 1
        env_counts[str(row.get("env_type") or "UNKNOWN")] += 1

    return MaterialCoverageStats(
        query_mode="code_and_token",
        total_muas=len(rows),
        approved=determination_counts.get("APPROVED", 0),
        conditional=determination_counts.get("APPROVED_WITH_LIMITS", 0),
        rejected=determination_counts.get("REJECTED", 0),
        deferred=determination_counts.get("DEFERRED", 0) + determination_counts.get("TESTING_REQUIRED", 0),
        top_issues=[MaterialStatsItem(label=k, count=v) for k, v in issue_counts.most_common(5)],
        top_env_types=[MaterialStatsItem(label=k, count=v) for k, v in env_counts.most_common(5)],
        sample_muas=[str(row.get("mua_number") or "") for row in rows[:5] if row.get("mua_number")],
    )


def _annotate_candidate_differences(candidates: list[MaterialIntelCandidate]) -> None:
    if not candidates:
        return
    baseline = candidates[0]
    for idx, candidate in enumerate(candidates):
        diffs: list[str] = []
        if candidate.is_mixed_record:
            diffs.append("Mixed-material record ('/').")
        if idx > 0:
            if candidate.form and candidate.form != baseline.form:
                diffs.append(f"Form differs from top candidate ({candidate.form} vs {baseline.form or 'unspecified'}).")
            if candidate.condition and candidate.condition != baseline.condition:
                diffs.append(
                    f"Condition differs ({candidate.condition} vs {baseline.condition or 'unspecified'})."
                )
            if candidate.family and candidate.family != baseline.family:
                diffs.append(f"Family differs ({candidate.family} vs {baseline.family or 'unknown'}).")
            if candidate.coverage.total_muas < baseline.coverage.total_muas:
                diffs.append(
                    f"Lower precedent coverage ({candidate.coverage.total_muas} vs {baseline.coverage.total_muas})."
                )
        candidate.differences = diffs


_FILTER_KEYS = {"family", "form", "condition", "mixed"}


def _normalize_material_filters(raw_filters: dict[str, str]) -> dict[str, str]:
    normalized: dict[str, str] = {}
    for key, value in (raw_filters or {}).items():
        k = str(key or "").strip().lower()
        v = str(value or "").strip()
        if not k or not v or k not in _FILTER_KEYS:
            continue

        if k in {"family", "form"}:
            normalized[k] = v.lower()
        elif k == "condition":
            normalized[k] = v.upper()
        elif k == "mixed":
            low = v.lower()
            if low in {"yes", "true", "mixed", "1"}:
                normalized[k] = "yes"
            elif low in {"no", "false", "single", "0"}:
                normalized[k] = "no"
    return normalized


def _candidate_filter_value(candidate: MaterialIntelCandidate, key: str) -> Optional[str]:
    if key == "family":
        return (candidate.family or "").lower() or None
    if key == "form":
        return (candidate.form or "").lower() or None
    if key == "condition":
        return (candidate.condition or "").upper() or None
    if key == "mixed":
        return "yes" if candidate.is_mixed_record else "no"
    return None


def _candidate_matches_filter(candidate: MaterialIntelCandidate, key: str, value: str) -> bool:
    candidate_value = _candidate_filter_value(candidate, key)
    if candidate_value is None:
        return False
    if key == "condition":
        lhs = candidate_value.replace("CONDITION ", "")
        rhs = value.replace("CONDITION ", "")
        return lhs == rhs or candidate_value == value
    return candidate_value == value


def _apply_candidate_filters(
    candidates: list[MaterialIntelCandidate],
    filters: dict[str, str],
    *,
    exclude_key: Optional[str] = None,
) -> list[MaterialIntelCandidate]:
    if not filters:
        return list(candidates)

    filtered: list[MaterialIntelCandidate] = []
    for candidate in candidates:
        keep = True
        for key, value in filters.items():
            if exclude_key and key == exclude_key:
                continue
            if not _candidate_matches_filter(candidate, key, value):
                keep = False
                break
        if keep:
            filtered.append(candidate)
    return filtered


def _build_disambiguation_questions(
    all_candidates: list[MaterialIntelCandidate],
    active_filters: dict[str, str],
) -> list[MaterialDisambiguationQuestion]:
    if not all_candidates:
        return []

    question_specs: list[tuple[str, str]] = [
        ("form", "What material form is this part?"),
        ("condition", "Do you know the temper/condition?"),
        ("family", "Which material family matches the callout?"),
        ("mixed", "Is this a mixed-material MAPTIS record?"),
    ]

    questions: list[MaterialDisambiguationQuestion] = []
    for key, prompt in question_specs:
        base_pool = _apply_candidate_filters(all_candidates, active_filters, exclude_key=key)
        if not base_pool:
            continue

        option_counts: Counter[str] = Counter()
        for candidate in base_pool:
            value = _candidate_filter_value(candidate, key)
            if value:
                option_counts[value] += 1

        if len(option_counts) <= 1 and key not in active_filters:
            continue

        options: list[MaterialDisambiguationOption] = []
        for value, count in option_counts.most_common():
            if key == "mixed":
                label = "Mixed-material record" if value == "yes" else "Single-material record"
            else:
                label = value
            options.append(
                MaterialDisambiguationOption(value=value, label=label, candidate_count=count)
            )

        questions.append(
            MaterialDisambiguationQuestion(
                key=key,
                prompt=prompt,
                options=options[:10],
                selected_value=active_filters.get(key),
            )
        )

    return questions



@router.post(
    "/material-intel",
    response_model=MaterialIntelResponse,
    summary="Step 1a: Explain candidate differences and precedent coverage",
)
async def material_intel_endpoint(request: MaterialIntelRequest) -> MaterialIntelResponse:
    material_text = (request.material or "").strip()
    requested_code = (request.material_code or "").strip()

    if not material_text and not requested_code:
        raise HTTPException(status_code=400, detail="Provide material text or material_code.")

    lookup_text = material_text or requested_code
    resolution = resolve_material(lookup_text)

    notes: list[str] = [
        "Coverage uses precedent-text token matching (estimate), not a strict material_code foreign key.",
        "Candidates are ranked by exact designation match, token overlap, resolver score, then precedent coverage.",
    ]
    if resolution.selection_method == "multi_material_detected":
        notes.append("Multiple materials detected. Select the exact subject material before investigate.")

    suggestion_rows = resolution.suggestions[: request.top_n]
    by_code: dict[str, dict] = {}
    for row in suggestion_rows:
        code = str(row.get("material_code") or row.get("spec") or "").strip()
        if not code:
            continue
        by_code.setdefault(code, row)

    if resolution.material_code:
        code = str(resolution.material_code).strip()
        by_code.setdefault(
            code,
            {
                "material_code": code,
                "material_key": resolution.material_key,
                "name": resolution.resolved_name or resolution.input_text,
                "score": 1.0,
            },
        )
    if requested_code:
        by_code.setdefault(
            requested_code,
            {
                "material_code": requested_code,
                "material_key": None,
                "name": requested_code,
                "score": 1.0,
            },
        )

    candidate_codes = list(by_code.keys())[: request.top_n]
    candidates: list[MaterialIntelCandidate] = []

    if candidate_codes:
        try:
            import psycopg2
            from psycopg2.extras import RealDictCursor
            from mira.core.db_config import get_db_connection_params

            with _open_maptis_connection() as conn:
                with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                    cursor.execute(
                        """
                        SELECT material_code, material_key, designation
                        FROM materials
                        WHERE material_code = ANY(%s)
                        """,
                        (candidate_codes,),
                    )
                    material_rows = {
                        str(row["material_code"]): row
                        for row in cursor.fetchall()
                        if row.get("material_code")
                    }

                    for code in candidate_codes:
                        seed = by_code.get(code, {})
                        row = material_rows.get(code, {})
                        designation = str(
                            row.get("designation")
                            or seed.get("name")
                            or seed.get("canonical_name")
                            or code
                        )
                        family = _infer_family_from_text(designation) or resolution.family
                        coverage = _estimate_mua_coverage(
                            cursor,
                            material_code=code,
                            designation=designation,
                            family=family,
                        )
                        candidates.append(
                            MaterialIntelCandidate(
                                material_code=code,
                                material_key=row.get("material_key") or seed.get("material_key"),
                                designation=designation,
                                score=float(seed.get("score") or seed.get("similarity") or 0.0),
                                family=family,
                                form=_infer_form(designation),
                                condition=_infer_condition(designation),
                                is_mixed_record=_is_mixed_record(designation),
                                coverage=coverage,
                            )
                        )
        except Exception:
            logger.exception("material-intel DB enrichment failed for %r", lookup_text)
            notes.append("DB enrichment unavailable; showing unresolved candidate metadata only.")
            for code in candidate_codes:
                seed = by_code.get(code, {})
                designation = str(seed.get("name") or seed.get("canonical_name") or code)
                candidates.append(
                    MaterialIntelCandidate(
                        material_code=code,
                        material_key=seed.get("material_key"),
                        designation=designation,
                        score=float(seed.get("score") or seed.get("similarity") or 0.0),
                        family=_infer_family_from_text(designation) or resolution.family,
                        form=_infer_form(designation),
                        condition=_infer_condition(designation),
                        is_mixed_record=_is_mixed_record(designation),
                    )
                )

    query_canonical = _canonicalize_label(lookup_text)
    query_tokens = set(_extract_search_tokens(lookup_text))

    def _candidate_rank(candidate: MaterialIntelCandidate) -> tuple[int, int, float, int]:
        designation_canonical = _canonicalize_label(candidate.designation)
        exact_match = int(bool(query_canonical) and designation_canonical == query_canonical)
        overlap = 0
        if query_tokens:
            overlap = len(query_tokens.intersection(_extract_search_tokens(candidate.designation)))
        return (exact_match, overlap, candidate.score, candidate.coverage.total_muas)

    candidates.sort(key=_candidate_rank, reverse=True)
    _annotate_candidate_differences(candidates)

    initial_candidate_count = len(candidates)
    active_filters = _normalize_material_filters(request.filters)
    filtered_candidates = _apply_candidate_filters(candidates, active_filters)
    questions = _build_disambiguation_questions(candidates, active_filters)

    if active_filters and not filtered_candidates:
        notes.append("Selected filters returned no matches. Adjust one filter to continue narrowing.")

    return MaterialIntelResponse(
        resolution=resolution,
        mixed_input=(resolution.selection_method == "multi_material_detected"),
        initial_candidate_count=initial_candidate_count,
        candidate_count=len(filtered_candidates),
        candidates=filtered_candidates,
        active_filters=active_filters,
        disambiguation_questions=questions,
        notes=notes,
    )


# ---------------------------------------------------------------------------
# Step 1b: Preview issue codes (live, from environment fields)
# ---------------------------------------------------------------------------



# PreviewIssues models and _ISSUE_LABELS — extracted to mua_v7_models.py



@router.post(
    "/preview-issues",
    response_model=PreviewIssuesResponse,
    summary="Preview auto-detected issue codes from environment",
)
async def preview_issues_endpoint(request: PreviewIssuesRequest) -> PreviewIssuesResponse:
    """Return the issue codes the system would auto-detect for this environment.

    Called by the Define step as the engineer fills in environment fields,
    so they can see and override which MAPTIS issues will drive the search.
    """
    from mira.mua.v7.models import EnvironmentSpec

    env = EnvironmentSpec(
        o2_percent=request.o2_percent,
        pressure_psia=request.pressure_psia,
        temp_min_f=request.temp_min_f,
        temp_max_f=request.temp_max_f,
        medium=request.medium,
        location=request.location,
        application="",
    )
    auto_codes = MUAInvestigator._derive_issues_from_env(env)
    return PreviewIssuesResponse(
        issues=[
            IssueCodeInfo(
                code=code,
                label=_ISSUE_LABELS.get(code, code),
                auto_detected=True,
            )
            for code in auto_codes
        ]
    )


@router.post(
    "/import-miul",
    response_model=MIULImportResponse,
    summary="Step 0: Import MIUL workbook and build MUA trigger buckets",
)
async def import_miul_endpoint(
    file: UploadFile = File(...),
) -> MIULImportResponse:
    """Import MIUL workbook, detect non-A triggers, and return bucketed queue.

    The response is designed to seed MUA Define step inputs:
    - suggested material code/designation
    - suggested environment
    - issue codes from trigger signature
    """
    if not file.filename.lower().endswith(".xlsx"):
        raise HTTPException(status_code=400, detail="Only .xlsx files are supported.")

    try:
        from mira.miul.mua_trigger_analyzer import (
            analyze_miul_bytes,
            build_trigger_buckets,
        )

        content = await file.read()
        if not content:
            raise HTTPException(status_code=400, detail="Uploaded file is empty.")

        analysis = analyze_miul_bytes(
            content, workbook_name=file.filename, sheet_name="MIUL"
        )
        buckets = build_trigger_buckets(analysis)

        # Index part records by material+signature+environment bucket id
        by_bucket_id: dict[str, list[dict]] = {}
        for p in analysis.get("part_triggers", []):
            triggers = p.get("triggers", [])
            signature = "|".join(
                sorted(f"{t['issue']}:{t['rating']}" for t in triggers)
            )
            env = str(p.get("environment") or "")
            code = str(p.get("material_code") or "(missing)")
            bucket_id = f"{code}::{signature}::{env}"
            by_bucket_id.setdefault(bucket_id, []).append(p)

        out_buckets: list[MIULImportBucket] = []
        for bucket in buckets.get("material_signature_buckets", []):
            bucket_id = bucket["bucket_id"]
            bucket_parts = by_bucket_id.get(bucket_id, [])
            issues = _issues_from_signature(bucket.get("trigger_signature", ""))

            designations = bucket.get("designations", {}) or {}
            suggested_material = (
                next(iter(designations.keys()))
                if designations
                else str(bucket.get("material_code") or "")
            )
            suggested_environment = _suggest_environment_from_bucket(bucket)
            fluid_types = sorted((bucket.get("fluid_types") or {}).keys())
            issues, fs_scope_reasons = _adjust_fs_issue_scope(
                str(bucket.get("material_code") or ""),
                issues,
                env_raw=str(bucket.get("environment") or ""),
                suggested_env=suggested_environment,
                fluid_types=fluid_types,
            )
            likely_category, reasons = _category_hint_for_bucket(bucket, issues)
            reasons.extend(fs_scope_reasons)

            sample_pns = [
                str(p.get("part_number"))
                for p in bucket_parts[:8]
                if p.get("part_number")
            ]
            sample_desc = [
                str(p.get("part_description"))
                for p in bucket_parts[:5]
                if p.get("part_description")
            ]
            out_buckets.append(
                MIULImportBucket(
                    bucket_id=bucket_id,
                    material_code=str(bucket.get("material_code") or ""),
                    suggested_material=suggested_material,
                    trigger_signature=str(bucket.get("trigger_signature") or ""),
                    issue_codes=issues,
                    environment_raw=str(bucket.get("environment") or ""),
                    part_count=int(bucket.get("part_count", 0)),
                    risk_band=str(bucket.get("risk_band") or "low"),
                    likely_category=likely_category,
                    category_reasons=reasons,
                    fluid_types=fluid_types,
                    sample_part_numbers=sample_pns,
                    sample_part_descriptions=sample_desc,
                    suggested_environment=suggested_environment,
                )
            )

        out_buckets.sort(
            key=lambda b: (-b.part_count, b.material_code, b.trigger_signature)
        )
        return MIULImportResponse(
            filename=file.filename,
            total_parts=int(analysis.get("total_parts", 0)),
            non_a_parts=int(analysis.get("non_a_parts", 0)),
            bucket_count=len(out_buckets),
            buckets=out_buckets[:200],
        )
    except HTTPException:
        raise
    except Exception:
        logger.exception("Failed to import MIUL workbook '%s'", file.filename)
        raise HTTPException(
            status_code=500,
            detail="Failed to parse MIUL workbook. Confirm it includes a 'MIUL' sheet.",
        )


# ---------------------------------------------------------------------------
# Step 2: Investigate
# ---------------------------------------------------------------------------


@router.post(
    "/investigate",
    response_model=InvestigateKickoffResponse,
    summary="Step 2: Start async evidence gathering",
)
async def investigate_endpoint(
    request: InvestigateRequest,
    http_request: Request,
) -> InvestigateKickoffResponse:
    """Start the investigation pipeline asynchronously.

    Returns immediately with the session ID.  The investigation runs in
    the background.  Poll ``GET /session/{id}/status`` every 3 seconds
    for progress updates.  Typically completes in 15-30 seconds.
    """
    logger.info(
        "Step 2 -- investigate (async): session_id=%s, material='%s', center=%s",
        request.session_id,
        request.material,
        request.center,
    )

    # Auto-create session if none provided, or if the provided one is stale
    # (in-memory sessions are lost on server restart).
    session_id = request.session_id
    actor = get_request_user(http_request)
    actor_name = (actor.username if actor else None) or getattr(request, "created_by", None)
    if not session_id:
        session = await session_manager.acreate_session(
            created_by=actor_name,
            center=request.center,
        )
        session_id = session.session_id
    else:
        session = await session_manager.aget_session(session_id)
        if session is None:
            # Stale session ID (e.g. server restarted) -- create a fresh one.
            logger.warning(
                "Session '%s' not found (stale?). Creating new session.",
                session_id,
            )
            session = await session_manager.acreate_session(
                created_by=actor_name,
                center=request.center,
            )
            session_id = session.session_id
        else:
            authorize_owner_or_admin(
                http_request,
                getattr(session, "created_by", None),
                resource_label="mua v7 session",
            )

    current_step = await session_manager.aget_current_step(session_id)
    if current_step not in (StepName.DEFINE, StepName.INVESTIGATE):
        raise HTTPException(
            status_code=400,
            detail=(
                f"Session is at step '{current_step}'. "
                f"Investigation requires DEFINE or INVESTIGATE step."
            ),
        )

    # Resolve material before launching the background task (fast).
    resolution = resolve_material(
        request.material,
        preferred_code=request.material_code,
        preferred_name=request.resolved_name,
        preferred_key=request.material_key,
    )

    # Store define inputs so the step gate passes.
    await session_manager.astore_define_inputs(
        session_id,
        material_resolution=resolution,
        environment=request.environment,
        process_params=request.process_params,
        material_input=request.material,
        application=request.environment.application,
        program=getattr(request, 'program', None),
        hardware=getattr(request, 'hardware', None),
        miul_ref=getattr(request, 'miul_ref', None),
        approved_cat3_codes=getattr(request, 'approved_cat3_codes', None),
    )

    # Initialize progress tracking and launch background task.
    _investigation_progress[session_id] = {
        "status": "investigating",
        "progress": 5,
    }

    asyncio.create_task(
        _run_investigation_background(
            session_id=session_id,
            material=resolution,
            environment=request.environment,
            process_params=request.process_params,
            center=request.center,
            issue_codes=request.issue_codes,
            approved_cat3_codes=request.approved_cat3_codes,
        )
    )

    logger.info(
        "Step 2 -- investigate: async task launched for session '%s'.",
        session_id,
    )

    return InvestigateKickoffResponse(session_id=session_id)


async def _run_investigation_background(
    *,
    session_id: str,
    material: "MaterialResolution",
    environment: "EnvironmentSpec",
    process_params: "Optional[ProcessParams]",
    center: "Center",
    issue_codes: "Optional[list[str]]" = None,
    approved_cat3_codes: "Optional[list[str]]" = None,
) -> None:
    """Background coroutine that runs the 10-phase investigation pipeline.

    Updates ``_investigation_progress`` as it runs so the polling
    endpoint can report progress to the frontend.
    """
    from mira.mua.v7.models import MaterialResolution, EnvironmentSpec, ProcessParams, Center

    try:
        _investigation_progress[session_id] = {
            "status": "investigating",
            "progress": 10,
        }

        investigation_result: InvestigationResult = await investigator.investigate(
            material=material,
            environment=environment,
            process_params=process_params,
            center=center,
            issue_codes=issue_codes,
            approved_cat3_codes=approved_cat3_codes,
        )

        # Store results and advance session step.
        await session_manager.astore_investigation(session_id, investigation_result)
        await session_manager.aadvance_step(session_id, StepName.INVESTIGATE)

        _investigation_progress[session_id] = {
            "status": "complete",
            "progress": 100,
        }

        logger.info(
            "Step 2 -- investigate: background task completed for session '%s'. "
            "precedents=%d supporting + %d conflicting, gaps=%d, conflicts=%d, "
            "strength=%s",
            session_id,
            len(investigation_result.supporting_precedents),
            len(investigation_result.conflicting_precedents),
            len(investigation_result.gaps),
            len(investigation_result.conflicts),
            investigation_result.evidence_strength.band,
        )

    except Exception as exc:
        logger.exception(
            "Step 2 -- investigate: background task FAILED for session '%s'",
            session_id,
        )
        _investigation_progress[session_id] = {
            "status": "failed",
            "progress": 0,
            "error": str(exc),
        }


# ---------------------------------------------------------------------------
# Step 2b: Poll investigation status
# ---------------------------------------------------------------------------


@router.get(
    "/session/{session_id}/status",
    response_model=InvestigationStatusResponse,
    summary="Poll investigation progress",
)
async def investigation_status_endpoint(
    session_id: str,
    http_request: Request,
) -> InvestigationStatusResponse:
    """Poll the status of a running investigation.

    Frontend should call this every 3 seconds after ``POST /investigate``
    returns.  Returns ``status='complete'`` once the investigation
    pipeline finishes and results are stored on the session.
    """
    session = await _require_owned_session(session_id, http_request)

    progress = _investigation_progress.get(session_id)

    if progress is not None:
        return InvestigationStatusResponse(
            session_id=session_id,
            status=progress["status"],
            progress=progress.get("progress", 0),
            current_step=await session_manager.aget_current_step(session_id),
            session_status=await session_manager.aget_status(session_id),
            error=progress.get("error"),
        )

    # No active tracking -- check if investigation was already completed.
    if session.investigation_result is not None:
        return InvestigationStatusResponse(
            session_id=session_id,
            status="complete",
            progress=100,
            current_step=await session_manager.aget_current_step(session_id),
            session_status=await session_manager.aget_status(session_id),
        )

    return InvestigationStatusResponse(
        session_id=session_id,
        status="idle",
        progress=0,
        current_step=await session_manager.aget_current_step(session_id),
        session_status=await session_manager.aget_status(session_id),
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
    http_request: Request,
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
    session = await _require_owned_session(request.session_id, http_request)

    current_step = await session_manager.aget_current_step(request.session_id)
    if current_step not in (StepName.INVESTIGATE, StepName.REVIEW):
        raise HTTPException(
            status_code=400,
            detail=(
                f"Session is at step '{current_step}'. "
                f"Review requires INVESTIGATE or REVIEW step."
            ),
        )

    # Retrieve the investigation to validate completeness.
    investigation = await session_manager.aget_investigation(request.session_id)
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

    # Human-in-the-loop floor:
    # require explicit human intervention on a minimum share of items that
    # genuinely need review (not every precedent row).
    review_required_precedent_ids = {
        p.mua_number
        for p in (
            investigation.supporting_precedents
            + investigation.conflicting_precedents
        )
        if p.is_conflicting or p.relevance_score < 0.4
    }
    total_review_items_for_hitl = (
        len(review_required_precedent_ids) + total_gaps + total_conflicts
    )
    required_human_reviews = (
        max(1, math.ceil(total_review_items_for_hitl * _MIN_HITL_PRECEDENT_FRACTION))
        if total_review_items_for_hitl > 0
        else 0
    )

    precedent_lookup = {
        p.mua_number: p
        for p in (
            investigation.supporting_precedents
            + investigation.conflicting_precedents
        )
    }
    human_touched_precedents = 0
    for pd in decisions.precedent_decisions:
        precedent = precedent_lookup.get(pd.mua_number)
        if precedent is None:
            continue

        default_decision = (
            "include_supporting"
            if precedent.is_supporting and precedent.relevance_score >= 0.7
            else "include_context"
        )
        decision_value = (
            pd.decision.value
            if hasattr(pd.decision, "value")
            else str(pd.decision)
        )
        has_rationale = bool((pd.rationale or "").strip())

        if decision_value != default_decision or has_rationale:
            human_touched_precedents += 1

    human_touched_total = (
        human_touched_precedents
        + len(decisions.gap_decisions)
        + len(decisions.conflict_decisions)
    )
    missing_human_reviews = max(0, required_human_reviews - human_touched_total)
    if all_items_reviewed and missing_human_reviews > 0:
        raise HTTPException(
            status_code=400,
            detail=(
                "Human-in-the-loop policy requires explicit review on at least "
                f"{required_human_reviews} items "
                f"({int(_MIN_HITL_PRECEDENT_FRACTION * 100)}% of "
                f"{total_review_items_for_hitl}). "
                f"Currently {human_touched_total} meet that threshold. "
                "Add rationale and/or override default decisions for additional precedents."
            ),
        )

    logger.info(
        "Step 3 -- HITL check: review_required_precedents=%d, gaps=%d, conflicts=%d, "
        "required=%d, touched=%d",
        len(review_required_precedent_ids),
        total_gaps,
        total_conflicts,
        required_human_reviews,
        human_touched_total,
    )

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
        # D-1: Divergence tracking is silent -- JSONB label only, no
        # user-facing text.  The flag is recorded on the session state
        # for audit purposes.
        logger.warning(
            "Step 3 -- divergence detected in session '%s': "
            "band=%s, engineer decisions diverge.",
            request.session_id,
            evidence_band,
        )

    # Store decisions and advance step.
    await session_manager.astore_review_decisions(request.session_id, decisions)
    await session_manager.aadvance_step(request.session_id, StepName.REVIEW)

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
    http_request: Request,
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
    session = await _require_owned_session(request.session_id, http_request)

    current_step = await session_manager.aget_current_step(request.session_id)
    if current_step != StepName.REVIEW:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Session is at step '{current_step}'. "
                f"Draft generation requires REVIEW step."
            ),
        )

    # All items must be reviewed before draft generation.
    review_decisions = await session_manager.aget_review_decisions(request.session_id)
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

    investigation = await session_manager.aget_investigation(request.session_id)
    if investigation is None:
        raise HTTPException(
            status_code=400,
            detail="No investigation found for this session.",
        )

    # Step 4a: Route to MUA category.
    try:
        routing_result: CategoryRoutingResult = category_router.route(
            environment=investigation.environment,
            test_data=investigation.test_data,
            gaps=investigation.gaps,
            material_resolution=investigation.material,
            engineer_notes=investigation.environment.application or "",
            approved_appendix_b_codes=(
                await session_manager.aget_approved_cat3_codes(request.session_id)
            ),
        )
    except Exception:
        logger.exception(
            "Category routing failed for session '%s'", request.session_id
        )
        raise HTTPException(
            status_code=500,
            detail="Internal error during category routing.",
        )

    # Step 4b: Render the draft document (template layer -- deterministic).
    try:
        draft: MUADraft = draft_renderer.render(
            investigation=investigation,
            review_decisions=review_decisions,
            category_routing=routing_result,
        )
    except Exception:
        logger.exception(
            "Draft rendering failed for session '%s'", request.session_id
        )
        raise HTTPException(
            status_code=500,
            detail="Internal error during draft rendering.",
        )

    # Step 4b½: LLM polish (optional -- falls back to template on failure).
    try:
        from mira.mua.v7.draft_polish import polish_rationale

        mat = investigation.material
        # Use the resolved family name (e.g. "aluminum") which maps to PG
        # canonical families (ALUMINUM, NICKEL_ALLOY, etc.).
        material_family = (
            mat.family.upper() if mat.family else (
                mat.material_class.value.upper()
                if mat.material_class
                else None
            )
        )
        env_type = _infer_env_type(investigation.environment)

        draft = polish_rationale(
            draft,
            material_family=material_family,
            env_type=env_type,
        )
    except Exception:
        # Layer 2 failure is non-fatal -- template ships.
        logger.warning(
            "LLM polish failed for session '%s' -- using template.",
            request.session_id,
            exc_info=True,
        )

    # Step 4c: Fact-check the draft.
    try:
        fact_check_results = fact_checker.check_draft(
            draft=draft,
            investigation=investigation,
            review_decisions=review_decisions,
            category_routing=routing_result,
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
    await session_manager.astore_draft(request.session_id, draft)
    await session_manager.aadvance_step(request.session_id, StepName.DRAFT)
    await session_manager.aupdate_status(
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
    http_request: Request,
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
    session = await _require_owned_session(request.session_id, http_request)

    current_step = await session_manager.aget_current_step(request.session_id)
    if current_step != StepName.DRAFT:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Session is at step '{current_step}'. "
                f"Finalization requires DRAFT step."
            ),
        )

    # Gather all session artifacts.
    investigation = await session_manager.aget_investigation(request.session_id)
    review_decisions = await session_manager.aget_review_decisions(request.session_id)
    draft = await session_manager.aget_draft(request.session_id)

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
    await session_manager.astore_finalized_mua(request.session_id, finalized_mua)
    await session_manager.aadvance_step(request.session_id, StepName.FINALIZE)
    await session_manager.aupdate_status(
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
async def get_session_endpoint(session_id: str, http_request: Request) -> SessionDetailResponse:
    """Retrieve full session state for resuming an in-progress MUA workflow."""
    logger.info("GET session: session_id=%s", session_id)

    session = await _require_owned_session(session_id, http_request)

    return SessionDetailResponse(
        session_id=session_id,
        current_step=await session_manager.aget_current_step(session_id),
        status=await session_manager.aget_status(session_id),
        material_input=await session_manager.aget_material_input(session_id),
        center=await session_manager.aget_center(session_id),
        created_by=await session_manager.aget_created_by(session_id),
        created_at=await session_manager.aget_created_at(session_id),
        updated_at=await session_manager.aget_updated_at(session_id),
        approved_cat3_codes=await session_manager.aget_approved_cat3_codes(session_id),
        investigation=await session_manager.aget_investigation(session_id),
        review_decisions=await session_manager.aget_review_decisions(session_id),
        draft=await session_manager.aget_draft(session_id),
        finalized_mua=await session_manager.aget_finalized_mua(session_id),
    )


@router.get(
    "/sessions",
    response_model=SessionListResponse,
    summary="List user sessions",
)
async def list_sessions_endpoint(
    http_request: Request,
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

    actor = get_request_user(http_request)
    if actor is not None and not actor.is_admin:
        created_by = (actor.username or actor.email or "").strip() or created_by

    try:
        sessions = await session_manager.alist_sessions(
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
    http_request: Request,
) -> DeleteSessionResponse:
    """Mark a session as ABANDONED.

    Abandoned sessions are retained for audit purposes but cannot be
    resumed or modified further.
    """
    logger.info("DELETE session: session_id=%s", session_id)

    session = await _require_owned_session(session_id, http_request)

    current_status = await session_manager.aget_status(session_id)
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

    await session_manager.aupdate_status(session_id, SessionStatus.ABANDONED)

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
        raw_stats = await session_manager.aget_stats()
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



# _infer_env_type — extracted to mua_v7_helpers.py




# _detect_divergence, _build_audit_trail, _generate_export_text
# extracted to mua_v7_helpers.py

