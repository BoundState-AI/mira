#!/usr/bin/env python3
"""
Module: Engine
Purpose: Hydrogen Compatibility Engine for MIRA — Evidence-first H2 Knowledge Twin v3.

The legacy FAISS-based HydrogenCompatibilityEngine class has been moved to
legacy_engine.py.  This module contains the modern evaluate_h2_compatibility()
pipeline that delegates to the H2 Knowledge Twin v3 (engine_simple.py).

BoundState AI 2025
Version: 2.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Fran OpenAI 5 <noreply@openai.com>
Co-Authored-By: Grok 4.0 <noreply@x.ai>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: SWE-032 (Data validation), SWE-033 (Requirements Traceability)
Safety Critical: True
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from core.models.answer import AnswerSeverity, EvidenceItem
from mira.maptis import (
    H2_HIGH_STRENGTH_THRESHOLD_KSI,
    MaterialFamily,
    get_h2_family_rule,
)
from mira.maptis.repository import _infer_family_from_key
from .models import (
    H2CompatibilityRequest,
    H2CompatibilityResponse,
    H2ConditionLookupResponse,
    HydrogenPhase,
    ConditionOptionResponse,
)

# Re-export legacy class for backward compatibility
# Used by: mira/bsmh/bok_adapter.py, mira/core/search_engine.py
from .legacy_engine import HydrogenCompatibilityEngine  # noqa: F401

LOGGER = logging.getLogger(__name__)

# H2 Knowledge Twin v3.0 - Simplified Engine
_H2_SIMPLE_ENGINE = None
_TITANIUM_HYDRIDE_LIMIT_K = 422.039


def _get_h2_simple_engine():
    """Lazy-load the simplified H2Engine."""
    global _H2_SIMPLE_ENGINE

    if _H2_SIMPLE_ENGINE is not None:
        return _H2_SIMPLE_ENGINE

    try:
        from mira.knowledge_twins.h2.engine_simple import H2Engine

        _H2_SIMPLE_ENGINE = H2Engine()
        # Trigger load to verify it works
        stats = _H2_SIMPLE_ENGINE.get_evidence_stats()
        LOGGER.info(f"Loaded simplified H2 engine: {stats['total_records']} evidence records")
        return _H2_SIMPLE_ENGINE

    except Exception as e:
        LOGGER.error(f"Failed to load simplified H2Engine: {e}")
        return None


def _infer_request_family(material_key: str) -> MaterialFamily:
    """Use the shared MAPTIS fallback family heuristic in no-DB runtime."""
    return _infer_family_from_key(material_key or "")


def _classification_from_family_rule(rule: dict) -> AnswerSeverity:
    """Map a family-rule classification string to AnswerSeverity."""
    classification = (rule.get("classification") or "unknown").lower()
    return {
        "approved": AnswerSeverity.OK,
        "approved_with_caution": AnswerSeverity.CAUTION,
        "caution": AnswerSeverity.CAUTION,
        "prohibited": AnswerSeverity.PROHIBITED,
    }.get(classification, AnswerSeverity.UNKNOWN)


def _family_rule_evidence(rule: dict) -> EvidenceItem:
    """Render a compact evidence item for a deterministic family rule."""
    return EvidenceItem(
        source_id=rule.get("bok_ref", "NSS 1740.16"),
        location="Family-level hydrogen compatibility rule",
        summary=rule.get("reason", "Family-level hydrogen compatibility guidance."),
    )


def _render_family_rule_response(
    request: H2CompatibilityRequest,
    *,
    rule: dict,
    rationale: str,
    notes: str,
    evidence: list[EvidenceItem] | None = None,
    band_distribution: Optional[dict] = None,
    envelope_context: Optional[dict] = None,
) -> H2CompatibilityResponse:
    """Build a response from a deterministic family rule fallback."""
    return H2CompatibilityResponse(
        classification=_classification_from_family_rule(rule),
        rationale=rationale,
        evidence=evidence or [_family_rule_evidence(rule)],
        embrittlement_risk=rule.get("embrittlement_risk"),
        h2_score=0.55,
        notes=notes,
        band_distribution=band_distribution,
        envelope_context=envelope_context,
    )


def _deterministic_guardrail_response(
    request: H2CompatibilityRequest,
) -> H2CompatibilityResponse | None:
    """Apply safety guardrails that must not depend on evidence lookup success."""
    family = _infer_request_family(request.material_key)

    if (
        request.yield_strength_ksi is not None
        and request.yield_strength_ksi > H2_HIGH_STRENGTH_THRESHOLD_KSI
    ):
        return H2CompatibilityResponse(
            classification=AnswerSeverity.PROHIBITED,
            rationale=(
                f"Yield strength {request.yield_strength_ksi:.1f} ksi exceeds the "
                f"{H2_HIGH_STRENGTH_THRESHOLD_KSI:.0f} ksi hydrogen embrittlement threshold."
            ),
            evidence=[
                EvidenceItem(
                    source_id="NSS 1740.16 §4.3.2",
                    location="Hydrogen high-strength steel limit",
                    summary="Materials above 150 ksi are treated as hydrogen-embrittlement susceptible.",
                )
            ],
            embrittlement_risk="severe",
            h2_score=0.0,
            notes="Deterministic safety guardrail applied before evidence-twin assessment.",
        )

    if (
        family == MaterialFamily.TITANIUM
        and request.phase == HydrogenPhase.GAS
        and request.temperature_k > _TITANIUM_HYDRIDE_LIMIT_K
    ):
        return H2CompatibilityResponse(
            classification=AnswerSeverity.PROHIBITED,
            rationale=(
                "Titanium in gaseous hydrogen above 300°F can absorb hydrogen and form brittle hydrides."
            ),
            evidence=[
                EvidenceItem(
                    source_id="NSS 1740.16 §4.5",
                    location="Titanium hydride formation limit",
                    summary="Titanium is not allowed for elevated-temperature GH2 service above 300°F.",
                )
            ],
            embrittlement_risk="severe",
            h2_score=0.0,
            notes="Deterministic safety guardrail applied before evidence-twin assessment.",
        )

    return None


def evaluate_h2_compatibility(request: H2CompatibilityRequest) -> H2CompatibilityResponse:
    """Evaluate hydrogen compatibility using H2 Knowledge Twin v3.0 (Simplified).

    Evidence-first approach using NASA/TM-2016-218602 and Sandia data:
    1. Loads 361 evidence records (HEE test data)
    2. Matches material name with tiered matching (exact → alias → fuzzy)
    3. Returns worst-case verdict for conservative safety assessment

    Args:
        request: H2CompatibilityRequest with material_key, pressure, temp, phase

    Returns:
        H2CompatibilityResponse with classification, rationale, evidence
    """
    guardrail_response = _deterministic_guardrail_response(request)
    if guardrail_response is not None:
        return guardrail_response

    family = _infer_request_family(request.material_key)
    family_rule = get_h2_family_rule(family)
    engine = _get_h2_simple_engine()

    if engine is None:
        return H2CompatibilityResponse(
            classification=AnswerSeverity.UNKNOWN,
            rationale="H2 Knowledge Twin not available - evidence database not loaded",
            evidence=[],
            notes="Check mira/data/h2_evidence_merged.json exists",
        )

    try:
        from mira.knowledge_twins.h2.engine_simple import Verdict

        # Execute query using simplified engine
        result = engine.query(
            material=request.material_key,
            pressure_psi=request.pressure_psia,
            temperature_k=request.temperature_k,
            condition=request.condition,
        )

        # Convert evidence to EvidenceItem
        evidence_items = []
        for ev in result.top_evidence:
            evidence_items.append(EvidenceItem(
                source_id=ev.get("source", "unknown"),
                location=f"Table {ev.get('table', '')}" if ev.get("table") else None,
                summary=f"{ev.get('material', 'unknown')}: HEE band = {ev.get('hee_band', 'unknown')}",
            ))

        # Handle CLARIFICATION_NEEDED verdict specially
        if result.verdict == Verdict.CLARIFICATION_NEEDED:
            if (
                result.match_type == "family"
                and _classification_from_family_rule(family_rule) != AnswerSeverity.UNKNOWN
            ):
                return _render_family_rule_response(
                    request,
                    rule=family_rule,
                    rationale=(
                        f"{request.material_key}: No material-specific H2 evidence was found. "
                        f"Applying the {family.value.replace('_', ' ')} family rule. "
                        f"{family_rule.get('reason', '')}"
                    ),
                    notes=(
                        "Direct material-specific H2 evidence was not found; "
                        "family-level compatibility guidance was applied."
                    ),
                    evidence=evidence_items[:2] or None,
                    band_distribution=result.band_distribution if len(result.band_distribution) > 1 else None,
                    envelope_context=result.envelope_context,
                )

            if (
                family == MaterialFamily.TITANIUM
                and request.phase == HydrogenPhase.LIQUID
                and request.temperature_k <= _TITANIUM_HYDRIDE_LIMIT_K
            ):
                fallback_evidence = evidence_items[:2]
                fallback_evidence.append(_family_rule_evidence(family_rule))
                return _render_family_rule_response(
                    request,
                    rule=family_rule,
                    rationale=(
                        f"{request.material_key}: Cryogenic LH2 service is treated with caution. "
                        f"{family_rule.get('reason', '')}"
                    ),
                    notes=(
                        "Condition-specific ambient GH2 evidence is mixed; "
                        "cryogenic LH2 fallback follows the titanium family rule."
                    ),
                    evidence=fallback_evidence,
                    band_distribution=result.band_distribution if len(result.band_distribution) > 1 else None,
                    envelope_context=result.envelope_context,
                )

            # Convert ConditionOption dataclasses to ConditionOptionResponse Pydantic models
            available_conditions = [
                ConditionOptionResponse(
                    condition_name=opt.condition_name,
                    hee_band=opt.hee_band,
                    verdict_if_selected=opt.verdict_if_selected,
                    evidence_count=opt.evidence_count,
                    source=opt.source,
                )
                for opt in result.available_conditions
            ]

            return H2CompatibilityResponse(
                classification=AnswerSeverity.UNKNOWN,  # No definitive classification yet
                rationale=result.rationale,
                evidence=evidence_items,
                embrittlement_risk=None,
                h2_score=None,
                notes="Specify heat treatment condition for accurate assessment.",
                needs_clarification=True,
                clarification_prompt=result.clarification_prompt,
                available_conditions=available_conditions,
                band_distribution=result.band_distribution,
                envelope_context=result.envelope_context,
            )

        # Map Verdict to AnswerSeverity for non-clarification cases
        verdict_map = {
            Verdict.ACCEPTABLE: AnswerSeverity.OK,
            Verdict.CAUTION: AnswerSeverity.CAUTION,
            Verdict.PROHIBITED: AnswerSeverity.PROHIBITED,
            Verdict.UNKNOWN: AnswerSeverity.UNKNOWN,
        }
        classification = verdict_map.get(result.verdict, AnswerSeverity.UNKNOWN)

        # Map HEE band to embrittlement risk
        embrittlement_risk = None
        if result.hee_band:
            risk_map = {
                "negligible": "low",
                "small": "low",
                "high": "medium",
                "severe": "high",
                "extreme": "severe",
            }
            embrittlement_risk = risk_map.get(result.hee_band, "unknown")

        if (
            classification == AnswerSeverity.OK
            and family_rule.get("classification") == "approved"
            and family_rule.get("embrittlement_risk") in {"none", "very_low", "low"}
        ):
            embrittlement_risk = family_rule["embrittlement_risk"]

        # Combine warnings into notes
        notes = None
        if result.warnings:
            notes = "; ".join(result.warnings[:2])

        return H2CompatibilityResponse(
            classification=classification,
            rationale=result.rationale,
            evidence=evidence_items,
            embrittlement_risk=embrittlement_risk,
            h2_score=0.85 if result.match_type in ["exact", "alias"] else 0.7,  # Simple confidence
            notes=notes,
            band_distribution=result.band_distribution if len(result.band_distribution) > 1 else None,
            envelope_context=result.envelope_context,
        )

    except Exception as e:
        LOGGER.error(f"H2 evaluation failed: {e}")
        return H2CompatibilityResponse(
            classification=AnswerSeverity.UNKNOWN,
            rationale=f"H2 evaluation error: {str(e)}",
            evidence=[],
            notes="Check server logs for details",
        )


def lookup_h2_conditions(material_key: str) -> H2ConditionLookupResponse:
    """Lookup known heat-treatment conditions for a material from H2 evidence."""
    material = (material_key or "").strip()
    if not material:
        return H2ConditionLookupResponse(
            material_key=material_key,
            has_matches=False,
            notes="material_key is required",
        )

    engine = _get_h2_simple_engine()
    if engine is None:
        return H2ConditionLookupResponse(
            material_key=material,
            has_matches=False,
            notes="H2 Knowledge Twin not available",
        )

    try:
        payload = engine.get_condition_options(material)
        options = [
            ConditionOptionResponse(
                condition_name=str(item.get("condition_name", "")),
                hee_band=str(item.get("hee_band", "unknown")),
                verdict_if_selected=str(item.get("verdict_if_selected", "unknown")),
                evidence_count=int(item.get("evidence_count", 0)),
                source=str(item.get("source", "unknown")),
            )
            for item in payload.get("available_conditions", [])
            if isinstance(item, dict) and item.get("condition_name")
        ]
        return H2ConditionLookupResponse(
            material_key=material,
            canonical_material=payload.get("canonical_material"),
            has_matches=bool(payload.get("has_matches")),
            requires_clarification=bool(payload.get("requires_clarification")),
            match_type=str(payload.get("match_type", "none")),
            available_conditions=options,
            band_distribution=payload.get("band_distribution") or {},
            unresolved_condition_count=int(payload.get("unresolved_condition_count") or 0),
            notes=(
                f"{int(payload.get('unresolved_condition_count') or 0)} condition label(s) need review."
                if int(payload.get("unresolved_condition_count") or 0) > 0
                else (None if options else "No condition-specific evidence variants found for this material.")
            ),
        )
    except Exception as exc:
        LOGGER.error("H2 condition lookup failed for %s: %s", material, exc)
        return H2ConditionLookupResponse(
            material_key=material,
            has_matches=False,
            notes=f"H2 condition lookup error: {exc}",
        )


# Singleton instance for legacy engine
_H2_ENGINE: Optional[HydrogenCompatibilityEngine] = None
_H2_ENGINE_ERROR: Optional[Exception] = None


def get_h2_engine() -> Optional[HydrogenCompatibilityEngine]:
    """Get or create the singleton H2 engine."""
    global _H2_ENGINE, _H2_ENGINE_ERROR

    if _H2_ENGINE is not None:
        return _H2_ENGINE
    if _H2_ENGINE_ERROR is not None:
        return None

    try:
        # Default path to MAPTIS metadata - relative to this module
        base_dir = Path(__file__).parent.parent  # boundstate/mira
        metadata_path = base_dir / "databases" / "maptis_faiss_db" / "metadata.json"
        if not metadata_path.exists():
            # Try alternate paths
            alt_paths = [
                Path("mira/databases/maptis_faiss_db/metadata.json"),
                Path("databases/maptis_faiss_db/metadata.json"),
            ]
            for alt in alt_paths:
                if alt.exists():
                    metadata_path = alt
                    break

        _H2_ENGINE = HydrogenCompatibilityEngine(metadata_path)
        LOGGER.info("Loaded H2 compatibility engine")
        return _H2_ENGINE

    except Exception as exc:
        _H2_ENGINE_ERROR = exc
        LOGGER.warning(f"Failed to load H2 engine: {exc}")
        return None


__all__ = [
    "HydrogenCompatibilityEngine",
    "get_h2_engine",
    "evaluate_h2_compatibility",
    "lookup_h2_conditions",
]
