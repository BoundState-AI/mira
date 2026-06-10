"""ElevenLabs streaming TTS provider — demo voice choice."""

from __future__ import annotations

import logging
from typing import AsyncIterator

import httpx

from .base import TTSProvider

LOGGER = logging.getLogger(__name__)

_BASE_URL = "https://api.elevenlabs.io/v1"


class ElevenLabsTTS(TTSProvider):
    def __init__(
        self,
        api_key: str,
        default_voice_id: str,
        model: str = "eleven_flash_v2_5",
    ) -> None:
        if not api_key:
            raise ValueError("ElevenLabsTTS requires api_key")
        if not default_voice_id:
            raise ValueError("ElevenLabsTTS requires default_voice_id")
        self._api_key = api_key
        self._default_voice = default_voice_id
        self._model = model

    @property
    def provider_id(self) -> str:
        return f"elevenlabs:{self._model}"

    @property
    def audio_mime_type(self) -> str:
        return "audio/mpeg"

    async def synthesize(
        self,
        text: str,
        *,
        voice_id: str | None = None,
    ) -> AsyncIterator[bytes]:
        voice = voice_id or self._default_voice
        url = f"{_BASE_URL}/text-to-speech/{voice}/stream"
        headers = {
            "xi-api-key": self._api_key,
            "Accept": "audio/mpeg",
            "Content-Type": "application/json",
            # Opt out of input retention on plans that honor it; harmless
            # on plans that don't. Demo TTS never trains a future model.
            "xi-no-retention": "true",
        }
        body = {
            "text": text,
            "model_id": self._model,
            "voice_settings": {
                "stability": 0.45,
                "similarity_boost": 0.75,
                "use_speaker_boost": True,
            },
        }
        params = {"output_format": "mp3_44100_128"}

        async with httpx.AsyncClient(timeout=httpx.Timeout(30.0, read=60.0)) as client:
            async with client.stream(
                "POST", url, headers=headers, params=params, json=body
            ) as response:
                if response.status_code != 200:
                    detail = await response.aread()
                    LOGGER.warning(
                        "ElevenLabs TTS error %s: %s", response.status_code, detail[:200]
                    )
                    return
                async for chunk in response.aiter_bytes():
                    if chunk:
                        yield chunk

    async def list_voices(self) -> list[dict[str, str]]:
        url = f"{_BASE_URL}/voices"
        headers = {"xi-api-key": self._api_key}
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(url, headers=headers)
            if response.status_code != 200:
                LOGGER.warning("ElevenLabs list_voices error: %s", response.status_code)
                return []
            data = response.json()
        voices = []
        for entry in data.get("voices", []):
            voices.append(
                {
                    "voice_id": str(entry.get("voice_id", "")),
                    "name": str(entry.get("name", "")),
                    "engine": "elevenlabs",
                }
            )
        return voices
