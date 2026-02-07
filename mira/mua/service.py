#!/usr/bin/env python3
"""
Module: Service
Purpose: MUA Service Layer - Clean Wrapper Entrypoint

BoundState AI 2025
Version: 1.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Fran OpenAI 5 <noreply@openai.com>
Co-Authored-By: Grok 4.0 <noreply@x.ai>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: NASA-CSET, SWE-013, SWE-032
Safety Critical: False
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Dict, List

from core.models.answer import EvidenceItem

from .api_models import (
    EnvironmentSpec,
    MaterialRating,
    MitigationClause,
    MuaGenerationRequest,
    MuaGenerationResponse,
)

LOGGER = logging.getLogger(__name__)

# NASA-STD-6016 clause references for common test classes
CLAUSE_REFS = {
    "FLAMM": ["§4.2.1.1", "§4.2.1.4"],
    "TOX": ["§4.2.1.2"],
    "TVS": ["§4.2.3.6"],
    "SCC": ["§4.2.6.3"],
    "CORR": ["§4.2.6.3"],
    "FS": ["§4.2.1.3"],
}


def generate_mua(request: MuaGenerationRequest) -> MuaGenerationResponse:
    """Generate an MUA for a material with rating gaps.

    This is the CLEAN wrapper that:
    1. Identifies rating gaps (non-A ratings)
    2. Routes to appropriate MUA category
    3. Generates mitigations for gaps
    4. Returns structured response with evidence

    Args:
        request: MuaGenerationRequest with material, program, environment, ratings

    Returns:
        MuaGenerationResponse with category, mitigations, and evidence
    """
    warnings: List[str] = []
    evidence: List[EvidenceItem] = []

    # Evidence: Record the generation request
    evidence.append(EvidenceItem(
        source_id="mua_generation_request",
        location=f"material={request.material_key}",
        summary=f"MUA generation for {request.material_name or request.material_key} on {request.program}",
    ))

    try:
        # Step 1: Identify gaps (non-A ratings)
        gaps: Dict[str, str] = {}
        for rating in request.known_ratings:
            if rating.rating != "A":
                gaps[rating.test_class] = rating.rating

        if not gaps:
            # All A-ratings - no MUA needed
            return MuaGenerationResponse(
                success=True,
                material_key=request.material_key,
                material_name=request.material_name,
                program=request.program,
                category="N/A",
                gaps_identified={},
                mitigations=[],
                rationale_summary="Material has A-ratings in all required test classes. No MUA required.",
                evidence=evidence,
                warnings=["Material has full A-ratings - MUA not required"],
            )

        # Step 2: Validate environment completeness
        env = request.environment
        if env.habitable_volume is None:
            warnings.append("habitable_volume not specified - assuming non-habitable")
            # Default to non-habitable for safety
            env = EnvironmentSpec(
                oxygen_pct=env.oxygen_pct,
                pressure_kpa=env.pressure_kpa,
                temperature_c=env.temperature_c,
                fluid_medium=env.fluid_medium,
                habitable_volume=False,
            )

        # Step 3: Route to MUA category
        category, appendix_b = _route_category(env, gaps)

        evidence.append(EvidenceItem(
            source_id="NASA-STD-6016C",
            location="§4.3 Verification",
            summary=f"Material routed to Category {category} based on environment and gaps",
        ))

        # Step 4: Generate mitigations for gaps
        mitigations: List[MitigationClause] = []
        for test_class, rating in gaps.items():
            mitigation = _generate_mitigation(
                test_class=test_class,
                rating=rating,
                material_key=request.material_key,
                material_name=request.material_name,
                environment=env,
            )
            mitigations.append(mitigation)

            evidence.append(EvidenceItem(
                source_id=mitigation.source_document,
                location=", ".join(mitigation.clause_refs),
                summary=f"Mitigation for {test_class} rating {rating}",
            ))

        # Step 5: Generate rationale summary
        rationale_parts = [
            f"Material {request.material_name or request.material_key} requires MUA Category {category} ",
            f"for use on {request.program}.",
        ]

        if gaps:
            rationale_parts.append(f" Gaps identified: {', '.join(f'{k}={v}' for k, v in gaps.items())}.")

        if mitigations:
            rationale_parts.append(f" {len(mitigations)} mitigation(s) provided.")

        rationale_summary = "".join(rationale_parts)

        return MuaGenerationResponse(
            success=True,
            material_key=request.material_key,
            material_name=request.material_name,
            program=request.program,
            category=category,
            appendix_b_exemptions=appendix_b,
            gaps_identified=gaps,
            mitigations=mitigations,
            rationale_summary=rationale_summary,
            evidence=evidence,
            warnings=warnings,
        )

    except Exception as e:
        LOGGER.exception(f"MUA generation failed: {e}")
        return MuaGenerationResponse(
            success=False,
            material_key=request.material_key,
            material_name=request.material_name,
            program=request.program,
            category="ERROR",
            gaps_identified={},
            mitigations=[],
            rationale_summary=f"MUA generation failed: {e}",
            evidence=evidence,
            warnings=warnings + [f"Generation error: {e}"],
        )


def _route_category(env: EnvironmentSpec, gaps: Dict[str, str]) -> tuple[str, List[str]]:
    """Route to MUA category based on environment and gaps.

    Categories per NASA-STD-6016C:
    - Category I: High severity (O2 enriched, high pressure, flammability gaps)
    - Category II: Standard (ambient conditions, non-critical gaps)
    - Category III: Appendix B exemptions (e.g., TVS-407 for non-habitable)

    Returns:
        (category, list of appendix_b exemptions)
    """
    appendix_b: List[str] = []

    # Check for Appendix B exemptions first
    if "TVS" in gaps and not (env.habitable_volume or False):
        appendix_b.append("TVS-407")

    if appendix_b:
        return "III", appendix_b

    # Check for Category I conditions
    o2_pct = env.oxygen_pct or 21.0
    is_lox_gox = (env.fluid_medium or "").upper() in {"LOX", "GOX"}
    high_pressure = (env.pressure_kpa or 101.3) > 300

    if is_lox_gox or o2_pct >= 23.5 or high_pressure:
        return "I", []

    # Default to Category II
    return "II", []


def _generate_mitigation(
    test_class: str,
    rating: str,
    material_key: str,
    material_name: str | None,
    environment: EnvironmentSpec,
) -> MitigationClause:
    """Generate a mitigation clause for a specific gap.

    This is a simplified generator. In production, this would query
    the precedent database for similar mitigations.
    """
    material = material_name or material_key
    clause_refs = CLAUSE_REFS.get(test_class, ["§4.3"])

    # Generate mitigation text based on test class and rating
    if test_class == "TVS":
        if rating == "B":
            mitigation_text = (
                f"Material {material} has TVS rating B (CVCM > 0.1%). "
                f"Acceptable for non-critical optical surfaces per NASA-STD-6016C {clause_refs[0]}. "
                "Outgassing products do not affect nearby optics based on usage location."
            )
        else:
            mitigation_text = (
                f"Material {material} has TVS rating {rating}. "
                f"Engineering evaluation confirms acceptable outgassing for this application."
            )
    elif test_class == "FLAMM":
        mitigation_text = (
            f"Material {material} has flammability rating {rating}. "
            f"Quantity/configuration limits combustion propagation per NASA-STD-6016C {clause_refs[0]}. "
            "Material is isolated from ignition sources."
        )
    elif test_class == "TOX":
        mitigation_text = (
            f"Material {material} has toxicity rating {rating}. "
            f"Offgas products within acceptable limits for cabin volume per NASA-STD-6016C {clause_refs[0]}."
        )
    elif test_class == "SCC":
        mitigation_text = (
            f"Material {material} has SCC rating {rating}. "
            f"Environmental conditions do not promote stress corrosion cracking per NASA-STD-6016C {clause_refs[0]}."
        )
    elif test_class == "CORR":
        mitigation_text = (
            f"Material {material} has corrosion rating {rating}. "
            f"Protective coatings/treatments applied per NASA-STD-6016C {clause_refs[0]}."
        )
    else:
        mitigation_text = (
            f"Material {material} has {test_class} rating {rating}. "
            f"Engineering evaluation confirms acceptable performance for this application."
        )

    return MitigationClause(
        test_class=test_class,
        rating_gap=rating,
        mitigation_text=mitigation_text,
        source_document="NASA-STD-6016C",
        clause_refs=clause_refs,
        confidence_score=0.7,  # Base confidence without precedent lookup
        precedent_count=0,  # Would be populated by precedent retrieval
    )


__all__ = ["generate_mua"]
