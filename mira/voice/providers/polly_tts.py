"""AWS Polly streaming TTS provider — GovCloud-native production path."""

from __future__ import annotations

import asyncio
import logging
from typing import AsyncIterator

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from .base import TTSProvider

LOGGER = logging.getLogger(__name__)


class PollyTTS(TTSProvider):
    def __init__(
        self,
        default_voice_id: str,
        engine: str = "generative",
        region: str = "us-gov-west-1",
    ) -> None:
        if not default_voice_id:
            raise ValueError("PollyTTS requires default_voice_id")
        self._default_voice = default_voice_id
        self._engine = engine
        self._region = region
        self._client = boto3.client("polly", region_name=region)

    @property
    def provider_id(self) -> str:
        return f"polly:{self._engine}"

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

        def _invoke() -> bytes:
            response = self._client.synthesize_speech(
                Text=text,
                OutputFormat="mp3",
                VoiceId=voice,
                Engine=self._engine,
            )
            return response["AudioStream"].read()

        try:
            audio = await asyncio.to_thread(_invoke)
        except (BotoCoreError, ClientError) as exc:
            LOGGER.exception("Polly synthesize_speech failed: %s", exc)
            return

        chunk_size = 8192
        for offset in range(0, len(audio), chunk_size):
            yield audio[offset : offset + chunk_size]

    async def list_voices(self) -> list[dict[str, str]]:
        def _describe() -> list[dict]:
            voices: list[dict] = []
            paginator = self._client.get_paginator("describe_voices")
            for page in paginator.paginate(Engine=self._engine):
                voices.extend(page.get("Voices", []))
            return voices

        try:
            entries = await asyncio.to_thread(_describe)
        except (BotoCoreError, ClientError) as exc:
            LOGGER.warning("Polly describe_voices failed: %s", exc)
            return []

        return [
            {
                "voice_id": str(item.get("Id", "")),
                "name": str(item.get("Name", "")),
                "engine": self._engine,
                "language": str(item.get("LanguageCode", "")),
                "gender": str(item.get("Gender", "")),
            }
            for item in entries
        ]
