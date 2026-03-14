"""Reference pack loader for OCA deterministic rules."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from .models import AuthoritySource, OcaAuthorityManifest


DATA_DIR = Path(__file__).parent / "data"


def _load_json(name: str) -> Any:
    with (DATA_DIR / name).open("r", encoding="utf-8") as handle:
        return json.load(handle)


@lru_cache(maxsize=1)
def get_authority_manifest() -> OcaAuthorityManifest:
    payload = _load_json("source_manifest.json")
    return OcaAuthorityManifest(
        spec_id=payload["spec_id"],
        approved_on=payload["approved_on"],
        sources=[AuthoritySource(**item) for item in payload["sources"]],
    )


@lru_cache(maxsize=1)
def get_requirement_binding() -> list[dict[str, Any]]:
    return _load_json("oca_requirement_binding.json")


@lru_cache(maxsize=1)
def get_ignition_mechanisms() -> list[dict[str, Any]]:
    return _load_json("oca_ignition_mechanisms.json")


@lru_cache(maxsize=1)
def get_material_pressure_rules() -> dict[str, Any]:
    return _load_json("oca_material_pressure_rules.json")


@lru_cache(maxsize=1)
def get_test_mapping() -> dict[str, Any]:
    return _load_json("oca_test_mapping.json")


@lru_cache(maxsize=1)
def get_hazard_control_library() -> list[dict[str, Any]]:
    return _load_json("oca_hazard_control_library.json")


@lru_cache(maxsize=1)
def get_material_reference() -> list[dict[str, Any]]:
    data = _load_json("material_reference.json")
    if isinstance(data, dict):
        return data.get("families", [])
    return data


@lru_cache(maxsize=1)
def get_material_catalog() -> list[dict[str, Any]]:
    data = _load_json("material_reference.json")
    if isinstance(data, dict):
        return data.get("materials", [])
    return data


@lru_cache(maxsize=1)
def get_focr_definitions() -> list[dict[str, Any]]:
    return _load_json("oca_focr_definitions.json")


@lru_cache(maxsize=1)
def get_reaction_effect_matrix() -> dict[str, Any]:
    return _load_json("oca_reaction_effect_matrix.json")


@lru_cache(maxsize=1)
def get_ignition_rating_logic() -> dict[str, Any]:
    return _load_json("oca_ignition_rating_logic.json")
