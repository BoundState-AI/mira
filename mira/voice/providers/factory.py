"""Build the active STT / TTS providers from VoiceConfig.

Each builder returns the requested provider when fully configured, or falls
back to the mock provider with a logged warning so the WebSocket pipeline
still exercises end-to-end during dev / dry runs.
"""

from __future__ import annotations

import logging
from functools import lru_cache

from ..config import VoiceConfig
from .base import STTProvider, TTSProvider
from .mock import MockSTT, MockTTS

LOGGER = logging.getLogger(__name__)


# Providers are stateless wrappers around thread-safe clients (boto3 / httpx),
# so one instance per config serves every session and request. Caching avoids
# rebuilding boto3 clients (credential resolution, endpoint discovery) on each
# WebSocket connection. VoiceConfig is a frozen dataclass, hence hashable.
@lru_cache(maxsize=4)
def build_stt_provider(config: VoiceConfig) -> STTProvider:
    provider = (config.stt_provider or "mock").lower()

    if provider == "whisper":
        if not config.whisper_endpoint:
            LOGGER.warning(
                "STT provider=whisper but MIRA_VOICE_WHISPER_ENDPOINT is unset; using mock."
            )
            return MockSTT()
        from .whisper_sagemaker import WhisperSageMakerSTT
        return WhisperSageMakerSTT(
            endpoint_name=config.whisper_endpoint,
            region=config.aws_region,
        )

    if provider != "mock":
        LOGGER.warning("Unknown STT provider %r; using mock.", provider)
    return MockSTT()


@lru_cache(maxsize=4)
def build_tts_provider(config: VoiceConfig) -> TTSProvider:
    provider = (config.tts_provider or "mock").lower()

    if provider == "elevenlabs":
        if not (config.elevenlabs_api_key and config.elevenlabs_voice_id):
            LOGGER.warning(
                "TTS provider=elevenlabs but API key or voice_id missing; using mock."
            )
            return MockTTS()
        from .elevenlabs_tts import ElevenLabsTTS
        return ElevenLabsTTS(
            api_key=config.elevenlabs_api_key,
            default_voice_id=config.elevenlabs_voice_id,
            model=config.elevenlabs_model,
        )

    if provider == "polly":
        if not config.polly_voice_id:
            LOGGER.warning("TTS provider=polly but voice_id missing; using mock.")
            return MockTTS()
        from .polly_tts import PollyTTS
        return PollyTTS(
            default_voice_id=config.polly_voice_id,
            engine=config.polly_engine,
            region=config.aws_region,
        )

    if provider != "mock":
        LOGGER.warning("Unknown TTS provider %r; using mock.", provider)
    return MockTTS()
