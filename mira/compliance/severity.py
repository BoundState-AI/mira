#!/usr/bin/env python3
"""
Module: Severity Mapping
Purpose: Deterministic HEE band to severity mapping

BoundState AI 2025
Version: 2.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Fran OpenAI 5 <noreply@openai.com>
Co-Authored-By: Grok 4.0 <noreply@x.ai>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: NASA-STD-8739.8B, SWE-013, SWE-033
Safety Critical: True
"""

# Copyright © 2025 BoundState AI. All Rights Reserved.
# Classification: BoundState Proprietary
# License: Evaluation Use Only - Authorized Pilot Program
"""
NASA-STD-6016C Compliance Module - Severity Mapping

Deterministic HEE band to severity mapping.

Fran Fix #4: Removes dependence on human text in driver.severity.
This is the ONLY place severity is derived from HEE band.

Reference: NASA/TM-2016-218602 (Hydrogen Embrittlement)

Compliance: NASA-STD-8739.8B, SWE-013, SWE-033

Author: BoundState Team
Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Fran OpenAI <noreply@openai.com>
Co-Authored-By: Grok <noreply@x.ai>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI
"""

__version__ = "2.0.0"
__safety_critical__ = True

from typing import Optional

from mira.compliance.models.enums import GapSeverity, GapTrigger


# Deterministic mapping from HEE band to severity
# Based on NASA/TM-2016-218602 classification
HEE_BAND_SEVERITY_MAP: dict[str, GapSeverity] = {
    "extreme": GapSeverity.CRITICAL,
    "severe": GapSeverity.CRITICAL,
    "high": GapSeverity.HIGH,
    "small": GapSeverity.MEDIUM,
    "negligible": GapSeverity.LOW,
}

# Mapping from HEE band to gap trigger
HEE_BAND_TRIGGER_MAP: dict[str, GapTrigger] = {
    "extreme": GapTrigger.HEE_BAND_EXTREME,
    "severe": GapTrigger.HEE_BAND_SEVERE,
    "high": GapTrigger.HEE_BAND_HIGH,
    "small": GapTrigger.RATING_NON_A,
    "negligible": GapTrigger.RATING_NON_A,
}


def quantize_hee_severity(hee_band: Optional[str]) -> GapSeverity:
    """
    Convert HEE band to deterministic severity.

    This is the ONLY place severity is derived from HEE band.
    Driver.severity (human text) is ignored in favor of this.

    Fran Fix #4: Deterministic mapping ensures reproducibility.

    Args:
        hee_band: HEE band string (extreme, severe, high, small, negligible)

    Returns:
        GapSeverity enum value. Defaults to HIGH if band is unknown.
    """
    if not hee_band:
        return GapSeverity.HIGH  # Conservative default

    return HEE_BAND_SEVERITY_MAP.get(hee_band.lower(), GapSeverity.HIGH)


def hee_band_to_trigger(hee_band: Optional[str]) -> GapTrigger:
    """
    Convert HEE band to appropriate gap trigger.

    Args:
        hee_band: HEE band string (extreme, severe, high, small, negligible)

    Returns:
        GapTrigger enum value.
    """
    if not hee_band:
        return GapTrigger.RATING_NON_A

    return HEE_BAND_TRIGGER_MAP.get(hee_band.lower(), GapTrigger.RATING_NON_A)


def is_critical_hee_band(hee_band: Optional[str]) -> bool:
    """
    Check if HEE band indicates critical severity.

    Args:
        hee_band: HEE band string

    Returns:
        True if band is extreme or severe.
    """
    if not hee_band:
        return False

    return hee_band.lower() in {"extreme", "severe"}


def requires_mua_for_hee_band(hee_band: Optional[str]) -> bool:
    """
    Check if HEE band requires MUA generation.

    Args:
        hee_band: HEE band string

    Returns:
        True if band is high, severe, or extreme.
    """
    if not hee_band:
        return True  # Conservative: unknown requires MUA

    return hee_band.lower() in {"extreme", "severe", "high"}


# Numeric thresholds for HEE band classification
# Based on ductility ratio (property in H2 / property in air)
HEE_BAND_THRESHOLDS = {
    "negligible": (0.97, 1.00),
    "small": (0.90, 0.97),
    "high": (0.70, 0.90),
    "severe": (0.50, 0.70),
    "extreme": (0.00, 0.50),
}


def classify_hee_band_from_ratio(ductility_ratio: float) -> str:
    """
    Classify HEE band from ductility ratio.

    Used when computing HEE band from raw test data.

    Args:
        ductility_ratio: Ratio of ductility in H2 to ductility in air (0.0-1.0+)

    Returns:
        HEE band string (negligible, small, high, severe, extreme)
    """
    # Clamp ratio to valid range
    ratio = max(0.0, min(1.0, ductility_ratio))

    for band, (low, high) in HEE_BAND_THRESHOLDS.items():
        if low <= ratio < high:
            return band

    # Edge case: ratio >= 1.0 means no embrittlement
    if ductility_ratio >= 1.0:
        return "negligible"

    return "extreme"  # ratio < 0 (shouldn't happen)
