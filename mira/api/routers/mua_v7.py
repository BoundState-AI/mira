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
_investigation_progress: dict[str, dict] = {}

# Minimum explicit human-review share across precedent decisions.
_MIN_HITL_PRECEDENT_FRACTION = 0.20

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
    approved_cat3_codes: Optional[list[str]] = None
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


class InvestigateKickoffResponse(BaseModel):
    """Async kickoff response -- returned immediately when investigation starts."""

    session_id: str
    status: str = "investigating"


class InvestigationStatusResponse(BaseModel):
    """Lightweight polling response for investigation progress."""

    session_id: str
    status: str  # investigating | complete | failed | idle
    progress: int = 0
    current_step: Optional[StepName] = None
    session_status: Optional[SessionStatus] = None
    error: Optional[str] = None


class MIULImportBucket(BaseModel):
    bucket_id: str
    material_code: str
    suggested_material: str
    trigger_signature: str
    issue_codes: list[str] = Field(default_factory=list)
    environment_raw: str = ""
    part_count: int = 0
    risk_band: str = "low"
    likely_category: str = "II_or_III"
    category_reasons: list[str] = Field(default_factory=list)
    fluid_types: list[str] = Field(default_factory=list)
    sample_part_numbers: list[str] = Field(default_factory=list)
    sample_part_descriptions: list[str] = Field(default_factory=list)
    suggested_environment: dict = Field(default_factory=dict)


class MIULImportResponse(BaseModel):
    filename: str
    total_parts: int
    non_a_parts: int
    bucket_count: int
    buckets: list[MIULImportBucket]


def _issues_from_signature(signature: str) -> list[str]:
    issues: list[str] = []
    if not signature:
        return issues
    for token in signature.split("|"):
        if ":" not in token:
            continue
        issue = token.split(":", 1)[0].strip().upper()
        if issue and issue not in issues:
            issues.append(issue)
    return issues


def _suggest_environment_from_bucket(bucket: dict) -> dict:
    env_raw = str(bucket.get("environment") or "")
    env_upper = env_raw.upper()

    medium = "Air"
    o2_percent = 21.0
    location = "habitable"
    if "GH2" in env_upper or "LH2" in env_upper or "HYDROGEN" in env_upper:
        medium = "Hydrogen"
        o2_percent = 0.0
        location = "non-habitable"
    elif "GOX" in env_upper:
        medium = "GOX"
        o2_percent = 99.5
        location = "non-habitable"
    elif "LOX" in env_upper:
        medium = "LOX"
        o2_percent = 99.5
        location = "non-habitable"

    tmin = bucket.get("temp_min_f")
    tmax = bucket.get("temp_max_f")
    pmax = bucket.get("pressure_max_psia")
    return {
        "o2_percent": float(o2_percent),
        "pressure_psia": float(pmax) if pmax is not None else 14.7,
        "temp_min_f": float(tmin) if tmin is not None else 60.0,
        "temp_max_f": float(tmax) if tmax is not None else 85.0,
        "medium": medium,
        "location": location,
        "application": "",
    }


def _category_hint_for_bucket(bucket: dict, issues: list[str]) -> tuple[str, list[str]]:
    env_raw = str(bucket.get("environment") or "").upper()
    sig = str(bucket.get("trigger_signature") or "")
    risk = str(bucket.get("risk_band") or "low").lower()

    reasons: list[str] = []
    if "GOX" in env_raw or "LOX" in env_raw:
        reasons.append("Oxygen service detected from MIUL environment.")
        return "I_or_II", reasons
    if "GH2" in env_raw or "LH2" in env_raw:
        reasons.append("Hydrogen service detected from MIUL environment.")
        reasons.append("Many programs still close this via Category III rationale when approved in-plan.")
        return "III_or_II", reasons
    if any(code in sig for code in ("FLAM:C", "FLAM:D", "FLAM:X")):
        reasons.append("Non-A flammability rating requires engineering disposition.")
        return "II_or_III", reasons
    if risk == "high":
        reasons.append("High trigger-risk bucket; engineer review required.")
        return "II_or_III", reasons
    if issues and all(i in ("FS", "SCC", "CORR", "TVS", "TOX", "FLAM") for i in issues):
        reasons.append("Common repeat-trigger bucket suitable for batched MUA triage.")
        return "III_or_II", reasons
    return "II_or_III", ["Default non-A trigger path."]


def _classify_medium_text(value: str) -> str:
    text = (value or "").strip().upper()
    if not text:
        return "UNKNOWN"
    if any(
        k in text
        for k in (
            "HYDRAZINE",
            "N2H4",
            "MMH",
            "UDMH",
            "NTO",
            "N2O4",
            "DINITROGEN TETROXIDE",
        )
    ):
        return "HYDRAZINE"
    if any(k in text for k in ("GH2", "LH2", " HYDROGEN", "H2", "GASEOUS HYDROGEN", "LIQUID HYDROGEN")):
        return "HYDROGEN"
    if any(k in text for k in ("GOX", "LOX", "OXYGEN", " ENRICHED O2", " O2")):
        return "OXYGEN"
    if "AIR" in text:
        return "AIR"
    return "UNKNOWN"


@lru_cache(maxsize=1)
def _get_db_params_cached() -> dict:
    from mira.core.db_config import get_db_connection_params

    return get_db_connection_params(options="-c search_path=maptis,public")


def _open_maptis_connection():
    from mira.core.db_config import open_db_connection

    return open_db_connection(options="-c search_path=maptis,public")


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


@lru_cache(maxsize=512)
def _lookup_fs_media_context(material_code: str) -> dict:
    """Best-effort FS media context lookup for a MAPTIS material code.

    Looks at two sources:
    1) silver_report_rows (materialkey-based, authoritative for material link)
    2) maptis.fluid_compatibility_tests (media strings when available)
    """
    code = str(material_code or "").strip()
    if not code:
        return {"classes": [], "examples": [], "report_numbers": [], "source_count": 0}

    try:
        import psycopg2
        from psycopg2.extras import RealDictCursor
    except Exception:
        return {"classes": [], "examples": [], "report_numbers": [], "source_count": 0}

    classes: set[str] = set()
    examples: list[str] = []
    report_numbers: set[str] = set()
    source_count = 0

    def _add_text(text: str) -> None:
        nonlocal source_count
        t = (text or "").strip()
        if not t or t.upper() == "NULL":
            return
        source_count += 1
        cls = _classify_medium_text(t)
        if cls != "UNKNOWN":
            classes.add(cls)
        if len(examples) < 8:
            examples.append(t[:220])

    try:
        with _open_maptis_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                # Optional user-provided FS media mapping table.
                # If present, this is the highest-fidelity context.
                try:
                    cur.execute(
                        """
                        SELECT material_code, testreportkey, testreportnumber, fluid_name
                        FROM public.fs_media_map
                        WHERE material_code = %s
                        """,
                        (code,),
                    )
                    for row in cur.fetchall():
                        rno = str(row.get("testreportnumber") or "").strip()
                        if rno:
                            report_numbers.add(rno)
                        tkey = str(row.get("testreportkey") or "").strip()
                        if tkey:
                            report_numbers.add(f"key:{tkey}")
                        _add_text(str(row.get("fluid_name") or ""))
                except Exception:
                    # Table is optional; ignore when not provisioned.
                    try:
                        conn.rollback()
                    except Exception:
                        pass

                cur.execute(
                    """
                    SELECT
                        normalized_payload->>'testreportnumber' AS report_no,
                        normalized_payload->>'fluc_reference' AS fluc_reference,
                        normalized_payload->>'fluc_materialfluidchanges' AS fluc_changes
                    FROM silver_report_rows
                    WHERE contract_id = 'fluid_compatibility_report'
                      AND normalized_payload->>'materialkey' = %s
                    """,
                    (code,),
                )
                silver_rows = cur.fetchall()
                for row in silver_rows:
                    report_no = str(row.get("report_no") or "").strip()
                    if report_no and report_no.upper() != "NULL":
                        report_numbers.add(report_no)
                    ref = str(row.get("fluc_reference") or "").strip()
                    if ref and ref.upper() != "NULL":
                        _add_text(f"FS_REF:{ref}")
                    _add_text(str(row.get("fluc_changes") or ""))

                # Material-code direct lookup in curated FS table
                material_code_int = int(code) if code.isdigit() else None
                if material_code_int is not None:
                    cur.execute(
                        """
                        SELECT test_report_no, media, media_spec, material_fluid_changes
                        FROM maptis.fluid_compatibility_tests
                        WHERE material_code = %s
                        """,
                        (material_code_int,),
                    )
                    rows = cur.fetchall()
                    for row in rows:
                        rno = str(row.get("test_report_no") or "").strip()
                        if rno and rno.upper() != "NULL":
                            report_numbers.add(rno)
                        _add_text(str(row.get("media") or ""))
                        _add_text(str(row.get("media_spec") or ""))
                        _add_text(str(row.get("material_fluid_changes") or ""))

                # Report-number join fallback (helps when material keys are inconsistent)
                if report_numbers:
                    report_list = sorted(report_numbers)
                    cur.execute(
                        """
                        SELECT test_report_no, media, media_spec, material_fluid_changes
                        FROM maptis.fluid_compatibility_tests
                        WHERE test_report_no = ANY(%s)
                        """,
                        (report_list,),
                    )
                    rows = cur.fetchall()
                    for row in rows:
                        _add_text(str(row.get("media") or ""))
                        _add_text(str(row.get("media_spec") or ""))
                        _add_text(str(row.get("material_fluid_changes") or ""))
    except Exception:
        logger.exception("FS media context lookup failed for material_code=%s", code)

    return {
        "classes": sorted(classes),
        "examples": examples,
        "report_numbers": sorted(report_numbers),
        "source_count": source_count,
    }


def _usage_medium_class(
    suggested_env: dict,
    env_raw: str,
    fluid_types: list[str],
) -> str:
    for value in fluid_types:
        cls = _classify_medium_text(value)
        if cls != "UNKNOWN":
            return cls
    cls_from_env = _classify_medium_text(env_raw)
    if cls_from_env != "UNKNOWN":
        return cls_from_env
    return _classify_medium_text(str(suggested_env.get("medium") or ""))


def _adjust_fs_issue_scope(
    material_code: str,
    issues: list[str],
    *,
    env_raw: str,
    suggested_env: dict,
    fluid_types: list[str],
) -> tuple[list[str], list[str]]:
    """Filter FS issue when DB media context conflicts with usage medium."""
    if "FS" not in issues:
        return issues, []

    usage_cls = _usage_medium_class(suggested_env, env_raw, fluid_types)
    if usage_cls != "HYDROGEN":
        return issues, []

    ctx = _lookup_fs_media_context(material_code)
    ctx_classes = set(ctx.get("classes") or [])
    reasons: list[str] = []

    if ctx_classes and "HYDROGEN" not in ctx_classes and "HYDRAZINE" in ctx_classes:
        filtered = [i for i in issues if i != "FS"]
        reasons.append(
            "FS evidence appears tied to hydrazine/non-H2 media in DB; "
            "FS was removed from default issue scope for H2 usage."
        )
        return filtered, reasons

    if not ctx_classes:
        reasons.append(
            "No FS media mapping found in DB for this material. If your FS dataset is available, "
            "load it so FS can be medium-filtered (H2 vs hydrazine)."
        )
    return issues, reasons


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


class MaterialIntelRequest(BaseModel):
    """Request richer candidate intelligence for HITL material selection."""

    material: Optional[str] = None
    material_code: Optional[str] = None
    top_n: int = Field(8, ge=1, le=20)
    filters: dict[str, str] = Field(default_factory=dict)


class MaterialStatsItem(BaseModel):
    label: str
    count: int


class MaterialCoverageStats(BaseModel):
    """Estimated precedent coverage for a material candidate."""

    query_mode: str = "token_estimate"
    total_muas: int = 0
    approved: int = 0
    conditional: int = 0
    rejected: int = 0
    deferred: int = 0
    top_issues: list[MaterialStatsItem] = Field(default_factory=list)
    top_env_types: list[MaterialStatsItem] = Field(default_factory=list)
    sample_muas: list[str] = Field(default_factory=list)


class MaterialIntelCandidate(BaseModel):
    material_code: str
    material_key: Optional[int] = None
    designation: str
    score: float = 0.0
    family: Optional[str] = None
    form: Optional[str] = None
    condition: Optional[str] = None
    is_mixed_record: bool = False
    differences: list[str] = Field(default_factory=list)
    coverage: MaterialCoverageStats = Field(default_factory=MaterialCoverageStats)


class MaterialDisambiguationOption(BaseModel):
    value: str
    label: str
    candidate_count: int = 0


class MaterialDisambiguationQuestion(BaseModel):
    key: str
    prompt: str
    options: list[MaterialDisambiguationOption] = Field(default_factory=list)
    selected_value: Optional[str] = None


class MaterialIntelResponse(BaseModel):
    resolution: MaterialResolution
    mixed_input: bool = False
    initial_candidate_count: int = 0
    candidate_count: int = 0
    candidates: list[MaterialIntelCandidate] = Field(default_factory=list)
    active_filters: dict[str, str] = Field(default_factory=dict)
    disambiguation_questions: list[MaterialDisambiguationQuestion] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


_FORM_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("tube", re.compile(r"\b(TUBE|TUBING|PIPE)\b", re.IGNORECASE)),
    ("wire", re.compile(r"\b(WIRE|CABLE|SPRING WIRE)\b", re.IGNORECASE)),
    ("sheet", re.compile(r"\b(SHEET|FOIL|STRIP)\b", re.IGNORECASE)),
    ("plate", re.compile(r"\bPLATE\b", re.IGNORECASE)),
    ("bar", re.compile(r"\b(BAR|ROD)\b", re.IGNORECASE)),
    ("forging", re.compile(r"\b(FORGING|FORGED)\b", re.IGNORECASE)),
    ("casting", re.compile(r"\bCASTING\b", re.IGNORECASE)),
]

_CONDITION_PATTERN = re.compile(
    r"\b(CONDITION\s+[A-Z0-9]+|ANNEALED|COLD\s+ROLLED|COLD\s+DRAWN|TEMPER|HARD)\b",
    re.IGNORECASE,
)
_TEMPER_PATTERN = re.compile(r"\b(T\d{1,4}|H\d{1,2}|O|F)\b", re.IGNORECASE)
_MATERIAL_KEYWORD_PATTERN = re.compile(
    r"\b(STEEL|STAINLESS|CRES|SST|ALUMINUM|ALUMINIUM|ALLOY|TITANIUM|INCONEL|NICKEL)\b",
    re.IGNORECASE,
)


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


class PreviewIssuesRequest(BaseModel):
    """Lightweight request to preview auto-detected issue codes."""
    o2_percent: float = 21.0
    pressure_psia: float = 14.7
    temp_min_f: float = 60.0
    temp_max_f: float = 85.0
    medium: str = "Air"
    location: str = "habitable"


class IssueCodeInfo(BaseModel):
    code: str
    label: str
    auto_detected: bool = True


class PreviewIssuesResponse(BaseModel):
    issues: list[IssueCodeInfo]


_ISSUE_LABELS: dict[str, str] = {
    "FLAM": "Flammability",
    "TVS": "Thermal Vacuum Stability",
    "FS": "Fluid Susceptibility",
    "TOX": "Toxicity",
    "OFFGAS": "Offgassing",
    "O2_COMPAT": "O2 Compatibility",
    "HEE": "Hydrogen Embrittlement",
    "SCC": "Stress Corrosion",
    "CORR": "Corrosion",
    "FRACTURE": "Cryogenic Fracture",
}


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


def _infer_env_type(env: "EnvironmentSpec") -> str:
    """Map an EnvironmentSpec to a canonical PG env_type for example lookup.

    Uses the same canonical values as the ``mua_precedents_v7`` table:
    LOX_GOX, ENRICHED_O2, CABIN_AIR, VACUUM, CRYOGENIC, etc.
    """
    from mira.mua.v7.models import EnvironmentSpec

    o2 = getattr(env, "o2_percent", 21.0) or 21.0
    location = getattr(env, "location", "") or ""
    medium = (getattr(env, "medium", "") or "").lower()
    temp_min = getattr(env, "temp_min_f", 60.0) or 60.0

    # LOX/GOX environments
    if o2 >= 99.0 or "lox" in medium or "gox" in medium:
        return "LOX_GOX"
    if o2 >= 23.5:
        return "ENRICHED_O2"
    if "vacuum" in medium or "vacuum" in location:
        return "VACUUM"
    if temp_min <= -150:
        return "CRYOGENIC"
    if "habitable" in location:
        return "CABIN_AIR"
    if "water" in medium:
        return "WATER"

    return "UNKNOWN"


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

    lines.append(f"Category:           {finalized_mua.category.category.value}")
    lines.append(
        f"Evidence Strength:  {finalized_mua.evidence_strength.band.value.upper()} "
        f"({finalized_mua.evidence_strength.score:.2f})"
    )
    lines.append(f"Center:             {finalized_mua.center.value}")
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
