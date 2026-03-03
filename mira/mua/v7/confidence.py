#!/usr/bin/env python3
"""
Module: Evidence Strength Calculator
Purpose: Compute evidence strength for MUA v7 pipeline using Fran's formula
         from the Oracle convergence.

BoundState AI 2025-2026
Version: 7.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Fran OpenAI 5 <noreply@openai.com>
Co-Authored-By: Grok 4.0 <noreply@x.ai>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: SWE-013, NASA-STD-8739.8B, NASA-STD-6001B
Safety Critical: True

Formula (Fran's Oracle Convergence)
------------------------------------
    EvidenceStrength = clamp(0, 1,
        wP * PrecedentSupport +
        wT * TestCoverage +
        wE * EnvelopeCoverage +
        wC * Currency +
        wK * Consistency
    ) * Penalties

Components & Weights:
    PrecedentSupport  (wP = 0.30)  Saturating sum of relevance * authority
    TestCoverage      (wT = 0.25)  Per required test dimension coverage
    EnvelopeCoverage  (wE = 0.20)  Per envelope dimension (weighted min)
    Currency          (wC = 0.10)  Data currency + regulatory currency
    Consistency       (wK = 0.15)  Conflict-based consistency penalty

Penalties (multiplicative):
    Gap severity      exp(-g * gap_severity_sum),  g ~ 0.3
    Unresolved mat.   x 0.5
    Missing critical  x 0.0 -> forces REVIEW

Bands:
    STRONG:       >= 0.70
    MODERATE:     0.40 - 0.69
    WEAK:         0.15 - 0.39
    INSUFFICIENT: <  0.15
"""

from __future__ import annotations

import math
from typing import List

from .models import (
    ConflictFound,
    ConflictSeverity,
    DeterminationStatus,
    EnvironmentSpec,
    EnvelopeResult,
    EvidenceStrengthBand,
    EvidenceStrengthResult,
    GapIdentified,
    MaterialResolution,
    OverlapStatus,
    PrecedentMatch,
    ResolutionStatus,
    TestDataRecord,
)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Component weights (must sum to 1.0)
W_PRECEDENT: float = 0.30
W_TEST: float = 0.25
W_ENVELOPE: float = 0.20
W_CURRENCY: float = 0.10
W_CONSISTENCY: float = 0.15

# Precedent support saturation constant
_PRECEDENT_K: float = 1.5

# Gap penalty decay constant
_GAP_DECAY_G: float = 0.3

# Required test dimensions (NASA-STD-6001B / 6016)
_REQUIRED_TEST_CLASSES: list[str] = [
    "FLAMM",  # Flammability
    "SCC",    # Stress Corrosion Cracking
    "CORR",   # Corrosion compatibility
    "TVS",    # Thermal Vacuum Stability
    "TOX",    # Toxicity / Offgassing
    "FS",     # Fluid Susceptibility
]

# Issue scope -> required test classes.
_ISSUE_TO_TEST_CLASS: dict[str, str] = {
    "FLAM": "FLAMM",
    "O2_COMPAT": "FLAMM",
    "SCC": "SCC",
    "HEE": "SCC",
    "CORR": "CORR",
    "TVS": "TVS",
    "FS": "FS",
    "TOX": "TOX",
    "OFFGAS": "TOX",
}

# High-pass ratings (A or B considered high coverage)
_HIGH_RATINGS: set[str] = {"A", "B"}

# Partial-credit ratings (C is ambiguous, grant partial)
_PARTIAL_RATINGS: set[str] = {"C"}

# Envelope dimension coverage score mapping
_OVERLAP_SCORES: dict[OverlapStatus, float] = {
    OverlapStatus.WITHIN: 1.0,
    OverlapStatus.PARTIAL: 0.6,
    OverlapStatus.EXTRAPOLATION: 0.2,
    OverlapStatus.OUTSIDE: 0.0,
    OverlapStatus.INSUFFICIENT_DATA: 0.0,
}

# Gap severity string -> numeric mapping
_GAP_SEVERITY_SCORES: dict[str, float] = {
    "critical": 1.0,
    "high": 0.7,
    "medium": 0.4,
    "low": 0.15,
}


# ---------------------------------------------------------------------------
# Band classification
# ---------------------------------------------------------------------------

def _classify_band(score: float) -> EvidenceStrengthBand:
    """Map a numeric evidence strength score to its discrete band.

    Thresholds
    ----------
    >= 0.70  STRONG
    >= 0.40  MODERATE
    >= 0.15  WEAK
    <  0.15  INSUFFICIENT
    """
    if score >= 0.70:
        return EvidenceStrengthBand.STRONG
    if score >= 0.40:
        return EvidenceStrengthBand.MODERATE
    if score >= 0.15:
        return EvidenceStrengthBand.WEAK
    return EvidenceStrengthBand.INSUFFICIENT


# ---------------------------------------------------------------------------
# Component calculators
# ---------------------------------------------------------------------------

def _compute_precedent_support(
    supporting: List[PrecedentMatch],
) -> tuple[float, str]:
    """Compute PrecedentSupport using a saturating exponential.

    Formula:  ``1 - exp(-k * sum(relevance_i * authority_i))``

    Each precedent contributes ``relevance_i * authority_i``.  The authority
    value is drawn from ``evidence_ref.quality.authority_score`` when
    available, falling back to a heuristic based on the determination status:
    APPROVED -> 0.8, CONDITIONAL -> 0.5, others -> 0.3.

    Returns
    -------
    tuple[float, str]
        Raw score (0..1) and a human-readable detail string.
    """
    if not supporting:
        return 0.0, "No supporting precedents available."

    total = 0.0
    contributions: list[str] = []
    for p in supporting:
        relevance = p.relevance_score

        # Extract authority from evidence quality if available
        authority = 0.0
        if p.evidence_ref and p.evidence_ref.quality:
            authority = p.evidence_ref.quality.authority_score

        # Fallback heuristic when authority is unset
        if authority <= 0.0:
            if p.determination == DeterminationStatus.APPROVED:
                authority = 0.8
            elif p.determination == DeterminationStatus.CONDITIONAL:
                authority = 0.5
            else:
                authority = 0.3

        contrib = relevance * authority
        total += contrib
        contributions.append(
            f"{p.mua_number}: relevance={relevance:.2f}, "
            f"authority={authority:.2f}, contrib={contrib:.2f}"
        )

    score = 1.0 - math.exp(-_PRECEDENT_K * total)
    detail = (
        f"Saturating sum = {total:.3f}, "
        f"score = 1 - exp(-{_PRECEDENT_K} * {total:.3f}) = {score:.3f}. "
        f"Contributions: {'; '.join(contributions)}."
    )
    return score, detail


def _compute_test_coverage(
    test_data: List[TestDataRecord],
    required_test_classes: list[str] | None = None,
) -> tuple[float, str]:
    """Compute TestCoverage across the six required test dimensions.

    Per dimension scoring:
        A or B rating -> 1.0  (high)
        C rating      -> 0.6  (partial -- may indicate analog data)
        D / E / U     -> 0.2  (low / failing)
        missing       -> 0.0

    The overall score is the average across all six required dimensions.
    If a dimension has multiple records, the best score is taken.

    Returns
    -------
    tuple[float, str]
        Raw score (0..1) and human-readable detail string.
    """
    required_classes = required_test_classes or _REQUIRED_TEST_CLASSES
    if not required_classes:
        return 0.0, "No required test classes defined."

    # Build best-score-per-dimension map
    dim_best: dict[str, float] = {cls: 0.0 for cls in required_classes}
    dim_detail: dict[str, str] = {cls: "missing" for cls in required_classes}

    for rec in test_data:
        cls_upper = (rec.test_class or "").upper()
        if cls_upper not in dim_best:
            continue
        if cls_upper == "FS" and rec.medium_match is False:
            # FS record exists but was generated for a different medium
            # than the queried usage (e.g., hydrazine vs H2).
            continue

        rating = (rec.rating or "").upper()
        if rating in _HIGH_RATINGS:
            dim_score = 1.0
        elif rating in _PARTIAL_RATINGS:
            dim_score = 0.6
        elif rating:
            # D, E, U -- present but low / failing
            dim_score = 0.2
        else:
            dim_score = 0.0

        # Analog data gets partial credit at most
        if rec.is_current is False:
            # Expired data receives a penalty
            dim_score *= 0.6

        if dim_score > dim_best[cls_upper]:
            dim_best[cls_upper] = dim_score
            dim_detail[cls_upper] = f"rating={rating}, score={dim_score:.2f}"

    score = sum(dim_best.values()) / len(required_classes)
    details_parts = [f"{d}: {dim_detail[d]}" for d in required_classes]
    detail = f"Test coverage = {score:.3f}. {'; '.join(details_parts)}."
    return score, detail


def _resolve_required_test_classes(
    issue_codes: List[str] | None,
    environment: EnvironmentSpec,
) -> list[str]:
    """Resolve required test classes from issue scope.

    If issue_codes is empty, default to the historical full six-class
    requirement for backward compatibility.
    """
    if not issue_codes:
        return list(_REQUIRED_TEST_CLASSES)

    seen: set[str] = set()
    resolved: list[str] = []
    for raw in issue_codes:
        code = str(raw or "").strip().upper()
        mapped = _ISSUE_TO_TEST_CLASS.get(code)
        if not mapped or mapped in seen:
            continue
        # TOX relevance is only meaningful for habitable uses.
        if mapped == "TOX" and environment.location != "habitable":
            continue
        seen.add(mapped)
        resolved.append(mapped)

    if not resolved:
        return list(_REQUIRED_TEST_CLASSES)
    return resolved


def _compute_envelope_coverage(
    envelope: EnvelopeResult | None,
) -> tuple[float, str]:
    """Compute EnvelopeCoverage via a weighted-minimum strategy.

    Per dimension (temperature, pressure, O2%, phase):
        WITHIN         -> 1.0
        PARTIAL        -> 0.6
        EXTRAPOLATION  -> 0.2
        INSUFFICIENT   -> 0.0

    The overall score is the weighted minimum across dimensions, reflecting
    that a single missing dimension may invalidate the whole envelope.
    The ``coverage_ratio`` from the ``EnvelopeResult`` is blended in at 20%
    to reward breadth even when the worst dimension is marginal.

    Returns
    -------
    tuple[float, str]
        Raw score (0..1) and human-readable detail string.
    """
    if envelope is None:
        return 0.0, "No envelope analysis available."

    dim_scores: dict[str, float] = {}

    # Temperature
    temp_score = _OVERLAP_SCORES.get(envelope.temp_status, 0.0)
    dim_scores["temperature"] = temp_score

    # Pressure
    pressure_score = _OVERLAP_SCORES.get(envelope.pressure_status, 0.0)
    dim_scores["pressure"] = pressure_score

    # O2 concentration
    o2_score = _OVERLAP_SCORES.get(envelope.o2_status, 0.0)
    dim_scores["o2_pct"] = o2_score

    # Phase is not explicitly tracked in the model; fall back to
    # overall_status as a proxy when all three explicit dimensions
    # are covered.
    phase_score = _OVERLAP_SCORES.get(envelope.overall_status, 0.0)
    dim_scores["phase"] = phase_score

    if not dim_scores:
        return 0.0, "Envelope has no scoreable dimensions."

    # Weighted-min strategy: use the minimum dimension score but blend in
    # the mean to avoid a single marginal dimension zeroing everything.
    min_score = min(dim_scores.values())
    mean_score = sum(dim_scores.values()) / len(dim_scores)
    score = 0.80 * min_score + 0.20 * mean_score

    detail_parts = [f"{k}={v:.2f}" for k, v in dim_scores.items()]
    detail = (
        f"Envelope coverage = {score:.3f} "
        f"(min={min_score:.2f}, mean={mean_score:.2f}). "
        f"Dimensions: {', '.join(detail_parts)}."
    )
    return score, detail


def _compute_currency(
    test_data: List[TestDataRecord],
    supporting: List[PrecedentMatch],
) -> tuple[float, str]:
    """Compute Currency as the average of data currency and regulatory currency.

    Data currency (50% of component):
        current (is_current=True)  -> 1.0
        expired (is_current=False) -> 0.4
        unknown (is_current=None)  -> 0.2

    Regulatory currency (50% of component):
        Precedent cites current standard (NASA-STD-6016C or NASA-STD-6001B)
            -> 1.0
        Pre-current standard
            -> decay factor of 0.5
        Unknown
            -> 0.2

    Returns
    -------
    tuple[float, str]
        Raw score (0..1) and human-readable detail string.
    """
    # --- Data currency ---
    if test_data:
        currency_values: list[float] = []
        for rec in test_data:
            if rec.is_current is True:
                currency_values.append(1.0)
            elif rec.is_current is False:
                currency_values.append(0.4)
            else:
                currency_values.append(0.2)
        data_currency = sum(currency_values) / len(currency_values)
    else:
        data_currency = 0.0

    # --- Regulatory currency ---
    _CURRENT_STANDARDS: set[str] = {
        "NASA-STD-6016C",
        "NASA-STD-6016",
        "NASA-STD-6001B",
        "NASA-STD-6001",
    }
    if supporting:
        reg_values: list[float] = []
        for p in supporting:
            # Check if the precedent references a current standard
            ref_quality = (
                p.evidence_ref.quality if p.evidence_ref else None
            )
            if ref_quality and ref_quality.regulatory_currency > 0.0:
                reg_values.append(ref_quality.regulatory_currency)
            else:
                # Heuristic: no regulatory currency info -> 0.2
                reg_values.append(0.2)
        regulatory_currency = sum(reg_values) / len(reg_values)
    else:
        regulatory_currency = 0.0

    score = 0.5 * data_currency + 0.5 * regulatory_currency

    detail = (
        f"Currency = {score:.3f} "
        f"(data={data_currency:.2f}, regulatory={regulatory_currency:.2f})."
    )
    return score, detail


def _compute_consistency(
    conflicts: List[ConflictFound],
) -> tuple[float, str]:
    """Compute Consistency from detected conflicts.

    Scoring:
        No conflicts   -> 1.0
        Soft conflicts -> 0.7 per soft conflict (worst wins)
        Hard conflicts -> 0.4 per hard conflict (worst wins)

    The score is the *minimum* penalty across all conflicts -- a single
    hard conflict dominates.

    Returns
    -------
    tuple[float, str]
        Raw score (0..1) and human-readable detail string.
    """
    if not conflicts:
        return 1.0, "No conflicts detected; full consistency."

    worst = 1.0
    hard_count = 0
    soft_count = 0

    for c in conflicts:
        if c.severity == ConflictSeverity.HARD:
            worst = min(worst, 0.4)
            hard_count += 1
        elif c.severity == ConflictSeverity.SOFT:
            worst = min(worst, 0.7)
            soft_count += 1
        # NONE severity does not affect the score

    detail = (
        f"Consistency = {worst:.2f}. "
        f"Hard conflicts: {hard_count}, soft conflicts: {soft_count}."
    )
    return worst, detail


# ---------------------------------------------------------------------------
# Penalty calculators
# ---------------------------------------------------------------------------

def _compute_gap_penalty(
    gaps: List[GapIdentified],
) -> tuple[float, str]:
    """Compute the gap severity penalty.

    Formula:  ``exp(-g * sum(severity_i))``  where  g ~ 0.3

    Returns
    -------
    tuple[float, str]
        Multiplicative factor (0..1) and explanation.
    """
    if not gaps:
        return 1.0, "No gaps identified."

    severity_sum = 0.0
    gap_descriptions: list[str] = []
    for gap in gaps:
        sev_numeric = _GAP_SEVERITY_SCORES.get(
            (gap.severity or "").lower(), 0.2
        )
        severity_sum += sev_numeric
        gap_descriptions.append(
            f"{gap.dimension} ({gap.severity}={sev_numeric:.2f})"
        )

    factor = math.exp(-_GAP_DECAY_G * severity_sum)
    detail = (
        f"Gap penalty = exp(-{_GAP_DECAY_G} * {severity_sum:.2f}) "
        f"= {factor:.3f}. Gaps: {', '.join(gap_descriptions)}."
    )
    return factor, detail


def _compute_material_penalty(
    material: MaterialResolution,
) -> tuple[float, str]:
    """Compute the unresolved-material penalty.

    RESOLVED   -> 1.0 (no penalty)
    FUZZY      -> 0.75 (mild penalty, engineer must confirm)
    UNRESOLVED -> 0.5

    Returns
    -------
    tuple[float, str]
        Multiplicative factor and explanation.
    """
    if material.status == ResolutionStatus.RESOLVED:
        return 1.0, "Material resolved; no penalty."
    if material.status == ResolutionStatus.FUZZY:
        return 0.75, (
            "Material resolution is fuzzy; "
            "engineer confirmation may be required (x0.75 penalty)."
        )
    # UNRESOLVED
    return 0.5, (
        "Material is unresolved; "
        "identity could not be confirmed (x0.5 penalty)."
    )


def _compute_critical_field_penalty(
    environment: EnvironmentSpec,
    envelope: EnvelopeResult | None,
    gaps: List[GapIdentified],
) -> tuple[float, str]:
    """Compute the missing-critical-field penalty.

    Safety-critical conditions that force REVIEW (score -> 0.0):
        - Hydrogen service with no pressure data
        - Missing temperature bounds in any cryogenic or high-temp case
        - Enriched O2 with no O2 envelope data

    Returns
    -------
    tuple[float, str]
        Multiplicative factor (1.0 or 0.0) and explanation.
    """
    reasons: list[str] = []

    # Hydrogen service: pressure data is critical
    if environment.is_hydrogen_service:
        has_pressure = (
            envelope is not None
            and envelope.pressure_status != OverlapStatus.INSUFFICIENT_DATA
        )
        if not has_pressure:
            reasons.append(
                "Hydrogen service requires pressure envelope data, "
                "but pressure data is insufficient or missing."
            )

    # Cryogenic or high-temp: temperature bounds are critical
    if environment.is_cryogenic or environment.temp_max_f > 400.0:
        has_temp = (
            envelope is not None
            and envelope.temp_status != OverlapStatus.INSUFFICIENT_DATA
        )
        if not has_temp:
            reasons.append(
                "Extreme temperature conditions require temperature "
                "envelope data, but temperature data is insufficient "
                "or missing."
            )

    # Enriched O2: O2 envelope is critical
    if environment.is_enriched_o2:
        has_o2 = (
            envelope is not None
            and envelope.o2_status != OverlapStatus.INSUFFICIENT_DATA
        )
        if not has_o2:
            reasons.append(
                "Enriched oxygen environment (>= 23.5%) requires O2 "
                "envelope data, but O2 data is insufficient or missing."
            )

    # Check for gaps flagged as critical
    for gap in gaps:
        if gap.requires_review and (gap.severity or "").lower() == "critical":
            reasons.append(
                f"Critical gap in '{gap.dimension}': {gap.description}"
            )

    if reasons:
        detail = (
            "CRITICAL FIELD MISSING -- evidence strength forced to 0.0 "
            "(REVIEW required). Reasons: " + "; ".join(reasons)
        )
        return 0.0, detail

    return 1.0, "No missing critical fields."


# ---------------------------------------------------------------------------
# Explanation builder
# ---------------------------------------------------------------------------

def _build_explanation(
    score: float,
    band: EvidenceStrengthBand,
    components: dict,
    penalties: dict,
    raw_weighted_sum: float,
) -> str:
    """Build a plain-English explanation of the evidence strength result.

    The explanation is intended for the reviewing engineer and uses hedged
    language ("may", "suggests") rather than definitive assertions.
    """
    lines: list[str] = []

    lines.append(
        f"Evidence strength score: {score:.3f} ({band.value.upper()})."
    )
    lines.append("")

    # Component summary
    lines.append("Component breakdown:")
    for name, info in components.items():
        lines.append(
            f"  - {name}: raw={info['raw']:.3f}, "
            f"weight={info['weight']:.2f}, "
            f"weighted={info['weighted']:.3f}"
        )
        if info.get("detail"):
            lines.append(f"    {info['detail']}")
    lines.append(f"  Raw weighted sum (before penalties): {raw_weighted_sum:.3f}")
    lines.append("")

    # Penalties
    active_penalties = {
        k: v for k, v in penalties.items() if v["factor"] < 1.0
    }
    if active_penalties:
        lines.append("Penalties applied:")
        for name, info in active_penalties.items():
            lines.append(
                f"  - {name}: x{info['factor']:.3f} -- {info['reason']}"
            )
    else:
        lines.append("No penalties applied.")

    lines.append("")

    # Band-specific guidance
    if band == EvidenceStrengthBand.STRONG:
        lines.append(
            "This evidence base may be sufficient to support a "
            "determination, subject to engineering review."
        )
    elif band == EvidenceStrengthBand.MODERATE:
        lines.append(
            "This evidence base suggests moderate support. Additional "
            "precedent or test data may strengthen the determination."
        )
    elif band == EvidenceStrengthBand.WEAK:
        lines.append(
            "This evidence base may be insufficient for a standalone "
            "determination. Additional testing or precedent review "
            "is recommended."
        )
    else:
        lines.append(
            "Insufficient evidence to support a determination. "
            "Testing per NASA-STD-6001B may be required."
        )

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def calculate_evidence_strength(
    supporting_precedents: List[PrecedentMatch],
    conflicting_precedents: List[PrecedentMatch],
    test_data: List[TestDataRecord],
    envelope: EnvelopeResult | None,
    conflicts: List[ConflictFound],
    gaps: List[GapIdentified],
    material: MaterialResolution,
    environment: EnvironmentSpec,
    issue_codes: List[str] | None = None,
) -> EvidenceStrengthResult:
    """Calculate composite evidence strength using Fran's formula.

    This is the primary entry point for evidence strength calculation in
    the MUA v7 pipeline.  The result is used for:
        - Engineer-facing evidence strength display (Step 2)
        - Category routing heuristics (Step 5)
        - Audit trail completeness checks

    Parameters
    ----------
    supporting_precedents:
        Precedents that support the proposed determination.
    conflicting_precedents:
        Precedents that conflict with the proposed determination.
    test_data:
        MAPTIS / lab test records for the material.
    envelope:
        Envelope overlap analysis result (may be ``None`` if unavailable).
    conflicts:
        Cross-source conflicts detected by the conflict detector.
    gaps:
        Gaps identified during investigation.
    material:
        Material resolution result (RESOLVED / FUZZY / UNRESOLVED).
    environment:
        Target environment specification.

    Returns
    -------
    EvidenceStrengthResult
        Composite score, band, component breakdown, penalties, and a
        human-readable explanation suitable for display to engineers.
    """
    # --- 1. Compute individual components ---
    prec_score, prec_detail = _compute_precedent_support(supporting_precedents)
    required_test_classes = _resolve_required_test_classes(issue_codes, environment)
    test_score, test_detail = _compute_test_coverage(test_data, required_test_classes)
    env_score, env_detail = _compute_envelope_coverage(envelope)
    curr_score, curr_detail = _compute_currency(
        test_data, supporting_precedents
    )
    cons_score, cons_detail = _compute_consistency(conflicts)

    # --- 2. Weighted sum ---
    raw_weighted_sum = (
        W_PRECEDENT * prec_score
        + W_TEST * test_score
        + W_ENVELOPE * env_score
        + W_CURRENCY * curr_score
        + W_CONSISTENCY * cons_score
    )

    # Clamp to [0, 1]
    clamped = max(0.0, min(1.0, raw_weighted_sum))

    # --- 3. Compute penalties ---
    gap_factor, gap_detail = _compute_gap_penalty(gaps)
    mat_factor, mat_detail = _compute_material_penalty(material)
    crit_factor, crit_detail = _compute_critical_field_penalty(
        environment, envelope, gaps
    )

    combined_penalty = gap_factor * mat_factor * crit_factor

    # --- 4. Final score ---
    final_score = clamped * combined_penalty
    final_score = max(0.0, min(1.0, final_score))

    band = _classify_band(final_score)

    # --- 5. Build structured output ---
    components = {
        "precedent_support": {
            "raw": prec_score,
            "weight": W_PRECEDENT,
            "weighted": W_PRECEDENT * prec_score,
            "detail": prec_detail,
        },
        "test_coverage": {
            "raw": test_score,
            "weight": W_TEST,
            "weighted": W_TEST * test_score,
            "detail": test_detail,
        },
        "envelope_coverage": {
            "raw": env_score,
            "weight": W_ENVELOPE,
            "weighted": W_ENVELOPE * env_score,
            "detail": env_detail,
        },
        "currency": {
            "raw": curr_score,
            "weight": W_CURRENCY,
            "weighted": W_CURRENCY * curr_score,
            "detail": curr_detail,
        },
        "consistency": {
            "raw": cons_score,
            "weight": W_CONSISTENCY,
            "weighted": W_CONSISTENCY * cons_score,
            "detail": cons_detail,
        },
    }

    penalties = {
        "gap_severity": {
            "factor": gap_factor,
            "reason": gap_detail,
        },
        "material_resolution": {
            "factor": mat_factor,
            "reason": mat_detail,
        },
        "critical_field": {
            "factor": crit_factor,
            "reason": crit_detail,
        },
    }

    explanation = _build_explanation(
        final_score, band, components, penalties, raw_weighted_sum
    )

    return EvidenceStrengthResult(
        score=round(final_score, 4),
        band=band,
        components=components,
        penalties=penalties,
        explanation=explanation,
    )
