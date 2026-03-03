"""MUA v10 classifier API router."""

from __future__ import annotations

import hashlib
import io
import json
import logging
import os
import re
import uuid
from dataclasses import asdict, is_dataclass
from datetime import date as date_type
from typing import Any, Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
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


class ProcessMiulRowResult(BaseModel):
    row_index: int
    line_number: str = ""
    part_number: str = ""
    maptis_code: str
    material_designation: str = ""
    media: str
    environment: str
    ratings: dict[str, str] = Field(default_factory=dict)
    pipeline_result: PipelineResult


class ProcessMiulResponse(BaseModel):
    filename: str
    total_rows: int
    processed_rows: int
    skipped_rows: int
    skipped_reasons: dict[str, int] = Field(default_factory=dict)
    results: list[ProcessMiulRowResult] = Field(default_factory=list)


ProcessMiulRowResult.model_rebuild()
ProcessMiulResponse.model_rebuild()


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


def _cell_to_text(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if not text or text.lower() == "nan":
        return ""
    if re.fullmatch(r"\d+\.0+", text):
        return text.split(".", 1)[0]
    return text


def _match_column(columns: dict[str, str], *candidates: str) -> Optional[str]:
    for candidate in candidates:
        key = candidate.strip().lower()
        if key in columns:
            return columns[key]
    return None


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


def _to_jsonable(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(k): _to_jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_to_jsonable(v) for v in value]
    if is_dataclass(value):
        return _to_jsonable(asdict(value))
    if hasattr(value, "model_dump"):
        try:
            return value.model_dump(mode="json")
        except Exception:
            return value.model_dump()
    if hasattr(value, "value"):
        return str(getattr(value, "value"))
    return str(value)


def _persist_runtime_artifacts(
    *,
    cur,
    session_id: str,
    pipeline_result: PipelineResult,
) -> None:
    for classification in pipeline_result.classifications:
        evidence = classification.evidence_bundle
        synthesis = classification.synthesis
        evidence_id: Optional[str] = None
        issue = str(classification.issue_key or "").upper().strip()
        rating = str(classification.rating or "").upper().strip()

        if evidence is not None:
            evidence_id = str(uuid.uuid4())
            cur.execute(
                """
                INSERT INTO mua_runtime.evidence_bundles(
                    id,
                    session_id,
                    issue,
                    rating,
                    evidence_hash,
                    precedent_count,
                    precedent_ring,
                    exemplar_muas,
                    extracted_phrases
                ) VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s, %s::jsonb, %s::jsonb)
                """,
                (
                    evidence_id,
                    session_id,
                    issue,
                    rating,
                    str(getattr(evidence, "evidence_hash", "") or ""),
                    json.dumps(_to_jsonable(getattr(evidence, "precedent_summary", None) or {})),
                    str(getattr(evidence, "precedent_ring", "") or ""),
                    json.dumps(_to_jsonable(getattr(evidence, "exemplars", []) or [])),
                    json.dumps(_to_jsonable(getattr(evidence, "phrases", []) or [])),
                ),
            )

        if synthesis is not None:
            cur.execute(
                """
                INSERT INTO mua_runtime.synthesis_drafts(
                    session_id,
                    evidence_id,
                    issue,
                    rationale_draft,
                    disposition_draft,
                    claims,
                    model_id,
                    prompt_version,
                    tokens_used,
                    latency_ms,
                    template_fallback,
                    verified,
                    blocked_claims
                ) VALUES (
                    %s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s, %s, %s, %s, %s::jsonb
                )
                """,
                (
                    session_id,
                    evidence_id,
                    issue,
                    str(getattr(synthesis, "rationale", "") or ""),
                    str(getattr(synthesis, "disposition", "") or ""),
                    json.dumps(_to_jsonable(getattr(synthesis, "claims", []) or [])),
                    str(getattr(synthesis, "model_id", "") or ""),
                    str(getattr(synthesis, "prompt_version", "") or ""),
                    int(getattr(synthesis, "tokens_used", 0) or 0),
                    int(getattr(synthesis, "latency_ms", 0) or 0),
                    bool(getattr(synthesis, "template_fallback", False)),
                    not bool(getattr(synthesis, "template_fallback", False)),
                    json.dumps([]),
                ),
            )


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
                _persist_runtime_artifacts(
                    cur=cur,
                    session_id=session_id,
                    pipeline_result=pipeline_result,
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
    alloy_family: str = "",
) -> PipelineResult:
    return process_miul_row(
        ratings=normalized_ratings,
        maptis_code=resolved_maptis_code,
        material_designation=material_designation.strip(),
        alloy_family=alloy_family.strip(),
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


@router.post("/process-miul", response_model=ProcessMiulResponse)
async def process_miul_workbook(
    file: UploadFile = File(...),
    media_override: Optional[str] = Form(None),
    environment_override: Optional[str] = Form(None),
    project: str = Form(""),
    system: str = Form(""),
    max_rows: int = Form(200),
) -> ProcessMiulResponse:
    """Process completed MIUL workbook rows with the V10 classifier pipeline."""
    filename = file.filename or "miul.xlsx"
    if not filename.lower().endswith((".xlsx", ".xlsm")):
        raise HTTPException(status_code=400, detail="Only .xlsx/.xlsm MIUL files are supported.")

    if max_rows < 1:
        raise HTTPException(status_code=400, detail="max_rows must be >= 1")

    try:
        import pandas as pd
    except Exception as exc:  # pragma: no cover - dependency/install specific
        raise HTTPException(
            status_code=500,
            detail="pandas/openpyxl are required for MIUL upload processing.",
        ) from exc

    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")

    try:
        df = pd.read_excel(io.BytesIO(content), sheet_name="MIUL", engine="openpyxl")
    except ValueError:
        df = pd.read_excel(io.BytesIO(content), engine="openpyxl")
    except Exception as exc:
        raise HTTPException(
            status_code=400,
            detail="Failed to parse workbook. Confirm this is a valid MIUL Excel file.",
        ) from exc

    if df is None or df.empty:
        return ProcessMiulResponse(
            filename=filename,
            total_rows=0,
            processed_rows=0,
            skipped_rows=0,
            skipped_reasons={},
            results=[],
        )

    raw_columns = [str(c).strip() for c in df.columns]
    column_lookup = {c.lower(): c for c in raw_columns if c}

    maptis_col = _match_column(
        column_lookup,
        "Material Code",
        "MAPTIS Code",
        "MAPTIS",
        "material_code",
        "maptis_code",
    )
    designation_col = _match_column(
        column_lookup,
        "Designation",
        "Material Designation",
        "Manufacturer Designation",
        "material_designation",
    )
    class_col = _match_column(
        column_lookup,
        "Material Class",
        "material_class",
    )
    media_col = _match_column(
        column_lookup,
        "Fluid Type",
        "Media",
        "Medium",
        "fluid_type",
    )
    env_col = _match_column(
        column_lookup,
        "Environment",
        "Location",
        "environment",
    )
    part_col = _match_column(
        column_lookup,
        "Part Number",
        "part_number",
    )
    line_col = _match_column(
        column_lookup,
        "Line Number",
        "Line Item",
        "line_number",
    )

    rating_cols = {
        "FLAM": _match_column(column_lookup, "FLAM", "FLAMM Rating", "FLAM Rating"),
        "FS": _match_column(column_lookup, "FS", "FS Rating"),
        "TOX": _match_column(column_lookup, "TOX", "TOX Rating"),
        "TVS": _match_column(column_lookup, "TVS", "TVS Rating"),
        "SCC": _match_column(column_lookup, "SCC", "SCC Rating"),
        "CORR": _match_column(column_lookup, "CORR", "CORR Rating"),
    }

    if maptis_col is None:
        raise HTTPException(
            status_code=400,
            detail="Missing required MIUL column: Material Code (MAPTIS code).",
        )

    results: list[ProcessMiulRowResult] = []
    skipped_reasons: dict[str, int] = {}

    def _skip(reason: str) -> None:
        skipped_reasons[reason] = skipped_reasons.get(reason, 0) + 1

    for idx, row in df.iterrows():
        if len(results) >= max_rows:
            _skip("max_rows_limit")
            continue

        maptis_code = _cell_to_text(row.get(maptis_col))
        if not maptis_code:
            _skip("missing_maptis_code")
            continue

        designation = _cell_to_text(row.get(designation_col)) if designation_col else ""
        media = (media_override or (_cell_to_text(row.get(media_col)) if media_col else "")).strip()
        environment = (
            environment_override
            or (_cell_to_text(row.get(env_col)) if env_col else "")
            or "non-habitable"
        ).strip()

        if not media:
            _skip("missing_media")
            continue

        all_ratings: dict[str, str] = {}
        for issue_key, col_name in rating_cols.items():
            if not col_name:
                continue
            value = _cell_to_text(row.get(col_name)).upper()
            if value:
                all_ratings[issue_key] = value

        # Mirror the v8 helper intent: queue only rows with actionable (non-A) triggers.
        trigger_ratings = {k: v for k, v in all_ratings.items() if v != "A"}
        if not trigger_ratings:
            _skip("no_non_a_ratings")
            continue

        part_number = _cell_to_text(row.get(part_col)) if part_col else ""
        line_number = _cell_to_text(row.get(line_col)) if line_col else str(idx + 2)

        material_class_value: Optional[str] = None
        if class_col:
            material_class_value = _cell_to_text(row.get(class_col)).lower()
        if material_class_value not in {"metal", "nonmetallic"}:
            inferred = material_class_from_miul(designation)
            material_class_value = inferred.value if inferred else "metal"

        try:
            pipeline_result = process_miul_row(
                ratings=trigger_ratings,
                maptis_code=maptis_code,
                material_designation=designation,
                material_class=material_class_value,
                media=media,
                environment=environment,
                o2_percent=None,
                batch_verified=False,
                part_numbers=[part_number] if part_number else None,
                part_count=1,
                project=project.strip(),
                system=system.strip(),
                material_specification=None,
                pressure="",
                temperature="",
            )
        except Exception:
            LOGGER.exception("Failed to process MIUL row %s (MAPTIS %s)", idx + 2, maptis_code)
            _skip("pipeline_error")
            continue

        results.append(
            ProcessMiulRowResult(
                row_index=int(idx) + 2,
                line_number=line_number,
                part_number=part_number,
                maptis_code=maptis_code,
                material_designation=designation,
                media=media,
                environment=environment,
                ratings=trigger_ratings,
                pipeline_result=pipeline_result,
            )
        )

    return ProcessMiulResponse(
        filename=filename,
        total_rows=int(len(df)),
        processed_rows=len(results),
        skipped_rows=int(len(df)) - len(results),
        skipped_reasons=skipped_reasons,
        results=results,
    )


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

    resolved_maptis_code = ""
    resolved_name = designation
    resolved_family = ""
    resolved_candidates: list[dict[str, Any]] = []
    material_class = request.material_class

    if request.maptis_code:
        resolved_maptis_code = request.maptis_code.strip()
        resolved_name = designation or resolved_maptis_code
    else:
        try:
            from mira.mua.matchmaker.adapters import resolve_material as resolve_material_v7

            resolution = resolve_material_v7(designation)
            resolved_candidates = list(resolution.suggestions or [])

            if resolution.status.value != "resolved" or not resolution.material_code:
                return {
                    "status": "needs_resolution",
                    "material_resolution": {
                        "input_text": designation,
                        "status": resolution.status.value,
                        "message": "Material resolution requires engineer confirmation.",
                    },
                    "candidates": resolved_candidates,
                }

            resolved_maptis_code = str(resolution.material_code).strip()
            resolved_name = str(resolution.resolved_name or designation or resolved_maptis_code).strip()
            resolved_family = str(resolution.family or "").strip()

            if material_class is None:
                resolved_class = str(resolution.material_class or "").strip().lower()
                if resolved_class in {"metal", "nonmetallic"}:
                    material_class = MaterialClassEnum(resolved_class)
        except Exception as exc:
            LOGGER.warning("v7 adapter material resolver failed, falling back to local resolver: %s", exc)
            try:
                resolved_maptis_code = _resolve_maptis_code_or_raise(request.maptis_code, designation)
            except HTTPException as resolver_exc:
                if resolver_exc.status_code in {400, 503} and not request.maptis_code:
                    return {
                        "status": "needs_resolution",
                        "material_resolution": {
                            "input_text": designation,
                            "status": "unresolved",
                            "message": resolver_exc.detail,
                        },
                    }
                raise

    if not resolved_maptis_code:
        raise HTTPException(status_code=400, detail="Unable to resolve MAPTIS code for input material")

    if material_class is None and designation:
        inferred_class = material_class_from_miul(designation)
        material_class = inferred_class or MaterialClassEnum.METAL
    elif material_class is None:
        material_class = MaterialClassEnum.METAL

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

    pipeline_result = _run_pipeline_from_request(
        request=classify_payload,
        normalized_ratings=normalized_ratings,
        resolved_maptis_code=resolved_maptis_code,
        material_designation=resolved_name,
        alloy_family=resolved_family,
    )

    material_resolution = {
        "input_text": designation,
        "status": "resolved",
        "maptis_code": resolved_maptis_code,
        "resolved_name": resolved_name,
        "family": resolved_family,
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
        "candidates": resolved_candidates,
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
