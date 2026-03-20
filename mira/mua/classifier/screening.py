"""Material-Class Pre-Filter Gate — BS-SPEC-MUA-003 Step 3.

CRITICAL gate: "Should this flag even exist on this material class?"
If screening doesn't apply to the material class, no deficiency exists
and no MUA is generated — regardless of what MAPTIS says.

Also provides material_class_from_miul() for inferring material class
from MIUL designation strings.

BoundState AI 2026
Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: NASA-STD-6016C w/Change 2, JSC-27301 Rev J
Safety Critical: True
"""

from __future__ import annotations

from typing import Optional

from .models import MaterialClassEnum, ScreeningResult


# ---------------------------------------------------------------------------
# Screening applicability tables (spec Section 5)
# ---------------------------------------------------------------------------

SCREENING_APPLICABILITY: dict[str, list[str]] = {
    # Screening key: [applicable material classes]
    "FLAM": ["all"],          # Promoted ignition — all materials
    "TOX": ["nonmetallic"],   # MPR 45: nonmetallic materials in habitable compartments
    "TVS": ["nonmetallic"],   # section 4.2.3.6: ASTM E595 outgassing — nonmetallics only
    "FS": ["all"],            # MPR 47: all materials exposed to hazardous fluids
    "FLUID": ["all"],         # Same as FS
    "SCC": ["metal"],         # Stress corrosion cracking — metals only
    "CORR": ["metal"],        # Corrosion — metals only
    "H2COMPAT": ["metal"],    # MPR 192/193: metallic materials in H2 systems
    "LEGACY_OC": ["all"],     # Legacy oxygen compatibility — all materials
    "LEGACY_COMPAT": ["all"], # Legacy compatibility — all materials
}

ENVIRONMENT_APPLICABILITY: dict[str, dict[str, bool]] = {
    "TOX": {"habitable": True, "non-habitable": False},
    # TOX only applies in habitable compartments
    # All other screenings apply regardless of habitability
}


def is_screening_applicable(
    issue_key: str,
    material_class: MaterialClassEnum | str,
    environment: str = "non-habitable",
) -> ScreeningResult:
    """Check if a screening category applies to a material class + environment.

    This is the material-class gate from spec Section 5. It MUST execute
    before the classifier. If this returns applicable=False, no MUA should
    be generated for this issue_key + material combination.

    Parameters
    ----------
    issue_key
        Screening category: FLAM, TOX, TVS, FS, FLUID, SCC, CORR, H2COMPAT.
    material_class
        Material class: "metal" or "nonmetallic".
    environment
        Environment type: "habitable" or "non-habitable".

    Returns
    -------
    ScreeningResult
        Contains applicable flag and reason for the decision.
    """
    # Normalize inputs
    issue_upper = issue_key.upper().strip()
    if isinstance(material_class, str):
        material_class = MaterialClassEnum(material_class.lower().strip())
    env_lower = environment.lower().strip().replace(" ", "-")
    # Normalize common variants
    if env_lower in ("non_habitable", "nonhabitable", "external"):
        env_lower = "non-habitable"

    # Check material class applicability
    applicable_classes = SCREENING_APPLICABILITY.get(issue_upper, ["all"])
    if "all" not in applicable_classes and material_class.value not in applicable_classes:
        return ScreeningResult(
            issue_key=issue_upper,
            material_class=material_class,
            environment=env_lower,
            applicable=False,
            reason=(
                f"Screening '{issue_upper}' does not apply to "
                f"{material_class.value} materials. "
                f"Applicable to: {applicable_classes}."
            ),
        )

    # Check environment applicability
    env_rules = ENVIRONMENT_APPLICABILITY.get(issue_upper)
    if env_rules is not None:
        is_applicable = env_rules.get(env_lower, True)
        if not is_applicable:
            return ScreeningResult(
                issue_key=issue_upper,
                material_class=material_class,
                environment=env_lower,
                applicable=False,
                reason=(
                    f"Screening '{issue_upper}' does not apply in "
                    f"{env_lower} environment. "
                    f"Only applicable in: "
                    f"{[k for k, v in env_rules.items() if v]}."
                ),
            )

    return ScreeningResult(
        issue_key=issue_upper,
        material_class=material_class,
        environment=env_lower,
        applicable=True,
        reason=f"Screening '{issue_upper}' applies to {material_class.value} in {env_lower}.",
    )


# ---------------------------------------------------------------------------
# Material class inference from MIUL designation (BS-SPEC-MUA-003 Step 3)
# ---------------------------------------------------------------------------

_METAL_KEYWORDS: list[str] = [
    "steel", "sst", "cres", "inconel", "aluminum", "al ", "titanium",
    "bronze", "copper", "nickel", "a286", "waspaloy", "monel",
    "hastelloy", "cobalt", "tungsten", "beryllium", "magnesium",
    "invar", "kovar", "rene", "mp35n", "stellite", "zirconium",
    "7075", "6061", "2024", "4130", "4340", "316", "304", "302",
    "321", "347", "17-4", "15-5", "718", "625", "x-750",
]

_NONMETALLIC_KEYWORDS: list[str] = [
    "vespel", "teflon", "ptfe", "kapton", "nylon", "rubber",
    "silicone", "epoxy", "polyimide", "adhesive", "sealant",
    "elastomer", "composite", "foam", "film", "plastic",
    "viton", "fluorocarbon", "peek", "delrin", "acetal",
    "fiberglass", "kevlar", "nomex", "mylar",
]


def material_class_from_miul(
    designation: str,
) -> Optional[MaterialClassEnum]:
    """Determine material class from MIUL designation string.

    Per BS-SPEC-MUA-003 Section 3, Step 3: infer whether a material
    is metal or nonmetallic from its designation text. Returns None
    if the class cannot be determined (route to human).

    Parameters
    ----------
    designation
        The material designation string from the MIUL (e.g.,
        "A286 CRES", "Vespel SP-3", "7075-T651 AL").

    Returns
    -------
    MaterialClassEnum or None
        METAL, NONMETALLIC, or None if unknown.
    """
    if not designation:
        return None

    d = designation.lower()

    for keyword in _METAL_KEYWORDS:
        if keyword in d:
            return MaterialClassEnum.METAL

    for keyword in _NONMETALLIC_KEYWORDS:
        if keyword in d:
            return MaterialClassEnum.NONMETALLIC

    return None


# ---------------------------------------------------------------------------
# Rating coverage sanity check — catches material class mismatches
# ---------------------------------------------------------------------------

# Columns that should NOT have ratings for each material class
_UNEXPECTED_RATINGS: dict[str, list[str]] = {
    "metal": ["TOX", "TVS"],        # TOX/TVS are nonmetallic-only screenings
    "nonmetallic": ["SCC", "CORR"],  # SCC/CORR are metal-only screenings
}


def validate_rating_coverage(
    ratings: dict[str, str | None],
    material_class: MaterialClassEnum | str,
) -> list[str]:
    """Flag anomalous rating combinations that suggest wrong material class.

    A metal with TOX=A is suspicious (TOX shouldn't apply to metals).
    A nonmetallic with SCC=A suggests wrong material class inference.

    Returns list of warning strings (empty = no anomalies).
    """
    if isinstance(material_class, str):
        mc = material_class.lower().strip()
    else:
        mc = material_class.value

    unexpected = _UNEXPECTED_RATINGS.get(mc, [])
    warnings: list[str] = []

    for col in unexpected:
        rating = ratings.get(col)
        if rating is not None and str(rating).strip():
            warnings.append(
                f"Anomaly: {col} rating '{rating}' present for {mc} material. "
                f"{col} screening applies to {'nonmetallic' if mc == 'metal' else 'metal'} "
                f"materials only. Verify material class."
            )

    return warnings
