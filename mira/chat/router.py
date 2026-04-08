"""
Module: MIRA Chat — Router
Purpose: POST /api/chat endpoint — the orchestration hub that ties
         query interpretation, engine dispatch, formatting, and auditing
         together per BS-SPEC-MIRA-CHAT-001-REV2.

Multi-turn design:
  - In-memory session store persists engine context (e.g. OCA case_id)
    across turns within the same session_id.
  - Every ChatResponse includes extracted entities so the frontend can
    echo them back in the next ChatMessage.entities field.
  - The query interpreter uses those entities for anaphora resolution
    ("What about at 1500 psi?" inherits material from prior turn).

BoundState AI 2026
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: SWE-013, SWE-032, NASA-STD-8739.8B
Safety Critical: True
"""

from __future__ import annotations

import hashlib
import logging
import re
import traceback
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from .audit import generate_audit_id, write_audit_record
from .engine_adapter import EngineAdapter
from .models import (
    AuditRecord,
    ChatMessage,
    ChatRequest,
    ChatResponse,
    EngineEnvelope,
    Status,
    TaskMode,
)
from .module_context import resolve_module_context, extract_module_entities
from .query_interpreter import ParsedQuery, interpret
from .rate_limiter import get_rate_limiter
from .response_formatter import extract_follow_ups, format_response
from .streaming import _sse_event, stream_formatter_response
from .db.router_integration import (
    get_or_create_session,
    save_session_state,
    append_history,
    get_effective_history,
)

LOGGER = logging.getLogger(__name__)

_MAX_HISTORY_MESSAGES = 10


# ---------------------------------------------------------------------------
# Adapter registry
# ---------------------------------------------------------------------------

_adapter_cache: dict[str, EngineAdapter] = {}


def _load_adapters() -> dict[str, EngineAdapter]:
    """Build and cache the engine adapter registry.

    Each adapter is imported inside the function body so that a broken
    import (e.g. missing data file) only affects that one engine — the
    rest remain available.
    """
    if _adapter_cache:
        return _adapter_cache

    def _try_load(name: str, factory):  # type: ignore[no-untyped-def]
        try:
            adapter = factory()
            _adapter_cache[name] = adapter
            LOGGER.debug("Chat adapter loaded: %s", name)
        except Exception:
            LOGGER.warning("Chat adapter failed to load: %s", name, exc_info=True)

    def _oca():
        from .adapters.oca_adapter import OcaAdapter
        return OcaAdapter()

    def _h2():
        from .adapters.h2_adapter import H2Adapter
        return H2Adapter()

    def _maptis():
        from .adapters.maptis_adapter import MAPTISAdapter
        return MAPTISAdapter()

    def _bsmh():
        from .adapters.bsmh_adapter import BSMHAdapter
        return BSMHAdapter()

    def _galvanic():
        from .adapters.galvanic_adapter import GalvanicAdapter
        return GalvanicAdapter()

    def _fracture():
        from .adapters.fracture_adapter import FractureAdapter
        return FractureAdapter()

    def _gpcm():
        from .adapters.gpcm_adapter import GPCMAdapter
        return GPCMAdapter()

    _try_load("oca", _oca)
    _try_load("h2", _h2)
    _try_load("maptis_search", _maptis)
    _try_load("bsmh", _bsmh)
    _try_load("galvanic", _galvanic)
    _try_load("fracture", _fracture)
    _try_load("gpcm", _gpcm)

    return _adapter_cache


def get_adapter(engine_id: str) -> EngineAdapter | None:
    """Return the adapter for *engine_id*, or ``None`` if unavailable."""
    adapters = _load_adapters()
    return adapters.get(engine_id)


# ---------------------------------------------------------------------------
# FastAPI Router
# ---------------------------------------------------------------------------

router = APIRouter(prefix="/api/chat", tags=["chat"])

__safety_critical__ = True  # NASA SWE-032 compliance


@router.get("/ping")
async def ping() -> dict[str, str]:
    """Health check for the chat subsystem."""
    adapters = _load_adapters()
    return {
        "status": "ok",
        "domain": "chat",
        "adapters_loaded": ",".join(sorted(adapters.keys())),
    }


@router.post("/")
async def chat(request: ChatRequest) -> ChatResponse:
    """
    Unified MIRA Chat endpoint — multi-turn, evidence-grounded.

    Pipeline:
    1. Restore session state (engine context, accumulated entities)
    2. Parse the user query (intent + entities + task mode)
    3. If clarification needed → return clarifying question with entities
    4. Dispatch to the appropriate engine adapter
    5. Format response with senior M&P engineer voice
    6. Build follow-up suggestions
    7. Write audit record
    8. Persist session state + return response with entities
    """
    request_id = f"req-{uuid4().hex[:12]}"
    session_id = request.session_id or f"session-{uuid4().hex[:8]}"

    LOGGER.info(
        "[CHAT] request_id=%s session=%s message_length=%d history_turns=%d",
        request_id,
        session_id,
        len(request.message),
        len(request.history),
    )

    # ------------------------------------------------------------------
    # 0. Rate limiting (BS-SPEC Section 13)
    # ------------------------------------------------------------------
    limiter = get_rate_limiter()
    allowed, rejection_reason = limiter.check_and_record(session_id, request.message)
    if not allowed:
        LOGGER.warning(
            "[CHAT] Rate limit rejected: session=%s reason=%s",
            session_id, rejection_reason,
        )
        return _error_response(
            rejection_reason or "Rate limit exceeded.",
            session_id=session_id,
            request_id=request_id,
        )

    # ------------------------------------------------------------------
    # 1. Restore session
    # ------------------------------------------------------------------
    session = await get_or_create_session(session_id)
    session["turn_count"] += 1
    effective_history = await get_effective_history(session_id, request.history)

    _prime_session_from_history(session, effective_history)

    # Pre-populate session entities from module_context on first turn
    if session["turn_count"] == 1 and request.module_context:
        module_entities = extract_module_entities(request.module_context)
        session["accumulated_entities"].update(module_entities)

    # Build session_context that adapters can read/write
    session_context: dict[str, Any] = {
        "session_id": session_id,
        "request_id": request_id,
        "turn_count": session["turn_count"],
        "accumulated_entities": dict(session["accumulated_entities"]),
        **session["engine_context"],  # Includes oca_case_id etc. from prior turns
    }
    if request.module_context:
        session_context["module_context"] = dict(request.module_context)

    # ------------------------------------------------------------------
    # 2. Parse query
    # ------------------------------------------------------------------
    try:
        parsed: ParsedQuery = interpret(
            request.message,
            history=effective_history,
            module_context=request.module_context,
        )
    except Exception as exc:
        LOGGER.exception("[CHAT] Query interpretation failed: %s", exc)
        return _error_response(
            "I wasn't able to parse that query. Could you rephrase it? "
            "For example: 'Is 316L compatible with GOX at 3000 psi?'",
            session_id=session_id,
            request_id=request_id,
        )

    # ------------------------------------------------------------------
    # 2a. Module context resolution (BS-SPEC Section 9.2)
    # ------------------------------------------------------------------
    if request.module_context:
        try:
            parsed = resolve_module_context(
                request.message,
                request.module_context,
                parsed,
            )
        except Exception as exc:
            LOGGER.warning("[CHAT] Module context resolution failed: %s", exc)

    # Build the entities dict that we'll return to the frontend
    turn_entities = _build_turn_entities(parsed)

    # Merge into session's accumulated entities (latest wins)
    session["accumulated_entities"].update(
        {k: v for k, v in turn_entities.items() if v is not None}
    )
    session_context["accumulated_entities"] = dict(session["accumulated_entities"])

    # ------------------------------------------------------------------
    # 3. Clarification check
    # ------------------------------------------------------------------
    if parsed.clarification_needed:
        LOGGER.info(
            "[CHAT] Clarification needed: routing=%s conf=%.2f",
            parsed.fine_routing,
            parsed.routing_confidence,
        )
        return ChatResponse(
            response=parsed.clarification_question,
            session_id=session_id,
            engine_used=None,
            verdict=None,
            audit_id=None,
            follow_up_suggestions=[],
            mode=parsed.task_mode,
            entities=turn_entities,
        )

    if parsed.task_mode == TaskMode.REVIEW_EXISTING:
        review_prompt = (
            "What document would you like me to review? "
            "Please upload or identify the artifact."
        )
        await save_session_state(session_id, session)
        await append_history(session_id, request.message, review_prompt, None, turn_entities)
        return ChatResponse(
            response=review_prompt,
            session_id=session_id,
            engine_used=None,
            verdict=Status.INSUFFICIENT_DATA.value,
            audit_id=None,
            follow_up_suggestions=[],
            mode=parsed.task_mode,
            entities=turn_entities,
        )

    # ------------------------------------------------------------------
    # 4. Look up adapter
    # ------------------------------------------------------------------
    adapter = None
    engine_id = parsed.fine_routing

    if parsed.task_mode == TaskMode.DRAFT_ARTIFACT:
        envelope = _build_draft_envelope(parsed, session)
        if envelope is None:
            message = (
                "I can draft that, but I need an assessed material and service context first. "
                "Run the compatibility question, then ask me to draft the MUA."
            )
            await save_session_state(session_id, session)
            await append_history(session_id, request.message, message, None, turn_entities)
            return ChatResponse(
                response=message,
                session_id=session_id,
                engine_used=None,
                verdict=Status.INSUFFICIENT_DATA.value,
                audit_id=None,
                follow_up_suggestions=[],
                mode=parsed.task_mode,
                entities=turn_entities,
            )
        engine_id = envelope.engine_id
        turn_entities["engine_used"] = engine_id
    else:
        adapter = get_adapter(engine_id)

        if adapter is None:
            LOGGER.warning("[CHAT] No adapter for engine_id=%s", engine_id)
            return _error_response(
                f"The {engine_id} engine is not available right now. "
                "You can try the dedicated module or rephrase your question.",
                session_id=session_id,
                request_id=request_id,
                entities=turn_entities,
            )

    # ------------------------------------------------------------------
    # 5. Execute engine
    # ------------------------------------------------------------------
    if parsed.task_mode != TaskMode.DRAFT_ARTIFACT:
        parsed_input = _build_parsed_input(parsed)

        try:
            envelope = await adapter.execute(
                parsed_input,
                session_context,
            )
        except Exception as exc:
            LOGGER.exception("[CHAT] Engine %s raised: %s", engine_id, exc)
            envelope = EngineEnvelope(
                status=Status.ERROR,
                engine_id=engine_id,
                response_text=f"Engine error: {exc}",
                domain_payload={
                    "error_type": type(exc).__name__,
                    "error_detail": str(exc),
                    "traceback": traceback.format_exc(),
                },
            )

        # Persist any engine context the adapter wrote back (e.g. oca_case_id)
        session["engine_context"].update(
            {
                k: v
                for k, v in session_context.items()
                if k not in ("session_id", "request_id", "turn_count", "accumulated_entities")
            }
        )

    _remember_last_assessment(session, parsed, turn_entities, envelope)

    # ------------------------------------------------------------------
    # 6. Format response
    # ------------------------------------------------------------------
    try:
        formatted = await format_response(envelope, session_context=session_context)
    except Exception as exc:
        LOGGER.exception("[CHAT] Formatter failed: %s", exc)
        formatted = envelope.response_text or f"Engine returned: {envelope.status.value}"

    # ------------------------------------------------------------------
    # 7. Follow-up suggestions
    # ------------------------------------------------------------------
    try:
        follow_up_dicts = [] if envelope.status == Status.REFUSE else extract_follow_ups(envelope)
        follow_up_labels = [f["label"] for f in follow_up_dicts]
    except Exception:
        LOGGER.exception("[CHAT] Follow-up extraction failed")
        follow_up_labels = []

    # ------------------------------------------------------------------
    # 8. Audit record
    # ------------------------------------------------------------------
    audit_id = generate_audit_id()

    try:
        audit_routing = engine_id if parsed.task_mode == TaskMode.DRAFT_ARTIFACT else parsed.fine_routing
        record = AuditRecord(
            audit_id=audit_id,
            timestamp=datetime.now(timezone.utc),
            session_id=session_id,
            user_input=request.message,
            parsed_entities=turn_entities,
            normalized_units=_normalized_units(parsed),
            coarse_intent=parsed.coarse_intent,
            fine_routing=audit_routing,
            task_mode=envelope.mode,
            routing_confidence=parsed.routing_confidence,
            engines_invoked=[engine_id],
            engine_versions={engine_id: envelope.engine_version},
            engine_status=envelope.status,
            source_citations=envelope.citations,
            assumptions=envelope.assumptions,
            missing_inputs=envelope.missing_inputs,
            llm_model_used=session_context.get("formatter_model_used"),
            response_hash=_response_hash(formatted),
            artifact_generated=(envelope.mode == TaskMode.DRAFT_ARTIFACT),
            follow_ups_offered=follow_up_labels,
            follow_ups_taken=[],
            module_context=request.module_context,
            envelope_json=envelope.model_dump(mode="json"),
            authority_basis=envelope.authority_basis,
            error_detail=(
                envelope.domain_payload.get("error_detail")
                if envelope.status == Status.ERROR
                else None
            ),
        )
        write_audit_record(record)
    except Exception:
        LOGGER.exception("[CHAT] Audit write failed for request_id=%s", request_id)

    # ------------------------------------------------------------------
    # 9. Return with entities for multi-turn continuity
    # ------------------------------------------------------------------
    await save_session_state(session_id, session)
    await append_history(session_id, request.message, formatted, engine_id, turn_entities)

    return ChatResponse(
        response=formatted,
        session_id=session_id,
        engine_used=engine_id,
        verdict=envelope.status.value,
        audit_id=audit_id,
        follow_up_suggestions=follow_up_labels,
        mode=envelope.mode,
        entities=turn_entities,
    )


# ---------------------------------------------------------------------------
# SSE Streaming Endpoint (Phase 2)
# ---------------------------------------------------------------------------


@router.post("/stream")
async def chat_stream(request: ChatRequest) -> StreamingResponse:
    """SSE streaming endpoint per BS-SPEC-MIRA-CHAT-001-REV2 Section 11.3.

    Reuses the SAME pipeline as the synchronous ``POST /api/chat`` endpoint
    (parse query -> check clarification -> lookup adapter -> execute engine).
    Only the formatting step differs: instead of awaiting a complete Claude
    response, the formatter streams thinking and text blocks as SSE events.

    After streaming completes, the audit record is written and the ``done``
    event carries the audit_id back to the frontend.
    """

    async def _event_generator():  # noqa: C901 — complexity is inherent
        request_id = f"req-{uuid4().hex[:12]}"
        session_id = request.session_id or f"session-{uuid4().hex[:8]}"

        LOGGER.info(
            "[CHAT-STREAM] request_id=%s session=%s message_length=%d history_turns=%d",
            request_id,
            session_id,
            len(request.message),
            len(request.history),
        )

        # --------------------------------------------------------------
        # 0. Rate limiting (BS-SPEC Section 13)
        # --------------------------------------------------------------
        limiter = get_rate_limiter()
        allowed, rejection_reason = limiter.check_and_record(session_id, request.message)
        if not allowed:
            LOGGER.warning(
                "[CHAT-STREAM] Rate limit rejected: session=%s reason=%s",
                session_id, rejection_reason,
            )
            yield _sse_event({"type": "meta", "engine_id": None, "verdict": "ERROR", "mode": None})
            yield _sse_event({"type": "text_start"})
            yield _sse_event({"type": "text", "content": rejection_reason or "Rate limit exceeded."})
            yield _sse_event({"type": "text_end"})
            yield _sse_event({
                "type": "done",
                "audit_id": None,
                "session_id": session_id,
                "entities": {},
                "follow_ups": [],
            })
            return

        # --------------------------------------------------------------
        # 1. Restore session
        # --------------------------------------------------------------
        session = await get_or_create_session(session_id)
        session["turn_count"] += 1
        effective_history = await get_effective_history(session_id, request.history)

        _prime_session_from_history(session, effective_history)

        # Pre-populate session entities from module_context on first turn
        if session["turn_count"] == 1 and request.module_context:
            module_entities = extract_module_entities(request.module_context)
            session["accumulated_entities"].update(module_entities)

        session_context: dict[str, Any] = {
            "session_id": session_id,
            "request_id": request_id,
            "turn_count": session["turn_count"],
            "accumulated_entities": dict(session["accumulated_entities"]),
            **session["engine_context"],
        }
        if request.module_context:
            session_context["module_context"] = dict(request.module_context)

        # --------------------------------------------------------------
        # 2. Parse query
        # --------------------------------------------------------------
        try:
            parsed: ParsedQuery = interpret(
                request.message,
                history=effective_history,
                module_context=request.module_context,
            )
        except Exception as exc:
            LOGGER.exception("[CHAT-STREAM] Query interpretation failed: %s", exc)
            err_msg = (
                "I wasn't able to parse that query. Could you rephrase it? "
                "For example: 'Is 316L compatible with GOX at 3000 psi?'"
            )
            yield _sse_event({"type": "meta", "engine_id": None, "verdict": "ERROR", "mode": None})
            yield _sse_event({"type": "text_start"})
            yield _sse_event({"type": "text", "content": err_msg})
            yield _sse_event({"type": "text_end"})
            yield _sse_event({
                "type": "done",
                "audit_id": None,
                "session_id": session_id,
                "entities": {},
                "follow_ups": [],
            })
            return

        # Module context resolution (BS-SPEC Section 9.2)
        if request.module_context:
            try:
                parsed = resolve_module_context(
                    request.message,
                    request.module_context,
                    parsed,
                )
            except Exception as exc:
                LOGGER.warning("[CHAT-STREAM] Module context resolution failed: %s", exc)

        turn_entities = _build_turn_entities(parsed)
        session["accumulated_entities"].update(
            {k: v for k, v in turn_entities.items() if v is not None}
        )
        session_context["accumulated_entities"] = dict(session["accumulated_entities"])

        # --------------------------------------------------------------
        # 3. Clarification check
        # --------------------------------------------------------------
        if parsed.clarification_needed:
            LOGGER.info(
                "[CHAT-STREAM] Clarification needed: routing=%s conf=%.2f",
                parsed.fine_routing,
                parsed.routing_confidence,
            )
            yield _sse_event({
                "type": "meta",
                "engine_id": None,
                "verdict": None,
                "mode": parsed.task_mode.value,
            })
            yield _sse_event({"type": "text_start"})
            yield _sse_event({"type": "text", "content": parsed.clarification_question})
            yield _sse_event({"type": "text_end"})
            yield _sse_event({
                "type": "done",
                "audit_id": None,
                "session_id": session_id,
                "entities": turn_entities,
                "follow_ups": [],
            })
            return

        if parsed.task_mode == TaskMode.REVIEW_EXISTING:
            review_prompt = (
                "What document would you like me to review? "
                "Please upload or identify the artifact."
            )
            await save_session_state(session_id, session)
            await append_history(session_id, request.message, review_prompt, None, turn_entities)
            yield _sse_event({
                "type": "meta",
                "engine_id": None,
                "verdict": Status.INSUFFICIENT_DATA.value,
                "mode": parsed.task_mode.value,
            })
            yield _sse_event({"type": "text_start"})
            yield _sse_event({"type": "text", "content": review_prompt})
            yield _sse_event({"type": "text_end"})
            yield _sse_event({
                "type": "done",
                "audit_id": None,
                "session_id": session_id,
                "entities": turn_entities,
                "follow_ups": [],
            })
            return

        # --------------------------------------------------------------
        # 4. Look up adapter
        # --------------------------------------------------------------
        adapter = None
        engine_id = parsed.fine_routing

        if parsed.task_mode == TaskMode.DRAFT_ARTIFACT:
            envelope = _build_draft_envelope(parsed, session)
            if envelope is None:
                message = (
                    "I can draft that, but I need an assessed material and service context first. "
                    "Run the compatibility question, then ask me to draft the MUA."
                )
                await save_session_state(session_id, session)
                await append_history(session_id, request.message, message, None, turn_entities)
                yield _sse_event({
                    "type": "meta",
                    "engine_id": None,
                    "verdict": Status.INSUFFICIENT_DATA.value,
                    "mode": parsed.task_mode.value,
                })
                yield _sse_event({"type": "text_start"})
                yield _sse_event({"type": "text", "content": message})
                yield _sse_event({"type": "text_end"})
                yield _sse_event({
                    "type": "done",
                    "audit_id": None,
                    "session_id": session_id,
                    "entities": turn_entities,
                    "follow_ups": [],
                })
                return
            engine_id = envelope.engine_id
            turn_entities["engine_used"] = engine_id
        else:
            adapter = get_adapter(engine_id)

            if adapter is None:
                LOGGER.warning("[CHAT-STREAM] No adapter for engine_id=%s", engine_id)
                err_msg = (
                    f"The {engine_id} engine is not available right now. "
                    "You can try the dedicated module or rephrase your question."
                )
                yield _sse_event({
                    "type": "meta",
                    "engine_id": engine_id,
                    "verdict": "ERROR",
                    "mode": None,
                })
                yield _sse_event({"type": "text_start"})
                yield _sse_event({"type": "text", "content": err_msg})
                yield _sse_event({"type": "text_end"})
                yield _sse_event({
                    "type": "done",
                    "audit_id": None,
                    "session_id": session_id,
                    "entities": turn_entities,
                    "follow_ups": [],
                })
                return

        # --------------------------------------------------------------
        # 5. Execute engine (synchronous — engines are fast)
        # --------------------------------------------------------------
        if parsed.task_mode != TaskMode.DRAFT_ARTIFACT:
            parsed_input = _build_parsed_input(parsed)

            try:
                envelope = await adapter.execute(
                    parsed_input,
                    session_context,
                )
            except Exception as exc:
                LOGGER.exception("[CHAT-STREAM] Engine %s raised: %s", engine_id, exc)
                envelope = EngineEnvelope(
                    status=Status.ERROR,
                    engine_id=engine_id,
                    response_text=f"Engine error: {exc}",
                    domain_payload={
                        "error_type": type(exc).__name__,
                        "error_detail": str(exc),
                        "traceback": traceback.format_exc(),
                    },
                )

            session["engine_context"].update(
                {
                    k: v
                    for k, v in session_context.items()
                    if k not in ("session_id", "request_id", "turn_count", "accumulated_entities")
                }
            )

        _remember_last_assessment(session, parsed, turn_entities, envelope)

        # --------------------------------------------------------------
        # 6. Stream the formatter response
        # --------------------------------------------------------------
        async for sse_event in stream_formatter_response(envelope, session_context):
            yield sse_event

        # Retrieve the final assembled text written by the streaming function
        formatted = session_context.get("_stream_final_text", "")
        if not formatted:
            formatted = envelope.response_text or f"Engine returned: {envelope.status.value}"

        # --------------------------------------------------------------
        # 7. Follow-up suggestions
        # --------------------------------------------------------------
        try:
            follow_up_dicts = [] if envelope.status == Status.REFUSE else extract_follow_ups(envelope)
            follow_up_labels = [f["label"] for f in follow_up_dicts]
        except Exception:
            LOGGER.exception("[CHAT-STREAM] Follow-up extraction failed")
            follow_up_labels = []

        # --------------------------------------------------------------
        # 8. Audit record
        # --------------------------------------------------------------
        audit_id = generate_audit_id()

        try:
            audit_routing = engine_id if parsed.task_mode == TaskMode.DRAFT_ARTIFACT else parsed.fine_routing
            record = AuditRecord(
                audit_id=audit_id,
                timestamp=datetime.now(timezone.utc),
                session_id=session_id,
                user_input=request.message,
                parsed_entities=turn_entities,
                normalized_units=_normalized_units(parsed),
                coarse_intent=parsed.coarse_intent,
                fine_routing=audit_routing,
                task_mode=envelope.mode,
                routing_confidence=parsed.routing_confidence,
                engines_invoked=[engine_id],
                engine_versions={engine_id: envelope.engine_version},
                engine_status=envelope.status,
                source_citations=envelope.citations,
                assumptions=envelope.assumptions,
                missing_inputs=envelope.missing_inputs,
                llm_model_used=session_context.get("formatter_model_used"),
                response_hash=_response_hash(formatted),
                artifact_generated=(envelope.mode == TaskMode.DRAFT_ARTIFACT),
                follow_ups_offered=follow_up_labels,
                follow_ups_taken=[],
                module_context=request.module_context,
                envelope_json=envelope.model_dump(mode="json"),
                authority_basis=envelope.authority_basis,
                error_detail=(
                    envelope.domain_payload.get("error_detail")
                    if envelope.status == Status.ERROR
                    else None
                ),
            )
            write_audit_record(record)
        except Exception:
            LOGGER.exception("[CHAT-STREAM] Audit write failed for request_id=%s", request_id)

        # --------------------------------------------------------------
        # 9. Session history + done event
        # --------------------------------------------------------------
        await save_session_state(session_id, session)
        await append_history(session_id, request.message, formatted, engine_id, turn_entities)

        yield _sse_event({
            "type": "done",
            "audit_id": audit_id,
            "session_id": session_id,
            "entities": turn_entities,
            "follow_ups": follow_up_labels,
        })

    return StreamingResponse(
        _event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_turn_entities(parsed: ParsedQuery) -> dict[str, Any]:
    """Extract the resolved entities from a ParsedQuery for return to frontend.

    These get echoed back in the next turn's ChatMessage.entities field,
    enabling the query interpreter to resolve anaphora like "that material"
    and "what about at 1500 psi?".
    """
    entities: dict[str, Any] = {}
    if parsed.material_designation:
        entities["material_designation"] = parsed.material_designation
    if parsed.second_material:
        entities["second_material"] = parsed.second_material
    if parsed.gas_service:
        entities["gas_service"] = parsed.gas_service
    if parsed.environment:
        entities["environment"] = parsed.environment
    if parsed.pressure:
        entities["pressure"] = parsed.pressure
        entities["pressure_value"] = parsed.pressure_value
    if parsed.temperature:
        entities["temperature"] = parsed.temperature
        entities["temperature_value"] = parsed.temperature_value
    if parsed.standard_ref:
        entities["standard_ref"] = parsed.standard_ref
    if parsed.fine_routing:
        entities["engine_used"] = parsed.fine_routing
    return entities


def _build_parsed_input(parsed: ParsedQuery) -> dict[str, Any]:
    """Convert a ParsedQuery dataclass into the dict expected by adapters.

    For OCA, also builds the structured service_context/materials dicts
    that the OCA adapter's _build_case_request expects.
    """
    base = {
        "raw_query": parsed.raw_query,
        "coarse_intent": parsed.coarse_intent,
        "fine_routing": parsed.fine_routing,
        "task_mode": parsed.task_mode.value,
        "material_designation": parsed.material_designation,
        "second_material": parsed.second_material,
        "gas_service": parsed.gas_service,
        "environment": parsed.environment,
        "pressure": parsed.pressure,
        "pressure_value": parsed.pressure_value,
        "temperature": parsed.temperature,
        "temperature_value": parsed.temperature_value,
        "standard_ref": parsed.standard_ref,
        "dissimilar_metals": parsed.dissimilar_metals,
        "fracture_context": parsed.fracture_context,
        "routing_confidence": parsed.routing_confidence,
        "inherited_entities": parsed.inherited_entities,
    }

    # OCA needs structured input — build it from flat entities
    if parsed.fine_routing == "oca" and parsed.material_designation:
        base["service_context"] = _build_oca_service_context(parsed)
        base["materials"] = [{"material_name": parsed.material_designation}]
        base["components"] = [
            {
                "component_class": "line",
                "geometry_class": "bulk",
                "design_function": "pressure_boundary",
                "pressure_boundary_material": parsed.material_designation,
                "is_rigid_metallic_tubing": True,
            }
        ]
        base["free_text_intake"] = parsed.raw_query

    # H2 needs material + pressure + query
    if parsed.fine_routing == "h2":
        base["material"] = parsed.material_designation
        base["pressure_psia"] = parsed.pressure_value
        base["question"] = parsed.raw_query

    # MAPTIS needs query text
    if parsed.fine_routing == "maptis_search":
        base["query"] = parsed.raw_query

    # BSMH needs query text
    if parsed.fine_routing == "bsmh":
        base["query"] = parsed.raw_query

    # Galvanic needs two materials + environment
    if parsed.fine_routing == "galvanic":
        base["second_material"] = (
            parsed.second_material or parsed.inherited_entities.get("second_material")
        )
        base["environment"] = (
            parsed.environment or parsed.inherited_entities.get("environment")
        )

    # Fracture needs part_name + material
    if parsed.fine_routing == "fracture":
        base["part_name"] = parsed.inherited_entities.get("part_name", "")
        base["mission_class"] = parsed.inherited_entities.get("mission_class")

    # GPCM needs material + gas_service
    if parsed.fine_routing == "gpcm":
        base["query"] = parsed.raw_query

    return base


def _error_response(
    message: str,
    *,
    session_id: str,
    request_id: str,
    entities: dict[str, Any] | None = None,
) -> ChatResponse:
    """Build a ChatResponse for error / unrecoverable situations."""
    return ChatResponse(
        response=message,
        session_id=session_id,
        engine_used=None,
        verdict=Status.ERROR.value,
        audit_id=None,
        follow_up_suggestions=[],
        mode=None,
        entities=entities or {},
    )


def _prime_session_from_history(
    session: dict[str, Any],
    effective_history: list[ChatMessage],
) -> None:
    """Rehydrate session continuity from frontend-supplied history.

    This keeps multi-turn routing resilient when the API process restarts
    between requests and only the browser still holds the conversation.
    """
    if not effective_history:
        return

    session["history"] = effective_history[-_MAX_HISTORY_MESSAGES:]

    prior_turns = sum(1 for msg in effective_history if msg.role == "assistant")
    if prior_turns:
        session["turn_count"] = max(session.get("turn_count", 0), prior_turns + 1)

    accumulated_entities: dict[str, Any] = session.setdefault("accumulated_entities", {})
    if accumulated_entities:
        return

    for turn in effective_history[-_MAX_HISTORY_MESSAGES:]:
        if not turn.entities:
            continue
        accumulated_entities.update(
            {key: value for key, value in turn.entities.items() if value is not None}
        )


def _build_oca_service_context(parsed: ParsedQuery) -> dict[str, Any]:
    """Map parsed chat entities to the real ``mira.oca`` service context schema."""
    raw = parsed.raw_query.lower()
    oxidizer_type = "gox"
    phase = "gas"
    if "lox" in raw or "liquid oxygen" in raw:
        oxidizer_type = "lox"
        phase = "liquid"

    service_context: dict[str, Any] = {
        "oxidizer_type": oxidizer_type,
        "o2_fraction": 1.0,
        "phase": phase,
    }
    if parsed.pressure_value is not None:
        service_context["total_pressure_min_psia"] = parsed.pressure_value
        service_context["total_pressure_max_psia"] = parsed.pressure_value
        if parsed.gas_service == "oxygen":
            service_context["oxygen_partial_pressure_psia"] = parsed.pressure_value

    temperature_c = _temperature_celsius(parsed.temperature)
    if temperature_c is not None:
        service_context["temp_min_c"] = temperature_c
        service_context["temp_max_c"] = temperature_c
    else:
        service_context["temp_min_c"] = 20.0
        service_context["temp_max_c"] = 20.0

    return service_context


def _temperature_celsius(raw_temperature: str | None) -> float | None:
    if not raw_temperature:
        return None
    match = re.search(
        r"(-?\d+(?:\.\d+)?)\s*(?:°\s*)?([FfCcKk]|Fahrenheit|Celsius|Kelvin)",
        raw_temperature,
    )
    if not match:
        return None
    value = float(match.group(1))
    unit = match.group(2).lower()
    if unit.startswith("f"):
        return (value - 32.0) * 5.0 / 9.0
    if unit.startswith("k"):
        return value - 273.15
    return value


def _normalized_units(parsed: ParsedQuery) -> dict[str, str]:
    normalized: dict[str, str] = {}
    if parsed.pressure and parsed.pressure_value is not None:
        normalized["pressure"] = f"{parsed.pressure} -> {parsed.pressure_value / 145.038:.2f} MPa"
    if parsed.temperature:
        temp_c = _temperature_celsius(parsed.temperature)
        if temp_c is not None:
            normalized["temperature"] = f"{parsed.temperature} -> {temp_c:.2f} C"
    return normalized


def _response_hash(response_text: str) -> str:
    digest = hashlib.sha256(response_text.encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def _remember_last_assessment(
    session: dict[str, Any],
    parsed: ParsedQuery,
    turn_entities: dict[str, Any],
    envelope: EngineEnvelope,
) -> None:
    """Persist the latest draftable assessment context for follow-on draft requests."""
    if envelope.status in {Status.ERROR, Status.REFUSE}:
        return
    if envelope.mode != TaskMode.ANSWER_ONLY:
        return
    if parsed.fine_routing not in {"oca", "h2"}:
        return
    if not turn_entities.get("material_designation"):
        return

    session["last_assessment"] = {
        "engine_id": envelope.engine_id,
        "engine_version": envelope.engine_version,
        "status": envelope.status.value,
        "entities": dict(turn_entities),
        "response_text": envelope.response_text,
        "citations": list(envelope.citations),
        "assumptions": list(envelope.assumptions),
        "recommended_actions": [str(item) for item in envelope.recommended_actions],
        "domain_payload": dict(envelope.domain_payload),
    }


def _build_draft_envelope(
    parsed: ParsedQuery,
    session: dict[str, Any],
) -> EngineEnvelope | None:
    """Generate a transient DRAFT artifact from the latest assessment context."""
    last = session.get("last_assessment")
    if not last:
        return None

    entities = last.get("entities", {})
    material = entities.get("material_designation")
    gas_service = entities.get("gas_service")
    pressure_value = entities.get("pressure_value")
    if not material or not gas_service:
        return None

    citations = [str(item) for item in last.get("citations", [])]
    assumptions = [str(item) for item in last.get("assumptions", [])]
    recommended_actions = [
        str(item)
        for item in last.get("recommended_actions", [])
        if str(item).strip()
    ]
    verdict = str(last.get("status", Status.CONDITIONAL_PASS.value))
    try:
        status = Status(verdict)
    except ValueError:
        status = Status.CONDITIONAL_PASS

    lines = [
        "Material Usage Agreement (MUA) Draft",
        f"Material: {material}",
        f"Service: {gas_service}",
    ]
    if pressure_value is not None:
        lines.append(f"Pressure: {pressure_value:g} psia")
    lines.append(f"Source verdict: {verdict}")
    lines.append("")
    lines.append("Scope:")
    lines.append(
        "This draft captures the currently assessed material/service combination for engineering review."
    )

    if assumptions:
        lines.append("")
        lines.append("Assumptions carried from the assessment:")
        lines.extend(f"- {item}" for item in assumptions)

    if recommended_actions:
        lines.append("")
        lines.append("Assessment-driven actions to incorporate:")
        lines.extend(f"- {item}" for item in recommended_actions)

    if citations:
        lines.append("")
        lines.append("Citations to preserve in the reviewed artifact:")
        lines.extend(f"- {item}" for item in citations)

    lines.append("")
    lines.append("Approval note:")
    lines.append(
        "This draft requires review and approval per your program's M&P Plan before use."
    )

    return EngineEnvelope(
        status=status,
        engine_id=str(last.get("engine_id", "oca")),
        engine_version=str(last.get("engine_version", "1.0.0")),
        mode=TaskMode.DRAFT_ARTIFACT,
        response_text="\n".join(lines),
        citations=citations,
        assumptions=assumptions,
        recommended_actions=[],
        domain_payload={
            "draft_source_engine": last.get("engine_id"),
            "draft_source_verdict": verdict,
        },
    )
