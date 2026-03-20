"""
Module: MIRA Chat -- Rate Limiter
Purpose: Per-session sliding window rate limiter for the MIRA Chat endpoint.

Per BS-SPEC-MIRA-CHAT-001-REV2 Section 13:
  - Per-session rate limit: 30 messages/minute
  - Max message length: 2000 characters
  - Bounded LLM calls per request: max 2 (one for query interpretation if
    needed, one for formatting)

Implementation: Simple in-memory sliding window rate limiter with per-session
tracking and automatic cleanup of stale sessions.

BoundState AI 2026
Classification: BoundState Proprietary

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: SWE-032 (Data validation)
Safety Critical: False
"""

from __future__ import annotations

import logging
import threading
import time
from collections import deque
from typing import Deque, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DEFAULT_MAX_REQUESTS_PER_MINUTE = 30
DEFAULT_MAX_MESSAGE_LENGTH = 2000
DEFAULT_MAX_LLM_CALLS_PER_REQUEST = 2
DEFAULT_WINDOW_SECONDS = 60.0

# Stale session cleanup: sessions with no activity for this long are evicted
_STALE_SESSION_SECONDS = 600.0  # 10 minutes
_MAX_TRACKED_SESSIONS = 2000


# ---------------------------------------------------------------------------
# Rate Limiter
# ---------------------------------------------------------------------------


class ChatRateLimiter:
    """
    Per-session sliding window rate limiter.

    Each session tracks a deque of request timestamps.  A request is allowed
    if the number of timestamps within the sliding window is below the limit.

    Thread-safe: uses a lock to protect the session map.

    Usage::

        limiter = ChatRateLimiter()

        # Before processing a request:
        allowed, reason = limiter.check(session_id)
        if not allowed:
            return error_response(reason)

        # Validate message length:
        length_ok, reason = limiter.check_message_length(message)
        if not length_ok:
            return error_response(reason)

        # After processing (or at check time if you prefer):
        limiter.record(session_id)
    """

    def __init__(
        self,
        *,
        max_requests_per_minute: int = DEFAULT_MAX_REQUESTS_PER_MINUTE,
        max_message_length: int = DEFAULT_MAX_MESSAGE_LENGTH,
        max_llm_calls_per_request: int = DEFAULT_MAX_LLM_CALLS_PER_REQUEST,
        window_seconds: float = DEFAULT_WINDOW_SECONDS,
    ):
        self._max_rpm = max_requests_per_minute
        self._max_message_length = max_message_length
        self._max_llm_calls = max_llm_calls_per_request
        self._window = window_seconds

        self._sessions: dict[str, Deque[float]] = {}
        self._lock = threading.Lock()

        logger.info(
            "[RATE_LIMITER] Initialized: max_rpm=%d, max_msg_len=%d, window=%.0fs",
            self._max_rpm, self._max_message_length, self._window,
        )

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def check(self, session_id: str) -> tuple[bool, Optional[str]]:
        """
        Check if a request from *session_id* is allowed.

        Returns
        -------
        (allowed, rejection_reason) : tuple[bool, str | None]
            ``allowed`` is True if the request may proceed.
            ``rejection_reason`` is None when allowed, or a human-readable
            string explaining why the request was rejected.
        """
        now = time.monotonic()

        with self._lock:
            self._maybe_cleanup(now)
            timestamps = self._sessions.get(session_id)

            if timestamps is None:
                # New session, always allowed
                return True, None

            # Prune timestamps outside the window
            cutoff = now - self._window
            while timestamps and timestamps[0] < cutoff:
                timestamps.popleft()

            count = len(timestamps)

            if count >= self._max_rpm:
                logger.warning(
                    "[RATE_LIMITER] Session %s exceeded rate limit: %d/%d in window",
                    session_id, count, self._max_rpm,
                )
                return False, (
                    f"Rate limit exceeded: {self._max_rpm} messages per minute. "
                    f"Please wait a moment before sending another message."
                )

            return True, None

    def record(self, session_id: str) -> None:
        """Record a request timestamp for *session_id*."""
        now = time.monotonic()
        with self._lock:
            if session_id not in self._sessions:
                self._sessions[session_id] = deque()
            self._sessions[session_id].append(now)

    def check_message_length(self, message: str) -> tuple[bool, Optional[str]]:
        """
        Check if a message is within the allowed length.

        Returns
        -------
        (allowed, rejection_reason) : tuple[bool, str | None]
        """
        if len(message) > self._max_message_length:
            return False, (
                f"Message too long: {len(message)} characters "
                f"(maximum {self._max_message_length}). "
                "Please shorten your message."
            )
        return True, None

    def check_and_record(self, session_id: str, message: str) -> tuple[bool, Optional[str]]:
        """
        Combined check: validate rate limit and message length, then record.

        This is the convenience method for the typical use case where you
        want to do all validation in one call.

        Returns
        -------
        (allowed, rejection_reason) : tuple[bool, str | None]
        """
        # Check message length first (cheaper)
        length_ok, reason = self.check_message_length(message)
        if not length_ok:
            return False, reason

        # Check rate limit
        allowed, reason = self.check(session_id)
        if not allowed:
            return False, reason

        # Record the request
        self.record(session_id)
        return True, None

    @property
    def max_llm_calls_per_request(self) -> int:
        """Return the max LLM calls allowed per request (for enforcement elsewhere)."""
        return self._max_llm_calls

    @property
    def max_message_length(self) -> int:
        """Return the max message length."""
        return self._max_message_length

    @property
    def max_requests_per_minute(self) -> int:
        """Return the max requests per minute."""
        return self._max_rpm

    # ------------------------------------------------------------------
    # Session management
    # ------------------------------------------------------------------

    def get_session_usage(self, session_id: str) -> dict[str, int | float]:
        """Return current usage stats for a session (for diagnostics)."""
        now = time.monotonic()
        with self._lock:
            timestamps = self._sessions.get(session_id)
            if timestamps is None:
                return {"requests_in_window": 0, "remaining": self._max_rpm}

            cutoff = now - self._window
            while timestamps and timestamps[0] < cutoff:
                timestamps.popleft()

            count = len(timestamps)
            return {
                "requests_in_window": count,
                "remaining": max(0, self._max_rpm - count),
                "window_seconds": self._window,
                "oldest_in_window": timestamps[0] if timestamps else 0,
            }

    def reset_session(self, session_id: str) -> None:
        """Clear rate limit state for a session."""
        with self._lock:
            self._sessions.pop(session_id, None)

    @property
    def active_sessions(self) -> int:
        """Return the number of currently tracked sessions."""
        with self._lock:
            return len(self._sessions)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _maybe_cleanup(self, now: float) -> None:
        """Evict stale sessions to prevent unbounded memory growth.

        Called inside the lock.
        """
        if len(self._sessions) < _MAX_TRACKED_SESSIONS:
            return

        cutoff = now - _STALE_SESSION_SECONDS
        stale_keys = [
            sid for sid, ts in self._sessions.items()
            if not ts or ts[-1] < cutoff
        ]
        for sid in stale_keys:
            del self._sessions[sid]

        if stale_keys:
            logger.info(
                "[RATE_LIMITER] Cleaned up %d stale session(s), %d remaining",
                len(stale_keys), len(self._sessions),
            )


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_default_limiter: Optional[ChatRateLimiter] = None


def get_rate_limiter() -> ChatRateLimiter:
    """Return the module-level singleton rate limiter."""
    global _default_limiter
    if _default_limiter is None:
        _default_limiter = ChatRateLimiter()
    return _default_limiter
