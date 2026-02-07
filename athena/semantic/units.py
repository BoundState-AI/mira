#!/usr/bin/env python3
"""
Module: Units
Purpose: ATHENA Unit Detection.

BoundState AI 2025
Version: 1.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Fran OpenAI 5 <noreply@openai.com>
Co-Authored-By: Grok 4.0 <noreply@x.ai>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: SWE-032
Safety Critical: True
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from athena.semantic.ontology import SemanticTag

__all__ = ["UnitDetector", "UnitInfo"]
__safety_critical__ = True


@dataclass
class UnitInfo:
    """Parsed unit information."""
    raw: str                    # Original text (e.g., "MPa", "ksi")
    canonical: str              # SI canonical (e.g., "Pa", "Pa")
    multiplier: float           # Conversion factor to canonical
    tag_hint: Optional[SemanticTag] = None  # Inferred semantic tag


# Unit patterns and conversions
PRESSURE_UNITS = {
    # MPa variants
    "mpa": ("Pa", 1e6),
    "megapascal": ("Pa", 1e6),
    "megapascals": ("Pa", 1e6),
    # ksi variants
    "ksi": ("Pa", 6.894757e6),
    "kpsi": ("Pa", 6.894757e6),
    # psi variants
    "psi": ("Pa", 6894.757),
    "psig": ("Pa", 6894.757),
    "psia": ("Pa", 6894.757),
    # GPa
    "gpa": ("Pa", 1e9),
    "gigapascal": ("Pa", 1e9),
    # Pa
    "pa": ("Pa", 1.0),
    "pascal": ("Pa", 1.0),
    # bar
    "bar": ("Pa", 1e5),
    "mbar": ("Pa", 100.0),
    # atm
    "atm": ("Pa", 101325.0),
}

TEMPERATURE_UNITS = {
    # Kelvin
    "k": ("K", 1.0),
    "kelvin": ("K", 1.0),
    # Celsius (conversion handled specially)
    "c": ("C", 1.0),
    "°c": ("C", 1.0),
    "celsius": ("C", 1.0),
    "deg c": ("C", 1.0),
    "degc": ("C", 1.0),
    # Fahrenheit (conversion handled specially)
    "f": ("F", 1.0),
    "°f": ("F", 1.0),
    "fahrenheit": ("F", 1.0),
    "deg f": ("F", 1.0),
    "degf": ("F", 1.0),
}

STRAIN_RATE_UNITS = {
    "s-1": ("s⁻¹", 1.0),
    "s^-1": ("s⁻¹", 1.0),
    "/s": ("s⁻¹", 1.0),
    "per second": ("s⁻¹", 1.0),
    "1/s": ("s⁻¹", 1.0),
}

PERCENTAGE_UNITS = {
    "%": ("%", 1.0),
    "percent": ("%", 1.0),
    "pct": ("%", 1.0),
}

# Pattern to extract units from header text
UNIT_PATTERN = re.compile(
    r"\(([^)]+)\)|\[([^\]]+)\]|,\s*(\S+)$",
    re.IGNORECASE
)


class UnitDetector:
    """
    Detects and normalizes units from header text.

    Uses semantic tag hints for context-aware parsing.
    """

    def __init__(self) -> None:
        self._all_units: dict[str, tuple[str, float]] = {}
        self._all_units.update(PRESSURE_UNITS)
        self._all_units.update(TEMPERATURE_UNITS)
        self._all_units.update(STRAIN_RATE_UNITS)
        self._all_units.update(PERCENTAGE_UNITS)

    def detect(
        self,
        header_text: str,
        tag_hint: Optional[SemanticTag] = None,
    ) -> Optional[UnitInfo]:
        """
        Detect unit from header text.

        Args:
            header_text: Column header (e.g., "UTS (MPa)")
            tag_hint: Optional semantic tag for context

        Returns:
            UnitInfo if unit found, None otherwise
        """
        if not header_text:
            return None

        # Extract potential unit strings
        matches = UNIT_PATTERN.findall(header_text)
        candidates = []
        for match in matches:
            for group in match:
                if group:
                    candidates.append(group.strip())

        # Try each candidate
        for candidate in candidates:
            unit_info = self._parse_unit(candidate, tag_hint)
            if unit_info:
                return unit_info

        # Fallback: check if entire header is a known unit
        normalized = header_text.lower().strip()
        if normalized in self._all_units:
            canonical, multiplier = self._all_units[normalized]
            return UnitInfo(
                raw=header_text,
                canonical=canonical,
                multiplier=multiplier,
                tag_hint=tag_hint,
            )

        return None

    def _parse_unit(
        self,
        text: str,
        tag_hint: Optional[SemanticTag],
    ) -> Optional[UnitInfo]:
        """Parse a single unit string."""
        normalized = text.lower().strip()

        # Check known units
        if normalized in self._all_units:
            canonical, multiplier = self._all_units[normalized]
            return UnitInfo(
                raw=text,
                canonical=canonical,
                multiplier=multiplier,
                tag_hint=tag_hint,
            )

        # Handle composite units (e.g., "10^-4 s-1")
        rate_match = re.match(r"10\^?(-?\d+)\s*s-?1", normalized)
        if rate_match:
            exp = int(rate_match.group(1))
            return UnitInfo(
                raw=text,
                canonical="s⁻¹",
                multiplier=10 ** exp,
                tag_hint=SemanticTag.TEST_STRAIN_RATE,
            )

        return None

    def normalize_to_si(
        self,
        value: float,
        unit_info: UnitInfo,
    ) -> float:
        """
        Convert value to SI units.

        Note: Temperature conversions require special handling.
        """
        if unit_info.canonical == "C":
            # Celsius to Kelvin
            return value + 273.15
        elif unit_info.canonical == "F":
            # Fahrenheit to Kelvin
            return (value - 32) * 5 / 9 + 273.15
        else:
            return value * unit_info.multiplier
