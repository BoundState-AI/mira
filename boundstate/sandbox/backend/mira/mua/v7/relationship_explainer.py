"""MUA v7 Relationship Explainer --- Per-precedent plain-English explanations.

Core v7 innovation: every precedent returned by the investigator gets a
human-readable explanation of HOW it relates to the current MUA query.

Language rules (safety-critical):
- Always "may be applicable", never "is approved" or "is compatible".
- Always "may support your case", never "proves" or "confirms".
- Always "engineering judgment needed", never "automatically acceptable".
- For conflicting: "This precedent was [DETERMINATION] in [environment].
  If your application is [X], this precedent opposes your case."

Example outputs:
- "Strong analog. Same alloy, similar enriched O2 environment. Pressure
   envelope covers your requirement. Temperature range partially covers --
   your -100 degF lower bound extends beyond tested range. May require
   cryogenic gap disposition."
- "Same alloy at higher pressure, but ambient O2 only. Pressure data may
   support your case. O2 environment does not -- ambient air precedent
   cannot justify enriched O2 service without additional evidence."
- "Different alloy, same family (nickel superalloy). Exact O2 match.
   Lower pressure. May be applicable as family analog if specific
   precedent is insufficient -- alloy substitution requires engineering
   justification."
"""

from __future__ import annotations

import logging
from typing import Optional

from .models import (
    PrecedentMatch,
    MaterialResolution,
    EnvironmentSpec,
    ProcessParams,
    DeterminationStatus,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Thresholds
# ---------------------------------------------------------------------------

# Percent tolerance for considering a numeric value "similar" vs "different".
_O2_SIMILAR_TOLERANCE_PCT = 3.0        # 3 percentage points for O2
_PRESSURE_SIMILAR_RATIO = 0.15         # 15% relative difference
_TEMP_SIMILAR_TOLERANCE_F = 25.0       # 25 degF absolute difference

# O2 enrichment threshold per NASA-STD-6016.
_O2_ENRICHMENT_THRESHOLD = 23.5


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def generate_relationship_explanations(
    precedents: list[PrecedentMatch],
    query_material: MaterialResolution,
    query_environment: EnvironmentSpec,
    process_params: Optional[ProcessParams] = None,
) -> list[PrecedentMatch]:
    """Generate plain-English relationship explanations for each precedent.

    Updates each precedent's ``relationship_explanation`` field in-place
    and returns the same list (for chaining convenience).

    Parameters
    ----------
    precedents:
        Precedent matches from the search phase.
    query_material:
        Resolved material from Step 1.
    query_environment:
        Target environment specification.
    process_params:
        Optional process parameters (adhesives / composites).

    Returns
    -------
    list[PrecedentMatch]
        The same list with ``relationship_explanation`` populated.
    """
    for p in precedents:
        try:
            explanation = _explain_single_precedent(
                p, query_material, query_environment, process_params
            )
            p.relationship_explanation = explanation
        except Exception:
            logger.exception(
                "Failed to generate explanation for %s", p.mua_number
            )
            p.relationship_explanation = (
                "Unable to generate relationship explanation for this precedent.  "
                "Review the raw data directly."
            )

    return precedents


# ---------------------------------------------------------------------------
# Single-precedent explanation
# ---------------------------------------------------------------------------


def _explain_single_precedent(
    precedent: PrecedentMatch,
    query_material: MaterialResolution,
    query_environment: EnvironmentSpec,
    process_params: Optional[ProcessParams],
) -> str:
    """Build a plain-English explanation for one precedent.

    Assembles paragraphs covering:
    1. Material comparison (same/different alloy, same/different family).
    2. Environment comparison (O2%, pressure, temperature overlap).
    3. Determination relevance.
    4. Process comparison (adhesives/composites only).
    5. Gap flagging.
    """
    parts: list[str] = []

    mat_info = _compare_material(query_material, precedent)
    env_info = _compare_environment(query_environment, precedent)

    # ------------------------------------------------------------------
    # 1. Material comparison
    # ------------------------------------------------------------------
    if mat_info["same_alloy"]:
        parts.append("Same alloy")
    elif mat_info["same_family"]:
        family_label = precedent.material_family or "same family"
        parts.append(
            f"Different alloy, same family ({family_label})"
        )
    else:
        parts.append(
            f"Different material ({precedent.material_designation})"
        )

    # ------------------------------------------------------------------
    # 2. Environment comparison -- assemble per-dimension sentences
    # ------------------------------------------------------------------
    env_sentences: list[str] = []

    # O2 comparison
    o2 = env_info["o2"]
    if o2["status"] == "exact_match":
        env_sentences.append(f"exact O2 match ({precedent.o2_percent}%)")
    elif o2["status"] == "similar":
        env_sentences.append(
            f"similar O2 environment "
            f"(precedent {precedent.o2_percent}% vs query {query_environment.o2_percent}%)"
        )
    elif o2["status"] == "both_enriched":
        env_sentences.append(
            f"both enriched O2, but different concentrations "
            f"(precedent {precedent.o2_percent}% vs query {query_environment.o2_percent}%)"
        )
    elif o2["status"] == "query_enriched_prec_ambient":
        env_sentences.append(
            f"ambient O2 only in precedent ({precedent.o2_percent}%).  "
            f"Your query requires enriched O2 ({query_environment.o2_percent}%) "
            f"-- ambient air precedent cannot justify enriched O2 service "
            f"without additional evidence"
        )
    elif o2["status"] == "query_ambient_prec_enriched":
        env_sentences.append(
            f"precedent was evaluated in enriched O2 ({precedent.o2_percent}%), "
            f"which bounds your ambient O2 requirement ({query_environment.o2_percent}%)"
        )
    elif o2["status"] == "insufficient_data":
        env_sentences.append("O2 data missing from precedent")
    else:
        env_sentences.append(
            f"O2 mismatch (precedent {precedent.o2_percent}% vs "
            f"query {query_environment.o2_percent}%)"
        )

    # Pressure comparison
    pres = env_info["pressure"]
    if pres["status"] == "exact_match":
        env_sentences.append("exact pressure match")
    elif pres["status"] == "covers":
        env_sentences.append(
            f"pressure envelope covers your requirement "
            f"(precedent {precedent.pressure_psia} psia >= "
            f"query {query_environment.pressure_psia} psia)"
        )
    elif pres["status"] == "similar":
        env_sentences.append(
            f"similar pressure "
            f"(precedent {precedent.pressure_psia} psia vs "
            f"query {query_environment.pressure_psia} psia)"
        )
    elif pres["status"] == "lower":
        env_sentences.append(
            f"lower pressure in precedent "
            f"({precedent.pressure_psia} psia vs "
            f"query {query_environment.pressure_psia} psia).  "
            f"Pressure data may support your case for the overlapping range, "
            f"but does not cover the full requirement"
        )
    elif pres["status"] == "insufficient_data":
        env_sentences.append("pressure data missing from precedent")
    else:
        env_sentences.append(
            f"pressure mismatch (precedent {precedent.pressure_psia} psia vs "
            f"query {query_environment.pressure_psia} psia)"
        )

    # Temperature comparison
    temp = env_info["temperature"]
    if temp["status"] == "within":
        env_sentences.append("temperature range fully covers your requirement")
    elif temp["status"] == "partial_low":
        env_sentences.append(
            f"temperature range partially covers -- "
            f"your {query_environment.temp_min_f} degF lower bound extends "
            f"beyond tested range (precedent low: {precedent.temp_min_f} degF).  "
            f"May require cryogenic gap disposition"
        )
    elif temp["status"] == "partial_high":
        env_sentences.append(
            f"temperature range partially covers -- "
            f"your {query_environment.temp_max_f} degF upper bound extends "
            f"beyond tested range (precedent high: {precedent.temp_max_f} degF).  "
            f"High-temperature gap disposition may be needed"
        )
    elif temp["status"] == "partial_both":
        env_sentences.append(
            f"temperature range partially covers -- "
            f"both your lower bound ({query_environment.temp_min_f} degF) and "
            f"upper bound ({query_environment.temp_max_f} degF) extend beyond "
            f"the tested range [{precedent.temp_min_f} to {precedent.temp_max_f} degF].  "
            f"Temperature gap disposition required"
        )
    elif temp["status"] == "outside":
        env_sentences.append(
            f"temperature range does not overlap "
            f"(precedent [{precedent.temp_min_f} to {precedent.temp_max_f} degF] "
            f"vs query [{query_environment.temp_min_f} to {query_environment.temp_max_f} degF])"
        )
    elif temp["status"] == "insufficient_data":
        env_sentences.append("temperature data missing from precedent")

    # Join the material and environment parts.
    if env_sentences:
        # First sentence connects to material with a period-separated structure.
        combined_env = "; ".join(env_sentences)
        parts.append(combined_env)

    # ------------------------------------------------------------------
    # 3. Determination relevance
    # ------------------------------------------------------------------
    det = precedent.determination
    if precedent.is_conflicting:
        det_text = (
            f"This precedent was {det.value.upper()} in "
            f"{precedent.environment_description}.  "
        )
        if det == DeterminationStatus.REJECTED:
            det_text += (
                "If your application conditions are similar, this precedent "
                "opposes your case.  Engineering judgment needed to determine "
                "whether the rejection basis applies to your specific configuration."
            )
        elif det == DeterminationStatus.CANCELLED:
            det_text += (
                "This MUA was cancelled.  Determine whether the cancellation "
                "was due to material issues or programmatic reasons.  "
                "Engineering judgment needed."
            )
        else:
            det_text += (
                "Review the determination context to assess applicability "
                "to your query."
            )
        parts.append(det_text)
    else:
        if det == DeterminationStatus.APPROVED:
            parts.append(
                f"Precedent was approved for {precedent.environment_description}.  "
                f"May support your case if environment conditions are sufficiently similar."
            )
        elif det == DeterminationStatus.CONDITIONAL:
            parts.append(
                f"Precedent was conditionally approved for "
                f"{precedent.environment_description}.  "
                f"Review the conditions to determine if they apply to your query.  "
                f"May be applicable if conditions are met."
            )
        elif det == DeterminationStatus.DEFERRED:
            parts.append(
                f"Precedent determination was deferred.  "
                f"Limited applicability -- review the deferral basis."
            )
        else:
            parts.append(
                f"Precedent determination is {det.value}.  "
                f"Limited applicability until determination status is resolved."
            )

    # ------------------------------------------------------------------
    # 4. Process comparison (adhesives / composites only)
    # ------------------------------------------------------------------
    if process_params is not None:
        process_note = _compare_process(process_params, precedent)
        if process_note:
            parts.append(process_note)

    # ------------------------------------------------------------------
    # 5. Family analog note
    # ------------------------------------------------------------------
    if mat_info["same_family"] and not mat_info["same_alloy"]:
        parts.append(
            "May be applicable as family analog if specific-alloy precedent "
            "is insufficient -- alloy substitution requires engineering justification."
        )

    # ------------------------------------------------------------------
    # 6. Different-family note
    # ------------------------------------------------------------------
    if not mat_info["same_family"] and not mat_info["same_alloy"]:
        parts.append(
            "Different material family.  Applicability is limited -- "
            "may provide contextual data only.  "
            "Engineering judgment needed to assess cross-family relevance."
        )

    # Build the final explanation.
    explanation = ".  ".join(parts)
    # Ensure it ends with a period.
    if not explanation.endswith("."):
        explanation += "."

    return explanation


# ---------------------------------------------------------------------------
# Comparison helpers
# ---------------------------------------------------------------------------


def _compare_environment(
    query_env: EnvironmentSpec,
    precedent: PrecedentMatch,
) -> dict:
    """Per-dimension environment comparison between query and precedent.

    Returns a dict with keys ``o2``, ``pressure``, ``temperature``,
    each containing ``status`` and dimension-specific metadata.
    """
    result: dict = {}

    # --- O2 comparison ---
    prec_o2 = precedent.o2_percent
    query_o2 = query_env.o2_percent

    if prec_o2 is None:
        result["o2"] = {"status": "insufficient_data"}
    elif abs(prec_o2 - query_o2) < 0.1:
        result["o2"] = {"status": "exact_match", "delta": 0.0}
    elif abs(prec_o2 - query_o2) <= _O2_SIMILAR_TOLERANCE_PCT:
        result["o2"] = {"status": "similar", "delta": query_o2 - prec_o2}
    elif prec_o2 >= _O2_ENRICHMENT_THRESHOLD and query_o2 >= _O2_ENRICHMENT_THRESHOLD:
        result["o2"] = {"status": "both_enriched", "delta": query_o2 - prec_o2}
    elif query_o2 >= _O2_ENRICHMENT_THRESHOLD and prec_o2 < _O2_ENRICHMENT_THRESHOLD:
        result["o2"] = {"status": "query_enriched_prec_ambient", "delta": query_o2 - prec_o2}
    elif prec_o2 >= _O2_ENRICHMENT_THRESHOLD and query_o2 < _O2_ENRICHMENT_THRESHOLD:
        result["o2"] = {"status": "query_ambient_prec_enriched", "delta": query_o2 - prec_o2}
    else:
        result["o2"] = {"status": "mismatch", "delta": query_o2 - prec_o2}

    # --- Pressure comparison ---
    prec_psi = precedent.pressure_psia
    query_psi = query_env.pressure_psia

    if prec_psi is None:
        result["pressure"] = {"status": "insufficient_data"}
    elif abs(prec_psi - query_psi) < 0.1:
        result["pressure"] = {"status": "exact_match", "delta": 0.0}
    elif prec_psi >= query_psi:
        # Precedent tested at equal or higher pressure -- it covers the query.
        relative_diff = abs(prec_psi - query_psi) / max(query_psi, 0.1)
        if relative_diff <= _PRESSURE_SIMILAR_RATIO:
            result["pressure"] = {"status": "similar", "delta": query_psi - prec_psi}
        else:
            result["pressure"] = {"status": "covers", "delta": query_psi - prec_psi}
    else:
        # Precedent tested at lower pressure.
        relative_diff = abs(prec_psi - query_psi) / max(query_psi, 0.1)
        if relative_diff <= _PRESSURE_SIMILAR_RATIO:
            result["pressure"] = {"status": "similar", "delta": query_psi - prec_psi}
        else:
            result["pressure"] = {"status": "lower", "delta": query_psi - prec_psi}

    # --- Temperature comparison ---
    prec_t_min = precedent.temp_min_f
    prec_t_max = precedent.temp_max_f
    query_t_min = query_env.temp_min_f
    query_t_max = query_env.temp_max_f

    if prec_t_min is None or prec_t_max is None:
        result["temperature"] = {"status": "insufficient_data"}
    else:
        low_covered = prec_t_min <= query_t_min + _TEMP_SIMILAR_TOLERANCE_F
        high_covered = prec_t_max >= query_t_max - _TEMP_SIMILAR_TOLERANCE_F

        if low_covered and high_covered:
            result["temperature"] = {"status": "within"}
        elif not low_covered and not high_covered:
            # Check if there is ANY overlap.
            if prec_t_max < query_t_min or prec_t_min > query_t_max:
                result["temperature"] = {"status": "outside"}
            else:
                result["temperature"] = {"status": "partial_both"}
        elif not low_covered:
            result["temperature"] = {"status": "partial_low"}
        else:
            result["temperature"] = {"status": "partial_high"}

    return result


def _compare_material(
    query_material: MaterialResolution,
    precedent: PrecedentMatch,
) -> dict:
    """Material identity comparison.

    Returns a dict with:
    - ``same_alloy``: bool -- exact designation match.
    - ``same_family``: bool -- same material family (e.g. both aluminum).
    - ``query_name``: str
    - ``precedent_name``: str
    """
    query_name = (query_material.resolved_name or query_material.input_text).strip()
    prec_name = (precedent.material_designation or "").strip()

    # Exact match: normalize by stripping common suffixes/prefixes and casing.
    same_alloy = _normalize_alloy_name(query_name) == _normalize_alloy_name(prec_name)

    # Family match.
    query_family = (query_material.family or "").lower().strip()
    prec_family = (precedent.material_family or "").lower().strip()
    same_family = (
        same_alloy
        or (query_family != "" and prec_family != "" and query_family == prec_family)
    )

    return {
        "same_alloy": same_alloy,
        "same_family": same_family,
        "query_name": query_name,
        "precedent_name": prec_name,
    }


def _compare_process(
    process_params: ProcessParams,
    precedent: PrecedentMatch,
) -> str:
    """Generate a process-parameter comparison note.

    Since the precedent model does not carry process parameters (they are
    stored in the full MUA record), this produces a generic advisory for
    process-sensitive materials.
    """
    notes: list[str] = []

    if process_params.cure_temp_f is not None:
        notes.append(
            f"Your cure temperature is {process_params.cure_temp_f} degF"
        )
    if process_params.cure_time_min is not None:
        notes.append(
            f"cure time {process_params.cure_time_min} min"
        )
    if process_params.mix_ratio is not None:
        notes.append(
            f"mix ratio {process_params.mix_ratio}"
        )
    if process_params.layup_orientation is not None:
        notes.append(
            f"layup orientation {process_params.layup_orientation}"
        )

    if not notes:
        return ""

    param_summary = ", ".join(notes)
    return (
        f"Process-sensitive material.  {param_summary}.  "
        f"Precedent process parameters are not available in the summary record.  "
        f"Verify that the precedent cure schedule and process conditions are "
        f"compatible with your application.  Engineering judgment needed."
    )


def _normalize_alloy_name(name: str) -> str:
    """Normalize an alloy designation for comparison.

    Strips common suffixes like temper designations for aluminum
    (e.g. "-T6", "-T651"), removes spaces, lowercases, and strips
    generic prefixes ("alloy", "grade").
    """
    s = name.lower().strip()

    # Remove common generic prefixes.
    for prefix in ("alloy ", "grade ", "type "):
        if s.startswith(prefix):
            s = s[len(prefix):]

    # Remove temper suffixes for aluminum alloys (e.g. -T6, -T651, -T73).
    # This ensures "6061-T6" matches "6061-T651".
    import re
    s = re.sub(r"-t\d+\w*$", "", s)

    # Remove spaces, hyphens, underscores for generic normalization.
    s = re.sub(r"[\s\-_]", "", s)

    return s
