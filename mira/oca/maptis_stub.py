"""
Stub for mira.maptis.repository functions used by the OCA engine.

In the full MIRA platform, these functions query the MAPTIS PostgreSQL
silver layer. For standalone OCA, we provide a minimal implementation
using the local material_reference.json data pack.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Optional

_DATA_DIR = Path(__file__).parent / "data"


class MaterialFamily(str, Enum):
    TITANIUM = "titanium"
    MAGNESIUM = "magnesium"
    ALUMINUM = "aluminum"
    NICKEL_ALLOY = "nickel_alloy"
    AUSTENITIC_STEEL = "austenitic_steel"
    COPPER = "copper"
    POLYMER_FLUORINATED = "polymer_fluorinated"
    POLYMER_ORGANIC = "polymer_organic"
    COMPOSITE = "composite"
    CARBON_STEEL = "carbon_steel"
    UNKNOWN = "unknown"


# Map JSON family strings to enum values
_FAMILY_MAP: dict[str, MaterialFamily] = {
    "nickel_alloy": MaterialFamily.NICKEL_ALLOY,
    "copper": MaterialFamily.COPPER,
    "austenitic_steel": MaterialFamily.AUSTENITIC_STEEL,
    "aluminum": MaterialFamily.ALUMINUM,
    "titanium": MaterialFamily.TITANIUM,
    "magnesium": MaterialFamily.MAGNESIUM,
    "fluoropolymer": MaterialFamily.POLYMER_FLUORINATED,
    "perfluoroelastomer": MaterialFamily.POLYMER_FLUORINATED,
    "polyimide": MaterialFamily.POLYMER_ORGANIC,
    "polymer_organic": MaterialFamily.POLYMER_ORGANIC,
    "elastomer": MaterialFamily.POLYMER_ORGANIC,
    "carbon_steel": MaterialFamily.CARBON_STEEL,
    "unknown": MaterialFamily.UNKNOWN,
}


@dataclass
class MaterialRecord:
    """Structured material data for safety engines."""
    material_key: str
    designation: str
    material_code: Optional[int] = None
    material_type: Optional[str] = None
    family: MaterialFamily = MaterialFamily.UNKNOWN

    rating_flam: Optional[str] = None
    auto_ignition_temp_c: Optional[float] = None
    o2_test_count: int = 0
    max_tested_pressure_psi: Optional[float] = None

    contains_pfas: bool = False
    is_restricted: bool = False

    data_source: str = "unknown"
    confidence: float = 0.0
    source: str = ""
    # Provenance tier: "governing_standard" > "published_literature" > "estimated" > "not_available"
    provenance_tier: str = "not_available"


_material_ref: Optional[dict[str, Any]] = None


def _load_material_ref() -> dict[str, Any]:
    global _material_ref
    if _material_ref is None:
        ref_path = _DATA_DIR / "material_reference.json"
        if ref_path.exists():
            with open(ref_path, encoding="utf-8") as f:
                data = json.load(f)
            # Handle both list (legacy) and dict format
            if isinstance(data, list):
                _material_ref = {"materials": [], "families": data}
            else:
                _material_ref = data
        else:
            _material_ref = {"materials": [], "families": []}
    return _material_ref


# Heuristic family inference patterns (fallback)
_FAMILY_PATTERNS: list[tuple[str, MaterialFamily]] = [
    (r"monel|inconel|hastelloy|waspaloy|nimonic|ni[-\s]?alloy", MaterialFamily.NICKEL_ALLOY),
    (r"copper|brass|bronze|cu[-\s]", MaterialFamily.COPPER),
    (r"316|304|321|347|austenitic|stainless", MaterialFamily.AUSTENITIC_STEEL),
    (r"titanium|ti[-\s]?\d|ti-6al", MaterialFamily.TITANIUM),
    (r"aluminum|aluminium|al[-\s]?\d|6061|7075|2024|2219|5052", MaterialFamily.ALUMINUM),
    (r"magnesium|mg[-\s]?\d|az\d", MaterialFamily.MAGNESIUM),
    (r"ptfe|teflon|fep|pfa|etfe|pvdf|fluoropolymer|kalrez|ffkm|perfluoro", MaterialFamily.POLYMER_FLUORINATED),
    (r"vespel|polyimide|nylon|delrin|peek|ultem|pei|kapton|buna|nitrile|viton|silicone|epdm|elastomer", MaterialFamily.POLYMER_ORGANIC),
    (r"carbon steel|1018|1020|a36|a105|a106", MaterialFamily.CARBON_STEEL),
    (r"carbon fiber|fiberglass|composite|cfrp|gfrp", MaterialFamily.COMPOSITE),
]


def _infer_family(name: str) -> MaterialFamily:
    lower = name.lower()
    for pattern, family in _FAMILY_PATTERNS:
        if re.search(pattern, lower):
            return family
    return MaterialFamily.UNKNOWN


def get_material_for_o2(material_name: str) -> MaterialRecord:
    """Look up material O2 compatibility data from the reference pack.

    Returns a MaterialRecord. Never returns None — unknown materials get
    a low-confidence record with family=UNKNOWN.
    """
    ref = _load_material_ref()
    materials = ref.get("materials", [])
    name_lower = material_name.lower().strip()

    # Exact match
    for mat in materials:
        if mat.get("material_name", "").lower().strip() == name_lower:
            return _dict_to_record(mat, material_name, confidence=0.95)

    # Partial match
    for mat in materials:
        if name_lower in mat.get("material_name", "").lower():
            return _dict_to_record(mat, material_name, confidence=0.85)

    # Reverse partial match
    for mat in materials:
        if mat.get("material_name", "").lower() in name_lower:
            return _dict_to_record(mat, material_name, confidence=0.80)

    # Heuristic fallback
    family = _infer_family(material_name)
    return MaterialRecord(
        material_key=name_lower,
        designation=material_name,
        family=family,
        rating_flam="U" if family == MaterialFamily.UNKNOWN else None,
        data_source="heuristic_fallback",
        confidence=0.5 if family != MaterialFamily.UNKNOWN else 0.2,
        source="oca_standalone_heuristic",
    )


def _worst_provenance(mat: dict[str, Any]) -> str:
    """Determine the worst provenance tier used across all non-null data fields."""
    # Priority: governing_standard (best) > published_literature > estimated > not_available (worst)
    tier_rank = {"governing_standard": 0, "published_literature": 1, "estimated": 2, "not_available": 3}
    worst = "governing_standard"
    for key in ("flammability_provenance", "auto_ignition_provenance",
                "heat_of_combustion_provenance", "o2_index_provenance",
                "o2_test_count_provenance", "max_tested_pressure_provenance",
                "promoted_ignition_provenance"):
        prov = mat.get(key, "not_available")
        # Only count provenance for fields that actually have data
        data_key = key.replace("_provenance", "")
        if data_key == "flammability":
            data_key = "flammability_rating"
        if data_key == "max_tested_pressure":
            data_key = "max_tested_pressure_psia"
        data_val = mat.get(data_key)
        if data_val is not None:
            if tier_rank.get(prov, 3) > tier_rank.get(worst, 0):
                worst = prov
    return worst


def _dict_to_record(mat: dict[str, Any], original_name: str, confidence: float) -> MaterialRecord:
    family_str = mat.get("family", "unknown")
    family = _FAMILY_MAP.get(family_str, MaterialFamily.UNKNOWN)

    restricted = mat.get("flammability_rating", "U") in ("C", "D", "X")

    return MaterialRecord(
        material_key=original_name.lower().strip(),
        designation=mat.get("material_name", original_name),
        family=family,
        rating_flam=mat.get("flammability_rating"),
        auto_ignition_temp_c=mat.get("auto_ignition_temp_c"),
        o2_test_count=mat.get("o2_test_count") or 0,
        max_tested_pressure_psi=mat.get("max_tested_pressure_psia"),
        is_restricted=restricted,
        data_source="material_reference_json",
        confidence=confidence,
        source="oca_standalone/material_reference.json",
        provenance_tier=_worst_provenance(mat),
    )


def get_o2_family_rule(family: str) -> Optional[dict[str, Any]]:
    """Look up O2 family-level rule from reference pack.

    Returns dict with keys: classification, reason, bok_ref — matching
    the contract expected by the OCA engine.
    """
    ref = _load_material_ref()
    families = ref.get("families", [])
    family_lower = str(family).lower().strip()

    for fam in families:
        if fam.get("family", "").lower().strip() == family_lower:
            # Translate reference_pack format to engine-expected format
            compat = fam.get("compatibility_class", "U")
            classification_map = {
                "A": "approved",
                "B": "acceptable_with_review",
                "C": "restricted",
                "D": "not_recommended",
                "X": "prohibited",
                "U": "unresolved",
            }
            return {
                "family": fam["family"],
                "compatibility_class": compat,
                "classification": classification_map.get(compat, "unresolved"),
                "reason": fam.get("general_recommendation", f"Family {family} — compatibility class {compat}"),
                "bok_ref": "NASA-STD-6016 Table 4-1, NASA/TM-2007-213740",
                "notes": fam.get("notes", ""),
            }

    # Unknown family fallback
    return {
        "family": family_lower,
        "compatibility_class": "U",
        "classification": "unresolved",
        "reason": f"Family '{family}' not found in reference data. Material identity must be resolved.",
        "bok_ref": "NASA-STD-6016",
        "notes": "",
    }
