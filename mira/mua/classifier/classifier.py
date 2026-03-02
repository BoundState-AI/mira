"""MUA Flag-First Classifier — BS-SPEC-MUA-003 Steps 1-6.

Each step asks one question, gets one answer, proceeds to the next.
Every step is a function. Every function is automatable.

Step 1: WHAT FLAG?        → Read the column and the letter
Step 2: WHAT DOES IT MEAN? → Decode the letter per that column's dictionary
Step 3: SHOULD THIS FLAG EXIST? → Material-class smell test
Step 4: DOES THE HAZARD APPLY?  → Environment check against service conditions
Step 5: WHAT TYPE OF MUA?       → Classify from flag_type + hazard_applies
Step 6: WHAT CATEGORY?          → Cat I or Cat II from type

Supersedes: BS-SPEC-MUA-002 monolithic decision tree

BoundState AI 2026
Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: NASA-STD-6016C w/Change 2, JSC-27301 Rev J
Safety Critical: True
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from .models import (
    COLUMN_FLAG_DICT,
    ClassifierResult,
    DecodedFlag,
    FlagType,
    MaterialClassEnum,
    MUACategorySpec,
    MUAType,
    RATING_SEMANTICS,
)
from .screening import is_screening_applicable

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Screening columns recognized by the pipeline
# ---------------------------------------------------------------------------

SCREENING_COLUMNS: list[str] = ["FLAM", "SCC", "CORR", "TVS", "TOX", "FS"]


# ---------------------------------------------------------------------------
# Environment media sets (domain facts encoded as sets)
# ---------------------------------------------------------------------------

# FS Test 15 covers these fluids only
_FS_RELEVANT_MEDIA: set[str] = {
    "N2H4", "HYDRAZINE",
    "MMH", "MONOMETHYLHYDRAZINE",
    "N2O4", "NTO", "NITROGEN_TETROXIDE",
    "UDMH",
}

# Hydrogen media identifiers
_H2_MEDIA: set[str] = {
    "H2", "GH2", "LH2", "HYDROGEN",
}

# O2-enriched media (FLAM failure mode is credible here)
_O2_ENRICHED_MEDIA: set[str] = {
    "GOX", "LOX", "O2", "OXYGEN",
    "ENRICHED_AIR", "ENRICHED_O2",
}

# SCC suppressors (cryogenic H2 suppresses aqueous SCC)
_SCC_SUPPRESSOR_MEDIA: set[str] = {
    "GH2", "LH2", "H2", "HYDROGEN",
}


# =========================================================================
# Step 1: WHAT FLAG?
# =========================================================================


def step1_identify_flags(
    ratings: dict[str, str | None],
) -> list[tuple[str, str]]:
    """Identify all non-passing flags from a row's rating columns.

    Only processes columns that are PRESENT in the ratings dict with
    non-None, non-empty values. Columns the caller didn't provide are
    silently skipped — "not provided" is NOT the same as "missing in
    MAPTIS."

    For batch MIUL processing where blanks mean "MAPTIS has no entry,"
    the caller should pass empty strings explicitly. For the interactive
    UI where blanks mean "user didn't enter anything," the caller should
    omit the key or pass None.

    Parameters
    ----------
    ratings
        Dict mapping column name -> rating letter.
        E.g. {"FLAM": "C", "FS": "U", "SCC": "A"}
        Columns not in the dict or with None values are skipped.

    Returns
    -------
    list of (column, rating) pairs that need MUAs.
    """
    flags: list[tuple[str, str]] = []
    for column in SCREENING_COLUMNS:
        rating = ratings.get(column)
        # Skip columns not provided or explicitly None
        if rating is None:
            continue
        rating_str = str(rating).strip()
        if not rating_str:
            continue  # Empty string = not provided, skip
        rating_upper = rating_str.upper()
        if rating_upper == "A":
            continue  # Pass, no MUA needed
        if rating_upper == "N":
            continue  # Not applicable, no MUA needed
        flags.append((column, rating_upper))
    return flags


# =========================================================================
# Step 2: WHAT DOES IT MEAN?
# =========================================================================


def step2_decode_flag(
    column: str,
    rating: str,
) -> DecodedFlag:
    """Decode a rating letter using the column-specific dictionary.

    CRITICAL: The same letter means different things in different columns.
    This function uses COLUMN_FLAG_DICT to get the correct FlagType.

    Parameters
    ----------
    column
        Screening column: FLAM, FS, TOX, TVS, SCC, CORR.
    rating
        The raw rating letter (or "" for blank).

    Returns
    -------
    DecodedFlag with flag_type and decoded meaning.
    """
    col_upper = column.upper().strip()
    rat_upper = (rating or "").upper().strip()

    # Handle blank/missing
    if not rat_upper:
        return DecodedFlag(
            column=col_upper,
            rating="",
            flag_type=FlagType.MISSING_DATA,
            decoded_meaning="No entry in MAPTIS. Unknown status.",
        )

    # Look up in column-specific dictionary
    col_dict = COLUMN_FLAG_DICT.get(col_upper, {})
    flag_type = col_dict.get(rat_upper)

    if flag_type is None:
        # Rating letter not in dictionary for this column
        return DecodedFlag(
            column=col_upper,
            rating=rat_upper,
            flag_type=FlagType.BAD_DATA,
            decoded_meaning=(
                f"Rating '{rat_upper}' is not defined in the {col_upper} "
                f"column dictionary. Possible MIUL builder artifact."
            ),
        )

    # Get human-readable meaning from RATING_SEMANTICS
    semantics = RATING_SEMANTICS.get((col_upper, rat_upper))
    meaning = semantics.meaning if semantics else f"{col_upper} rating {rat_upper}"

    return DecodedFlag(
        column=col_upper,
        rating=rat_upper,
        flag_type=flag_type,
        decoded_meaning=meaning,
        source=semantics.issue_key if semantics else col_upper,
    )


# =========================================================================
# Step 3: SHOULD THIS FLAG EXIST? (delegates to screening.py)
# =========================================================================


def step3_should_flag_exist(
    column: str,
    material_class: MaterialClassEnum | str,
    environment: str = "non-habitable",
) -> bool:
    """Check if this screening column applies to this material/environment.

    Delegates to is_screening_applicable() from screening.py.
    Returns True if the flag should exist, False if it's invalid.
    """
    result = is_screening_applicable(column, material_class, environment)
    return result.applicable


# =========================================================================
# Step 4: DOES THE HAZARD APPLY?
# =========================================================================


def step4_hazard_applies(
    column: str,
    media: str,
    environment: str = "non-habitable",
    o2_percent: float | None = None,
) -> bool:
    """Check if the hazard tested by this screening exists in the service environment.

    One domain fact + one string match per column. Not a database lookup.
    Not an LLM call.

    Parameters
    ----------
    column
        Screening column: FLAM, FS, TOX, TVS, SCC, CORR.
    media
        Service medium: GH2, LH2, GOX, LOX, Air, N2H4, etc.
    environment
        "habitable" or "non-habitable".
    o2_percent
        Oxygen percentage if known.

    Returns
    -------
    bool
        True if the hazard IS present (flag is relevant).
        False if the hazard is NOT present (flag is a paperwork artifact).
    """
    media_upper = media.upper().strip()
    col_upper = column.upper().strip()

    if col_upper == "FLAM":
        # Promoted ignition requires O2-enriched atmosphere
        if media_upper in _O2_ENRICHED_MEDIA:
            return True
        if o2_percent is not None and o2_percent >= 23.5:
            return True
        return False

    if col_upper == "FS":
        # Test 15 covers hydrazine/MMH/N2O4 only
        return media_upper in _FS_RELEVANT_MEDIA

    if col_upper == "TOX":
        # Already gated by Step 3 (nonmetallic + habitable)
        # If it got here, the hazard applies
        return True

    if col_upper == "TVS":
        # If it passed Step 3 (nonmetallic), the hazard applies
        return True

    if col_upper == "SCC":
        # SCC requires aqueous environment / corrodents
        # Cryogenic H2 suppresses aqueous SCC mechanisms
        if media_upper in _SCC_SUPPRESSOR_MEDIA:
            return False
        return True

    if col_upper == "CORR":
        # Similar to SCC but broader
        if media_upper in _SCC_SUPPRESSOR_MEDIA:
            return False
        return True

    # Unknown column — conservative: assume hazard applies
    return True


# =========================================================================
# Step 5: WHAT TYPE OF MUA?
# =========================================================================


def step5_classify_type(
    flag_type: FlagType,
    hazard_applies: bool,
) -> MUAType:
    """Classify MUA type from flag_type + hazard_applies.

    This is the 2x3 matrix from BS-SPEC-MUA-003 Section 3, Step 5:

    flag_type=REAL_FAIL  + hazard=False → ANTI_RULE      (automatable)
    flag_type=REAL_FAIL  + hazard=True  → REAL_PROBLEM    (needs engineer)
    flag_type=ADMIN_GAP  + hazard=False → INCOMPLETE_PASS (automatable)
    flag_type=ADMIN_GAP  + hazard=True  → INCOMPLETE_PASS (automatable, data favorable)
    flag_type=NO_DATA    + hazard=False → THIN_SCREENING  (automatable)
    flag_type=NO_DATA    + hazard=True  → REAL_GAP        (needs engineer)
    """
    if flag_type == FlagType.REAL_FAIL:
        return MUAType.ANTI_RULE if not hazard_applies else MUAType.REAL_PROBLEM

    if flag_type == FlagType.ADMIN_GAP:
        return MUAType.INCOMPLETE_PASS  # Always automatable — data is favorable

    if flag_type == FlagType.NO_DATA:
        return MUAType.THIN_SCREENING if not hazard_applies else MUAType.REAL_GAP

    # Should not reach here for pipeline flags — defensive
    return MUAType.FLAG_FOR_HUMAN


# =========================================================================
# Step 6: WHAT CATEGORY?
# =========================================================================


_CATEGORY_MAP: dict[MUAType, MUACategorySpec | None] = {
    MUAType.THIN_SCREENING: MUACategorySpec.II,
    MUAType.ANTI_RULE: MUACategorySpec.II,
    MUAType.INCOMPLETE_PASS: MUACategorySpec.II,
    MUAType.REAL_PROBLEM: MUACategorySpec.I,
    MUAType.REAL_GAP: MUACategorySpec.II,  # Default II, engineer may elevate to I
    MUAType.STANDARD: None,
    MUAType.FLAG_FOR_HUMAN: None,
}

_AUTOMATABLE: set[MUAType] = {
    MUAType.THIN_SCREENING,
    MUAType.ANTI_RULE,
    MUAType.INCOMPLETE_PASS,
}


def step6_assign_category(
    mua_type: MUAType,
) -> MUACategorySpec | None:
    """Assign MUA category from type.

    All automatable MUAs are Category II. This is inherent — if the
    tool can determine the hazard doesn't apply, it's by definition
    "not considered a hazard in its use application."

    Category I requires engineering judgment about accepted risk.
    """
    return _CATEGORY_MAP.get(mua_type)


# =========================================================================
# Confidence assignment per MUA type
# =========================================================================

_TYPE_CONFIDENCE: dict[MUAType, float] = {
    MUAType.THIN_SCREENING: 0.90,
    MUAType.ANTI_RULE: 0.70,
    MUAType.INCOMPLETE_PASS: 0.95,
    MUAType.REAL_PROBLEM: 0.00,
    MUAType.REAL_GAP: 0.40,
    MUAType.STANDARD: 1.00,
    MUAType.FLAG_FOR_HUMAN: 0.00,
}

_TYPE_PRECEDENTS_NEEDED: dict[MUAType, int] = {
    MUAType.THIN_SCREENING: 0,
    MUAType.ANTI_RULE: 5,
    MUAType.INCOMPLETE_PASS: 0,
    MUAType.REAL_PROBLEM: 0,
    MUAType.REAL_GAP: 3,
    MUAType.STANDARD: 0,
    MUAType.FLAG_FOR_HUMAN: 0,
}


# =========================================================================
# Integrated classify_mua — runs Steps 1-6 for a single flag
# =========================================================================


def _get_companion_ref(media_upper: str) -> str | None:
    """Return H2COMPAT companion MUA reference if in H2 service."""
    if media_upper in _H2_MEDIA:
        return (
            "H2COMPAT companion MUA per NASA-STD-6016C §4.2.6.4 "
            "[MPR 192/193] and §4.2.1.3 [MPR 47] (TBD)"
        )
    return None


def classify_mua(
    maptis_code: str,
    issue_key: str,
    rating: str,
    material_class: MaterialClassEnum | str,
    media: str,
    environment: str = "non-habitable",
    o2_percent: float | None = None,
    batch_verified: bool = False,
) -> ClassifierResult:
    """Classify a single MAPTIS flag through Steps 2-6 of the pipeline.

    This is the integrated classifier that runs all steps for a single
    (column, rating) pair. For the full pipeline starting from a MIUL
    row, use pipeline.process_miul_row().

    Parameters
    ----------
    maptis_code
        MAPTIS material code from the MIUL. Trust it — don't re-resolve.
    issue_key
        Screening column: FLAM, FS, TOX, SCC, CORR, TVS, H2COMPAT.
    rating
        MAPTIS rating letter: A, B, C, D, I, U, K, S, N, or blank.
    material_class
        "metal" or "nonmetallic".
    media
        Service medium: GH2, LH2, GOX, LOX, Air, N2H4, etc.
    environment
        "habitable" or "non-habitable".
    o2_percent
        Oxygen percentage if known.
    batch_verified
        Whether batch/lot verification exists for B-rated material.

    Returns
    -------
    ClassifierResult with full decision trace.
    """
    # Normalize inputs
    if isinstance(material_class, str):
        material_class = MaterialClassEnum(material_class.lower().strip())
    rating_upper = (rating or "").upper().strip()
    issue_upper = issue_key.upper().strip()
    media_upper = media.upper().strip()

    # Look up rating semantics
    semantics = RATING_SEMANTICS.get((issue_upper, rating_upper))

    # ── Step 3: Material-class gate ──
    screening = is_screening_applicable(issue_upper, material_class, environment)
    if not screening.applicable:
        return ClassifierResult(
            maptis_code=maptis_code,
            issue_key=issue_upper,
            rating=rating_upper,
            material_class=material_class,
            media=media_upper,
            environment=screening.environment,
            flag_type=None,
            hazard_applies=None,
            mua_type=MUAType.STANDARD,
            category=None,
            confidence=1.0,
            automatable=False,
            screening_applicable=False,
            screening_reason=screening.reason,
            classification_reason="No MUA needed — screening not applicable to this material/environment.",
        )

    # ── Step 2: Decode flag ──
    decoded = step2_decode_flag(issue_upper, rating_upper)
    flag_type = decoded.flag_type

    # Handle non-pipeline flag types (stop conditions per MUA-003 Section 3)
    if flag_type == FlagType.NO_FLAG:
        return ClassifierResult(
            maptis_code=maptis_code,
            issue_key=issue_upper,
            rating=rating_upper,
            material_class=material_class,
            media=media_upper,
            environment=screening.environment,
            flag_type=flag_type,
            hazard_applies=None,
            mua_type=MUAType.STANDARD,
            category=None,
            confidence=1.0,
            automatable=False,
            screening_applicable=True,
            screening_reason=screening.reason,
            classification_reason="Rating A — pass. No MUA needed.",
            rating_semantics=semantics,
        )

    if flag_type in (FlagType.BAD_DATA, FlagType.MISSING_DATA, FlagType.NEEDS_REVIEW):
        return ClassifierResult(
            maptis_code=maptis_code,
            issue_key=issue_upper,
            rating=rating_upper,
            material_class=material_class,
            media=media_upper,
            environment=screening.environment,
            flag_type=flag_type,
            hazard_applies=None,
            mua_type=MUAType.FLAG_FOR_HUMAN,
            category=None,
            confidence=0.0,
            automatable=False,
            screening_applicable=True,
            screening_reason=screening.reason,
            classification_reason=(
                f"Flag type {flag_type.value}: {decoded.decoded_meaning} "
                f"Tool cannot proceed. Route to human."
            ),
            rating_semantics=semantics,
        )

    if flag_type == FlagType.BATCH_REQUIRED:
        if batch_verified:
            return ClassifierResult(
                maptis_code=maptis_code,
                issue_key=issue_upper,
                rating=rating_upper,
                material_class=material_class,
                media=media_upper,
                environment=screening.environment,
                flag_type=flag_type,
                hazard_applies=None,
                mua_type=MUAType.STANDARD,
                category=None,
                confidence=0.95,
                automatable=False,
                screening_applicable=True,
                screening_reason=screening.reason,
                classification_reason=(
                    "Rating B with batch/lot verification — treated as pass. "
                    "Per retired codes 303/406."
                ),
                rating_semantics=semantics,
                requires_batch_verification=False,
            )
        else:
            return ClassifierResult(
                maptis_code=maptis_code,
                issue_key=issue_upper,
                rating=rating_upper,
                material_class=material_class,
                media=media_upper,
                environment=screening.environment,
                flag_type=flag_type,
                hazard_applies=None,
                mua_type=MUAType.FLAG_FOR_HUMAN,
                category=MUACategorySpec.II,
                confidence=0.0,
                automatable=False,
                screening_applicable=True,
                screening_reason=screening.reason,
                classification_reason=(
                    "Rating B without batch/lot verification. "
                    "B does NOT mean pass — it means CAN pass if "
                    "specific batch is verified. Route to human. "
                    "Per retired codes 303, 406 (Appendix C of 6016C)."
                ),
                rating_semantics=semantics,
                requires_batch_verification=True,
            )

    # ── Step 4: Hazard check ──
    hazard = step4_hazard_applies(issue_upper, media_upper, screening.environment, o2_percent)

    # ── Step 5: Classify type ──
    mua_type = step5_classify_type(flag_type, hazard)
    is_automatable = mua_type in _AUTOMATABLE

    # ── Step 6: Category ──
    category = step6_assign_category(mua_type)
    confidence = _TYPE_CONFIDENCE.get(mua_type, 0.0)

    # Companion reference for H2 service
    companion_ref = _get_companion_ref(media_upper) if is_automatable else None

    # Build classification reason
    reason_parts = [
        f"Flag: {issue_upper}={rating_upper} → flag_type={flag_type.value}.",
        f"Hazard applies in {media_upper}: {hazard}.",
        f"Classification: {mua_type.value}.",
    ]
    if is_automatable:
        reason_parts.append("Automatable — tool can generate Form 551.")
    else:
        reason_parts.append("Requires engineering judgment.")

    return ClassifierResult(
        maptis_code=maptis_code,
        issue_key=issue_upper,
        rating=rating_upper,
        material_class=material_class,
        media=media_upper,
        environment=screening.environment,
        flag_type=flag_type,
        hazard_applies=hazard,
        mua_type=mua_type,
        category=category,
        confidence=confidence,
        automatable=is_automatable,
        screening_applicable=True,
        screening_reason=screening.reason,
        classification_reason=" ".join(reason_parts),
        rating_semantics=semantics,
        precedents_needed=_TYPE_PRECEDENTS_NEEDED.get(mua_type, 0),
        companion_mua_ref=companion_ref,
    )


def classify_mua_batch(
    items: list[dict[str, Any]],
) -> list[ClassifierResult]:
    """Classify a batch of MIUL flags.

    Each item dict must contain:
    - maptis_code: str
    - issue_key: str
    - rating: str
    - material_class: str ("metal" or "nonmetallic")
    - media: str
    - environment: str (optional, defaults to "non-habitable")
    - o2_percent: float (optional)
    - batch_verified: bool (optional, defaults to False)

    Returns a list of ClassifierResult in the same order.
    """
    results: list[ClassifierResult] = []
    for item in items:
        result = classify_mua(
            maptis_code=item["maptis_code"],
            issue_key=item["issue_key"],
            rating=item["rating"],
            material_class=item["material_class"],
            media=item["media"],
            environment=item.get("environment", "non-habitable"),
            o2_percent=item.get("o2_percent"),
            batch_verified=item.get("batch_verified", False),
        )
        results.append(result)
    return results
