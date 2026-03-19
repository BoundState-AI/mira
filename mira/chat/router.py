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

import logging
import threading
import traceback
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from fastapi import APIRouter

from .audit import generate_audit_id, write_audit_record
from .engine_adapter import EngineAdapter
from .models import (
    AuditRecord,
    ChatRequest,
    ChatResponse,
    EngineEnvelope,
    SideEffectLevel,
    Status,
    TaskMode,
)
from .query_interpreter import ParsedQuery, interpret
from .response_formatter import extract_follow_ups, format_response

LOGGER = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# In-memory session store (Phase 1)
# ---------------------------------------------------------------------------
# Persists engine context (OCA case_id, accumulated entities, etc.) across
# turns within the same session_id.  Phase 2 migrates to server-side
# SessionManager backed by Redis or PostgreSQL.

_session_store: dict[str, dict[str, Any]] = {}
_session_lock = threading.Lock()

# Cap the number of sessions to prevent unbounded memory growth.
_MAX_SESSIONS = 500


def _get_session(session_id: str) -> dict[str, Any]:
    """Return (or create) the session dict for *session_id*."""
    with _session_lock:
        if session_id not in _session_store:
            # Evict oldest sessions if at capacity
            if len(_session_store) >= _MAX_SESSIONS:
                oldest = next(iter(_session_store))
                del _session_store[oldest]
            _session_store[session_id] = {
                "engine_context": {},  # per-engine state (e.g. oca_case_id)
                "accumulated_entities": {},  # entities seen so far in this session
                "turn_count": 0,
            }
        return _session_store[session_id]


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

    _try_load("oca", _oca)
    _try_load("h2", _h2)
    _try_load("maptis_search", _maptis)
    _try_load("bsmh", _bsmh)

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
    # 1. Restore session
    # ------------------------------------------------------------------
    session = _get_session(session_id)
    session["turn_count"] += 1

    # Build session_context that adapters can read/write
    session_context: dict[str, Any] = {
        "session_id": session_id,
        "request_id": request_id,
        "turn_count": session["turn_count"],
        **session["engine_context"],  # Includes oca_case_id etc. from prior turns
    }

    # ------------------------------------------------------------------
    # 2. Parse query
    # ------------------------------------------------------------------
    try:
        parsed: ParsedQuery = interpret(
            request.message,
            history=request.history,
            module_context=request.module_context,
        )
    except Exception as exc:
        LOGGER.exception("[CHAT] Query interpretation failed: %s", exc)
        return _error_response(
            "I wasn't able to parse that query. Could you rephrase it? "
            "For example: 'Is 316L compatible with GOX at 3000 psi?'",
            request_id=request_id,
        )

    # Build the entities dict that we'll return to the frontend
    turn_entities = _build_turn_entities(parsed)

    # Merge into session's accumulated entities (latest wins)
    session["accumulated_entities"].update(
        {k: v for k, v in turn_entities.items() if v is not None}
    )

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
            engine_used=None,
            verdict=None,
            audit_id=None,
            follow_up_suggestions=[],
            mode=None,
            entities=turn_entities,
        )

    # ------------------------------------------------------------------
    # 4. Look up adapter
    # ------------------------------------------------------------------
    engine_id = parsed.fine_routing
    adapter = get_adapter(engine_id)

    if adapter is None:
        LOGGER.warning("[CHAT] No adapter for engine_id=%s", engine_id)
        return _error_response(
            f"The {engine_id} engine is not available right now. "
            "You can try the dedicated module or rephrase your question.",
            request_id=request_id,
            entities=turn_entities,
        )

    # ------------------------------------------------------------------
    # 5. Execute engine
    # ------------------------------------------------------------------
    parsed_input = _build_parsed_input(parsed)

    try:
        envelope: EngineEnvelope = await adapter.execute(
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
        {k: v for k, v in session_context.items()
         if k not in ("session_id", "request_id", "turn_count")}
    )

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
        follow_up_dicts = extract_follow_ups(envelope)
        follow_up_labels = [f["label"] for f in follow_up_dicts]
    except Exception:
        LOGGER.exception("[CHAT] Follow-up extraction failed")
        follow_up_labels = []

    # ------------------------------------------------------------------
    # 8. Audit record
    # ------------------------------------------------------------------
    audit_id = generate_audit_id()

    try:
        record = AuditRecord(
            audit_id=audit_id,
            timestamp=datetime.now(timezone.utc),
            session_id=session_id,
            user_message=request.message,
            module_context=request.module_context,
            engine_id=engine_id,
            engine_version=envelope.engine_version,
            mode=envelope.mode,
            status=envelope.status,
            side_effect_level=adapter.side_effect_level,
            envelope_json=envelope.model_dump(mode="json"),
            authority_basis=envelope.authority_basis,
            citations=envelope.citations,
            assumptions=envelope.assumptions,
            missing_inputs=envelope.missing_inputs,
            recommended_actions=envelope.recommended_actions,
            domain_payload=envelope.domain_payload,
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
    return ChatResponse(
        response=formatted,
        engine_used=engine_id,
        verdict=envelope.status.value,
        audit_id=audit_id,
        follow_up_suggestions=follow_up_labels,
        mode=envelope.mode,
        entities=turn_entities,
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
    if parsed.gas_service:
        entities["gas_service"] = parsed.gas_service
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
        "gas_service": parsed.gas_service,
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
        base["service_context"] = {
            "gas_type": "GOX" if parsed.gas_service == "oxygen" else "LOX",
            "pressure_psi": parsed.pressure_value,
        }
        base["materials"] = [{
            "designation": parsed.material_designation,
        }]
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

    return base


def _error_response(
    message: str,
    *,
    request_id: str,
    entities: dict[str, Any] | None = None,
) -> ChatResponse:
    """Build a ChatResponse for error / unrecoverable situations."""
    return ChatResponse(
        response=message,
        engine_used=None,
        verdict=Status.ERROR.value,
        audit_id=None,
        follow_up_suggestions=[],
        mode=None,
        entities=entities or {},
    )
