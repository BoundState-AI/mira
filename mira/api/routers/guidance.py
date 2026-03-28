#!/usr/bin/env python3
"""
Universal Guidance Schema API router.

Serves validated guidance packs and authority registries so frontend surfaces
can verify schema currency and swap in newer packs without a redeploy.
"""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from mira.api.module_controls import runtime_key_enabled
from mira.guidance.models import AuthorityRegistryEntry, GuidancePack


router = APIRouter()

_ROOT = Path(__file__).resolve().parents[3]
_FRONTEND_DATA = _ROOT / "frontend" / "src" / "data"

_PACK_SOURCES: dict[str, dict[str, Path]] = {
    "mira-oca-guidance": {
        "pack": _FRONTEND_DATA / "oca-guidance-pack.json",
        "authority_registry": _FRONTEND_DATA / "authority-registry.json",
    },
    "mira-mua-guidance": {
        "pack": _FRONTEND_DATA / "mua-guidance-pack.json",
        "authority_registry": _FRONTEND_DATA / "authority-registry.json",
    },
    "mira-miul-guidance": {
        "pack": _FRONTEND_DATA / "miul-guidance-pack.json",
        "authority_registry": _FRONTEND_DATA / "authority-registry.json",
    },
    "mira-h2-guidance": {
        "pack": _FRONTEND_DATA / "h2-guidance-pack.json",
        "authority_registry": _FRONTEND_DATA / "authority-registry.json",
    },
    "mira-galvanic-guidance": {
        "pack": _FRONTEND_DATA / "galvanic-guidance-pack.json",
        "authority_registry": _FRONTEND_DATA / "authority-registry.json",
    },
    "mira-fracture-guidance": {
        "pack": _FRONTEND_DATA / "fracture-guidance-pack.json",
        "authority_registry": _FRONTEND_DATA / "authority-registry.json",
    },
    "mira-mp-plan-guidance": {
        "pack": _FRONTEND_DATA / "mp-plan-guidance-pack.json",
        "authority_registry": _FRONTEND_DATA / "authority-registry.json",
    },
}

_PACK_CACHE: dict[str, GuidancePack] = {}
_AUTHORITY_CACHE: dict[str, dict[str, AuthorityRegistryEntry]] = {}


class GuidancePackVersionResponse(BaseModel):
    pack_id: str
    version: str
    pack: GuidancePack | None = None


GuidancePackVersionResponse.model_rebuild()


def _get_pack_source(pack_id: str) -> dict[str, Path]:
    if pack_id == "mira-mua-guidance" and not runtime_key_enabled("guidance:mua"):
        raise HTTPException(status_code=404, detail=f"Unknown guidance pack '{pack_id}'.")
    try:
        return _PACK_SOURCES[pack_id]
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"Unknown guidance pack '{pack_id}'.") from exc


def _load_pack(pack_id: str) -> GuidancePack:
    cached = _PACK_CACHE.get(pack_id)
    if cached is not None:
        return cached

    pack_path = _get_pack_source(pack_id)["pack"]
    if not pack_path.exists():
        raise HTTPException(status_code=500, detail=f"Guidance pack '{pack_id}' is missing.")

    pack = GuidancePack.model_validate(
        json.loads(pack_path.read_text(encoding="utf-8")),
    )
    _PACK_CACHE[pack_id] = pack
    return pack


def _load_authority_registry(pack_id: str) -> dict[str, AuthorityRegistryEntry]:
    cached = _AUTHORITY_CACHE.get(pack_id)
    if cached is not None:
        return cached

    authority_path = _get_pack_source(pack_id)["authority_registry"]
    if not authority_path.exists():
        raise HTTPException(
            status_code=500,
            detail=f"Authority registry for guidance pack '{pack_id}' is missing.",
        )

    raw_registry = json.loads(authority_path.read_text(encoding="utf-8"))
    registry = {
        authority_id: AuthorityRegistryEntry.model_validate(payload)
        for authority_id, payload in raw_registry.items()
    }
    _AUTHORITY_CACHE[pack_id] = registry
    return registry


@router.get("/ping")
async def ping() -> dict[str, str]:
    return {"status": "ok", "domain": "guidance"}


@router.get("/packs/{pack_id}", response_model=GuidancePack)
async def get_guidance_pack(pack_id: str) -> GuidancePack:
    return _load_pack(pack_id)


@router.get("/packs/{pack_id}/version", response_model=GuidancePackVersionResponse)
async def get_guidance_pack_version(pack_id: str) -> GuidancePackVersionResponse:
    pack = _load_pack(pack_id)
    return GuidancePackVersionResponse(
        pack_id=pack.guidance_pack_id,
        version=pack.schema_version,
        pack=pack,
    )


@router.get(
    "/packs/{pack_id}/authority-registry",
    response_model=dict[str, AuthorityRegistryEntry],
)
async def get_guidance_authority_registry(
    pack_id: str,
) -> dict[str, AuthorityRegistryEntry]:
    _load_pack(pack_id)  # Ensure pack exists before serving registry
    return _load_authority_registry(pack_id)
