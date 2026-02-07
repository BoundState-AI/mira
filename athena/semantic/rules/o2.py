#!/usr/bin/env python3
"""
Module: O2
Purpose: ATHENA O2-Specific Semantic Rules.

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

__all__ = ["O2_EXACT_RULES", "O2_PATTERN_RULES"]
__safety_critical__ = True


# O2-specific exact matches
O2_EXACT_RULES: dict[str, SemanticTag] = {
    # O2 environment
    "o2 pressure": SemanticTag.ENVIRONMENT_PRESSURE,
    "oxygen pressure": SemanticTag.ENVIRONMENT_PRESSURE,
    "lox": SemanticTag.ENVIRONMENT_GAS,
    "gox": SemanticTag.ENVIRONMENT_GAS,
    "liquid oxygen": SemanticTag.ENVIRONMENT_GAS,
    "gaseous oxygen": SemanticTag.ENVIRONMENT_GAS,

    # Flammability/ignition
    "ait": SemanticTag.ENVIRONMENT_TEMPERATURE,  # Auto-ignition temperature
    "ignition temperature": SemanticTag.ENVIRONMENT_TEMPERATURE,
    "auto-ignition temperature": SemanticTag.ENVIRONMENT_TEMPERATURE,

    # Promoted ignition
    "pic": SemanticTag.TEST_TYPE,  # Promoted ignition combustion
    "promoted ignition": SemanticTag.TEST_TYPE,
    "promoted combustion": SemanticTag.TEST_TYPE,

    # Compatibility ratings
    "compatibility": SemanticTag.COMPATIBILITY_CLASS,
    "compatibility rating": SemanticTag.COMPATIBILITY_CLASS,
    "o2 compatibility": SemanticTag.COMPATIBILITY_CLASS,
    "oxygen compatibility": SemanticTag.COMPATIBILITY_CLASS,

    # Test types
    "odi": SemanticTag.TEST_TYPE,  # Oxygen drop impact
    "mdi": SemanticTag.TEST_TYPE,  # Mechanical drop impact
    "friction": SemanticTag.TEST_TYPE,
    "particle impact": SemanticTag.TEST_TYPE,
    "pneumatic impact": SemanticTag.TEST_TYPE,

    # Properties
    "heat of combustion": SemanticTag.PROPERTY_IMPACT,
    "burn rate": SemanticTag.PROPERTY_IMPACT,
    "regression rate": SemanticTag.PROPERTY_IMPACT,
}


# O2-specific pattern rules
O2_PATTERN_RULES: list[tuple[re.Pattern, SemanticTag]] = [
    # O2/oxygen pressure patterns
    (re.compile(r"(?:o2|oxygen)\s*pressure", re.IGNORECASE), SemanticTag.ENVIRONMENT_PRESSURE),
    (re.compile(r"p\s*\(\s*(?:o2|oxygen)\s*\)", re.IGNORECASE), SemanticTag.ENVIRONMENT_PRESSURE),

    # LOX/GOX patterns
    (re.compile(r"\blox\b", re.IGNORECASE), SemanticTag.ENVIRONMENT_GAS),
    (re.compile(r"\bgox\b", re.IGNORECASE), SemanticTag.ENVIRONMENT_GAS),
    (re.compile(r"liquid\s*(?:o2|oxygen)", re.IGNORECASE), SemanticTag.ENVIRONMENT_GAS),
    (re.compile(r"gaseous\s*(?:o2|oxygen)", re.IGNORECASE), SemanticTag.ENVIRONMENT_GAS),

    # Ignition patterns
    (re.compile(r"ignit", re.IGNORECASE), SemanticTag.ENVIRONMENT_TEMPERATURE),
    (re.compile(r"ait\b", re.IGNORECASE), SemanticTag.ENVIRONMENT_TEMPERATURE),
    (re.compile(r"auto[-\s]?ignition", re.IGNORECASE), SemanticTag.ENVIRONMENT_TEMPERATURE),

    # Test type patterns
    (re.compile(r"promoted\s*(?:ignition|combustion)", re.IGNORECASE), SemanticTag.TEST_TYPE),
    (re.compile(r"pic\b", re.IGNORECASE), SemanticTag.TEST_TYPE),
    (re.compile(r"(?:odi|mdi)\b", re.IGNORECASE), SemanticTag.TEST_TYPE),
    (re.compile(r"drop\s*impact", re.IGNORECASE), SemanticTag.TEST_TYPE),
    (re.compile(r"friction\s*test", re.IGNORECASE), SemanticTag.TEST_TYPE),
    (re.compile(r"particle\s*impact", re.IGNORECASE), SemanticTag.TEST_TYPE),

    # Compatibility patterns
    (re.compile(r"compat(?:ibility)?", re.IGNORECASE), SemanticTag.COMPATIBILITY_CLASS),
    (re.compile(r"rating", re.IGNORECASE), SemanticTag.COMPATIBILITY_CLASS),

    # Combustion patterns
    (re.compile(r"combust", re.IGNORECASE), SemanticTag.PROPERTY_IMPACT),
    (re.compile(r"burn\s*rate", re.IGNORECASE), SemanticTag.PROPERTY_IMPACT),
    (re.compile(r"regress", re.IGNORECASE), SemanticTag.PROPERTY_IMPACT),
]
