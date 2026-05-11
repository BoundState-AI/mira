"""MIRA Voice — two-way voice interface for the MIRA chat surface.

Demo-first implementation. See docs/VOICE_CHAT_PLAN.md for the architecture.

Components:
  * config           — environment-driven configuration
  * providers/       — STT / TTS provider abstractions (mock, whisper, polly, elevenlabs)
  * sentence_buffer  — split LLM text deltas into TTS-friendly clauses
  * session          — per-WebSocket session state machine
  * presence         — page-aware proactive greeting templates
  * ws_endpoint      — FastAPI WebSocket handler at /api/chat/voice
"""

from .config import VoiceConfig, get_voice_config

__all__ = ["VoiceConfig", "get_voice_config"]
