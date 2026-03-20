#!/usr/bin/env python3
"""
Module: Capability Registry
Purpose: Phase 2 self-declaring engine registry with JSON manifest discovery.

Engines declare their capabilities via JSON manifests in ``mira/chat/manifests/``.
At startup, the registry scans the manifest directory, validates each file, and
builds the in-memory registry.  Any engines still using the hardcoded Phase 1
format are merged as a fallback.

Implements BS-SPEC-MIRA-CHAT-001-REV2 Section 4.2 (Engine Self-Declaration)
and Section 7 (Engine Registry).

BoundState AI 2026
Version: 2.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: SWE-013, SWE-032, NASA-STD-8739.8B
Safety Critical: False
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MANIFESTS_DIR = Path(__file__).resolve().parent / "manifests"
_SUPPORTED_SCHEMA_VERSIONS = {"1.0"}

# Required fields in every manifest JSON
_REQUIRED_MANIFEST_FIELDS = frozenset({
    "engine_id",
    "display_name",
    "version",
    "supported_tasks",
    "supported_domains",
    "required_inputs",
    "adapter_module",
    "adapter_class",
    "side_effect_level",
    "output_schema_version",
})


# ---------------------------------------------------------------------------
# Phase 1 fallback registry — only engines NOT yet migrated to manifests
# ---------------------------------------------------------------------------
# Once all engines have manifests, this dict can be emptied.

_PHASE1_FALLBACK: Dict[str, Dict[str, Any]] = {}


# ---------------------------------------------------------------------------
# Manifest-based registry (populated at first access)
# ---------------------------------------------------------------------------

_registry: Dict[str, Dict[str, Any]] = {}
_routing_map: Dict[str, str] = {}
_initialized: bool = False


# ---------------------------------------------------------------------------
# Manifest validation
# ---------------------------------------------------------------------------


def _validate_manifest(data: Dict[str, Any], path: Path) -> Optional[str]:
    """Validate a parsed manifest dict.  Returns an error string or None."""
    missing = _REQUIRED_MANIFEST_FIELDS - set(data.keys())
    if missing:
        return f"Missing required fields: {sorted(missing)}"

    schema_version = str(data.get("output_schema_version", ""))
    if schema_version not in _SUPPORTED_SCHEMA_VERSIONS:
        return (
            f"Unsupported output_schema_version '{schema_version}' "
            f"(supported: {_SUPPORTED_SCHEMA_VERSIONS})"
        )

    if not isinstance(data.get("supported_tasks"), list):
        return "'supported_tasks' must be a list"

    if not isinstance(data.get("supported_domains"), list):
        return "'supported_domains' must be a list"

    if not isinstance(data.get("required_inputs"), list):
        return "'required_inputs' must be a list"

    return None


# ---------------------------------------------------------------------------
# Discovery & initialization
# ---------------------------------------------------------------------------


def _discover_manifests() -> Dict[str, Dict[str, Any]]:
    """Scan the manifests directory and load all valid engine manifests."""
    discovered: Dict[str, Dict[str, Any]] = {}

    if not MANIFESTS_DIR.is_dir():
        logger.warning(
            "[REGISTRY] Manifests directory not found: %s", MANIFESTS_DIR
        )
        return discovered

    for manifest_path in sorted(MANIFESTS_DIR.glob("*.json")):
        try:
            with manifest_path.open("r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning(
                "[REGISTRY] Failed to parse manifest %s: %s",
                manifest_path.name, exc,
            )
            continue

        error = _validate_manifest(data, manifest_path)
        if error:
            logger.warning(
                "[REGISTRY] Invalid manifest %s: %s",
                manifest_path.name, error,
            )
            continue

        engine_id = str(data["engine_id"])

        if engine_id in discovered:
            logger.warning(
                "[REGISTRY] Duplicate engine_id '%s' in %s (already loaded)",
                engine_id, manifest_path.name,
            )
            continue

        # Normalize optional fields with defaults
        data.setdefault("optional_inputs", [])
        data.setdefault("multi_step", False)
        data.setdefault("case_driven", False)
        data.setdefault("chaining_outputs", {})
        data.setdefault("routing_aliases", [engine_id])

        discovered[engine_id] = data
        logger.info(
            "[REGISTRY] Loaded manifest: %s (%s v%s)",
            engine_id, data["display_name"], data["version"],
        )

    return discovered


def _build_routing_map(registry: Dict[str, Dict[str, Any]]) -> Dict[str, str]:
    """Build the fine_routing -> engine_id mapping from manifest routing_aliases."""
    routing: Dict[str, str] = {}
    for engine_id, entry in registry.items():
        # The engine_id itself is always a valid route
        routing[engine_id] = engine_id
        # Plus any declared aliases
        for alias in entry.get("routing_aliases", []):
            alias_lower = alias.lower()
            if alias_lower in routing and routing[alias_lower] != engine_id:
                logger.warning(
                    "[REGISTRY] Routing alias '%s' conflicts: %s vs %s (keeping first)",
                    alias, routing[alias_lower], engine_id,
                )
                continue
            routing[alias_lower] = engine_id
    return routing


def _ensure_initialized() -> None:
    """Initialize the registry on first access (thread-safe enough for startup)."""
    global _registry, _routing_map, _initialized
    if _initialized:
        return

    # Phase 2: discover from JSON manifests
    discovered = _discover_manifests()

    # Merge Phase 1 fallback for any engines without manifests
    merged = dict(_PHASE1_FALLBACK)
    merged.update(discovered)  # Manifests take precedence

    _registry = merged
    _routing_map = _build_routing_map(_registry)
    _initialized = True

    logger.info(
        "[REGISTRY] Initialized with %d engine(s): %s",
        len(_registry), sorted(_registry.keys()),
    )


def reload_registry() -> None:
    """Force re-discovery of manifests.  Useful for testing or hot-reload."""
    global _initialized
    _initialized = False
    _ensure_initialized()


# ---------------------------------------------------------------------------
# Public API (same interface as Phase 1)
# ---------------------------------------------------------------------------


def get_engine(engine_id: str) -> Optional[Dict[str, Any]]:
    """
    Look up a single engine by its canonical engine_id.

    Returns None if the engine is not registered (rather than raising).
    """
    _ensure_initialized()
    entry = _registry.get(engine_id)
    if entry is None:
        logger.warning("[REGISTRY] Unknown engine_id: %s", engine_id)
    return entry


def get_engines_for_domain(domain: str) -> List[Dict[str, Any]]:
    """
    Return all engines whose ``supported_domains`` include *domain*.

    The list is ordered with the most specific engines first (fewest
    supported domains) so callers can pick the best match.
    """
    _ensure_initialized()
    matches = [
        entry
        for entry in _registry.values()
        if domain in entry.get("supported_domains", [])
    ]
    # Sort: fewer supported domains = more specialised = first
    matches.sort(key=lambda e: len(e.get("supported_domains", [])))
    return matches


def get_engine_for_routing(fine_routing: str) -> Optional[str]:
    """
    Map a fine_routing value (from the query interpreter) to a canonical
    engine_id.

    Returns None if the routing target is not recognised.
    """
    _ensure_initialized()
    engine_id = _routing_map.get(fine_routing)
    if engine_id is None:
        # Try case-insensitive fallback
        engine_id = _routing_map.get(fine_routing.lower())
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
    _ensure_initialized()
    entry = _registry.get(engine_id)
    if entry is None:
        logger.warning("[REGISTRY] validate_inputs: unknown engine %s", engine_id)
        return False, [f"unknown_engine:{engine_id}"]

    required = entry.get("required_inputs", [])
    missing = [
        key for key in required
        if key not in inputs or inputs[key] is None
    ]
    return len(missing) == 0, missing


def list_engines() -> List[Dict[str, Any]]:
    """Return all registered engines (shallow copies)."""
    _ensure_initialized()
    return [dict(e) for e in _registry.values()]


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
    _ensure_initialized()
    entry = _registry.get(engine_id)
    if entry is None:
        return None
    return entry.get("chaining_outputs", {}).get(outcome)


def get_manifest(engine_id: str) -> Optional[Dict[str, Any]]:
    """Return the full manifest dict for an engine, or None."""
    _ensure_initialized()
    return _registry.get(engine_id)


def get_adapter_info(engine_id: str) -> Optional[Tuple[str, str]]:
    """
    Return (adapter_module, adapter_class) for the given engine_id.

    Useful for dynamic adapter loading in Phase 2+.
    """
    _ensure_initialized()
    entry = _registry.get(engine_id)
    if entry is None:
        return None
    module = entry.get("adapter_module")
    cls = entry.get("adapter_class")
    if module and cls:
        return (module, cls)
    return None
