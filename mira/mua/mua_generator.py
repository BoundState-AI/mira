#!/usr/bin/env python3
"""
Module: Mua Generator
Purpose: Clause-anchored MUA draft generator with FAISS-backed precedent retrieval.

BoundState AI 2025
Version: 1.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Fran OpenAI 5 <noreply@openai.com>
Co-Authored-By: Grok 4.0 <noreply@x.ai>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: SWE-032 (Data validation), SWE-033 (Requirements Traceability)
Safety Critical: False
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from .models import (
    EnvironmentEnvelope,
    EvidenceRef,
    MIULRef,
    Mitigation,
    RatingClass,
    RatingResult,
)
from .retrieval import build_retrieval_query, get_retriever
import uuid

LOGGER = logging.getLogger(__name__)

CLAUSE = {
    "flammability_control": "\u00A74.2.1.1",
    "offgassing": "\u00A74.2.1.2",
    "fluid_compat": "\u00A74.2.1.3",
    "oxygen_compat": "\u00A74.2.1.4",
    "tvs": "\u00A74.2.3.6",
    "corrosion": "\u00A74.2.6.3",
    "verification": "\u00A74.3",
}

REQ_CLASSES: List[RatingClass] = ["FLAMM", "SCC", "CORR", "TVS", "TOX", "FS"]


def detect_gaps(ratings: List[RatingResult]) -> Dict[str, str]:
    return {r.test_class: r.rating for r in ratings if r.test_class in REQ_CLASSES and r.rating != "A"}


def _validate_environment(miul: MIULRef, gaps: Dict[str, str]) -> None:
    """
    Ensure the MIUL environment envelope contains the minimum information required
    to generate a precedent-backed MUA. Missing context is an immediate hard stop.
    """
    env = miul.environment
    missing: List[str] = []

    # Always require explicit habitable flag (NASA-STD-6016 routing)
    if env.habitable_volume is None:
        missing.append("habitable_volume")

    # Require at least one of pressure/temperature to describe severity
    if env.pressure_kpa is None and env.temperature_c is None:
        missing.append("pressure_kpa or temperature_c")

    # Fluid compatibility and toxicity analysis demand a fluid/gas identifier
    if any(g in gaps for g in ("FS", "TOX", "FLAMM")) and not (env.fluid_medium and env.fluid_medium.strip()):
        missing.append("fluid_medium")

    # Flammability/toxicity also expect oxygen context (percent or enriched flag)
    if any(g in gaps for g in ("FLAMM", "TOX")) and env.oxygen_pct is None:
        missing.append("oxygen_pct")

    if missing:
        raise ValueError(
            f"Incomplete environment data for MUA generation "
            f"(missing {', '.join(missing)}). Provide full envelope before drafting."
        )


def route_category(miul: MIULRef, gaps: Dict[str, str]) -> Tuple[str, List[str]]:
    app_b: List[str] = []
    if "TVS" in gaps and not (miul.environment.habitable_volume or False):
        app_b.append("TVS-407")
    if app_b:
        return "III", app_b
    o2 = miul.environment.oxygen_pct or 0.0
    lo2 = (miul.environment.fluid_medium or "").upper() in {"LOX", "GOX"}
    high_p = (miul.environment.pressure_kpa or 0) > 300
    if lo2 or o2 >= 23.5 or high_p:
        return "I", []
    return "II", []


def _fake_retrieve(miul: MIULRef, gaps: Dict[str, str]) -> List[Mitigation]:
    """Generate gap-specific mitigations when retriever unavailable."""
    out: List[Mitigation] = []
    material = miul.material_designator or miul.materialkey

    if "TVS" in gaps:
        rating = gaps["TVS"]
        if rating == "B":
            out.append(
                Mitigation(
                    text=f"Vacuum bake {material} components at 125\u00B0C for 24h prior to final assembly. Verify CVCM \u2264 0.10% and TML \u2264 1.00% via ASTM E595 testing on as-fabricated lot.",
                    source_doc_id="NASA-STD-6016",
                    clause_refs=[CLAUSE["tvs"], CLAUSE["verification"]],
                    score=0.85,
                    hazards=["miul:TVS"],
                    acceptance={"cvcm_max": 0.1, "tml_max": 1.0},
                )
            )
        else:  # U or worse
            out.append(
                Mitigation(
                    text=f"Conduct ASTM E595 outgassing testing on {material} in as-fabricated configuration. Acceptance: CVCM \u2264 0.10%, TML \u2264 1.00%. If used near contamination-sensitive optics, require CVCM \u2264 0.01%.",
                    source_doc_id="NASA-STD-6016",
                    clause_refs=[CLAUSE["tvs"], CLAUSE["verification"]],
                    score=0.82,
                    hazards=["miul:TVS"],
                    acceptance={"cvcm_max": 0.1, "tml_max": 1.0, "cvcm_max_tight": 0.01},
                )
            )

    if "FLAMM" in gaps:
        rating = gaps["FLAMM"]
        o2_env = "oxygen-enriched" if (miul.environment.oxygen_pct or 0) >= 23.5 else "ambient air"
        if rating == "B":
            out.append(
                Mitigation(
                    text=f"Limit {material} to low-energy-ignition configurations. Conduct configuration-specific flammability testing per NASA-STD-6001 at worst-case O\u2082 concentration and operating temperature for {o2_env} environment.",
                    source_doc_id="NASA-STD-6016",
                    clause_refs=[CLAUSE["flammability_control"], CLAUSE["oxygen_compat"], CLAUSE["verification"]],
                    score=0.80,
                    hazards=["miul:FLAMM", "hazard:oxygen"],
                )
            )
        else:
            out.append(
                Mitigation(
                    text=f"Establish flammability rating for {material} via NASA-STD-6001 Test 1 (upward propagation). Limit use to encapsulated or low-oxygen areas (\u2264 21% O\u2082). Implement ignition source controls per \u00A74.2.1.4.",
                    source_doc_id="NASA-STD-6016",
                    clause_refs=[CLAUSE["flammability_control"], CLAUSE["oxygen_compat"], CLAUSE["verification"]],
                    score=0.75,
                    hazards=["miul:FLAMM"],
                )
            )

    if "SCC" in gaps:
        rating = gaps["SCC"]
        if rating in ["B", "C"]:
            out.append(
                Mitigation(
                    text=f"Evaluate {material} stress state and environment. Limit operating stress to \u2264 50% yield strength in corrosive environments. Conduct stress corrosion testing per ASTM G129 if high-stress service expected.",
                    source_doc_id="MSFC-SPEC-522B",
                    clause_refs=[CLAUSE["corrosion"], CLAUSE["verification"]],
                    score=0.78,
                    hazards=["miul:SCC"],
                )
            )
        else:
            out.append(
                Mitigation(
                    text=f"Conduct stress corrosion cracking assessment for {material} per MSFC-SPEC-522B. Establish material condition, stress levels, and environmental exposure. Perform coupon testing if moderate-to-high SCC risk identified.",
                    source_doc_id="MSFC-SPEC-522B",
                    clause_refs=[CLAUSE["corrosion"], CLAUSE["verification"]],
                    score=0.72,
                    hazards=["miul:SCC"],
                )
            )

    if "CORR" in gaps:
        rating = gaps["CORR"]
        out.append(
            Mitigation(
                text=f"Protect {material} surfaces with corrosion-resistant coating or finish per MSFC-SPEC-250A. Verify coating integrity via visual inspection and adhesion testing. Alternative: demonstrate corrosion resistance via testing per ASTM B117 or G85.",
                source_doc_id="NASA-STD-6016",
                clause_refs=[CLAUSE["corrosion"], CLAUSE["verification"]],
                score=0.76,
                hazards=["miul:CORR"],
            )
        )

    if "FS" in gaps:
        rating = gaps["FS"]
        fluid = miul.environment.fluid_medium or "service fluid"
        out.append(
            Mitigation(
                text=f"Conduct fluid compatibility testing for {material} with {fluid} per NASA-STD-6001 Test 13 or ASTM G46. Verify no significant material degradation, swelling, or contamination. Document fluid exposure limits and service conditions.",
                source_doc_id="NASA-STD-6016",
                clause_refs=[CLAUSE["fluid_compat"], CLAUSE["verification"]],
                score=0.80,
                hazards=["miul:FS"],
            )
        )

    if "TOX" in gaps:
        rating = gaps["TOX"]
        out.append(
            Mitigation(
                text=f"Evaluate toxicity hazards for {material} combustion products and decomposition. Implement ventilation controls for habitable volumes. Provide crew training on material hazards. Conduct toxicity testing per NASA-STD-6001 if significant crew exposure risk.",
                source_doc_id="NASA-STD-6016",
                clause_refs=[CLAUSE["offgassing"], CLAUSE["verification"]],
                score=0.74,
                hazards=["miul:TOX"],
            )
        )

    # Add general engineering controls
    if len(out) > 0:
        out.append(
            Mitigation(
                text=f"Document {material} usage in hardware configuration control. Implement inspection and verification requirements in acceptance test procedures. Track material lot/batch traceability through manufacturing records.",
                source_doc_id="NASA-STD-6016",
                clause_refs=[CLAUSE["verification"]],
                score=0.65,
            )
        )

    if not out:
        out.append(
            Mitigation(
                text=f"Perform engineering evaluation of {material} for gaps: {', '.join(gaps.keys())}. Add verification testing to demonstrate acceptability in as-used configuration per NASA-STD-6016 \u00A74.3.",
                source_doc_id="NASA-STD-6016",
                clause_refs=[CLAUSE["verification"]],
                score=0.50,
            )
        )

    out.sort(key=lambda m: m.score, reverse=True)
    return out


def estimate_confidence(mitigations: List[Mitigation]) -> Dict[str, Any]:
    if not mitigations:
        return {"global": 0.4, "notes": ["Low precedent coverage."]}
    avg = sum(m.score for m in mitigations) / len(mitigations)
    return {
        "global": round(min(0.95, max(0.3, avg)), 3),
        "interval_68": [round(max(0.0, avg - 0.08), 3), round(min(1.0, avg + 0.08), 3)],
        "interval_95": [round(max(0.0, avg - 0.15), 3), round(min(1.0, avg + 0.15), 3)],
        "known_unknowns": [
            "Verify environment bounds match as-used configuration.",
            "Confirm latest MAPTIS evidence IDs and report revisions.",
        ],
    }


def _format_acceptance(acc: Dict[str, float]) -> Optional[str]:
    if not acc:
        return None
    parts: List[str] = []
    if "cvcm_max" in acc:
        parts.append(f"CVCM \u2264 {acc['cvcm_max']:.2f}%")
    if "tml_max" in acc:
        parts.append(f"TML \u2264 {acc['tml_max']:.2f}%")
    if "cvcm_max_tight" in acc:
        parts.append(f"CVCM \u2264 {acc['cvcm_max_tight']:.2f}% (contamination-sensitive)")
    if "o2_threshold_pct" in acc:
        parts.append(f"O\u2082 \u2264 {acc['o2_threshold_pct']:.1f}%")
    return ", ".join(parts) if parts else None


def render_text(
    mua_id: str,
    miul: MIULRef,
    ratings: List[RatingResult],
    gaps: Dict[str, str],
    category: str,
    appendix_b: List[str],
    mitigations: List[Mitigation],
    confidence: Dict[str, Any],
) -> str:
    lines: List[str] = []
    lines.append(f"Material Usage Agreement (MUA) | ID: {mua_id}")
    lines.append(f"Created: {datetime.utcnow().isoformat(timespec='seconds')}Z")
    lines.append("")
    lines.append(f"Program: {miul.program or 'N/A'} | Hardware: {miul.hardware_name or 'N/A'}")
    lines.append(
        f"MIUL: {miul.miul_id} | MaterialKey: {miul.materialkey} | Designator: {miul.material_designator or 'N/A'}"
    )
    env = miul.environment
    lines.append(
        f"Env: O2={env.oxygen_pct if env.oxygen_pct is not None else 'N/A'}% | "
        f"P={env.pressure_kpa if env.pressure_kpa is not None else 'N/A'} kPa | "
        f"T={env.temperature_c if env.temperature_c is not None else 'N/A'} \u00B0C | "
        f"Medium={env.fluid_medium or 'N/A'} | Habitable={'Yes' if env.habitable_volume else 'No'}"
    )
    lines.append("Ratings:")
    for r in ratings:
        ev = (
            f" (MAPTIS {r.evidence.map_tis_id or '?'}; {r.evidence.test_method or 'method?'}; "
            f"report {r.evidence.report_no or '?'})" if r.evidence else ""
        )
        lines.append(f"  - {r.test_class}: {r.rating}{ev}")
    lines.append(f"Gap Profile: {gaps or 'None'}")
    lines.append(f"Category (6016 \u00A74.1.3): {category}")
    if appendix_b and category == "III":
        lines.append("Appendix B Codes: " + ", ".join(appendix_b))
    lines.append("")
    lines.append("1) Purpose & Scope")
    lines.append(
        "   This MUA reduces risks associated with non-A ratings in the as-used configuration. "
        f"Clauses: {', '.join(CLAUSE.values())}."
    )
    lines.append("2) Mitigations / Controls (ranked)")
    for idx, m in enumerate(mitigations, start=1):
        lines.append(f"   {idx}. {m.text}")
        em_dash = '\u2014'
        clause_refs_text = ', '.join(m.clause_refs) if m.clause_refs else em_dash
        lines.append(
            f"      \u2022 Clause refs: {clause_refs_text}"
        )
        lines.append(
            f"      \u2022 Source precedent: {m.source_doc_id}"
            + (f" ({m.source_center})" if m.source_center else "")
            + f" | Score: {round(m.score, 2)}"
        )
        meta = m.metadata or {}
        if meta.get("historic_precedent"):
            material_codes = ", ".join(meta.get("material_codes") or [])
            specifications = ", ".join(filter(None, meta.get("specifications") or []))
            conditions = meta.get("conditions")
            if material_codes:
                lines.append(f"      \u2022 Precedent material codes: {material_codes}")
            if specifications:
                lines.append(f"      \u2022 Referenced specs: {specifications}")
            if conditions:
                lines.append(f"      \u2022 Operating conditions: {conditions}")
            if meta.get("tags"):
                lines.append(f"      \u2022 Tags: {', '.join(meta['tags'])}")
            if meta.get("file_hash"):
                file_hash = meta["file_hash"]
                lines.append(
                    f"      \u2022 Historic record: /mua/historic/{file_hash} "
                    f"| PDF: /mua/historic/{file_hash}/pdf"
                )
        acceptance_text = _format_acceptance(m.acceptance)
        if acceptance_text:
            lines.append(f"      \u2022 Acceptance: {acceptance_text}")
        if m.has_table:
            lines.append("      \u2022 Derived from standards table")
    lines.append("3) Verification & Acceptance (\u00A74.3)")
    if "TVS" in gaps:
        lines.append(
            "   - Perform ASTM E595 on as-fabricated lot; Acceptance: CVCM \u2264 0.10%, TML \u2264 1.00% "
            "(CVCM \u2264 0.01% for contamination-sensitive optics)."
        )
    if "FLAMM" in gaps:
        lines.append(
            "   - Conduct configuration-representative flammability testing at worst-case O\u2082 and temperature; "
            "no sustained ignition per method criteria."
        )
    lines.append("4) Traceability & Citations")
    for m in mitigations:
        # Add file_hash if this is a historic precedent with PDF
        file_hash = m.metadata.get("file_hash") if m.metadata.get("historic_precedent") else None
        if file_hash:
            lines.append(f"   - [Precedent] {m.source_doc_id} (PDF: /mua/historic/{file_hash}/pdf)")
        else:
            lines.append(f"   - [Precedent] {m.source_doc_id}")
        specs = m.metadata.get("specifications") if m.metadata else None
        if specs:
            lines.append(f"     • Specs: {', '.join(filter(None, specs))}")
        codes = m.metadata.get("material_codes") if m.metadata else None
        if codes:
            lines.append(f"     • Material codes: {', '.join(codes)}")
        if m.metadata.get("conditions"):
            lines.append(f"     • Conditions: {m.metadata.get('conditions')}")
        for clause in m.clause_refs:
            lines.append(f"   - [6016] {clause}")
    for r in ratings:
        if r.evidence and (r.evidence.map_tis_id or r.evidence.report_no):
            lines.append(
                f"   - [MAPTIS] {r.evidence.map_tis_id or r.evidence.report_no}: {r.test_class}={r.rating}"
            )
    lines.append("5) Confidence Summary")
    lines.append(
        f"   - global={confidence.get('global')} | 68%={confidence.get('interval_68')} | "
        f"95%={confidence.get('interval_95')}"
    )
    for note in confidence.get("known_unknowns", []):
        lines.append(f"   - {note}")
    lines.append("")
    lines.append("[Note] Language avoids guarantees; mitigations reduce risk based on precedent and standards.")
    return "\n".join(lines)


def generate_mua(miul: MIULRef, ratings: List[RatingResult]) -> Dict[str, Any]:
    gaps = detect_gaps(ratings)
    if not gaps:
        return {"required": False, "reason": "All required ratings are A"}

    _validate_environment(miul, gaps)

    category, appendix_b = route_category(miul, gaps)

    try:
        retriever = get_retriever()
    except Exception as exc:  # pragma: no cover
        raise RuntimeError(f"Mitigation retrieval unavailable: {exc}") from exc

    try:
        mitigations = retriever.retrieve(miul, gaps)
        LOGGER.debug(
            "Retrieved %d mitigations for %s using query '%s'",
            len(mitigations),
            miul.materialkey,
            build_retrieval_query(miul, gaps),
        )
    except Exception as exc:  # pragma: no cover
        raise RuntimeError(f"Mitigation retrieval failed: {exc}") from exc

    if not mitigations:
        raise RuntimeError(
            "No precedent-backed mitigations matched the current gap profile. "
            "Escalate for manual engineering review."
        )

    confidence = estimate_confidence(mitigations)
    mua_id = f"MUA-DRAFT-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}"
    draft_text = render_text(mua_id, miul, ratings, gaps, category, appendix_b, mitigations, confidence)

    return {
        "required": True,
        "id": mua_id,
        "category": category,
        "appendix_b": appendix_b,
        "gap_profile": gaps,
        "mitigations": [m.__dict__ for m in mitigations],
        "confidence": confidence,
        "draft_text": draft_text,
    }
