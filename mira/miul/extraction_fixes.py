#!/usr/bin/env python3
"""
Module: Extraction Fixes
Purpose: Corrected material extraction logic for BioServe EPL format.

BoundState AI 2025
Version: 1.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Fixes:
1. EPL extraction prompt that distinguishes MATERIAL PART NUMBER vs MATERIAL columns
2. SolidWorks suffix stripper for (SS), (SN), (SS,SN) notation
3. Embedded material parser for "HELICOIL, 18-8 SS" style descriptions
4. Child drawing material resolution for assemblies
5. Purchased parts database schema and lookup

Based on analysis of GPE drawing set (Jan 2026).
"""

from __future__ import annotations

import re
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple
from pathlib import Path

logger = logging.getLogger(__name__)

__all__ = [
    "CORRECTED_EPL_PROMPT",
    "CORRECTED_DETAIL_PROMPT",
    "clean_solidworks_designation",
    "parse_embedded_material",
    "normalize_part_number",
    "is_drawing_reference",
    "PurchasedPartLookup",
    "MCMASTER_PATTERNS",
    "HELICOIL_PATTERNS",
    "STANDARD_HARDWARE_MATERIALS",
]


# =============================================================================
# FIX 1: CORRECTED EPL EXTRACTION PROMPT
# =============================================================================
# The key insight: BioServe EPLs have TWO material-related columns:
#   - MATERIAL PART NUMBER: McMaster P/N (89015K28) or "AR"
#   - MATERIAL: Actual designation (Al 6061-T6)
#
# Assembly drawings often have NO material column at all - just PART NUMBER
# and PART TITLE. Materials must come from child detail drawings.

CORRECTED_EPL_PROMPT = """Extract ALL items from the PARTS LIST or EPL table on this assembly drawing.

ASSEMBLY: {assembly_pn}

CRITICAL - BioServe EPL tables have specific column formats. Look carefully for these columns:

COLUMN IDENTIFICATION:
1. ITEM NO / FIND NO - Row identifier (1, 2, 3, etc.)
2. QTY - Quantity (number or "AR" for As Required)
3. MATERIAL PART NUMBER - This is often a McMaster-Carr P/N (like 89015K28) or "AR" - NOT the material itself!
4. PART NUMBER - The drawing/part number (GPE-051-1, FH100-1M4-32, NAS1149, etc.)
5. PART TITLE / DESCRIPTION / NOMENCLATURE - What the part is (SCREW, BRACKET, ROD, etc.)
6. MATERIAL - The actual material designation (6061-T6, Al 6061-T6, 18-8 SS, AISI 304, etc.)
7. LOT - S/N - Lot/serial tracking (usually empty)

IMPORTANT: Some EPL tables do NOT have a MATERIAL column at all (especially for assemblies).
If there is no MATERIAL column, return material="" for all parts.

OUTPUT FORMAT (JSON):
{{
    "has_material_column": true,  // Set to false if EPL has no MATERIAL column
    "parts": [
        {{
            "find_no": "1",
            "part_number": "GPE-051-1",
            "material_part_number": "AR",
            "description": "ROD",
            "qty": 4,
            "material": "6061-T6"
        }},
        {{
            "find_no": "2",
            "part_number": "89015K28",
            "material_part_number": "89015K28",
            "description": "SHIM",
            "qty": 8,
            "material": "Al 6061-T6"
        }},
        {{
            "find_no": "3",
            "part_number": "91732A355",
            "material_part_number": "91732A355",
            "description": "HELICAL INSERT, 6-32 X .138\\", 18-8 SS",
            "qty": 33,
            "material": "18-8 SS"
        }},
        {{
            "find_no": "4",
            "part_number": "FH100-1M4-32-625",
            "material_part_number": "",
            "description": "SCREW, 100 DEG FLAT HEAD",
            "qty": 6,
            "material": ""
        }}
    ]
}}

MATERIAL EXTRACTION RULES:
1. The "material" field comes ONLY from the MATERIAL column (rightmost data column, before LOT-S/N)
2. If there's no MATERIAL column, set has_material_column=false and material="" for all parts
3. DO NOT confuse MATERIAL PART NUMBER (McMaster P/N) with the MATERIAL (designation)
4. If material is embedded in description (like "HELICOIL, 18-8 SS"), extract it to material field
5. Common material formats: "6061-T6", "Al 6061-T6", "18-8 SS", "AISI 304 STAINLESS", "A286 CRES"

CHARACTER ACCURACY:
- 5 vs 8 (curved top = 5, two loops = 8)
- 6 vs 8 vs 9 (check loop direction)
- 0 vs O vs D (zero often has slash)
- Copy part numbers EXACTLY as shown

Return ONLY valid JSON. If no parts list table found, return {{"has_material_column": false, "parts": []}}"""


CORRECTED_DETAIL_PROMPT = """Extract material information from this DETAIL engineering drawing.

DRAWING: {drawing_pn}

Look for material information in these locations (in order of priority):
1. EPL TABLE - Small table usually bottom right with columns: ITEM NO, QTY, MATERIAL PART NUMBER, MATERIAL
2. TITLE BLOCK - Fields labeled MATERIAL, MAT'L, or in the main title block area
3. NOTES SECTION - Notes like "MATERIAL: 6061-T6 ALUMINUM" or "2. MATERIAL: Al 6061-T6 MMPDS"
4. FLAGGED CALLOUTS - Triangle/flag symbols pointing to material notes

EPL TABLE FORMAT (BioServe standard):
| ITEM NO. | QTY | MATERIAL PART NUMBER | MATERIAL | LOT - S/N |
|----------|-----|---------------------|----------|-----------|
| 1        | A/R | 89015K28            | Al 6061-T6 |         |
| 2        | 94  | HCC-138-40-138      | HELICOIL, 18-8 SS |  |

IMPORTANT DISTINCTIONS:
- "MATERIAL PART NUMBER" = McMaster-Carr P/N or vendor code (89015K28, HCC-138-40-138) - NOT the material!
- "MATERIAL" = Actual material designation (Al 6061-T6, 18-8 SS, AISI 304)
- "(SS)" suffix like "6061-T6 (SS)" is SolidWorks notation for Stress-Strain data, NOT stainless steel!

OUTPUT FORMAT (JSON):
{{
    "drawing_number": "GPE-205",
    "title": "SHIM",
    "revision": "B",
    "material_designation": "Al 6061-T6",
    "material_part_number": "89015K28",
    "material_spec": "AMS 4027",
    "process_spec": "CHEM FILM PER MIL-DTL-5541, TYPE 1, CLASS 3, YELLOW",
    "form": "SHEET",
    "has_helicoils": true,
    "helicoils": [
        {{"part_number": "HCC-138-40-138", "material": "18-8 SS", "qty": 94}}
    ]
}}

RULES:
1. material_designation = The BASE MATERIAL (6061-T6, 7075-T73, A286, INCONEL 718)
2. Strip "(SS)" or "(SN)" suffixes - these are SolidWorks simulation markers
3. material_part_number = McMaster/vendor P/N if shown (may be empty)
4. Extract ALL helicoils/inserts as separate items with their materials
5. process_spec = Surface finish/coating specs from notes (passivation, chem film, anodize, etc.)

Return ONLY valid JSON."""


# =============================================================================
# FIX 2: SOLIDWORKS SUFFIX STRIPPER
# =============================================================================

def clean_solidworks_designation(designation: str) -> str:
    """Remove SolidWorks simulation suffixes from material designations.

    SolidWorks materials library adds these suffixes to indicate simulation data:
    - (SS) = Stress-Strain curves defined
    - (SN) = S-N fatigue curves defined
    - (SS,SN) = Both curves defined

    These are NOT material properties - they're CAD metadata that should be stripped.

    Examples:
        "6061-T6 (SS)" -> "6061-T6"
        "7075-T73 (SS,SN)" -> "7075-T73"
        "A286 (SN)" -> "A286"
        "6061-T6" -> "6061-T6" (no change)

    Args:
        designation: Raw material designation from drawing/CAD

    Returns:
        Cleaned designation without SolidWorks suffixes
    """
    if not designation:
        return ""

    cleaned = designation.strip()

    # Pattern matches: (SS), (SN), (SS,SN), (SN,SS) with optional whitespace
    # Case insensitive to catch variations
    patterns = [
        r'\s*\(\s*SS\s*,\s*SN\s*\)\s*$',  # (SS,SN) or ( SS , SN )
        r'\s*\(\s*SN\s*,\s*SS\s*\)\s*$',  # (SN,SS)
        r'\s*\(\s*SS\s*\)\s*$',            # (SS)
        r'\s*\(\s*SN\s*\)\s*$',            # (SN)
    ]

    for pattern in patterns:
        cleaned = re.sub(pattern, '', cleaned, flags=re.IGNORECASE)

    return cleaned.strip()


# =============================================================================
# FIX 3: EMBEDDED MATERIAL PARSER
# =============================================================================
# Many EPLs embed material info in the description field, especially for hardware:
#   "HELICAL INSERT, 6-32 X .138", 18-8 SS"
#   "HELICOIL, 18-8 Stainless Steel"
#   "SCREW, FLAT HEAD, CRES"

@dataclass
class ParsedMaterial:
    """Result of parsing embedded material from description."""
    designation: str = ""
    material_type: str = ""  # STAINLESS, ALUMINUM, INCONEL, etc.
    alloy: str = ""          # 304, 6061, 718, etc.
    confidence: float = 0.0
    source: str = ""         # Where we found it


# Material patterns to search for in descriptions
EMBEDDED_MATERIAL_PATTERNS = [
    # Stainless steel patterns
    (r'\b18-8\s*(?:SS|STAINLESS(?:\s+STEEL)?)\b', 'STAINLESS STEEL', '304', 0.95),
    (r'\b(\d{3}[LNH]?)\s*(?:SS|STAINLESS(?:\s+STEEL)?)\b', 'STAINLESS STEEL', r'\1', 0.9),  # "304 SS"
    (r'\b(?:SS|STAINLESS)\s*(?:STEEL\s*)?(\d{3}[LNH]?)\b', 'STAINLESS STEEL', r'\1', 0.9),  # "SS 304"
    (r'\b(?:AISI|SAE)\s*(\d{3}[LNH]?)\b', 'STAINLESS STEEL', r'\1', 0.9),
    (r'\bCRES\b', 'CRES', '', 0.8),  # Corrosion Resistant Steel (generic)
    (r'\bA-?286\b', 'A286 CRES', 'A286', 0.95),
    (r'\b17-4\s*PH\b', 'STAINLESS STEEL', '17-4 PH', 0.95),
    (r'\b15-5\s*PH\b', 'STAINLESS STEEL', '15-5 PH', 0.95),

    # Aluminum patterns
    (r'\b(?:AL|ALUMINUM|ALUMINIUM)\s*(\d{4})-?([TFHOW]\d{1,4})?\b', 'ALUMINUM', r'\1-\2', 0.9),
    (r'\b(\d{4})-([TFHOW]\d{1,4})\s*(?:AL|ALUMINUM|ALUMINIUM)?\b', 'ALUMINUM', r'\1-\2', 0.85),

    # Nickel alloys
    (r'\bINCONEL\s*(\d{3})\b', 'INCONEL', r'\1', 0.95),
    (r'\bHASTELLOY\s*([A-Z]-?\d+)\b', 'HASTELLOY', r'\1', 0.95),
    (r'\bMONEL\s*(\d{3})?\b', 'MONEL', r'\1', 0.9),

    # Titanium
    (r'\bTI(?:TANIUM)?\s*(?:GRADE\s*)?(\d+|6AL-?4V|6-4)\b', 'TITANIUM', r'\1', 0.9),

    # Copper/Bronze
    (r'\bPHOSPHOR\s*BRONZE\b', 'PHOSPHOR BRONZE', '', 0.9),
    (r'\bBERYLLIUM\s*COPPER\b', 'BERYLLIUM COPPER', '', 0.9),
    (r'\bBRASS\b', 'BRASS', '', 0.85),

    # Generic steel
    (r'\bALLOY\s*STEEL\b', 'ALLOY STEEL', '', 0.8),
    (r'\bCARBON\s*STEEL\b', 'CARBON STEEL', '', 0.8),
]


def parse_embedded_material(description: str, part_number: str = "") -> ParsedMaterial:
    """Extract material designation from description text.

    Many EPLs embed material info in the description, especially for hardware:
        "HELICAL INSERT, 6-32 X .138", 18-8 SS" -> 18-8 STAINLESS STEEL
        "HELICOIL, 18-8 Stainless Steel" -> 18-8 STAINLESS STEEL
        "SCREW, FLAT HEAD, CRES" -> CRES
        "WASHER, FLAT, 304 SS" -> 304 STAINLESS STEEL

    Args:
        description: Part description text
        part_number: Part number (for context)

    Returns:
        ParsedMaterial with extracted info
    """
    if not description:
        return ParsedMaterial()

    text = description.upper()
    combined = f"{part_number} {description}".upper()

    result = ParsedMaterial(source="description")

    # Try each pattern
    for pattern, mat_type, alloy_group, confidence in EMBEDDED_MATERIAL_PATTERNS:
        match = re.search(pattern, combined, re.IGNORECASE)
        if match:
            result.material_type = mat_type
            result.confidence = confidence

            # Extract alloy if it's a capture group reference
            if alloy_group.startswith('\\'):
                try:
                    group_num = int(alloy_group[1:])
                    result.alloy = match.group(group_num) or ""
                except (IndexError, ValueError):
                    result.alloy = ""
            else:
                result.alloy = alloy_group

            # Build designation
            if result.alloy:
                # Clean up alloy (remove trailing dash from partial matches)
                result.alloy = result.alloy.strip('-').strip()
                if result.material_type == 'STAINLESS STEEL':
                    result.designation = f"{result.alloy} STAINLESS STEEL"
                elif result.material_type == 'ALUMINUM':
                    result.designation = f"{result.alloy} ALUMINUM"
                else:
                    result.designation = f"{result.material_type} {result.alloy}".strip()
            else:
                result.designation = result.material_type

            # Special case: 18-8 SS is specifically 304
            if '18-8' in combined:
                result.designation = "18-8 STAINLESS STEEL"
                result.alloy = "304"
                result.confidence = 0.95

            return result

    # Check for helicoil/insert without explicit material (default to 18-8 SS)
    if re.search(r'\b(?:HELICOIL|HELI-COIL|HELICAL\s+INSERT|INSERT)\b', text):
        return ParsedMaterial(
            designation="18-8 STAINLESS STEEL",
            material_type="STAINLESS STEEL",
            alloy="304",
            confidence=0.75,  # Lower confidence since it's a default assumption
            source="hardware_default"
        )

    return ParsedMaterial()


# =============================================================================
# FIX 4: PART NUMBER UTILITIES
# =============================================================================

def normalize_part_number(pn: str) -> str:
    """Normalize part number for matching.

    Handles variations like:
        GPE-010-1 == GPE0101 == gpe-010-1 == GPE_010_1

    Args:
        pn: Part number string

    Returns:
        Normalized uppercase string without separators
    """
    if not pn:
        return ""
    return re.sub(r'[-_\s]', '', pn.upper())


def is_drawing_reference(part_number: str, project_prefix: str = "") -> bool:
    """Check if a part number is a reference to another drawing (not hardware).

    Drawing numbers typically match patterns like:
    - GPE-051-1, GPE-A050-1, MER07564-001
    - Project prefix + numbers

    Hardware/consumables typically:
    - Start with NAS, MS, AN, PP-, FH, SHC-, etc.
    - Or are catalog numbers like 9246K13, 91732A355

    Args:
        part_number: Part number to check
        project_prefix: Project prefix (e.g., "GPE", "DMLLV")

    Returns:
        True if this is a drawing reference, False if hardware/consumable
    """
    pn = str(part_number).upper().strip()
    if not pn:
        return False

    # Hardware prefixes - definitely NOT drawing references
    hardware_prefixes = (
        'NAS', 'MS', 'AN', 'NASM',  # Military/aerospace standards
        'PP-', 'SHC', 'SHCS', 'FH', 'FHS', 'HHS', 'BHS', 'BHCS',  # Fastener prefixes
        'HCC', 'HCI',  # Helicoil prefixes
        'PH-', 'TH-',  # Generic hardware
    )
    if any(pn.startswith(p) for p in hardware_prefixes):
        return False

    # McMaster-Carr style numbers (digits with optional letter suffix)
    # Examples: 89015K28, 91732A355, 8983K363
    if re.match(r'^\d{4,}[A-Z]?\d*$', pn):
        return False

    # Vendor part numbers with all digits
    if pn.isdigit() and len(pn) >= 5:
        return False

    # Drawing number patterns
    # PREFIX-NUMBER-REVISION: GPE-010-1, MER07540-001-A
    if re.match(r'^[A-Z]{2,6}[-]?[A-Z]?\d{2,5}[-]?\d{0,3}[-]?[A-Z]?$', pn):
        return True

    # Check project prefix
    if project_prefix and pn.startswith(project_prefix.upper()):
        return True

    # Assembly patterns: PREFIX-Axxx (A indicates assembly)
    if re.match(r'^[A-Z]{2,6}-A\d{2,4}', pn):
        return True

    return False


# =============================================================================
# FIX 5: PURCHASED PARTS DATABASE & LOOKUP
# =============================================================================

# McMaster-Carr part number patterns -> likely material
MCMASTER_PATTERNS = {
    # Raw stock patterns
    r'^89\d{3}K\d+$': {  # 89xxxKxx = Raw materials
        'category': 'raw_stock',
        'default_material': None,  # Must lookup by specific P/N
        'confidence': 0.5,
    },
    r'^8974K\d+$': {  # 8974Kxx = 6061 aluminum bar
        'category': 'aluminum_bar',
        'default_material': '6061-T6 ALUMINUM',
        'uns': 'A96061',
        'confidence': 0.85,
    },
    r'^8975K\d+$': {  # 8975Kxx = 6061 aluminum plate
        'category': 'aluminum_plate',
        'default_material': '6061-T6 ALUMINUM',
        'uns': 'A96061',
        'confidence': 0.85,
    },
    r'^89105K\d+$': {  # 89105Kxx = 6061 aluminum sheet
        'category': 'aluminum_sheet',
        'default_material': '6061-T6 ALUMINUM',
        'uns': 'A96061',
        'confidence': 0.9,
    },
    r'^89015K\d+$': {  # 89015Kxx = 6061 aluminum sheet
        'category': 'aluminum_sheet',
        'default_material': '6061-T6 ALUMINUM',
        'uns': 'A96061',
        'confidence': 0.9,
    },
    r'^8983K\d+$': {  # 8983Kxx = 304 SS bar/stock
        'category': 'stainless_bar',
        'default_material': 'AISI 304 STAINLESS',
        'uns': 'S30400',
        'confidence': 0.9,
    },
    r'^91732A\d+$': {  # 91732Axxx = Helical inserts, 18-8 SS
        'category': 'helical_insert',
        'default_material': '18-8 STAINLESS STEEL',
        'uns': 'S30400',
        'confidence': 0.95,
    },
}

# Helicoil part number patterns
HELICOIL_PATTERNS = {
    r'^HCC[-]?\d{3}[-]?\d{2}[-]?\d{3}$': {  # HCC-xxx-xx-xxx (Heli-Coil)
        'default_material': '18-8 STAINLESS STEEL',
        'uns': 'S30400',
        'confidence': 0.9,
    },
    r'^T\d{4}[-]?\d?[A-Z]?\d+$': {  # Txxxx-xCxxx (Kato/Recoil)
        'default_material': '18-8 STAINLESS STEEL',
        'uns': 'S30400',
        'confidence': 0.9,
    },
    r'^MS\d{5}[-]?\d*$': {  # MSxxxxx (Military spec inserts)
        'default_material': '18-8 STAINLESS STEEL',
        'uns': 'S30400',
        'confidence': 0.85,
    },
}

# Standard hardware materials (fallback defaults)
STANDARD_HARDWARE_MATERIALS = {
    # Helicoils/Inserts - almost always 18-8 SS unless specified otherwise
    'HELICOIL': ('18-8 STAINLESS STEEL', 'S30400', 0.9),
    'HELI-COIL': ('18-8 STAINLESS STEEL', 'S30400', 0.9),
    'HELICAL INSERT': ('18-8 STAINLESS STEEL', 'S30400', 0.9),
    'INSERT': ('18-8 STAINLESS STEEL', 'S30400', 0.8),

    # Fasteners - typically alloy steel or CRES
    'SCREW': ('ALLOY STEEL', None, 0.6),
    'BOLT': ('ALLOY STEEL', None, 0.6),
    'NUT': ('ALLOY STEEL', None, 0.6),
    'WASHER': ('ALLOY STEEL', None, 0.6),

    # Specific fastener types
    'FLAT HEAD': ('ALLOY STEEL', None, 0.6),
    'SOCKET HEAD': ('ALLOY STEEL', None, 0.6),
    'PAN HEAD': ('ALLOY STEEL', None, 0.6),

    # Part number prefix patterns (added for GPE project)
    'FH100': ('ALLOY STEEL', None, 0.75),  # Flat head screws - FH100-xxx-xxx
    'SHC': ('ALLOY STEEL', None, 0.75),    # Socket head cap screws - SHC-xxx-xxx
}

# =============================================================================
# NAS/MS/AN AEROSPACE STANDARD MATERIAL LOOKUP
# =============================================================================
# These military/aerospace fastener specs define the material.
# Material may vary by dash number - these are the most common defaults.

AEROSPACE_STANDARD_MATERIALS: Dict[str, Dict[str, Any]] = {
    # Helical Coil Inserts
    "NASM33537": {"material": "CRES 302/304", "spec": "AMS 5688/5697", "confidence": 0.85},
    "MS33537": {"material": "CRES 302/304", "spec": "AMS 5688/5697", "confidence": 0.85},
    "NASM33538": {"material": "Phosphor Bronze", "spec": "QQ-B-750", "confidence": 0.90},
    "NAS1130": {"material": "CRES 302/304", "spec": "AMS 5688", "confidence": 0.85},
    "MS124651": {"material": "CRES 302/304", "spec": "AMS 5688", "confidence": 0.85},

    # Key-Locking Inserts
    "MS21209": {"material": "CRES 303", "spec": "AMS 5640", "confidence": 0.80},

    # Washers
    "NAS1149": {"material": "CRES 300 Series", "spec": "AMS 5510", "confidence": 0.75},
    "NAS1515": {"material": "CRES 300 Series", "spec": "AMS 5510", "confidence": 0.80},
    "AN960": {"material": "CRES or Alloy Steel", "spec": "Various", "confidence": 0.70},

    # Self-Locking Nuts
    "MS21042": {"material": "CRES or Alloy Steel", "spec": "Various", "confidence": 0.70},
    "MS21043": {"material": "CRES or Alloy Steel", "spec": "MIL-N-25027", "confidence": 0.70},
    "MS21044": {"material": "A286 CRES", "spec": "AMS 5525/5726", "confidence": 0.80},
    "MS21046": {"material": "A286 CRES", "spec": "AMS 5525/5726", "confidence": 0.80},

    # Socket Head Cap Screws
    "NAS1351": {"material": "Alloy Steel or A286", "spec": "Various", "confidence": 0.70},
    "NAS1352": {"material": "A286 CRES", "spec": "AMS 5737", "confidence": 0.85},

    # Flat Head Screws
    "NAS1580": {"material": "A286 CRES", "spec": "AMS 5737", "confidence": 0.85},
    "NAS1581": {"material": "Alloy Steel", "spec": "MIL-S-8879", "confidence": 0.80},

    # Spring Pins
    "MS16555": {"material": "CRES 302/304", "spec": "QQ-S-763", "confidence": 0.85},
    "MS16562": {"material": "CRES 302/304", "spec": "QQ-S-763", "confidence": 0.85},

    # AN Bolts (cadmium plated alloy steel by default)
    "AN3": {"material": "Alloy Steel, Cadmium Plated", "spec": "MIL-S-6758", "confidence": 0.80},
    "AN4": {"material": "Alloy Steel, Cadmium Plated", "spec": "MIL-S-6758", "confidence": 0.80},
    "AN5": {"material": "Alloy Steel, Cadmium Plated", "spec": "MIL-S-6758", "confidence": 0.80},
    "AN6": {"material": "Alloy Steel, Cadmium Plated", "spec": "MIL-S-6758", "confidence": 0.80},

    # AN Nuts
    "AN310": {"material": "Alloy Steel, Cadmium Plated", "spec": "MIL-N-21840", "confidence": 0.80},
    "AN315": {"material": "Alloy Steel, Cadmium Plated", "spec": "Various", "confidence": 0.80},
    "AN316": {"material": "Alloy Steel, Cadmium Plated", "spec": "Various", "confidence": 0.80},
    "AN320": {"material": "Alloy Steel, Cadmium Plated", "spec": "Various", "confidence": 0.80},
    "AN340": {"material": "CRES", "spec": "Various", "confidence": 0.80},
    "AN350": {"material": "CRES", "spec": "Various", "confidence": 0.80},

    # Rivets
    "MS20470": {"material": "Aluminum 2117-T4", "spec": "QQ-A-430", "confidence": 0.85},
    "AN470": {"material": "Aluminum 2117-T4", "spec": "QQ-A-430", "confidence": 0.85},
}


def lookup_aerospace_standard(part_number: str) -> Optional[Dict[str, Any]]:
    """Look up material for NAS/MS/AN aerospace standard part numbers.

    Args:
        part_number: The part number (e.g., "NAS1352C3-8", "MS21042-3")

    Returns:
        Dict with material, spec, confidence if found, None otherwise
    """
    pn_upper = part_number.upper().strip()

    # Try exact match first (for short standards like AN3, AN4)
    for standard, info in AEROSPACE_STANDARD_MATERIALS.items():
        if pn_upper == standard:
            return {**info, "standard": standard}

    # Try prefix match (NAS1352C3-8 -> NAS1352)
    for standard, info in AEROSPACE_STANDARD_MATERIALS.items():
        if pn_upper.startswith(standard):
            # Make sure it's a real prefix match (not NAS1 matching NAS1352)
            remainder = pn_upper[len(standard):]
            if not remainder or remainder[0] in '-0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ':
                return {**info, "standard": standard}

    return None


@dataclass
class PurchasedPartMatch:
    """Result of purchased part lookup."""
    part_number: str
    material_designation: str = ""
    uns_number: str = ""
    material_spec: str = ""
    confidence: float = 0.0
    source: str = ""  # 'mcmaster_pattern', 'helicoil_pattern', 'database', 'web_verified'
    needs_verification: bool = True


class PurchasedPartLookup:
    """Lookup service for purchased/standard parts materials.

    Multi-tier lookup strategy:
    1. Pattern matching (McMaster P/N patterns, helicoil patterns)
    2. Database cache (previously verified parts)
    3. Web search + AI verification (for unknowns)
    4. Conservative defaults (last resort)
    """

    def __init__(self, db_connection=None):
        """Initialize lookup service.

        Args:
            db_connection: Optional database connection for cached lookups
        """
        self._db = db_connection
        self._session_cache: Dict[str, PurchasedPartMatch] = {}

    def lookup(self, part_number: str, description: str = "") -> PurchasedPartMatch:
        """Look up material for a purchased part.

        Args:
            part_number: Part number (McMaster P/N, helicoil P/N, etc.)
            description: Part description for context

        Returns:
            PurchasedPartMatch with material info
        """
        pn_upper = part_number.upper().strip()
        cache_key = normalize_part_number(pn_upper)

        # Check session cache first
        if cache_key in self._session_cache:
            return self._session_cache[cache_key]

        result = PurchasedPartMatch(part_number=part_number)

        # Tier 1: McMaster pattern matching
        for pattern, info in MCMASTER_PATTERNS.items():
            if re.match(pattern, pn_upper):
                if info.get('default_material'):
                    result.material_designation = info['default_material']
                    result.uns_number = info.get('uns', '')
                    result.confidence = info.get('confidence', 0.8)
                    result.source = 'mcmaster_pattern'
                    result.needs_verification = result.confidence < 0.9
                    self._session_cache[cache_key] = result
                    return result

        # Tier 2: NAS/MS/AN aerospace standard lookup (before helicoil patterns!)
        # This must come before helicoil patterns because MS patterns overlap
        nas_match = lookup_aerospace_standard(pn_upper)
        if nas_match:
            result.material_designation = nas_match['material']
            result.material_spec = nas_match.get('spec', '')
            result.confidence = nas_match.get('confidence', 0.8)
            result.source = f"aerospace_standard:{nas_match.get('standard', pn_upper)}"
            result.needs_verification = result.confidence < 0.85
            self._session_cache[cache_key] = result
            return result

        # Tier 3: Helicoil pattern matching
        for pattern, info in HELICOIL_PATTERNS.items():
            if re.match(pattern, pn_upper):
                result.material_designation = info['default_material']
                result.uns_number = info.get('uns', '')
                result.confidence = info.get('confidence', 0.85)
                result.source = 'helicoil_pattern'
                result.needs_verification = False  # Helicoils are well-known
                self._session_cache[cache_key] = result
                return result

        # Tier 4: Parse material from description
        if description:
            parsed = parse_embedded_material(description, part_number)
            if parsed.designation and parsed.confidence >= 0.7:
                result.material_designation = parsed.designation
                result.confidence = parsed.confidence
                result.source = 'description_parsed'
                result.needs_verification = parsed.confidence < 0.9
                self._session_cache[cache_key] = result
                return result

        # Tier 5: Hardware type defaults (select highest confidence match)
        desc_upper = description.upper() if description else ""
        best_match = None
        best_conf = 0.0

        for keyword, (material, uns, conf) in STANDARD_HARDWARE_MATERIALS.items():
            if keyword in desc_upper or keyword in pn_upper:
                # Prefer highest confidence; tie-break: prefer PN match, then longer keyword
                if conf > best_conf or (conf == best_conf and best_match and (
                    (keyword in pn_upper and best_match[0] not in pn_upper) or
                    len(keyword) > len(best_match[0])
                )):
                    best_match = (keyword, material, uns, conf)
                    best_conf = conf

        if best_match:
            keyword, material, uns, conf = best_match
            result.material_designation = material
            result.uns_number = uns or ""
            result.confidence = conf
            result.source = f'hardware_default:{keyword}'
            result.needs_verification = True
            self._session_cache[cache_key] = result
            return result

        # No match found
        result.source = 'unresolved'
        result.needs_verification = True
        self._session_cache[cache_key] = result
        return result

    def lookup_batch(self, parts: List[Dict[str, str]]) -> Dict[str, PurchasedPartMatch]:
        """Look up materials for multiple parts.

        Args:
            parts: List of dicts with 'part_number' and 'description' keys

        Returns:
            Dict mapping part_number -> PurchasedPartMatch
        """
        results = {}
        for part in parts:
            pn = part.get('part_number', '')
            desc = part.get('description', '')
            if pn:
                results[pn] = self.lookup(pn, desc)
        return results


# =============================================================================
# CHILD DRAWING MATERIAL RESOLUTION
# =============================================================================

@dataclass
class DrawingMaterial:
    """Material info extracted from a detail drawing."""
    drawing_number: str
    designation: str = ""
    material_spec: str = ""
    process_spec: str = ""
    form: str = ""
    source: str = ""  # 'detail_drawing', 'parent_assembly', etc.


class ChildDrawingResolver:
    """Resolve materials for parts by looking up their detail drawings.

    When an assembly EPL references a child drawing (GPE-051-1), the material
    comes from that drawing's detail sheet, not the assembly.
    """

    def __init__(self, drawing_materials: Dict[str, DrawingMaterial] = None):
        """Initialize resolver.

        Args:
            drawing_materials: Pre-loaded dict of drawing_number -> DrawingMaterial
        """
        self._materials = drawing_materials or {}
        self._normalized_map: Dict[str, str] = {}
        self._base_map: Dict[str, str] = {}  # Base part number (strip -A/-1) -> actual drawing

        # Build normalized and base lookup maps
        for dwg_num in self._materials:
            normalized = normalize_part_number(dwg_num)
            self._normalized_map[normalized] = dwg_num

            # Base matching: strip revision suffixes (-A, -B, -1, -2, etc.)
            base = self._get_base_part_number(dwg_num)
            self._base_map[base] = dwg_num

    @staticmethod
    def _get_base_part_number(part_number: str) -> str:
        """Strip revision suffixes for base matching.

        Examples:
            GPE-010-A → GPE-010  (strips letter revision)
            GPE-014-1 → GPE-014  (strips number revision)
            GPE-015-B → GPE-015

        This handles cases where files are named with letter revisions (GPE-010-A)
        but EPLs reference them with number revisions (GPE-010-1).
        """
        base = part_number
        # Strip trailing dash + single letter (A, B, C, etc.)
        base = re.sub(r'-[A-Z]$', '', base, flags=re.IGNORECASE)
        # Strip trailing dash + single digit (1, 2, 3, etc.)
        base = re.sub(r'-\d$', '', base)
        return base

    def add_drawing_material(self, material: DrawingMaterial):
        """Add a drawing's material info."""
        self._materials[material.drawing_number] = material
        normalized = normalize_part_number(material.drawing_number)
        self._normalized_map[normalized] = material.drawing_number

        # Also add to base map
        base = self._get_base_part_number(material.drawing_number)
        self._base_map[base] = material.drawing_number

    def resolve(self, part_number: str) -> Optional[DrawingMaterial]:
        """Look up material for a drawing reference.

        Multi-level matching strategy:
        0. Base match: GPE-010-A matches GPE-010-1 (both → GPE-010)
        1. Exact match: GPE-010-1 == GPE-010-1
        2. Normalized match: GPE010-1 == GPE0101 (strip separators)
        3. Recursive: Try stripping numeric suffix and retry

        Args:
            part_number: Part number that may reference a detail drawing

        Returns:
            DrawingMaterial if found, None otherwise
        """
        # Level 0: Base match (strip -A/-1 revision suffixes)
        # Handles: GPE-010-A (file) matches GPE-010-1 (EPL reference)
        base = self._get_base_part_number(part_number)
        if base in self._base_map:
            actual_dwg = self._base_map[base]
            return self._materials.get(actual_dwg)

        # Level 1: Try exact match
        if part_number in self._materials:
            return self._materials[part_number]

        # Level 2: Try normalized match
        normalized = normalize_part_number(part_number)
        if normalized in self._normalized_map:
            actual_dwg = self._normalized_map[normalized]
            return self._materials.get(actual_dwg)

        # Level 3: Try stripping revision suffix (GPE-010-1 -> GPE-010)
        base_pn = re.sub(r'-\d+$', '', part_number)
        if base_pn != part_number:
            return self.resolve(base_pn)

        return None

    def resolve_assembly_parts(
        self,
        assembly_parts: List[Dict[str, Any]],
        project_prefix: str = ""
    ) -> List[Dict[str, Any]]:
        """Resolve materials for all parts in an assembly EPL.

        For each part:
        - If it's a drawing reference, look up material from detail drawing
        - If it's hardware, use purchased part lookup
        - If material is in EPL, use that

        Args:
            assembly_parts: List of parts from EPL extraction
            project_prefix: Project prefix for drawing detection

        Returns:
            Updated parts list with resolved materials
        """
        purchased_lookup = PurchasedPartLookup()
        resolved = []

        for part in assembly_parts:
            part = dict(part)  # Copy to avoid mutation
            pn = part.get('part_number', '')
            desc = part.get('description', '')
            existing_material = part.get('material', '')

            # If EPL already has material, clean it and use it
            if existing_material and existing_material.upper() not in ('', 'AR', 'N/A'):
                part['material'] = clean_solidworks_designation(existing_material)
                part['material_source'] = 'epl_direct'
                resolved.append(part)
                continue

            # Check if this is a drawing reference
            if is_drawing_reference(pn, project_prefix):
                dwg_material = self.resolve(pn)
                if dwg_material and dwg_material.designation:
                    part['material'] = dwg_material.designation
                    part['material_spec'] = dwg_material.material_spec
                    part['process_spec'] = dwg_material.process_spec
                    part['form'] = dwg_material.form
                    part['material_source'] = 'child_drawing'
                    resolved.append(part)
                    continue
                else:
                    # Drawing reference but no material found - flag it
                    part['material'] = ''
                    part['material_source'] = 'child_drawing_missing'
                    resolved.append(part)
                    continue

            # Not a drawing - try purchased part lookup
            purchased = purchased_lookup.lookup(pn, desc)
            if purchased.material_designation:
                part['material'] = purchased.material_designation
                part['uns_number'] = purchased.uns_number
                part['material_source'] = purchased.source
                part['needs_verification'] = purchased.needs_verification
            else:
                # Try parsing from description
                parsed = parse_embedded_material(desc, pn)
                if parsed.designation:
                    part['material'] = parsed.designation
                    part['material_source'] = 'description_parsed'
                else:
                    part['material'] = ''
                    part['material_source'] = 'unresolved'

            resolved.append(part)

        return resolved


# =============================================================================
# DATABASE SCHEMA FOR PURCHASED PARTS LEARNING
# =============================================================================

PURCHASED_PARTS_SCHEMA = """
-- Persistent storage for learned hardware/purchased part materials
-- This builds up over time as parts are verified via web lookup or human review

CREATE TABLE IF NOT EXISTS purchased_parts_materials (
    id SERIAL PRIMARY KEY,

    -- Part identification
    part_number VARCHAR(100) NOT NULL,
    part_number_normalized VARCHAR(100) NOT NULL,  -- For fuzzy matching
    vendor VARCHAR(100),  -- McMaster-Carr, Kato, etc.
    description VARCHAR(500),

    -- Material info
    material_designation VARCHAR(200) NOT NULL,
    uns_number VARCHAR(20),
    material_spec VARCHAR(100),
    maptis_material_code VARCHAR(20),

    -- Verification tracking
    verification_method VARCHAR(50) NOT NULL,  -- 'pattern', 'web_verified', 'opus_verified', 'human_verified'
    confidence FLOAT NOT NULL DEFAULT 0.0,
    verification_source TEXT,  -- URL or description of source
    reasoning TEXT,  -- Why this material was assigned
    verified_by VARCHAR(100) DEFAULT 'system',
    verified_at TIMESTAMP NOT NULL DEFAULT NOW(),

    -- Usage tracking
    times_used INTEGER DEFAULT 0,
    last_used_at TIMESTAMP,

    -- Timestamps
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW(),

    -- Constraints
    UNIQUE(part_number_normalized, material_designation)
);

-- Indexes for fast lookup
CREATE INDEX IF NOT EXISTS idx_purchased_parts_pn
    ON purchased_parts_materials(part_number_normalized);
CREATE INDEX IF NOT EXISTS idx_purchased_parts_vendor
    ON purchased_parts_materials(vendor);
CREATE INDEX IF NOT EXISTS idx_purchased_parts_confidence
    ON purchased_parts_materials(confidence DESC);

-- Pre-seed with known McMaster patterns
INSERT INTO purchased_parts_materials
    (part_number, part_number_normalized, vendor, description, material_designation, uns_number, verification_method, confidence, verified_by)
VALUES
    ('91732A355', '91732A355', 'McMaster-Carr', 'Helical Insert, 18-8 SS', '18-8 STAINLESS STEEL', 'S30400', 'standard_spec', 0.95, 'system'),
    ('89015K28', '89015K28', 'McMaster-Carr', '6061-T6 Aluminum Sheet', '6061-T6 ALUMINUM', 'A96061', 'standard_spec', 0.95, 'system'),
    ('89105K31', '89105K31', 'McMaster-Carr', '6061-T6 Aluminum Sheet', '6061-T6 ALUMINUM', 'A96061', 'standard_spec', 0.95, 'system'),
    ('8983K363', '8983K363', 'McMaster-Carr', '304 Stainless Steel', 'AISI 304 STAINLESS', 'S30400', 'standard_spec', 0.95, 'system'),
    ('HCC-138-40-138', 'HCC13840138', 'Heli-Coil', 'Helicoil Insert', '18-8 STAINLESS STEEL', 'S30400', 'standard_spec', 0.95, 'system'),
    ('HCC-250-28-250', 'HCC25028250', 'Heli-Coil', 'Helicoil Insert', '18-8 STAINLESS STEEL', 'S30400', 'standard_spec', 0.95, 'system'),
    ('T1084-3C045', 'T10843C045', 'Kato', 'Helicoil Insert, M3', '18-8 STAINLESS STEEL', 'S30400', 'standard_spec', 0.95, 'system'),
    ('11054-3CN45', '110543CN45', 'Kato', 'Helicoil Insert, M3', '18-8 STAINLESS STEEL', 'S30400', 'standard_spec', 0.95, 'system')
ON CONFLICT (part_number_normalized, material_designation) DO NOTHING;
"""


def migrate_purchased_parts_table(
    host: Optional[str] = None,
    port: Optional[int] = None,
    database: Optional[str] = None,
    user: Optional[str] = None,
    password: Optional[str] = None
) -> bool:
    """Create the purchased_parts_materials table in PostgreSQL.

    Uses centralized db_config module for credentials. Environment variables:
        POSTGRES_HOST, POSTGRES_PORT, POSTGRES_DB, POSTGRES_USER, POSTGRES_PASSWORD

    Args:
        host: Database host override
        port: Database port override
        database: Database name override
        user: Database user override
        password: Database password override

    Returns:
        True if migration succeeded, False otherwise
    """
    try:
        import psycopg2
    except ImportError:
        print("ERROR: psycopg2 not available. Install with: pip install psycopg2-binary")
        return False

    try:
        # Get connection params from centralized config
        try:
            from mira.core.db_config import get_db_connection_params
            conn_params = get_db_connection_params(
                host=host, port=port, database=database, user=user, password=password
            )
        except ImportError:
            import os
            conn_params = {
                "host": host or os.environ.get("POSTGRES_HOST", "localhost"),
                "port": port or int(os.environ.get("POSTGRES_PORT", "5432")),
                "database": database or os.environ.get("POSTGRES_DB", "mira"),
                "user": user or os.environ.get("POSTGRES_USER", "postgres"),
                "password": password or os.environ.get("POSTGRES_PASSWORD", "postgres"),
            }
        conn = psycopg2.connect(**conn_params)
        cur = conn.cursor()
        cur.execute(PURCHASED_PARTS_SCHEMA)
        conn.commit()
        cur.close()
        conn.close()
        print(f"SUCCESS: Created/updated purchased_parts_materials table in {database}")
        return True
    except Exception as e:
        print(f"ERROR: Migration failed: {e}")
        return False


if __name__ == "__main__":
    import sys

    # Check for migration command
    if len(sys.argv) > 1 and sys.argv[1] == "migrate":
        print("Running database migration for purchased_parts_materials table...")
        success = migrate_purchased_parts_table()
        sys.exit(0 if success else 1)

    # Quick test of the utilities
    print("=== SolidWorks Suffix Stripper Test ===")
    test_cases = [
        "6061-T6 (SS)",
        "7075-T73 (SS,SN)",
        "A286 (SN)",
        "6061-T6",
        "INCONEL 718 ( SS )",
    ]
    for tc in test_cases:
        print(f"  {tc!r} -> {clean_solidworks_designation(tc)!r}")

    print("\n=== Embedded Material Parser Test ===")
    desc_cases = [
        ("HELICAL INSERT, 6-32 X .138\", 18-8 SS", "91732A355"),
        ("HELICOIL, 18-8 Stainless Steel", "HCC-138-40-138"),
        ("SCREW, FLAT HEAD, CRES", "NAS1352C3-8"),
        ("WASHER, FLAT, 304 SS", "NAS1149"),
        ("ROD CONNECTOR", "GPE-052-1"),
    ]
    for desc, pn in desc_cases:
        result = parse_embedded_material(desc, pn)
        print(f"  {desc!r} -> {result.designation!r} (conf={result.confidence:.2f})")

    print("\n=== Part Number Classification Test ===")
    pn_cases = [
        ("GPE-051-1", "GPE"),
        ("GPE-A050-1", "GPE"),
        ("91732A355", "GPE"),
        ("FH100-1M4-32-625", "GPE"),
        ("NAS1352C3-8", "GPE"),
        ("HCC-138-40-138", "GPE"),
    ]
    for pn, prefix in pn_cases:
        is_dwg = is_drawing_reference(pn, prefix)
        print(f"  {pn}: {'DRAWING' if is_dwg else 'HARDWARE'}")

    print("\n=== Purchased Part Lookup Test ===")
    lookup = PurchasedPartLookup()
    lookup_cases = [
        ("91732A355", "HELICAL INSERT"),
        ("89015K28", "SHIM"),
        ("HCC-138-40-138", "HELICOIL"),
        ("FH100-1M4-32-625", "SCREW, FLAT HEAD"),
    ]
    for pn, desc in lookup_cases:
        result = lookup.lookup(pn, desc)
        print(f"  {pn}: {result.material_designation!r} ({result.source}, conf={result.confidence:.2f})")
