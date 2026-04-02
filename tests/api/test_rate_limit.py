"""
Tests for API rate limiting middleware.

Covers:
  - Limiter can be enabled/disabled via env
  - Requests over the limit get 429
  - Disabled mode does not rate-limit
  - Health and ping routes are exempt
  - Rate limit headers are present on responses

BoundState AI 2026
Classification: BoundState Proprietary
"""

from __future__ import annotations

import os

import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from starlette.middleware.base import BaseHTTPMiddleware

from mira.api.rate_limit import (
    ApiRateLimitMiddleware,
    GlobalRateLimiter,
    _rate_limit_key,
    rate_limit_enabled,
    rate_limit_requests,
    rate_limit_window_seconds,
)


# ---------------------------------------------------------------------------
# GlobalRateLimiter unit tests
# ---------------------------------------------------------------------------


class TestGlobalRateLimiter:
    def test_allows_under_limit(self):
        limiter = GlobalRateLimiter(max_requests=5, window_seconds=60)
        for _ in range(5):
            allowed, remaining, _ = limiter.check("user:test")
            assert allowed

    def test_blocks_over_limit(self):
        limiter = GlobalRateLimiter(max_requests=3, window_seconds=60)
        for _ in range(3):
            limiter.check("user:test")

        allowed, remaining, retry_after = limiter.check("user:test")
        assert not allowed
        assert remaining == 0
        assert retry_after >= 1

    def test_separate_keys_independent(self):
        limiter = GlobalRateLimiter(max_requests=2, window_seconds=60)
        limiter.check("user:alice")
        limiter.check("user:alice")

        # Alice is at limit, but bob should still be fine
        allowed_alice, _, _ = limiter.check("user:alice")
        assert not allowed_alice

        allowed_bob, _, _ = limiter.check("user:bob")
        assert allowed_bob

    def test_remaining_decreases(self):
        limiter = GlobalRateLimiter(max_requests=5, window_seconds=60)
        _, remaining, _ = limiter.check("user:test")
        assert remaining == 4

        _, remaining, _ = limiter.check("user:test")
        assert remaining == 3


# ---------------------------------------------------------------------------
# Env var config tests
# ---------------------------------------------------------------------------


class TestEnvConfig:
    def setup_method(self):
        for var in ("MIRA_RATE_LIMIT_ENABLED", "MIRA_RATE_LIMIT_REQUESTS",
                     "MIRA_RATE_LIMIT_WINDOW_SECONDS", "MIRA_ENV"):
            os.environ.pop(var, None)

    def teardown_method(self):
        for var in ("MIRA_RATE_LIMIT_ENABLED", "MIRA_RATE_LIMIT_REQUESTS",
                     "MIRA_RATE_LIMIT_WINDOW_SECONDS", "MIRA_ENV"):
            os.environ.pop(var, None)

    def test_enabled_in_production_by_default(self):
        os.environ["MIRA_ENV"] = "production"
        assert rate_limit_enabled() is True

    def test_disabled_in_development_by_default(self):
        os.environ["MIRA_ENV"] = "development"
        assert rate_limit_enabled() is False

    def test_explicit_enable(self):
        os.environ["MIRA_ENV"] = "development"
        os.environ["MIRA_RATE_LIMIT_ENABLED"] = "true"
        assert rate_limit_enabled() is True

    def test_explicit_disable(self):
        os.environ["MIRA_ENV"] = "production"
        os.environ["MIRA_RATE_LIMIT_ENABLED"] = "false"
        assert rate_limit_enabled() is False

    def test_requests_default(self):
        assert rate_limit_requests() == 240

    def test_requests_override(self):
        os.environ["MIRA_RATE_LIMIT_REQUESTS"] = "40"
        assert rate_limit_requests() == 40

    def test_window_default(self):
        assert rate_limit_window_seconds() == 60.0

    def test_window_override(self):
        os.environ["MIRA_RATE_LIMIT_WINDOW_SECONDS"] = "30"
        assert rate_limit_window_seconds() == 30.0


class TestRateLimitKey:
    def test_prefers_authenticated_user(self):
        class User:
            sub = "abc123"

        request = type(
            "RequestStub",
            (),
            {
                "state": type("State", (), {"user": User()})(),
                "headers": {},
                "client": None,
            },
        )()

        assert _rate_limit_key(request) == "user:abc123"

    def test_uses_hashed_bearer_token_before_ip(self):
        request = type(
            "RequestStub",
            (),
            {
                "state": type("State", (), {})(),
                "headers": {
                    "Authorization": "Bearer secret-token",
                    "X-Forwarded-For": "203.0.113.10",
                },
                "client": None,
            },
        )()

        key = _rate_limit_key(request)
        assert key.startswith("token:")
        assert "secret-token" not in key


# ---------------------------------------------------------------------------
# Middleware integration tests
# ---------------------------------------------------------------------------


def _make_app(max_requests: int = 3, window_seconds: float = 60) -> TestClient:
    """Create a minimal FastAPI app with the rate limiter enabled."""
    app = FastAPI()

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    @app.get("/api/chat/ping")
    async def ping():
        return {"status": "ok"}

    @app.get("/api/test")
    async def test_endpoint():
        return {"result": "ok"}

    app.add_middleware(
        ApiRateLimitMiddleware,
        max_requests=max_requests,
        window_seconds=window_seconds,
    )

    return TestClient(app)


def _make_auth_then_rate_limit_app(max_requests: int = 3) -> TestClient:
    app = FastAPI()

    class DummyAuthMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request, call_next):
            auth = request.headers.get("Authorization", "")
            if auth == "Bearer good-token":
                request.state.user = type("User", (), {"sub": "user-123"})()
                return await call_next(request)
            return JSONResponse(status_code=401, content={"detail": "Missing Bearer token"})

    @app.get("/api/protected")
    async def protected():
        return {"result": "ok"}

    app.add_middleware(DummyAuthMiddleware)
    app.add_middleware(ApiRateLimitMiddleware, max_requests=max_requests, window_seconds=60)
    return TestClient(app)


class TestMiddleware:
    def test_returns_429_over_limit(self):
        client = _make_app(max_requests=2)

        # Two allowed
        assert client.get("/api/test").status_code == 200
        assert client.get("/api/test").status_code == 200

        # Third blocked
        resp = client.get("/api/test")
        assert resp.status_code == 429
        assert "Rate limit exceeded" in resp.json()["detail"]
        assert "Retry-After" in resp.headers

    def test_rate_limit_headers_present(self):
        client = _make_app(max_requests=10)
        resp = client.get("/api/test")
        assert resp.status_code == 200
        assert "X-RateLimit-Limit" in resp.headers
        assert "X-RateLimit-Remaining" in resp.headers
        assert resp.headers["X-RateLimit-Limit"] == "10"

    def test_health_exempt(self):
        client = _make_app(max_requests=1)

        # Use up the limit
        assert client.get("/api/test").status_code == 200
        assert client.get("/api/test").status_code == 429

        # Health should still work
        assert client.get("/health").status_code == 200

    def test_ping_exempt(self):
        client = _make_app(max_requests=1)

        # Use up the limit
        assert client.get("/api/test").status_code == 200
        assert client.get("/api/test").status_code == 429

        # Ping should still work
        assert client.get("/api/chat/ping").status_code == 200

    def test_disabled_does_not_limit(self):
        """When middleware is not added, no rate limiting occurs."""
        app = FastAPI()

        @app.get("/api/test")
        async def test_endpoint():
            return {"result": "ok"}

        client = TestClient(app)

        # Should never 429
        for _ in range(50):
            assert client.get("/api/test").status_code == 200

    def test_protected_route_is_rate_limited_before_auth_rejection(self):
        client = _make_auth_then_rate_limit_app(max_requests=2)

        assert client.get("/api/protected").status_code == 401
        assert client.get("/api/protected").status_code == 401

        resp = client.get("/api/protected")
        assert resp.status_code == 429
        assert resp.headers["X-RateLimit-Remaining"] == "0"

    def test_distinct_bearer_tokens_get_distinct_buckets(self):
        client = _make_auth_then_rate_limit_app(max_requests=1)

        assert client.get("/api/protected", headers={"Authorization": "Bearer token-a"}).status_code == 401
        assert client.get("/api/protected", headers={"Authorization": "Bearer token-b"}).status_code == 401
