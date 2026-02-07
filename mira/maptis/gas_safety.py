#!/usr/bin/env python3
"""
Module: Gas Safety
Purpose: Gas Safety Rules for O2 and H2 Compatibility

BoundState AI 2025
Version: 1.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Fran OpenAI 5 <noreply@openai.com>
Co-Authored-By: Grok 4.0 <noreply@x.ai>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: NASA-CSET, SWE-013, SWE-032
Safety Critical: True
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Dict, Optional, Set

from .repository import MaterialFamily
import uuid


# =============================================================================
# GAS SAFETY RULE DATACLASS
# =============================================================================

@dataclass(frozen=True)
class GasSafetyRule:
    """Immutable rule for gas compatibility.

    Frozen=True ensures rules cannot be modified at runtime.
    """
    classification: str  # "approved", "caution", "prohibited", "unknown"
    reason: str
    bok_ref: str
    notes: Optional[str] = None
    max_pressure_psia: Optional[float] = None
    max_temp_f: Optional[float] = None
    min_temp_f: Optional[float] = None
    embrittlement_risk: Optional[str] = None  # H2-specific
    source: str = ""  # NASA SWE-013 traceability



# =============================================================================
# O2 SAFETY RULES TABLE
# =============================================================================

# Families that are ALWAYS prohibited in O2 service
O2_PROHIBITED_FAMILIES: Set[MaterialFamily] = frozenset({
    MaterialFamily.TITANIUM,   # Promoted combustion risk - NASA-STD-6016 §4.2.6.2
    MaterialFamily.MAGNESIUM,  # Highly flammable - NASA-STD-6016 Table 4-1
})

# Families that are restricted in O2 service (conditional use)
O2_RESTRICTED_FAMILIES: Set[MaterialFamily] = frozenset({
    MaterialFamily.ALUMINUM,        # LOX only, not GOX at elevated pressure
    MaterialFamily.POLYMER_ORGANIC, # Generally prohibited except specific compounds
})

# Pressure limit for aluminum in GOX (psia) - per JSC-27301F §5.1.4
O2_GOX_ALUMINUM_PRESSURE_LIMIT: float = 200.0

O2_RULES: Dict[MaterialFamily, GasSafetyRule] = {
    MaterialFamily.TITANIUM: GasSafetyRule(
        classification="prohibited",
        reason="Titanium alloys are prohibited in O2 service - promoted combustion risk",
        bok_ref="NASA-STD-6016 §4.2.6.2, NASA/TM-2007-213740",
    ),
    MaterialFamily.MAGNESIUM: GasSafetyRule(
        classification="prohibited",
        reason="Magnesium alloys are prohibited in O2 service - highly flammable",
        bok_ref="NASA-STD-6016 Table 4-1",
    ),
    MaterialFamily.ALUMINUM: GasSafetyRule(
        classification="restricted",
        reason="Aluminum alloys limited to LOX (cryogenic) service only, NOT GOX at elevated pressure",
        bok_ref="NASA-STD-6016 §4.2.6.3, JSC-27301F §5.1.4",
        max_pressure_psia=O2_GOX_ALUMINUM_PRESSURE_LIMIT,  # GOX limit
        max_temp_f=-200,  # Cryo only for LOX
        notes="GOX prohibited above 200 psia; LOX acceptable at cryogenic temps",
    ),
    MaterialFamily.NICKEL_ALLOY: GasSafetyRule(
        classification="approved",
        reason="Nickel alloys (Inconel, Monel, Hastelloy) are preferred for high-pressure O2 service",
        bok_ref="NASA-STD-6016 Table 4-1",
        max_pressure_psia=10000,
    ),
    MaterialFamily.AUSTENITIC_STEEL: GasSafetyRule(
        classification="approved_with_caution",
        reason="300-series austenitic stainless steels are acceptable with precision cleaning",
        bok_ref="NASA-STD-6016 Table 4-1",
        max_pressure_psia=3000,
        notes="Precision cleaning required above 1000 psi",
    ),
    MaterialFamily.COPPER: GasSafetyRule(
        classification="approved",
        reason="Copper and copper alloys are excellent for O2 service",
        bok_ref="NASA-STD-6016 Table 4-1",
        max_pressure_psia=5000,
    ),
    MaterialFamily.POLYMER_FLUORINATED: GasSafetyRule(
        classification="restricted",
        reason="PTFE/Teflon limited to static seals, no flow",
        bok_ref="NASA-STD-6016 Table 4-1",
        max_pressure_psia=3000,
        notes="Static seals only; no flow applications",
    ),
    MaterialFamily.UNKNOWN: GasSafetyRule(
        classification="unknown",
        reason="Material family not identified - engineering evaluation required",
        bok_ref="NASA-STD-6001B Test 1",
    ),
}


# =============================================================================
# H2 SAFETY RULES TABLE
# =============================================================================

# Families approved for H2 service (low/no HE risk)
H2_APPROVED_FAMILIES: Set[MaterialFamily] = frozenset({
    MaterialFamily.AUSTENITIC_STEEL,  # 304, 316, 321 - FCC structure resists HE
    MaterialFamily.NICKEL_ALLOY,      # Inconel, Monel, Hastelloy - best for H2
    MaterialFamily.COPPER,            # No HE, low permeation
    MaterialFamily.ALUMINUM,          # No HE (unlike O2, Al is good for H2)
})

# Families requiring caution in H2 service
H2_CAUTION_FAMILIES: Set[MaterialFamily] = frozenset({
    MaterialFamily.TITANIUM,          # Hydride formation at elevated temps
    MaterialFamily.POLYMER_FLUORINATED,  # Permeation concerns
    MaterialFamily.MAGNESIUM,         # Hydride formation possible
})

# H2 embrittlement thresholds - per NSS 1740.16
H2_HIGH_STRENGTH_THRESHOLD_KSI: float = 150.0  # Materials >150 ksi are HE-susceptible
H2_PRESSURE_THRESHOLD_PSIA: float = 1000.0     # HE risk increases above this
H2_TITANIUM_MAX_TEMP_F: float = 300.0          # Ti forms hydrides above this

H2_RULES: Dict[MaterialFamily, GasSafetyRule] = {
    MaterialFamily.AUSTENITIC_STEEL: GasSafetyRule(
        classification="approved",
        reason="300-series austenitic stainless steels have excellent H2 resistance due to FCC structure",
        bok_ref="NSS 1740.16 Table A5.2, SAND2012_7321 §3.2",
        embrittlement_risk="low",
        max_pressure_psia=15000,
        notes="Preferred for H2 service up to 15,000 psi",
    ),
    MaterialFamily.NICKEL_ALLOY: GasSafetyRule(
        classification="approved",
        reason="Nickel alloys (Inconel, Monel, Hastelloy) are optimal for high-pressure H2 service",
        bok_ref="NSS 1740.16 Table A5.2, SAND2012_7321 §3.3",
        embrittlement_risk="very_low",
        notes="Best choice for H2 pressures above 10,000 psi",
    ),
    MaterialFamily.COPPER: GasSafetyRule(
        classification="approved",
        reason="Copper and copper alloys have very low H2 permeation and no HE",
        bok_ref="NSS 1740.16 Table A5.2",
        embrittlement_risk="very_low",
    ),
    MaterialFamily.ALUMINUM: GasSafetyRule(
        classification="approved",
        reason="Aluminum alloys do not suffer hydrogen embrittlement (HE not a concern for Al)",
        bok_ref="SAND2012_7321 §3.4",
        embrittlement_risk="none",
        notes="Good for cryogenic LH2; permeation may be concern at elevated temps",
    ),
    MaterialFamily.TITANIUM: GasSafetyRule(
        classification="caution",
        reason="Titanium can absorb hydrogen at elevated temperatures (>300°F), forming brittle hydrides",
        bok_ref="NSS 1740.16 §4.5, SAND2012_7321 §3.5",
        embrittlement_risk="medium",
        max_temp_f=H2_TITANIUM_MAX_TEMP_F,
        notes="Acceptable for cryogenic LH2; avoid elevated temps with GH2",
    ),
    MaterialFamily.MAGNESIUM: GasSafetyRule(
        classification="caution",
        reason="Magnesium forms hydrides but has been used in some H2 applications",
        bok_ref="SAND2012_7321 §3.6",
        embrittlement_risk="medium",
        notes="Engineering evaluation required; not common for H2 service",
    ),
    MaterialFamily.POLYMER_FLUORINATED: GasSafetyRule(
        classification="caution",
        reason="PTFE and fluoropolymers have H2 permeation concerns at elevated pressure",
        bok_ref="NSS 1740.16 §5.2",
        embrittlement_risk="n/a",
        notes="Acceptable for seals with proper backup",
    ),
    MaterialFamily.POLYMER_ORGANIC: GasSafetyRule(
        classification="caution",
        reason="Organic polymers may have permeation and compatibility issues",
        bok_ref="NSS 1740.16 §5.2",
        embrittlement_risk="n/a",
        notes="Requires permeation testing; elastomers may swell",
    ),
    MaterialFamily.UNKNOWN: GasSafetyRule(
        classification="unknown",
        reason="Material family not identified - engineering evaluation required per NSS 1740.16",
        bok_ref="NSS 1740.16 Test 19 (H2 embrittlement test)",
        embrittlement_risk="unknown",
    ),
}


# =============================================================================
# LOOKUP HELPERS
# =============================================================================

def get_o2_rule(family: MaterialFamily) -> GasSafetyRule:
    """Get O2 safety rule for a material family."""
    return O2_RULES.get(family, O2_RULES[MaterialFamily.UNKNOWN])


def get_h2_rule(family: MaterialFamily) -> GasSafetyRule:
    """Get H2 safety rule for a material family."""
    return H2_RULES.get(family, H2_RULES[MaterialFamily.UNKNOWN])


def is_o2_prohibited(family: MaterialFamily) -> bool:
    """Check if a material family is prohibited in O2 service."""
    return family in O2_PROHIBITED_FAMILIES


def is_o2_restricted(family: MaterialFamily) -> bool:
    """Check if a material family is restricted in O2 service."""
    return family in O2_RESTRICTED_FAMILIES


def is_h2_approved(family: MaterialFamily) -> bool:
    """Check if a material family is approved for H2 service."""
    return family in H2_APPROVED_FAMILIES


def is_h2_caution(family: MaterialFamily) -> bool:
    """Check if a material family requires caution in H2 service."""
    return family in H2_CAUTION_FAMILIES


__all__ = [
    # Dataclass
    "GasSafetyRule",
    # O2 exports
    "O2_PROHIBITED_FAMILIES",
    "O2_RESTRICTED_FAMILIES",
    "O2_GOX_ALUMINUM_PRESSURE_LIMIT",
    "O2_RULES",
    "get_o2_rule",
    "is_o2_prohibited",
    "is_o2_restricted",
    # H2 exports
    "H2_APPROVED_FAMILIES",
    "H2_CAUTION_FAMILIES",
    "H2_HIGH_STRENGTH_THRESHOLD_KSI",
    "H2_PRESSURE_THRESHOLD_PSIA",
    "H2_TITANIUM_MAX_TEMP_F",
    "H2_RULES",
    "get_h2_rule",
    "is_h2_approved",
    "is_h2_caution",
]
