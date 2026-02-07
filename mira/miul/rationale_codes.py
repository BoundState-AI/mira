#!/usr/bin/env python3
"""
Module: Rationale Codes
Purpose: NASA-STD-6016A Rationale Codes for MIUL.

BoundState AI 2025
Version: 1.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Fran OpenAI 5 <noreply@openai.com>
Co-Authored-By: Grok 4.0 <noreply@x.ai>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: SWE-013 (Data requirements), SWE-033 (Requirements Traceability)
Safety Critical: True
"""

from __future__ import annotations

from enum import Enum
from typing import Dict, Literal, Optional

from pydantic import BaseModel, Field
import uuid

__all__ = [
    "RationaleCategory",
    "RationaleCode",
    "get_rationales_for_rating",
    "get_mua_reference_code",
    "get_rationale",
    "FLAMMABILITY_RATIONALES",
    "TOXICITY_RATIONALES",
    "FLUID_SYSTEM_RATIONALES",
    "THERMAL_VACUUM_RATIONALES",
    "STRESS_CORROSION_RATIONALES",
    "CORROSION_RATIONALES",
]

__safety_critical__ = True


class RationaleCategory(str, Enum):
    """NASA-STD-6016A rationale code categories."""

    FLAMMABILITY = "FLAM"      # 100 series
    TOXICITY = "TOX"          # 200 series
    FLUID_SYSTEM = "FS"       # 300 series
    THERMAL_VACUUM = "TVS"    # 400 series
    STRESS_CORROSION = "SCC"  # 500 series
    CORROSION = "CORR"        # 600 series


class RationaleCode(BaseModel):
    """Single rationale code definition."""

    model_config = {"extra": "forbid"}

    code: str = Field(..., description="Rationale code (e.g., '403')")
    category: RationaleCategory = Field(..., description="Category this code belongs to")
    rationale: str = Field(..., description="Full rationale text")
    mua_category: Optional[Literal["I", "II"]] = Field(
        None, description="MUA category if this is an MUA reference code"
    )
    is_mua_reference: bool = Field(
        False, description="True if this code references an MUA approval"
    )
    requires_mua: bool = Field(
        False, description="True if selecting this code triggers MUA generation"
    )


# === 100 Series: Flammability Rationales ===
FLAMMABILITY_RATIONALES: Dict[str, RationaleCode] = {
    "101": RationaleCode(
        code="101",
        category=RationaleCategory.FLAMMABILITY,
        rationale="Approved Material Usage Agreement (MUA) Category I.",
        mua_category="I",
        is_mua_reference=True,
    ),
    "102": RationaleCode(
        code="102",
        category=RationaleCategory.FLAMMABILITY,
        rationale="Approved Material Usage Agreement (MUA) Category II.",
        mua_category="II",
        is_mua_reference=True,
    ),
    "103": RationaleCode(
        code="103",
        category=RationaleCategory.FLAMMABILITY,
        rationale="Material is totally sandwiched between or bonded to nonflammable materials.",
    ),
    "104": RationaleCode(
        code="104",
        category=RationaleCategory.FLAMMABILITY,
        rationale="Material is totally enclosed or encapsulated in a sealed, nonflammable container.",
    ),
    "105": RationaleCode(
        code="105",
        category=RationaleCategory.FLAMMABILITY,
        rationale="Material is in minor usage and is not located adjacent to an ignition source or flammable materials.",
    ),
    "106": RationaleCode(
        code="106",
        category=RationaleCategory.FLAMMABILITY,
        rationale="Material is inherently self-extinguishing in the applicable environment.",
    ),
    "107": RationaleCode(
        code="107",
        category=RationaleCategory.FLAMMABILITY,
        rationale="Material usage is limited to ground support equipment (GSE) only.",
    ),
    "108": RationaleCode(
        code="108",
        category=RationaleCategory.FLAMMABILITY,
        rationale="Material is used in electrical applications and meets requirements per NASA-STD-6001 Test 1.",
    ),
    "109": RationaleCode(
        code="109",
        category=RationaleCategory.FLAMMABILITY,
        rationale="Material is a lubricant that has been tested and approved for the specific application.",
    ),
    "110": RationaleCode(
        code="110",
        category=RationaleCategory.FLAMMABILITY,
        rationale="Material configuration meets flammability requirements as tested.",
    ),
    "111": RationaleCode(
        code="111",
        category=RationaleCategory.FLAMMABILITY,
        rationale="Material is used externally and will not be exposed to crew atmosphere.",
    ),
    "112": RationaleCode(
        code="112",
        category=RationaleCategory.FLAMMABILITY,
        rationale="Material is coated or treated with fire-retardant coating.",
    ),
    "113": RationaleCode(
        code="113",
        category=RationaleCategory.FLAMMABILITY,
        rationale="Material is tested and passes at the use thickness.",
    ),
    "114": RationaleCode(
        code="114",
        category=RationaleCategory.FLAMMABILITY,
        rationale="Material is a metal or ceramic and is inherently nonflammable.",
    ),
}

# === 200 Series: Toxicity Rationales ===
TOXICITY_RATIONALES: Dict[str, RationaleCode] = {
    "201": RationaleCode(
        code="201",
        category=RationaleCategory.TOXICITY,
        rationale="Approved Material Usage Agreement (MUA) Category I.",
        mua_category="I",
        is_mua_reference=True,
    ),
    "202": RationaleCode(
        code="202",
        category=RationaleCategory.TOXICITY,
        rationale="Approved Material Usage Agreement (MUA) Category II.",
        mua_category="II",
        is_mua_reference=True,
    ),
    "203": RationaleCode(
        code="203",
        category=RationaleCategory.TOXICITY,
        rationale="Material T-value is below the spacecraft maximum allowable concentration (SMAC).",
    ),
    "204": RationaleCode(
        code="204",
        category=RationaleCategory.TOXICITY,
        rationale="Material is totally enclosed in a sealed container and will not release offgassed products.",
    ),
    "205": RationaleCode(
        code="205",
        category=RationaleCategory.TOXICITY,
        rationale="Material is external to pressurized volume and will not contaminate crew atmosphere.",
    ),
    "206": RationaleCode(
        code="206",
        category=RationaleCategory.TOXICITY,
        rationale="Material offgassing products are removed by Environmental Control and Life Support System (ECLSS).",
    ),
    "207": RationaleCode(
        code="207",
        category=RationaleCategory.TOXICITY,
        rationale="Material is used in Ground Support Equipment (GSE) only.",
    ),
    "208": RationaleCode(
        code="208",
        category=RationaleCategory.TOXICITY,
        rationale="Material meets toxicity requirements per NASA-STD-6001 Test 7.",
    ),
}

# === 300 Series: Fluid Systems Rationales ===
FLUID_SYSTEM_RATIONALES: Dict[str, RationaleCode] = {
    "301": RationaleCode(
        code="301",
        category=RationaleCategory.FLUID_SYSTEM,
        rationale="Approved Material Usage Agreement (MUA) Category I.",
        mua_category="I",
        is_mua_reference=True,
    ),
    "302": RationaleCode(
        code="302",
        category=RationaleCategory.FLUID_SYSTEM,
        rationale="Approved Material Usage Agreement (MUA) Category II.",
        mua_category="II",
        is_mua_reference=True,
    ),
    "303": RationaleCode(
        code="303",
        category=RationaleCategory.FLUID_SYSTEM,
        rationale="Material is compatible with fluid as tested in the actual configuration.",
    ),
    "304": RationaleCode(
        code="304",
        category=RationaleCategory.FLUID_SYSTEM,
        rationale="Material is tested batch/lot specific and meets requirements.",
    ),
    "305": RationaleCode(
        code="305",
        category=RationaleCategory.FLUID_SYSTEM,
        rationale="Material is not in direct contact with the fluid.",
    ),
    "306": RationaleCode(
        code="306",
        category=RationaleCategory.FLUID_SYSTEM,
        rationale="Material is used in ground support equipment (GSE) only.",
    ),
    "307": RationaleCode(
        code="307",
        category=RationaleCategory.FLUID_SYSTEM,
        rationale="Material is rated A or B for the specific fluid per MAPTIS database.",
    ),
}

# === 400 Series: Thermal Vacuum Stability (TVS) Rationales ===
THERMAL_VACUUM_RATIONALES: Dict[str, RationaleCode] = {
    "401": RationaleCode(
        code="401",
        category=RationaleCategory.THERMAL_VACUUM,
        rationale="Approved Material Usage Agreement (MUA) Category I.",
        mua_category="I",
        is_mua_reference=True,
    ),
    "402": RationaleCode(
        code="402",
        category=RationaleCategory.THERMAL_VACUUM,
        rationale="Approved Material Usage Agreement (MUA) Category II.",
        mua_category="II",
        is_mua_reference=True,
    ),
    "403": RationaleCode(
        code="403",
        category=RationaleCategory.THERMAL_VACUUM,
        rationale="VCM between 0.1 and 1.0 percent; exposed area is less than 13 cm² (2 in²) and not near a critical surface.",
    ),
    "404": RationaleCode(
        code="404",
        category=RationaleCategory.THERMAL_VACUUM,
        rationale="VCM greater than 1.0 percent; exposed area is less than 1.6 cm² (0.25 in²).",
    ),
    "405": RationaleCode(
        code="405",
        category=RationaleCategory.THERMAL_VACUUM,
        rationale="Material is unexposed, overcoated, or encapsulated.",
    ),
    "406": RationaleCode(
        code="406",
        category=RationaleCategory.THERMAL_VACUUM,
        rationale="Material is used in pressurized volume only; no vacuum exposure.",
    ),
    "407": RationaleCode(
        code="407",
        category=RationaleCategory.THERMAL_VACUUM,
        rationale="Material meets TVS requirements in the actual configuration as tested.",
    ),
    "408": RationaleCode(
        code="408",
        category=RationaleCategory.THERMAL_VACUUM,
        rationale="Material is hermetically sealed and will not outgas to the external environment.",
    ),
    "409": RationaleCode(
        code="409",
        category=RationaleCategory.THERMAL_VACUUM,
        rationale="Material is in a sealed container with negligible leak rate.",
    ),
}

# === 500 Series: Stress Corrosion Cracking (SCC) Rationales ===
STRESS_CORROSION_RATIONALES: Dict[str, RationaleCode] = {
    "501": RationaleCode(
        code="501",
        category=RationaleCategory.STRESS_CORROSION,
        rationale="Approved Material Usage Agreement (MUA) Category I.",
        mua_category="I",
        is_mua_reference=True,
    ),
    "502": RationaleCode(
        code="502",
        category=RationaleCategory.STRESS_CORROSION,
        rationale="Approved Material Usage Agreement (MUA) Category II.",
        mua_category="II",
        is_mua_reference=True,
    ),
    "503": RationaleCode(
        code="503",
        category=RationaleCategory.STRESS_CORROSION,
        rationale="Application is low stress (below 25% of yield strength).",
    ),
    "504": RationaleCode(
        code="504",
        category=RationaleCategory.STRESS_CORROSION,
        rationale="Material is in compressive loading only; no tensile stress.",
    ),
    "505": RationaleCode(
        code="505",
        category=RationaleCategory.STRESS_CORROSION,
        rationale="Material is protected by coating or finish from corrosive environment.",
    ),
    "506": RationaleCode(
        code="506",
        category=RationaleCategory.STRESS_CORROSION,
        rationale="Material has been stress-relieved per specification requirements.",
    ),
    "507": RationaleCode(
        code="507",
        category=RationaleCategory.STRESS_CORROSION,
        rationale="Material is not exposed to corrosive environment.",
    ),
    "508": RationaleCode(
        code="508",
        category=RationaleCategory.STRESS_CORROSION,
        rationale="Material meets SCC requirements per MSFC-SPEC-522.",
    ),
}

# === 600 Series: Corrosion Rationales ===
CORROSION_RATIONALES: Dict[str, RationaleCode] = {
    "601": RationaleCode(
        code="601",
        category=RationaleCategory.CORROSION,
        rationale="Approved Material Usage Agreement (MUA) Category I.",
        mua_category="I",
        is_mua_reference=True,
    ),
    "602": RationaleCode(
        code="602",
        category=RationaleCategory.CORROSION,
        rationale="Approved Material Usage Agreement (MUA) Category II.",
        mua_category="II",
        is_mua_reference=True,
    ),
    "603": RationaleCode(
        code="603",
        category=RationaleCategory.CORROSION,
        rationale="Material is protected by approved finish or coating system.",
    ),
    "604": RationaleCode(
        code="604",
        category=RationaleCategory.CORROSION,
        rationale="Material is galvanically compatible with adjacent materials.",
    ),
    "605": RationaleCode(
        code="605",
        category=RationaleCategory.CORROSION,
        rationale="Material is isolated from dissimilar metals by non-conductive barrier.",
    ),
    "606": RationaleCode(
        code="606",
        category=RationaleCategory.CORROSION,
        rationale="Material is used in controlled atmosphere or vacuum only.",
    ),
    "607": RationaleCode(
        code="607",
        category=RationaleCategory.CORROSION,
        rationale="Material has passed 336-hour salt spray testing per ASTM B117.",
    ),
    "608": RationaleCode(
        code="608",
        category=RationaleCategory.CORROSION,
        rationale="Material is inherently corrosion resistant (e.g., noble metal, ceramic).",
    ),
    "609": RationaleCode(
        code="609",
        category=RationaleCategory.CORROSION,
        rationale="Material is plated or anodized per approved specification.",
    ),
    "610": RationaleCode(
        code="610",
        category=RationaleCategory.CORROSION,
        rationale="Application is temporary/limited duration; corrosion is acceptable.",
    ),
    "611": RationaleCode(
        code="611",
        category=RationaleCategory.CORROSION,
        rationale="Material is painted or sealed with corrosion inhibitor.",
    ),
    "612": RationaleCode(
        code="612",
        category=RationaleCategory.CORROSION,
        rationale="Dissimilar metal junction uses approved sealant or compound.",
    ),
}


# Combined lookup of all rationales
_ALL_RATIONALES: Dict[str, RationaleCode] = {
    **FLAMMABILITY_RATIONALES,
    **TOXICITY_RATIONALES,
    **FLUID_SYSTEM_RATIONALES,
    **THERMAL_VACUUM_RATIONALES,
    **STRESS_CORROSION_RATIONALES,
    **CORROSION_RATIONALES,
}


def get_rationales_for_rating(category: RationaleCategory) -> Dict[str, RationaleCode]:
    """Get all rationale codes for a specific rating category.

    Args:
        category: The rating category (FLAM, TOX, FS, TVS, SCC, CORR)

    Returns:
        Dictionary of code -> RationaleCode for that category
    """
    category_map = {
        RationaleCategory.FLAMMABILITY: FLAMMABILITY_RATIONALES,
        RationaleCategory.TOXICITY: TOXICITY_RATIONALES,
        RationaleCategory.FLUID_SYSTEM: FLUID_SYSTEM_RATIONALES,
        RationaleCategory.THERMAL_VACUUM: THERMAL_VACUUM_RATIONALES,
        RationaleCategory.STRESS_CORROSION: STRESS_CORROSION_RATIONALES,
        RationaleCategory.CORROSION: CORROSION_RATIONALES,
    }
    return category_map.get(category, {})


def get_mua_reference_code(
    rating_type: str,
    mua_category: Literal["I", "II"],
) -> str:
    """Get the MUA reference code (x01 or x02) for a rating type.

    Args:
        rating_type: Rating type (FLAM, TOX, FS, TVS, SCC, CORR)
        mua_category: MUA category (I or II)

    Returns:
        Code string (e.g., "401" for TVS Cat I)
    """
    prefix_map = {
        "FLAM": "1",
        "TOX": "2",
        "FS": "3",
        "TVS": "4",
        "SCC": "5",
        "CORR": "6",
    }
    prefix = prefix_map.get(rating_type.upper(), "7")
    suffix = "01" if mua_category == "I" else "02"
    return f"{prefix}{suffix}"


def get_rationale(code: str) -> Optional[RationaleCode]:
    """Look up a rationale code by its code string.

    Args:
        code: The rationale code (e.g., "403")

    Returns:
        RationaleCode if found, None otherwise
    """
    return _ALL_RATIONALES.get(code)
