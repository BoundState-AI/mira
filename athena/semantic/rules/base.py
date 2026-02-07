#!/usr/bin/env python3
"""
Module: Base
Purpose: ATHENA Base Semantic Rules.

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

__all__ = ["EXACT_RULES", "PATTERN_RULES"]
__safety_critical__ = True


# Exact match rules (case-insensitive)
# Maps normalized header text → SemanticTag
EXACT_RULES: dict[str, SemanticTag] = {
    # Material identification
    "material": SemanticTag.MATERIAL_NAME,
    "alloy": SemanticTag.MATERIAL_NAME,
    "material name": SemanticTag.MATERIAL_NAME,
    "alloy name": SemanticTag.MATERIAL_NAME,
    "alloy designation": SemanticTag.MATERIAL_NAME,
    "material/alloy": SemanticTag.MATERIAL_NAME,

    "uns": SemanticTag.MATERIAL_UNS,
    "uns no.": SemanticTag.MATERIAL_UNS,
    "uns number": SemanticTag.MATERIAL_UNS,
    "uns #": SemanticTag.MATERIAL_UNS,

    "specification": SemanticTag.MATERIAL_SPEC,
    "spec": SemanticTag.MATERIAL_SPEC,
    "spec no.": SemanticTag.MATERIAL_SPEC,
    "ams": SemanticTag.MATERIAL_SPEC,
    "astm": SemanticTag.MATERIAL_SPEC,

    "form": SemanticTag.MATERIAL_FORM,
    "product form": SemanticTag.MATERIAL_FORM,
    "product": SemanticTag.MATERIAL_FORM,

    "condition": SemanticTag.MATERIAL_CONDITION,
    "heat treatment": SemanticTag.MATERIAL_CONDITION,
    "temper": SemanticTag.MATERIAL_CONDITION,
    "processing": SemanticTag.MATERIAL_CONDITION,

    # Mechanical properties
    "uts": SemanticTag.PROPERTY_TENSILE,
    "tensile strength": SemanticTag.PROPERTY_TENSILE,
    "ultimate tensile strength": SemanticTag.PROPERTY_TENSILE,
    "σuts": SemanticTag.PROPERTY_TENSILE,

    "ys": SemanticTag.PROPERTY_YIELD,
    "yield strength": SemanticTag.PROPERTY_YIELD,
    "yield stress": SemanticTag.PROPERTY_YIELD,
    "0.2% ys": SemanticTag.PROPERTY_YIELD,
    "0.2% yield": SemanticTag.PROPERTY_YIELD,
    "σy": SemanticTag.PROPERTY_YIELD,

    "elongation": SemanticTag.PROPERTY_ELONGATION,
    "el": SemanticTag.PROPERTY_ELONGATION,
    "el.": SemanticTag.PROPERTY_ELONGATION,
    "% elongation": SemanticTag.PROPERTY_ELONGATION,
    "elong.": SemanticTag.PROPERTY_ELONGATION,

    "ra": SemanticTag.PROPERTY_RA,
    "reduction of area": SemanticTag.PROPERTY_RA,
    "reduction in area": SemanticTag.PROPERTY_RA,
    "% ra": SemanticTag.PROPERTY_RA,
    "ra (%)": SemanticTag.PROPERTY_RA,

    "hardness": SemanticTag.PROPERTY_HARDNESS,
    "hrc": SemanticTag.PROPERTY_HARDNESS,
    "hrb": SemanticTag.PROPERTY_HARDNESS,
    "hv": SemanticTag.PROPERTY_HARDNESS,
    "bhn": SemanticTag.PROPERTY_HARDNESS,

    "modulus": SemanticTag.PROPERTY_MODULUS,
    "elastic modulus": SemanticTag.PROPERTY_MODULUS,
    "young's modulus": SemanticTag.PROPERTY_MODULUS,
    "e": SemanticTag.PROPERTY_MODULUS,

    # Environment
    "pressure": SemanticTag.ENVIRONMENT_PRESSURE,
    "test pressure": SemanticTag.ENVIRONMENT_PRESSURE,
    "gas pressure": SemanticTag.ENVIRONMENT_PRESSURE,
    "p": SemanticTag.ENVIRONMENT_PRESSURE,

    "temperature": SemanticTag.ENVIRONMENT_TEMPERATURE,
    "temp": SemanticTag.ENVIRONMENT_TEMPERATURE,
    "test temperature": SemanticTag.ENVIRONMENT_TEMPERATURE,
    "t": SemanticTag.ENVIRONMENT_TEMPERATURE,

    "environment": SemanticTag.ENVIRONMENT_GAS,
    "gas": SemanticTag.ENVIRONMENT_GAS,
    "atmosphere": SemanticTag.ENVIRONMENT_GAS,

    # Test metadata
    "strain rate": SemanticTag.TEST_STRAIN_RATE,
    "ε̇": SemanticTag.TEST_STRAIN_RATE,

    "specimen": SemanticTag.TEST_SPECIMEN,
    "specimen type": SemanticTag.TEST_SPECIMEN,
    "geometry": SemanticTag.TEST_SPECIMEN,

    "reference": SemanticTag.TEST_REFERENCE,
    "ref": SemanticTag.TEST_REFERENCE,
    "source": SemanticTag.TEST_REFERENCE,
    "citation": SemanticTag.TEST_REFERENCE,

    # Notes
    "notes": SemanticTag.NOTES,
    "remarks": SemanticTag.NOTES,
    "comments": SemanticTag.NOTES,

    # Identifiers
    "no.": SemanticTag.ID_ROW,
    "no": SemanticTag.ID_ROW,
    "#": SemanticTag.ID_ROW,
    "row": SemanticTag.ID_ROW,
    "id": SemanticTag.ID_ROW,

    "sample": SemanticTag.ID_SAMPLE,
    "sample id": SemanticTag.ID_SAMPLE,
    "specimen id": SemanticTag.ID_SAMPLE,
}


# Pattern rules (regex → SemanticTag)
# Checked after exact rules, in order
PATTERN_RULES: list[tuple[re.Pattern, SemanticTag]] = [
    # UTS with unit
    (re.compile(r"uts\s*\(", re.IGNORECASE), SemanticTag.PROPERTY_TENSILE),
    (re.compile(r"tensile.*strength", re.IGNORECASE), SemanticTag.PROPERTY_TENSILE),
    (re.compile(r"σ\s*uts", re.IGNORECASE), SemanticTag.PROPERTY_TENSILE),

    # Yield with unit
    (re.compile(r"yield\s*(?:strength|stress)", re.IGNORECASE), SemanticTag.PROPERTY_YIELD),
    (re.compile(r"ys\s*\(", re.IGNORECASE), SemanticTag.PROPERTY_YIELD),
    (re.compile(r"0\.2%\s*(?:ys|yield)", re.IGNORECASE), SemanticTag.PROPERTY_YIELD),

    # Elongation
    (re.compile(r"elong", re.IGNORECASE), SemanticTag.PROPERTY_ELONGATION),
    (re.compile(r"el\s*\(%\)", re.IGNORECASE), SemanticTag.PROPERTY_ELONGATION),

    # RA variants
    (re.compile(r"r\.?a\.?\s*\(%?\)", re.IGNORECASE), SemanticTag.PROPERTY_RA),
    (re.compile(r"reduction.*area", re.IGNORECASE), SemanticTag.PROPERTY_RA),

    # Pressure with unit
    (re.compile(r"pressure\s*\(", re.IGNORECASE), SemanticTag.ENVIRONMENT_PRESSURE),
    (re.compile(r"p\s*\((?:mpa|psi|bar|ksi)", re.IGNORECASE), SemanticTag.ENVIRONMENT_PRESSURE),

    # Temperature with unit
    (re.compile(r"temp(?:erature)?\s*\(", re.IGNORECASE), SemanticTag.ENVIRONMENT_TEMPERATURE),
    (re.compile(r"t\s*\((?:°?[cfk]|k|celsius|fahrenheit)", re.IGNORECASE), SemanticTag.ENVIRONMENT_TEMPERATURE),

    # Strain rate
    (re.compile(r"strain\s*rate", re.IGNORECASE), SemanticTag.TEST_STRAIN_RATE),
    (re.compile(r"ε̇|έ|dε/dt", re.IGNORECASE), SemanticTag.TEST_STRAIN_RATE),
    (re.compile(r"\(s-?1\)|\(1/s\)", re.IGNORECASE), SemanticTag.TEST_STRAIN_RATE),

    # Material patterns
    (re.compile(r"uns\s*(?:no\.?|number|#)?", re.IGNORECASE), SemanticTag.MATERIAL_UNS),
    (re.compile(r"ams\s*\d+", re.IGNORECASE), SemanticTag.MATERIAL_SPEC),
    (re.compile(r"astm\s*[a-z]?\d+", re.IGNORECASE), SemanticTag.MATERIAL_SPEC),

    # References
    (re.compile(r"ref(?:erence)?\.?\s*(?:\#|no\.?)?", re.IGNORECASE), SemanticTag.TEST_REFERENCE),
]
