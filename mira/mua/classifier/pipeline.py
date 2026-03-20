"""MUA Generation Pipeline — BS-SPEC-MUA-003 Steps 1-8.

Full orchestration: MIUL Row In → MUA Out.

Step 1: WHAT FLAG?             → Read columns, identify non-passing ratings
Step 2: WHAT DOES IT MEAN?     → Decode via column-specific dictionary
Step 3: SHOULD THIS FLAG EXIST? → Material-class gate
Step 4: DOES THE HAZARD APPLY? → Environment check
Step 5: WHAT TYPE OF MUA?      → flag_type × hazard_applies matrix
Step 6: WHAT CATEGORY?         → Cat I or Cat II
Step 7: WRITE RATIONALE        → Template-based rationale
Step 8: FILL FORM 551          → Populate form fields

BoundState AI 2026
Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: NASA-STD-6016C w/Change 2, JSC-27301 Rev J
Safety Critical: True
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING, Any, Optional

from .classifier import (
    classify_mua,
    step1_identify_flags,
    step2_decode_flag,
)
from .models import (
    ClassifierResult,
    Form551Fields,
    MaterialClassEnum,
    MUAType,
    PipelineResult,
)
from .rationale import render_disposition, render_rationale, verify_claims
from .screening import material_class_from_miul, validate_rating_coverage
from mira.mua.evidence.retriever import retrieve_evidence_bundle
from mira.mua.precedent.lookup import lookup_precedent_with_ring
from mira.mua.synthesis.synthesizer import synthesize_rationale

if TYPE_CHECKING:
    from mira.mua.precedent.models import PrecedentSummary

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Step 8: Fill Form 551
# ---------------------------------------------------------------------------


def _fill_form_551(
    result: ClassifierResult,
    material_designation: str,
    material_specification: str | None = None,
    part_numbers: list[str] | None = None,
    part_count: int = 1,
    project: str = "",
    system: str = "",
    pressure: str = "",
    temperature: str = "",
    mua_number: str = "",
    date: str = "",
) -> Form551Fields:
    """Populate MSFC Form 551 fields from a ClassifierResult.

    Per BS-SPEC-MUA-003 Section 3, Step 8: a form with fields,
    NOT a narrative document.
    """
    rationale = render_rationale(result, material_name=material_designation)
    disposition = render_disposition(result)

    # Auto-generate MUA number if not provided
    if not mua_number:
        from datetime import date as date_mod
        mua_number = f"MUA-{result.issue_key}-{result.maptis_code}-{date_mod.today().strftime('%Y%m%d')}"

    # Link to MIUL rationale code (e.g., FLAM Cat II → "102")
    rationale_code = ""
    if result.category:
        try:
            from mira.miul.rationale_codes import get_mua_reference_code
            rationale_code = get_mua_reference_code(result.issue_key, result.category.value)
        except Exception:
            pass

    # Auto-generate application field from available data
    application_parts = []
    if material_designation:
        application_parts.append(f"{material_designation} in {result.media} service")
    if result.environment:
        application_parts.append(result.environment)
    if pressure:
        application_parts.append(pressure)
    if temperature:
        application_parts.append(temperature)
    if part_numbers:
        part_summary = ", ".join(part_numbers[:5])
        if len(part_numbers) > 5:
            part_summary += f" (+{len(part_numbers) - 5} more)"
        application_parts.append(f"Part(s): {part_summary}")
    application = ". ".join(application_parts) + "." if application_parts else ""

    return Form551Fields(
        mua_number=mua_number,
        category=result.category.value if result.category else "",
        date=date,
        governing_standard="NASA-STD-6016C",
        project=project,
        system=system,
        material_designation=material_designation,
        maptis_code=result.maptis_code,
        material_specification=material_specification or "",
        material_class=result.material_class.value,
        issue=result.issue_key,
        rating=result.rating,
        part_numbers=part_numbers or [],
        part_count=part_count,
        media=result.media,
        pressure=pressure,
        temperature=temperature,
        location=result.environment,
        application=application,
        rationale=rationale,
        disposition=disposition,
        rationale_code=rationale_code,
    )


def _infer_alloy_family(material_designation: str) -> str:
    """Best-effort alloy family inference from designation text."""
    text = (material_designation or "").upper()
    if not text:
        return ""

    if re.search(r"\bA[\-\s]?286\b", text):
        return "fe_superalloy"
    if re.search(r"\b(304|316|321|347)\b", text):
        return "austenitic_ss"
    if "INCONEL" in text or "HASTELLOY" in text or "WASPALOY" in text or "MP35N" in text:
        return "ni_superalloy"
    if "MONEL" in text:
        return "ni_alloy"
    if re.search(r"\b(70[0-9]{2}|60[0-9]{2}|20[0-9]{2})\b", text):
        return "al_alloy"
    if re.search(r"\bTI[\-\s]*6AL[\-\s]*4V\b", text):
        return "ti_alloy"
    if "VESPEL" in text:
        return "polyimide"
    if "PTFE" in text or "TEFLON" in text or re.search(r"\bKEL[\-\s]*F\b", text):
        return "fluoropolymer"
    if "VITON" in text:
        return "fluoroelastomer"
    if "COPPER" in text or "OFHC" in text or "C63000" in text:
        return "cu_alloy"
    if re.search(r"\b17[\-\s]*4\s*PH\b", text):
        return "martensitic_ss"
    return ""


def _parse_pressure_psia(pressure_str: str) -> float | None:
    """Best-effort numeric extraction of pressure in psia from free-text."""
    if not pressure_str:
        return None
    text = pressure_str.upper().strip()
    # Try to extract a number — handles "300 psia", "300", "300 PSI", etc.
    m = re.search(r"([\d.]+)\s*(?:PSIA|PSI|LB)", text)
    if m:
        try:
            return float(m.group(1))
        except ValueError:
            pass
    # Try bare number
    m = re.search(r"([\d.]+)", text)
    if m:
        try:
            val = float(m.group(1))
            # If "KPA" or "MPA" in text, convert
            if "MPA" in text:
                return val * 145.038  # MPa to psia
            if "KPA" in text:
                return val * 0.145038  # kPa to psia
            return val  # assume psia
        except ValueError:
            pass
    return None


def _parse_temp_min_f(temperature_str: str) -> float | None:
    """Best-effort numeric extraction of minimum temperature in °F from free-text."""
    if not temperature_str:
        return None
    text = temperature_str.upper().strip()
    # Look for negative numbers first (cryogenic temps)
    numbers = re.findall(r"-?[\d.]+", text)
    if not numbers:
        return None
    try:
        values = [float(n) for n in numbers]
    except ValueError:
        return None
    min_val = min(values)
    # If Celsius indicator, convert
    if "°C" in text or "DEG C" in text or "CELSIUS" in text:
        min_val = min_val * 9.0 / 5.0 + 32.0
    return min_val


def adjust_confidence(base: float, precedent: Optional["PrecedentSummary"]) -> float:
    """Apply precedent-weighted confidence adjustment."""
    if precedent is None:
        return base
    if precedent.total_count == 0:
        return base * 0.95
    weight = min(precedent.total_count / 20.0, 1.0) * 0.10
    return min(base + (weight * precedent.approval_rate), 0.99)


# ---------------------------------------------------------------------------
# Single-flag pipeline: classify + generate Form 551
# ---------------------------------------------------------------------------


def process_single_flag(
    maptis_code: str,
    issue_key: str,
    rating: str,
    material_class: MaterialClassEnum | str,
    media: str,
    material_designation: str = "",
    material_specification: str | None = None,
    environment: str = "non-habitable",
    o2_percent: float | None = None,
    batch_verified: bool = False,
    part_numbers: list[str] | None = None,
    part_count: int = 1,
    project: str = "",
    system: str = "",
    pressure: str = "",
    temperature: str = "",
    mua_number: str = "",
    date: str = "",
    alloy_family: str = "",
) -> tuple[ClassifierResult, Form551Fields | None]:
    """Run the full pipeline for a single flag.

    Returns (ClassifierResult, Form551Fields or None).
    Form551Fields is None if the MUA is not automatable.
    """
    result = classify_mua(
        maptis_code=maptis_code,
        issue_key=issue_key,
        rating=rating,
        material_class=material_class,
        media=media,
        environment=environment,
        o2_percent=o2_percent,
        batch_verified=batch_verified,
        pressure_psia=_parse_pressure_psia(pressure),
        temp_min_f=_parse_temp_min_f(temperature),
        material_family=alloy_family,
    )

    form = None
    if result.automatable:
        form = _fill_form_551(
            result=result,
            material_designation=material_designation or maptis_code,
            material_specification=material_specification,
            part_numbers=part_numbers,
            part_count=part_count,
            project=project,
            system=system,
            pressure=pressure,
            temperature=temperature,
            mua_number=mua_number,
            date=date,
        )

    return result, form


# ---------------------------------------------------------------------------
# Full pipeline: MIUL row → PipelineResult
# ---------------------------------------------------------------------------


def process_miul_row(
    ratings: dict[str, str | None],
    maptis_code: str,
    material_designation: str = "",
    alloy_family: str = "",
    material_class: MaterialClassEnum | str | None = None,
    media: str = "",
    environment: str = "non-habitable",
    o2_percent: float | None = None,
    batch_verified: bool = False,
    part_numbers: list[str] | None = None,
    part_count: int = 1,
    project: str = "",
    system: str = "",
    material_specification: str | None = None,
    pressure: str = "",
    temperature: str = "",
) -> PipelineResult:
    """Run the full 9-step pipeline for one MIUL row.

    This is the top-level orchestrator. One MIUL row can have multiple
    screening columns, each producing a separate flag and potentially
    a separate MUA.

    Parameters
    ----------
    ratings
        Dict mapping column name -> rating letter.
        E.g. {"FLAM": "C", "FS": "U", "SCC": "A", "CORR": "A", "TVS": "A", "TOX": "A"}
    maptis_code
        MAPTIS material code.
    material_designation
        Human-readable material name (e.g. "A286 CRES").
    material_class
        "metal" or "nonmetallic". If None, inferred from designation.
    media
        Service medium (e.g. "GH2", "LOX", "N2H4").
    environment
        "habitable" or "non-habitable".
    o2_percent
        Oxygen percentage if known.
    batch_verified
        Whether batch/lot verification exists for B-rated materials.
    part_numbers
        List of part numbers sharing this MAPTIS code.
    part_count
        Total number of parts (may differ from len(part_numbers)).
    project
        Project name for Form 551.
    system
        System name for Form 551.
    material_specification
        Material specification string.
    pressure
        Operating pressure string.
    temperature
        Operating temperature string.

    Returns
    -------
    PipelineResult with all flags, classifications, forms, and routing info.
    """
    # Infer material class if not provided
    if material_class is None:
        inferred = material_class_from_miul(material_designation)
        if inferred is None:
            logger.warning(
                "Cannot infer material class for '%s' (MAPTIS %s). "
                "Defaulting to metal. Route to human for verification.",
                material_designation,
                maptis_code,
            )
            material_class = MaterialClassEnum.METAL
        else:
            material_class = inferred
    elif isinstance(material_class, str):
        material_class = MaterialClassEnum(material_class.lower().strip())

    # Validate rating coverage against material class
    coverage_warnings = validate_rating_coverage(ratings, material_class)

    # Step 1: Identify all non-passing flags
    flags = step1_identify_flags(ratings)

    # Decode all flags (Step 2, for the summary)
    decoded_flags = [step2_decode_flag(col, rat) for col, rat in flags]

    # Process each flag through Steps 2-8
    classifications: list[ClassifierResult] = []
    forms: list[Form551Fields] = []
    human_required: list[ClassifierResult] = []
    human_reasons: list[str] = []

    automatable_count = 0
    human_count = 0
    no_mua_count = 0
    inferred_alloy_family = alloy_family or _infer_alloy_family(material_designation)

    for column, rating in flags:
        result, form = process_single_flag(
            maptis_code=maptis_code,
            issue_key=column,
            rating=rating,
            material_class=material_class,
            media=media,
            material_designation=material_designation,
            material_specification=material_specification,
            environment=environment,
            o2_percent=o2_percent,
            batch_verified=batch_verified,
            part_numbers=part_numbers,
            part_count=part_count,
            project=project,
            system=system,
            pressure=pressure,
            temperature=temperature,
            alloy_family=inferred_alloy_family,
        )

        try:
            precedent, ring = lookup_precedent_with_ring(
                issue=result.issue_key,
                media_category=media,
                material_class=result.material_class.value,
                alloy_family=inferred_alloy_family,
            )
        except Exception as exc:  # pragma: no cover - guardrail only
            logger.warning("MUA precedent lookup crashed, continuing without precedent: %s", exc)
            precedent, ring = None, None

        result.precedent = precedent
        result.precedent_ring = ring
        result.confidence = adjust_confidence(result.confidence, precedent)

        evidence = None
        synthesis = None

        # Retrieve evidence for all non-standard outcomes so review UI has
        # precedent context even when a flag is routed to human.
        if result.mua_type != MUAType.STANDARD:
            try:
                evidence = retrieve_evidence_bundle(
                    result=result,
                    alloy_family=inferred_alloy_family,
                )
            except Exception as exc:  # pragma: no cover - guardrail only
                logger.warning("Evidence retrieval failed; continuing with template rationale: %s", exc)
                evidence = None

        if evidence is not None:
            result.evidence_bundle = evidence

        # Synthesis runs for automatable outcomes and for REAL_PROBLEM/REAL_GAP
        # where we surface suggested rationale elements for engineers.
        if evidence and result.mua_type != MUAType.STANDARD:
            try:
                synthesis = synthesize_rationale(
                    result=result,
                    evidence=evidence,
                    material_name=material_designation or maptis_code,
                )
            except Exception as exc:  # pragma: no cover - guardrail only
                logger.warning("Synthesis failed; continuing with template rationale: %s", exc)
                synthesis = None

        if synthesis and not synthesis.template_fallback and evidence:
            _verified_claims, blocked_claims = verify_claims(synthesis, evidence)
            if blocked_claims:
                logger.warning(
                    "Blocked %d ungrounded claims for %s=%s, using template rationale",
                    len(blocked_claims),
                    result.issue_key,
                    result.rating,
                )
                synthesis = None

        if synthesis is not None:
            result.synthesis = synthesis

        if form and result.automatable:
            if synthesis and not synthesis.template_fallback:
                form.rationale = synthesis.rationale
                form.disposition = synthesis.disposition
            else:
                form.rationale = render_rationale(
                    result,
                    material_name=material_designation or maptis_code,
                )
                form.disposition = render_disposition(result)

        classifications.append(result)

        if result.mua_type == MUAType.STANDARD:
            no_mua_count += 1
        elif result.automatable:
            automatable_count += 1
            if form:
                forms.append(form)
        else:
            human_count += 1
            human_required.append(result)
            human_reasons.append(result.classification_reason)

    return PipelineResult(
        maptis_code=maptis_code,
        material_designation=material_designation,
        material_class=material_class,
        flags_identified=decoded_flags,
        classifications=classifications,
        forms=forms,
        human_required=human_required,
        human_required_reasons=human_reasons,
        total_flags=len(flags),
        automatable_count=automatable_count,
        human_required_count=human_count,
        no_mua_needed_count=no_mua_count,
        coverage_warnings=coverage_warnings,
    )


# ---------------------------------------------------------------------------
# Batch pipeline: multiple MIUL rows
# ---------------------------------------------------------------------------


def process_miul_batch(
    rows: list[dict[str, Any]],
    project: str = "",
    system: str = "",
) -> list[PipelineResult]:
    """Run the pipeline for a batch of MIUL rows.

    Each row dict must contain:
    - maptis_code: str
    - ratings: dict[str, str | None]  (or individual columns: FLAM, FS, etc.)
    - media: str
    - designation: str (optional, for material name)
    - material_class: str (optional, inferred from designation if absent)
    - environment: str (optional, defaults to "non-habitable")
    - o2_percent: float (optional)
    - batch_verified: bool (optional)
    - part_number: str (optional)
    - material_specification: str (optional)
    - pressure: str (optional)
    - temperature: str (optional)

    Returns one PipelineResult per row.
    """
    results: list[PipelineResult] = []
    for row in rows:
        # Build ratings dict from row — accept either 'ratings' key or individual columns
        ratings = row.get("ratings")
        if ratings is None:
            ratings = {}
            for col in ("FLAM", "FS", "TOX", "TVS", "SCC", "CORR"):
                val = row.get(col) or row.get(col.lower())
                if val is not None:
                    ratings[col] = val

        result = process_miul_row(
            ratings=ratings,
            maptis_code=str(row.get("maptis_code", "")).strip(),
            material_designation=str(row.get("designation", "")).strip(),
            material_class=row.get("material_class"),
            media=str(row.get("media", "")).strip(),
            environment=str(row.get("environment", "non-habitable")).strip(),
            o2_percent=row.get("o2_percent"),
            batch_verified=row.get("batch_verified", False),
            part_numbers=[str(row.get("part_number", "")).strip()] if row.get("part_number") else None,
            part_count=1,
            project=project,
            system=system,
            material_specification=row.get("material_specification"),
            pressure=str(row.get("pressure", "")).strip(),
            temperature=str(row.get("temperature", "")).strip(),
        )
        results.append(result)
    return results
