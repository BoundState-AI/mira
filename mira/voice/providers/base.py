"""Abstract base classes for voice providers.

Providers are deliberately narrow: STT takes a complete utterance, TTS takes a
text chunk and yields audio bytes. Sentence buffering, VAD orchestration, and
session state live above this layer.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import AsyncIterator


@dataclass(frozen=True)
class STTResult:
    text: str
    is_final: bool = True
    confidence: float | None = None


class STTProvider(ABC):
    @property
    @abstractmethod
    def provider_id(self) -> str: ...

    @abstractmethod
    async def transcribe(self, pcm16_16k_mono: bytes) -> STTResult:
        """Transcribe a complete utterance (16kHz mono Int16 PCM)."""


class TTSProvider(ABC):
    @property
    @abstractmethod
    def provider_id(self) -> str: ...

    @property
    @abstractmethod
    def audio_mime_type(self) -> str: ...

    @abstractmethod
    async def synthesize(
        self,
        text: str,
        *,
        voice_id: str | None = None,
    ) -> AsyncIterator[bytes]:
        """Yield audio chunks for *text*. Caller owns chunk concatenation/playback."""

    async def list_voices(self) -> list[dict[str, str]]:
        """Optional: enumerate available voices. Default: empty."""
        return []
