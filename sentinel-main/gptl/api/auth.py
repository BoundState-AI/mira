# Copyright 2025 BoundStateAI
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
Authentication middleware for SENTINEL API.

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI
"""

from __future__ import annotations

from typing import Optional

from fastapi import Header, HTTPException, Depends

from gptl.api.deps import get_settings, Settings

__safety_critical__: bool = True


async def verify_api_key(
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
    settings: Settings = Depends(get_settings),
) -> Optional[str]:
    """
    Verify API key if auth is enabled.

    Returns the API key if valid, None if open demo mode.
    Raises HTTPException if invalid key provided.
    """
    if settings.auth_mode == "open_demo":
        return None

    if not x_api_key:
        raise HTTPException(
            status_code=401,
            detail="Missing X-API-Key header",
        )

    valid_keys = [k.strip() for k in settings.api_keys.split(",") if k.strip()]

    if x_api_key not in valid_keys:
        raise HTTPException(
            status_code=403,
            detail="Invalid API key",
        )

    return x_api_key


__all__ = ["verify_api_key"]
