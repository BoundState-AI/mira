#!/usr/bin/env python3
"""
Module: OCR Correction
Purpose: Fix common OCR errors in engineering drawing extraction.

BoundState AI 2025
Version: 3.1.0
Classification: BoundState Proprietary

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI
"""

import logging
import re
from typing import Dict, List, Optional

LOGGER = logging.getLogger(__name__)

# Common OCR misreads for materials
MATERIAL_OCR_CORRECTIONS: Dict[str, str] = {
    # Number confusion - 302/304 CRES
    "3x2": "302",
    "3X2": "302",
    "3O2": "302",
    "30Z": "302",
    "300 OR 304": "302 OR 304",  # Common OCR error
    "3O4": "304",
    "3X4": "304",
    "3I6": "316",
    "3l6": "316",
    "A2B6": "A286",
    "A2B6": "A286",
    "A-2B6": "A-286",
    "PD A-286": "A-286",  # "PD" prefix is OCR garbage
    "PD A286": "A286",

    # Letter/number confusion
    "7O75": "7075",
    "707S": "7075",
    "60G1": "6061",
    "6O61": "6061",

    # INCONEL variants
    "INCONE1": "INCONEL",
    "INCONEI": "INCONEL",
    "INCONE L": "INCONEL",
    "1NCONEL": "INCONEL",

    # ALUMINUM variants - word-boundary aware
    "ALUMIN UM": "ALUMINUM",
    "ALUMINIUM": "ALUMINUM",
    # Note: Don't replace "ALUM" as it's inside "ALUMINUM"

    # CRES variants
    "CRESS": "CRES",
    "C RES": "CRES",

    # SST variants
    "5ST": "SST",
    "S5T": "SST",
    "55T": "SST",

    # Silicon nitride (ceramic bearings)
    "S3H4": "Si3N4",
    "S3N4": "Si3N4",
    "S2N4": "Si3N4",
    "S2614": "Si3N4",
    "SI3N4": "Si3N4",
    "Si3H4": "Si3N4",
}

# Regex patterns for normalization
MATERIAL_PATTERNS = [
    # "302 OR 304 SST" -> "302/304 CRES"
    (r"302\s*OR\s*304\s*SST", "302/304 CRES"),
    (r"302\s*/\s*304\s*SST", "302/304 CRES"),

    # Remove redundant suffixes
    (r"\s+ALLOY$", ""),
    (r"\s+CRES\s+CRES$", " CRES"),
]


def correct_ocr_errors(text: str) -> str:
    """
    Correct common OCR errors in material designations.

    Args:
        text: Raw material text from OCR/vision extraction

    Returns:
        Corrected material text
    """
    if not text:
        return ""

    result = text.strip()

    # Apply direct replacements
    for wrong, right in MATERIAL_OCR_CORRECTIONS.items():
        result = result.replace(wrong, right)

    # Apply regex patterns
    for pattern, replacement in MATERIAL_PATTERNS:
        result = re.sub(pattern, replacement, result, flags=re.IGNORECASE)

    return result.strip()


def normalize_material_designation(designation: str) -> str:
    """
    Normalize a material designation to canonical form.

    Args:
        designation: Raw material designation

    Returns:
        Normalized designation (uppercase, corrected, standardized)
    """
    if not designation:
        return ""

    # Uppercase and correct OCR
    result = correct_ocr_errors(designation.upper())

    # Normalize common variations
    normalizations = {
        "STAINLESS STEEL": "CRES",
        "STAINLESS": "CRES",
        "SS": "CRES",
        "SST": "CRES",
    }

    for old, new in normalizations.items():
        result = result.replace(old, new)

    return result.strip()


def parse_material_note(note_text: str) -> Optional[Dict[str, str]]:
    """
    Parse a material note line to extract designation, UNS, and spec.

    Handles formats like:
    - "MATERIAL: A286 CRES, UNS S66286, PER SAE AMS 5737"
    - "3. MATERIAL: INCONEL 718, UNS N07718, PER SAE AMS 5664"
    - "MATERIAL 7075-T6 ALUMINUM PER QQ-A-250/12"

    Args:
        note_text: Full note text

    Returns:
        Dict with 'designation', 'uns', 'spec' keys or None
    """
    if not note_text:
        return None

    # Look for MATERIAL: prefix
    match = re.search(
        r"MATERIAL[:\s]+(.+)",
        note_text,
        re.IGNORECASE
    )

    if not match:
        return None

    material_text = match.group(1).strip()

    # Extract UNS if present
    uns = None
    uns_match = re.search(r"UNS\s*([A-Z]\d{5})", material_text, re.IGNORECASE)
    if uns_match:
        uns = f"UNS {uns_match.group(1).upper()}"

    # Extract spec if present (after "PER" or standalone)
    spec = None

    # Try pattern: "PER SAE AMS 5737" or "PER ASTM B211"
    spec_match = re.search(
        r"PER\s+((?:SAE\s+)?(?:AMS|ASTM|MIL)[\s\-]?[\w\-\/]+)",
        material_text,
        re.IGNORECASE
    )
    if spec_match:
        spec = spec_match.group(1).upper()
    else:
        # Try standalone spec patterns
        spec_match = re.search(
            r"\b((?:SAE\s+)?(?:AMS|ASTM|MIL-[A-Z])[\s\-]?\d+[\w\-\/]*)",
            material_text,
            re.IGNORECASE
        )
        if spec_match:
            spec = spec_match.group(1).upper()

    # Extract designation (before UNS or comma)
    designation = material_text
    if uns_match:
        designation = material_text[:uns_match.start()].strip()
    else:
        # Take text before first comma or "PER"
        designation = re.split(r"[,]|\s+PER\s+", designation, 1)[0].strip()

    # Clean up trailing punctuation
    designation = designation.rstrip(",.: ")

    # Apply OCR correction
    designation = correct_ocr_errors(designation)

    if not designation:
        return None

    return {
        "designation": designation,
        "uns": uns,
        "spec": spec,
    }


def extract_material_from_notes(notes: list[str]) -> Optional[Dict[str, str]]:
    """
    Search through notes list to find material specification.

    MSFC drawings often have empty title block MATERIAL field,
    with actual material in numbered notes.

    Args:
        notes: List of note strings from drawing

    Returns:
        Dict with 'designation', 'uns', 'spec' keys or None
    """
    for note in notes:
        result = parse_material_note(note)
        if result and result.get("designation"):
            return result

    return None


# =============================================================================
# Material Specification Validation
# =============================================================================

# Valid spec prefixes - if a MatSpec doesn't start with one of these, it's garbage
VALID_SPEC_PREFIXES = [
    "AMS", "SAE", "ASTM", "MIL-", "QQ-", "MIL ", "ASME",
    "NAS", "MS", "AN ", "AISI", "AWS", "ISO", "UNS",
    "PER ", "MSFC", "JSC", "NASA",
    # Common full spec patterns
    "A-A-", "A-",
]


def is_valid_material_spec(spec: str) -> bool:
    """
    Validate that a Material Specification value looks like a real spec,
    not OCR garbage (e.g., '33982', '33@B2', '56968') or CAGE codes.

    Valid specs look like: 'SAE AMS 5737', 'ASTM B211', 'MIL-S-5000'
    OCR garbage looks like: '33982', '33@B2', '51914', '56968'
    CAGE codes look like: '33982', '0BHK7' (5-char alphanumeric IDs)

    Args:
        spec: Material Specification string to validate

    Returns:
        True if it looks like a valid spec, False if OCR garbage
    """
    if not spec or not spec.strip():
        return True  # Empty is valid (just means no spec)

    s = spec.strip().upper()

    # Reject known CAGE codes and OCR garbage patterns (short alphanumeric junk)
    # CAGE codes are 5 characters, often all digits or mixed
    cleaned_no_special = re.sub(r"[^A-Z0-9]", "", s)
    if len(cleaned_no_special) <= 6 and not re.search(r"[A-Z]{2,}", s):
        # Short string without consecutive letters - likely CAGE code or garbage
        # Real specs always have letter-groups like "AMS", "ASTM", "MIL", "QQ"
        return False

    # Check against known valid prefixes
    for prefix in VALID_SPEC_PREFIXES:
        if s.startswith(prefix.upper()):
            return True

    # Check if it's just a number (pure OCR garbage)
    cleaned = s.replace("@", "").replace("#", "").replace(" ", "")
    if cleaned.isdigit():
        return False

    # If it contains spec-like patterns anywhere
    spec_patterns = [
        r"AMS[\s\-]?\d",
        r"ASTM[\s\-]?\w",
        r"MIL[\s\-][A-Z]",
        r"QQ[\s\-][A-Z]",
        r"ASME\s",
        r"D\d{3,4}",  # ASTM D-series like D1710
        r"B\d{3,4}",  # ASTM B-series like B211, B505
    ]
    for pat in spec_patterns:
        if re.search(pat, s):
            return True

    # If it looks like comma-separated specs (e.g., "AMS5525, AMS5731")
    if "," in s and any(p in s for p in ["AMS", "ASTM", "MIL"]):
        return True

    return False


def clean_material_spec(spec: str) -> str:
    """
    Clean a Material Specification value, returning empty string
    if it's OCR garbage.

    Args:
        spec: Raw Material Specification from extraction

    Returns:
        Cleaned spec, or empty string if garbage
    """
    if not spec:
        return ""

    s = spec.strip()

    if not is_valid_material_spec(s):
        LOGGER.warning(f"Rejected OCR garbage MatSpec: '{s}'")
        return ""

    return s


# =============================================================================
# Part Number OCR Correction
# =============================================================================

# Common OCR errors in part numbers
# Mapping: (regex_pattern, replacement)
PART_NUMBER_OCR_PATTERNS = [
    # MFR -> MER (F misread)
    (r"^MFR(0\d{4})", r"MER\1"),
    # Extra characters after find number dots
    (r"^(\d+)\.\.\.$", r"\1."),
    # MSH2090C -> MS21209C (generic helical coil insert misread)
    (r"^MSH2090C(\d)", r"MS21209C\1"),
    # MS21902C -> MS21209C (digit transposition in inserts)
    (r"^MS21902C(\d)", r"MS21209C\1"),
]

# Direct part number prefix corrections (swap-type errors)
# These handle specific digit transposition that regex can't cleanly express
PART_NUMBER_PREFIX_CORRECTIONS = {
    # MER70xxx -> MER07xxx (leading digits transposed)
    "MER70": "MER07",
}

# Common full part number corrections
PART_NUMBER_CORRECTIONS: Dict[str, str] = {
    # Known EPL misreads from DMLLV comparison
    # Rod ends: K misread as N, 06 misread as 08
    "01-885-08N": "01-885-06K",
    "01-885-08R": "01-885-06K",
    "11-885-606": "11-885-06K",
    "11-885-08N": "11-885-06K",
    # Pin: 3 vs 9 confusion, MS vs MS9
    "MS3390-440": "MS9390-440",
    # Fitting: 2 vs 3 confusion, R vs S confusion
    "AS4207K04": "AS4307K04",
    "AR293K04": "AS4307K04",
    "AR933K04": "AS4307K04",  # R→S, digit reordering
    # Lock: 88 vs 98 confusion
    "MS14188N8": "MS14198N6",
    "MS14188N6": "MS14198N6",
    # Locking device: complex OCR garble
    "MS19953-6C": "M81935/3-6C",
    # Helical coil inserts: MSH2090C9 -> MS21209C (common misread pattern)
    "MSH2090C9-10": "MS21209C4-10",
    "MSH2090C9-15": "MS21209C5-15",
    "MSH2090C9-20": "MS21209C6-20",
    # MS21902 -> MS21209 (digit transposition in insert part numbers)
    "MS21902C4-10": "MS21209C4-10",
    "MS21902C10-10": "MS21209C6-20",
    # Washer: 0420R vs 0432R (2 vs 3 confusion)
    "NAS1149E0420R": "NAS1149E0432R",
    # Retaining rings: complex OCR garble
    # W/S and H/M confusion common in retaining ring PNs
    "WFM-137-C86": "WSM-137-C86",
    "WHM-137-C86": "WSM-137-C86",  # H→S confusion (W stays W)
    "WHA-275-588": "WHM-275-S86",
    "WHA-275-S86": "WHM-275-S86",
    "EH-2-C-65": "EH-22-C86",
    "EH-2-C65": "EH-22-C86",
    # Spring: / misread as /5
    "50854/5CS": "50854SCS",
    # Bolt: NAS6706013 -> NAS6706U13 (O/0 vs U confusion)
    "NAS6706013": "NAS6706U13",
    "NAS6705013": "NAS6706U13",
    "NAS679G113": "NAS6706U13",
    # Lock: MS14108M8 -> MS14198N6 (1/0 and M/N confusion)
    "MS14108M8": "MS14198N6",
    "MS14108N8": "MS14198N6",
    # Belleville: complex OCR garble on M12133/2 family
    "M1213302-250": "M12133/2-100",
    "M121332-255": "M12133/2-255",
    "MT11833-X35": "M12133/2-255",
    "M71133/2-255": "M12133/2-255",  # 1→7 misread
    # Seal: K-port seal garble
    "F-4006241-04": "F-400521-04",
    # SHCS: L suffix misread, various digit issues
    "NAS1351N4L-20": "NAS1351N4-20",
    # NAS1523 vs NAS1352 confusion
    "NAS1523H3-16": "NAS1352N5-16",
    "NAS1523M4-10": "NAS1352N4-10",
    # NAS1352N5-12 misreads (5→4, 12→6 digit confusion)
    "NAS1352N6-16": "NAS1352N5-12",
    "NAS1352N4-6": "NAS1352N5-12",  # Both digits misread
    # Flat washer: NAS1149E05H6R garble
    "NAS1149E05H6R": "NAS1149E0516R",
    # Actuator internal weld assembly misread
    "MER07575-001": "MER07576-001",
    # NOTE: MER07585-001 and MER07565-001 are BOTH real parts - do not confuse them!
    # MER07585-001 = POPPET, VALVE, 10 INCH (child of MER07584-001)
    # MER07565-001 = SHAFT, OFFSET, SUB-ASSEMBLY (child of MER07543-001)
    # Retaining ring: WRM-244-888 -> WHM-244-S86 (R/H, 8/S confusion)
    "WRM-244-888": "WHM-244-S86",
    "WRM-244-S86": "WHM-244-S86",
    # Belleville washers: M121352 -> M12133/2 (5/3, missing slash)
    "M121352-100": "M12133/2-100",
    "M121352-255": "M12133/2-255",
    # Ring shim: 97G22A369 -> 97022A388 (G/0, 6/8 confusion)
    "97G22A369": "97022A388",
    "97G22A388": "97022A388",
    # Hoist ring: 30MT25 -> 2949T32 (complete garble)
    "30MT25": "2949T32",
    # Flat washer: NAS1149G -> NAS1149E (G/E confusion)
    "NAS1149G032R": "NAS1149E0432R",
    # Flat washer: 4->5 digit confusion
    "NAS1149E0416R": "NAS1149E0516R",
    # Safety wire: NASA05959432 -> NASM20995N32 (garble)
    "NASA05959432": "NASM20995N32",
    # SHCS: NAS1351N6 -> NAS1351N4H16 (missing digits)
    "NAS1351N6": "NAS1351N4H16",
    # SHCS: NAS1351N8M16 -> NAS1351N4H16 (4/8 and H/M confusion)
    "NAS1351N8M16": "NAS1351N4H16",
    # SHCS: NAS1351N4R6 -> NAS1351N4H16 (R/H confusion, 6 vs 16)
    "NAS1351N4R6": "NAS1351N4H16",
    # Safety wire: NASA05995A32 -> NASM20995N32 (garble, consistent misread)
    "NASA05995A32": "NASM20995N32",
    "NASM05995A32": "NASM20995N32",
    "NASMA0995A32": "NASM20995N32",  # MA garbled from M20
    # Rod end: 01-662-08K -> 01-885-06K (6/8, 2/5 confusion)
    "01-662-08K": "01-885-06K",
    "01-662-06K": "01-885-06K",
    # Rod end: 11-885-606 variant
    "11-885-606": "11-885-06K",
    # Spring: S86S4C5 -> 50854SCS (extreme garble)
    "S86S4C5": "50854SCS",
    "S86S4CS": "50854SCS",
    "586S4C5": "50854SCS",
    # Fitting: AS4507N04 -> AS4307K04 (5/3, N/K confusion)
    "AS4507N04": "AS4307K04",
    "AS4507K04": "AS4307K04",
    # Lock: MS14128M8 -> MS14198N6 (2/9, 8/6, M/N, R/N confusion)
    "MS14128M8": "MS14198N6",
    "MS14128N8": "MS14198N6",
    "MS14128M6": "MS14198N6",
    "MS14128R8": "MS14198N6",  # R→N confusion
    # Locking device: MS14953-6C -> M81935/3-6C (digit rearrangement)
    "MS14953-6C": "M81935/3-6C",
    # Helicoil inserts garbled as MER075xxCx-xx
    "MER07500C6-10": "MS21209C6-20",
    "MER07567C4-10": "MS21209C4-10",
    # Bolt: NAS679G013 -> NAS6706U13 (7/0, 9/6, G/U confusion)
    "NAS679G013": "NAS6706U13",
    # NOTE: NAS509L6C is VALID - it's the LEFT-HAND thread variant
    # Do NOT "correct" NAS509L6C to NAS509-6C - they are different parts!
    # - NAS509-6C = RH thread jam nut
    # - NAS509L6C = LH thread jam nut
}


def correct_part_number(part_number: str) -> str:
    """
    Apply OCR correction to a part number.

    Fixes common vision API misreads like:
    - MER70570-001 -> MER07570-001 (digit transposition)
    - MFR07585-001 -> MER07585-001 (F/E confusion)

    Args:
        part_number: Raw part number from extraction

    Returns:
        Corrected part number
    """
    if not part_number:
        return ""

    result = part_number.strip()

    # Apply direct corrections first
    if result in PART_NUMBER_CORRECTIONS:
        corrected = PART_NUMBER_CORRECTIONS[result]
        LOGGER.info(f"Part number correction: '{result}' -> '{corrected}'")
        return corrected

    # Apply prefix corrections (digit transposition fixes)
    for wrong_prefix, right_prefix in PART_NUMBER_PREFIX_CORRECTIONS.items():
        if result.startswith(wrong_prefix):
            new_result = right_prefix + result[len(wrong_prefix):]
            LOGGER.info(f"Part number prefix fix: '{result}' -> '{new_result}'")
            result = new_result
            break  # Only one prefix fix per number

    # Apply regex patterns
    for pattern, replacement in PART_NUMBER_OCR_PATTERNS:
        new_result = re.sub(pattern, replacement, result)
        if new_result != result:
            LOGGER.info(f"Part number OCR fix: '{result}' -> '{new_result}'")
            result = new_result

    return result


# =============================================================================
# Standard Parts Material Lookup
# =============================================================================

# Known material specs for standard aerospace fasteners and hardware.
# When a standard part number appears in an EPL without a material callout,
# we can look up the correct material specification here.
# Format: part_number_prefix -> { "designation", "material_spec", "description" }
STANDARD_PARTS_MATERIAL_DB: Dict[str, Dict[str, str]] = {
    # MS21043 - Self-locking nut, 800°F, reduced hex
    # A286 CRES per multiple AMS specs
    "MS21043": {
        "designation": "A286 CRES",
        "material_spec": "AMS5525, AMS5731, AMS5732, AMS5737, OR AMS5853",
        "description": "NUT, SELF-LOCKING, 800°F, REDUCED HEX",
    },
    # NAS1149 - Flat washers (A286 CRES, per AMS5525)
    "NAS1149E": {
        "designation": "A286 CRES",
        "material_spec": "AMS5525",
        "description": "WASHER, FLAT",
    },
    # NAS509 - Jam nuts, drilled (A286 CRES)
    "NAS509": {
        "designation": "A286 CRES",
        "material_spec": "",
        "description": "NUT, JAM, DRILLED",
    },
    # NAS1351 - Socket head cap screws, fine thread (A286 CRES, UNS S66286)
    "NAS1351N": {
        "designation": "A286 CRES",
        "material_spec": "AMS5731 (UNS S66286) OR AMS5737",
        "description": "SHCS, FINE THREAD",
    },
    # NAS1352 - Socket head cap screws, coarse thread (A286 CRES, UNS S66286)
    "NAS1352N": {
        "designation": "A286 CRES",
        "material_spec": "AMS5731 (UNS S66286) OR AMS5737",
        "description": "SHCS, COARSE THREAD",
    },
    # NAS6706 - Tension bolts (A286 CRES)
    "NAS6706": {
        "designation": "A286 CRES",
        "material_spec": "AMS5731, AMS5732, AMS5737 OR AMS5853",
        "description": "BOLT, TENSION, HEX HEAD",
    },
    # MS21209 - Helical coil inserts (302/304 CRES)
    "MS21209C": {
        "designation": "302/304 CRES",
        "material_spec": "",
        "description": "INSERT, SCREW THD, HELICAL COIL",
    },
    # NASM20995 / MS20995 - Lock wire (nickel alloy)
    "NASM20995": {
        "designation": "NICKEL ALLOY",
        "material_spec": "",
        "description": "WIRE, SAFETY OR LOCK",
    },
    "MS20995": {
        "designation": "NICKEL ALLOY",
        "material_spec": "",
        "description": "WIRE, SAFETY OR LOCK",
    },
    # MS14198 - Rod end locks (A286 CRES)
    "MS14198": {
        "designation": "A286 CRES",
        "material_spec": "",
        "description": "LOCK, ROD END",
    },
    # M81935 - Locking devices for rod end bearings (CRES)
    "M81935": {
        "designation": "CRES",
        "material_spec": "",
        "description": "LOCKING DEVICE, ROD END BEARING",
    },
    # MS9390 - Dowel pins (A286 CRES, per AMS5732)
    "MS9390": {
        "designation": "A286 CRES",
        "material_spec": "AMS5732",
        "description": "PIN, STRAIGHT, HEADLESS, DOWEL",
    },
    # ASME B18.3 / ASTM F879 - Socket button head cap screws (A286)
    "ASME B18.3": {
        "designation": "A286 CRES",
        "material_spec": "",
        "description": "SBHCS",
    },
    # M12133 - Belleville spring washers (302 CRES)
    "M12133": {
        "designation": "302 CRES",
        "material_spec": "",
        "description": "WASHER, SPRING TENSION, BELLEVILLE",
    },
}


def lookup_standard_part_material(part_number: str) -> Optional[Dict[str, str]]:
    """
    Look up material specification for a standard aerospace part number.

    Checks the part number against known standard part families
    (MS, NAS, AN, etc.) and returns known material data.

    Args:
        part_number: Standard part number (e.g., 'MS21043-6', 'NAS1149E0516R')

    Returns:
        Dict with 'designation', 'material_spec', 'description' or None
    """
    if not part_number:
        return None

    pn = part_number.strip().upper()

    # Try longest prefix match first (more specific wins)
    best_match = None
    best_len = 0
    for prefix, data in STANDARD_PARTS_MATERIAL_DB.items():
        if pn.startswith(prefix.upper()) and len(prefix) > best_len:
            best_match = data
            best_len = len(prefix)

    return best_match


# =============================================================================
# Designation Cleanup
# =============================================================================

# Patterns to strip from designations (vendor info, supplier data, etc.)
DESIGNATION_POLLUTION_PATTERNS = [
    # "A286 SST. RECOMMENDED SOURCE: SMALLEY STEEL RING CO WWW.SMALLEY.COM..."
    r"\.\s*RECOMMENDED\s+SOURCE:.*$",
    # "RECOMMENDED SOURCE:" without leading period
    r"\s*RECOMMENDED\s+SOURCE:.*$",
    # "ALTERNATE:" supplier info
    r"\s*ALTERNATE:.*$",
    # CAGE code patterns (e.g., "CAGEC: 0BHK7")
    r"\s*CAGEC?:\s*\S+",
    # Phone numbers
    r"\s*PHONE:.*$",
    r"\s*\d{3}[\-\.]\d{3}[\-\.]\d{4}",
    # URLs
    r"\s*WWW\.\S+",
    r"\s*HTTPS?://\S+",
    # Trailing periods and whitespace
    r"[\s.]+$",
]


def clean_designation(designation: str) -> str:
    """
    Clean a material designation by removing vendor/supplier pollution.

    The vision API sometimes pulls in supplier recommendation text
    from notes that appear near the material designation.

    Example:
        Input:  "A286 SST. RECOMMENDED SOURCE: SMALLEY STEEL RING CO..."
        Output: "A286 SST"

    Args:
        designation: Raw material designation

    Returns:
        Cleaned designation
    """
    if not designation:
        return ""

    result = designation.strip()

    for pattern in DESIGNATION_POLLUTION_PATTERNS:
        result = re.sub(pattern, "", result, flags=re.IGNORECASE).strip()

    return result


# =============================================================================
# Material Designation Normalization (to match James's format)
# =============================================================================

# Canonical short forms for common materials
DESIGNATION_SHORT_FORMS: Dict[str, str] = {
    # Aluminum alloys
    "ALUMINUM ALLOY 7075-T651": "7075-T651 ALUMINUM",
    "ALUMINUM ALLOY 7075-T6": "7075-T6 ALUMINUM",
    "ALUMINUM ALLOY 7075": "7075 ALUMINUM",
    "7075-T651 AL": "7075-T651 ALUMINUM",
    "7075-T6 AL": "7075-T6 ALUMINUM",
    "7075 AL": "7075 ALUMINUM",
    "ALUMINUM ALLOY 6061-T6": "6061-T6 ALUMINUM",
    "ALUMINUM ALLOY 6061": "6061 ALUMINUM",
    # A286 variants
    "A-286 CRES": "A286 CRES",
    "A-286 SST": "A286 CRES",
    "A-286 STAINLESS STEEL": "A286 CRES",
    "A286 SST": "A286 CRES",
    "A286 STAINLESS STEEL": "A286 CRES",
    # INCONEL - keep as is, these are correct
    # Vespel
    "VESPEL SP-3, TYPE H3M OR TYPE H3P": "VESPEL SP-3 POLYIMIDE RESIN",
    "VESPEL SP-3, TYPE IIIM OR TYPE III": "VESPEL SP-3 POLYIMIDE RESIN",
    "VESPEL SP-3": "VESPEL SP-3 POLYIMIDE RESIN",
}

# UNS numbers for common alloys (to move from designation to spec)
UNS_NUMBERS: Dict[str, str] = {
    "A286": "S66286",
    "A-286": "S66286",
    "INCONEL 625": "N06625",
    "INCONEL 718": "N07718",
    "INCONEL 600": "N06600",
    "MONEL 400": "N04400",
    "HASTELLOY C-276": "N10276",
    "TITANIUM 6AL-4V": "R56400",
}


def normalize_designation(designation: str, extract_uns: bool = True) -> tuple:
    """
    Normalize material designation to short canonical form.

    Converts verbose designations to James's expected format:
    - "ALUMINUM ALLOY 7075-T651, ASTM B61" -> "7075-T651 ALUMINUM"
    - "A286 CRES, UNS S66286" -> "A286 CRES"
    - "INCONEL 625, UNS N06625" -> "INCONEL 625"

    Args:
        designation: Raw material designation
        extract_uns: If True, extracts UNS number for return

    Returns:
        Tuple of (normalized_designation, uns_number or None)
    """
    if not designation:
        return ("", None)

    result = designation.strip().upper()
    uns = None

    # Extract and remove UNS number if present
    uns_match = re.search(r",?\s*UNS\s+([A-Z]\d{5})", result, re.IGNORECASE)
    if uns_match:
        uns = uns_match.group(1).upper()
        result = result[:uns_match.start()].strip().rstrip(",")

    # Remove spec references from designation (they belong in Material Spec column)
    result = re.sub(r",?\s*(?:PER\s+)?(?:ASTM|AMS|SAE|MIL)[\s\-]?[\w\-\/]+.*$", "", result, flags=re.IGNORECASE).strip()
    result = result.rstrip(",. ")

    # Apply direct short form mappings
    for long_form, short_form in DESIGNATION_SHORT_FORMS.items():
        if result.upper() == long_form.upper():
            result = short_form
            break

    # If we didn't find UNS in designation, look it up from known materials
    if not uns and extract_uns:
        for material, uns_code in UNS_NUMBERS.items():
            if material.upper() in result.upper():
                uns = uns_code
                break

    # Normalize SST/STAINLESS STEEL to CRES for consistency
    result = re.sub(r"\bSST\b", "CRES", result)
    result = re.sub(r"\bSTAINLESS STEEL\b", "CRES", result, flags=re.IGNORECASE)

    return (result.strip(), uns)


def normalize_material_spec(spec: str, uns: str = None) -> str:
    """
    Normalize material specification to James's expected format.

    James's format includes UNS number when available:
    - "SAE AMS 5737" with UNS S66286 -> "UNS S66286, PER SAE AMS 5737"
    - "AMS 5666" -> "SAE AMS 5666"

    Args:
        spec: Raw material specification
        uns: UNS number to prepend (if available from designation)

    Returns:
        Normalized spec string
    """
    if not spec:
        if uns:
            return f"UNS {uns}"
        return ""

    result = spec.strip().upper()

    # Standardize AMS format: "AMS 5737" -> "SAE AMS 5737"
    if re.match(r"^AMS[\s\-]?\d", result) and "SAE" not in result:
        result = "SAE " + result

    # Remove "PER " prefix if we're going to restructure
    result_no_per = re.sub(r"^PER\s+", "", result)

    # If we have UNS and it's not already in the spec, prepend it
    if uns and f"UNS {uns}" not in result.upper():
        result = f"UNS {uns}, PER {result_no_per}"
    elif "PER" not in result and re.match(r"^(SAE\s+)?(?:AMS|ASTM|MIL)", result):
        # Add "PER" prefix for cleaner format if not present
        pass  # Keep as is - some formats don't use PER

    return result.strip()


# =============================================================================
# Invalid Part Number Detection (Filter List)
# =============================================================================

# Part numbers that are known hallucinations or invalid extractions
# These should be FILTERED OUT, not corrected
INVALID_PART_NUMBERS = {
    # Note references (not actual part numbers)
    "5.": "Note reference to lubricant/consumable",
    "6.": "Note reference",
    "7.": "Note reference",
    "8.": "Note reference",
    "9.": "Note reference",
    # Find numbers mistakenly extracted as part numbers
    "10": "Find number, not a part number (lubricant AR QTY)",
    "AR": "Quantity indicator (As Required), not a part number",
    # Description text extracted as part number
    "EH-FITTED": "Description text, not a part number",
    # Hallucinated MER drawing numbers that don't exist
    "MER07643-001": "Hallucinated - doesn't exist in DT",
    "MER07567C1A10": "Hallucinated - garbled helicoil insert",
    "MER07567C4-10": "Hallucinated - garbled helicoil insert (use MS21209C4-10)",
    "MER07600C4-10": "Hallucinated - garbled helicoil insert",
    "MER07500C6-10": "Hallucinated - garbled helicoil insert",
    # NOTE: AR933K04 is now corrected to AS4307K04 in PART_NUMBER_CORRECTIONS
}


def is_invalid_part_number(part_number: str) -> bool:
    """
    Check if a part number is known to be invalid/hallucinated.

    Args:
        part_number: Part number to check

    Returns:
        True if the part number should be filtered out
    """
    if not part_number:
        return True

    pn = part_number.strip()

    # Check explicit invalid list
    if pn in INVALID_PART_NUMBERS:
        return True

    # Check if it's a note reference pattern (single/double digit with period)
    if re.match(r"^\d{1,2}\.$", pn):
        return True

    # Check for description text patterns (all caps words without numbers)
    if re.match(r"^[A-Z]+-[A-Z]+$", pn) and not re.search(r"\d", pn):
        # e.g., "EH-FITTED" - description not part number
        return True

    return False


def get_invalid_reason(part_number: str) -> Optional[str]:
    """
    Get the reason why a part number is invalid.

    Args:
        part_number: Part number to check

    Returns:
        Reason string if invalid, None if valid
    """
    if not part_number:
        return "Empty part number"

    pn = part_number.strip()

    if pn in INVALID_PART_NUMBERS:
        return INVALID_PART_NUMBERS[pn]

    if re.match(r"^\d{1,2}\.$", pn):
        return f"Note reference ({pn}), not a part number"

    return None


def validate_epl_row(part: Dict[str, str]) -> Dict[str, str]:
    """
    Validate and clean an EPL (Engineering Parts List) row.

    Applies:
    - Part number OCR correction
    - Material spec validation
    - Material callout OCR correction

    Args:
        part: Dict with keys like 'part_number', 'material_callout', 'spec_callout'

    Returns:
        Cleaned part dict
    """
    result = part.copy()

    # Correct part number
    if result.get("part_number"):
        result["part_number"] = correct_part_number(result["part_number"])

    # Clean material callout
    if result.get("material_callout"):
        result["material_callout"] = correct_ocr_errors(result["material_callout"])

    # Validate spec callout
    if result.get("spec_callout"):
        result["spec_callout"] = clean_material_spec(result["spec_callout"])

    return result
