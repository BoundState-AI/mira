"""Voice subsystem configuration — environment-driven.

Demo mode disables auto-shutoff timers, rate limits, and the worker pool so a
single demoer can sustain a long session without the production safeguards
getting in the way. Promotion to production is a flag flip plus the provider
swap (see docs/VOICE_CHAT_PLAN.md).
"""

from __future__ import annotations

import os
from dataclasses import dataclass


def _env_flag(name: str, default: bool = False) -> bool:
    raw = os.getenv(name, "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


@dataclass(frozen=True)
class VoiceConfig:
    enabled: bool
    demo_mode: bool

    stt_provider: str            # "whisper" | "mock"
    tts_provider: str            # "polly" | "elevenlabs" | "mock"

    max_concurrent_sessions: int

    # Whisper / SageMaker
    whisper_endpoint: str
    whisper_model: str

    # ElevenLabs
    elevenlabs_api_key: str
    elevenlabs_voice_id: str
    elevenlabs_model: str

    # Polly
    polly_voice_id: str
    polly_engine: str            # "generative" | "neural" | "long-form"
    aws_region: str

    # Demo behavior
    sentence_flush_min_chars: int
    sentence_flush_max_chars: int

    @property
    def has_real_stt(self) -> bool:
        return self.stt_provider != "mock" and bool(self.whisper_endpoint)

    @property
    def has_real_tts(self) -> bool:
        if self.tts_provider == "mock":
            return False
        if self.tts_provider == "elevenlabs":
            return bool(self.elevenlabs_api_key and self.elevenlabs_voice_id)
        if self.tts_provider == "polly":
            return bool(self.polly_voice_id)
        return False


_cached: VoiceConfig | None = None


def get_voice_config(*, refresh: bool = False) -> VoiceConfig:
    """Return the process-wide voice configuration (cached)."""
    global _cached
    if _cached is not None and not refresh:
        return _cached

    _cached = VoiceConfig(
        enabled=_env_flag("MIRA_VOICE_ENABLED", default=True),
        demo_mode=_env_flag("MIRA_VOICE_DEMO_MODE", default=True),
        stt_provider=os.getenv("MIRA_VOICE_STT_PROVIDER", "mock").strip().lower(),
        tts_provider=os.getenv("MIRA_VOICE_TTS_PROVIDER", "mock").strip().lower(),
        max_concurrent_sessions=_env_int("MIRA_VOICE_MAX_CONCURRENT", 10),
        whisper_endpoint=os.getenv("MIRA_VOICE_WHISPER_ENDPOINT", "").strip(),
        whisper_model=os.getenv("MIRA_VOICE_WHISPER_MODEL", "large-v3").strip(),
        elevenlabs_api_key=os.getenv("MIRA_VOICE_ELEVENLABS_API_KEY", "").strip(),
        elevenlabs_voice_id=os.getenv("MIRA_VOICE_ELEVENLABS_VOICE_ID", "").strip(),
        elevenlabs_model=os.getenv("MIRA_VOICE_ELEVENLABS_MODEL", "eleven_flash_v2_5").strip(),
        polly_voice_id=os.getenv("MIRA_VOICE_POLLY_VOICE_ID", "Ruth").strip(),
        polly_engine=os.getenv("MIRA_VOICE_POLLY_ENGINE", "generative").strip(),
        aws_region=os.getenv("AWS_REGION", "us-gov-west-1").strip(),
        sentence_flush_min_chars=_env_int("MIRA_VOICE_FLUSH_MIN_CHARS", 40),
        sentence_flush_max_chars=_env_int("MIRA_VOICE_FLUSH_MAX_CHARS", 120),
    )
    return _cached
