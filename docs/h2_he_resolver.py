#!/usr/bin/env python3
"""H2/He embrittlement index resolver for MAPTIS materials.

Maps MAPTIS material designations to NSS 1740.16 Table A5.8 H2/He notched
strength ratios.  Used by the Browse Materials tab to display hydrogen
embrittlement level without requiring environment context.

Reference condition: 10 000 psi GH2, 72 deg-F (NSS 1740.16 Table A5.8).

Compliance: SWE-013, SWE-033, NASA-STD-8739.8B
"""

from __future__ import annotations

__safety_critical__: bool = True

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

__all__ = [
    "H2HeIndexResolver",
    "H2HeResult",
    "resolve_h2_he_index",
]


@dataclass(frozen=True, slots=True)
class H2HeResult:
    """Result of an H2/He index lookup for a single MAPTIS material.

    Attributes:
        h2_he_ratio: Notched strength ratio H2/He from Table A5.8.
        level: Embrittlement level (negligible | slight | severe | extreme).
        a58_id: Table A5.8 entry identifier for traceability.
        a58_name: Canonical material name from Table A5.8.
        notes: Condition or disambiguation notes from the curated config.
        source: Always "NSS 1740.16 Table A5.8" for provenance.
        condition_warning: Set when material has condition-dependent entries
            (e.g. Ti-6Al-4V STA vs annealed).  The Browse badge should
            display the *worst-case* ratio but flag the warning.
    """

    h2_he_ratio: float
    level: str
    a58_id: str
    a58_name: str
    notes: str
    source: str = "NSS 1740.16 Table A5.8"
    condition_warning: Optional[str] = None


# Embrittlement level boundaries (lower bound inclusive).
_LEVEL_THRESHOLDS: list[tuple[float, str]] = [
    (0.90, "negligible"),
    (0.75, "slight"),
    (0.50, "severe"),
    (0.00, "extreme"),
]


def _ratio_to_level(ratio: float) -> str:
    """Map H2/He ratio to embrittlement level string."""
    for threshold, level in _LEVEL_THRESHOLDS:
        if ratio >= threshold:
            return level
    return "extreme"


class H2HeIndexResolver:
    """Resolve MAPTIS designations to Table A5.8 H2/He index values.

    The resolver loads a curated JSON config containing 36 materials from
    NSS 1740.16 Table A5.8.  Each entry has ``maptis_patterns`` (substrings
    that must appear in the MAPTIS designation, case-insensitive) and
    ``maptis_exclude`` (substrings that disqualify a match, e.g. "C10200"
    prevents copper alloy C10200 from matching "1020 Steel").

    Matching priority:
        1. All ``maptis_patterns`` are tested as case-insensitive substring
           matches against ``matl_designation``.
        2. If any ``maptis_exclude`` pattern also matches, the entry is
           skipped.
        3. If multiple A5.8 entries match (e.g. Ti-6Al-4V has both STA and
           annealed rows), the *worst-case* (lowest ratio) is returned with
           a ``condition_warning``.

    Compliance: SWE-013, SWE-033
    """

    def __init__(self, config_path: Optional[Path] = None) -> None:
        if config_path is None:
            config_path = Path(__file__).parent / "h2_he_index.json"
        self._entries: list[dict] = []
        self._meta: dict = {}
        self._load(config_path)

    def _load(self, path: Path) -> None:
        """Load curated A5.8 config from JSON."""
        if not path.exists():
            logger.error("H2/He index config not found: %s", path)
            return
        try:
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            self._meta = data.get("_meta", {})
            self._entries = data.get("materials", [])
            logger.info(
                "Loaded H2/He index: %d materials from %s",
                len(self._entries),
                self._meta.get("source", "unknown"),
            )
        except Exception:
            logger.exception("Failed to load H2/He index config")

    def resolve(self, designation: str) -> Optional[H2HeResult]:
        """Look up H2/He index for a MAPTIS material designation.

        Args:
            designation: MAPTIS ``matl_designation`` string.

        Returns:
            H2HeResult if a match is found, None otherwise.
        """
        if not designation or not self._entries:
            return None

        desig_upper = designation.upper()
        matches: list[dict] = []

        for entry in self._entries:
            patterns = entry.get("maptis_patterns", [])
            excludes = entry.get("maptis_exclude", [])

            # All patterns must match (they're alternative names, so ANY match)
            hit = any(p.upper() in desig_upper for p in patterns)
            if not hit:
                continue

            # Check exclusions
            excluded = any(x.upper() in desig_upper for x in excludes)
            if excluded:
                continue

            matches.append(entry)

        if not matches:
            return None

        if len(matches) == 1:
            e = matches[0]
            return H2HeResult(
                h2_he_ratio=e["h2_he_ratio"],
                level=_ratio_to_level(e["h2_he_ratio"]),
                a58_id=e["id"],
                a58_name=e["name"],
                notes=e.get("notes", ""),
            )

        # Multiple matches -> worst-case ratio, flag condition-dependence.
        worst = min(matches, key=lambda e: e["h2_he_ratio"])
        best = max(matches, key=lambda e: e["h2_he_ratio"])
        names = [e["name"] for e in matches]

        return H2HeResult(
            h2_he_ratio=worst["h2_he_ratio"],
            level=_ratio_to_level(worst["h2_he_ratio"]),
            a58_id=worst["id"],
            a58_name=worst["name"],
            notes=worst.get("notes", ""),
            condition_warning=(
                f"Condition-dependent: ranges from {worst['h2_he_ratio']:.2f} "
                f"({worst['name']}) to {best['h2_he_ratio']:.2f} "
                f"({best['name']}). Specify condition in Ask Question tab."
            ),
        )

    def resolve_batch(
        self, materials: dict[str, str]
    ) -> dict[str, Optional[H2HeResult]]:
        """Resolve H2/He index for a batch of materials.

        Args:
            materials: Mapping of material_key -> designation.

        Returns:
            Mapping of material_key -> H2HeResult (or None).
        """
        results: dict[str, Optional[H2HeResult]] = {}
        matched = 0
        for mat_key, designation in materials.items():
            result = self.resolve(designation)
            results[mat_key] = result
            if result is not None:
                matched += 1

        logger.info(
            "H2/He batch resolve: %d/%d materials matched Table A5.8",
            matched,
            len(materials),
        )
        return results


# ---------------------------------------------------------------------------
# Module-level convenience
# ---------------------------------------------------------------------------

_RESOLVER: Optional[H2HeIndexResolver] = None


def resolve_h2_he_index(designation: str) -> Optional[H2HeResult]:
    """Convenience wrapper using a module-level singleton resolver.

    Args:
        designation: MAPTIS ``matl_designation`` string.

    Returns:
        H2HeResult if matched, None otherwise.
    """
    global _RESOLVER
    if _RESOLVER is None:
        _RESOLVER = H2HeIndexResolver()
    return _RESOLVER.resolve(designation)
