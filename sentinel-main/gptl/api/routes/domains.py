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
Domain endpoints - list and inspect domain packs.

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI
"""

from __future__ import annotations

from typing import List, Optional, Dict, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from gptl.api.auth import verify_api_key
from gptl.config_loader import load_domain_pack, get_loader, compute_config_hash

__safety_critical__: bool = True

router = APIRouter()


class DomainSummary(BaseModel):
    """Summary of a domain pack."""
    domain_id: str
    name: str
    version: str
    description: str
    config_hash: str


class DomainDetail(BaseModel):
    """Full domain pack details (safe for clients)."""
    domain_id: str
    name: str
    version: str
    description: str
    config_hash: str
    intent_frames: List[str]
    evidence_types: Dict[str, List[str]]
    quality_tiers: List[str]


@router.get("/domains", response_model=List[DomainSummary])
async def list_domains(
    api_key: Optional[str] = Depends(verify_api_key),
) -> List[DomainSummary]:
    """List available domain packs."""
    loader = get_loader()
    available = loader.list_available_domains()

    summaries = []
    for domain_id in available:
        try:
            pack = load_domain_pack(domain_id)
            # Get name and description from pack if available
            name = getattr(pack, 'name', domain_id)
            description = getattr(pack, 'description', '')
            summaries.append(DomainSummary(
                domain_id=pack.domain_id,
                name=name if name else domain_id,
                version=pack.version,
                description=description if description else '',
                config_hash=compute_config_hash(pack),
            ))
        except Exception:
            continue

    return summaries


@router.get("/domains/{domain_id}", response_model=DomainDetail)
async def get_domain(
    domain_id: str,
    api_key: Optional[str] = Depends(verify_api_key),
) -> DomainDetail:
    """Get details of a specific domain pack."""
    try:
        pack = load_domain_pack(domain_id)
    except Exception as e:
        raise HTTPException(
            status_code=404,
            detail=f"Domain pack not found: {domain_id}",
        )

    # Get name and description from pack if available
    name = getattr(pack, 'name', domain_id)
    description = getattr(pack, 'description', '')

    # Extract quality tiers - handle both dict and object formats
    quality_tiers = []
    if hasattr(pack, 'quality_tiers'):
        qt = pack.quality_tiers
        if isinstance(qt, dict):
            quality_tiers = list(qt.keys())
        elif hasattr(qt, '__dict__'):
            quality_tiers = list(vars(qt).keys())

    return DomainDetail(
        domain_id=pack.domain_id,
        name=name if name else domain_id,
        version=pack.version,
        description=description if description else '',
        config_hash=compute_config_hash(pack),
        intent_frames=[f.frame_id for f in pack.intent_frames],
        evidence_types={
            "primary": [e.value for e in pack.evidence_taxonomy.primary],
            "supporting": [e.value for e in pack.evidence_taxonomy.supporting],
            "contextual": [e.value for e in pack.evidence_taxonomy.contextual],
            "noise": [e.value for e in pack.evidence_taxonomy.noise],
        },
        quality_tiers=quality_tiers if quality_tiers else ["standard", "critical"],
    )


__all__ = ["router"]
