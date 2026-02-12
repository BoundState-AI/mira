#!/usr/bin/env python3
"""
Module: Alloy Normalizer
Purpose: Alloy Designation Normalizer - UNS-based deterministic material identification.

BoundState AI 2025
Version: 1.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Fran OpenAI 5 <noreply@openai.com>
Co-Authored-By: Grok 4.0 <noreply@x.ai>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: SWE-032 (Data validation), SWE-033 (Requirements Traceability)
Safety Critical: True
"""

from __future__ import annotations
"""
Alloy Designation Normalizer - UNS-based deterministic material identification.

Converts messy MAPTIS designations, trade names, and variant spellings to
canonical UNS (Unified Numbering System) codes for deterministic lookup.

Copyright (c) 2025 BoundState Inc. All Rights Reserved.
Classification: BoundState Proprietary

Author: Dr. Joseph N. Wilde, Founder, BoundState Inc.
Created: 2025-02-XX
Equipment: Personal hardware, personal funding, personal API accounts

Development tools: Claude (Anthropic), Fran ChatGPT (OpenAI), Grok (xAI)

Compliance: SWE-032 (Data validation), SWE-033 (Requirements Traceability)
Safety Critical: True (Material identification affects safety decisions)
"""

__version__ = "1.0.0"
__safety_critical__ = True

import logging
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional
import uuid

logger = logging.getLogger(__name__)

__all__ = [
    "AlloyFamily",
    "NormalizedAlloy",
    "AlloyNormalizer",
    "normalize_alloy",
]


class AlloyFamily(str, Enum):
    """Material family classification per UNS groupings."""
    ALUMINUM = "aluminum"
    STAINLESS_STEEL = "stainless_steel"
    CARBON_STEEL = "carbon_steel"
    TITANIUM = "titanium"
    NICKEL = "nickel"
    COPPER = "copper"
    MAGNESIUM = "magnesium"
    COBALT = "cobalt"
    REFRACTORY = "refractory"
    UNKNOWN = "unknown"


@dataclass
class NormalizedAlloy:
    """Result of alloy normalization with full traceability.

    Compliance: SWE-033 (Traceability - original input preserved)
    """
    original_input: str
    uns: Optional[str] = None
    canonical_name: str = ""
    family: AlloyFamily = AlloyFamily.UNKNOWN
    base_alloy: str = ""
    temper: Optional[str] = None
    condition: Optional[str] = None
    confidence: float = 0.0
    match_method: str = "none"
    warnings: list[str] = field(default_factory=list)
    source: str = ""  # NASA SWE-013 traceability


    @property
    def is_resolved(self) -> bool:
        """True if UNS was successfully resolved."""
        return self.uns is not None and self.confidence >= 0.7


# =============================================================================
# REGEX PATTERNS - Ordered by specificity (most specific first)
# =============================================================================

PATTERNS = {
    # -------------------------------------------------------------------------
    # ALUMINUM (Axxxx UNS, 4-digit alloy + temper)
    # -------------------------------------------------------------------------
    "aluminum_full": re.compile(
        r"""
        (?:AL(?:UMINUM|UMINIUM)?[\s\-]?)?  # Optional prefix
        (?:ALLOY[\s\-]?)?                   # Optional "Alloy"
        (?P<alloy>[1-8]\d{3})               # 4-digit alloy (1xxx-8xxx)
        (?:[\s\-]?(?P<temper>[OFHW]\d*|T\d{1,4}))?  # Temper
        """,
        re.IGNORECASE | re.VERBOSE
    ),

    # -------------------------------------------------------------------------
    # STAINLESS STEEL - 300/400 series + PH grades
    # -------------------------------------------------------------------------
    "stainless_300_400": re.compile(
        r"""
        (?:(?:SS|SST|STAINLESS|CRES|AISI)[\s\-]?)?  # Optional prefix
        (?P<alloy>3\d{2}|4[0-5]\d)              # 300-series or 400-4xx
        (?P<suffix>[LNH])?                      # L/N/H suffix
        (?:[\s\-]?(?P<condition>ANN|CW|CD|\d{1,2}%\s?CW))?  # Condition
        """,
        re.IGNORECASE | re.VERBOSE
    ),

    # 18-8 stainless (equivalent to 304)
    "stainless_18_8": re.compile(
        r"""
        (?P<alloy>18[\s\-]?8)                   # 18-8 designation
        [\s\-]?(?:SS|SST|STAINLESS|CRES)?       # Optional suffix
        """,
        re.IGNORECASE | re.VERBOSE
    ),

    "stainless_ph": re.compile(
        r"""
        (?:(?:SS|STAINLESS|CRES|AISI)[\s\-]?)?  # Optional prefix
        (?P<alloy>17[\s\-]?4|15[\s\-]?5|17[\s\-]?7|13[\s\-]?8)  # PH grades
        [\s\-]?(?:PH)?                          # Optional PH suffix
        (?:[\s\-]?MO)?                          # Optional Mo (13-8 Mo)
        (?:[\s\-]?(?P<condition>H\d{3,4}|A|COND[\s\-]?[A-Z]))?  # Condition
        """,
        re.IGNORECASE | re.VERBOSE
    ),

    # 321/347 with stabilization note
    "stainless_stabilized": re.compile(
        r"""
        (?:(?:SS|STAINLESS|CRES|AISI)[\s\-]?)?
        (?P<alloy>321|347|348)
        (?P<suffix>[H])?
        """,
        re.IGNORECASE | re.VERBOSE
    ),

    # A-286 / A286 variants, often with extra qualifiers like "(160 KSI)" or "SST"
    "stainless_a286": re.compile(
        r"""
        \bA[\s\-]?286\b
        """,
        re.IGNORECASE | re.VERBOSE
    ),

    # -------------------------------------------------------------------------
    # TITANIUM - CP grades and alloys
    # -------------------------------------------------------------------------
    "titanium_grade": re.compile(
        r"""
        (?:TI(?:TANIUM)?[\s\-]?)?
        (?:GRADE[\s\-]?)?
        (?P<grade>[1-4]|5|23|6|7|9|12)
        (?![\d])  # Not followed by more digits
        """,
        re.IGNORECASE | re.VERBOSE
    ),

    "titanium_6al4v": re.compile(
        r"""
        (?:TI(?:TANIUM)?[\s\-]?)?
        (?:
            6[\s\-]?AL[\s\-]?4[\s\-]?V |  # 6Al-4V
            6[\s\-]?4 |                    # 6-4
            64 |                           # 64
            TI64                           # Ti64
        )
        (?:[\s\-]?(?P<eli>ELI))?           # ELI variant
        """,
        re.IGNORECASE | re.VERBOSE
    ),

    "titanium_beta": re.compile(
        r"""
        (?:TI(?:TANIUM)?[\s\-]?)?
        (?:
            15[\s\-]?(?:V[\s\-]?)?3[\s\-]?(?:CR[\s\-]?)?3[\s\-]?(?:AL[\s\-]?)?3[\s\-]?(?:SN)? |
            15[\s\-]?3[\s\-]?3[\s\-]?3 |
            10[\s\-]?(?:V[\s\-]?)?2[\s\-]?(?:FE[\s\-]?)?3[\s\-]?(?:AL)? |
            10[\s\-]?2[\s\-]?3 |
            BETA[\s\-]?C
        )
        """,
        re.IGNORECASE | re.VERBOSE
    ),

    # -------------------------------------------------------------------------
    # NICKEL ALLOYS - Inconel, Hastelloy, Monel, Waspaloy
    # -------------------------------------------------------------------------
    "inconel": re.compile(
        r"""
        (?:INCONEL|IN|ALLOY)[\s\-]?
        (?P<alloy>600|601|617|625|686|690|718|725|X[\s\-]?750|X750)
        """,
        re.IGNORECASE | re.VERBOSE
    ),

    "hastelloy": re.compile(
        r"""
        (?:HASTELLOY|HAS)[\s\-]?
        (?P<alloy>B[\s\-]?[23]?|C[\s\-]?(?:4|22|276|2000)?|G[\s\-]?(?:30|35)?|N|S|W|X)
        """,
        re.IGNORECASE | re.VERBOSE
    ),

    "monel": re.compile(
        r"""
        (?:MONEL)[\s\-]?
        (?P<alloy>400|401|404|K[\s\-]?500|R[\s\-]?405)
        """,
        re.IGNORECASE | re.VERBOSE
    ),

    "waspaloy": re.compile(
        r"""
        (?:WASPALOY|WASPALLOY)
        """,
        re.IGNORECASE | re.VERBOSE
    ),

    "rene": re.compile(
        r"""
        (?:RENE|RENE')[\s\-]?
        (?P<alloy>41|77|80|88|95|104|N4|N5|N6)
        """,
        re.IGNORECASE | re.VERBOSE
    ),

    # -------------------------------------------------------------------------
    # COPPER ALLOYS - UNS Cxxxxx or common names
    # -------------------------------------------------------------------------
    "copper_uns": re.compile(
        r"""
        (?:UNS[\s\-]?)?
        C(?P<uns>\d{5})
        """,
        re.IGNORECASE | re.VERBOSE
    ),

    "copper_common": re.compile(
        r"""
        (?:
            (?P<becu>BE(?:RYLLIUM)?[\s\-]?CU(?:PPER)?|BECU|ALLOY[\s\-]?25) |
            (?P<brass>BRASS|70[\s\-]?30[\s\-]?BRASS|CARTRIDGE) |
            (?P<bronze>PHOSPHOR[\s\-]?BRONZE|AL(?:UMINUM)?[\s\-]?BRONZE|SILICON[\s\-]?BRONZE) |
            (?P<cupronickel>CU(?:PRO)?[\s\-]?NI(?:CKEL)?|90[\s\-]?10|70[\s\-]?30[\s\-]?(?:CN|CUPRO))
        )
        """,
        re.IGNORECASE | re.VERBOSE
    ),

    # -------------------------------------------------------------------------
    # COBALT ALLOYS
    # -------------------------------------------------------------------------
    "stellite": re.compile(
        r"""
        (?:STELLITE|HAYNES)[\s\-]?
        (?P<alloy>6[B]?|12|21|25|31|188|230|242|263|282|556|617|625|HR[\s\-]?120|HR[\s\-]?160)
        """,
        re.IGNORECASE | re.VERBOSE
    ),

    "mp35n": re.compile(
        r"""
        MP[\s\-]?35[\s\-]?N
        """,
        re.IGNORECASE | re.VERBOSE
    ),

    # -------------------------------------------------------------------------
    # UNS DIRECT MATCH (fallback)
    # -------------------------------------------------------------------------
    "uns_direct": re.compile(
        r"""
        (?:UNS[\s\-]?)?
        (?P<uns>[ACGKMNRSTW]\d{5})
        """,
        re.IGNORECASE | re.VERBOSE
    ),
}


# =============================================================================
# UNS LOOKUP TABLES - Canonical mappings
# =============================================================================

UNS_ALUMINUM = {
    "1050": "A91050", "1060": "A91060", "1100": "A91100",
    "2014": "A92014", "2017": "A92017", "2024": "A92024",
    "2124": "A92124", "2195": "A92195", "2219": "A92219",
    "3003": "A93003", "3004": "A93004", "3105": "A93105",
    "4043": "A94043", "4047": "A94047",
    "5052": "A95052", "5056": "A95056", "5083": "A95083",
    "5086": "A95086", "5154": "A95154", "5454": "A95454", "5456": "A95456",
    "6013": "A96013", "6061": "A96061", "6063": "A96063", "6082": "A96082",
    "7050": "A97050", "7075": "A97075", "7079": "A97079",
    "7150": "A97150", "7178": "A97178", "7475": "A97475",
    "8090": "A98090",
}

UNS_STAINLESS = {
    # Austenitic 300-series
    "301": "S30100", "302": "S30200", "303": "S30300",
    "304": "S30400", "304L": "S30403", "304H": "S30409", "304N": "S30451",
    # 18-8 is equivalent to 304 (18% Cr, 8% Ni)
    "18-8": "S30400", "18 8": "S30400", "188": "S30400",
    "305": "S30500", "308": "S30800", "309": "S30900", "309S": "S30908",
    "310": "S31000", "310S": "S31008",
    "316": "S31600", "316L": "S31603", "316H": "S31609", "316N": "S31651",
    "316TI": "S31635", "316LN": "S31653",
    "317": "S31700", "317L": "S31703",
    "321": "S32100", "321H": "S32109",
    "347": "S34700", "347H": "S34709",
    "348": "S34800", "348H": "S34809",
    # Ferritic 400-series
    "405": "S40500", "409": "S40900", "430": "S43000", "439": "S43035", "446": "S44600",
    # Martensitic 400-series
    "410": "S41000", "414": "S41400", "416": "S41600",
    "420": "S42000", "431": "S43100",
    "440A": "S44002", "440B": "S44003", "440C": "S44004",
    # Precipitation hardening
    "17-4 PH": "S17400", "17-4PH": "S17400", "174PH": "S17400",
    "15-5 PH": "S15500", "15-5PH": "S15500", "155PH": "S15500",
    "17-7 PH": "S17700", "17-7PH": "S17700",
    "PH 13-8 MO": "S13800", "13-8 MO": "S13800", "13-8MO": "S13800",
    "PH 15-7 MO": "S15700",
    # Duplex
    "2205": "S32205", "2507": "S32750", "2304": "S32304",
    # Specialty
    "254 SMO": "S31254", "904L": "N08904",
    "A286": "S66286", "A-286": "S66286", "A 286": "S66286",
    "CRES A-286": "S66286", "CRES A286": "S66286", "CRES A 286": "S66286",
    "A286 CRES": "S66286", "A-286 CRES": "S66286", "A 286 CRES": "S66286",
    "21-6-9": "S21900", "NITRONIC 50": "S20910", "NITRONIC 60": "S21800",
}

UNS_TITANIUM = {
    # CP grades
    "GRADE 1": "R50250", "GR1": "R50250", "CP1": "R50250",
    "GRADE 2": "R50400", "GR2": "R50400", "CP2": "R50400",
    "GRADE 3": "R50550", "GR3": "R50550", "CP3": "R50550",
    "GRADE 4": "R50700", "GR4": "R50700", "CP4": "R50700",
    # Alpha-beta
    "TI-6AL-4V": "R56400", "6AL-4V": "R56400", "6-4": "R56400",
    "TI64": "R56400", "GRADE 5": "R56400",
    "TI-6AL-4V ELI": "R56401", "6AL-4V ELI": "R56401", "GRADE 23": "R56401",
    "TI-6AL-6V-2SN": "R56620",
    # Beta
    "TI-15V-3CR-3AL-3SN": "R58153", "15-3-3-3": "R58153",
    "TI-10V-2FE-3AL": "R56410", "10-2-3": "R56410",
    "TI-3AL-8V-6CR-4MO-4ZR": "R58640", "BETA-C": "R58640",
    "TI-15MO-3NB-3AL-0.2SI": "R58150", "TIMETAL 21S": "R58150",
    # Near-alpha
    "TI-6AL-2SN-4ZR-2MO": "R54620", "TI-6242": "R54620",
    "TI-5AL-2.5SN": "R54520",
    "TI-8AL-1MO-1V": "R54810", "TI-811": "R54810",
}

UNS_NICKEL = {
    # Inconel family
    "INCONEL 600": "N06600", "IN600": "N06600", "600": "N06600",
    "INCONEL 601": "N06601", "IN601": "N06601",
    "INCONEL 617": "N06617", "IN617": "N06617",
    "INCONEL 625": "N06625", "IN625": "N06625", "625": "N06625",
    "INCONEL 686": "N06686",
    "INCONEL 690": "N06690", "IN690": "N06690",
    "INCONEL 718": "N07718", "IN718": "N07718", "718": "N07718", "ALLOY 718": "N07718",
    "INCONEL 725": "N07725",
    "INCONEL X-750": "N07750", "X-750": "N07750", "X750": "N07750",
    # Hastelloy family
    "HASTELLOY B": "N10001", "HASTELLOY B-2": "N10665", "HASTELLOY B-3": "N10675",
    "HASTELLOY C": "N10002", "HASTELLOY C-4": "N06455",
    "HASTELLOY C-22": "N06022", "C-22": "N06022",
    "HASTELLOY C-276": "N10276", "C-276": "N10276",
    "HASTELLOY C-2000": "N06200",
    "HASTELLOY G-30": "N06030", "HASTELLOY G-35": "N06035",
    "HASTELLOY N": "N10003",
    "HASTELLOY S": "N06635",
    "HASTELLOY W": "N10004",
    "HASTELLOY X": "N06002", "HAS X": "N06002",
    # Monel family
    "MONEL 400": "N04400", "400": "N04400",
    "MONEL K-500": "N05500", "K-500": "N05500", "K500": "N05500",
    "MONEL R-405": "N04405",
    # Other nickel alloys
    "WASPALOY": "N07001",
    "RENE 41": "N07041", "RENE 77": "N07777", "RENE 80": "N07080",
    "RENE 88": "N07088", "RENE 95": "N07095",
    "MAR-M-247": "N07247",
    "UDIMET 500": "N07500", "UDIMET 520": "N07520", "UDIMET 720": "N07720",
    "NIMONIC 75": "N06075", "NIMONIC 80A": "N07080", "NIMONIC 90": "N07090",
    "INVAR 36": "K93600",
    "KOVAR": "K94610",
    "ALLOY 20": "N08020", "CARPENTER 20": "N08020",
    "ALLOY 825": "N08825", "INCOLOY 825": "N08825",
    "ALLOY 800": "N08800", "INCOLOY 800": "N08800",
    "ALLOY 800H": "N08810", "ALLOY 800HT": "N08811",
}

UNS_COPPER = {
    # Pure copper
    "C10100": "C10100", "OFE": "C10100", "OFHC": "C10200",
    "C10200": "C10200",
    "C11000": "C11000", "ETP": "C11000", "110": "C11000",
    # High copper alloys
    "C17200": "C17200", "BECU": "C17200", "BERYLLIUM COPPER": "C17200", "ALLOY 25": "C17200",
    "C17500": "C17500",
    "C18200": "C18200", "CHROMIUM COPPER": "C18200",
    # Brasses
    "C26000": "C26000", "CARTRIDGE BRASS": "C26000", "70-30 BRASS": "C26000",
    "C27000": "C27000", "65-35 BRASS": "C27000",
    "C28000": "C28000", "MUNTZ METAL": "C28000",
    "C36000": "C36000", "FREE-CUTTING BRASS": "C36000",
    # Bronzes
    "C51000": "C51000", "PHOSPHOR BRONZE A": "C51000",
    "C52100": "C52100", "PHOSPHOR BRONZE C": "C52100",
    "C54400": "C54400",
    "C61400": "C61400", "ALUMINUM BRONZE D": "C61400",
    "C63000": "C63000", "ALUMINUM BRONZE": "C63000",
    "C65500": "C65500", "SILICON BRONZE A": "C65500",
    # Copper-nickels
    "C70600": "C70600", "90-10 CUPRONICKEL": "C70600", "90-10": "C70600",
    "C71500": "C71500", "70-30 CUPRONICKEL": "C71500", "70-30 CN": "C71500",
    # Nickel silvers
    "C75200": "C75200", "NICKEL SILVER": "C75200",
}

UNS_COBALT = {
    "STELLITE 6": "R30006", "STELLITE 6B": "R30016",
    "STELLITE 12": "R30012", "STELLITE 21": "R30021",
    "HAYNES 25": "R30605", "L-605": "R30605",
    "HAYNES 188": "R30188",
    "HAYNES 230": "N06230",
    "HAYNES 242": "N10242",
    "HAYNES 263": "N07263",
    "HAYNES 282": "N07208",
    "HAYNES 556": "R30556",
    "MP35N": "R30035",
    "ELGILOY": "R30003",
    "MAR-M-509": "R30509",
}

# H2 compatibility by UNS prefix (austenitic = safe)
H2_COMPATIBLE_PREFIXES = {"S30", "S31", "S32", "N0", "N1", "R5"}  # 300-series SS, nickel, titanium
H2_INCOMPATIBLE_PREFIXES = {"S4", "S17", "S15", "S13"}  # 400-series, PH grades


class AlloyNormalizer:
    """Deterministic alloy designation normalizer using UNS as canonical key.

    Compliance: SWE-032 (Data validation), NASA-STD-6016 (Material identification)
    """

    def __init__(self) -> None:
        """Initialize normalizer with compiled lookup tables."""
        self._all_uns = {}
        self._all_uns.update({k.upper(): v for k, v in UNS_ALUMINUM.items()})
        self._all_uns.update({k.upper(): v for k, v in UNS_STAINLESS.items()})
        self._all_uns.update({k.upper(): v for k, v in UNS_TITANIUM.items()})
        self._all_uns.update({k.upper(): v for k, v in UNS_NICKEL.items()})
        self._all_uns.update({k.upper(): v for k, v in UNS_COPPER.items()})
        self._all_uns.update({k.upper(): v for k, v in UNS_COBALT.items()})

        # Build reverse lookup (UNS -> canonical name)
        self._uns_to_name: dict[str, str] = {}
        for name, uns in self._all_uns.items():
            if uns not in self._uns_to_name:
                self._uns_to_name[uns] = name

    def normalize(self, designation: str) -> NormalizedAlloy:
        """Normalize a material designation to canonical UNS.

        Args:
            designation: Raw material designation from MAPTIS or other source

        Returns:
            NormalizedAlloy with UNS code, family, and confidence

        Compliance: SWE-032 (Deterministic validation, no fuzzy guessing)
        """
        if not designation or not designation.strip():
            return NormalizedAlloy(
                original_input=designation or "",
                warnings=["Empty designation provided"],
            )

        original = designation
        cleaned = self._clean_input(designation)

        # Try direct UNS match first
        result = self._try_direct_uns(cleaned, original)
        if result.is_resolved:
            return result

        # Try direct lookup in combined tables BEFORE patterns
        # (exact matches like "IN625" should take priority)
        result = self._try_table_lookup(cleaned, original)
        if result.is_resolved:
            return result

        # Try pattern matching for complex designations
        for pattern_name, pattern in PATTERNS.items():
            result = self._try_pattern(pattern_name, pattern, cleaned, original)
            if result.is_resolved:
                return result

        # Unresolved - return with warnings
        return NormalizedAlloy(
            original_input=original,
            canonical_name=cleaned,
            confidence=0.3,
            match_method="unresolved",
            warnings=[f"Could not resolve '{designation}' to UNS code"],
        )

    # Common UNS typos and their corrections
    UNS_TYPO_CORRECTIONS = {
        # Aluminum: A0xxxx should be A9xxxx
        'A07075': 'A97075',
        'A06061': 'A96061',
        'A02024': 'A92024',
        'A02014': 'A92014',
        'A05052': 'A95052',
        'A05083': 'A95083',
        'A06063': 'A96063',
        # Stainless: Common transposition errors
        'S69386': 'S66286',  # A286 typo
        'S66986': 'S66286',  # A286 typo
        'S69286': 'S66286',  # A286 typo
    }

    # Common designation typos
    DESIGNATION_TYPO_CORRECTIONS = {
        'A296': 'A286',
        'A-296': 'A-286',
    }

    def _clean_input(self, designation: str) -> str:
        """Clean and normalize input string."""
        cleaned = designation.upper().strip()
        # Normalize common separators
        cleaned = re.sub(r"[\s\-_/]+", " ", cleaned)
        # Remove specs/standards prefix
        cleaned = re.sub(r"^(AMS|ASTM|SAE|MIL|QQ|ASME)\s*[-\s]?\d*\s*", "", cleaned)
        # Remove trailing stock forms
        cleaned = re.sub(r"\s+(SHEET|PLATE|BAR|ROD|WIRE|TUBE|PIPE|FORGING|CASTING).*$", "", cleaned)

        # Fix common UNS typos
        for typo, correct in self.UNS_TYPO_CORRECTIONS.items():
            if typo in cleaned:
                logger.warning(f"Correcting UNS typo: {typo} -> {correct} in '{designation}'")
                cleaned = cleaned.replace(typo, correct)

        # Fix common designation typos
        for typo, correct in self.DESIGNATION_TYPO_CORRECTIONS.items():
            if typo in cleaned:
                logger.warning(f"Correcting designation typo: {typo} -> {correct} in '{designation}'")
                cleaned = cleaned.replace(typo, correct)

        return cleaned.strip()

    def _try_direct_uns(self, cleaned: str, original: str) -> NormalizedAlloy:
        """Try to match a direct UNS code."""
        match = PATTERNS["uns_direct"].search(cleaned)
        if match:
            uns = match.group("uns").upper()
            family = self._family_from_uns(uns)
            return NormalizedAlloy(
                original_input=original,
                uns=uns,
                canonical_name=self._uns_to_name.get(uns, uns),
                family=family,
                base_alloy=uns,
                confidence=0.95,
                match_method="uns_direct",
            )
        return NormalizedAlloy(original_input=original)

    def _try_pattern(
        self, pattern_name: str, pattern: re.Pattern, cleaned: str, original: str
    ) -> NormalizedAlloy:
        """Try to match a specific pattern and resolve to UNS."""
        match = pattern.search(cleaned)
        if not match:
            return NormalizedAlloy(original_input=original)

        groups = match.groupdict()

        # Aluminum patterns
        if pattern_name == "aluminum_full":
            alloy = groups.get("alloy", "")
            temper = groups.get("temper")
            uns = UNS_ALUMINUM.get(alloy)
            if uns:
                canonical = f"{alloy}-{temper}" if temper else alloy
                return NormalizedAlloy(
                    original_input=original,
                    uns=uns,
                    canonical_name=canonical,
                    family=AlloyFamily.ALUMINUM,
                    base_alloy=alloy,
                    temper=temper,
                    confidence=0.9,
                    match_method=pattern_name,
                )

        # Stainless 300/400 patterns
        if pattern_name in ("stainless_300_400", "stainless_stabilized"):
            alloy = groups.get("alloy", "")
            suffix = groups.get("suffix", "") or ""
            condition = groups.get("condition")
            lookup_key = f"{alloy}{suffix}".upper()
            uns = UNS_STAINLESS.get(lookup_key) or UNS_STAINLESS.get(alloy)
            if uns:
                return NormalizedAlloy(
                    original_input=original,
                    uns=uns,
                    canonical_name=lookup_key,
                    family=AlloyFamily.STAINLESS_STEEL,
                    base_alloy=alloy,
                    condition=condition,
                    confidence=0.9,
                    match_method=pattern_name,
                )

        # 18-8 stainless pattern (equivalent to 304)
        if pattern_name == "stainless_18_8":
            alloy = groups.get("alloy", "").replace(" ", "-")
            uns = UNS_STAINLESS.get("18-8")
            if uns:
                return NormalizedAlloy(
                    original_input=original,
                    uns=uns,
                    canonical_name="304 (18-8)",
                    family=AlloyFamily.STAINLESS_STEEL,
                    base_alloy="304",
                    confidence=0.9,
                    match_method=pattern_name,
                )

        # Stainless PH patterns
        if pattern_name == "stainless_ph":
            alloy = groups.get("alloy", "").replace(" ", "-")
            condition = groups.get("condition")
            # Normalize to standard form
            if "17" in alloy and "4" in alloy:
                lookup_key = "17-4 PH"
            elif "15" in alloy and "5" in alloy:
                lookup_key = "15-5 PH"
            elif "17" in alloy and "7" in alloy:
                lookup_key = "17-7 PH"
            elif "13" in alloy and "8" in alloy:
                lookup_key = "PH 13-8 MO"
            else:
                lookup_key = alloy
            uns = UNS_STAINLESS.get(lookup_key)
            if uns:
                return NormalizedAlloy(
                    original_input=original,
                    uns=uns,
                    canonical_name=lookup_key,
                    family=AlloyFamily.STAINLESS_STEEL,
                    base_alloy=lookup_key,
                    condition=condition,
                    confidence=0.9,
                    match_method=pattern_name,
                )

        # A286 variants (including A286 SST, A286 (160 KSI), etc.)
        if pattern_name == "stainless_a286":
            uns = UNS_STAINLESS.get("A286")
            if uns:
                return NormalizedAlloy(
                    original_input=original,
                    uns=uns,
                    canonical_name="A286",
                    family=AlloyFamily.STAINLESS_STEEL,
                    base_alloy="A286",
                    confidence=0.9,
                    match_method=pattern_name,
                )

        # Titanium patterns
        if pattern_name == "titanium_grade":
            grade = groups.get("grade", "")
            lookup_key = f"GRADE {grade}"
            uns = UNS_TITANIUM.get(lookup_key)
            if uns:
                return NormalizedAlloy(
                    original_input=original,
                    uns=uns,
                    canonical_name=lookup_key,
                    family=AlloyFamily.TITANIUM,
                    base_alloy=f"Grade {grade}",
                    confidence=0.85,
                    match_method=pattern_name,
                )

        if pattern_name == "titanium_6al4v":
            eli = groups.get("eli")
            if eli:
                uns = UNS_TITANIUM.get("TI-6AL-4V ELI")
                canonical = "Ti-6Al-4V ELI"
            else:
                uns = UNS_TITANIUM.get("TI-6AL-4V")
                canonical = "Ti-6Al-4V"
            if uns:
                return NormalizedAlloy(
                    original_input=original,
                    uns=uns,
                    canonical_name=canonical,
                    family=AlloyFamily.TITANIUM,
                    base_alloy="Ti-6Al-4V",
                    condition="ELI" if eli else None,
                    confidence=0.95,
                    match_method=pattern_name,
                )

        # Nickel alloy patterns
        if pattern_name == "inconel":
            alloy = groups.get("alloy", "").replace(" ", "").replace("-", "")
            lookup_key = f"INCONEL {alloy}".upper()
            uns = UNS_NICKEL.get(lookup_key) or UNS_NICKEL.get(alloy)
            if uns:
                return NormalizedAlloy(
                    original_input=original,
                    uns=uns,
                    canonical_name=f"Inconel {alloy}",
                    family=AlloyFamily.NICKEL,
                    base_alloy=alloy,
                    confidence=0.9,
                    match_method=pattern_name,
                )

        if pattern_name == "hastelloy":
            alloy = groups.get("alloy", "").replace(" ", "-")
            lookup_key = f"HASTELLOY {alloy}".upper()
            uns = UNS_NICKEL.get(lookup_key)
            if uns:
                return NormalizedAlloy(
                    original_input=original,
                    uns=uns,
                    canonical_name=f"Hastelloy {alloy}",
                    family=AlloyFamily.NICKEL,
                    base_alloy=alloy,
                    confidence=0.9,
                    match_method=pattern_name,
                )

        if pattern_name == "monel":
            alloy = groups.get("alloy", "").replace(" ", "-")
            lookup_key = f"MONEL {alloy}".upper()
            uns = UNS_NICKEL.get(lookup_key)
            if uns:
                return NormalizedAlloy(
                    original_input=original,
                    uns=uns,
                    canonical_name=f"Monel {alloy}",
                    family=AlloyFamily.NICKEL,
                    base_alloy=alloy,
                    confidence=0.9,
                    match_method=pattern_name,
                )

        if pattern_name == "waspaloy":
            uns = UNS_NICKEL.get("WASPALOY")
            return NormalizedAlloy(
                original_input=original,
                uns=uns,
                canonical_name="Waspaloy",
                family=AlloyFamily.NICKEL,
                base_alloy="Waspaloy",
                confidence=0.95,
                match_method=pattern_name,
            )

        # Copper patterns
        if pattern_name == "copper_uns":
            uns = f"C{groups.get('uns', '')}"
            return NormalizedAlloy(
                original_input=original,
                uns=uns,
                canonical_name=self._uns_to_name.get(uns, uns),
                family=AlloyFamily.COPPER,
                base_alloy=uns,
                confidence=0.95,
                match_method=pattern_name,
            )

        if pattern_name == "copper_common":
            if groups.get("becu"):
                uns = UNS_COPPER.get("BECU")
                canonical = "Beryllium Copper (C17200)"
            elif groups.get("brass"):
                uns = UNS_COPPER.get("CARTRIDGE BRASS")
                canonical = "Cartridge Brass (C26000)"
            elif groups.get("bronze"):
                # Try to distinguish bronze types
                if "ALUMINUM" in cleaned or "AL " in cleaned:
                    uns = UNS_COPPER.get("ALUMINUM BRONZE")
                    canonical = "Aluminum Bronze (C63000)"
                elif "SILICON" in cleaned:
                    uns = UNS_COPPER.get("SILICON BRONZE A")
                    canonical = "Silicon Bronze (C65500)"
                else:
                    uns = UNS_COPPER.get("PHOSPHOR BRONZE A")
                    canonical = "Phosphor Bronze (C51000)"
            elif groups.get("cupronickel"):
                if "90" in cleaned:
                    uns = UNS_COPPER.get("90-10")
                    canonical = "90-10 Cupronickel (C70600)"
                else:
                    uns = UNS_COPPER.get("70-30 CN")
                    canonical = "70-30 Cupronickel (C71500)"
            else:
                return NormalizedAlloy(original_input=original)

            if uns:
                return NormalizedAlloy(
                    original_input=original,
                    uns=uns,
                    canonical_name=canonical,
                    family=AlloyFamily.COPPER,
                    base_alloy=uns,
                    confidence=0.85,
                    match_method=pattern_name,
                )

        # Cobalt patterns
        if pattern_name in ("stellite", "mp35n"):
            alloy = groups.get("alloy", "") if groups else ""
            if pattern_name == "mp35n":
                lookup_key = "MP35N"
            else:
                lookup_key = f"STELLITE {alloy}".upper() if alloy else "STELLITE 6"
            uns = UNS_COBALT.get(lookup_key)
            if uns:
                return NormalizedAlloy(
                    original_input=original,
                    uns=uns,
                    canonical_name=lookup_key.title(),
                    family=AlloyFamily.COBALT,
                    base_alloy=alloy or "MP35N",
                    confidence=0.9,
                    match_method=pattern_name,
                )

        return NormalizedAlloy(original_input=original)

    def _try_table_lookup(self, cleaned: str, original: str) -> NormalizedAlloy:
        """Try direct lookup in combined UNS tables."""
        # Try exact match
        if cleaned in self._all_uns:
            uns = self._all_uns[cleaned]
            return NormalizedAlloy(
                original_input=original,
                uns=uns,
                canonical_name=cleaned,
                family=self._family_from_uns(uns),
                base_alloy=cleaned,
                confidence=0.85,
                match_method="table_exact",
            )

        # Try with common variations removed
        for suffix in [" ANN", " CW", " HT", " ST", " CD"]:
            if cleaned.endswith(suffix):
                base = cleaned[: -len(suffix)]
                if base in self._all_uns:
                    uns = self._all_uns[base]
                    return NormalizedAlloy(
                        original_input=original,
                        uns=uns,
                        canonical_name=base,
                        family=self._family_from_uns(uns),
                        base_alloy=base,
                        condition=suffix.strip(),
                        confidence=0.8,
                        match_method="table_suffix_strip",
                    )

        return NormalizedAlloy(original_input=original)

    def _family_from_uns(self, uns: str) -> AlloyFamily:
        """Determine alloy family from UNS prefix."""
        if not uns:
            return AlloyFamily.UNKNOWN
        prefix = uns[0].upper()
        families = {
            "A": AlloyFamily.ALUMINUM,
            "C": AlloyFamily.COPPER,
            "G": AlloyFamily.CARBON_STEEL,
            "K": AlloyFamily.CARBON_STEEL,
            "N": AlloyFamily.NICKEL,
            "R": AlloyFamily.REFRACTORY,  # Also titanium, cobalt
            "S": AlloyFamily.STAINLESS_STEEL,
            "T": AlloyFamily.CARBON_STEEL,
            "M": AlloyFamily.MAGNESIUM,
        }
        family = families.get(prefix, AlloyFamily.UNKNOWN)
        # Refine R-series (refractory covers Ti, Co, etc.)
        if prefix == "R" and uns.startswith("R5"):
            return AlloyFamily.TITANIUM
        if prefix == "R" and uns.startswith("R30"):
            return AlloyFamily.COBALT
        return family

    def is_h2_compatible(self, uns: Optional[str]) -> Optional[bool]:
        """Check H2 compatibility based on UNS code.

        Returns:
            True if known compatible (austenitic SS, Ni, Ti)
            False if known incompatible (ferritic/martensitic SS, PH grades)
            None if unknown

        Compliance: BoundState H2 Policy Engine integration
        """
        if not uns:
            return None
        uns_upper = uns.upper()
        for prefix in H2_COMPATIBLE_PREFIXES:
            if uns_upper.startswith(prefix):
                return True
        for prefix in H2_INCOMPATIBLE_PREFIXES:
            if uns_upper.startswith(prefix):
                return False
        return None

    def get_uns_info(self, uns: str) -> dict:
        """Get detailed info for a UNS code.

        Args:
            uns: UNS code to look up

        Returns:
            Dict with canonical_name, family, h2_compatible
        """
        if not uns:
            return {}
        uns_upper = uns.upper()
        return {
            "uns": uns_upper,
            "canonical_name": self._uns_to_name.get(uns_upper, uns_upper),
            "family": self._family_from_uns(uns_upper).value,
            "h2_compatible": self.is_h2_compatible(uns_upper),
        }


# Module-level convenience instance
_normalizer = AlloyNormalizer()


def normalize_alloy(designation: str) -> NormalizedAlloy:
    """Normalize an alloy designation to canonical UNS.

    Module-level convenience function.

    Args:
        designation: Raw material designation

    Returns:
        NormalizedAlloy with UNS and metadata

    Examples:
        >>> result = normalize_alloy("SS 316L")
        >>> result.uns
        'S31603'
        >>> result.family
        <AlloyFamily.STAINLESS_STEEL: 'stainless_steel'>

        >>> result = normalize_alloy("Ti 6-4 ELI")
        >>> result.uns
        'R56401'
        >>> result.canonical_name
        'Ti-6Al-4V ELI'

    Compliance: SWE-032 (Deterministic material identification)
    """
    return _normalizer.normalize(designation)
