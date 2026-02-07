#!/usr/bin/env python3
"""
Module: Legacy Bok Loader
Purpose: Extract temperature range from text.

BoundState AI 2025
Version: 1.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Fran OpenAI 5 <noreply@openai.com>
Co-Authored-By: Grok 4.0 <noreply@x.ai>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: SWE-013, NASA-STD-8739.8B
Safety Critical: True
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .compatibility_models import (
    CompatibilityClass,
    CompatibilityRecord,
    DataClass,
    EnvelopeEvidence,
    EnvironmentEnvelope,
    GasType,
    MaterialFamilyKey,
    Phase,
    PropertyEvidence,
    PropertyKey,
)


logger = logging.getLogger(__name__)

__all__ = [
    "load_legacy_h2_bok",
    "load_legacy_o2_bok",
    "convert_legacy_section_to_record",
    "extract_material_mentions",
    "extract_temperature_mentions",
    "extract_pressure_mentions",
]


# ---------------------------------------------------------------------------
# Standard Source Documents
# ---------------------------------------------------------------------------

H2_SOURCE_DOCUMENTS = {
    "19970033338.pdf": "NSS 1740.16 (NASA Hydrogen Safety Standard)",
    "SAND2012_7321.pdf": "SAND2012-7321 (Sandia H2 Materials Compatibility)",
    "20160005654.pdf": "NASA Technical Memorandum (H2 Safety)",
    "20160008869.pdf": "NASA Technical Memorandum (H2 Systems)",
}

O2_SOURCE_DOCUMENTS = {
    "6001b.pdf": "NASA-STD-6001B (Flammability, Offgassing, Compatibility)",
    "6016.pdf": "NASA-STD-6016 (Oxygen Compatibility Standards)",
    "KSC-KTI-5210C.pdf": "KSC-KTI-5210C (O2 Compatibility)",
    "JSC-27301F MUA.pdf": "JSC-27301F (MUA Guidelines)",
    "ASTM_G94.pdf": "ASTM G94 (O2 Compatibility Test Methods)",
    "ASTM_MNL36.pdf": "ASTM MNL36 (O2 Compatibility Manual)",
}


# ---------------------------------------------------------------------------
# Pattern Extraction Helpers
# ---------------------------------------------------------------------------

# Temperature patterns
TEMP_PATTERNS = [
    r"(-?\d+\.?\d*)\s*(?:°|degrees?)\s*[FC]",
    r"(-?\d+\.?\d*)\s*K(?:elvin)?",
    r"(-?\d+\.?\d*)\s*(?:to|through|-)\s*(-?\d+\.?\d*)\s*(?:°|degrees?)\s*[FC]",
    r"(?:temperature|temp)\s*(?:of|at|:)?\s*(-?\d+\.?\d*)",
    r"cryogenic",  # Implies LH2 temps (-423°F)
    r"ambient",    # Implies ~70°F
]

# Pressure patterns
PRESSURE_PATTERNS = [
    r"(\d+\.?\d*)\s*(?:psia|psig|psi)",
    r"(\d+\.?\d*)\s*(?:MPa|kPa|bar|atm)",
    r"(\d+\.?\d*)\s*(?:to|through|-)\s*(\d+\.?\d*)\s*(?:psia|psig|psi)",
    r"(?:pressure|press)\s*(?:of|at|:)?\s*(\d+\.?\d*)",
]

# Material family patterns (for tagging, NOT for identity)
MATERIAL_FAMILY_PATTERNS = {
    MaterialFamilyKey.AUSTENITIC_STAINLESS: [
        r"(?:304|316|321|347)\s*(?:SS|stainless)",
        r"austenitic\s+stainless",
        r"300\s*series\s+stainless",
    ],
    MaterialFamilyKey.NICKEL_ALLOY: [
        r"(?:inconel|monel|hastelloy)",
        r"nickel\s+alloy",
        r"ni-?\s*based\s+alloy",
    ],
    MaterialFamilyKey.ALUMINUM_ALLOY: [
        r"(?:6061|2024|2219|7075)\s*(?:aluminum|al)",
        r"aluminum\s+alloy",
    ],
    MaterialFamilyKey.TITANIUM_ALLOY: [
        r"(?:ti-?6al-?4v|ti-?6-?4)",
        r"titanium\s+alloy",
    ],
    MaterialFamilyKey.COPPER_ALLOY: [
        r"(?:copper|brass|bronze)",
        r"cu\s+alloy",
    ],
    MaterialFamilyKey.FLUOROPOLYMER: [
        r"(?:ptfe|teflon|viton)",
        r"fluoropolymer",
    ],
    MaterialFamilyKey.ELASTOMER: [
        r"(?:buna|nitrile|epdm|silicone)",
        r"elastomer",
        r"o-?ring",
    ],
}


def extract_temperature_mentions(text: str) -> Optional[Tuple[float, float]]:
    """Extract temperature range from text.

    Args:
        text: Text to search

    Returns:
        Tuple of (temp_min_f, temp_max_f) or None if not found
    """
    text_lower = text.lower()

    # Check for cryogenic indicator
    if "cryogenic" in text_lower or "lh2" in text_lower:
        return (-423.0, -423.0)  # LH2 boiling point

    if "ambient" in text_lower and "temperature" in text_lower:
        return (70.0, 70.0)

    # Try range patterns first
    range_match = re.search(
        r"(-?\d+\.?\d*)\s*(?:°|degrees?)?\s*(?:to|through|-)\s*(-?\d+\.?\d*)\s*(?:°|degrees?)?\s*([FC])",
        text,
        re.IGNORECASE,
    )
    if range_match:
        t1, t2, unit = float(range_match.group(1)), float(range_match.group(2)), range_match.group(3).upper()
        if unit == "C":
            t1 = t1 * 9 / 5 + 32
            t2 = t2 * 9 / 5 + 32
        return (min(t1, t2), max(t1, t2))

    # Try single temp patterns
    single_match = re.search(
        r"(-?\d+\.?\d*)\s*(?:°|degrees?)\s*([FC])",
        text,
        re.IGNORECASE,
    )
    if single_match:
        temp, unit = float(single_match.group(1)), single_match.group(2).upper()
        if unit == "C":
            temp = temp * 9 / 5 + 32
        return (temp, temp)

    return None


def extract_pressure_mentions(text: str) -> Optional[Tuple[float, float]]:
    """Extract pressure range from text.

    Args:
        text: Text to search

    Returns:
        Tuple of (pressure_min_psia, pressure_max_psia) or None if not found
    """
    # Try range patterns first
    range_match = re.search(
        r"(\d+\.?\d*)\s*(?:to|through|-)\s*(\d+\.?\d*)\s*(psia|psig|psi)",
        text,
        re.IGNORECASE,
    )
    if range_match:
        p1, p2 = float(range_match.group(1)), float(range_match.group(2))
        return (min(p1, p2), max(p1, p2))

    # Try single pressure patterns
    single_match = re.search(
        r"(\d+\.?\d*)\s*(psia|psig|psi)",
        text,
        re.IGNORECASE,
    )
    if single_match:
        pressure = float(single_match.group(1))
        return (pressure, pressure)

    return None


def extract_material_mentions(text: str) -> List[MaterialFamilyKey]:
    """Extract material family mentions from text.

    Note: This is for TAGGING purposes only, NOT for identity matching.
    Decisions must use validated material_key, not text extraction.

    Args:
        text: Text to search

    Returns:
        List of mentioned material families
    """
    text_lower = text.lower()
    found: List[MaterialFamilyKey] = []

    for family, patterns in MATERIAL_FAMILY_PATTERNS.items():
        for pattern in patterns:
            if re.search(pattern, text_lower):
                if family not in found:
                    found.append(family)
                break

    return found


def detect_compatibility_statement(text: str, gas_type: GasType) -> Optional[Tuple[CompatibilityClass, str]]:
    """Detect compatibility statements in BOK text.

    Args:
        text: Text to analyze
        gas_type: H2 or O2

    Returns:
        Tuple of (CompatibilityClass, reason) or None
    """
    text_lower = text.lower()

    # Incompatible indicators
    incompatible_phrases = [
        "shall not be used",
        "not recommended",
        "prohibited",
        "incompatible",
        "severe embrittlement",
        "severe degradation",
        "not suitable",
        "avoid",
    ]
    for phrase in incompatible_phrases:
        if phrase in text_lower:
            return (CompatibilityClass.INCOMPATIBLE, f"BOK states: '{phrase}'")

    # Compatible indicators (with caution - BOK alone can't grant COMPATIBLE)
    compatible_phrases = [
        "recommended for",
        "suitable for",
        "compatible with",
        "excellent resistance",
        "good resistance",
        "widely used",
        "preferred material",
    ]
    for phrase in compatible_phrases:
        if phrase in text_lower:
            # Note: This will be MARGINAL because BOK lacks direct evidence
            return (CompatibilityClass.MARGINAL, f"BOK indicates suitability: '{phrase}'")

    return None


# ---------------------------------------------------------------------------
# Legacy Section to Record Conversion
# ---------------------------------------------------------------------------


def convert_legacy_section_to_record(
    section: Dict[str, Any],
    gas_type: GasType,
    source_mapping: Dict[str, str],
) -> CompatibilityRecord:
    """Convert a legacy BOK section to CompatibilityRecord.

    CRITICAL: Legacy BOK chunks use data_class=BOK_PRECEDENT or DERIVED,
    which means they CANNOT unlock COMPATIBLE verdict alone.

    Args:
        section: Legacy section dict with doc_id, title, text, tags, etc.
        gas_type: H2 or O2
        source_mapping: Map of source_document to standard reference

    Returns:
        CompatibilityRecord in v2 schema
    """
    doc_id = section.get("doc_id", "")
    title = section.get("title", "")[:200]  # Truncate long titles
    text = section.get("text", "")
    source_doc = section.get("source_document", "unknown")
    page_num = section.get("page_number", 0)

    # Build record ID
    prefix = "H2BOK" if gas_type == GasType.H2 else "O2BOK"
    record_id = f"{prefix}:{doc_id}"

    # Extract environmental info from text
    temp_range = extract_temperature_mentions(text)
    pressure_range = extract_pressure_mentions(text)

    # Build environment envelope (mostly null for legacy BOK)
    env = EnvironmentEnvelope(
        temp_min_f=temp_range[0] if temp_range else None,
        temp_max_f=temp_range[1] if temp_range else None,
        pressure_min_psia=pressure_range[0] if pressure_range else None,
        pressure_max_psia=pressure_range[1] if pressure_range else None,
        phase=Phase.UNKNOWN,  # Legacy BOK rarely specifies phase
        concentration_pct=None,
    )

    env_evidence = EnvelopeEvidence(
        data_class=DataClass.DERIVED,  # Extracted from text, not from test data
        source_ref=f"{source_doc}:p{page_num}",
        confidence=0.5,  # Low confidence for text extraction
    )

    # Extract material families mentioned (for tagging)
    mentioned_families = extract_material_mentions(text)

    # Detect compatibility statements
    compat_result = detect_compatibility_statement(text, gas_type)
    if compat_result:
        compatibility, reason = compat_result
    else:
        compatibility = CompatibilityClass.INSUFFICIENT_DATA
        reason = f"BOK section from {source_doc}"

    # Build properties from text (if any explicit statements found)
    properties: List[PropertyEvidence] = []

    # Add a general BOK reference property
    standard_ref = source_mapping.get(source_doc, source_doc)
    properties.append(
        PropertyEvidence(
            property_key=(
                PropertyKey.H2_EMBRITTLEMENT_CLASS
                if gas_type == GasType.H2
                else PropertyKey.FLAMMABILITY_RATING
            ),
            value_text=f"See {standard_ref} section {section.get('section', '')}",
            source_ref=f"{source_doc}:p{page_num}",
            data_class=DataClass.BOK_PRECEDENT,
            confidence=0.7,
        )
    )

    return CompatibilityRecord(
        record_id=record_id,
        material_key="UNKNOWN",  # Legacy BOK doesn't have validated material keys
        material_name=title[:100] if title else f"BOK Section {doc_id}",
        material_type_key=235,  # Default to Metal (most common in BOK)
        material_family_key=mentioned_families[0] if mentioned_families else MaterialFamilyKey.UNKNOWN,
        gas_type=gas_type,
        environment=env,
        environment_evidence=env_evidence,
        compatibility=compatibility,
        reason=reason[:500],  # Truncate long reasons
        mitigation=None,
        properties=properties,
        standard_ref=standard_ref,
        test_report_id=None,  # BOK has no test reports
        source=f"BOK:{source_doc}",
    )


# ---------------------------------------------------------------------------
# Legacy BOK Loaders
# ---------------------------------------------------------------------------


def load_legacy_h2_bok(
    bok_dir: Path | str = Path("C:/BoundState/mira/databases/h2_bok"),
) -> Tuple[List[CompatibilityRecord], List[str]]:
    """Load legacy H2 BOK and convert to v2 CompatibilityRecords.

    Args:
        bok_dir: Directory containing legacy H2 BOK files

    Returns:
        Tuple of (records, warnings)
    """
    bok_dir = Path(bok_dir)
    sections_file = bok_dir / "h2_bok_sections.json"

    if not sections_file.exists():
        return [], [f"H2 BOK sections file not found: {sections_file}"]

    logger.info(f"Loading legacy H2 BOK from {sections_file}")

    with open(sections_file, "r", encoding="utf-8") as f:
        sections = json.load(f)

    records: List[CompatibilityRecord] = []
    warnings: List[str] = []

    for section in sections:
        try:
            record = convert_legacy_section_to_record(
                section,
                GasType.H2,
                H2_SOURCE_DOCUMENTS,
            )
            records.append(record)
        except Exception as e:
            warnings.append(
                f"Failed to convert H2 BOK section {section.get('doc_id', 'unknown')}: {e}"
            )

    logger.info(f"Loaded {len(records)} H2 BOK records, {len(warnings)} warnings")
    return records, warnings


def load_legacy_o2_bok(
    bok_dir: Path | str = Path("C:/BoundState/mira/databases/o2_bok"),
) -> Tuple[List[CompatibilityRecord], List[str]]:
    """Load legacy O2 BOK and convert to v2 CompatibilityRecords.

    Args:
        bok_dir: Directory containing legacy O2 BOK files

    Returns:
        Tuple of (records, warnings)
    """
    bok_dir = Path(bok_dir)
    sections_file = bok_dir / "o2_bok_sections.json"

    if not sections_file.exists():
        return [], [f"O2 BOK sections file not found: {sections_file}"]

    logger.info(f"Loading legacy O2 BOK from {sections_file}")

    with open(sections_file, "r", encoding="utf-8") as f:
        sections = json.load(f)

    records: List[CompatibilityRecord] = []
    warnings: List[str] = []

    for section in sections:
        try:
            record = convert_legacy_section_to_record(
                section,
                GasType.O2,
                O2_SOURCE_DOCUMENTS,
            )
            records.append(record)
        except Exception as e:
            warnings.append(
                f"Failed to convert O2 BOK section {section.get('doc_id', 'unknown')}: {e}"
            )

    logger.info(f"Loaded {len(records)} O2 BOK records, {len(warnings)} warnings")
    return records, warnings


# ---------------------------------------------------------------------------
# Combined Loader
# ---------------------------------------------------------------------------


def load_all_legacy_bok(
    h2_bok_dir: Path | str = Path("C:/BoundState/mira/databases/h2_bok"),
    o2_bok_dir: Path | str = Path("C:/BoundState/mira/databases/o2_bok"),
) -> Tuple[List[CompatibilityRecord], List[CompatibilityRecord], List[str]]:
    """Load both H2 and O2 legacy BOK indices.

    Args:
        h2_bok_dir: H2 BOK directory
        o2_bok_dir: O2 BOK directory

    Returns:
        Tuple of (h2_records, o2_records, all_warnings)
    """
    h2_records, h2_warnings = load_legacy_h2_bok(h2_bok_dir)
    o2_records, o2_warnings = load_legacy_o2_bok(o2_bok_dir)

    all_warnings = h2_warnings + o2_warnings

    logger.info(
        f"Total: {len(h2_records)} H2 records, {len(o2_records)} O2 records, "
        f"{len(all_warnings)} warnings"
    )

    return h2_records, o2_records, all_warnings
