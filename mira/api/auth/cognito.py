#!/usr/bin/env python3
"""
Cognito authentication and authorization middleware for MIRA.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any, Optional

import httpx
from cachetools import TTLCache
from fastapi import Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from starlette.middleware.base import BaseHTTPMiddleware

from .audit import log_auth_event, log_itar_access

LOGGER = logging.getLogger("mira.auth")

security = HTTPBearer(auto_error=False)
_jwks_cache: TTLCache = TTLCache(maxsize=2, ttl=3600)


def auth_enabled() -> bool:
    return os.getenv("MIRA_AUTH_MODE", "cognito").strip().lower() == "cognito"


def _parse_prefixes(env_name: str, default: tuple[str, ...]) -> tuple[str, ...]:
    raw = os.getenv(env_name)
    if not raw:
        return default
    prefixes = []
    for item in raw.split(","):
        cleaned = item.strip()
        if not cleaned:
            continue
        if not cleaned.startswith("/"):
            cleaned = f"/{cleaned}"
        prefixes.append(cleaned.rstrip("/"))
    return tuple(prefixes)


PUBLIC_EXACT_PATHS = {
    "/health",
    "/openapi.json",
    "/favicon.ico",
}
PUBLIC_PREFIX_PATHS = (
    "/docs",
    "/redoc",
)

ITAR_PATH_PREFIXES = _parse_prefixes("ITAR_PATH_PREFIXES", ("/miul", "/bom"))
ADMIN_PATH_PREFIXES = _parse_prefixes("ADMIN_PATH_PREFIXES", ())


def _candidate_paths(path: str) -> tuple[str, ...]:
    normalized = path.rstrip("/") if path != "/" else path
    if normalized.startswith("/api/"):
        return normalized, normalized[4:]
    return (normalized,)


def is_public_path(path: str) -> bool:
    for candidate in _candidate_paths(path):
        if candidate in PUBLIC_EXACT_PATHS:
            return True
        if any(candidate.startswith(prefix) for prefix in PUBLIC_PREFIX_PATHS):
            return True
    return False


def requires_itar(path: str) -> bool:
    for candidate in _candidate_paths(path):
        if any(candidate.startswith(prefix) for prefix in ITAR_PATH_PREFIXES):
            return True
    return False


def requires_admin(path: str) -> bool:
    for candidate in _candidate_paths(path):
        if any(candidate.startswith(prefix) for prefix in ADMIN_PATH_PREFIXES):
            return True
    return False


def _get_cognito_config() -> dict[str, str]:
    region = os.getenv("COGNITO_REGION", "us-gov-west-1").strip()
    user_pool_id = (os.getenv("COGNITO_USER_POOL_ID") or "").strip()
    client_id = (os.getenv("COGNITO_CLIENT_ID") or "").strip()

    if not region:
        raise RuntimeError("COGNITO_REGION is required")
    if not user_pool_id:
        raise RuntimeError("COGNITO_USER_POOL_ID is required")
    if not client_id:
        raise RuntimeError("COGNITO_CLIENT_ID is required")

    issuer = f"https://cognito-idp.{region}.amazonaws.com/{user_pool_id}"
    return {
        "region": region,
        "user_pool_id": user_pool_id,
        "client_id": client_id,
        "issuer": issuer,
        "jwks_url": f"{issuer}/.well-known/jwks.json",
    }


def validate_auth_configuration() -> None:
    if not auth_enabled():
        LOGGER.warning("MIRA auth mode is disabled; API is running without Cognito enforcement.")
        return
    _get_cognito_config()
    LOGGER.info("Cognito auth enforcement enabled for MIRA API.")


async def _get_jwks(jwks_url: str) -> list[dict[str, Any]]:
    cached = _jwks_cache.get(jwks_url)
    if cached is not None:
        return cached
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.get(jwks_url)
        response.raise_for_status()
        keys = response.json().get("keys", [])
    if not keys:
        raise JWTError("JWKS key set is empty")
    _jwks_cache[jwks_url] = keys
    return keys


def _find_jwk_for_token(token: str, keys: list[dict[str, Any]]) -> dict[str, Any]:
    headers = jwt.get_unverified_headers(token)
    token_kid = headers.get("kid")
    if not token_kid:
        raise JWTError("JWT missing kid header")
    for key in keys:
        if key.get("kid") == token_kid:
            return key
    raise JWTError(f"No matching JWKS key for kid={token_kid}")


def _normalize_groups(raw_groups: Any) -> tuple[str, ...]:
    if raw_groups is None:
        return ()
    if isinstance(raw_groups, str):
        return (raw_groups,)
    if isinstance(raw_groups, list):
        return tuple(str(item) for item in raw_groups)
    return ()


@dataclass(slots=True)
class MIRAUser:
    sub: str
    username: str
    email: str
    groups: tuple[str, ...]
    role: str
    itar_access: str
    us_person_verified: Optional[bool]

    @classmethod
    def from_claims(cls, claims: dict[str, Any]) -> "MIRAUser":
        us_person_raw = claims.get("custom:us_person_verified")
        us_person_verified: Optional[bool]
        if us_person_raw is None:
            us_person_verified = None
        else:
            us_person_verified = str(us_person_raw).strip().lower() == "true"

        return cls(
            sub=str(claims.get("sub") or ""),
            username=str(
                claims.get("cognito:username")
                or claims.get("username")
                or claims.get("email")
                or ""
            ),
            email=str(claims.get("email") or ""),
            groups=_normalize_groups(claims.get("cognito:groups")),
            role=str(claims.get("custom:role") or ""),
            itar_access=str(claims.get("custom:itar_access") or ""),
            us_person_verified=us_person_verified,
        )

    @property
    def is_admin(self) -> bool:
        return "mira-admin" in self.groups

    @property
    def is_itar_cleared(self) -> bool:
        if "mira-itar" not in self.groups:
            return False
        if self.us_person_verified is False:
            return False
        if self.itar_access and self.itar_access not in {"full", "read"}:
            return False
        return True


def _request_ip(request: Request) -> str:
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    if request.client and request.client.host:
        return request.client.host
    return "unknown"


def _extract_bearer_token(authorization_header: str | None) -> str | None:
    if not authorization_header:
        return None
    scheme, _, token = authorization_header.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        return None
    return token.strip()


async def verify_token_string(token: str) -> dict[str, Any]:
    config = _get_cognito_config()
    keys = await _get_jwks(config["jwks_url"])
    key = _find_jwk_for_token(token, keys)

    try:
        claims = jwt.decode(
            token,
            key,
            algorithms=["RS256"],
            issuer=config["issuer"],
            options={"verify_aud": False, "verify_at_hash": False},
        )
    except JWTError as exc:
        raise HTTPException(status_code=401, detail="Invalid or expired token") from exc

    token_use = claims.get("token_use")
    if token_use != "access":
        raise HTTPException(status_code=401, detail="Access token required")

    client_id = claims.get("client_id")
    if client_id != config["client_id"]:
        raise HTTPException(status_code=401, detail="Token audience mismatch")

    return claims


async def verify_token(
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
) -> dict[str, Any]:
    if not auth_enabled():
        raise HTTPException(status_code=503, detail="Authentication mode disabled")
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(status_code=401, detail="Missing Bearer token")
    return await verify_token_string(credentials.credentials)


async def get_current_user(
    request: Request,
    claims: dict[str, Any] = Depends(verify_token),
) -> MIRAUser:
    cached_user = getattr(request.state, "user", None)
    if cached_user:
        return cached_user
    user = MIRAUser.from_claims(claims)
    request.state.user = user
    return user


async def require_itar_user(user: MIRAUser = Depends(get_current_user)) -> MIRAUser:
    if not user.is_itar_cleared:
        raise HTTPException(
            status_code=403,
            detail="ITAR-controlled content requires verified U.S. person ITAR access",
        )
    return user


async def require_admin_user(user: MIRAUser = Depends(get_current_user)) -> MIRAUser:
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    return user


def get_request_user(request: Request) -> MIRAUser | None:
    """Return the authenticated user attached by middleware, if present."""
    user = getattr(request.state, "user", None)
    return user if isinstance(user, MIRAUser) else None


def authorize_owner_or_admin(
    request: Request,
    owner_username: str | None,
    *,
    resource_label: str = "resource",
) -> MIRAUser | None:
    """Allow access for the recorded owner or any admin.

    When authentication is disabled (local/dev/test), this is a no-op.
    Legacy ownerless resources require admin when auth is enabled.
    """
    user = get_request_user(request)
    if user is None:
        return None
    if user.is_admin:
        return user

    actor = (user.username or user.email or "").strip().lower()
    owner = (owner_username or "").strip().lower()

    if owner and actor and actor == owner:
        return user

    if not owner:
        raise HTTPException(
            status_code=403,
            detail=f"{resource_label.capitalize()} ownership is unavailable; admin access required",
        )

    raise HTTPException(
        status_code=403,
        detail=f"Owner or admin access required for this {resource_label}",
    )


class CognitoAuthzMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.method == "OPTIONS":
            return await call_next(request)

        path = request.url.path
        if is_public_path(path):
            return await call_next(request)

        if not auth_enabled():
            return await call_next(request)

        ip_address = _request_ip(request)
        token = _extract_bearer_token(request.headers.get("Authorization"))
        if token is None:
            log_auth_event(
                event_type="AUTH_FAILURE",
                username="unknown",
                success=False,
                ip_address=ip_address,
                details={"path": path, "reason": "missing_bearer"},
            )
            return JSONResponse(status_code=401, content={"detail": "Missing Bearer token"})

        try:
            claims = await verify_token_string(token)
            user = MIRAUser.from_claims(claims)
            request.state.user = user
        except HTTPException as exc:
            log_auth_event(
                event_type="AUTH_FAILURE",
                username="unknown",
                success=False,
                ip_address=ip_address,
                details={"path": path, "reason": "invalid_token", "status": exc.status_code},
            )
            return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})
        except Exception as exc:  # pragma: no cover
            LOGGER.error("Unexpected auth middleware failure: %s", exc)
            log_auth_event(
                event_type="AUTH_FAILURE",
                username="unknown",
                success=False,
                ip_address=ip_address,
                details={"path": path, "reason": "middleware_exception"},
            )
            return JSONResponse(status_code=401, content={"detail": "Authentication failed"})

        if requires_admin(path) and not user.is_admin:
            log_auth_event(
                event_type="AUTH_FAILURE",
                username=user.username or "unknown",
                success=False,
                ip_address=ip_address,
                details={"path": path, "reason": "admin_required", "status": 403},
            )
            return JSONResponse(status_code=403, content={"detail": "Admin access required"})

        if requires_itar(path):
            if not user.is_itar_cleared:
                log_itar_access(
                    username=user.username or "unknown",
                    action="ACCESS",
                    resource_type="API_PATH",
                    resource_id=path,
                    granted=False,
                    details={"method": request.method},
                )
                return JSONResponse(
                    status_code=403,
                    content={
                        "detail": "ITAR-controlled content requires verified U.S. person ITAR access"
                    },
                )
            log_itar_access(
                username=user.username or "unknown",
                action="ACCESS",
                resource_type="API_PATH",
                resource_id=path,
                granted=True,
                details={"method": request.method},
            )

        response = await call_next(request)
        if response.status_code in {401, 403}:
            log_auth_event(
                event_type="AUTH_FAILURE",
                username=user.username or "unknown",
                success=False,
                ip_address=ip_address,
                details={"path": path, "status": response.status_code},
            )
        return response


__all__ = [
    "CognitoAuthzMiddleware",
    "MIRAUser",
    "auth_enabled",
    "get_current_user",
    "require_itar_user",
    "require_admin_user",
    "get_request_user",
    "authorize_owner_or_admin",
    "verify_token",
    "validate_auth_configuration",
]
