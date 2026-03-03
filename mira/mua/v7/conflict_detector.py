#!/usr/bin/env python3
"""
Module: Cross-Source Conflict Detector
Purpose: Detect contradictions across MUA precedents and MAPTIS test data.

BoundState AI 2025-2026
Version: 7.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Fran OpenAI 5 <noreply@openai.com>
Co-Authored-By: Grok 4.0 <noreply@x.ai>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: SWE-013, NASA-STD-8739.8B, NASA-STD-6001B
Safety Critical: True

Background
----------
The v6 pipeline lacked cross-source conflict detection entirely (H1 finding
in the 2025 safety audit).  This module closes that gap by checking:

    1. Supporting vs conflicting precedent contradictions
    2. MAPTIS test data vs BOK precedent contradictions
    3. Within-supporting precedent contradictions

All output uses hedged ("may") language -- this system does NOT make
safety determinations.  It surfaces potential conflicts for engineering
review.
"""

from __future__ import annotations

import uuid
from typing import List, Optional

from .models import (
    ConflictFound,
    ConflictSeverity,
    DeterminationStatus,
    PrecedentMatch,
    TestDataRecord,
)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Determinations considered "positive" (material is suitable)
_POSITIVE_DETERMINATIONS: frozenset[DeterminationStatus] = frozenset({
    DeterminationStatus.APPROVED,
    DeterminationStatus.CONDITIONAL,
})

# Determinations considered "negative" (material is not suitable)
_NEGATIVE_DETERMINATIONS: frozenset[DeterminationStatus] = frozenset({
    DeterminationStatus.REJECTED,
})

# MAPTIS ratings considered "passing"
_PASSING_RATINGS: frozenset[str] = frozenset({"A", "B"})

# MAPTIS ratings considered "failing" or "marginal"
_FAILING_RATINGS: frozenset[str] = frozenset({"D", "E"})

# MAPTIS ratings considered "ambiguous"
_AMBIGUOUS_RATINGS: frozenset[str] = frozenset({"C", "U"})

# Test class human-readable names
_TEST_CLASS_NAMES: dict[str, str] = {
    "FLAMM": "flammability",
    "SCC": "stress corrosion cracking",
    "CORR": "corrosion compatibility",
    "TVS": "thermal vacuum stability",
    "TOX": "toxicity / offgassing",
    "FS": "fluid susceptibility",
}


# ---------------------------------------------------------------------------
# Internal ID generation
# ---------------------------------------------------------------------------

def _new_conflict_id() -> str:
    """Generate a unique conflict identifier."""
    return f"CFT-{uuid.uuid4().hex[:12].upper()}"


# ---------------------------------------------------------------------------
# Description generator
# ---------------------------------------------------------------------------

def _generate_conflict_description(
    source_a: str,
    source_b: str,
    conflict_type: str,
    *,
    detail_a: str = "",
    detail_b: str = "",
    context: str = "",
) -> str:
    """Generate a human-readable conflict description.

    Uses hedged ("may") language throughout -- this module surfaces
    potential issues for engineering review, it does not make safety
    determinations.

    Parameters
    ----------
    source_a:
        Identifier of the first source (e.g. MUA number or test record).
    source_b:
        Identifier of the second source.
    conflict_type:
        Category of conflict (e.g. "precedent_vs_precedent").
    detail_a:
        Optional detail string for source A (e.g. "APPROVED").
    detail_b:
        Optional detail string for source B (e.g. "D-rating for FLAMM").
    context:
        Additional context about why this may matter.

    Returns
    -------
    str
        A plain-English explanation suitable for display to an engineer.
    """
    type_phrases: dict[str, str] = {
        "precedent_vs_precedent": (
            f"Precedent {source_a} and precedent {source_b} may contain "
            f"contradictory determinations for similar materials or "
            f"environments."
        ),
        "within_supporting": (
            f"Supporting precedents {source_a} and {source_b} may contain "
            f"contradictory implications despite both being classified as "
            f"supporting."
        ),
        "same_family_contradiction": (
            f"Precedents {source_a} and {source_b} cover materials in the "
            f"same family but may have contradictory outcomes."
        ),
        "maptis_vs_precedent": (
            f"Test data from {source_a} may contradict the determination "
            f"in precedent {source_b}."
        ),
        "rating_vs_determination": (
            f"MAPTIS rating from {source_a} may be inconsistent with "
            f"the MUA determination in {source_b}."
        ),
    }

    base = type_phrases.get(
        conflict_type,
        (
            f"A potential conflict was detected between {source_a} and "
            f"{source_b} (type: {conflict_type})."
        ),
    )

    parts: list[str] = [base]

    if detail_a:
        parts.append(f"{source_a} indicates: {detail_a}.")
    if detail_b:
        parts.append(f"{source_b} indicates: {detail_b}.")
    if context:
        parts.append(context)

    return " ".join(parts)


# ---------------------------------------------------------------------------
# Recommendation generator
# ---------------------------------------------------------------------------

def _generate_recommendation(
    severity: ConflictSeverity,
    conflict_type: str,
) -> str:
    """Generate a plain-English recommendation for a detected conflict.

    Parameters
    ----------
    severity:
        The assessed severity of the conflict.
    conflict_type:
        Category of conflict.

    Returns
    -------
    str
        Actionable guidance for the reviewing engineer.
    """
    if severity == ConflictSeverity.HARD:
        base = (
            "This conflict may represent a material safety concern. "
            "Engineering review is recommended before proceeding with "
            "the determination."
        )
        if conflict_type in ("maptis_vs_precedent", "rating_vs_determination"):
            return (
                f"{base} The reviewing engineer may wish to verify whether "
                f"the test data and precedent apply to the same material "
                f"configuration and environment conditions."
            )
        if conflict_type == "precedent_vs_precedent":
            return (
                f"{base} The reviewing engineer may wish to examine whether "
                f"differences in environment, configuration, or testing "
                f"conditions explain the contradictory determinations."
            )
        return base

    if severity == ConflictSeverity.SOFT:
        return (
            "This may represent a minor inconsistency. The reviewing "
            "engineer may wish to note this conflict and confirm that "
            "the differences do not affect the current determination."
        )

    return "No action required; conflict severity is minimal."


# ---------------------------------------------------------------------------
# Precedent-vs-precedent conflict detection
# ---------------------------------------------------------------------------

def _environments_may_overlap(
    a: PrecedentMatch,
    b: PrecedentMatch,
) -> bool:
    """Heuristic check for whether two precedents may cover overlapping environments.

    This is intentionally conservative -- it returns ``True`` when
    overlap cannot be ruled out, preferring false positives over
    missed conflicts.
    """
    # If either has no environment description, assume possible overlap
    env_a = (a.environment_description or "").lower()
    env_b = (b.environment_description or "").lower()

    if not env_a or not env_b:
        return True

    # Simple keyword overlap heuristic
    keywords_a = set(env_a.split())
    keywords_b = set(env_b.split())
    if keywords_a & keywords_b:
        return True

    # Check O2 percentage overlap (if both have data)
    if a.o2_percent is not None and b.o2_percent is not None:
        # Both enriched or both ambient -> may overlap
        a_enriched = a.o2_percent >= 23.5
        b_enriched = b.o2_percent >= 23.5
        if a_enriched == b_enriched:
            return True

    # Pressure/temp ranges overlap check
    if (
        a.pressure_psia is not None
        and b.pressure_psia is not None
    ):
        # Rough overlap: within 2x of each other
        ratio = (
            max(a.pressure_psia, b.pressure_psia)
            / max(min(a.pressure_psia, b.pressure_psia), 0.01)
        )
        if ratio <= 2.0:
            return True

    return False


def _materials_in_same_family(
    a: PrecedentMatch,
    b: PrecedentMatch,
) -> bool:
    """Check if two precedents reference materials in the same family."""
    if a.material_family and b.material_family:
        return a.material_family.lower() == b.material_family.lower()
    # Fallback: check if the material designations share a common root
    name_a = (a.material_designation or "").lower()
    name_b = (b.material_designation or "").lower()
    if name_a and name_b:
        # Crude prefix check (e.g. "316" in "316L" and "316SS")
        short = min(name_a, name_b, key=len)
        long = max(name_a, name_b, key=len)
        if short and long.startswith(short[:4]):
            return True
    return False


def _check_precedent_conflicts(
    supporting: List[PrecedentMatch],
    conflicting: List[PrecedentMatch],
) -> List[ConflictFound]:
    """Detect conflicts between and within precedent sets.

    Checks performed:
        1. Each supporting precedent vs each conflicting precedent
           with similar environments -> HARD conflict if determinations
           contradict.
        2. Within supporting: two precedents with opposing determination
           implications in similar environments -> SOFT or HARD.
        3. Same material family with contradictory results across
           different precedents -> SOFT.

    Parameters
    ----------
    supporting:
        Precedents classified as supporting the proposed determination.
    conflicting:
        Precedents classified as conflicting with the proposed determination.

    Returns
    -------
    list[ConflictFound]
        Detected conflicts with severity, descriptions, and recommendations.
    """
    results: list[ConflictFound] = []

    # --- 1. Supporting vs Conflicting ---
    for sup in supporting:
        for con in conflicting:
            if not _environments_may_overlap(sup, con):
                continue

            sup_positive = sup.determination in _POSITIVE_DETERMINATIONS
            con_negative = con.determination in _NEGATIVE_DETERMINATIONS

            if sup_positive and con_negative:
                severity = ConflictSeverity.HARD
            elif sup.determination != con.determination:
                severity = ConflictSeverity.SOFT
            else:
                continue

            description = _generate_conflict_description(
                source_a=sup.mua_number,
                source_b=con.mua_number,
                conflict_type="precedent_vs_precedent",
                detail_a=f"determination={sup.determination.value}",
                detail_b=f"determination={con.determination.value}",
                context=(
                    "These precedents may apply to overlapping environments "
                    "and may reach different conclusions about material "
                    "suitability."
                ),
            )

            results.append(ConflictFound(
                conflict_id=_new_conflict_id(),
                severity=severity,
                source_a=sup.mua_number,
                source_b=con.mua_number,
                description=description,
                recommendation=_generate_recommendation(
                    severity, "precedent_vs_precedent"
                ),
            ))

    # --- 2. Within-supporting contradictions ---
    for i, a in enumerate(supporting):
        for b in supporting[i + 1:]:
            if not _environments_may_overlap(a, b):
                continue

            a_positive = a.determination in _POSITIVE_DETERMINATIONS
            b_positive = b.determination in _POSITIVE_DETERMINATIONS

            # Both supporting should be positive; flag if one is not
            if a_positive != b_positive:
                severity = ConflictSeverity.SOFT
                description = _generate_conflict_description(
                    source_a=a.mua_number,
                    source_b=b.mua_number,
                    conflict_type="within_supporting",
                    detail_a=f"determination={a.determination.value}",
                    detail_b=f"determination={b.determination.value}",
                    context=(
                        "Both precedents are classified as supporting, but "
                        "their determinations may not fully agree."
                    ),
                )
                results.append(ConflictFound(
                    conflict_id=_new_conflict_id(),
                    severity=severity,
                    source_a=a.mua_number,
                    source_b=b.mua_number,
                    description=description,
                    recommendation=_generate_recommendation(
                        severity, "within_supporting"
                    ),
                ))

            # APPROVED vs CONDITIONAL in similar environments
            elif (
                a.determination == DeterminationStatus.APPROVED
                and b.determination == DeterminationStatus.CONDITIONAL
            ) or (
                a.determination == DeterminationStatus.CONDITIONAL
                and b.determination == DeterminationStatus.APPROVED
            ):
                severity = ConflictSeverity.SOFT
                description = _generate_conflict_description(
                    source_a=a.mua_number,
                    source_b=b.mua_number,
                    conflict_type="within_supporting",
                    detail_a=f"determination={a.determination.value}",
                    detail_b=f"determination={b.determination.value}",
                    context=(
                        "One precedent was approved unconditionally while "
                        "the other was conditional. The conditions attached "
                        "to the conditional approval may be relevant."
                    ),
                )
                results.append(ConflictFound(
                    conflict_id=_new_conflict_id(),
                    severity=severity,
                    source_a=a.mua_number,
                    source_b=b.mua_number,
                    description=description,
                    recommendation=_generate_recommendation(
                        severity, "within_supporting"
                    ),
                ))

    # --- 3. Same-family contradictions ---
    all_precedents = list(supporting) + list(conflicting)
    seen_pairs: set[tuple[str, str]] = set()

    for i, a in enumerate(all_precedents):
        for b in all_precedents[i + 1:]:
            pair = tuple(sorted([a.mua_number, b.mua_number]))
            if pair in seen_pairs:
                continue

            if not _materials_in_same_family(a, b):
                continue

            a_positive = a.determination in _POSITIVE_DETERMINATIONS
            b_positive = b.determination in _POSITIVE_DETERMINATIONS

            if a_positive != b_positive:
                seen_pairs.add(pair)
                severity = ConflictSeverity.SOFT
                description = _generate_conflict_description(
                    source_a=a.mua_number,
                    source_b=b.mua_number,
                    conflict_type="same_family_contradiction",
                    detail_a=(
                        f"material={a.material_designation}, "
                        f"determination={a.determination.value}"
                    ),
                    detail_b=(
                        f"material={b.material_designation}, "
                        f"determination={b.determination.value}"
                    ),
                    context=(
                        "Materials in the same family may have different "
                        "behavior under specific conditions. The reviewing "
                        "engineer may wish to verify that these differences "
                        "are expected for the specific alloys or formulations "
                        "involved."
                    ),
                )
                results.append(ConflictFound(
                    conflict_id=_new_conflict_id(),
                    severity=severity,
                    source_a=a.mua_number,
                    source_b=b.mua_number,
                    description=description,
                    recommendation=_generate_recommendation(
                        severity, "same_family_contradiction"
                    ),
                ))

    return results


# ---------------------------------------------------------------------------
# Cross-source (MAPTIS vs precedent) conflict detection
# ---------------------------------------------------------------------------

def _rating_contradicts_determination(
    rating: str,
    determination: DeterminationStatus,
) -> Optional[ConflictSeverity]:
    """Assess whether a MAPTIS rating contradicts a precedent determination.

    Parameters
    ----------
    rating:
        MAPTIS rating string (A/B/C/D/E/U).
    determination:
        MUA precedent determination.

    Returns
    -------
    ConflictSeverity or None
        HARD if clear contradiction, SOFT if ambiguous, None if consistent.
    """
    rating_upper = (rating or "").upper()

    if determination in _POSITIVE_DETERMINATIONS:
        # Positive determination but failing test rating -> HARD
        if rating_upper in _FAILING_RATINGS:
            return ConflictSeverity.HARD
        # Ambiguous rating with positive determination -> SOFT
        if rating_upper in _AMBIGUOUS_RATINGS:
            return ConflictSeverity.SOFT
        return None

    if determination in _NEGATIVE_DETERMINATIONS:
        # Negative determination but passing test rating -> SOFT
        # (less severe: conservative determination is acceptable)
        if rating_upper in _PASSING_RATINGS:
            return ConflictSeverity.SOFT
        return None

    # DEFERRED / CANCELLED / UNKNOWN: no conflict to assess
    return None


def _test_class_relevant_to_precedent(
    test_class: str,
    precedent: PrecedentMatch,
) -> bool:
    """Heuristic: check if a test class is relevant to the precedent's context.

    Avoids false positives from comparing e.g. a toxicity rating against
    a flammability determination.
    """
    cls_upper = (test_class or "").upper()
    env = (precedent.environment_description or "").lower()

    # Flammability tests are broadly relevant to oxygen/flamm determinations
    if cls_upper == "FLAMM":
        if any(kw in env for kw in ["oxygen", "gox", "lox", "o2", "flamm"]):
            return True
        # Flammability is relevant to most determinations
        return True

    # SCC/CORR relevant to hydrogen/cryogenic environments
    if cls_upper in ("SCC", "CORR"):
        if any(kw in env for kw in ["hydrogen", "h2", "cryog", "corros"]):
            return True

    # TOX relevant to habitable environments
    if cls_upper == "TOX":
        if any(kw in env for kw in ["habitable", "crew", "cabin"]):
            return True

    # Default: assume possible relevance (conservative)
    return True


def _check_cross_source_conflicts(
    precedents: List[PrecedentMatch],
    test_data: List[TestDataRecord],
) -> List[ConflictFound]:
    """Detect conflicts between MAPTIS test data and MUA precedents.

    Checks for situations where test data ratings contradict precedent
    determinations -- for example, a MAPTIS D-rating for flammability
    paired with an APPROVED precedent.

    Parameters
    ----------
    precedents:
        All precedents (supporting and conflicting).
    test_data:
        MAPTIS test records for the material.

    Returns
    -------
    list[ConflictFound]
        Detected cross-source conflicts.
    """
    results: list[ConflictFound] = []

    for rec in test_data:
        if not rec.rating:
            continue

        for prec in precedents:
            # Skip if the test class is not relevant to this precedent
            if not _test_class_relevant_to_precedent(
                rec.test_class, prec
            ):
                continue

            severity = _rating_contradicts_determination(
                rec.rating, prec.determination
            )
            if severity is None:
                continue

            test_class_name = _TEST_CLASS_NAMES.get(
                (rec.test_class or "").upper(),
                rec.test_class or "unknown",
            )
            test_source = (
                f"MAPTIS {rec.report_number or rec.test_class}"
                if rec.report_number
                else f"MAPTIS test ({rec.test_class})"
            )

            description = _generate_conflict_description(
                source_a=test_source,
                source_b=prec.mua_number,
                conflict_type="rating_vs_determination",
                detail_a=(
                    f"{rec.rating}-rating for {test_class_name}"
                ),
                detail_b=(
                    f"determination={prec.determination.value}"
                ),
                context=(
                    f"The {test_class_name} test rating may not be "
                    f"consistent with the precedent determination. "
                    f"This may indicate different test conditions, "
                    f"material configurations, or testing standards."
                ),
            )

            results.append(ConflictFound(
                conflict_id=_new_conflict_id(),
                severity=severity,
                source_a=test_source,
                source_b=prec.mua_number,
                description=description,
                recommendation=_generate_recommendation(
                    severity, "rating_vs_determination"
                ),
            ))

    return results


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def detect_conflicts(
    supporting: List[PrecedentMatch],
    conflicting: List[PrecedentMatch],
    test_data: List[TestDataRecord],
) -> List[ConflictFound]:
    """Detect all cross-source conflicts in the evidence base.

    This is the primary entry point for conflict detection in the MUA v7
    pipeline.  It consolidates three categories of checks:

        1. Supporting vs conflicting precedent contradictions
        2. Within-supporting precedent contradictions
        3. MAPTIS test data vs precedent contradictions

    All output uses hedged language ("may") -- this module surfaces
    potential conflicts for engineering review.  It does not make safety
    determinations.

    Parameters
    ----------
    supporting:
        Precedents that support the proposed determination.
    conflicting:
        Precedents that conflict with the proposed determination.
    test_data:
        MAPTIS / lab test records for the material.

    Returns
    -------
    list[ConflictFound]
        All detected conflicts, sorted by severity (HARD first).

    Examples
    --------
    >>> from mira.mua.v7.models import PrecedentMatch, DeterminationStatus
    >>> sup = [PrecedentMatch(
    ...     mua_number="MUA-001",
    ...     material_designation="316L SS",
    ...     determination=DeterminationStatus.APPROVED,
    ...     environment_description="GOX at 3000 psi",
    ... )]
    >>> con = [PrecedentMatch(
    ...     mua_number="MUA-002",
    ...     material_designation="316L SS",
    ...     determination=DeterminationStatus.REJECTED,
    ...     environment_description="GOX at 4500 psi",
    ... )]
    >>> conflicts = detect_conflicts(sup, con, [])
    >>> len(conflicts) >= 1
    True
    >>> conflicts[0].severity
    <ConflictSeverity.HARD: 'hard'>
    """
    all_conflicts: list[ConflictFound] = []

    # 1. Precedent-vs-precedent (including within-supporting)
    precedent_conflicts = _check_precedent_conflicts(supporting, conflicting)
    all_conflicts.extend(precedent_conflicts)

    # 2. Cross-source: MAPTIS test data vs all precedents
    all_precedents = list(supporting) + list(conflicting)
    cross_source_conflicts = _check_cross_source_conflicts(
        all_precedents, test_data
    )
    all_conflicts.extend(cross_source_conflicts)

    # Sort by severity: HARD first, then SOFT, then NONE
    severity_order = {
        ConflictSeverity.HARD: 0,
        ConflictSeverity.SOFT: 1,
        ConflictSeverity.NONE: 2,
    }
    all_conflicts.sort(
        key=lambda c: severity_order.get(c.severity, 99)
    )

    return all_conflicts
