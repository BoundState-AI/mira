#!/usr/bin/env python3
"""
FORGE API router.

Additive database compiler surface. This does not modify existing MIRA routes.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import MetaData, String, Table, create_engine, func, or_, select
from sqlalchemy.engine.url import make_url

from mira.forge import bsms_runtime
from mira.forge.jobs import ForgeCompileJobManager
from mira.forge.models import ForgeCompileAcceptedResponse, ForgeCompileJobResponse
from mira.forge.models import ForgeCompileRequest
from mira.forge_claude.compiler import ForgeClaudeCompiler

router = APIRouter()
_compiler = ForgeClaudeCompiler()
_job_manager = ForgeCompileJobManager(_compiler)

_MUTATION_TERMS = {"delete", "drop", "truncate", "update", "insert", "alter", "create", "grant", "revoke"}
_HUMAN_REVIEW_TERMS = {"approve", "certify", "guarantee", "sign off", "safety critical", "compliance decision"}
_ALLOWED_DIALECTS = {"sqlite", "postgresql", "mysql"}
_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}


def _engine_options(database_url: str) -> dict[str, Any]:
    if database_url.startswith("sqlite"):
        return {"future": True, "connect_args": {"check_same_thread": False}}
    return {"future": True, "pool_pre_ping": True, "pool_size": 5, "max_overflow": 10}


class BSMSQueryRequest(BaseModel):
    """Request to run a query through the BSMS pipeline."""

    query: str = Field(..., min_length=1, max_length=2000)
    question_map: dict[str, Any] = Field(..., description="Compiled question_map from /compile")
    database_url: str | None = Field(
        None,
        description="Optional database URL for evidence-backed execution of the selected compiled question.",
    )
    bsms_pipeline: dict[str, Any] = Field(default_factory=dict, description="BSMS pipeline config")
    authority_pack: dict[str, Any] = Field(default_factory=dict, description="Authority pack")
    limit: int = Field(25, ge=1, le=100)
    require_llm: bool = Field(
        True,
        description="When true, the LLM bouncer/parser/formatter stages are mandatory and fail closed.",
    )
    persist_lineage: bool = Field(
        True,
        description="When true, append a JSONL decision-lineage record for this BSMS query.",
    )
    lineage_dir: str | None = Field(
        None,
        description="Optional directory for persisted BSMS lineage records.",
    )

    model_config = {"extra": "forbid"}


class BSMSQueryResponse(BaseModel):
    """BSMS pipeline response."""

    status: str
    pipeline: str = "B-S-M-S"
    bouncer: dict[str, Any]
    parsed_intent: dict[str, Any] | None = None
    rules: dict[str, Any] | None = None
    answer: str
    lineage: dict[str, Any] = Field(default_factory=dict)

    model_config = {"extra": "forbid"}


@router.get("/ping")
async def ping() -> dict[str, str]:
    """Health check for the FORGE subsystem."""
    return {"status": "ok", "domain": "forge", "version": "0.1.0"}


def _validate_compile_request(request: ForgeCompileRequest) -> None:
    """Fast preflight validation before creating a long-running compile job."""
    try:
        url = make_url(request.database_url)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid database URL: {exc}") from exc

    dialect = url.get_backend_name()
    if dialect not in _ALLOWED_DIALECTS:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Unsupported database dialect '{dialect}'. "
                "FORGE currently supports sqlite, postgresql, and mysql."
            ),
        )

    if dialect != "sqlite":
        allow_remote = os.getenv("FORGE_ALLOW_REMOTE_DATABASES", "").strip().lower() in {"1", "true", "yes"}
        if (url.host or "").lower() not in _LOCAL_HOSTS and not allow_remote:
            raise HTTPException(
                status_code=400,
                detail=(
                    "Remote database URLs are disabled by default. Use a local database host "
                    "or set FORGE_ALLOW_REMOTE_DATABASES=true explicitly."
                ),
            )


@router.post("/compile", response_model=ForgeCompileAcceptedResponse, status_code=202)
async def compile_database(request: ForgeCompileRequest) -> ForgeCompileAcceptedResponse:
    """Queue a FORGE compile job and return immediately."""
    _validate_compile_request(request)
    return _job_manager.submit(request)


@router.get("/compile/{job_id}", response_model=ForgeCompileJobResponse)
async def compile_database_status(job_id: str) -> ForgeCompileJobResponse:
    """Fetch FORGE compile job status, progress, and final result."""
    job = _job_manager.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Unknown FORGE job '{job_id}'.")
    return job


@router.post("/bsms/query", response_model=BSMSQueryResponse)
async def bsms_query(request: BSMSQueryRequest) -> BSMSQueryResponse:
    """Run a query through the BSMS pipeline against compiled FORGE data."""
    try:
        return _run_bsms_pipeline(request)
    except bsms_runtime.BSMSRuntimePolicyError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"BSMS query failed: {exc}") from exc


def _run_bsms_pipeline(request: BSMSQueryRequest) -> BSMSQueryResponse:
    """BSMS pipeline: deterministic guardrail, LLM parse, deterministic rules, LLM format."""
    query = request.query
    lowered = query.lower()
    runtime = bsms_runtime.llm_status(require_llm=request.require_llm)

    mutation_flags = sorted(term for term in _MUTATION_TERMS if term in lowered)
    if mutation_flags:
        bouncer = {
            "status": "rejected",
            "reason": "Mutation or administrative requests are outside BSMS authority.",
            "risk_flags": mutation_flags,
            "decision_source": "deterministic_guardrail",
            "llm_runtime": runtime,
        }
        lineage = _persist_lineage(
            request,
            {
                "pipeline": "B-S-M-S",
                "query": query,
                "bouncer_verdict": "REJECT",
                "parsed_intent": None,
                "rules_verdict": "REJECTED",
                "rules_applied": ["deterministic_guardrail"],
                "evidence_sources": [],
                "executed_query": None,
                "rendering_source": "deterministic_guardrail",
                "confidence": 1.0,
                "runtime": {"llm": runtime},
                "bouncer": bouncer,
            },
        )
        return BSMSQueryResponse(
            status="rejected",
            bouncer=bouncer,
            answer=bouncer["reason"],
            lineage=lineage,
        )

    bouncer = _run_bouncer_stage(request, query, runtime)
    if bouncer["status"] != "accepted":
        lineage = _persist_lineage(
            request,
            {
                "pipeline": "B-S-M-S",
                "query": query,
                "bouncer_verdict": "REJECT",
                "parsed_intent": None,
                "rules_verdict": "REJECTED",
                "rules_applied": ["bouncer"],
                "evidence_sources": [],
                "executed_query": None,
                "rendering_source": "bouncer_rejection",
                "confidence": float(bouncer.get("confidence", 0.0) or 0.0),
                "runtime": {"llm": runtime},
                "bouncer": bouncer,
            },
        )
        return BSMSQueryResponse(
            status="rejected",
            bouncer=bouncer,
            answer=bouncer.get("reason") or "Query rejected by bouncer.",
            lineage=lineage,
        )

    questions = _extract_questions(request.question_map)
    if not questions:
        lineage = _persist_lineage(
            request,
            {
                "pipeline": "B-S-M-S",
                "query": query,
                "bouncer_verdict": "PASS",
                "parsed_intent": None,
                "rules_verdict": "UNSUPPORTED",
                "rules_applied": ["question_catalog_empty"],
                "evidence_sources": [],
                "executed_query": None,
                "rendering_source": "deterministic_formatter",
                "confidence": 0.0,
                "runtime": {"llm": runtime},
                "bouncer": bouncer,
            },
        )
        return BSMSQueryResponse(
            status="ok",
            bouncer=bouncer,
            answer="No compiled questions available to match against.",
            lineage=lineage,
        )

    parsed_intent = _run_parser_stage(request, query, questions, runtime)

    gate_hits = sorted(term for term in _HUMAN_REVIEW_TERMS if term in lowered)
    gate = {"status": "human_review_required" if gate_hits else "approved", "matches": gate_hits}
    rules = _run_rules_stage(request, query, parsed_intent, gate)

    if rules["verdict"] != "SUPPORTED":
        status = "human_review_required" if rules["verdict"] == "HUMAN_REVIEW_REQUIRED" else "unsupported"
        if rules["verdict"] == "HUMAN_REVIEW_REQUIRED":
            answer = "This request requires human review before FORGE can return an authoritative answer."
        else:
            answer = str(
                rules["payload"].get("reason")
                or "FORGE could not validate an evidence-backed answer for this request."
            )
        lineage = _persist_lineage(
            request,
            {
                "pipeline": "B-S-M-S",
                "query": query,
                "bouncer_verdict": "PASS",
                "parsed_intent": parsed_intent,
                "rules_verdict": rules["verdict"],
                "rules_applied": rules["rules_applied"],
                "evidence_sources": rules["payload"]["lineage"]["evidence_sources"],
                "executed_query": rules["payload"]["executed_query"],
                "rendering_source": "deterministic_formatter",
                "confidence": float(parsed_intent.get("confidence", 0.0) or 0.0),
                "runtime": {"llm": runtime},
                "bouncer": bouncer,
                "rules": rules,
            },
        )
        return BSMSQueryResponse(
            status=status,
            bouncer=bouncer,
            parsed_intent=parsed_intent,
            rules=rules,
            answer=answer,
            lineage=lineage,
        )

    formatted = _run_formatter_stage(query, parsed_intent, rules, runtime, request.require_llm)
    lineage = _persist_lineage(
        request,
        {
            "pipeline": "B-S-M-S",
            "query": query,
            "bouncer_verdict": "PASS",
            "parsed_intent": parsed_intent,
            "rules_verdict": rules["verdict"],
            "rules_applied": rules["rules_applied"],
            "evidence_sources": rules["payload"]["lineage"]["evidence_sources"],
            "executed_query": rules["payload"]["executed_query"],
            "rendering_source": formatted["rendering_source"],
            "confidence": float(parsed_intent.get("confidence", 0.0) or 0.0),
            "runtime": {"llm": runtime},
            "bouncer": bouncer,
            "rules": rules,
            "llm": formatted.get("llm"),
        },
    )
    return BSMSQueryResponse(
        status="ok",
        bouncer=bouncer,
        parsed_intent=parsed_intent,
        rules=rules,
        answer=str(formatted["answer"]),
        lineage=lineage,
    )


def _run_bouncer_stage(
    request: BSMSQueryRequest,
    query: str,
    runtime: dict[str, Any],
) -> dict[str, Any]:
    keywords = request.bsms_pipeline.get("bouncer_config", {}).get("domain_keywords", [])
    allowed_intents = request.bsms_pipeline.get("bouncer_config", {}).get("allowed_intents", [])
    lowered = query.lower()
    keyword_match = any(str(keyword).lower() in lowered for keyword in keywords[:200] if keyword)
    deterministic = {
        "status": "accepted" if keyword_match or len(query.split()) >= 3 else "rejected",
        "reason": None if keyword_match or len(query.split()) >= 3 else "Query appears outside generated domain vocabulary",
        "risk_flags": [],
        "decision_source": "deterministic_guardrail",
        "llm_runtime": runtime,
    }

    if not runtime["enabled"]:
        if request.require_llm:
            raise bsms_runtime.BSMSRuntimePolicyError(
                "FORGE BSMS bouncer requires LLM runtime, but no configured provider is available."
            )
        return deterministic

    user = {
        "query": query,
        "allowed_intents": allowed_intents,
        "domain_keywords": keywords[:80],
        "required_json_schema": {
            "status": "accepted|rejected",
            "reason": "short string or null",
            "matched_intent": "string or null",
            "risk_flags": ["string"],
            "confidence": 0.0,
        },
    }
    try:
        parsed, meta = bsms_runtime.complete_json(
            (
                "You are the FORGE BSMS bouncer. "
                "Allow only analytical read-only questions grounded in the compiled database domain. "
                "Reject out-of-domain, mutation, credential, or privileged administration requests. "
                "Return only JSON."
            ),
            _json_dumps(user),
            require_llm=request.require_llm,
            max_tokens=300,
            temperature=0.0,
        )
    except Exception as exc:
        if request.require_llm:
            raise bsms_runtime.BSMSRuntimePolicyError(f"BSMS bouncer failed closed: {exc}") from exc
        deterministic["llm_error"] = str(exc)
        return deterministic

    return {
        "status": "accepted" if parsed.get("status") == "accepted" else "rejected",
        "reason": parsed.get("reason"),
        "matched_intent": parsed.get("matched_intent"),
        "risk_flags": [str(flag) for flag in parsed.get("risk_flags", [])][:8],
        "confidence": float(parsed.get("confidence", 0.0) or 0.0),
        "decision_source": "llm_bouncer",
        "llm_runtime": runtime,
        "llm": meta,
    }


def _run_parser_stage(
    request: BSMSQueryRequest,
    query: str,
    questions: list[dict[str, Any]],
    runtime: dict[str, Any],
) -> dict[str, Any]:
    best_match = _match_question(query, questions)
    deterministic = {
        "question_id": best_match["id"],
        "question_text": best_match["text"],
        "question_type": best_match["type"],
        "table": best_match["table"],
        "filters": {},
        "confidence": best_match["score"],
        "rationale": "Selected by deterministic overlap ranking.",
        "decision_source": "deterministic_parser",
        "llm_runtime": runtime,
    }

    if not runtime["enabled"]:
        if request.require_llm:
            raise bsms_runtime.BSMSRuntimePolicyError(
                "FORGE BSMS parser requires LLM runtime, but no configured provider is available."
            )
        return deterministic

    candidates = _candidate_questions(query, questions, limit=min(request.limit, 8))
    field_mappings = request.bsms_pipeline.get("parser_config", {}).get("field_mappings", {})
    user = {
        "query": query,
        "candidate_questions": [
            {
                "id": candidate["id"],
                "text": candidate["text"],
                "type": candidate["type"],
                "table": candidate["table"],
                "columns": candidate.get("columns", []),
                "score": candidate.get("score", 0.0),
            }
            for candidate in candidates
        ],
        "field_mappings": {
            candidate["table"]: field_mappings.get(candidate["table"], [])
            for candidate in candidates
            if candidate.get("table")
        },
        "required_json_schema": {
            "question_id": "string",
            "filters": {"field": "scalar"},
            "confidence": 0.0,
            "rationale": "short string",
            "clarification_needed": False,
            "clarification_question": "string or null",
        },
    }
    try:
        parsed, meta = bsms_runtime.complete_json(
            (
                "You are the FORGE BSMS parser. "
                "Map the user query onto exactly one compiled question. "
                "Only emit equality filters that exist on the selected table. "
                "Return only JSON."
            ),
            _json_dumps(user),
            require_llm=request.require_llm,
            max_tokens=500,
            temperature=0.0,
        )
    except Exception as exc:
        if request.require_llm:
            raise bsms_runtime.BSMSRuntimePolicyError(f"BSMS parser failed closed: {exc}") from exc
        deterministic["llm_error"] = str(exc)
        return deterministic

    selected = next((candidate for candidate in candidates if candidate["id"] == str(parsed.get("question_id"))), None)
    if selected is None:
        if request.require_llm:
            raise bsms_runtime.BSMSRuntimePolicyError("BSMS parser returned an unknown question_id")
        return deterministic

    return {
        "question_id": selected["id"],
        "question_text": selected["text"],
        "question_type": selected["type"],
        "table": selected["table"],
        "filters": _sanitize_filters(parsed.get("filters", {}), selected["table"], request.bsms_pipeline),
        "confidence": float(parsed.get("confidence", selected.get("score", 0.0)) or 0.0),
        "rationale": parsed.get("rationale") or "Selected by LLM parser.",
        "clarification_needed": bool(parsed.get("clarification_needed", False)),
        "clarification_question": parsed.get("clarification_question"),
        "decision_source": "llm_parser",
        "llm_runtime": runtime,
        "llm": meta,
    }


def _run_rules_stage(
    request: BSMSQueryRequest,
    query: str,
    parsed_intent: dict[str, Any],
    gate: dict[str, Any],
) -> dict[str, Any]:
    evidence_sources = [f"question_map:{parsed_intent['question_id']}"]
    if parsed_intent.get("table"):
        evidence_sources.append(f"table:{parsed_intent['table']}")
    payload = {
        "question": {
            "id": parsed_intent["question_id"],
            "question": parsed_intent.get("question_text"),
            "type": parsed_intent.get("question_type"),
            "table": parsed_intent.get("table"),
            "filters": parsed_intent.get("filters", {}),
        },
        "results": {
            "mode": "compiled_question_selection",
            "selected_question_id": parsed_intent["question_id"],
            "filters": parsed_intent.get("filters", {}),
            "clarification_needed": bool(parsed_intent.get("clarification_needed", False)),
        },
        "executed_query": (
            f"compiled_question:{parsed_intent['question_id']}"
            + (
                f" filters={_json_dumps(parsed_intent.get('filters', {}), compact=True)}"
                if parsed_intent.get("filters")
                else ""
            )
        ),
        "lineage": {
            "evidence_sources": evidence_sources,
            "original_query": query,
        },
    }
    if gate["status"] != "approved" or parsed_intent.get("clarification_needed"):
        verdict = "HUMAN_REVIEW_REQUIRED"
    else:
        execution = _execute_compiled_question(request, query, parsed_intent)
        payload["results"] = execution["results"]
        payload["executed_query"] = execution["executed_query"]
        payload["lineage"]["evidence_sources"] = execution["lineage"]["evidence_sources"]
        if execution["verdict"] != "SUPPORTED":
            payload["reason"] = execution.get("reason")
        verdict = execution["verdict"]
    return {
        "verdict": verdict,
        "confidence": float(parsed_intent.get("confidence", 0.0) or 0.0),
        "gate": gate,
        "rules_applied": [parsed_intent.get("question_type"), "authority_pack", "gate_check"],
        "payload": payload,
    }


def _execute_compiled_question(
    request: BSMSQueryRequest,
    query: str,
    parsed_intent: dict[str, Any],
) -> dict[str, Any]:
    database_url = (request.database_url or "").strip()
    if not database_url:
        return {
            "verdict": "UNSUPPORTED",
            "reason": "FORGE BSMS cannot validate this question without a database connection.",
            "results": {"mode": "no_database_connection", "rows": []},
            "executed_query": None,
            "lineage": {"evidence_sources": [f"question_map:{parsed_intent['question_id']}"]},
        }

    _validate_compile_request(
        ForgeCompileRequest(
            database_url=database_url,
            app_name="FORGE BSMS Runtime",
            sample_rows_per_table=5,
            generate_bundle=False,
            require_llm_refinement=False,
        )
    )
    questions = _extract_questions(request.question_map)
    question = next((item for item in questions if item["id"] == parsed_intent["question_id"]), None)
    if question is None:
        return {
            "verdict": "UNSUPPORTED",
            "reason": "Selected question is no longer present in the compiled question map.",
            "results": {"mode": "missing_question", "rows": []},
            "executed_query": None,
            "lineage": {"evidence_sources": []},
        }

    try:
        return _run_query_execution(
            database_url,
            question,
            query,
            parsed_intent.get("filters", {}),
            request.limit,
        )
    except HTTPException as exc:
        return {
            "verdict": "UNSUPPORTED",
            "reason": str(exc.detail),
            "results": {"mode": "execution_error", "rows": []},
            "executed_query": None,
            "lineage": {"evidence_sources": [f"table:{question.get('table', '')}"]},
        }


def _run_query_execution(
    database_url: str,
    question: dict[str, Any],
    query: str,
    filters: dict[str, Any],
    limit: int,
) -> dict[str, Any]:
    engine = create_engine(database_url, **_engine_options(database_url))
    metadata = MetaData()
    table_name = str(question.get("table", "")).strip()
    if not table_name:
        raise HTTPException(status_code=400, detail="Selected question does not target a table.")
    table = _reflect_table(table_name, metadata, engine)
    question_type = str(question.get("type", "")).strip()
    target_columns = [str(column) for column in question.get("columns", []) if str(column).strip() and str(column) != "*"]
    join_tables = [str(name) for name in question.get("join_tables", []) if str(name).strip()]
    question_text = str(question.get("text", ""))
    execution_plan = question.get("execution_plan") if isinstance(question.get("execution_plan"), dict) else {}

    stmt = select(table)
    for key, value in filters.items():
        if key not in table.c:
            raise HTTPException(status_code=400, detail=f"Unknown filter column: {key}")
        stmt = stmt.where(func.lower(table.c[key].cast(String)) == str(value).lower())

    evidence_sources = [f"table:{table_name}"]
    with engine.connect() as connection:
        compiled_packet = _execute_compiled_plan(
            connection,
            table,
            metadata,
            engine,
            query,
            question_text,
            question_type,
            target_columns,
            join_tables,
            execution_plan,
            filters,
            limit,
            evidence_sources,
        )
        if compiled_packet is not None:
            return compiled_packet

        semantic_packet = _run_semantic_query_plan(
            connection,
            table,
            question_text,
            question_type,
            filters,
            limit,
            evidence_sources,
        )
        if semantic_packet is not None:
            return semantic_packet

        if question_type in {"detail_view", "categorical_filter", "filter"}:
            rows_stmt = stmt.limit(limit)
            rows = [dict(row) for row in connection.execute(rows_stmt).mappings()]
            return _evidence_packet(rows, rows_stmt, evidence_sources)

        if question_type == "text_search":
            search_columns = [column for column in target_columns if column in table.c]
            if not search_columns:
                raise HTTPException(status_code=400, detail="No searchable columns available for this question.")
            query_terms = [
                term for term in re.findall(r"\w+", query.lower())
                if len(term) > 2 and term not in {"show", "find", "search", "records", "record", "table", "data"}
            ]
            if query_terms:
                predicates = []
                for column in search_columns:
                    for term in query_terms:
                        predicates.append(func.lower(table.c[column].cast(String)).like(f"%{term}%"))
                if predicates:
                    stmt = stmt.where(or_(*predicates))
            rows_stmt = stmt.limit(limit)
            rows = [dict(row) for row in connection.execute(rows_stmt).mappings()]
            return _evidence_packet(rows, rows_stmt, evidence_sources)

        if question_type == "aggregation":
            metrics = [column for column in target_columns if column in table.c and _is_numeric_column(table.c[column].type)]
            if not metrics:
                raise HTTPException(status_code=400, detail="No numeric metric is available for this aggregation.")
            metric = metrics[0]
            agg_stmt = select(
                func.min(table.c[metric]).label("min"),
                func.max(table.c[metric]).label("max"),
                func.avg(table.c[metric]).label("avg"),
            )
            for key, value in filters.items():
                agg_stmt = agg_stmt.where(table.c[key] == value)
            summary = dict(connection.execute(agg_stmt).mappings().one())
            has_evidence = any(value is not None for value in summary.values())
            return {
                "verdict": "SUPPORTED" if has_evidence else "NO_EVIDENCE",
                "reason": None if has_evidence else "No aggregate evidence was available for the selected question.",
                "results": {"mode": "aggregation", "metric": metric, "summary": summary},
                "executed_query": str(agg_stmt),
                "lineage": {"evidence_sources": evidence_sources},
            }

        if question_type == "comparison":
            metrics = [column for column in target_columns if column in table.c and _is_numeric_column(table.c[column].type)]
            if len(metrics) < 2:
                raise HTTPException(status_code=400, detail="No valid numeric comparison columns are available.")
            comp_stmt = select(*[table.c[name] for name in metrics[:2]]).limit(limit)
            for key, value in filters.items():
                comp_stmt = comp_stmt.where(table.c[key] == value)
            rows = [dict(row) for row in connection.execute(comp_stmt).mappings()]
            return _evidence_packet(rows, comp_stmt, evidence_sources, mode="comparison", extra={"columns": metrics[:2]})

        if question_type == "time_series":
            timestamp_column = next((column for column in target_columns if column in table.c and _is_temporal_column(table.c[column].type)), None)
            numeric_column = next((column for column in target_columns if column in table.c and _is_numeric_column(table.c[column].type)), None)
            if not timestamp_column:
                timestamp_column = next((column.name for column in table.columns if _is_temporal_column(column.type)), None)
            if not numeric_column:
                numeric_column = next((column.name for column in table.columns if _is_numeric_column(column.type)), None)
            if not timestamp_column or not numeric_column:
                raise HTTPException(status_code=400, detail="No valid time-series columns are available.")
            ts_stmt = select(table.c[timestamp_column], table.c[numeric_column]).limit(limit)
            for key, value in filters.items():
                ts_stmt = ts_stmt.where(table.c[key] == value)
            rows = [dict(row) for row in connection.execute(ts_stmt).mappings()]
            return _evidence_packet(rows, ts_stmt, evidence_sources, mode="time_series", extra={"columns": [timestamp_column, numeric_column]})

        if question_type in {"relationship_join", "cross_reference"}:
            if question_type == "cross_reference":
                return {
                    "verdict": "UNSUPPORTED",
                    "reason": "FORGE cannot treat speculative cross-reference questions as supported without a compiled join plan.",
                    "results": {"mode": "speculative_cross_reference", "rows": []},
                    "executed_query": None,
                    "lineage": {"evidence_sources": evidence_sources},
                }
            join_stmt, joined_sources = _build_verified_join_stmt(table, metadata, engine, filters, join_tables, limit)
            rows = [dict(row) for row in connection.execute(join_stmt).mappings()]
            return _evidence_packet(rows, join_stmt, joined_sources, mode="relationship_join")

    raise HTTPException(status_code=400, detail=f"Unsupported question type: {question_type}")


def _build_verified_join_stmt(
    base_table: Table,
    metadata: MetaData,
    engine: Any,
    filters: dict[str, Any],
    join_tables: list[str],
    limit: int,
) -> tuple[Any, list[str]]:
    if not join_tables:
        raise HTTPException(status_code=400, detail="No join tables were compiled for this relationship question.")

    stmt = select(base_table)
    reflected: dict[str, Table] = {base_table.name: base_table}
    current_table = base_table
    evidence_sources = [f"table:{base_table.name}"]

    for join_name in join_tables:
        join_table = reflected.setdefault(join_name, _reflect_table(join_name, metadata, engine))
        join_condition = _foreign_key_join_condition(current_table, join_table) or _foreign_key_join_condition(join_table, current_table)
        if join_condition is None:
            raise HTTPException(
                status_code=400,
                detail=f"No verified foreign-key join path exists between {current_table.name} and {join_name}.",
            )
        stmt = stmt.add_columns(join_table).join(join_table, join_condition)
        current_table = join_table
        evidence_sources.append(f"table:{join_name}")

    for key, value in filters.items():
        if key not in base_table.c:
            raise HTTPException(status_code=400, detail=f"Unknown filter column: {key}")
        stmt = stmt.where(base_table.c[key] == value)

    return stmt.limit(limit), evidence_sources


def _foreign_key_join_condition(left: Table, right: Table) -> Any | None:
    for foreign_key in left.foreign_keys:
        if foreign_key.column.table.name == right.name:
            return foreign_key.parent == foreign_key.column
    return None


def _split_schema_qualified_name(name: str) -> tuple[str | None, str]:
    value = name.strip()
    if "." not in value:
        return None, value
    schema, table = value.split(".", 1)
    return schema, table


def _reflect_table(name: str, metadata: MetaData, engine: Any) -> Table:
    schema, table = _split_schema_qualified_name(name)
    return Table(table, metadata, schema=schema, autoload_with=engine)


def _run_semantic_query_plan(
    connection: Any,
    table: Table,
    question_text: str,
    question_type: str,
    filters: dict[str, Any],
    limit: int,
    evidence_sources: list[str],
) -> dict[str, Any] | None:
    # Removed: all domain-specific hardcoded handlers. Execution plans are the
    # sole contract between compile and runtime. If a question has no
    # execution_plan, it falls through to the generic type-based handlers below.
    return None


def _execute_compiled_plan(
    connection: Any,
    table: Table,
    metadata: MetaData,
    engine: Any,
    query: str,
    question_text: str,
    question_type: str,
    target_columns: list[str],
    join_tables: list[str],
    execution_plan: dict[str, Any],
    filters: dict[str, Any],
    limit: int,
    evidence_sources: list[str],
) -> dict[str, Any] | None:
    if not execution_plan:
        return None

    plan_type = str(execution_plan.get("plan_type", "")).strip()
    group_by = [str(name) for name in execution_plan.get("group_by", []) if str(name).strip() and str(name) in table.c]
    metrics = [str(name) for name in execution_plan.get("metrics", []) if str(name).strip() and str(name) in table.c]
    selected_columns = [
        str(name) for name in execution_plan.get("selected_columns", [])
        if str(name).strip() and str(name) in table.c
    ]
    filter_columns = [str(name) for name in execution_plan.get("filters", []) if str(name).strip() and str(name) in table.c]
    plan_join_tables = [str(name) for name in execution_plan.get("join_tables", []) if str(name).strip()]

    if plan_type == "detail_rows":
        # If the user query contains entity terms, search for those first
        entity_terms = _extract_entity_terms(query) if not filters else []
        if entity_terms:
            text_columns = [col for col in table.c if _is_text_column_type(col.type)]
            if text_columns:
                predicates = []
                for col in text_columns[:6]:
                    for term in entity_terms:
                        predicates.append(func.lower(col.cast(String)).like(f"%{term.lower()}%"))
                if predicates:
                    stmt = select(table).where(or_(*predicates)).limit(limit)
                    rows = [dict(row) for row in connection.execute(stmt).mappings()]
                    if rows:
                        return _evidence_packet(rows, stmt, evidence_sources, mode="detail_rows")
        # Explicit filters or plain detail view
        stmt = select(table).limit(limit)
        for key, value in filters.items():
            if key not in table.c:
                raise HTTPException(status_code=400, detail=f"Unknown filter column: {key}")
            stmt = stmt.where(func.lower(table.c[key].cast(String)) == str(value).lower())
        rows = [dict(row) for row in connection.execute(stmt).mappings()]
        return _evidence_packet(rows, stmt, evidence_sources, mode="detail_rows")

    if plan_type == "search_lookup":
        search_columns = filter_columns or selected_columns or target_columns
        if not search_columns:
            return None
        stmt = select(*[table.c[name] for name in search_columns if name in table.c]).limit(limit)
        query_terms = [
            term for term in re.findall(r"\w+", query.lower())
            if len(term) > 2 and term not in {"show", "find", "search", "records", "record", "table", "data", "browse"}
        ]
        if query_terms:
            predicates = []
            for column in search_columns:
                for term in query_terms:
                    predicates.append(func.lower(table.c[column].cast(String)).like(f"%{term}%"))
            if predicates:
                stmt = stmt.where(or_(*predicates))
        rows = [dict(row) for row in connection.execute(stmt).mappings()]
        return _evidence_packet(rows, stmt, evidence_sources, mode="search_lookup", extra={"columns": search_columns})

    if plan_type == "categorical_browse":
        if group_by:
            group_column = group_by[0]
            stmt = (
                select(
                    table.c[group_column].label(group_column),
                    func.count().label("record_count"),
                )
                .where(table.c[group_column].is_not(None))
                .group_by(table.c[group_column])
                .order_by(func.count().desc(), table.c[group_column].asc())
                .limit(limit)
            )
            rows = [dict(row) for row in connection.execute(stmt).mappings()]
            return _evidence_packet(rows, stmt, evidence_sources, mode="categorical_browse")
        return None

    if plan_type == "grouped_aggregation":
        if not metrics:
            return None
        metric = metrics[0]
        if group_by:
            group_column = group_by[0]
            stmt = (
                select(
                    table.c[group_column].label(group_column),
                    func.count().label("record_count"),
                    func.avg(table.c[metric]).label(f"avg_{metric}"),
                    func.min(table.c[metric]).label(f"min_{metric}"),
                    func.max(table.c[metric]).label(f"max_{metric}"),
                )
                .where(table.c[group_column].is_not(None))
                .where(table.c[metric].is_not(None))
                .group_by(table.c[group_column])
                .order_by(func.count().desc(), table.c[group_column].asc())
                .limit(limit)
            )
            rows = [dict(row) for row in connection.execute(stmt).mappings()]
            return _evidence_packet(rows, stmt, evidence_sources, mode="grouped_aggregation")
        return None

    if plan_type == "grouped_comparison":
        if len(metrics) < 2:
            return None
        if group_by:
            group_column = group_by[0]
            stmt = (
                select(
                    table.c[group_column].label(group_column),
                    *[func.avg(table.c[metric]).label(f"avg_{metric}") for metric in metrics[:2]],
                    func.count().label("record_count"),
                )
                .where(table.c[group_column].is_not(None))
                .group_by(table.c[group_column])
                .order_by(func.count().desc(), table.c[group_column].asc())
                .limit(limit)
            )
            rows = [dict(row) for row in connection.execute(stmt).mappings()]
            return _evidence_packet(rows, stmt, evidence_sources, mode="grouped_comparison", extra={"columns": metrics[:2]})
        return None

    if plan_type == "raw_comparison":
        if len(metrics) < 2:
            return None
        stmt = select(*[table.c[name] for name in metrics[:2]]).limit(limit)
        rows = [dict(row) for row in connection.execute(stmt).mappings()]
        return _evidence_packet(rows, stmt, evidence_sources, mode="raw_comparison", extra={"columns": metrics[:2]})

    if plan_type == "time_series":
        if not group_by or not metrics:
            return None
        timestamp_column = group_by[0]
        metric = metrics[0]
        stmt = select(table.c[timestamp_column], table.c[metric]).where(table.c[timestamp_column].is_not(None)).limit(limit)
        rows = [dict(row) for row in connection.execute(stmt).mappings()]
        return _evidence_packet(rows, stmt, evidence_sources, mode="time_series", extra={"columns": [timestamp_column, metric]})

    if plan_type == "relationship_trace":
        effective_join_tables = plan_join_tables or join_tables
        if effective_join_tables:
            join_stmt, joined_sources = _build_verified_join_stmt(table, metadata, engine, filters, effective_join_tables, limit)
            rows = [dict(row) for row in connection.execute(join_stmt).mappings()]
            return _evidence_packet(rows, join_stmt, joined_sources, mode="relationship_trace")
        if group_by:
            group_column = group_by[0]
            stmt = (
                select(table.c[group_column].label(group_column), func.count().label("record_count"))
                .where(table.c[group_column].is_not(None))
                .group_by(table.c[group_column])
                .order_by(func.count().desc(), table.c[group_column].asc())
                .limit(limit)
            )
            rows = [dict(row) for row in connection.execute(stmt).mappings()]
            return _evidence_packet(rows, stmt, evidence_sources, mode="relationship_trace")
        return None

    # ── Generic plan executor ──────────────────────────────────────────
    # All remaining plan_types are executed from the contract fields:
    #   group_by, metrics, filters, sort, entity_key, selected_columns
    # No column names are hardcoded. The plan IS the contract.
    return _execute_generic_plan(
        connection, table, plan_type, group_by, metrics, selected_columns,
        filter_columns, execution_plan, filters, query, limit, evidence_sources,
    )


def _execute_generic_plan(
    connection: Any,
    table: Table,
    plan_type: str,
    group_by: list[str],
    metrics: list[str],
    selected_columns: list[str],
    filter_columns: list[str],
    execution_plan: dict[str, Any],
    filters: dict[str, Any],
    query: str,
    limit: int,
    evidence_sources: list[str],
) -> dict[str, Any] | None:
    """Data-agnostic plan executor. Reads group_by/metrics/filters/sort from the
    compiled execution plan — no column names are hardcoded."""

    entity_key = str(execution_plan.get("entity_key", "")).strip()
    if entity_key and entity_key not in table.c:
        entity_key = ""
    sort_spec = execution_plan.get("sort", [])

    # Strategy 1: Grouped aggregation (group_by + metrics)
    if group_by and metrics:
        cols = [table.c[col].label(col) for col in group_by]
        for metric in metrics:
            cols.extend([
                func.avg(table.c[metric]).label(f"avg_{metric}"),
                func.min(table.c[metric]).label(f"min_{metric}"),
                func.max(table.c[metric]).label(f"max_{metric}"),
            ])
        cols.append(func.count().label("record_count"))
        stmt = select(*cols)
        # WHERE: group_by columns not null, first metric not null
        for col in group_by:
            stmt = stmt.where(table.c[col].is_not(None))
        stmt = stmt.where(table.c[metrics[0]].is_not(None))
        # Apply user filters
        stmt = _apply_filters(stmt, table, filters)
        # GROUP BY
        stmt = stmt.group_by(*[table.c[col] for col in group_by])
        # ORDER BY from plan sort spec
        stmt = _apply_sort(stmt, table, sort_spec, fallback_count_desc=True)
        stmt = stmt.limit(limit)
        rows = [dict(row) for row in connection.execute(stmt).mappings()]
        return _evidence_packet(rows, stmt, evidence_sources, mode=plan_type)

    # Strategy 2: Grouped count (group_by, no metrics)
    if group_by and not metrics:
        group_column = group_by[0]
        stmt = (
            select(table.c[group_column].label(group_column), func.count().label("record_count"))
            .where(table.c[group_column].is_not(None))
            .group_by(table.c[group_column])
        )
        stmt = _apply_filters(stmt, table, filters)
        stmt = _apply_sort(stmt, table, sort_spec, fallback_count_desc=True)
        stmt = stmt.limit(limit)
        rows = [dict(row) for row in connection.execute(stmt).mappings()]
        return _evidence_packet(rows, stmt, evidence_sources, mode=plan_type)

    # Strategy 3: Entity listing (selected_columns or entity_key, no grouping)
    if selected_columns or entity_key:
        cols_to_select = selected_columns or ([entity_key] if entity_key else [col.name for col in table.columns])
        cols_to_select = [col for col in cols_to_select if col in table.c]
        if not cols_to_select:
            cols_to_select = [col.name for col in table.columns]
        stmt = select(*[table.c[col] for col in cols_to_select])
        if entity_key:
            stmt = stmt.where(table.c[entity_key].is_not(None))
        stmt = _apply_filters(stmt, table, filters)
        # Entity search: if query contains specific terms, search text columns
        entity_terms = _extract_entity_terms(query) if not filters else []
        if entity_terms:
            text_cols = [table.c[col] for col in cols_to_select if col in table.c and _is_text_column_type(table.c[col].type)]
            if text_cols:
                predicates = []
                for col in text_cols[:6]:
                    for term in entity_terms:
                        predicates.append(func.lower(col.cast(String)).like(f"%{term.lower()}%"))
                if predicates:
                    stmt = stmt.where(or_(*predicates))
        stmt = _apply_sort(stmt, table, sort_spec)
        stmt = stmt.limit(limit)
        rows = [dict(row) for row in connection.execute(stmt).mappings()]
        return _evidence_packet(rows, stmt, evidence_sources, mode=plan_type)

    # Strategy 4: Raw metrics (metrics, no grouping)
    if metrics:
        stmt = select(*[table.c[col] for col in metrics]).limit(limit)
        stmt = _apply_filters(stmt, table, filters)
        rows = [dict(row) for row in connection.execute(stmt).mappings()]
        return _evidence_packet(rows, stmt, evidence_sources, mode=plan_type)

    # Unknown plan shape — cannot execute
    return None


def _apply_filters(stmt: Any, table: Table, filters: dict[str, Any]) -> Any:
    """Apply user-supplied filters with case-insensitive text matching."""
    for key, value in filters.items():
        if key not in table.c:
            continue
        if _is_text_column_type(table.c[key].type):
            stmt = stmt.where(func.lower(table.c[key].cast(String)).like(f"%{str(value).lower()}%"))
        else:
            stmt = stmt.where(table.c[key] == value)
    return stmt


def _apply_sort(
    stmt: Any,
    table: Table,
    sort_spec: list[dict[str, str]],
    *,
    fallback_count_desc: bool = False,
) -> Any:
    """Apply sort from the execution plan's sort spec."""
    applied = False
    for entry in sort_spec:
        col_name = str(entry.get("column", "")).strip()
        direction = str(entry.get("direction", "asc")).lower()
        if col_name in table.c:
            col = table.c[col_name]
            stmt = stmt.order_by(col.desc() if direction == "desc" else col.asc())
            applied = True
        elif col_name == "record_count":
            stmt = stmt.order_by(func.count().desc() if direction == "desc" else func.count().asc())
            applied = True
    if not applied and fallback_count_desc:
        stmt = stmt.order_by(func.count().desc())
    return stmt


def _evidence_packet(
    rows: list[dict[str, Any]],
    stmt: Any,
    evidence_sources: list[str],
    *,
    mode: str = "rows",
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = {"mode": mode, "rows": rows}
    if extra:
        payload.update(extra)
    return {
        "verdict": "SUPPORTED" if rows else "NO_EVIDENCE",
        "reason": None if rows else "FORGE found no evidence rows for the selected question.",
        "results": payload,
        "executed_query": str(stmt),
        "lineage": {"evidence_sources": evidence_sources},
    }


def _is_numeric_column(column_type: Any) -> bool:
    return any(token in str(column_type).lower() for token in ("int", "numeric", "decimal", "float", "real", "double"))


def _is_temporal_column(column_type: Any) -> bool:
    return any(token in str(column_type).lower() for token in ("date", "time"))


def _is_text_column_type(column_type: Any) -> bool:
    return any(token in str(column_type).lower() for token in ("varchar", "char", "text", "string", "clob"))


_STOP_WORDS = frozenset({
    "tell", "me", "everything", "about", "show", "find", "search", "what",
    "which", "how", "does", "the", "and", "for", "with", "from", "that",
    "this", "all", "are", "its", "knew", "know", "knows", "data", "records",
    "it", "a", "an", "in", "on", "of", "to", "is", "was", "be", "do",
    "has", "have", "can", "will", "by", "at", "or", "not", "no", "any",
})


def _extract_entity_terms(query: str) -> list[str]:
    """Extract meaningful entity terms from a user query for text search fallback."""
    words = re.findall(r"\w+", query.lower())
    # Keep multi-word phrases by looking for consecutive non-stop-words
    terms: list[str] = []
    current_phrase: list[str] = []
    for word in words:
        if word not in _STOP_WORDS and len(word) > 1:
            current_phrase.append(word)
        else:
            if current_phrase:
                terms.append(" ".join(current_phrase))
                current_phrase = []
    if current_phrase:
        terms.append(" ".join(current_phrase))
    # Also add individual words for broader matching
    individual = [w for w in words if w not in _STOP_WORDS and len(w) > 2]
    for word in individual:
        if word not in terms:
            terms.append(word)
    return terms[:10]


def _run_formatter_stage(
    query: str,
    parsed_intent: dict[str, Any],
    rules: dict[str, Any],
    runtime: dict[str, Any],
    require_llm: bool,
) -> dict[str, Any]:
    deterministic_answer = _deterministic_answer(rules)
    if not runtime["enabled"]:
        if require_llm:
            raise bsms_runtime.BSMSRuntimePolicyError(
                "FORGE BSMS formatter requires LLM runtime, but no configured provider is available."
            )
        return {
            "answer": deterministic_answer,
            "rendering_source": "deterministic_formatter",
            "llm": None,
        }

    try:
        formatted, meta = bsms_runtime.complete_json(
            (
                "You are the FORGE BSMS formatter. "
                "Write a concise answer grounded only in the provided result packet. "
                "Do not invent facts. "
                "Return only JSON."
            ),
            _json_dumps(
                {
                    "query": query,
                    "parsed_intent": parsed_intent,
                    "rules_packet": {
                        "verdict": rules["verdict"],
                        "confidence": rules["confidence"],
                        "gate": rules.get("gate"),
                        "rules_applied": rules.get("rules_applied"),
                        "payload": rules.get("payload"),
                    },
                    "required_json_schema": {
                        "answer": "string",
                        "follow_up": "string or null",
                        "confidence_label": "low|medium|high",
                    },
                }
            ),
            require_llm=require_llm,
            max_tokens=500,
            temperature=0.1,
        )
    except Exception as exc:
        if require_llm:
            raise bsms_runtime.BSMSRuntimePolicyError(f"BSMS formatter failed closed: {exc}") from exc
        return {
            "answer": deterministic_answer,
            "rendering_source": "deterministic_formatter",
            "llm": {"error": str(exc)},
        }

    return {
        "answer": formatted.get("answer") or deterministic_answer,
        "rendering_source": "llm_formatter",
        "llm": {
            **meta,
            "confidence_label": formatted.get("confidence_label"),
            "follow_up": formatted.get("follow_up"),
        },
    }


def _extract_questions(question_map: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract a flat question list from categorized or flat question maps."""
    questions: list[dict[str, Any]] = []
    for category in question_map.get("question_categories", []):
        for question in category.get("questions", []):
            questions.append(
                {
                    "id": question.get("id", ""),
                    "text": question.get("text", question.get("natural_language", question.get("question", ""))),
                    "type": question.get("type", question.get("template_type", category.get("category", ""))),
                    "table": question.get("table", question.get("target_table", "")),
                    "columns": question.get("target_columns", []),
                    "join_tables": question.get("join_tables", []),
                    "capability_id": question.get("capability_id", ""),
                    "intent_family": question.get("intent_family", ""),
                    "execution_plan": question.get("execution_plan", {}),
                }
            )
    for question in question_map.get("questions", []):
        questions.append(
            {
                "id": question.get("id", ""),
                "text": question.get("question", question.get("natural_language", question.get("text", ""))),
                "type": question.get("question_type", question.get("type", "")),
                "table": question.get("table", question.get("target_table", "")),
                "columns": question.get("target_columns", []),
                "join_tables": question.get("join_tables", question.get("path_tables", [])[1:]),
                "capability_id": question.get("capability_id", ""),
                "intent_family": question.get("intent_family", ""),
                "execution_plan": question.get("execution_plan", {}),
            }
        )
    return questions


def _match_question(query: str, questions: list[dict[str, Any]]) -> dict[str, Any]:
    """Find the best matching question using weighted overlap scoring."""
    query_words = set(re.findall(r"\w+", query.lower()))

    best = questions[0]
    best_score = 0.0
    for question in questions:
        text_words = set(re.findall(r"\w+", str(question.get("text", "")).lower()))
        type_words = set(re.findall(r"\w+", str(question.get("type", "")).lower()))
        table_words = set(re.findall(r"\w+", str(question.get("table", "")).lower()))
        column_words = {
            token
            for column in question.get("columns", [])
            for token in re.findall(r"\w+", str(column).lower())
        }
        overlap = len(query_words & (text_words | type_words | table_words | column_words))
        score = overlap / max(len(query_words), 1)
        if question.get("table") and str(question["table"]).lower() in query.lower():
            score += 0.2
        if score > best_score:
            best_score = score
            best = question

    return {**best, "score": min(max(best_score, 0.2), 1.0)}


def _candidate_questions(query: str, questions: list[dict[str, Any]], *, limit: int) -> list[dict[str, Any]]:
    ranked = [_match_question(query, [question]) for question in questions]
    ranked.sort(key=lambda question: float(question.get("score", 0.0)), reverse=True)
    return ranked[: max(1, limit)]


def _sanitize_filters(raw_filters: Any, table: str, bsms_pipeline: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(raw_filters, dict):
        return {}
    allowed_columns = {
        str(column)
        for column in bsms_pipeline.get("parser_config", {}).get("field_mappings", {}).get(table, [])
    }
    sanitized: dict[str, Any] = {}
    for key, value in raw_filters.items():
        if str(key) not in allowed_columns:
            continue
        if isinstance(value, (str, int, float, bool)) or value is None:
            sanitized[str(key)] = value
        else:
            sanitized[str(key)] = str(value)
    return sanitized


def _deterministic_answer(rules: dict[str, Any]) -> str:
    if rules["verdict"] == "HUMAN_REVIEW_REQUIRED":
        return "This request requires human review before FORGE can return an authoritative answer."
    question = rules["payload"]["question"]
    filters = question.get("filters", {})
    filter_text = f" with filters {_json_dumps(filters, compact=True)}" if filters else ""
    return (
        f"FORGE matched '{question['question']}' on '{question['table']}'"
        f"{filter_text} and selected compiled question '{question['id']}'."
    )


def _persist_lineage(request: BSMSQueryRequest, payload: dict[str, Any]) -> dict[str, Any]:
    if not request.persist_lineage:
        return payload
    return bsms_runtime.record_lineage(payload, lineage_dir=request.lineage_dir)


def _json_dumps(value: Any, *, compact: bool = False) -> str:
    if compact:
        return json.dumps(value, default=str, sort_keys=True, separators=(",", ":"))
    return json.dumps(value, default=str, indent=2, sort_keys=True)
