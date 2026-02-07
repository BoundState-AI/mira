#!/usr/bin/env python3
"""
Module: Composition
Purpose: ATHENA Composition Rules.

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
from athena.semantic.ontology import SemanticTag

__all__ = ["COMPOSITION_RULES", "ELEMENT_SYMBOLS"]
__safety_critical__ = True


# Chemical element symbols that might appear as headers
ELEMENT_SYMBOLS = {
    "c", "carbon",
    "mn", "manganese",
    "si", "silicon",
    "p", "phosphorus",
    "s", "sulfur", "sulphur",
    "cr", "chromium",
    "ni", "nickel",
    "mo", "molybdenum",
    "v", "vanadium",
    "w", "tungsten",
    "co", "cobalt",
    "cu", "copper",
    "al", "aluminum", "aluminium",
    "ti", "titanium",
    "nb", "niobium", "columbium",
    "ta", "tantalum",
    "zr", "zirconium",
    "b", "boron",
    "n", "nitrogen",
    "fe", "iron",
    "o", "oxygen",
    "h", "hydrogen",
    "sn", "tin",
    "pb", "lead",
    "zn", "zinc",
    "mg", "magnesium",
    "ca", "calcium",
    "se", "selenium",
    "ag", "silver",
    "au", "gold",
    "pt", "platinum",
    "pd", "palladium",
    "rh", "rhodium",
    "ru", "ruthenium",
    "ir", "iridium",
    "os", "osmium",
    "re", "rhenium",
    "hf", "hafnium",
    "la", "lanthanum",
    "ce", "cerium",
    "y", "yttrium",
}


# Composition-specific rules
COMPOSITION_RULES: list[tuple[re.Pattern, SemanticTag]] = [
    # Element with percentage
    (re.compile(r"(?:^|\s)(c|mn|si|cr|ni|mo|v|w|co|cu|al|ti|nb|ta|zr|b|n|fe|s|p)\s*\(%?\)?\s*$", re.IGNORECASE),
     SemanticTag.COMPOSITION_ELEMENT),

    # Element name
    (re.compile(r"(?:^|\s)(carbon|manganese|silicon|chromium|nickel|molybdenum|vanadium|tungsten)\s*$", re.IGNORECASE),
     SemanticTag.COMPOSITION_ELEMENT),

    # Range patterns
    (re.compile(r"(?:min|max)\s*(?:c|mn|si|cr|ni|mo)", re.IGNORECASE), SemanticTag.COMPOSITION_RANGE),
    (re.compile(r"(?:c|mn|si|cr|ni|mo)\s*(?:min|max)", re.IGNORECASE), SemanticTag.COMPOSITION_RANGE),

    # Composition header
    (re.compile(r"composition", re.IGNORECASE), SemanticTag.COMPOSITION_ELEMENT),
    (re.compile(r"chemical\s*analysis", re.IGNORECASE), SemanticTag.COMPOSITION_ELEMENT),

    # wt% pattern
    (re.compile(r"wt\s*%", re.IGNORECASE), SemanticTag.COMPOSITION_ELEMENT),
    (re.compile(r"weight\s*%", re.IGNORECASE), SemanticTag.COMPOSITION_ELEMENT),
]


def is_element_header(text: str) -> bool:
    """Check if text looks like a chemical element header."""
    normalized = text.lower().strip()

    # Direct match
    if normalized in ELEMENT_SYMBOLS:
        return True

    # Element with parenthetical
    match = re.match(r"^(\w+)\s*\(", normalized)
    if match and match.group(1) in ELEMENT_SYMBOLS:
        return True

    return False
