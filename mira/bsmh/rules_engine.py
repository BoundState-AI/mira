#!/usr/bin/env python3
"""
Deterministic MIRA rules stage for temporary BSMH path.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from .models import MaterialRuleResult, RuleDecisionPacket, RuleEvidenceItem

_O2_PROHIBITED_TOKENS = (
    "TI-6AL-4V",
    "TITANIUM",
    "MAGNESIUM",
)

_VERDICT_PRIORITY = {
    "COMPATIBLE": 3,
    "CONDITIONAL": 2,
    "INSUFFICIENT_DATA": 1,
    "INCOMPATIBLE": 0,
}


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return default


def _normalize_token(value: str) -> str:
    return "".join(ch for ch in value.upper() if ch.isalnum())


def _material_name_matches_requested(material_name: str, requested: str) -> bool:
    req = requested.strip().upper()
    name = material_name.strip().upper()
    if not req or not name:
        return False

    if req in name:
        return True

    req_norm = _normalize_token(req)
    name_norm = _normalize_token(name)
    if req_norm and req_norm in name_norm:
        return True

    req_tokens = [tok for tok in req.replace("/", " ").replace("-", " ").split() if tok]
    if len(req_tokens) > 1 and all(tok in name for tok in req_tokens):
        return True

    return False


def _material_bok_supported(material_name: str, bok_rows: List[Dict[str, Any]]) -> bool:
    name = material_name.strip()
    if not name or not bok_rows:
        return False
    name_upper = name.upper()
    name_norm = _normalize_token(name_upper)
    for row in bok_rows:
        merged = " ".join(
            [
                str(row.get("title") or ""),
                str(row.get("section") or ""),
                str(row.get("excerpt") or ""),
                str(row.get("source") or ""),
                str(row.get("doc_id") or ""),
            ]
        ).upper()
        if not merged.strip():
            continue
        merged_norm = _normalize_token(merged)
        if name_upper in merged or (name_norm and name_norm in merged_norm):
            return True
    return False


def _compute_confidence(
    *,
    material_results: List[MaterialRuleResult],
    requested_materials: Optional[List[str]],
    safety_context: str,
    bok_rows: List[Dict[str, Any]],
) -> tuple[float, str]:
    if not material_results:
        return 0.1, "no_materials"

    requested = [r for r in (requested_materials or []) if str(r).strip()]
    if not requested:
        return sum(m.score for m in material_results) / len(material_results), "flat_average"

    requested_scores: List[float] = []
    for req in requested:
        matches = [m for m in material_results if _material_name_matches_requested(m.material_name, req)]
        if matches:
            score = max(m.score for m in matches)
        else:
            score = 0.1
        requested_scores.append(score)

    # Hydrogen context: BoK support provides bounded confidence lift per requested material.
    if safety_context == "hydrogen" and bok_rows:
        for idx, req in enumerate(requested):
            if requested_scores[idx] <= 0.1:
                continue
            if any(_material_name_matches_requested(m.material_name, req) and _material_bok_supported(m.material_name, bok_rows) for m in material_results):
                requested_scores[idx] = min(1.0, requested_scores[idx] + 0.10)
            else:
                requested_scores[idx] = min(1.0, requested_scores[idx] + 0.03)

    confidence = sum(requested_scores) / len(requested_scores)
    return confidence, "requested_best_of_family"


def _detect_linkage_gap(*, total_tests: int, mua_count: int) -> bool:
    """
    Detect when MUA heritage is substantial but MAPTIS test linkage is sparse.
    This indicates a database coverage gap, not an untested material.
    """
    return mua_count >= 20 and total_tests < 3


def _evidence_strength_band(score: float) -> str:
    """Map a numeric score to a qualitative evidence strength label."""
    if score >= 0.75:
        return "strong"
    if score >= 0.45:
        return "moderate"
    if score >= 0.15:
        return "limited"
    return "insufficient"


def _material_score(
    *,
    total_tests: int,
    oxygen_compatible: bool,
    mua_count: int,
    latest_test_year: Optional[int],
) -> float:
    linkage_gap = _detect_linkage_gap(total_tests=total_tests, mua_count=mua_count)

    if linkage_gap:
        # When heritage is strong but test linkage is sparse, rebalance weights.
        # Don't penalize the material for a database gap.
        test_component = min(total_tests / 10.0, 1.0) * 0.25
        oxygen_component = (1.0 if oxygen_compatible else 0.2) * 0.20
        mua_component = min(mua_count / 20.0, 1.0) * 0.40
    else:
        test_component = min(total_tests / 25.0, 1.0) * 0.45
        oxygen_component = (1.0 if oxygen_compatible else 0.2) * 0.25
        mua_component = min(mua_count / 5.0, 1.0) * 0.20

    freshness_component = 0.0
    if latest_test_year:
        age = datetime.now(timezone.utc).year - latest_test_year
        if age <= 10:
            freshness_component = 0.10
        elif age <= 20:
            freshness_component = 0.06
        else:
            freshness_component = 0.03

    # Linkage gap materials get a heritage floor -- substantial MUA means
    # the material is in active use regardless of MAPTIS test record count.
    raw = test_component + oxygen_component + mua_component + freshness_component
    if linkage_gap:
        raw = max(raw, 0.45)

    return max(0.0, min(raw, 1.0))


def _classify_material(
    material: Dict[str, Any],
    safety_context: str,
    min_evidence_rows: int,
) -> MaterialRuleResult:
    designation = str(material.get("designation") or "Unknown")
    designation_upper = designation.upper()
    total_tests = _safe_int(material.get("total_tests"), 0)
    mua_count = _safe_int(material.get("mua_count"), 0)
    oxygen_compatible = bool(material.get("oxygen_compatible"))
    oxygen_rating = str(material.get("oxygen_rating") or "").strip().upper() or "NO_RATING"
    oxygen_rating_present = bool(material.get("oxygen_rating_present"))
    if oxygen_rating == "NO_RATING" and oxygen_rating_present:
        oxygen_rating = "RATING_PRESENT_NOT_AB"

    test_counts = material.get("test_counts") if isinstance(material.get("test_counts"), dict) else {}
    fluid_compat_count = _safe_int(test_counts.get("fluid_compatibility"), 0)
    hydrogen_signal_present = fluid_compat_count > 0

    latest_test_year = material.get("latest_test_year")
    if latest_test_year is not None:
        latest_test_year = _safe_int(latest_test_year, 0) or None

    linkage_gap = _detect_linkage_gap(total_tests=total_tests, mua_count=mua_count)

    warnings: List[str] = []
    limitations: List[str] = []
    evidence_chain: List[RuleEvidenceItem] = []

    evidence_chain.append(
        RuleEvidenceItem(
            property="total_tests",
            value=str(total_tests),
            requirement=f">= {min_evidence_rows} test records",
            passed=total_tests >= min_evidence_rows,
            source=f"material_key:{material.get('material_key')}",
        )
    )
    evidence_chain.append(
        RuleEvidenceItem(
            property="mua_precedent_count",
            value=str(mua_count),
            requirement=">= 1 precedent preferred",
            passed=mua_count >= 1,
            source="mua_precedents_v7",
        )
    )

    if safety_context == "oxygen":
        evidence_chain.append(
            RuleEvidenceItem(
                property="oxygen_rating",
                value=oxygen_rating,
                requirement="A_OR_B rating required for oxygen compatibility claim",
                passed=oxygen_rating == "A_OR_B",
                source="flammability/promoted_combustion tests",
            )
        )
    if safety_context == "hydrogen":
        evidence_chain.append(
            RuleEvidenceItem(
                property="hydrogen_test_data_present",
                value=str(hydrogen_signal_present),
                requirement="Hydrogen-specific compatibility test data required for strong hydrogen claim",
                passed=hydrogen_signal_present,
                source="fluid_compatibility_tests",
            )
        )

    if total_tests <= 0:
        verdict = "INSUFFICIENT_DATA"
        if linkage_gap:
            warnings.append(
                f"No MAPTIS-linked test records found; however, {mua_count} MUA precedents "
                "indicate established use. This appears to be a database linkage gap."
            )
        else:
            warnings.append("No MAPTIS test records found for this material.")
        limitations.append("Deterministic decision confidence reduced due to zero direct tests.")
    elif safety_context == "oxygen":
        if any(tok in designation_upper for tok in _O2_PROHIBITED_TOKENS):
            verdict = "INCOMPATIBLE"
            warnings.append("Material family is prohibited for oxygen service due to ignition risk.")
            limitations.append("Conservative oxygen policy blocks titanium/magnesium-family materials.")
        elif oxygen_rating == "A_OR_B" and oxygen_compatible:
            verdict = "COMPATIBLE"
        else:
            verdict = "INCOMPATIBLE"
            if oxygen_rating == "RATING_PRESENT_NOT_AB":
                warnings.append("Oxygen rating exists but is not A/B compatible.")
                limitations.append("Conservative oxygen policy requires A/B oxygen compatibility rating.")
            else:
                warnings.append("No explicit oxygen compatibility rating found in MAPTIS.")
                limitations.append("Conservative oxygen policy treats unrated materials as incompatible.")
    elif total_tests < min_evidence_rows:
        verdict = "CONDITIONAL"
        if linkage_gap:
            warnings.append(
                f"MAPTIS-linked test records ({total_tests}) below minimum threshold ({min_evidence_rows}); "
                f"{mua_count} MUA precedents suggest database linkage gap rather than insufficient testing."
            )
        else:
            warnings.append(
                f"Limited test data available ({total_tests} record{'s' if total_tests != 1 else ''}; "
                f"minimum {min_evidence_rows} recommended)."
            )
        limitations.append("Limited direct test evidence in MAPTIS.")
    else:
        verdict = "COMPATIBLE"

    if safety_context == "hydrogen" and not hydrogen_signal_present:
        if verdict == "COMPATIBLE":
            verdict = "CONDITIONAL"
        warnings.append("No hydrogen-specific test data on file for this material.")
        limitations.append("Hydrogen assessment is conservative without direct hydrogen test data.")

    if safety_context in {"hydrogen", "cryogenic", "high_pressure"} and total_tests < (min_evidence_rows * 2):
        if verdict == "COMPATIBLE":
            verdict = "CONDITIONAL"
        if not linkage_gap:
            warnings.append(f"Limited dedicated test evidence for {safety_context} service conditions.")

    score = _material_score(
        total_tests=total_tests,
        oxygen_compatible=oxygen_compatible,
        mua_count=mua_count,
        latest_test_year=latest_test_year,
    )
    if verdict == "INSUFFICIENT_DATA":
        score = min(score, 0.25)
    if verdict == "INCOMPATIBLE":
        score = min(score, 0.20)

    evidence_strength = _evidence_strength_band(score)

    return MaterialRuleResult(
        material_name=designation,
        material_key=material.get("material_key"),
        oxygen_rating=oxygen_rating,
        hydrogen_signal_present=hydrogen_signal_present,
        verdict=verdict,  # type: ignore[arg-type]
        score=round(score, 3),
        evidence_strength=evidence_strength,
        linkage_gap=linkage_gap,
        warnings=warnings,
        limitations=limitations,
        evidence_chain=evidence_chain,
    )


def _overall_verdict(material_results: List[MaterialRuleResult]) -> str:
    if not material_results:
        return "INSUFFICIENT_DATA"
    verdicts = [m.verdict for m in material_results]
    if "INCOMPATIBLE" in verdicts:
        if "COMPATIBLE" in verdicts or "CONDITIONAL" in verdicts:
            return "CONDITIONAL"
        return "INCOMPATIBLE"
    if all(v == "INSUFFICIENT_DATA" for v in verdicts):
        return "INSUFFICIENT_DATA"
    if any(v in {"CONDITIONAL", "INSUFFICIENT_DATA"} for v in verdicts):
        return "CONDITIONAL"
    return "COMPATIBLE"


def _standards_category_for_context(safety_context: str) -> Optional[str]:
    if safety_context == "oxygen":
        return "I"
    if safety_context in {"hydrogen", "cryogenic", "high_pressure"}:
        return "II"
    if safety_context == "general":
        return "III"
    return None


def build_rule_decision(
    materials: List[Dict[str, Any]],
    *,
    safety_context: str = "general",
    min_evidence_rows: int = 2,
    aggregation_scope: str = "primary_only",
    primary_material_count: Optional[int] = None,
    associated_material_count: int = 0,
    bok_evidence: Optional[List[Dict[str, Any]]] = None,
    require_h2_bok: bool = False,
    requested_materials: Optional[List[str]] = None,
    missing_requested_materials: Optional[List[str]] = None,
) -> RuleDecisionPacket:
    """
    Deterministically evaluate v4 material evidence for BSMH.
    """

    normalized_scope = aggregation_scope if aggregation_scope in {"primary_only", "all_materials"} else "primary_only"

    material_results = [
        _classify_material(m, safety_context, min_evidence_rows)
        for m in materials[:10]
    ]

    if material_results:
        ranked = sorted(
            material_results,
            key=lambda m: (_VERDICT_PRIORITY.get(m.verdict, -1), m.score),
            reverse=True,
        )
        material_results = ranked

    overall = _overall_verdict(material_results)

    bok_rows = list(bok_evidence or [])
    bok_sources = sorted(
        {
            str(row.get("source")).strip()
            for row in bok_rows
            if str(row.get("source") or "").strip()
        }
    )

    confidence, confidence_mode = _compute_confidence(
        material_results=material_results,
        requested_materials=requested_materials,
        safety_context=safety_context,
        bok_rows=bok_rows,
    )

    # Deterministic output guard: low confidence cannot be presented as COMPATIBLE.
    if overall == "COMPATIBLE" and confidence < 0.5:
        overall = "CONDITIONAL"
    # Soft cap: CONDITIONAL verdict should not report overconfidence.
    # An engineer reading "CONDITIONAL at 92%" will distrust both numbers.
    if overall == "CONDITIONAL" and confidence > 0.80:
        confidence = 0.80
    if safety_context == "oxygen" and overall == "COMPATIBLE":
        if not any(m.oxygen_rating == "A_OR_B" for m in material_results):
            overall = "INCOMPATIBLE"

    evidence_gaps: List[str] = []
    if not material_results:
        evidence_gaps.append("No candidate materials found from Sonnet+MAPTIS retrieval.")
    if normalized_scope == "primary_only" and associated_material_count > 0:
        evidence_gaps.append(
            "Associated assembly records were found; deterministic verdict is based on primary requested materials only."
        )
    if safety_context == "oxygen" and not any(m.verdict == "COMPATIBLE" for m in material_results):
        evidence_gaps.append("No material with explicit oxygen-compatible signal found.")
    missing = list(missing_requested_materials or [])
    if missing:
        evidence_gaps.append(
            f"Requested material(s) not found in retrieved evidence: {', '.join(missing)}."
        )
    if safety_context == "hydrogen" and require_h2_bok and not bok_rows:
        evidence_gaps.append("No H2 BoK evidence retrieved for hydrogen-context decision.")

    rules_applied = [
        f"context_profile:{safety_context}",
        f"min_evidence_rows:{min_evidence_rows}",
        "property_driven_scoring",
        "conservative_verdict_aggregation",
        f"aggregation_scope:{normalized_scope}",
        f"confidence_aggregation:{confidence_mode}",
    ]
    if overall == "CONDITIONAL" and confidence < 0.5:
        rules_applied.append("guard:no_compatible_below_confidence_threshold")
    if requested_materials:
        rules_applied.append("requested_material_filter")
    if safety_context == "hydrogen":
        rules_applied.append("h2_bok_context_check")

    # Safety guard: if H2 BoK is required and absent, do not emit COMPATIBLE.
    if safety_context == "hydrogen" and require_h2_bok and not bok_rows and overall == "COMPATIBLE":
        overall = "CONDITIONAL"
        rules_applied.append("guard:require_h2_bok_for_compatible")

    return RuleDecisionPacket(
        verdict=overall,  # type: ignore[arg-type]
        confidence=round(max(0.0, min(confidence, 1.0)), 3),
        materials=material_results,
        aggregation_scope=normalized_scope,  # type: ignore[arg-type]
        primary_material_count=int(primary_material_count if primary_material_count is not None else len(materials)),
        associated_material_count=max(0, int(associated_material_count)),
        bok_context_used=bool(bok_rows),
        bok_evidence_count=len(bok_rows),
        bok_sources=bok_sources,
        requested_materials=list(requested_materials or []),
        missing_requested_materials=missing,
        determination_material_keys=[m.material_key for m in material_results],
        determination_material_names=[m.material_name for m in material_results],
        rules_applied=rules_applied,
        standards_category=_standards_category_for_context(safety_context),
        evidence_gaps=evidence_gaps,
    )
