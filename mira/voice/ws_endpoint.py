"""FastAPI WebSocket endpoint at /api/chat/voice.

Demo-mode auth: if Cognito is configured, callers must include a Bearer-style
token via ``?token=...`` query parameter (validated against the same Cognito
issuer the HTTP middleware uses). When auth is disabled, the WebSocket
accepts unconditionally.

Concurrency: the running session count is capped by ``VoiceConfig.max_concurrent_sessions``;
excess connections are rejected with code 1013 (server busy).
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState

from mira.chat.audit_identity import build_user_identity_from_claims
from mira.chat.models import UserIdentity

from .chat_bridge import stream_chat_events
from .config import VoiceConfig, get_voice_config
from .presence import build_greeting
from .providers import build_stt_provider, build_tts_provider
from .session import VoiceSession

LOGGER = logging.getLogger(__name__)

router = APIRouter(prefix="/api/chat", tags=["chat", "voice"])

_active_sessions: set[str] = set()
_sessions_lock = asyncio.Lock()


async def _try_acquire_slot(session_id: str, limit: int) -> bool:
    async with _sessions_lock:
        if len(_active_sessions) >= limit:
            return False
        _active_sessions.add(session_id)
        return True


async def _release_slot(session_id: str) -> None:
    async with _sessions_lock:
        _active_sessions.discard(session_id)


async def _resolve_identity(token: str | None) -> tuple[bool, UserIdentity | None]:
    """Validate the Cognito token and surface the resulting identity.

    Returns ``(allowed, identity)``. When auth is disabled, returns
    ``(True, anonymous-identity)``. When auth is enabled, an invalid or
    missing token returns ``(False, None)``.
    """
    from mira.api.auth.cognito import auth_enabled, verify_token_string

    if not auth_enabled():
        return True, build_user_identity_from_claims(None, auth_method="anonymous")
    if not token:
        return False, None
    try:
        claims = await verify_token_string(token)
    except Exception:
        LOGGER.warning("voice ws: token validation failed")
        return False, None
    return True, build_user_identity_from_claims(claims)


def _build_session(websocket: WebSocket, config: VoiceConfig) -> VoiceSession:
    stt = build_stt_provider(config)
    tts = build_tts_provider(config)

    async def _send_json(payload: dict[str, Any]) -> None:
        if websocket.client_state == WebSocketState.DISCONNECTED:
            return
        try:
            await websocket.send_json(payload)
        except Exception as exc:
            LOGGER.debug("voice ws: send_json failed: %s", exc)

    return VoiceSession(
        stt=stt,
        tts=tts,
        chat_stream_factory=stream_chat_events,
        config=config,
        send_json=_send_json,
    )


@router.websocket("/voice")
async def voice_endpoint(
    websocket: WebSocket,
    token: str | None = Query(default=None),
) -> None:
    config = get_voice_config()
    if not config.enabled:
        await websocket.close(code=1008, reason="voice disabled")
        return

    allowed, identity = await _resolve_identity(token)
    if not allowed:
        await websocket.close(code=4401, reason="unauthorized")
        return

    session = _build_session(websocket, config)
    session.user_identity = identity
    if not await _try_acquire_slot(session.session_id, config.max_concurrent_sessions):
        await websocket.close(code=1013, reason="voice capacity full")
        return

    await websocket.accept()
    try:
        while not session.closed:
            try:
                message = await websocket.receive_json()
            except WebSocketDisconnect:
                break
            except ValueError:
                LOGGER.debug("voice ws: non-JSON message")
                continue

            if not isinstance(message, dict):
                continue
            await session.handle_message(message)
    finally:
        await session.close()
        await _release_slot(session.session_id)
        if websocket.client_state != WebSocketState.DISCONNECTED:
            try:
                await websocket.close()
            except Exception:
                pass


# ---------------------------------------------------------------------------
# Companion HTTP endpoints (voice config & presence greeting)
# ---------------------------------------------------------------------------


# Voice catalogs change rarely; cache the upstream list_voices() call so
# opening voice settings doesn't hit Polly/ElevenLabs every time.
_VOICES_CACHE_TTL_SECONDS = 300.0
_voices_cache: tuple[float, str, list[dict[str, str]]] | None = None


@router.get("/voice/voices")
async def list_voices() -> dict[str, Any]:
    global _voices_cache
    config = get_voice_config()
    tts = build_tts_provider(config)

    now = asyncio.get_event_loop().time()
    if (
        _voices_cache is not None
        and _voices_cache[1] == tts.provider_id
        and now - _voices_cache[0] < _VOICES_CACHE_TTL_SECONDS
    ):
        voices = _voices_cache[2]
    else:
        voices = await tts.list_voices()
        _voices_cache = (now, tts.provider_id, voices)

    return {
        "provider": tts.provider_id,
        "voices": voices,
        "demo_mode": config.demo_mode,
        "default_voice_id": (
            config.elevenlabs_voice_id
            if config.tts_provider == "elevenlabs"
            else config.polly_voice_id
        ),
    }


@router.get("/voice/status")
async def voice_status() -> dict[str, Any]:
    config = get_voice_config()
    async with _sessions_lock:
        active = len(_active_sessions)
    return {
        "enabled": config.enabled,
        "demo_mode": config.demo_mode,
        "stt_provider": config.stt_provider,
        "tts_provider": config.tts_provider,
        "active_sessions": active,
        "max_concurrent_sessions": config.max_concurrent_sessions,
        "has_real_stt": config.has_real_stt,
        "has_real_tts": config.has_real_tts,
    }


@router.post("/presence")
async def presence(payload: dict[str, Any]) -> dict[str, Any]:
    """Return a page-aware greeting for the supplied module_context.

    Body shape: ``{"module_context": {...}, "session_id": "..."}``.
    Returns ``{"greeting": null}`` if no contextual greeting applies.
    """
    module_context = payload.get("module_context")
    greeting = build_greeting(module_context if isinstance(module_context, dict) else None)
    if greeting is None:
        return {"greeting": None}
    return {
        "greeting": {
            "text": greeting.text,
            "step_key": greeting.step_key,
            "step_label": greeting.step_label,
            "blockers": greeting.blockers,
        }
    }
