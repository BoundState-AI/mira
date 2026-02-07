#!/usr/bin/env python3
"""
Stage 1: Parse — Extract structured constraints from natural language.

Normalizes all units to canonical form (psi, °C) per Rule 5.5.
Classifies environment into EnvironmentClass per Rule 5.3.

BoundState AI 2026
Version: 3.0.0

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI
"""

from __future__ import annotations

import logging
import re
from typing import Optional

from ..context import EnvironmentClass, MaterialConstraints, QueryContext
from ..stage import PipelineStage

logger = logging.getLogger(__name__)

# ── Material patterns (specific first, generic last) ──────────────────
_MATERIAL_PATTERNS = [
    # Specific aerospace alloys
    r"(stainless steel \d+[a-z]*)",
    r"(aluminum \d+[a-z\d-]*)",
    r"(al \d+[a-z\d-]*)",
    r"(inconel \d+)",
    r"(monel \d+)",
    r"(hastelloy [a-z0-9]+)",
    r"(titanium \d*[a-z\d-]*)",
    r"(viton [a-z]*)",
    r"(kel-?f\b)",
    r"(teflon)",
    r"(kapton)",
    r"(ptfe)",
    r"(tefzel)",
    r"(fluorosilicone\s*(?:rubber)?)",
    r"(silicone\s+rubber|silicone)",
    r"(epdm)",
    r"(buna-?n)",
    r"(fkm)",
    r"(neoprene)",
    r"(vespel)",
    # Generic families (fallback)
    r"(aluminum)",
    r"(stainless steel)",
    r"(titanium)",
    r"(ss \d+[a-z]*)",
    r"(cres \d+[a-z]*)",
    # Verb-based patterns (lowest priority)
    r"\buse\s+(\w+[-]?\d*)\b.*(?:in|for|with)",
    r"\bis\s+(\w+[-]?\d*)\s+(?:compatible|safe|suitable)",
    r"\bcan\s+(\w+[-]?\d*)\s+be\s+used",
]


def _extract_material(query: str) -> Optional[str]:
    """Extract material name from query using pattern matching."""
    q = query.lower()
    for pattern in _MATERIAL_PATTERNS:
        match = re.search(pattern, q)
        if match:
            return match.group(1).strip()
    return None


def classify_environment(env_str: Optional[str]) -> EnvironmentClass:
    """
    Classify a free-text environment string into a coarse class.

    Rule 5.3: This is THE canonical environment classifier.
    All other code calls this function — no duplication.
    """
    if not env_str:
        return EnvironmentClass.OTHER

    env = env_str.lower()

    if any(kw in env for kw in ("oxygen", "gox", "lox", "o2", "o₂")):
        return EnvironmentClass.OXYGEN
    if any(kw in env for kw in ("hydrogen", "gh2", "lh2", "h2", "h₂")):
        return EnvironmentClass.HYDROGEN
    if any(kw in env for kw in ("air", "vacuum")):
        return EnvironmentClass.AIR_VACUUM

    return EnvironmentClass.OTHER


def _extract_environment(query: str) -> Optional[str]:
    """Extract environment from query text."""
    q = query.lower()
    if any(kw in q for kw in ("oxygen", "gox", "lox", "o2", "o₂")):
        return "oxygen"
    if any(kw in q for kw in ("hydrogen", "gh2", "lh2", "h2", "h₂")):
        return "hydrogen"
    if "vacuum" in q:
        return "vacuum"
    return None


def _extract_pressure_psi(query: str) -> Optional[float]:
    """Extract pressure and normalize to psi."""
    match = re.search(r"(\d+(?:\.\d+)?)\s*(psi|psia|bar|kpa|mpa)", query.lower())
    if not match:
        return None
    value = float(match.group(1))
    unit = match.group(2)
    if unit == "bar":
        return value * 14.504
    elif unit == "kpa":
        return value * 0.145
    elif unit == "mpa":
        return value * 145.04
    return value  # psi/psia


def _extract_temp_c(query: str) -> Optional[float]:
    """Extract temperature and normalize to °C."""
    match = re.search(r"(-?\d+(?:\.\d+)?)\s*(°?[fckFCK])\b", query)
    if not match:
        return None
    value = float(match.group(1))
    unit = match.group(2).lower().replace("°", "")
    if unit == "f":
        return (value - 32) * 5 / 9
    elif unit == "k":
        return value - 273.15
    return value  # already °C


class ParseStage(PipelineStage):
    """Stage 1: Parse natural language query into MaterialConstraints."""

    @property
    def name(self) -> str:
        return "parse"

    def execute(self, ctx: QueryContext) -> QueryContext:
        query = ctx.raw_query

        env_str = _extract_environment(query)

        ctx.constraints = MaterialConstraints(
            material=_extract_material(query),
            pressure_psi=_extract_pressure_psi(query),
            temp_c_max=_extract_temp_c(query),
            environment=env_str,
            environment_class=classify_environment(env_str),
        )

        logger.info(
            f"[PARSE] material={ctx.constraints.material}, "
            f"env={ctx.constraints.environment}, "
            f"pressure={ctx.constraints.pressure_psi} psi, "
            f"temp={ctx.constraints.temp_c_max} °C"
        )

        return ctx
