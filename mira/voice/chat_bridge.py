"""Bridge from the voice WebSocket into the existing chat SSE stream.

Voice is purely a transport layer — multi-turn state, query interpretation,
engine dispatch, formatting, and auditing all live in the existing chat
pipeline. This bridge invokes ``chat_stream`` in-process and yields parsed
SSE event dicts so the voice session can react to them.

Identity plumbing: the WebSocket validates the Cognito token at accept
time. The resulting ``UserIdentity`` is injected onto a synthetic Starlette
``Request`` scope so the chat router writes it (and ``turn_modality=voice``)
into the audit record — same code path as HTTP turns.
"""

from __future__ import annotations

import json
import logging
from typing import Any, AsyncIterator

from starlette.requests import Request

LOGGER = logging.getLogger(__name__)


def _build_voice_request(user_identity: Any | None) -> Request:
    """Construct a minimal Starlette Request that carries voice-turn identity."""
    scope: dict[str, Any] = {
        "type": "http",
        "method": "POST",
        "path": "/api/chat/stream",
        "headers": [],
        "query_string": b"",
        "state": {},
    }

    async def _receive() -> dict[str, Any]:
        return {"type": "http.disconnect"}

    request = Request(scope, receive=_receive)
    request.state.voice_turn = True
    if user_identity is not None:
        request.state.voice_user_identity = user_identity
    return request


async def stream_chat_events(
    message: str,
    session_id: str | None,
    history: list[dict[str, Any]],
    module_context: dict[str, Any] | None,
    *,
    user_identity: Any | None = None,
) -> AsyncIterator[dict[str, Any]]:
    """Yield parsed SSE event dicts from the in-process chat stream pipeline."""
    from mira.chat.models import ChatMessage, ChatRequest
    from mira.chat.router import chat_stream

    history_models: list[ChatMessage] = []
    for entry in history[-10:] if history else []:
        if not isinstance(entry, dict):
            continue
        try:
            history_models.append(ChatMessage(**entry))
        except Exception:
            LOGGER.debug("voice bridge: skipping malformed history entry")

    chat_request = ChatRequest(
        message=message,
        session_id=session_id,
        history=history_models,
        module_context=module_context,
    )

    voice_request = _build_voice_request(user_identity)
    response = await chat_stream(chat_request, voice_request)

    buffer = b""
    async for chunk in response.body_iterator:
        if isinstance(chunk, memoryview):
            chunk = bytes(chunk)
        elif isinstance(chunk, str):
            chunk = chunk.encode("utf-8")
        buffer += chunk

        while True:
            boundary = buffer.find(b"\n\n")
            if boundary == -1:
                break
            block = buffer[:boundary]
            buffer = buffer[boundary + 2 :]
            parsed = _parse_sse_block(block)
            if parsed is not None:
                yield parsed

    if buffer.strip():
        parsed = _parse_sse_block(buffer)
        if parsed is not None:
            yield parsed


def _parse_sse_block(block: bytes) -> dict[str, Any] | None:
    data_segments: list[str] = []
    for line in block.split(b"\n"):
        if line.startswith(b"data:"):
            data_segments.append(line[5:].lstrip(b" ").decode("utf-8", errors="replace"))
    if not data_segments:
        return None
    payload = "\n".join(data_segments)
    try:
        return json.loads(payload)
    except json.JSONDecodeError:
        LOGGER.debug("voice bridge: failed to parse SSE block: %r", payload[:200])
        return None
