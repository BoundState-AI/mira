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
Audit endpoint - retrieve full trace details.

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from gptl.api.auth import verify_api_key

__safety_critical__: bool = True

router = APIRouter()


@router.get("/audit/{trace_id}")
async def get_audit(
    trace_id: str,
    include_excerpts: bool = Query(default=True),
    max_eliminations: int = Query(default=100, ge=1, le=1000),
    api_key: Optional[str] = Depends(verify_api_key),
):
    """
    Retrieve full audit trail for a trace.

    Returns:
    - What was considered
    - What was eliminated and why
    - What survived
    - What evidence was used
    - All model calls
    - Refusal details (if applicable)
    """
    # TODO: Implement audit storage retrieval
    # For MVP, audits are returned inline with query response

    raise HTTPException(
        status_code=501,
        detail="Audit persistence not yet implemented. Use include_audit=true in query request.",
    )


__all__ = ["router"]
