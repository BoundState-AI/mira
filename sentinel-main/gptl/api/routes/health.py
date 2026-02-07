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
Health check endpoints.

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI
"""

from __future__ import annotations

import os
from typing import Dict, Any

from fastapi import APIRouter
from pydantic import BaseModel

__safety_critical__: bool = True

router = APIRouter()


class HealthResponse(BaseModel):
    """Health check response."""
    status: str
    version: str
    git_sha: str


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    """Liveness check."""
    return HealthResponse(
        status="ok",
        version="1.0.0",
        git_sha=os.getenv("GIT_SHA", "unknown"),
    )


@router.get("/ready")
async def ready() -> Dict[str, Any]:
    """Readiness check - verify providers are initialized."""
    from gptl.api.deps import get_vector_store, get_feature_cache
    from gptl.providers.faiss_provider import FAISS_AVAILABLE

    result: Dict[str, Any] = {
        "status": "ready",
        "faiss_available": FAISS_AVAILABLE,
    }

    try:
        if FAISS_AVAILABLE:
            vs = get_vector_store()
            result["vector_store"] = vs.get_stats()
    except Exception as e:
        result["vector_store_error"] = str(e)

    try:
        fc = get_feature_cache()
        result["feature_cache"] = fc.get_stats()
    except Exception as e:
        result["feature_cache_error"] = str(e)

    return result


__all__ = ["router"]
