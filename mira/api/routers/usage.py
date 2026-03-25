#!/usr/bin/env python3
"""Application usage telemetry endpoints for Mira."""

from __future__ import annotations

import json
import logging
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from mira.api.auth import get_request_user

LOGGER = logging.getLogger("mira.usage")
LOGGER.setLevel(logging.INFO)

router = APIRouter()


class UsageEventRequest(BaseModel):
    """Frontend usage event payload."""

    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    event_type: Literal["pageview"] = "pageview"
    path: str = Field(..., min_length=1, max_length=256)
    module_id: str = Field(..., min_length=1, max_length=128)
    page_label: str | None = Field(default=None, max_length=160)
    navigation_type: Literal["PUSH", "POP", "REPLACE", "unknown"] = "unknown"
    client_session_id: str = Field(..., min_length=8, max_length=128)
    referrer: str | None = Field(default=None, max_length=512)


def _request_ip(request: Request) -> str:
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    if request.client and request.client.host:
        return request.client.host
    return "unknown"


@router.get("/ping")
async def ping() -> dict[str, str]:
    return {"status": "ok", "domain": "usage"}


@router.post("/events")
async def record_usage_event(payload: UsageEventRequest, request: Request) -> dict[str, bool]:
    path = payload.path.strip()
    if not path.startswith("/"):
        raise HTTPException(status_code=422, detail="Usage event path must start with '/'")

    user = get_request_user(request)
    event = {
        "record_type": "mira_usage",
        "event_type": payload.event_type,
        "path": path,
        "module_id": payload.module_id,
        "page_label": payload.page_label,
        "navigation_type": payload.navigation_type,
        "client_session_id": payload.client_session_id,
        "client_ip": _request_ip(request),
        "user_agent": request.headers.get("user-agent", ""),
        "auth_user": (
            {
                "username": user.username,
                "email": user.email,
                "groups": user.groups,
                "role": user.role,
                "itar_cleared": user.is_itar_cleared,
                "is_admin": user.is_admin,
            }
            if user is not None
            else None
        ),
        "referrer": payload.referrer,
    }
    LOGGER.info("MIRA_USAGE %s", json.dumps(event, separators=(",", ":"), sort_keys=True))
    return {"accepted": True}
