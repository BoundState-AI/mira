"""Per-WebSocket voice session: state machine + orchestration.

State transitions:

    IDLE
      └─ client.start            → READY
    READY / SPEAKING
      └─ client streams audio    → LISTENING (accumulating PCM)
    LISTENING
      └─ client.utterance_end    → THINKING (STT + chat pipeline)
    THINKING
      └─ first sentence flushed  → SPEAKING (TTS streaming)
    SPEAKING
      └─ tts done                → READY
      └─ client.interrupt        → READY  (barge-in, cancel TTS+chat)

The session keeps the existing chat pipeline as the source of truth for
multi-turn state — voice is purely transport. We call the in-process chat
streaming generator directly to avoid an HTTP hop.
"""

from __future__ import annotations

import asyncio
import base64
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, AsyncIterator, Awaitable, Callable
from uuid import uuid4

from .config import VoiceConfig
from .providers import STTProvider, TTSProvider
from .sentence_buffer import SentenceBuffer

LOGGER = logging.getLogger(__name__)


class SessionState(str, Enum):
    IDLE = "idle"
    READY = "ready"
    LISTENING = "listening"
    THINKING = "thinking"
    SPEAKING = "speaking"
    CLOSED = "closed"


ChatStreamFactory = Callable[
    [str, str, list[dict[str, Any]], dict[str, Any] | None],
    AsyncIterator[dict[str, Any]],
]
"""Factory that yields parsed chat stream events for a given user message.

Signature: ``(message, session_id, history, module_context) -> AsyncIterator[dict]``
"""


@dataclass
class _Turn:
    audio: bytearray = field(default_factory=bytearray)


class VoiceSession:
    def __init__(
        self,
        *,
        stt: STTProvider,
        tts: TTSProvider,
        chat_stream_factory: ChatStreamFactory,
        config: VoiceConfig,
        send_json: Callable[[dict[str, Any]], Awaitable[None]],
    ) -> None:
        self._stt = stt
        self._tts = tts
        self._chat_stream = chat_stream_factory
        self._config = config
        self._send = send_json

        self.state = SessionState.IDLE
        self.session_id: str = f"voice-{uuid4().hex[:8]}"
        self.chat_session_id: str | None = None
        self.voice_id: str | None = None
        self.module_context: dict[str, Any] | None = None
        self.history: list[dict[str, Any]] = []

        self._current_turn: _Turn | None = None
        self._active_task: asyncio.Task[None] | None = None
        self._closed = False

    @property
    def closed(self) -> bool:
        return self._closed

    # ----- public message dispatch -----

    async def handle_message(self, message: dict[str, Any]) -> None:
        msg_type = message.get("type")
        if msg_type == "start":
            await self._on_start(message)
        elif msg_type == "audio":
            await self._on_audio_chunk(message)
        elif msg_type == "utterance_end":
            await self._on_utterance_end()
        elif msg_type == "interrupt":
            await self._on_interrupt()
        elif msg_type == "end":
            await self.close()
        else:
            LOGGER.debug("voice: unknown message type %r", msg_type)

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._cancel_active_task()
        self.state = SessionState.CLOSED

    # ----- handlers -----

    async def _on_start(self, message: dict[str, Any]) -> None:
        voice_id = message.get("voice_id")
        if isinstance(voice_id, str) and voice_id.strip():
            self.voice_id = voice_id.strip()
        chat_session_id = message.get("chat_session_id") or message.get("session_id")
        if isinstance(chat_session_id, str) and chat_session_id.strip():
            self.chat_session_id = chat_session_id.strip()
        module_context = message.get("module_context")
        if isinstance(module_context, dict):
            self.module_context = module_context
        history = message.get("history")
        if isinstance(history, list):
            self.history = [item for item in history if isinstance(item, dict)]

        self.state = SessionState.READY
        await self._emit_state()
        await self._send(
            {
                "type": "ready",
                "session_id": self.session_id,
                "stt_provider": self._stt.provider_id,
                "tts_provider": self._tts.provider_id,
                "audio_mime": self._tts.audio_mime_type,
            }
        )

    async def _on_audio_chunk(self, message: dict[str, Any]) -> None:
        if self.state == SessionState.SPEAKING:
            return
        data = message.get("data")
        if not isinstance(data, str):
            return
        try:
            pcm = base64.b64decode(data, validate=False)
        except (ValueError, TypeError):
            return
        if self._current_turn is None:
            self._current_turn = _Turn()
            self.state = SessionState.LISTENING
            await self._emit_state()
        self._current_turn.audio.extend(pcm)

    async def _on_utterance_end(self) -> None:
        turn = self._current_turn
        self._current_turn = None
        if turn is None or not turn.audio:
            self.state = SessionState.READY
            await self._emit_state()
            return

        self.state = SessionState.THINKING
        await self._emit_state()

        self._cancel_active_task()
        self._active_task = asyncio.create_task(
            self._run_turn(bytes(turn.audio)),
            name=f"voice-turn-{self.session_id}",
        )

    async def _on_interrupt(self) -> None:
        self._cancel_active_task()
        self._current_turn = None
        self.state = SessionState.READY
        await self._emit_state()
        await self._send({"type": "interrupted"})

    # ----- turn execution -----

    async def _run_turn(self, audio: bytes) -> None:
        try:
            stt_result = await self._stt.transcribe(audio)
            text = (stt_result.text or "").strip()
            if not text:
                await self._send({"type": "transcript_empty"})
                self.state = SessionState.READY
                await self._emit_state()
                return

            await self._send(
                {
                    "type": "transcript_final",
                    "text": text,
                    "confidence": stt_result.confidence,
                }
            )

            buffer = SentenceBuffer(
                min_chars=self._config.sentence_flush_min_chars,
                max_chars=self._config.sentence_flush_max_chars,
            )
            assistant_text_parts: list[str] = []
            speaking_started = False
            assistant_engine: str | None = None
            assistant_verdict: str | None = None
            audit_id: str | None = None
            turn_entities: dict[str, Any] = {}
            follow_ups: list[str] = []

            chat_iter = self._chat_stream(
                text,
                self.chat_session_id or self.session_id,
                self.history,
                self.module_context,
            )

            async for event in chat_iter:
                etype = event.get("type")
                if etype == "meta":
                    if isinstance(event.get("engine_id"), str):
                        assistant_engine = event["engine_id"]
                    if isinstance(event.get("verdict"), str):
                        assistant_verdict = event["verdict"]
                    await self._send(
                        {
                            "type": "assistant_meta",
                            "engine_id": assistant_engine,
                            "verdict": assistant_verdict,
                        }
                    )
                elif etype == "text":
                    delta = event.get("content") or ""
                    if not isinstance(delta, str) or not delta:
                        continue
                    assistant_text_parts.append(delta)
                    await self._send({"type": "assistant_text", "delta": delta})
                    for clause in buffer.push(delta):
                        if not speaking_started:
                            speaking_started = True
                            self.state = SessionState.SPEAKING
                            await self._emit_state()
                        await self._stream_tts_clause(clause)
                elif etype == "done":
                    if isinstance(event.get("session_id"), str):
                        self.chat_session_id = event["session_id"]
                    if isinstance(event.get("audit_id"), str):
                        audit_id = event["audit_id"]
                    entities = event.get("entities")
                    if isinstance(entities, dict):
                        turn_entities = entities
                    fu = event.get("follow_ups")
                    if isinstance(fu, list):
                        follow_ups = [item for item in fu if isinstance(item, str)]

            for clause in buffer.finalize():
                if not speaking_started:
                    speaking_started = True
                    self.state = SessionState.SPEAKING
                    await self._emit_state()
                await self._stream_tts_clause(clause)

            assistant_full_text = "".join(assistant_text_parts).strip()

            if assistant_full_text:
                user_entry = {"role": "user", "content": text}
                assistant_entry: dict[str, Any] = {
                    "role": "assistant",
                    "content": assistant_full_text,
                }
                if assistant_engine:
                    assistant_entry["engine_used"] = assistant_engine
                if turn_entities:
                    assistant_entry["entities"] = turn_entities
                self.history.extend([user_entry, assistant_entry])
                if len(self.history) > 20:
                    self.history = self.history[-20:]

            await self._send(
                {
                    "type": "turn_done",
                    "audit_id": audit_id,
                    "session_id": self.chat_session_id,
                    "entities": turn_entities,
                    "follow_ups": follow_ups,
                }
            )
        except asyncio.CancelledError:
            await self._send({"type": "turn_cancelled"})
            raise
        except Exception as exc:
            LOGGER.exception("voice turn failed: %s", exc)
            await self._send({"type": "error", "detail": str(exc)})
        finally:
            if self.state != SessionState.CLOSED:
                self.state = SessionState.READY
                await self._emit_state()

    async def _stream_tts_clause(self, clause: str) -> None:
        text = clause.strip()
        if not text:
            return
        await self._send({"type": "audio_start", "text": text})
        async for chunk in self._tts.synthesize(text, voice_id=self.voice_id):
            if not chunk:
                continue
            await self._send(
                {"type": "audio", "data": base64.b64encode(chunk).decode("ascii")}
            )
        await self._send({"type": "audio_end"})

    # ----- helpers -----

    def _cancel_active_task(self) -> None:
        task = self._active_task
        self._active_task = None
        if task is not None and not task.done():
            task.cancel()

    async def _emit_state(self) -> None:
        await self._send({"type": "state", "state": self.state.value})
