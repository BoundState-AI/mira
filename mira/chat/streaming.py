"""
Module: MIRA Chat — SSE Streaming Formatter
Purpose: Server-Sent Events streaming of the Claude formatter response per
         BS-SPEC-MIRA-CHAT-001-REV2 Section 11.3.

Phase 2 streams the formatter's Claude response to the frontend via SSE,
enabling real-time display of thinking (reasoning panel) and text (main
content) as the model generates them.

The streaming function reuses the same system prompt and prompt builder from
the synchronous formatter — only the transport layer differs.

SSE Event Protocol:
  meta           — engine_id, verdict, mode (sent immediately)
  thinking_start — reasoning block begins
  thinking       — reasoning content delta
  thinking_end   — reasoning block ends
  text_start     — content block begins
  text           — content text delta
  text_end       — content block ends
  done           — stream complete, carries audit_id + session metadata
  error          — something went wrong

BoundState AI 2026
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: SWE-013, SWE-032, NASA-STD-8739.8B
Safety Critical: True
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, AsyncGenerator

from .models import EngineEnvelope, Status
from .response_formatter import (
    DEFAULT_FORMATTER_MODEL_TIER,
    DEFAULT_FORMATTER_PROVIDER,
    FORMATTER_MAX_TOKENS,
    FORMATTER_TEMPERATURE,
    build_formatter_system_prompt,
    build_formatter_prompt,
    _fallback_format,
    format_response,
)
from mira.providers.llm_provider import resolve_model_for_provider, resolve_provider_name

LOGGER = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# SSE helpers
# ---------------------------------------------------------------------------


def _sse_event(data: dict[str, Any]) -> str:
    """Encode a dict as an SSE ``data:`` line with trailing double newline."""
    return f"data: {json.dumps(data, default=str)}\n\n"


# ---------------------------------------------------------------------------
# Streaming formatter
# ---------------------------------------------------------------------------


async def stream_formatter_response(
    envelope: EngineEnvelope,
    session_context: dict[str, Any],
) -> AsyncGenerator[str, None]:
    """Stream the formatted response via SSE events.

    Uses full event handling to capture:
    - thinking blocks -> SSE "thinking" events (for collapsible reasoning panel)
    - text deltas    -> SSE "text" events (main content)
    - final message  -> stored in session_context["_stream_final_text"] for audit

    Falls back to non-streaming deterministic output if the Anthropic API key
    is unavailable or the streaming call fails.

    Yields
    ------
    str
        SSE-formatted event strings (``data: {...}\\n\\n``).

    Side Effects
    ------------
    After the generator is exhausted, ``session_context["_stream_final_text"]``
    contains the complete assembled response text for audit/session storage.
    ``session_context["formatter_model_used"]`` is set to the model used.
    """

    # ------------------------------------------------------------------
    # 1. Yield meta event immediately
    # ------------------------------------------------------------------
    yield _sse_event({
        "type": "meta",
        "engine_id": envelope.engine_id,
        "verdict": envelope.status.value,
        "mode": envelope.mode.value,
    })

    # ------------------------------------------------------------------
    # 2. REFUSE status — verbatim text, no Claude call
    # ------------------------------------------------------------------
    if envelope.status == Status.REFUSE:
        if session_context is not None:
            session_context["formatter_model_used"] = None
        yield _sse_event({"type": "text_start"})
        yield _sse_event({"type": "text", "content": envelope.response_text})
        yield _sse_event({"type": "text_end"})
        session_context["_stream_final_text"] = envelope.response_text
        # done event is yielded by the caller after audit_id is generated
        return

    # ------------------------------------------------------------------
    # 3. Attempt streaming Claude call
    # ------------------------------------------------------------------
    provider = resolve_provider_name(
        os.environ.get("MIRA_CHAT_LLM_PROVIDER", DEFAULT_FORMATTER_PROVIDER).strip()
        or DEFAULT_FORMATTER_PROVIDER
    )
    if provider != "anthropic":
        formatted = await format_response(envelope, session_context=session_context)
        session_context["_stream_final_text"] = formatted
        yield _sse_event({"type": "text_start"})
        yield _sse_event({"type": "text", "content": formatted})
        yield _sse_event({"type": "text_end"})
        return

    try:
        import anthropic

        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            LOGGER.warning("ANTHROPIC_API_KEY not set — streaming falls back to deterministic formatter")
            for event in _yield_fallback(envelope, session_context):
                yield event
            return

        model = (
            os.environ.get("MIRA_CHAT_FORMATTER_MODEL")
            or os.environ.get("BEDROCK_MODEL_ID")
            or os.environ.get("LLM_SONNET_MODEL")
            or resolve_model_for_provider(
                DEFAULT_FORMATTER_MODEL_TIER,
                provider_name=provider,
            )
        )
        session_context["formatter_model_used"] = model
        client = anthropic.AsyncAnthropic(api_key=api_key)

        system = build_formatter_system_prompt(envelope, session_context)
        user_prompt = build_formatter_prompt(envelope, session_context)

        # Open the streaming connection with full event handling.
        # adaptive thinking gives the model flexibility on reasoning depth.
        async with client.messages.stream(
            model=model,
            max_tokens=FORMATTER_MAX_TOKENS,
            temperature=FORMATTER_TEMPERATURE,
            system=system,
            messages=[{"role": "user", "content": user_prompt}],
            thinking={
                "type": "enabled",
                "budget_tokens": 1024,
            },
        ) as stream:

            # Track which block type we're inside for SSE event framing
            current_block_type: str | None = None

            async for event in stream:
                event_type = event.type

                # -- content_block_start --
                if event_type == "content_block_start":
                    block = event.content_block
                    if block.type == "thinking":
                        current_block_type = "thinking"
                        yield _sse_event({"type": "thinking_start"})
                    elif block.type == "text":
                        current_block_type = "text"
                        yield _sse_event({"type": "text_start"})
                    else:
                        current_block_type = None

                # -- content_block_delta --
                elif event_type == "content_block_delta":
                    delta = event.delta
                    if delta.type == "thinking_delta":
                        yield _sse_event({
                            "type": "thinking",
                            "content": delta.thinking,
                        })
                    elif delta.type == "text_delta":
                        yield _sse_event({
                            "type": "text",
                            "content": delta.text,
                        })

                # -- content_block_stop --
                elif event_type == "content_block_stop":
                    if current_block_type == "thinking":
                        yield _sse_event({"type": "thinking_end"})
                    elif current_block_type == "text":
                        yield _sse_event({"type": "text_end"})
                    current_block_type = None

            # ------------------------------------------------------------------
            # 4. Get the final assembled message for audit
            # ------------------------------------------------------------------
            final_message = stream.get_final_message()
            final_text = ""
            for block in final_message.content:
                if hasattr(block, "text"):
                    final_text += block.text

            session_context["_stream_final_text"] = final_text.strip()

    except Exception as exc:
        LOGGER.exception("Streaming formatter failed — falling back to deterministic output")
        yield _sse_event({
            "type": "error",
            "message": f"Formatter streaming error: {exc}",
        })
        # Fall back to the deterministic formatter so the user still gets an answer
        for event in _yield_fallback(envelope, session_context):
            yield event


# ---------------------------------------------------------------------------
# Fallback: yield the deterministic formatter output as a single text event
# ---------------------------------------------------------------------------


def _yield_fallback(
    envelope: EngineEnvelope,
    session_context: dict[str, Any],
) -> list[str]:
    """Return a list of SSE events wrapping the deterministic fallback text.

    Returns a plain list so the async caller can iterate with ``for event in``.
    (``yield from`` is not valid inside ``async def`` generators.)
    """
    session_context["formatter_model_used"] = None
    fallback_text = _fallback_format(envelope, session_context)
    session_context["_stream_final_text"] = fallback_text
    return [
        _sse_event({"type": "text_start"}),
        _sse_event({"type": "text", "content": fallback_text}),
        _sse_event({"type": "text_end"}),
    ]
