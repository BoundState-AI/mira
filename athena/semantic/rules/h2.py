#!/usr/bin/env python3
"""
Module: H2
Purpose: ATHENA H2-Specific Semantic Rules.

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

__all__ = ["H2_EXACT_RULES", "H2_PATTERN_RULES"]
__safety_critical__ = True


# H2-specific exact matches
H2_EXACT_RULES: dict[str, SemanticTag] = {
    # H2 environment properties
    "h2 pressure": SemanticTag.ENVIRONMENT_PRESSURE,
    "hydrogen pressure": SemanticTag.ENVIRONMENT_PRESSURE,

    # H2-specific RA measurements
    "ra in h2": SemanticTag.PROPERTY_RA,
    "ra in he": SemanticTag.PROPERTY_RA,
    "ra in air": SemanticTag.PROPERTY_RA,
    "ra(h2)": SemanticTag.PROPERTY_RA,
    "ra(he)": SemanticTag.PROPERTY_RA,

    # Embrittlement index
    "embrittlement index": SemanticTag.PROPERTY_EMBRITTLEMENT_INDEX,
    "hei": SemanticTag.PROPERTY_EMBRITTLEMENT_INDEX,
    "hydrogen embrittlement index": SemanticTag.PROPERTY_EMBRITTLEMENT_INDEX,
    "i(h2)": SemanticTag.PROPERTY_EMBRITTLEMENT_INDEX,

    # Ratios
    "ra ratio": SemanticTag.PROPERTY_RATIO,
    "ra(h2)/ra(he)": SemanticTag.PROPERTY_RATIO,
    "ra h2/he": SemanticTag.PROPERTY_RATIO,
    "nts ratio": SemanticTag.PROPERTY_RATIO,
    "nts(h2)/nts(air)": SemanticTag.PROPERTY_RATIO,

    # SSRT test type
    "ssrt": SemanticTag.TEST_TYPE,
    "slow strain rate": SemanticTag.TEST_TYPE,

    # Notched tensile
    "nts": SemanticTag.PROPERTY_TENSILE,
    "notched tensile strength": SemanticTag.PROPERTY_TENSILE,
    "notch strength": SemanticTag.PROPERTY_TENSILE,
}


# H2-specific pattern rules
H2_PATTERN_RULES: list[tuple[re.Pattern, SemanticTag]] = [
    # RA in various environments
    (re.compile(r"ra\s*(?:in\s*)?(?:h2|hydrogen)", re.IGNORECASE), SemanticTag.PROPERTY_RA),
    (re.compile(r"ra\s*(?:in\s*)?(?:he|helium)", re.IGNORECASE), SemanticTag.PROPERTY_RA),
    (re.compile(r"ra\s*(?:in\s*)?air", re.IGNORECASE), SemanticTag.PROPERTY_RA),
    (re.compile(r"ra\s*\(\s*(?:h2|he|air)\s*\)", re.IGNORECASE), SemanticTag.PROPERTY_RA),

    # Embrittlement patterns
    (re.compile(r"embrit", re.IGNORECASE), SemanticTag.PROPERTY_EMBRITTLEMENT_INDEX),
    (re.compile(r"hei\b", re.IGNORECASE), SemanticTag.PROPERTY_EMBRITTLEMENT_INDEX),
    (re.compile(r"i\s*\(\s*h2\s*\)", re.IGNORECASE), SemanticTag.PROPERTY_EMBRITTLEMENT_INDEX),

    # Ratio patterns
    (re.compile(r"ra.*h2.*(?:/|÷).*(?:he|air)", re.IGNORECASE), SemanticTag.PROPERTY_RATIO),
    (re.compile(r"nts.*h2.*(?:/|÷).*air", re.IGNORECASE), SemanticTag.PROPERTY_RATIO),
    (re.compile(r"ratio", re.IGNORECASE), SemanticTag.PROPERTY_RATIO),

    # H2 pressure patterns
    (re.compile(r"(?:h2|hydrogen)\s*pressure", re.IGNORECASE), SemanticTag.ENVIRONMENT_PRESSURE),
    (re.compile(r"p\s*\(\s*(?:h2|hydrogen)\s*\)", re.IGNORECASE), SemanticTag.ENVIRONMENT_PRESSURE),

    # SSRT patterns
    (re.compile(r"ssrt", re.IGNORECASE), SemanticTag.TEST_TYPE),
    (re.compile(r"slow\s*strain\s*rate", re.IGNORECASE), SemanticTag.TEST_TYPE),

    # NTS patterns
    (re.compile(r"nts\s*\(", re.IGNORECASE), SemanticTag.PROPERTY_TENSILE),
    (re.compile(r"notch(?:ed)?\s*tensile", re.IGNORECASE), SemanticTag.PROPERTY_TENSILE),
]
