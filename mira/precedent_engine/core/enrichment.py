#!/usr/bin/env python3
"""
Module: Enrichment
Purpose: [Automatically migrated - needs manual review]

BoundState AI 2025
Version: 1.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Fran OpenAI 5 <noreply@openai.com>
Co-Authored-By: Grok 4.0 <noreply@x.ai>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: SWE-013, NASA-STD-6016
Safety Critical: True
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Awaitable, Callable, Literal

from mira.precedent_engine.models.enums import DeviationType, ProgramFamily
from mira.precedent_engine.models.enriched import EnrichedMUA
from mira.precedent_engine.models.raw import RawMUARecord
import uuid


# =============================================================================
# Multi-Material Splitting
# =============================================================================

SIMPLE_MATERIAL_PATTERNS = [
    r"^(CRES|SS|Al|Ti|Inconel|Monel|Hastelloy)\s*\d+",
    r"^\d+\s*(CRES|SS|Al|Ti)",
    r"^[A-Z]{2,3}\s*\d{4}",  # e.g., "AMS 5662"
]

MULTI_MATERIAL_PROMPT = """Extract individual materials from this designation.
Return a JSON array of canonical material names.

Rules:
- Split on "and", commas, parentheses
- Normalize: "316L CRES" → "CRES 316L"
- Skip non-materials: "see application", "N/A", "various"
- For surface treatments, return base metal: "Chem Film on Al" → ["Aluminum"]

Input: "{material_designation}"

Return ONLY valid JSON array, no explanation."""


async def split_materials(
    designation: str,
    llm_call: Callable[[str], Awaitable[str]],
) -> list[str]:
    """
    Split multi-material designation into individual materials.

    Args:
        designation: Raw material designation string
        llm_call: Async function to call Bedrock LLM

    Returns:
        List of individual material names
    """
    if not designation or len(designation.strip()) < 2:
        return []

    designation = designation.strip()

    # Quick check for simple single-material cases
    for pattern in SIMPLE_MATERIAL_PATTERNS:
        if re.match(pattern, designation, re.IGNORECASE):
            return [designation]

    # Check for obvious multi-material indicators
    if not any(sep in designation for sep in [",", " and ", "/", "("]):
        return [designation]

    # Use LLM for complex cases
    prompt = MULTI_MATERIAL_PROMPT.format(material_designation=designation)

    try:
        response = await llm_call(prompt)
        materials = json.loads(response)
        if isinstance(materials, list) and all(isinstance(m, str) for m in materials):
            return [m.strip() for m in materials if m.strip()]
    except (json.JSONDecodeError, TypeError):
        pass

    # Fallback: simple split
    parts = re.split(r",\s*|\s+and\s+", designation)
    return [p.strip() for p in parts if p.strip() and len(p.strip()) > 2]


# =============================================================================
# Environment Normalization
# =============================================================================

MEDIA_NORMALIZATION: dict[str, tuple[str, float]] = {
    # Oxygen
    "oxygen": ("GOX", 99.5),
    "gox": ("GOX", 99.5),
    "lox": ("LOX", 99.5),
    "o2": ("GOX", 99.5),
    # Vacuum
    "vacuum": ("Vacuum", 0.0),
    "torr": ("Vacuum", 0.0),
    # Air
    "air": ("Air", 21.0),
    "cabin": ("Air", 21.0),
    "habitable": ("Air", 21.0),
    # Nitrogen
    "nitrogen": ("GN2", 0.0),
    "gn2": ("GN2", 0.0),
    "ln2": ("LN2", 0.0),
    # Hydrogen
    "hydrogen": ("GH2", 0.0),
    "gh2": ("GH2", 0.0),
    "lh2": ("LH2", 0.0),
    # Helium
    "helium": ("GHe", 0.0),
    "ghe": ("GHe", 0.0),
}


def normalize_environment(env: str | None) -> tuple[str | None, float]:
    """
    Normalize environment string to canonical media + O2%.

    Returns: (media, o2_pct)
    """
    if not env:
        return None, 21.0

    env_lower = env.lower()

    for keyword, (media, o2) in MEDIA_NORMALIZATION.items():
        if keyword in env_lower:
            return media, o2

    return env, 21.0


def normalize_location(location: str | None) -> Literal["habitable", "non_habitable"]:
    """Normalize location class."""
    if not location:
        return "non_habitable"

    loc_lower = location.lower().replace(" ", "").replace("-", "").replace("_", "")

    if "nonhab" in loc_lower:
        return "non_habitable"
    if "hab" in loc_lower:
        return "habitable"

    return "non_habitable"


def derive_min_temperature(
    max_temp_f: float | None,
    media: str | None,
) -> float:
    """
    Derive minimum temperature from context.

    Cryogenic media implies cryogenic min temp.
    """
    if media:
        media_upper = media.upper()
        if media_upper in ("LOX", "LN2"):
            return -320.0  # LOX/LN2 boiling points
        if media_upper == "LH2":
            return -423.0  # LH2 boiling point

    if max_temp_f is not None and max_temp_f < 0:
        return max_temp_f - 50.0  # Assume some range below max

    return 70.0  # Default room temperature


# =============================================================================
# Issue Classification
# =============================================================================

ISSUE_CLASSIFICATION_PROMPT = """Classify this MUA issue into deviation categories.

Categories:
- flammability: fire, ignition, burn, flame rating
- offgassing: TML, CVCM, outgassing, volatile
- toxicity: toxic, poisonous, harmful fumes
- corrosion: rust, galvanic, oxidation
- stress_corrosion_cracking: SCC, stress corrosion
- compatibility: oxygen compatible, LOX/GOX, hydrogen compatible
- thermal_vacuum_stability: TVS, thermal vacuum, bakeout
- other: none of the above

Issue text: "{issue_text}"

Return ONLY a JSON array of matching category names. Example: ["flammability", "offgassing"]
If unclear, return ["other"]."""


async def classify_issue(
    issue_text: str,
    llm_call: Callable[[str], Awaitable[str]],
) -> list[DeviationType]:
    """
    Classify issue text into DeviationType enums.
    """
    if not issue_text or len(issue_text.strip()) < 3:
        return []

    # Quick pattern matching for common cases
    issue_lower = issue_text.lower()
    quick_matches = []

    if any(kw in issue_lower for kw in ["scc", "stress corrosion"]):
        quick_matches.append(DeviationType.SCC)
    if any(kw in issue_lower for kw in ["flam", "ignit", "burn"]):
        quick_matches.append(DeviationType.FLAMMABILITY)
    if any(kw in issue_lower for kw in ["tml", "cvcm", "outgas", "tvs"]):
        quick_matches.append(DeviationType.OFFGASSING)
    if any(kw in issue_lower for kw in ["toxic"]):
        quick_matches.append(DeviationType.TOXICITY)
    if any(kw in issue_lower for kw in ["corros", "galvanic"]):
        quick_matches.append(DeviationType.CORROSION)

    if quick_matches:
        return quick_matches

    # Use LLM for ambiguous cases
    prompt = ISSUE_CLASSIFICATION_PROMPT.format(issue_text=issue_text[:500])

    try:
        response = await llm_call(prompt)
        categories = json.loads(response)
        return [
            DeviationType(c)
            for c in categories
            if c in [e.value for e in DeviationType]
        ]
    except (json.JSONDecodeError, ValueError):
        return [DeviationType.OTHER]


# =============================================================================
# Material Key Resolution
# =============================================================================


def generate_material_hash_key(
    designation: str,
    specification: str | None = None,
) -> str:
    """
    Generate deterministic material key from available fields.

    Used when MAPTIS lookup fails or returns low confidence.
    """
    norm_designation = designation.strip().upper().replace(" ", "")
    norm_spec = (specification or "").strip().upper().replace(" ", "")

    canonical = f"{norm_designation}|{norm_spec}"
    hash_bytes = hashlib.sha256(canonical.encode()).hexdigest()[:12]

    return f"MAT-{hash_bytes}"


async def resolve_material_key(
    material_name: str,
    specification: str | None,
    maptis_lookup: Callable[[str, str | None], Awaitable[tuple[str | None, float]]]
    | None,
) -> str:
    """
    Resolve material to canonical key via MAPTIS or hash fallback.

    Args:
        material_name: Material designation
        specification: Material spec (AMS, ASTM, etc.)
        maptis_lookup: Optional async function to query MAPTIS

    Returns:
        Canonical material key
    """
    if maptis_lookup:
        try:
            maptis_code, confidence = await maptis_lookup(material_name, specification)
            if maptis_code and confidence >= 0.8:
                return maptis_code
        except Exception:
            pass

    return generate_material_hash_key(material_name, specification)


# =============================================================================
# Program Family Derivation
# =============================================================================

PROJECT_TO_FAMILY: dict[str, ProgramFamily] = {
    "orion": ProgramFamily.ORION_ARTEMIS,
    "sls": ProgramFamily.ORION_ARTEMIS,
    "artemis": ProgramFamily.ORION_ARTEMIS,
    "gateway": ProgramFamily.ORION_ARTEMIS,
    "iss": ProgramFamily.ISS,
    "station": ProgramFamily.ISS,
    "commercial crew": ProgramFamily.COMMERCIAL_CREW,
    "crew dragon": ProgramFamily.COMMERCIAL_CREW,
    "starliner": ProgramFamily.COMMERCIAL_CREW,
    "shuttle": ProgramFamily.SHUTTLE,
    "sts": ProgramFamily.SHUTTLE,
    "apollo": ProgramFamily.APOLLO,
}


def derive_program_family(project: str | None) -> ProgramFamily:
    """Derive program family from project name."""
    if not project:
        return ProgramFamily.OTHER

    project_lower = project.lower()

    for keyword, family in PROJECT_TO_FAMILY.items():
        if keyword in project_lower:
            return family

    return ProgramFamily.OTHER


# =============================================================================
# Material Validation
# =============================================================================

INVALID_MATERIAL_PATTERNS = [
    r"^n/?a$",
    r"^see\s",
    r"^various$",
    r"^next\s+page",
    r"^per\s+drawing",
    r"^\d+$",
]


def is_valid_material(designation: str | None) -> bool:
    """Check if material designation is valid."""
    if not designation:
        return False

    d_lower = designation.lower().strip()

    if len(d_lower) < 2:
        return False

    for pattern in INVALID_MATERIAL_PATTERNS:
        if re.match(pattern, d_lower):
            return False

    return True


# =============================================================================
# Supersession Detection
# =============================================================================

# Patterns to extract revision number from MUA contract IDs
# Examples: "MUA-12345-R1" -> 1, "MUA-12345 Rev 2" -> 2, "MUA-12345A" -> 1
REVISION_PATTERNS = [
    r"[-_\s]R(\d+)$",  # -R1, _R2, etc.
    r"[-_\s]Rev\s*(\d+)$",  # Rev 1, Rev2
    r"[-_\s]Revision\s*(\d+)$",  # Revision 1
    r"([A-D])$",  # Single letter suffix (A=1, B=2, etc.)
]


def extract_revision_number(contract_id: str) -> int | None:
    """Extract revision number from contract ID if present.

    Examples:
        "MUA-12345-R1" -> 1
        "MUA-12345 Rev 2" -> 2
        "MUA-12345A" -> 1  (A=1, B=2, C=3, D=4)
        "MUA-12345" -> None

    Returns:
        Revision number (0-indexed internally), or None if not found
    """
    if not contract_id:
        return None

    for pattern in REVISION_PATTERNS:
        match = re.search(pattern, contract_id.upper().strip(), re.IGNORECASE)
        if match:
            captured = match.group(1)
            # Handle letter suffix (A=1, B=2, etc.)
            if captured.isalpha() and len(captured) == 1:
                return ord(captured.upper()) - ord('A') + 1
            return int(captured)

    return None


def extract_base_contract_id(contract_id: str) -> str:
    """Extract base contract ID without revision suffix.

    Examples:
        "MUA-12345-R1" -> "MUA-12345"
        "MUA-12345 Rev 2" -> "MUA-12345"
        "MUA-12345A" -> "MUA-12345"
        "MUA-12345" -> "MUA-12345"
    """
    if not contract_id:
        return ""

    normalized = contract_id.upper().strip()

    for pattern in REVISION_PATTERNS:
        normalized = re.sub(pattern, "", normalized, flags=re.IGNORECASE)

    return normalized.strip()


def detect_supersession_relationships(
    muas: list[EnrichedMUA],
) -> list[EnrichedMUA]:
    """Detect supersession relationships among MUAs.

    Two types of supersession are detected:

    1. Revision-based: MUA-12345-R2 supersedes MUA-12345-R1
       (same base contract ID, higher revision)

    2. Material-based: Newer MUA for same material/environment
       (same material_key, same media/location, newer approval_date)

    Args:
        muas: List of enriched MUAs (will be modified in place)

    Returns:
        The same list with supersession fields populated
    """
    from collections import defaultdict

    # Group by base contract ID for revision-based supersession
    by_base_contract: dict[str, list[EnrichedMUA]] = defaultdict(list)
    for mua in muas:
        base_id = extract_base_contract_id(mua.contract_id)
        if base_id:
            by_base_contract[base_id].append(mua)
            # Also set revision number
            if mua.revision_number is None:
                rev = extract_revision_number(mua.contract_id)
                # Create a new instance with revision_number set
                # (EnrichedMUA is not frozen, so we can modify it)
                mua.revision_number = rev

    # Process revision-based supersession
    for base_id, group in by_base_contract.items():
        if len(group) <= 1:
            continue

        # Sort by revision (None = 0), then by contract_id for stability
        group.sort(key=lambda m: (m.revision_number or 0, m.contract_id))

        # Each earlier revision is superseded by the next
        for i in range(len(group) - 1):
            older = group[i]
            newer = group[i + 1]
            older.is_superseded = True
            older.superseded_by = newer.contract_id
            if older.contract_id not in newer.supersedes:
                newer.supersedes = newer.supersedes + [older.contract_id]

    return muas


# =============================================================================
# Full Enrichment Function
# =============================================================================


async def enrich_mua_record(
    raw: RawMUARecord,
    llm_call: Callable[[str], Awaitable[str]],
    maptis_lookup: Callable[[str, str | None], Awaitable[tuple[str | None, float]]]
    | None = None,
) -> list[EnrichedMUA]:
    """
    Transform raw parsed MUA into enriched records.

    May return multiple records if source has multiple materials.
    Returns empty list if material is invalid.

    IMPORTANT: If a value is missing, propagate it as missing.
    Do NOT infer missing values unless explicitly specified.
    """
    if not is_valid_material(raw.material_designation):
        return []

    # Split multi-material
    materials = await split_materials(raw.material_designation, llm_call)
    if not materials:
        materials = [raw.material_designation]

    # Normalize environment once (shared by all materials)
    media, o2_pct = normalize_environment(raw.environment)
    location = normalize_location(raw.location)
    min_temp = derive_min_temperature(raw.max_temperature_f, media)
    program_family = derive_program_family(raw.application)

    # Classify issue once
    deviation_types = await classify_issue(raw.issue, llm_call) if raw.issue else []

    # Derive rejection status
    determination_upper = (raw.determination or "").upper()
    is_rejected = determination_upper == "REJECTED"
    is_usable = determination_upper in ("APPROVED", "APPROVED_WITH_LIMITS", "")

    results = []

    for i, mat_name in enumerate(materials):
        # Resolve material key
        material_key = await resolve_material_key(mat_name, raw.specification, maptis_lookup)

        enriched = EnrichedMUA(
            contract_id=raw.mua_number,
            source_file=raw.file,
            material_name=mat_name,
            material_key=material_key,
            specification=raw.specification,
            manufacturer=raw.manufacturer,
            trade_name=raw.trade_name,
            media=media,
            o2_pct=o2_pct,
            location_class=location,
            temp_max_f=raw.max_temperature_f,
            temp_min_f=min_temp,
            pressure_max_psia=raw.max_pressure,
            pressure_min_psia=0.0,
            category=raw.category,
            determination=raw.determination,
            is_rejected=is_rejected,
            is_usable_precedent=is_usable,
            deviation_types=deviation_types,
            issue_text=raw.issue,
            rationale_text=raw.rationale,
            application_text=raw.application,
            program=raw.application,  # Best available
            program_family=program_family,
            test_reports=raw.test_reports or [],
            parse_confidence=raw.confidence,
            extraction_mode=raw.extraction_mode,
            is_multi_material_source=len(materials) > 1,
            source_material_index=i,
        )
        results.append(enriched)

    return results
