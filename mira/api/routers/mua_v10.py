"""MUA v10 classifier API router."""

from __future__ import annotations

import hashlib
import io
import json
import logging
import os
import re
import uuid
from datetime import date as date_type
from typing import Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from mira.core.db_config import get_db_connection_params
from mira.mua.classifier.models import Form551Fields, MaterialClassEnum, PipelineResult
from mira.mua.classifier.pipeline import process_miul_row
from mira.mua.classifier.screening import material_class_from_miul

router = APIRouter(tags=["MUA v10"])
LOGGER = logging.getLogger(__name__)

_ALLOWED_COLUMNS = ("FLAM", "FS", "TOX", "TVS", "SCC", "CORR")
_TRUE_VALUES = {"1", "true", "yes", "on"}

# Local/offline fallback mappings for known MUA v10 materials.
# This is intentionally small and deterministic, and only enabled in local/dev mode.
_OFFLINE_CODE_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"\bA[\-\s]?286\b", "10392"),
    (r"\bINCONEL[\s\-]*625\b|\bINC[\s\-]*625\b", "10727"),
    (r"\bINCONEL[\s\-]*718\b|\bINC[\s\-]*718\b", "55962"),
    (r"\b7075[\-\s]*T651\b", "50181"),
    (r"\b7075\b", "54223"),
    (r"\b(ALUMINUM|AL)\s+BRONZE\b|\bC63000\b", "50678"),
)


try:  # pragma: no cover - optional dependency behavior
    import psycopg2
except Exception:  # pragma: no cover
    psycopg2 = None


class ClassifyRowRequest(BaseModel):
    maptis_code: Optional[str] = None
    material_designation: str = ""
    material_class: Optional[MaterialClassEnum] = None
    media: str = Field(..., min_length=1)
    environment: str = "non-habitable"
    o2_percent: Optional[float] = None
    batch_verified: bool = False
    ratings: dict[str, Optional[str]] = Field(default_factory=dict)

    part_numbers: list[str] = Field(default_factory=list)
    part_count: int = Field(1, ge=1)
    project: str = ""
    system: str = ""
    material_specification: Optional[str] = None
    pressure: str = ""
    temperature: str = ""


class GenerateDocxRequest(ClassifyRowRequest):
    """Extends ClassifyRowRequest with optional rationale override."""

    rationale_override: Optional[str] = None
    disposition_override: Optional[str] = None
    session_id: Optional[str] = None
    issue: Optional[str] = None


class SingleMaterialRequest(BaseModel):
    material_text: str = ""
    maptis_code: Optional[str] = None
    material_class: Optional[MaterialClassEnum] = None
    media: str = Field(..., min_length=1)
    environment: str = "non-habitable"
    o2_percent: Optional[float] = None
    batch_verified: bool = False
    ratings: dict[str, Optional[str]] = Field(default_factory=dict)

    part_numbers: list[str] = Field(default_factory=list)
    part_count: int = Field(1, ge=1)
    project: str = ""
    system: str = ""
    material_specification: Optional[str] = None
    pressure: str = ""
    temperature: str = ""


class FinalizeAction(BaseModel):
    issue: str
    action: str = "approve"  # approve | edit | reject
    rationale: Optional[str] = None
    disposition: Optional[str] = None
    comment: str = ""


class FinalizeRequest(ClassifyRowRequest):
    session_id: Optional[str] = None
    actions: list[FinalizeAction] = Field(default_factory=list)


def _offline_lookup_enabled() -> bool:
    explicit = os.getenv("MUA_V10_ALLOW_OFFLINE_LOOKUP")
    if explicit is not None:
        return explicit.strip().lower() in _TRUE_VALUES

    auth_mode = os.getenv("MIRA_AUTH_MODE", "").strip().lower()
    app_env = os.getenv("MIRA_ENV", "").strip().lower()
    return auth_mode == "disabled" or app_env in {"local", "dev", "development"}


def _runtime_db_enabled() -> bool:
    value = os.getenv("MUA_RUNTIME_DB_ENABLED")
    if value is None:
        return True
    return value.strip().lower() in _TRUE_VALUES


def _resolve_offline_fallback_maptis_code(material_designation: str) -> Optional[str]:
    designation = material_designation.strip().upper()
    if not designation:
        return None

    # If a 5-digit MAPTIS-like code is embedded, use it directly.
    embedded = re.search(r"\b(\d{5})\b", designation)
    if embedded:
        return embedded.group(1)

    for pattern, code in _OFFLINE_CODE_PATTERNS:
        if re.search(pattern, designation):
            return code

    return None


def _resolve_maptis_code_or_raise(
    maptis_code: Optional[str],
    material_designation: str,
) -> str:
    explicit_code = (maptis_code or "").strip()
    if explicit_code:
        return explicit_code

    designation = material_designation.strip()
    if not designation:
        raise HTTPException(
            status_code=400,
            detail="Provide maptis_code or material_designation.",
        )

    # Local/dev mode: avoid database dependency entirely.
    if _offline_lookup_enabled():
        fallback = _resolve_offline_fallback_maptis_code(designation)
        if fallback:
            LOGGER.info(
                "Using offline MAPTIS lookup for '%s' -> %s",
                designation,
                fallback,
            )
            return fallback
        raise HTTPException(
            status_code=400,
            detail=(
                f"Could not resolve MAPTIS code from material_designation '{designation}' "
                "using offline lookup. Provide maptis_code manually."
            ),
        )

    try:
        from mira.miul.material_code_lookup import get_lookup_service

        service = get_lookup_service()
        matches = service.lookup_by_designation(designation)
    except Exception as exc:
        LOGGER.exception("MAPTIS lookup failed for designation '%s'", designation)
        if _offline_lookup_enabled():
            fallback = _resolve_offline_fallback_maptis_code(designation)
            if fallback:
                LOGGER.warning(
                    "Using offline MAPTIS fallback for '%s' -> %s due to lookup failure",
                    designation,
                    fallback,
                )
                return fallback
        raise HTTPException(
            status_code=503,
            detail=(
                "MAPTIS lookup service unavailable (check POSTGRES_* connection settings). "
                "Provide maptis_code manually."
            ),
        ) from exc

    candidate_codes: list[str] = []
    for match in matches:
        code = str(match.material_code or "").strip()
        if not code or code.upper() == "UNKNOWN":
            continue
        if code not in candidate_codes:
            candidate_codes.append(code)

    if not candidate_codes:
        if _offline_lookup_enabled():
            fallback = _resolve_offline_fallback_maptis_code(designation)
            if fallback:
                LOGGER.warning(
                    "Using offline MAPTIS fallback for '%s' -> %s due to no DB matches",
                    designation,
                    fallback,
                )
                return fallback
        raise HTTPException(
            status_code=400,
            detail=(
                f"Could not resolve MAPTIS code from material_designation '{designation}'. "
                "Provide maptis_code manually."
            ),
        )

    resolved_code = candidate_codes[0]
    if len(candidate_codes) > 1:
        LOGGER.info(
            "Resolved material '%s' to MAPTIS %s (alternates: %s)",
            designation,
            resolved_code,
            ", ".join(candidate_codes[1:4]),
        )
    return resolved_code


def _normalize_ratings_or_raise(ratings: dict[str, Optional[str]]) -> dict[str, str]:
    if not ratings:
        raise HTTPException(status_code=400, detail="ratings is required")

    normalized: dict[str, str] = {}
    for raw_key, raw_value in ratings.items():
        key = str(raw_key or "").upper().strip()
        if key not in _ALLOWED_COLUMNS:
            continue
        if raw_value is None:
            continue
        value = str(raw_value).strip().upper()
        if not value:
            continue
        normalized[key] = value

    if not normalized:
        raise HTTPException(
            status_code=400,
            detail=f"ratings must include at least one of: {', '.join(_ALLOWED_COLUMNS)}",
        )
    return normalized


def _runtime_connect():
    if not _runtime_db_enabled() or psycopg2 is None:
        return None

    params = get_db_connection_params(database="mira")
    params.setdefault("connect_timeout", 2)
    try:
        return psycopg2.connect(**params)
    except Exception as exc:  # pragma: no cover - infra dependent
        LOGGER.warning("mua_runtime DB unavailable: %s", exc)
        return None


def _create_runtime_session(
    *,
    request_payload: dict,
    resolution_payload: dict,
    pipeline_result: PipelineResult,
) -> Optional[str]:
    conn = _runtime_connect()
    if conn is None:
        return None

    session_id = str(uuid.uuid4())

    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO mua_runtime.sessions(
                        id,
                        material_text,
                        maptis_code,
                        material_name,
                        material_class,
                        alloy_family,
                        media,
                        environment,
                        project,
                        system,
                        ratings_input,
                        decisions,
                        status
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        %s::jsonb, %s::jsonb, %s
                    )
                    """,
                    (
                        session_id,
                        str(resolution_payload.get("input_text") or ""),
                        str(resolution_payload.get("maptis_code") or ""),
                        str(resolution_payload.get("resolved_name") or ""),
                        str(resolution_payload.get("material_class") or ""),
                        str(resolution_payload.get("family") or ""),
                        str(request_payload.get("media") or ""),
                        str(request_payload.get("environment") or "non-habitable"),
                        str(request_payload.get("project") or ""),
                        str(request_payload.get("system") or ""),
                        json.dumps(request_payload),
                        json.dumps(pipeline_result.model_dump(mode="json")),
                        "draft",
                    ),
                )
        return session_id
    except Exception as exc:  # pragma: no cover - infra dependent
        LOGGER.warning("Failed to persist runtime session: %s", exc)
        return None
    finally:
        try:
            conn.close()
        except Exception:
            pass


def _load_final_form_from_runtime(session_id: str, issue: str) -> Optional[Form551Fields]:
    conn = _runtime_connect()
    if conn is None:
        return None

    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT final_form_fields
                FROM mua_runtime.final_documents
                WHERE session_id = %s
                  AND COALESCE(final_form_fields->>'issue', '') = %s
                ORDER BY generated_at DESC
                LIMIT 1
                """,
                (session_id, issue),
            )
            row = cur.fetchone()
            if not row:
                return None
            payload = row[0]
            if isinstance(payload, str):
                payload = json.loads(payload)
            if not isinstance(payload, dict):
                return None
            return Form551Fields(**payload)
    except Exception as exc:  # pragma: no cover - infra dependent
        LOGGER.warning("Failed to load finalized form from runtime DB: %s", exc)
        return None
    finally:
        try:
            conn.close()
        except Exception:
            pass


def _persist_finalize(
    *,
    session_id: Optional[str],
    original_forms: dict[str, Form551Fields],
    final_forms: list[Form551Fields],
    actions: list[FinalizeAction],
) -> Optional[str]:
    if session_id is None:
        return None

    conn = _runtime_connect()
    if conn is None:
        return session_id

    sid = session_id

    actions_by_issue = {a.issue.upper().strip(): a for a in actions}

    try:
        with conn:
            with conn.cursor() as cur:
                for form in final_forms:
                    issue = form.issue.upper().strip()
                    action = actions_by_issue.get(issue)
                    original = original_forms.get(issue)
                    action_name = action.action if action else "approve"
                    comment = action.comment if action else ""

                    cur.execute(
                        """
                        INSERT INTO mua_runtime.engineer_actions(
                            session_id,
                            issue,
                            action,
                            original_rationale,
                            edited_rationale,
                            original_disposition,
                            edited_disposition,
                            comment
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                        """,
                        (
                            sid,
                            issue,
                            action_name,
                            original.rationale if original else "",
                            form.rationale,
                            original.disposition if original else "",
                            form.disposition,
                            comment,
                        ),
                    )

                    cur.execute(
                        """
                        INSERT INTO mua_runtime.final_documents(
                            session_id,
                            mua_number,
                            final_rationale,
                            final_disposition,
                            final_form_fields
                        ) VALUES (%s, %s, %s, %s, %s::jsonb)
                        """,
                        (
                            sid,
                            form.mua_number,
                            form.rationale,
                            form.disposition,
                            json.dumps(form.model_dump(mode="json")),
                        ),
                    )

                    if original and (
                        (original.rationale or "") != (form.rationale or "")
                        or (original.disposition or "") != (form.disposition or "")
                    ):
                        cur.execute(
                            """
                            INSERT INTO mua_runtime.learning_events(
                                session_id,
                                event_type,
                                payload
                            ) VALUES (%s, %s, %s::jsonb)
                            """,
                            (
                                sid,
                                "draft_vs_final",
                                json.dumps(
                                    {
                                        "issue": issue,
                                        "original_rationale": original.rationale,
                                        "edited_rationale": form.rationale,
                                        "original_disposition": original.disposition,
                                        "edited_disposition": form.disposition,
                                    }
                                ),
                            ),
                        )

                cur.execute(
                    """
                    UPDATE mua_runtime.sessions
                    SET status = %s, updated_at = NOW()
                    WHERE id = %s
                    """,
                    ("reviewed", sid),
                )
        return sid
    except Exception as exc:  # pragma: no cover - infra dependent
        LOGGER.warning("Failed to persist finalize payload: %s", exc)
        return sid
    finally:
        try:
            conn.close()
        except Exception:
            pass


def _update_runtime_docx_hash(session_id: str, issue: str, docx_bytes: bytes) -> None:
    conn = _runtime_connect()
    if conn is None:
        return

    digest = hashlib.sha256(docx_bytes).hexdigest()

    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE mua_runtime.final_documents
                    SET docx_hash = %s,
                        generated_at = NOW()
                    WHERE session_id = %s
                      AND COALESCE(final_form_fields->>'issue', '') = %s
                    """,
                    (digest, session_id, issue),
                )
    except Exception as exc:  # pragma: no cover - infra dependent
        LOGGER.warning("Failed to store docx hash in runtime DB: %s", exc)
    finally:
        try:
            conn.close()
        except Exception:
            pass


def _run_pipeline_from_request(
    *,
    request: ClassifyRowRequest,
    normalized_ratings: dict[str, str],
    resolved_maptis_code: str,
    material_designation: str,
) -> PipelineResult:
    return process_miul_row(
        ratings=normalized_ratings,
        maptis_code=resolved_maptis_code,
        material_designation=material_designation.strip(),
        material_class=request.material_class,
        media=request.media.strip(),
        environment=request.environment.strip() or "non-habitable",
        o2_percent=request.o2_percent,
        batch_verified=request.batch_verified,
        part_numbers=[p.strip() for p in request.part_numbers if p and p.strip()] or None,
        part_count=request.part_count,
        project=request.project.strip(),
        system=request.system.strip(),
        material_specification=(request.material_specification or "").strip() or None,
        pressure=request.pressure.strip(),
        temperature=request.temperature.strip(),
    )


@router.get("/ping")
async def ping() -> dict[str, str]:
    return {"status": "ok", "domain": "mua-v10"}


@router.post("/classify-row", response_model=PipelineResult)
async def classify_row(request: ClassifyRowRequest) -> PipelineResult:
    normalized_ratings = _normalize_ratings_or_raise(request.ratings)

    resolved_maptis_code = _resolve_maptis_code_or_raise(
        request.maptis_code,
        request.material_designation,
    )

    try:
        return _run_pipeline_from_request(
            request=request,
            normalized_ratings=normalized_ratings,
            resolved_maptis_code=resolved_maptis_code,
            material_designation=request.material_designation,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/process-single")
async def process_single_material(request: SingleMaterialRequest) -> dict:
    normalized_ratings = _normalize_ratings_or_raise(request.ratings)

    designation = (request.material_text or "").strip()
    if not designation and not request.maptis_code:
        raise HTTPException(status_code=400, detail="Provide material_text or maptis_code")

    try:
        resolved_maptis_code = _resolve_maptis_code_or_raise(request.maptis_code, designation)
    except HTTPException as exc:
        if exc.status_code in {400, 503} and not request.maptis_code:
            return {
                "status": "needs_resolution",
                "material_resolution": {
                    "input_text": designation,
                    "status": "unresolved",
                    "message": exc.detail,
                },
            }
        raise

    inferred_class = request.material_class
    if inferred_class is None and designation:
        inferred_class = material_class_from_miul(designation)

    material_class = inferred_class or MaterialClassEnum.METAL
    resolved_name = designation or resolved_maptis_code

    classify_payload = ClassifyRowRequest(
        maptis_code=resolved_maptis_code,
        material_designation=resolved_name,
        material_class=material_class,
        media=request.media,
        environment=request.environment,
        o2_percent=request.o2_percent,
        batch_verified=request.batch_verified,
        ratings=normalized_ratings,
        part_numbers=request.part_numbers,
        part_count=request.part_count,
        project=request.project,
        system=request.system,
        material_specification=request.material_specification,
        pressure=request.pressure,
        temperature=request.temperature,
    )

    pipeline_result = await classify_row(classify_payload)

    material_resolution = {
        "input_text": designation,
        "status": "resolved",
        "maptis_code": resolved_maptis_code,
        "resolved_name": resolved_name,
        "family": "",
        "material_class": material_class.value,
    }

    request_payload = {
        "material_text": designation,
        "maptis_code": request.maptis_code,
        "media": request.media,
        "environment": request.environment,
        "ratings": normalized_ratings,
        "project": request.project,
        "system": request.system,
        "pressure": request.pressure,
        "temperature": request.temperature,
    }

    session_id = _create_runtime_session(
        request_payload=request_payload,
        resolution_payload=material_resolution,
        pipeline_result=pipeline_result,
    )

    return {
        "status": "ok",
        "session_id": session_id,
        "material_resolution": material_resolution,
        "pipeline_result": pipeline_result,
    }


@router.post("/finalize")
async def finalize_mua(request: FinalizeRequest) -> dict:
    pipeline_result = await classify_row(
        ClassifyRowRequest(
            maptis_code=request.maptis_code,
            material_designation=request.material_designation,
            material_class=request.material_class,
            media=request.media,
            environment=request.environment,
            o2_percent=request.o2_percent,
            batch_verified=request.batch_verified,
            ratings=request.ratings,
            part_numbers=request.part_numbers,
            part_count=request.part_count,
            project=request.project,
            system=request.system,
            material_specification=request.material_specification,
            pressure=request.pressure,
            temperature=request.temperature,
        )
    )

    original_forms = {
        form.issue.upper().strip(): form.model_copy(deep=True)
        for form in pipeline_result.forms
    }
    forms_by_issue = {
        issue: form.model_copy(deep=True)
        for issue, form in original_forms.items()
    }

    for action in request.actions:
        issue = action.issue.upper().strip()
        form = forms_by_issue.get(issue)
        if not form:
            continue
        if action.rationale is not None and action.rationale.strip():
            form.rationale = action.rationale.strip()
        if action.disposition is not None and action.disposition.strip():
            form.disposition = action.disposition.strip()

    final_forms = list(forms_by_issue.values())

    persisted_session = _persist_finalize(
        session_id=request.session_id,
        original_forms=original_forms,
        final_forms=final_forms,
        actions=request.actions,
    )

    return {
        "status": "ok",
        "session_id": persisted_session,
        "finalized_count": len(final_forms),
        "forms": final_forms,
    }


@router.post("/generate-docx")
async def generate_docx(request: GenerateDocxRequest) -> StreamingResponse:
    """Run classification then render automatable MUA to Form 551 .docx.

    Accepts same fields as /classify-row plus optional rationale_override
    and disposition_override for engineer edits from the UI.
    """
    form: Optional[Form551Fields] = None

    if request.session_id and request.issue:
        form = _load_final_form_from_runtime(request.session_id, request.issue.upper().strip())
        if form is None:
            raise HTTPException(
                status_code=404,
                detail="No finalized form found for given session_id and issue",
            )
    else:
        normalized_ratings = _normalize_ratings_or_raise(request.ratings)

        classify_payload = {
            key: value
            for key, value in request.model_dump().items()
            if key in ClassifyRowRequest.model_fields
        }
        classify_payload["ratings"] = normalized_ratings
        classify_request = ClassifyRowRequest(**classify_payload)
        pipeline_result = await classify_row(classify_request)

        if not pipeline_result.forms:
            raise HTTPException(
                status_code=400,
                detail="No automatable MUAs found. Cannot generate .docx.",
            )

        form = pipeline_result.forms[0]

    if request.rationale_override:
        form.rationale = request.rationale_override
    if request.disposition_override:
        form.disposition = request.disposition_override

    if not form.date:
        form.date = str(date_type.today())
    if not form.project and request.project:
        form.project = request.project
    if not form.system and request.system:
        form.system = request.system

    try:
        from mira.mua.classifier.docx_renderer import render_form551_docx
    except ImportError as exc:
        raise HTTPException(
            status_code=500,
            detail="DOCX renderer unavailable. Install python-docx in the API environment.",
        ) from exc

    docx_bytes = render_form551_docx(form)
    filename = f"MUA_{form.issue}_{form.maptis_code}.docx"

    if request.session_id and request.issue:
        _update_runtime_docx_hash(request.session_id, request.issue.upper().strip(), docx_bytes)

    return StreamingResponse(
        io.BytesIO(docx_bytes),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
