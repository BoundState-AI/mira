#!/usr/bin/env python3
"""
Module: Materials
Purpose: ATHENA Material Resolver.

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

__all__ = ["MaterialResolver", "MaterialMatch"]
__safety_critical__ = True


@dataclass
class MaterialMatch:
    """Result of material resolution."""
    raw_name: str
    canonical_name: Optional[str] = None
    uns_number: Optional[str] = None
    spec_number: Optional[str] = None
    material_family: Optional[str] = None
    confidence: float = 0.0


# Common material name patterns
UNS_PATTERN = re.compile(r"\b([A-Z]\d{5})\b")
AMS_PATTERN = re.compile(r"\bAMS\s*(\d{4}[A-Z]?)\b", re.IGNORECASE)
ASTM_PATTERN = re.compile(r"\bASTM\s*([A-Z]?\d+(?:-\d+)?)\b", re.IGNORECASE)
SAE_PATTERN = re.compile(r"\bSAE\s*(\d{4,5})\b", re.IGNORECASE)

# Material family detection patterns
FAMILY_PATTERNS = {
    "stainless_steel": [
        re.compile(r"\b(?:stainless|SS)\s*(?:steel)?\b", re.IGNORECASE),
        re.compile(r"\b(?:304|316|321|347|410|420|430|17-4|17-7|15-5|13-8|A286)\b"),
    ],
    "nickel_alloy": [
        re.compile(r"\b(?:inconel|inco|hastelloy|monel|waspaloy|rene)\b", re.IGNORECASE),
        re.compile(r"\b(?:alloy\s*)?(?:625|718|725|X-750|C-276)\b", re.IGNORECASE),
    ],
    "titanium_alloy": [
        re.compile(r"\b(?:titanium|Ti)\s*(?:alloy)?\b", re.IGNORECASE),
        re.compile(r"\bTi[-\s]?(?:6Al[-\s]?4V|6-4|5Al|3Al)\b", re.IGNORECASE),
    ],
    "aluminum_alloy": [
        re.compile(r"\b(?:aluminum|aluminium|Al)\s*(?:alloy)?\b", re.IGNORECASE),
        re.compile(r"\b(?:2024|6061|7075|2219)\b"),
    ],
    "copper_alloy": [
        re.compile(r"\b(?:copper|Cu|bronze|brass)\b", re.IGNORECASE),
        re.compile(r"\bC\d{5}\b"),  # CDA numbers
    ],
    "carbon_steel": [
        re.compile(r"\b(?:carbon\s+steel|low\s+alloy)\b", re.IGNORECASE),
        re.compile(r"\b(?:1018|1020|1045|4130|4140|4340)\b"),
    ],
}

# Common name normalizations
NORMALIZATION_MAP = {
    # Stainless steels
    "304l": "304L",
    "304 l": "304L",
    "ss304": "304",
    "ss 304": "304",
    "316l": "316L",
    "ss316": "316",
    "17-4 ph": "17-4PH",
    "17-4ph": "17-4PH",
    "174ph": "17-4PH",
    "15-5 ph": "15-5PH",
    "15-5ph": "15-5PH",
    "a-286": "A286",
    "a286": "A286",

    # Nickel alloys
    "inconel 625": "Inconel 625",
    "in625": "Inconel 625",
    "alloy 625": "Inconel 625",
    "inconel 718": "Inconel 718",
    "in718": "Inconel 718",
    "alloy 718": "Inconel 718",
    "inconel x-750": "Inconel X-750",
    "x750": "Inconel X-750",
    "hastelloy c-276": "Hastelloy C-276",
    "c276": "Hastelloy C-276",
    "monel 400": "Monel 400",
    "monel k-500": "Monel K-500",

    # Titanium
    "ti-6al-4v": "Ti-6Al-4V",
    "ti6al4v": "Ti-6Al-4V",
    "ti 6-4": "Ti-6Al-4V",
    "ti64": "Ti-6Al-4V",

    # Aluminum
    "al 2024": "2024",
    "al2024": "2024",
    "al 6061": "6061",
    "al 7075": "7075",
}


class MaterialResolver:
    """
    Resolves and canonicalizes material names.

    Extracts:
    - UNS numbers (e.g., S17400)
    - Spec numbers (e.g., AMS 5643)
    - Material family classification
    - Canonical material name
    """

    def __init__(self) -> None:
        pass

    def resolve(self, text: str) -> MaterialMatch:
        """
        Resolve material name to canonical form.

        Args:
            text: Raw material name/description

        Returns:
            MaterialMatch with extracted information
        """
        if not text:
            return MaterialMatch(raw_name=text, confidence=0.0)

        text = text.strip()
        match = MaterialMatch(raw_name=text)

        # Extract UNS number
        uns_match = UNS_PATTERN.search(text)
        if uns_match:
            match.uns_number = uns_match.group(1)
            match.confidence += 0.3

        # Extract spec numbers
        for pattern, prefix in [
            (AMS_PATTERN, "AMS"),
            (ASTM_PATTERN, "ASTM"),
            (SAE_PATTERN, "SAE"),
        ]:
            spec_match = pattern.search(text)
            if spec_match:
                match.spec_number = f"{prefix} {spec_match.group(1)}"
                match.confidence += 0.2
                break

        # Detect material family
        for family, patterns in FAMILY_PATTERNS.items():
            for pattern in patterns:
                if pattern.search(text):
                    match.material_family = family
                    match.confidence += 0.2
                    break
            if match.material_family:
                break

        # Try canonical name normalization
        normalized = text.lower().strip()
        for key, canonical in NORMALIZATION_MAP.items():
            if key in normalized:
                match.canonical_name = canonical
                match.confidence += 0.3
                break

        # If no canonical name found, use cleaned version
        if not match.canonical_name:
            match.canonical_name = self._clean_name(text)

        # Cap confidence at 1.0
        match.confidence = min(1.0, match.confidence)

        return match

    def _clean_name(self, text: str) -> str:
        """Clean and normalize material name."""
        # Remove extra whitespace
        cleaned = re.sub(r"\s+", " ", text.strip())

        # Uppercase known alloy designations
        for pattern in [r"\b(\d{3,4}[A-Za-z]?)\b", r"\b([A-Z]\d{5})\b"]:
            cleaned = re.sub(
                pattern,
                lambda m: m.group(1).upper(),
                cleaned
            )

        return cleaned

    def extract_uns(self, text: str) -> Optional[str]:
        """Extract UNS number if present."""
        match = UNS_PATTERN.search(text)
        return match.group(1) if match else None

    def extract_spec(self, text: str) -> Optional[str]:
        """Extract specification number if present."""
        for pattern, prefix in [
            (AMS_PATTERN, "AMS"),
            (ASTM_PATTERN, "ASTM"),
            (SAE_PATTERN, "SAE"),
        ]:
            match = pattern.search(text)
            if match:
                return f"{prefix} {match.group(1)}"
        return None
