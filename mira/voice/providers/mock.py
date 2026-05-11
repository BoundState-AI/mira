"""Mock STT / TTS providers — used when real providers aren't configured.

Purpose:
  * Local dev without GPU / API keys can exercise the full WebSocket pipeline.
  * Demo dry runs can verify state machine + UI choreography end-to-end.

MockSTT returns a fixed transcript; MockTTS yields silent PCM-equivalent bytes
labeled as audio/mp3 so the client's MediaSource path is exercised.
"""

from __future__ import annotations

import asyncio
from typing import AsyncIterator

from .base import STTProvider, STTResult, TTSProvider


class MockSTT(STTProvider):
    @property
    def provider_id(self) -> str:
        return "mock"

    async def transcribe(self, pcm16_16k_mono: bytes) -> STTResult:
        await asyncio.sleep(0.1)
        sample_count = len(pcm16_16k_mono) // 2
        seconds = sample_count / 16000.0 if sample_count else 0.0
        text = (
            "Mock transcript: received "
            f"{sample_count} samples (~{seconds:.1f}s of audio)."
        )
        return STTResult(text=text, is_final=True, confidence=1.0)


class MockTTS(TTSProvider):
    """Emits ~50ms silent MP3-ish chunks sized to text length.

    Not real audio — only useful for wiring tests. Real TTS providers must be
    configured for actual playback.
    """

    @property
    def provider_id(self) -> str:
        return "mock"

    @property
    def audio_mime_type(self) -> str:
        return "audio/mpeg"

    async def synthesize(
        self,
        text: str,
        *,
        voice_id: str | None = None,
    ) -> AsyncIterator[bytes]:
        chunk_count = max(1, len(text) // 20)
        for _ in range(chunk_count):
            await asyncio.sleep(0.02)
            yield b"\x00" * 1024

    async def list_voices(self) -> list[dict[str, str]]:
        return [
            {"voice_id": "mock-narrator", "name": "Mock Narrator", "engine": "mock"},
        ]
