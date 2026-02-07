#!/usr/bin/env python3
"""
Module: Material Form Inference
Purpose: Infer material form from nomenclature, part description, and designation.

BoundState AI 2026
Version: 1.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: SWE-013 (Data requirements)
Safety Critical: False

Material form is a critical MIUL field that indicates the physical form of the
raw material (SHEET, PLATE, BAR, ROD, TUBE, FORGING, etc.). This module provides
intelligent inference when form is not explicitly stated on drawings.
"""

from __future__ import annotations

import re
import logging
from dataclasses import dataclass
from typing import Optional, Tuple, List

logger = logging.getLogger(__name__)

__all__ = [
    "infer_material_form",
    "FormInferenceResult",
    "FORM_NOMENCLATURE_PATTERNS",
    "FORM_DESIGNATION_PATTERNS",
]


@dataclass
class FormInferenceResult:
    """Result of material form inference."""
    form: str  # Inferred form (empty string if unable to infer)
    confidence: float  # 0.0 to 1.0
    source: str  # Where the inference came from
    reasoning: str  # Brief explanation


# Standard material forms per MAPTIS/MIUL specification
VALID_FORMS = {
    "SHEET", "PLATE", "BAR", "ROD", "TUBE", "WIRE",
    "FORGING", "CASTING", "SHAPES", "STRIP", "EXTRUSION",
    "INSERT", "SEAL", "FASTENER"
}


# =============================================================================
# FORM INFERENCE FROM NOMENCLATURE / PART DESCRIPTION
# =============================================================================
# These patterns map part descriptions to likely material forms.
# Order matters: more specific patterns first.

FORM_NOMENCLATURE_PATTERNS: List[Tuple[str, str, float, str]] = [
    # Pattern, Form, Confidence, Reasoning

    # Inserts (highest priority - very specific)
    (r'\b(HELICOIL|HELI-COIL|HELICAL\s+INSERT|INSERT|KEY-?LOCKING)\b', 'INSERT', 0.95, 'Insert/helicoil part'),

    # Seals and O-rings
    (r'\b(O-?RING|BACKUP\s+RING|SEAL|GASKET|PACKING)\b', 'SEAL', 0.90, 'Seal/O-ring part'),

    # Fasteners (screws, bolts, nuts, washers)
    (r'\b(SCREW|BOLT|NUT|WASHER|RIVET|PIN|COTTER)\b', 'FASTENER', 0.85, 'Fastener hardware'),

    # Sheet/Plate parts (thin flat parts)
    (r'\b(SKIN|PANEL|SHIM|DIAPHRAGM|MEMBRANE|LEAF|BLANK)\b', 'SHEET', 0.85, 'Thin flat part'),
    (r'\b(PLATE|MOUNTING\s+PLATE|BASE\s+PLATE|COVER\s+PLATE|END\s+PLATE|WEAR\s+PLATE)\b', 'PLATE', 0.90, 'Plate part'),

    # Tubular parts
    (r'\b(TUBE|TUBING|PIPE|CONDUIT|SLEEVE|BUSHING|LINER)\b', 'TUBE', 0.85, 'Tubular part'),

    # Rod/Bar parts (cylindrical or long prismatic)
    (r'\b(ROD|SHAFT|SPINDLE|AXLE|PISTON|PLUNGER|STEM)\b', 'ROD', 0.85, 'Cylindrical rod part'),
    (r'\b(BAR|RAIL|GUIDE|TRACK|RUNNER)\b', 'BAR', 0.80, 'Bar/rail part'),

    # Forgings (complex shapes machined from forging stock)
    (r'\b(FORGING|FORGED|HOUSING|BODY|MANIFOLD|CASE|HOUSING\s+ASSY)\b', 'FORGING', 0.75, 'Forged/machined housing'),
    (r'\b(VALVE\s+BODY|PUMP\s+BODY|ACTUATOR\s+BODY|CYLINDER\s+BODY)\b', 'FORGING', 0.80, 'Valve/pump body'),

    # Castings
    (r'\b(CAST|CASTING|INVESTMENT)\b', 'CASTING', 0.85, 'Cast part'),

    # Structural shapes/extrusions
    (r'\b(ANGLE|CHANNEL|I-?BEAM|T-?SECTION|EXTRUSION|PROFILE)\b', 'SHAPES', 0.85, 'Structural shape'),
    (r'\b(BRACKET|FITTING|GUSSET|CLIP|CLAMP|SUPPORT)\b', 'SHAPES', 0.70, 'Structural fitting'),

    # Wire
    (r'\b(WIRE|CABLE|CONDUCTOR|LEAD|HARNESS)\b', 'WIRE', 0.85, 'Wire/cable'),

    # Strip
    (r'\b(STRIP|BAND|STRAP)\b', 'STRIP', 0.80, 'Strip material'),
]


# =============================================================================
# FORM INFERENCE FROM MATERIAL DESIGNATION
# =============================================================================
# Material designation strings sometimes include form explicitly.

FORM_DESIGNATION_PATTERNS: List[Tuple[str, str, float]] = [
    # Pattern, Form, Confidence
    (r'\bPLATE\b', 'PLATE', 0.95),
    (r'\bSHEET\b', 'SHEET', 0.95),
    (r'\bBAR\b', 'BAR', 0.95),
    (r'\bROD\b', 'ROD', 0.95),
    (r'\bTUBE\b', 'TUBE', 0.95),
    (r'\bTUBING\b', 'TUBE', 0.95),
    (r'\bPIPE\b', 'TUBE', 0.90),
    (r'\bWIRE\b', 'WIRE', 0.95),
    (r'\bFORGING\b', 'FORGING', 0.95),
    (r'\bFORGED\b', 'FORGING', 0.90),
    (r'\bCASTING\b', 'CASTING', 0.95),
    (r'\bCAST\b', 'CASTING', 0.85),
    (r'\bEXTRUSION\b', 'EXTRUSION', 0.95),
    (r'\bEXTRUDED\b', 'EXTRUSION', 0.90),
    (r'\bSHAPES?\b', 'SHAPES', 0.90),
    (r'\bSTRIP\b', 'STRIP', 0.95),
]


# =============================================================================
# AEROSPACE MATERIAL SPEC FORM HINTS
# =============================================================================
# Some material specifications imply a particular form.

SPEC_FORM_HINTS = {
    # AMS specs that imply form
    'AMS 4027': 'SHEET',  # 6061-T6 sheet
    'AMS 4044': 'PLATE',  # 6061-T651 plate
    'AMS 4029': 'PLATE',  # 6061-T6 plate
    'AMS 4045': 'PLATE',  # 6061-T651 plate (thick)
    'AMS 4050': 'PLATE',  # 2024-T3 plate
    'AMS 4037': 'SHEET',  # 2024-T3 sheet
    'AMS 4117': 'BAR',    # 2024-T351 bar
    'AMS 4154': 'BAR',    # 6061-T6 bar
    'AMS 4150': 'BAR',    # 6061-T651 bar
    'AMS 4122': 'BAR',    # 7075-T73 bar
    'AMS 4123': 'FORGING',  # 7075-T73 forging
    'AMS 4134': 'EXTRUSION',  # 7075-T6 extrusion
    'AMS 5643': 'BAR',    # 17-4 PH bar
    'AMS 5659': 'BAR',    # 15-5 PH bar
    'AMS 5737': 'BAR',    # A286 bar
    'AMS 5662': 'BAR',    # Inconel 718 bar
    'AMS 5663': 'FORGING',  # Inconel 718 forging
    # ASTM specs
    'ASTM A276': 'BAR',   # Stainless bar
    'ASTM A564': 'BAR',   # Age-hardening stainless bar
    'ASTM B209': 'SHEET',  # Aluminum sheet/plate (ambiguous)
    'ASTM B211': 'BAR',   # Aluminum bar
    'ASTM B221': 'EXTRUSION',  # Aluminum extrusion
    'ASTM B247': 'FORGING',  # Aluminum forging
}


def infer_material_form(
    nomenclature: str = "",
    part_description: str = "",
    designation: str = "",
    material_spec: str = "",
    existing_form: str = "",
) -> FormInferenceResult:
    """Infer material form from available data.

    Inference priority:
    1. Use existing form if already populated (don't override)
    2. Check material designation for explicit form keywords
    3. Check material spec for form hints
    4. Infer from nomenclature/part description patterns

    Args:
        nomenclature: Part nomenclature (e.g., "SHIM", "ROD CONNECTOR")
        part_description: Part description (e.g., "SKIN, FUSELAGE")
        designation: Material designation (e.g., "6061-T6 ALUMINUM PLATE")
        material_spec: Material spec (e.g., "AMS 4027")
        existing_form: Any existing form value (will be returned if non-empty)

    Returns:
        FormInferenceResult with inferred form and confidence
    """
    # 1. Return existing form if populated
    if existing_form and existing_form.strip():
        existing_clean = existing_form.strip().upper()
        return FormInferenceResult(
            form=existing_clean,
            confidence=1.0,
            source="existing",
            reasoning="Form already specified"
        )

    # Combine nomenclature and description for pattern matching
    combined_desc = f"{nomenclature} {part_description}".upper().strip()
    designation_upper = designation.upper().strip() if designation else ""
    spec_upper = material_spec.upper().strip() if material_spec else ""

    # 2. Check designation for explicit form keywords (highest priority)
    for pattern, form, confidence in FORM_DESIGNATION_PATTERNS:
        if re.search(pattern, designation_upper, re.IGNORECASE):
            return FormInferenceResult(
                form=form,
                confidence=confidence,
                source="designation",
                reasoning=f"Form '{form}' found in material designation"
            )

    # 3. Check material spec for form hints
    for spec_key, form in SPEC_FORM_HINTS.items():
        if spec_key.upper() in spec_upper:
            return FormInferenceResult(
                form=form,
                confidence=0.75,
                source="material_spec",
                reasoning=f"Spec {spec_key} implies {form} form"
            )

    # 4. Infer from nomenclature/part description
    if combined_desc:
        for pattern, form, confidence, reasoning in FORM_NOMENCLATURE_PATTERNS:
            if re.search(pattern, combined_desc, re.IGNORECASE):
                return FormInferenceResult(
                    form=form,
                    confidence=confidence,
                    source="nomenclature",
                    reasoning=reasoning
                )

    # Unable to infer
    return FormInferenceResult(
        form="",
        confidence=0.0,
        source="none",
        reasoning="Unable to infer material form from available data"
    )


def infer_form_for_miul_row(row: dict) -> dict:
    """Apply form inference to a MIUL row dictionary.

    This is a convenience function that extracts relevant fields from a
    MIUL row dict, runs inference, and returns an updated dict with the
    form field populated.

    Args:
        row: MIUL row dictionary with fields like 'nomenclature',
             'part_description', 'designation', 'material_spec', 'form'

    Returns:
        Updated row dictionary with 'form' populated (if inferrable)
    """
    result = infer_material_form(
        nomenclature=row.get("nomenclature", ""),
        part_description=row.get("part_description", ""),
        designation=row.get("designation", ""),
        material_spec=row.get("material_spec", ""),
        existing_form=row.get("form", ""),
    )

    row = dict(row)  # Copy to avoid mutation

    if result.form:
        row["form"] = result.form
        row["_form_inference_source"] = result.source
        row["_form_inference_confidence"] = result.confidence

        if result.source != "existing":
            logger.debug(
                f"[FormInference] {row.get('part_number', 'UNKNOWN')}: "
                f"form='{result.form}' (source={result.source}, "
                f"conf={result.confidence:.2f}, {result.reasoning})"
            )

    return row


def batch_infer_forms(rows: List[dict]) -> Tuple[List[dict], dict]:
    """Apply form inference to a batch of MIUL rows.

    Args:
        rows: List of MIUL row dictionaries

    Returns:
        Tuple of (updated_rows, stats_dict)
    """
    updated = []
    stats = {
        "total": len(rows),
        "already_had_form": 0,
        "inferred_from_designation": 0,
        "inferred_from_spec": 0,
        "inferred_from_nomenclature": 0,
        "unable_to_infer": 0,
    }

    for row in rows:
        result_row = infer_form_for_miul_row(row)
        updated.append(result_row)

        source = result_row.get("_form_inference_source", "none")
        if source == "existing":
            stats["already_had_form"] += 1
        elif source == "designation":
            stats["inferred_from_designation"] += 1
        elif source == "material_spec":
            stats["inferred_from_spec"] += 1
        elif source == "nomenclature":
            stats["inferred_from_nomenclature"] += 1
        else:
            stats["unable_to_infer"] += 1

    logger.info(
        f"[FormInference] Batch stats: {stats['already_had_form']} existing, "
        f"{stats['inferred_from_designation']} from designation, "
        f"{stats['inferred_from_spec']} from spec, "
        f"{stats['inferred_from_nomenclature']} from nomenclature, "
        f"{stats['unable_to_infer']} unresolved"
    )

    return updated, stats


# =============================================================================
# QUICK TEST
# =============================================================================
if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.DEBUG, format="%(message)s")

    test_cases = [
        # (nomenclature, part_desc, designation, spec, existing_form)
        ("SHIM", "SHIM, DOOR", "6061-T6 ALUMINUM", "AMS 4027", ""),
        ("ROD", "ROD CONNECTOR", "A286 CRES BAR", "", ""),
        ("HOUSING", "VALVE BODY", "15-5 PH CRES", "AMS 5659", ""),
        ("", "", "INCONEL 718 FORGING", "AMS 5663", ""),
        ("INSERT", "HELICAL INSERT", "18-8 SS", "", ""),
        ("O-RING", "SEAL, BACKUP", "VITON", "", ""),
        ("SCREW", "FLAT HEAD SCREW", "A286", "", ""),
        ("BRACKET", "MOUNTING BRACKET", "6061-T6 ALUMINUM", "", ""),
        ("TUBE", "FUEL LINE", "304L SS", "", ""),
        ("", "", "7075-T73 PLATE", "", ""),
        ("SKIN", "FUSELAGE SKIN", "2024-T3 ALCLAD", "", ""),
        ("UNKNOWN PART", "", "", "", ""),  # Should fail to infer
        ("TEST", "", "", "", "PLATE"),  # Should keep existing
    ]

    print("=" * 80)
    print("MATERIAL FORM INFERENCE TEST")
    print("=" * 80)

    for nom, desc, desig, spec, existing in test_cases:
        result = infer_material_form(nom, desc, desig, spec, existing)
        print(f"\nInput: nom='{nom}', desc='{desc}', desig='{desig}', spec='{spec}', existing='{existing}'")
        print(f"Result: form='{result.form}', conf={result.confidence:.2f}, source={result.source}")
        print(f"        {result.reasoning}")
