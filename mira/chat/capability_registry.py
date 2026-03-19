#!/usr/bin/env python3
"""
Module: Capability Registry
Purpose: Phase 1 hardcoded registry of MIRA engine capabilities.

Maps engine IDs to their contracts: supported tasks, domains, required inputs,
chaining rules, and side-effect levels.  Phase 2 will load this from a config
file; Phase 1 uses a Python dict.

Implements BS-SPEC-MIRA-CHAT-001-REV2 Section 7 (Engine Registry).

BoundState AI 2026
Version: 1.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: SWE-013, SWE-032, NASA-STD-8739.8B
Safety Critical: False
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Phase 1 registry — hardcoded
# ---------------------------------------------------------------------------

_PHASE1_REGISTRY: Dict[str, Dict[str, Any]] = {
    "oca": {
        "engine_id": "oca",
        "display_name": "Oxygen Compatibility Assessment",
        "supported_tasks": ["answer_only"],
        "supported_domains": ["oxygen_compatibility"],
        "required_inputs": ["material_designation"],
        "optional_inputs": ["pressure", "temperature", "configuration"],
        "service_module": "mira.oca",
        "multi_step": True,
        "case_driven": True,
        "side_effect_level": "read_only",
        "chaining_outputs": {
            "CONDITIONAL_PASS": {
                "suggests": "mua",
                "auto_chain": False,
                "data_handoff": ["material", "environment", "gaps", "verdict"],
            },
        },
    },
    "h2": {
        "engine_id": "h2",
        "display_name": "Hydrogen Compatibility Assessment",
        "supported_tasks": ["answer_only"],
        "supported_domains": ["hydrogen_compatibility"],
        "required_inputs": ["material_designation"],
        "optional_inputs": ["pressure", "temperature", "phase", "condition"],
        "service_module": "mira.h2",
        "multi_step": False,
        "case_driven": False,
        "side_effect_level": "read_only",
        "chaining_outputs": {},
    },
    "maptis_search": {
        "engine_id": "maptis_search",
        "display_name": "MAPTIS Material Search",
        "supported_tasks": ["answer_only"],
        "supported_domains": ["materials_search", "test_data", "material_general"],
        "required_inputs": ["query_text"],
        "optional_inputs": ["material_designation", "property_filter"],
        "service_module": "mira.search",
        "multi_step": False,
        "case_driven": False,
        "side_effect_level": "read_only",
        "chaining_outputs": {},
    },
    "galvanic": {
        "engine_id": "galvanic",
        "display_name": "Galvanic Corrosion Assessment",
        "supported_tasks": ["answer_only"],
        "supported_domains": ["galvanic_corrosion", "dissimilar_metals"],
        "required_inputs": ["material_designation"],
        "optional_inputs": ["second_material", "environment"],
        "service_module": "mira.galvanic",
        "multi_step": False,
        "case_driven": False,
        "side_effect_level": "read_only",
        "chaining_outputs": {},
    },
    "bsmh": {
        "engine_id": "bsmh",
        "display_name": "BoundState Material Helper",
        "supported_tasks": ["answer_only"],
        "supported_domains": ["general_help", "material_general"],
        "required_inputs": ["query_text"],
        "optional_inputs": [],
        "service_module": "mira.bsmh.bouncer",
        "multi_step": False,
        "case_driven": False,
        "side_effect_level": "read_only",
        "chaining_outputs": {},
    },
}

# Fine-routing target → engine_id mapping
# Used by get_engine_for_routing() to translate fine_routing from the
# query interpreter into the engine that should handle it.
_ROUTING_MAP: Dict[str, str] = {
    "oca": "oca",
    "h2": "h2",
    "maptis_search": "maptis_search",
    "galvanic": "galvanic",
    "bsmh": "bsmh",
    # Aliases
    "oxygen": "oca",
    "hydrogen": "h2",
    "search": "maptis_search",
    "material_search": "maptis_search",
    "general": "bsmh",
    "help": "bsmh",
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def get_engine(engine_id: str) -> Optional[Dict[str, Any]]:
    """
    Look up a single engine by its canonical engine_id.

    Returns None if the engine is not registered (rather than raising).
    """
    entry = _PHASE1_REGISTRY.get(engine_id)
    if entry is None:
        logger.warning("[REGISTRY] Unknown engine_id: %s", engine_id)
    return entry


def get_engines_for_domain(domain: str) -> List[Dict[str, Any]]:
    """
    Return all engines whose ``supported_domains`` include *domain*.

    The list is ordered with the most specific engines first (fewest
    supported domains) so callers can pick the best match.
    """
    matches = [
        entry
        for entry in _PHASE1_REGISTRY.values()
        if domain in entry["supported_domains"]
    ]
    # Sort: fewer supported domains = more specialised = first
    matches.sort(key=lambda e: len(e["supported_domains"]))
    return matches


def get_engine_for_routing(fine_routing: str) -> Optional[str]:
    """
    Map a fine_routing value (from the query interpreter) to a canonical
    engine_id.

    Returns None if the routing target is not recognised.
    """
    engine_id = _ROUTING_MAP.get(fine_routing)
    if engine_id is None:
        logger.warning("[REGISTRY] No engine mapped for fine_routing=%s", fine_routing)
    return engine_id


def validate_inputs(
    engine_id: str,
    inputs: Dict[str, Any],
) -> Tuple[bool, List[str]]:
    """
    Check whether *inputs* satisfy the engine's ``required_inputs``.

    Parameters
    ----------
    engine_id : str
        Target engine.
    inputs : dict
        Key-value pairs of inputs the caller intends to provide.

    Returns
    -------
    (valid, missing) : tuple[bool, list[str]]
        ``valid`` is True when all required inputs are present and non-None.
        ``missing`` lists the required keys that are absent or None.
    """
    entry = _PHASE1_REGISTRY.get(engine_id)
    if entry is None:
        logger.warning("[REGISTRY] validate_inputs: unknown engine %s", engine_id)
        return False, [f"unknown_engine:{engine_id}"]

    required = entry["required_inputs"]
    missing = [
        key for key in required
        if key not in inputs or inputs[key] is None
    ]
    return len(missing) == 0, missing


def list_engines() -> List[Dict[str, Any]]:
    """Return all registered engines (shallow copies)."""
    return [dict(e) for e in _PHASE1_REGISTRY.values()]


def get_chaining_suggestion(
    engine_id: str,
    outcome: str,
) -> Optional[Dict[str, Any]]:
    """
    If *engine_id*'s registry entry defines a chaining rule for *outcome*,
    return the chaining descriptor.  Otherwise return None.

    Example::

        get_chaining_suggestion("oca", "CONDITIONAL_PASS")
        # -> {"suggests": "mua", "auto_chain": False, "data_handoff": [...]}
    """
    entry = _PHASE1_REGISTRY.get(engine_id)
    if entry is None:
        return None
    return entry.get("chaining_outputs", {}).get(outcome)
