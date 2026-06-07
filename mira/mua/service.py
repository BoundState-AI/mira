#!/usr/bin/env python3
"""
Module: Service
Purpose: MUA Service Layer — precedent-grounded MUA generation entrypoint.

This is the public, synchronous entrypoint (`mira.mua.generate_mua`). It grounds
every mitigation in the historic MUA corpus (`mua_precedents_v7`) via the v7
`search_precedents_pg` retriever:

    1. Identify rating gaps (non-A ratings).
    2. Map gaps -> canonical issue codes; derive material family + env envelope.
    3. Retrieve real historic precedents once from the corpus.
    4. Ground each gap's mitigation in the matching precedents (real citations,
       honest confidence = retriever relevance, real precedent_count).
    5. When the corpus is unavailable OR no precedent matches a gap, emit a
       standards-only mitigation EXPLICITLY flagged as such (precedent_backed=
       False, confidence_score=0.0) — never a fabricated precedent-looking score.

For the full wizard/80-20 engineer-review workflow, see the v7 router
(`mira.api.routers.mua_v7`) and `mira.mua.v7.investigator` / `DraftRenderer`.

BoundState AI 2025
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: NASA-CSET, SWE-013, SWE-032
Safety Critical: True
"""

from __future__ import annotations

import logging
import re
from typing import Dict, List, Optional

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

# Map a request test class to the canonical issue code stored in
# mua_precedents_v7 (see investigator._ALLOWED_ISSUE_CODES / aliases).
_TEST_CLASS_TO_ISSUE = {
    "FLAMM": "FLAM",
    "TVS": "TVS",
    "FS": "FS",
    "TOX": "TOX",
    "SCC": "SCC",
    "CORR": "CORR",
}

# kPa -> psia
_KPA_TO_PSIA = 0.1450377

# Determinations that count as supporting (a precedent that endorses use).
_SUPPORTING_DETERMINATIONS = {"APPROVED", "CONDITIONAL", "APPROVED_WITH_LIMITS"}
_CONFLICTING_DETERMINATIONS = {"REJECTED", "CANCELLED"}


def generate_mua(request: MuaGenerationRequest) -> MuaGenerationResponse:
    """Generate a precedent-grounded MUA for a material with rating gaps.

    Args:
        request: MuaGenerationRequest with material, program, environment, ratings

    Returns:
        MuaGenerationResponse with category, precedent-grounded mitigations, and
        evidence. Mitigations not backed by a historic precedent are explicitly
        flagged (precedent_backed=False) rather than given a fabricated score.
    """
    warnings: List[str] = []
    evidence: List[EvidenceItem] = []

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
            env = EnvironmentSpec(
                oxygen_pct=env.oxygen_pct,
                pressure_kpa=env.pressure_kpa,
                temperature_c=env.temperature_c,
                fluid_medium=env.fluid_medium,
                habitable_volume=False,
            )

        # Step 3: Route to MUA category (deterministic NASA-STD-6016C routing)
        category, appendix_b = _route_category(env, gaps)
        evidence.append(EvidenceItem(
            source_id="NASA-STD-6016C",
            location="§4.3 Verification",
            summary=f"Material routed to Category {category} based on environment and gaps",
        ))

        # Step 4: Retrieve historic precedents ONCE for all gap issues.
        designation = request.material_name or request.material_key
        precedents, corpus_available = _retrieve_precedents(
            designation=designation,
            specification=request.specification,
            gaps=gaps,
            env=env,
        )
        if not corpus_available:
            warnings.append(
                "Historic MUA precedent corpus unavailable - mitigations are "
                "standards-only and NOT grounded in precedent."
            )
        elif not precedents:
            warnings.append(
                "No historic precedents matched this material/environment/gap "
                "profile - mitigations are standards-only."
            )

        # Step 5: Build a precedent-grounded mitigation per gap.
        mitigations: List[MitigationClause] = []
        for test_class, rating in gaps.items():
            mitigation = _build_mitigation(
                test_class=test_class,
                rating=rating,
                material=designation,
                precedents=precedents,
            )
            mitigations.append(mitigation)

            cite = (
                f" (precedents: {', '.join(mitigation.cited_precedents)})"
                if mitigation.cited_precedents else " (standards-only)"
            )
            evidence.append(EvidenceItem(
                source_id=mitigation.source_document,
                location=", ".join(mitigation.clause_refs),
                summary=f"Mitigation for {test_class} rating {rating}{cite}",
            ))

        # Step 6: Rationale summary (honest about precedent grounding).
        grounded = sum(1 for m in mitigations if m.precedent_backed)
        rationale_parts = [
            f"Material {designation} requires MUA Category {category} for use on "
            f"{request.program}.",
            f" Gaps identified: {', '.join(f'{k}={v}' for k, v in gaps.items())}.",
            f" {grounded}/{len(mitigations)} mitigation(s) grounded in historic "
            f"MUA precedents",
        ]
        if corpus_available:
            rationale_parts.append(f" ({len(precedents)} precedents retrieved).")
        else:
            rationale_parts.append(" (precedent corpus unavailable).")
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
            precedents_considered=len(precedents),
            precedent_corpus_available=corpus_available,
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
    """
    appendix_b: List[str] = []

    if "TVS" in gaps and not (env.habitable_volume or False):
        appendix_b.append("TVS-407")

    if appendix_b:
        return "III", appendix_b

    o2_pct = env.oxygen_pct or 21.0
    is_lox_gox = (env.fluid_medium or "").upper() in {"LOX", "GOX"}
    high_pressure = (env.pressure_kpa or 101.3) > 300

    if is_lox_gox or o2_pct >= 23.5 or high_pressure:
        return "I", []

    return "II", []


# ---------------------------------------------------------------------------
# Precedent retrieval + grounding
# ---------------------------------------------------------------------------

def _retrieve_precedents(
    designation: str,
    specification: Optional[str],
    gaps: Dict[str, str],
    env: EnvironmentSpec,
):
    """Retrieve historic precedents from mua_precedents_v7.

    Returns (precedents, corpus_available). `precedents` is the raw list of
    PGPrecedentResult; corpus_available is False if the DB/corpus could not be
    reached (so callers can degrade transparently instead of pretending).
    """
    try:
        from mira.mua.v7.pg_precedent_search import search_precedents_pg
    except Exception as exc:  # import error / missing module
        LOGGER.warning("[MUA] precedent search unavailable: %s", exc)
        return [], False

    issues = sorted({
        _TEST_CLASS_TO_ISSUE[tc]
        for tc in gaps
        if tc in _TEST_CLASS_TO_ISSUE
    })
    family = _infer_pg_family(designation, specification)
    env_type = _derive_env_type(env)
    o2_percent = env.oxygen_pct
    pressure_psia = (env.pressure_kpa * _KPA_TO_PSIA) if env.pressure_kpa else None
    temp_f = (env.temperature_c * 9 / 5 + 32) if env.temperature_c is not None else None

    try:
        results = search_precedents_pg(
            material_designation=designation,
            material_family=family,
            issues=issues,
            env_type=env_type,
            o2_percent=o2_percent,
            pressure_psia=pressure_psia,
            temp_max_f=temp_f,
            temp_min_f=temp_f,
            is_habitable=bool(env.habitable_volume),
            include_rejected=True,
        )
        return results, True
    except Exception as exc:
        # search_precedents_pg does not wrap psycopg2.connect, so a DB-down
        # situation surfaces here. Treat it as "corpus unavailable" and degrade.
        LOGGER.warning("[MUA] precedent corpus unreachable: %s", exc)
        return [], False


def _build_mitigation(
    test_class: str,
    rating: str,
    material: str,
    precedents: list,
) -> MitigationClause:
    """Build a mitigation for one gap, grounded in matching precedents.

    Matching precedents are those whose canonical `issues` include this gap's
    issue code. Supporting (approved/conditional) precedents ground the
    mitigation; conflicting (rejected) precedents are surfaced as a warning in
    the text. Confidence = the retriever's relevance for the best supporting
    precedent (already envelope-scored and capped); 0.0 if none.
    """
    clause_refs = CLAUSE_REFS.get(test_class, ["§4.3"])
    issue_code = _TEST_CLASS_TO_ISSUE.get(test_class)

    matched = [
        p for p in precedents
        if issue_code and issue_code in (getattr(p, "issues", None) or [])
    ]
    supporting = [
        p for p in matched
        if (p.determination or "").upper() in _SUPPORTING_DETERMINATIONS
    ]
    conflicting = [
        p for p in matched
        if (p.determination or "").upper() in _CONFLICTING_DETERMINATIONS
    ]

    if supporting:
        supporting.sort(key=lambda p: p.confidence, reverse=True)
        best = supporting[0]
        cited = [p.mua_number for p in supporting[:5] if p.mua_number]
        excerpt = _clean_excerpt(best.rationale)
        text_parts = [
            f"Material {material} has {test_class} rating {rating}. "
            f"Grounded in {len(supporting)} historic precedent(s) for similar "
            f"material/environment (e.g. {best.mua_number})."
        ]
        if excerpt:
            text_parts.append(f' Precedent rationale: "{excerpt}"')
        if conflicting:
            text_parts.append(
                f" CAUTION: {len(conflicting)} historic precedent(s) were "
                f"REJECTED for similar conditions (e.g. {conflicting[0].mua_number}) "
                "— engineer review required."
            )
        return MitigationClause(
            test_class=test_class,
            rating_gap=rating,
            mitigation_text=" ".join(text_parts),
            source_document=(
                f"MUA precedents: {', '.join(cited)}" if cited else "MUA precedent corpus"
            ),
            clause_refs=clause_refs,
            confidence_score=round(float(best.confidence), 3),
            precedent_count=len(supporting),
            cited_precedents=cited,
            precedent_backed=True,
        )

    # No supporting precedent: standards-only, explicitly flagged. No fabricated
    # confidence — precedent_backed=False and confidence_score=0.0.
    caution = ""
    if conflicting:
        caution = (
            f" CAUTION: {len(conflicting)} historic precedent(s) were REJECTED "
            f"for similar conditions (e.g. {conflicting[0].mua_number})."
        )
    return MitigationClause(
        test_class=test_class,
        rating_gap=rating,
        mitigation_text=(
            f"Material {material} has {test_class} rating {rating}. No supporting "
            "historic precedent found; mitigation is standards-only and requires "
            f"engineering evaluation per NASA-STD-6016C {clause_refs[0]}.{caution}"
        ),
        source_document="NASA-STD-6016C",
        clause_refs=clause_refs,
        confidence_score=0.0,
        precedent_count=0,
        cited_precedents=[],
        precedent_backed=False,
    )


def _clean_excerpt(rationale: Optional[str], limit: int = 240) -> str:
    """Trim a precedent rationale to a short, clean excerpt."""
    if not rationale:
        return ""
    text = re.sub(r"\s+", " ", rationale).strip()
    if len(text) > limit:
        text = text[:limit].rsplit(" ", 1)[0] + "…"
    return text


def _derive_env_type(env: EnvironmentSpec) -> str:
    """Map the public EnvironmentSpec to a canonical env_type for PG search.

    Mirrors mira.mua.v7.investigator._derive_env_type, adapted to the simpler
    api_models EnvironmentSpec (fluid_medium / oxygen_pct / habitable_volume).
    """
    medium = (env.fluid_medium or "").upper()
    o2 = env.oxygen_pct

    if medium in ("LOX", "GOX", "OXYGEN", "O2"):
        return "LOX_GOX"
    if medium in ("ENRICHED_AIR", "ENRICHED_O2") or (o2 is not None and o2 >= 23.5):
        return "ENRICHED_O2"
    if medium in ("GH2", "LH2", "HYDROGEN", "H2"):
        return "HYDROGEN"
    if any(kw in medium for kw in ("NTO", "MMH", "N2O4", "HYDRAZINE")):
        return "PROPELLANT"
    if medium in ("VACUUM", "SPACE"):
        return "VACUUM"
    if env.habitable_volume:
        return "CABIN_AIR"
    if medium in ("AIR", "AMBIENT", "STANDARD_AIR", ""):
        return "STANDARD_AIR"
    return "UNKNOWN"


def _infer_pg_family(designation: str, specification: Optional[str]) -> Optional[str]:
    """Infer the canonical mua_precedents_v7 material_family from text.

    Returns None when no confident match (the retriever then relies on its
    full-text / material-anchor tiers). Canonical families per the v7 corpus.
    """
    text = f"{designation or ''} {specification or ''}".upper()

    if re.search(r"\b(STAINLESS|CRES|SST|SS)\b", text) or re.search(r"\b3\d{2}\b", text):
        return "STAINLESS_STEEL"
    if re.search(r"\b(INCONEL|HASTELLOY|MONEL|NICKEL|WASPALOY|RENE|INCOLOY|A-?286)\b", text):
        return "NICKEL_ALLOY"
    if re.search(r"\b(ALUMINUM|ALUMINIUM|AL)\b", text) or re.search(r"\b(?:60|70|20)\d{2}\b", text):
        return "ALUMINUM"
    if re.search(r"\b(TITANIUM|TI)\b", text):
        return "TITANIUM"
    if re.search(r"\b(COPPER|BRONZE|BRASS|BERYLLIUM COPPER|BECU)\b", text):
        return "COPPER_ALLOY"
    if re.search(r"\b(CARBON STEEL|ALLOY STEEL|4130|4140|A36)\b", text):
        return "CARBON_STEEL"
    if re.search(r"\b(ADHESIVE|EPOXY|SEALANT|RTV|POTTING)\b", text):
        return "ADHESIVE"
    if re.search(r"\b(PTFE|TEFLON|PEEK|POLYIMIDE|KAPTON|NYLON|DELRIN|POLYMER)\b", text):
        return "POLYMER"
    if re.search(r"\b(VITON|NITRILE|ELASTOMER|SILICONE|RUBBER|O-?RING)\b", text):
        return "ELASTOMER"
    if re.search(r"\b(COATING|ANODIZE|CHROMATE|PAINT|PRIMER)\b", text):
        return "COATING"
    if re.search(r"\b(CERAMIC|ALUMINA|GLASS|QUARTZ)\b", text):
        return "CERAMIC"
    return None


__all__ = ["generate_mua"]
