#!/usr/bin/env python3
"""
Module: MUA v7 API Router — Helper Functions
Purpose: Stateless utilities for the MUA v7 wizard workflow router.

BoundState AI 2026
Version: 7.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude "Atlas" <noreply@anthropic.com>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: NASA-STD-8739.8B, SWE-013, SWE-032
Safety Critical: True

Extracted from mua_v7.py to keep the router focused on route handlers
and reduce the god-class footprint. These are pure functions with no
dependency on module-level service instances (session_manager, etc.).

Groups:
- MIUL import helpers (bucket classification, environment suggestion)
- Environment/medium classification
- DB connection helpers (cached, MAPTIS schema)
- FS media context lookup (multi-source, silver_report_rows + curated)
- Divergence detection (audit-only, does NOT block workflow)
- Audit trail construction (structured dict for post-hoc review)
- Export text generation (plain-text MUA rendering)
"""

from __future__ import annotations

import logging
import re
from collections import Counter
from datetime import datetime
from functools import lru_cache
from typing import Optional

from mira.mua.v7.models import (
    EvidenceStrengthBand,
    FinalizedMUA,
    InvestigationResult,
    ReviewDecisions,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# MIUL import helpers
# ---------------------------------------------------------------------------


def issues_from_signature(signature: str) -> list[str]:
    """Extract issue codes from a MIUL trigger signature string."""
    issues: list[str] = []
    if not signature:
        return issues
    for token in signature.split("|"):
        if ":" not in token:
            continue
        issue = token.split(":", 1)[0].strip().upper()
        if issue and issue not in issues:
            issues.append(issue)
    return issues


def suggest_environment_from_bucket(bucket: dict) -> dict:
    """Build a default EnvironmentSpec dict from a MIUL import bucket."""
    env_raw = str(bucket.get("environment") or "")
    env_upper = env_raw.upper()

    medium = "Air"
    o2_percent = 21.0
    location = "habitable"
    if "GH2" in env_upper or "LH2" in env_upper or "HYDROGEN" in env_upper:
        medium = "Hydrogen"
        o2_percent = 0.0
        location = "non-habitable"
    elif "GOX" in env_upper:
        medium = "GOX"
        o2_percent = 99.5
        location = "non-habitable"
    elif "LOX" in env_upper:
        medium = "LOX"
        o2_percent = 99.5
        location = "non-habitable"

    tmin = bucket.get("temp_min_f")
    tmax = bucket.get("temp_max_f")
    pmax = bucket.get("pressure_max_psia")
    return {
        "o2_percent": float(o2_percent),
        "pressure_psia": float(pmax) if pmax is not None else 14.7,
        "temp_min_f": float(tmin) if tmin is not None else 60.0,
        "temp_max_f": float(tmax) if tmax is not None else 85.0,
        "medium": medium,
        "location": location,
        "application": "",
    }


def category_hint_for_bucket(bucket: dict, issues: list[str]) -> tuple[str, list[str]]:
    """Estimate MUA category from MIUL bucket characteristics."""
    env_raw = str(bucket.get("environment") or "").upper()
    sig = str(bucket.get("trigger_signature") or "")
    risk = str(bucket.get("risk_band") or "low").lower()

    reasons: list[str] = []
    if "GOX" in env_raw or "LOX" in env_raw:
        reasons.append("Oxygen service detected from MIUL environment.")
        return "I_or_II", reasons
    if "GH2" in env_raw or "LH2" in env_raw:
        reasons.append("Hydrogen service detected from MIUL environment.")
        reasons.append("Many programs still close this via Category III rationale when approved in-plan.")
        return "III_or_II", reasons
    if any(code in sig for code in ("FLAM:C", "FLAM:D", "FLAM:X")):
        reasons.append("Non-A flammability rating requires engineering disposition.")
        return "II_or_III", reasons
    if risk == "high":
        reasons.append("High trigger-risk bucket; engineer review required.")
        return "II_or_III", reasons
    if issues and all(i in ("FS", "SCC", "CORR", "TVS", "TOX", "FLAM") for i in issues):
        reasons.append("Common repeat-trigger bucket suitable for batched MUA triage.")
        return "III_or_II", reasons
    return "II_or_III", ["Default non-A trigger path."]


# ---------------------------------------------------------------------------
# Medium / environment classification
# ---------------------------------------------------------------------------


def classify_medium_text(value: str) -> str:
    """Classify a free-text medium string into a canonical category."""
    text = (value or "").strip().upper()
    if not text:
        return "UNKNOWN"
    if any(
        k in text
        for k in (
            "HYDRAZINE",
            "N2H4",
            "MMH",
            "UDMH",
            "NTO",
            "N2O4",
            "DINITROGEN TETROXIDE",
        )
    ):
        return "HYDRAZINE"
    if any(k in text for k in ("GH2", "LH2", " HYDROGEN", "H2", "GASEOUS HYDROGEN", "LIQUID HYDROGEN")):
        return "HYDROGEN"
    if any(k in text for k in ("GOX", "LOX", "OXYGEN", " ENRICHED O2", " O2")):
        return "OXYGEN"
    if "AIR" in text:
        return "AIR"
    return "UNKNOWN"


def infer_env_type(env: "object") -> str:
    """Map an EnvironmentSpec to a canonical PG env_type for precedent lookup.

    Uses the same canonical values as the ``mua_precedents_v7`` table:
    LOX_GOX, ENRICHED_O2, CABIN_AIR, VACUUM, CRYOGENIC, etc.
    """
    o2 = getattr(env, "o2_percent", 21.0) or 21.0
    location = getattr(env, "location", "") or ""
    medium = (getattr(env, "medium", "") or "").lower()
    temp_min = getattr(env, "temp_min_f", 60.0) or 60.0

    if o2 >= 99.0 or "lox" in medium or "gox" in medium:
        return "LOX_GOX"
    if o2 >= 23.5:
        return "ENRICHED_O2"
    if "vacuum" in medium or "vacuum" in location:
        return "VACUUM"
    if temp_min <= -150:
        return "CRYOGENIC"
    if "habitable" in location:
        return "CABIN_AIR"
    if "water" in medium:
        return "WATER"
    return "UNKNOWN"


# ---------------------------------------------------------------------------
# DB connection helpers
# ---------------------------------------------------------------------------


@lru_cache(maxsize=1)
def get_db_params_cached() -> dict:
    from mira.core.db_config import get_db_connection_params
    return get_db_connection_params(options="-c search_path=maptis,public")


def open_maptis_connection():
    from mira.core.db_config import open_db_connection
    return open_db_connection(options="-c search_path=maptis,public")


# ---------------------------------------------------------------------------
# FS media context
# ---------------------------------------------------------------------------


def usage_medium_class(
    suggested_env: dict,
    env_raw: str,
    fluid_types: list[str],
) -> str:
    """Determine the usage medium class from available context."""
    for value in fluid_types:
        cls = classify_medium_text(value)
        if cls != "UNKNOWN":
            return cls
    cls_from_env = classify_medium_text(env_raw)
    if cls_from_env != "UNKNOWN":
        return cls_from_env
    return classify_medium_text(str(suggested_env.get("medium") or ""))


@lru_cache(maxsize=512)
def lookup_fs_media_context(material_code: str) -> dict:
    """Best-effort FS media context lookup for a MAPTIS material code.

    Looks at two sources:
    1) silver_report_rows (materialkey-based, authoritative for material link)
    2) maptis.fluid_compatibility_tests (media strings when available)
    """
    code = str(material_code or "").strip()
    if not code:
        return {"classes": [], "examples": [], "report_numbers": [], "source_count": 0}

    try:
        import psycopg2
        from psycopg2.extras import RealDictCursor
    except Exception:
        return {"classes": [], "examples": [], "report_numbers": [], "source_count": 0}

    classes: set[str] = set()
    examples: list[str] = []
    report_numbers: set[str] = set()
    source_count = 0

    def _add_text(text: str) -> None:
        nonlocal source_count
        t = (text or "").strip()
        if not t or t.upper() == "NULL":
            return
        source_count += 1
        cls = classify_medium_text(t)
        if cls != "UNKNOWN":
            classes.add(cls)
        if len(examples) < 8:
            examples.append(t[:220])

    try:
        with open_maptis_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                try:
                    cur.execute(
                        """
                        SELECT material_code, testreportkey, testreportnumber, fluid_name
                        FROM public.fs_media_map
                        WHERE material_code = %s
                        """,
                        (code,),
                    )
                    for row in cur.fetchall():
                        rno = str(row.get("testreportnumber") or "").strip()
                        if rno:
                            report_numbers.add(rno)
                        tkey = str(row.get("testreportkey") or "").strip()
                        if tkey:
                            report_numbers.add(f"key:{tkey}")
                        _add_text(str(row.get("fluid_name") or ""))
                except Exception:
                    try:
                        conn.rollback()
                    except Exception:
                        pass

                cur.execute(
                    """
                    SELECT
                        normalized_payload->>'testreportnumber' AS report_no,
                        normalized_payload->>'fluc_reference' AS fluc_reference,
                        normalized_payload->>'fluc_materialfluidchanges' AS fluc_changes
                    FROM silver_report_rows
                    WHERE contract_id = 'fluid_compatibility_report'
                      AND normalized_payload->>'materialkey' = %s
                    """,
                    (code,),
                )
                silver_rows = cur.fetchall()
                for row in silver_rows:
                    report_no = str(row.get("report_no") or "").strip()
                    if report_no and report_no.upper() != "NULL":
                        report_numbers.add(report_no)
                    ref = str(row.get("fluc_reference") or "").strip()
                    if ref and ref.upper() != "NULL":
                        _add_text(f"FS_REF:{ref}")
                    _add_text(str(row.get("fluc_changes") or ""))

                material_code_int = int(code) if code.isdigit() else None
                if material_code_int is not None:
                    cur.execute(
                        """
                        SELECT test_report_no, media, media_spec, material_fluid_changes
                        FROM maptis.fluid_compatibility_tests
                        WHERE material_code = %s
                        """,
                        (material_code_int,),
                    )
                    rows = cur.fetchall()
                    for row in rows:
                        rno = str(row.get("test_report_no") or "").strip()
                        if rno and rno.upper() != "NULL":
                            report_numbers.add(rno)
                        _add_text(str(row.get("media") or ""))
                        _add_text(str(row.get("media_spec") or ""))
                        _add_text(str(row.get("material_fluid_changes") or ""))

                if report_numbers:
                    report_list = sorted(report_numbers)
                    cur.execute(
                        """
                        SELECT test_report_no, media, media_spec, material_fluid_changes
                        FROM maptis.fluid_compatibility_tests
                        WHERE test_report_no = ANY(%s)
                        """,
                        (report_list,),
                    )
                    rows = cur.fetchall()
                    for row in rows:
                        _add_text(str(row.get("media") or ""))
                        _add_text(str(row.get("media_spec") or ""))
                        _add_text(str(row.get("material_fluid_changes") or ""))
    except Exception:
        logger.exception("FS media context lookup failed for material_code=%s", code)

    return {
        "classes": sorted(classes),
        "examples": examples,
        "report_numbers": sorted(report_numbers),
        "source_count": source_count,
    }


def adjust_fs_issue_scope(
    material_code: str,
    issues: list[str],
    *,
    env_raw: str,
    suggested_env: dict,
    fluid_types: list[str],
) -> tuple[list[str], list[str]]:
    """Filter FS issue when DB media context conflicts with usage medium."""
    if "FS" not in issues:
        return issues, []

    u_cls = usage_medium_class(suggested_env, env_raw, fluid_types)
    if u_cls != "HYDROGEN":
        return issues, []

    ctx = lookup_fs_media_context(material_code)
    ctx_classes = set(ctx.get("classes") or [])
    reasons: list[str] = []

    if ctx_classes and "HYDROGEN" not in ctx_classes and "HYDRAZINE" in ctx_classes:
        filtered = [i for i in issues if i != "FS"]
        reasons.append(
            "FS evidence appears tied to hydrazine/non-H2 media in DB; "
            "FS was removed from default issue scope for H2 usage."
        )
        return filtered, reasons

    if not ctx_classes:
        reasons.append(
            "No FS media mapping found in DB for this material. If your FS dataset is available, "
            "load it so FS can be medium-filtered (H2 vs hydrazine)."
        )
    return issues, reasons


# ---------------------------------------------------------------------------
# Divergence detection
# ---------------------------------------------------------------------------


def detect_divergence(
    decisions: ReviewDecisions,
    investigation: InvestigationResult,
    evidence_band: EvidenceStrengthBand,
) -> bool:
    """Detect whether the engineer's review decisions diverge from the
    evidence strength band.

    Divergence is flagged when:
    - The evidence band is STRONG or MODERATE but the engineer excludes
      a majority of supporting precedents.
    - The evidence band is WEAK or INSUFFICIENT but the engineer includes
      a majority of conflicting precedents as supporting.

    This is a silent annotation for the audit trail -- it does NOT block
    the workflow.
    """
    from mira.mua.v7.models import ReviewDecisionType

    if not decisions.precedent_decisions:
        return False

    decision_map = {
        d.mua_number: d.decision for d in decisions.precedent_decisions
    }

    supporting_mua_numbers = {
        p.mua_number for p in investigation.supporting_precedents
    }
    excluded_supporting = sum(
        1
        for mua_num, dec in decision_map.items()
        if mua_num in supporting_mua_numbers
        and dec == ReviewDecisionType.EXCLUDE
    )
    total_supporting_reviewed = sum(
        1
        for mua_num in decision_map
        if mua_num in supporting_mua_numbers
    )

    conflicting_mua_numbers = {
        p.mua_number for p in investigation.conflicting_precedents
    }
    included_conflicting = sum(
        1
        for mua_num, dec in decision_map.items()
        if mua_num in conflicting_mua_numbers
        and dec == ReviewDecisionType.INCLUDE_SUPPORTING
    )
    total_conflicting_reviewed = sum(
        1
        for mua_num in decision_map
        if mua_num in conflicting_mua_numbers
    )

    if evidence_band in (
        EvidenceStrengthBand.STRONG,
        EvidenceStrengthBand.MODERATE,
    ):
        if (
            total_supporting_reviewed > 0
            and excluded_supporting > total_supporting_reviewed / 2
        ):
            return True

    if evidence_band in (
        EvidenceStrengthBand.WEAK,
        EvidenceStrengthBand.INSUFFICIENT,
    ):
        if (
            total_conflicting_reviewed > 0
            and included_conflicting > total_conflicting_reviewed / 2
        ):
            return True

    return False


# ---------------------------------------------------------------------------
# Audit trail construction
# ---------------------------------------------------------------------------


def build_audit_trail(
    *,
    session_id: str,
    investigation: InvestigationResult,
    review_decisions: ReviewDecisions,
    draft: "MUADraft",
    reviewer: str,
    finalized_at: datetime,
) -> dict:
    """Build a structured audit trail dictionary for the finalized MUA."""
    from mira.mua.v7.models import MUADraft

    return {
        "session_id": session_id,
        "finalized_at": finalized_at.isoformat(),
        "reviewer": reviewer,
        "evidence_summary": {
            "supporting_precedents": len(investigation.supporting_precedents),
            "conflicting_precedents": len(investigation.conflicting_precedents),
            "test_records": len(investigation.test_data),
            "gaps_identified": len(investigation.gaps),
            "conflicts_identified": len(investigation.conflicts),
            "evidence_strength_band": investigation.evidence_strength.band,
            "evidence_strength_score": investigation.evidence_strength.score,
            "is_novel_material": investigation.is_novel_material,
        },
        "review_summary": {
            "precedent_decisions": len(review_decisions.precedent_decisions),
            "gap_decisions": len(review_decisions.gap_decisions),
            "conflict_decisions": len(review_decisions.conflict_decisions),
            "all_items_reviewed": review_decisions.all_items_reviewed,
            "divergence_detected": review_decisions.divergence_detected,
            "divergence_rationale": review_decisions.divergence_rationale,
        },
        "draft_summary": {
            "mua_id": draft.mua_id,
            "category": draft.category,
            "sections_count": len(draft.sections),
            "fact_checks_total": len(draft.fact_check_results),
            "fact_checks_verified": sum(
                1 for fc in draft.fact_check_results if fc.status == "verified"
            ),
            "fact_checks_judgment": sum(
                1 for fc in draft.fact_check_results if fc.status == "judgment"
            ),
            "fact_checks_unverified": sum(
                1 for fc in draft.fact_check_results if fc.status == "unverified"
            ),
            "cited_precedents": draft.cited_precedents,
        },
        "banners": investigation.banners,
        "dependency_warnings": [
            {
                "cited_mua": w.cited_mua,
                "depends_on": w.depends_on,
                "warning": w.warning,
            }
            for w in investigation.dependency_warnings
        ],
    }


# ---------------------------------------------------------------------------
# Export text generation
# ---------------------------------------------------------------------------


def generate_export_text(
    finalized_mua: FinalizedMUA,
    export_format: str,
) -> str:
    """Generate a plain-text export of the finalized MUA.

    Raises:
        ValueError: If the export format is not supported.
    """
    if export_format != "text":
        raise ValueError(f"Unsupported export format: '{export_format}'")

    lines: list[str] = []
    lines.append("=" * 72)
    lines.append("NASA MATERIAL USAGE AGREEMENT (MUA)")
    lines.append("=" * 72)
    lines.append("")
    lines.append(f"MUA ID:             {finalized_mua.mua_id}")
    lines.append(f"Session ID:         {finalized_mua.session_id}")
    lines.append(f"Material:           {finalized_mua.material.input_text}")

    if finalized_mua.material.material_code:
        lines.append(
            f"MAPTIS Code:        {finalized_mua.material.material_code}"
        )

    lines.append(f"Category:           {finalized_mua.category.category.value}")
    lines.append(
        f"Evidence Strength:  {finalized_mua.evidence_strength.band.value.upper()} "
        f"({finalized_mua.evidence_strength.score:.2f})"
    )
    lines.append(f"Center:             {finalized_mua.center.value}")
    lines.append(
        f"Applied Standard:   {finalized_mua.applied_standard_version}"
    )
    lines.append(f"Reviewer:           {finalized_mua.reviewer}")
    lines.append(
        f"Finalized:          {finalized_mua.finalized_at.isoformat()}"
    )
    lines.append("")
    lines.append("-" * 72)
    lines.append("ENVIRONMENT")
    lines.append("-" * 72)
    env = finalized_mua.environment
    lines.append(f"Medium:             {env.medium}")
    lines.append(f"O2 Percent:         {env.o2_percent}%")
    lines.append(f"Pressure:           {env.pressure_psia} psia")
    lines.append(
        f"Temperature Range:  {env.temp_min_f} degF to {env.temp_max_f} degF"
    )
    lines.append(f"Location:           {env.location}")
    lines.append(f"Application:        {env.application}")
    lines.append("")

    for section in finalized_mua.draft.sections:
        lines.append("-" * 72)
        lines.append(
            f"Section {section.section_number}: {section.title}"
        )
        lines.append("-" * 72)
        lines.append(section.content)
        lines.append("")

    if finalized_mua.dependency_links:
        lines.append("-" * 72)
        lines.append("DEPENDENCY LINKS")
        lines.append("-" * 72)
        for link in finalized_mua.dependency_links:
            lines.append(f"  - {link}")
        lines.append("")

    lines.append("=" * 72)
    lines.append("END OF DOCUMENT")
    lines.append("=" * 72)

    return "\n".join(lines)
