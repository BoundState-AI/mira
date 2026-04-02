#!/usr/bin/env python3
"""
Lightweight global API rate limiting middleware.

This is intentionally process-local so it can harden single-instance and test
deployments without adding external infrastructure requirements. In production,
it should be paired with edge/WAF throttling for fleet-wide enforcement.
"""

from __future__ import annotations

import os
import hashlib
import threading
import time
from collections import deque
from typing import Deque

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware


def _env_flag(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def rate_limit_enabled() -> bool:
    default = os.getenv("MIRA_ENV", "development").strip().lower() == "production"
    return _env_flag("MIRA_RATE_LIMIT_ENABLED", default)


def rate_limit_requests() -> int:
    raw = os.getenv("MIRA_RATE_LIMIT_REQUESTS", "").strip()
    if not raw:
        return 240
    try:
        return max(1, int(raw))
    except ValueError:
        return 240


def rate_limit_window_seconds() -> float:
    raw = os.getenv("MIRA_RATE_LIMIT_WINDOW_SECONDS", "").strip()
    if not raw:
        return 60.0
    try:
        return max(1.0, float(raw))
    except ValueError:
        return 60.0


def _rate_limit_key(request: Request) -> str:
    user = getattr(request.state, "user", None)
    if user is not None and getattr(user, "sub", ""):
        return f"user:{user.sub}"

    auth_header = request.headers.get("Authorization", "").strip()
    if auth_header.lower().startswith("bearer "):
        token = auth_header[7:].strip()
        if token:
            token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()[:16]
            return f"token:{token_hash}"

    forwarded = request.headers.get("X-Forwarded-For", "")
    ip = forwarded.split(",")[0].strip() if forwarded else ""
    if not ip and request.client and request.client.host:
        ip = request.client.host
    return f"ip:{ip or 'unknown'}"


class GlobalRateLimiter:
    """Sliding-window rate limiter keyed by user-or-IP."""

    def __init__(self, *, max_requests: int, window_seconds: float):
        self._max_requests = max_requests
        self._window_seconds = window_seconds
        self._entries: dict[str, Deque[float]] = {}
        self._lock = threading.Lock()

    def check(self, key: str) -> tuple[bool, int, int]:
        now = time.monotonic()
        with self._lock:
            timestamps = self._entries.setdefault(key, deque())
            cutoff = now - self._window_seconds
            while timestamps and timestamps[0] < cutoff:
                timestamps.popleft()

            if len(timestamps) >= self._max_requests:
                retry_after = max(1, int(self._window_seconds - (now - timestamps[0])))
                return False, 0, retry_after

            timestamps.append(now)
            remaining = max(0, self._max_requests - len(timestamps))
            return True, remaining, 0


class ApiRateLimitMiddleware(BaseHTTPMiddleware):
    """Apply a process-local rate limit across API routes."""

    def __init__(self, app, *, max_requests: int, window_seconds: float):
        super().__init__(app)
        self._limiter = GlobalRateLimiter(
            max_requests=max_requests,
            window_seconds=window_seconds,
        )
        self._limit = max_requests

    async def dispatch(self, request: Request, call_next):
        if request.method == "OPTIONS":
            return await call_next(request)

        path = request.url.path
        if path in {"/health", "/api/health", "/favicon.ico"}:
            return await call_next(request)
        if path.endswith("/ping"):
            return await call_next(request)
        if path.startswith("/docs") or path.startswith("/redoc") or path.startswith("/openapi.json"):
            return await call_next(request)

        key = _rate_limit_key(request)
        allowed, remaining, retry_after = self._limiter.check(key)
        if not allowed:
            return JSONResponse(
                status_code=429,
                content={"detail": "Rate limit exceeded. Please wait before retrying."},
                headers={
                    "Retry-After": str(retry_after),
                    "X-RateLimit-Limit": str(self._limit),
                    "X-RateLimit-Remaining": "0",
                },
            )

        response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(self._limit)
        response.headers["X-RateLimit-Remaining"] = str(remaining)
        return response
