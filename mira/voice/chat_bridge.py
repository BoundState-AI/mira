"""Bridge from the voice WebSocket into the existing chat SSE stream.

Voice is purely a transport layer — multi-turn state, query interpretation,
engine dispatch, formatting, and auditing all live in the existing chat
pipeline. This bridge invokes ``chat_stream`` in-process and yields parsed
SSE event dicts so the voice session can react to them.
"""

from __future__ import annotations

import json
import logging
from typing import Any, AsyncIterator

LOGGER = logging.getLogger(__name__)


async def stream_chat_events(
    message: str,
    session_id: str | None,
    history: list[dict[str, Any]],
    module_context: dict[str, Any] | None,
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

    request = ChatRequest(
        message=message,
        session_id=session_id,
        history=history_models,
        module_context=module_context,
    )

    response = await chat_stream(request)

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
