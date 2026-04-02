"""
Module: MIRA Core — Bedrock Concurrency Gate
Purpose: Shared semaphores that cap parallel Bedrock API calls across
         all MIRA runtime paths — provider-backed and direct callers.

Usage (async)::

    from mira.core.bedrock_semaphore import bedrock_limiter

    async with bedrock_limiter("sonnet"):
        response = client.messages.create(...)

Usage (sync — runs in thread pool or no event loop)::

    from mira.core.bedrock_semaphore import bedrock_limiter_sync

    with bedrock_limiter_sync("vision"):
        response = client.messages.create(...)

Environment variables:
    MIRA_BEDROCK_SONNET_CONCURRENCY   — max parallel Sonnet/text calls (default 6)
    MIRA_BEDROCK_VISION_CONCURRENCY   — max parallel vision/image calls (default 4)

BoundState AI 2026
Classification: BoundState Proprietary

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: SWE-013, SWE-032, NASA-STD-8739.8B
Safety Critical: False
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import threading
import time

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

_DEFAULT_SONNET_CONCURRENCY = 6
_DEFAULT_VISION_CONCURRENCY = 4

# ---------------------------------------------------------------------------
# Singleton limiters (created on first access)
# ---------------------------------------------------------------------------

_limiters: dict[str, threading.Semaphore] = {}
_init_lock = threading.Lock()


def _normalize_pool(model_class: str) -> str:
    """Map callers onto shared limiter pools."""
    return "vision" if model_class == "vision" else "sonnet"


def _get_cap(model_class: str) -> int:
    """Read the concurrency cap from env vars with defaults."""
    pool = _normalize_pool(model_class)
    if pool == "vision":
        raw = os.environ.get("MIRA_BEDROCK_VISION_CONCURRENCY", "").strip()
        return int(raw) if raw else _DEFAULT_VISION_CONCURRENCY
    raw = os.environ.get("MIRA_BEDROCK_SONNET_CONCURRENCY", "").strip()
    return int(raw) if raw else _DEFAULT_SONNET_CONCURRENCY


def _ensure_limiter(model_class: str) -> threading.Semaphore:
    """Get or create the shared semaphore for *model_class*."""
    pool = _normalize_pool(model_class)
    if pool not in _limiters:
        with _init_lock:
            if pool not in _limiters:
                cap = _get_cap(pool)
                _limiters[pool] = threading.Semaphore(cap)
                logger.info(
                    "[BEDROCK-GATE] Created limiter for %r with cap=%d",
                    pool, cap,
                )
    return _limiters[pool]


# ---------------------------------------------------------------------------
# Public API — async context manager
# ---------------------------------------------------------------------------


@contextlib.asynccontextmanager
async def bedrock_limiter(model_class: str = "sonnet"):
    """Async context manager that gates Bedrock calls.

    Parameters
    ----------
    model_class : str
        ``"sonnet"`` for text/Sonnet calls, ``"vision"`` for
        image/document-heavy calls.  Other values fall under
        the ``"sonnet"`` cap.

    Example::

        async with bedrock_limiter("vision"):
            response = await client.messages.create(...)
    """
    pool = _normalize_pool(model_class)
    sem = _ensure_limiter(pool)
    t0 = time.monotonic()
    logger.debug("[BEDROCK-GATE] Waiting for %r slot...", pool)
    await asyncio.to_thread(sem.acquire)
    wait_ms = (time.monotonic() - t0) * 1000
    if wait_ms > 50:
        logger.info(
            "[BEDROCK-GATE] Acquired %r slot after %.0fms wait",
            pool, wait_ms,
        )
    try:
        yield
    finally:
        sem.release()
        logger.debug("[BEDROCK-GATE] Released %r slot", pool)


# ---------------------------------------------------------------------------
# Public API — sync context manager
# ---------------------------------------------------------------------------


@contextlib.contextmanager
def bedrock_limiter_sync(model_class: str = "sonnet"):
    """Sync context manager that gates Bedrock calls.

    For use in synchronous code paths (e.g. thread-pool workers,
    sync provider ``complete()`` methods).

    Parameters
    ----------
    model_class : str
        ``"sonnet"`` for text calls, ``"vision"`` for image calls.

    Example::

        with bedrock_limiter_sync("sonnet"):
            response = client.converse(...)
    """
    pool = _normalize_pool(model_class)
    sem = _ensure_limiter(pool)
    t0 = time.monotonic()
    logger.debug("[BEDROCK-GATE] Waiting for sync %r slot...", pool)
    sem.acquire()
    wait_ms = (time.monotonic() - t0) * 1000
    if wait_ms > 50:
        logger.info(
            "[BEDROCK-GATE] Acquired sync %r slot after %.0fms wait",
            pool, wait_ms,
        )
    try:
        yield
    finally:
        sem.release()
        logger.debug("[BEDROCK-GATE] Released sync %r slot", pool)


# ---------------------------------------------------------------------------
# Testing helpers
# ---------------------------------------------------------------------------


def reset_limiters() -> None:
    """Clear all cached limiters.  For testing only."""
    with _init_lock:
        _limiters.clear()


def get_async_limiter(model_class: str) -> threading.Semaphore:
    """Expose the shared semaphore for async-path testing introspection."""
    return _ensure_limiter(model_class)


def get_sync_limiter(model_class: str) -> threading.Semaphore:
    """Expose the shared semaphore for sync-path testing introspection."""
    return _ensure_limiter(model_class)
