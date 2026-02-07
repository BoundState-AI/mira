#!/usr/bin/env python3
"""
Module: Drawing Parser
Purpose: Multi-pass engineering drawing parser for complete MIUL extraction.

BoundState AI 2025
Version: 1.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Fran OpenAI 5 <noreply@openai.com>
Co-Authored-By: Grok 4.0 <noreply@x.ai>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: SWE-013, SWE-033, NASA-STD-6016 Section 4.1.2
Safety Critical: True
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from pydantic import BaseModel, Field, field_validator
import uuid

__all__ = [
    "DrawingMaterial",
    "EmbeddedHardware",
    "DrawingExtraction",
    "DrawingParserPrompts",
    "HARDWARE_STANDARD_MATERIALS",
    "aggregate_hardware_by_standard",
]

LOGGER = logging.getLogger(__name__)


class MaterialSource(str, Enum):
    """Where material was identified on the drawing."""

    TITLE_BLOCK = "title_block"
    NOTE = "note"
    CALLOUT = "callout"
    BOM = "bill_of_materials"
    INFERRED = "inferred_from_standard"


class DrawingMaterial(BaseModel):
    """A material identified on an engineering drawing.

    Compliance: NASA-STD-6016 Section 4.1.2.3
    """

    model_config = {"extra": "forbid", "populate_by_name": True}

    designation: str = Field(..., description="Material name/designation")
    specification: Optional[str] = Field(None, description="Spec number (AMS, MIL, etc.)")
    uns_number: Optional[str] = Field(None, description="UNS number if present")
    source: MaterialSource = Field(..., description="Where on drawing this was found")
    quantity: int = Field(1, ge=1, description="Quantity of this material usage")
    location_description: Optional[str] = Field(None, description="Where on part")
    raw_text: str = Field(..., description="Original text from drawing")


class EmbeddedHardware(BaseModel):
    """Standard hardware embedded in the drawing (inserts, fasteners, etc.).

    These require separate MUA tracking because their material differs from the parent.
    """

    model_config = {"extra": "forbid", "populate_by_name": True}

    standard: str = Field(..., description="Standard number (NASM33537, NAS1149, etc.)")
    thread_size: Optional[str] = Field(None, description="Thread size if applicable")
    quantity: int = Field(1, ge=1)
    inferred_material: Optional[str] = Field(None, description="Material from standard lookup")
    inferred_spec: Optional[str] = Field(None, description="Material spec from standard lookup")
    raw_callout: str = Field(..., description="Original callout text")
    confidence: float = Field(1.0, ge=0.0, le=1.0, description="Confidence in material inference")

    @field_validator("confidence", mode="after")
    @classmethod
    def validate_confidence_for_inferred(cls, v: float, info: Any) -> float:
        """Reduce confidence if material was inferred from standard."""
        data = info.data
        if data.get("inferred_material") and v == 1.0:
            return 0.85  # Default confidence for standard-based inference
        return v


class DrawingExtraction(BaseModel):
    """Complete extraction result from an engineering drawing.

    Compliance: NASA-STD-6016 MIUL requirements
    """

    model_config = {"extra": "forbid", "populate_by_name": True}

    drawing_number: str = Field(..., description="Drawing number from title block")
    revision: Optional[str] = Field(None, description="Revision letter/number")
    title: Optional[str] = Field(None, description="Part title")
    primary_material: Optional[DrawingMaterial] = Field(
        None, description="Main material from title block"
    )
    subordinate_materials: List[DrawingMaterial] = Field(
        default_factory=list, description="Additional materials from notes/callouts"
    )
    embedded_hardware: List[EmbeddedHardware] = Field(
        default_factory=list, description="Standard hardware requiring separate tracking"
    )
    referenced_standards: List[str] = Field(
        default_factory=list, description="All standards/specs referenced"
    )
    extraction_warnings: List[str] = Field(
        default_factory=list, description="Issues encountered during extraction"
    )

    def all_materials_for_miul(self) -> List[Dict[str, Any]]:
        """Flatten all materials into MIUL line items.

        Returns:
            List of material dictionaries ready for MIUL integration.
        """
        items: List[Dict[str, Any]] = []

        if self.primary_material:
            items.append({
                "material_designation": self.primary_material.designation,
                "material_specification": self.primary_material.specification,
                "source": "primary",
                "quantity": self.primary_material.quantity,
            })

        for mat in self.subordinate_materials:
            items.append({
                "material_designation": mat.designation,
                "material_specification": mat.specification,
                "source": mat.source.value,
                "quantity": mat.quantity,
            })

        for hw in self.embedded_hardware:
            if hw.inferred_material:
                items.append({
                    "material_designation": hw.inferred_material,
                    "material_specification": hw.inferred_spec,
                    "source": f"inferred_from_{hw.standard}",
                    "quantity": hw.quantity,
                    "confidence": hw.confidence,
                    "standard_part_number": hw.standard,
                    "thread_size": hw.thread_size,
                })

        return items


# Hardware standard -> typical material mapping
# These are DEFAULTS - actual material depends on dash number
HARDWARE_STANDARD_MATERIALS: Dict[str, Dict[str, Any]] = {
    # Helical Coil Inserts
    "NASM33537": {
        "material": "CRES 302/304",
        "spec": "AMS 5688 or AMS 5697",
        "description": "Helical coil screw thread insert, free running",
        "confidence": 0.85,
        "note": "Actual material depends on dash number. -1xx series is CRES.",
    },
    "MS33537": {
        "material": "CRES 302/304",
        "spec": "AMS 5688 or AMS 5697",
        "description": "Helical coil screw thread insert (legacy)",
        "confidence": 0.85,
    },
    "NASM33538": {
        "material": "Phosphor Bronze",
        "spec": "QQ-B-750",
        "description": "Helical coil screw thread insert, phosphor bronze",
        "confidence": 0.90,
    },
    "NAS1130": {
        "material": "CRES 302/304",
        "spec": "AMS 5688",
        "description": "Thin wall helical coil inserts",
        "confidence": 0.85,
    },
    "MS124651": {
        "material": "CRES 302/304",
        "spec": "AMS 5688",
        "description": "Helical coil inserts, screw-locking",
        "confidence": 0.85,
    },

    # Key-Locking Inserts
    "MS21209": {
        "material": "CRES 303",
        "spec": "AMS 5640",
        "description": "Key-locking thread insert",
        "confidence": 0.80,
    },

    # Washers
    "NAS1149": {
        "material": "CRES 300 Series or Alloy Steel",
        "spec": "Various per dash number",
        "description": "Flat washer",
        "confidence": 0.70,
        "note": "Material code suffix determines material.",
    },
    "AN960": {
        "material": "Alloy Steel or CRES",
        "spec": "Various",
        "description": "Flat washer",
        "confidence": 0.70,
    },

    # Nuts
    "MS21042": {
        "material": "Alloy Steel or CRES",
        "spec": "Various",
        "description": "Self-locking nut",
        "confidence": 0.70,
    },
    "MS21043": {
        "material": "Alloy Steel or CRES",
        "spec": "Various",
        "description": "Self-locking nut, high temperature",
        "confidence": 0.70,
    },
    "MS21044": {
        "material": "Alloy Steel",
        "spec": "MIL-S-8879",
        "description": "Self-locking nut, thin",
        "confidence": 0.75,
    },

    # Bolts/Screws
    "NAS1351": {
        "material": "Alloy Steel or CRES",
        "spec": "Various per dash number",
        "description": "Socket head cap screw",
        "confidence": 0.70,
    },
    "NAS1352": {
        "material": "A286 CRES",
        "spec": "AMS 5737",
        "description": "Socket head cap screw, high strength",
        "confidence": 0.80,
    },

    # Pins
    "MS16555": {
        "material": "CRES 302/304",
        "spec": "QQ-S-763",
        "description": "Spring pin, slotted",
        "confidence": 0.85,
    },
    "MS16562": {
        "material": "CRES 302/304",
        "spec": "QQ-S-763",
        "description": "Spring pin, coiled",
        "confidence": 0.85,
    },

    # AN Bolts
    "AN3": {
        "material": "Alloy Steel, cadmium plated",
        "spec": "MIL-S-6758",
        "description": "Hex head bolt, 10-32",
        "confidence": 0.80,
    },
    "AN4": {
        "material": "Alloy Steel, cadmium plated",
        "spec": "MIL-S-6758",
        "description": "Hex head bolt, 1/4-28",
        "confidence": 0.80,
    },
    "AN5": {
        "material": "Alloy Steel, cadmium plated",
        "spec": "MIL-S-6758",
        "description": "Hex head bolt, 5/16-24",
        "confidence": 0.80,
    },
    "AN6": {
        "material": "Alloy Steel, cadmium plated",
        "spec": "MIL-S-6758",
        "description": "Hex head bolt, 3/8-24",
        "confidence": 0.80,
    },

    # AN Nuts
    "AN310": {
        "material": "Alloy Steel, cadmium plated",
        "spec": "MIL-N-21840",
        "description": "Castle nut",
        "confidence": 0.80,
    },
    "AN315": {
        "material": "Alloy Steel, cadmium plated",
        "spec": "Various",
        "description": "Plain hex nut",
        "confidence": 0.80,
    },
    "AN316": {
        "material": "CRES 303/304",
        "spec": "AMS 5640",
        "description": "Check nut",
        "confidence": 0.80,
    },
}


@dataclass
class DrawingParserPrompts:
    source: str = ""  # NASA SWE-013 traceability

    """Prompt templates for multi-pass drawing extraction."""

    @staticmethod
    def pass1_title_block() -> str:
        """First pass: Extract title block information."""
        return """Analyze this engineering drawing and extract ONLY the title block information.

Return JSON with these fields:
{
    "drawing_number": "string - the drawing/part number",
    "revision": "string or null - revision letter",
    "title": "string - part name/title",
    "material_line": "string - exact material callout from title block",
    "material_designation": "string - material name (e.g., 'ALUMINUM ALLOY 7075-T6')",
    "material_spec": "string or null - specification (e.g., 'SAE AMS4124')",
    "uns_number": "string or null - UNS number if present"
}

Look in the title block area (typically lower right corner).
Return ONLY valid JSON, no explanation."""

    @staticmethod
    def pass2_embedded_hardware() -> str:
        """Second pass: Find all embedded hardware callouts."""
        return """Analyze this engineering drawing for EMBEDDED HARDWARE that requires separate
material tracking.

Look for callouts containing:
- Thread inserts: "HELICAL COIL INSERT", "NASM33537", "NASM33538"
- Fasteners: "NAS", "MS", "AN" part numbers
- Press-fit items: "DOWEL", "PIN", "BUSHING" with material specs
- Any callout referencing a material DIFFERENT from the title block material

For EACH embedded hardware item found, extract:
{
    "items": [
        {
            "standard": "string - standard number (NASM33537, NAS1149, etc.)",
            "thread_size": "string or null - thread size if applicable",
            "quantity": number - count (look for 'nX' prefix like '4X', '24X')",
            "raw_callout": "string - complete callout text"
        }
    ]
}

CRITICAL: Count ALL instances. If you see "4X .3125-18 UNC-3B HELICAL COIL INSERT"
on one sheet and "6X .3125-18 UNC-3B HELICAL COIL INSERT" on another, report both.

Return ONLY valid JSON array."""

    @staticmethod
    def pass3_referenced_standards() -> str:
        """Third pass: Collect all referenced standards."""
        return """List ALL standards, specifications, and documents referenced on this drawing.

Look for:
- Material specs: AMS, MIL-SPEC, QQ-, ASTM, SAE
- Hardware standards: NASM, NAS, MS, AN
- Process specs: MIL-STD, NASA-STD, ASME
- Drawing standards: ASME Y14.xx

Return JSON:
{
    "standards": ["list", "of", "all", "standards", "found"]
}

Return ONLY valid JSON."""


def aggregate_hardware_by_standard(
    items: List[EmbeddedHardware],
) -> List[EmbeddedHardware]:
    """Aggregate hardware items by standard and thread size for MIUL reporting.

    Multiple callouts of same standard become one line item with total quantity.

    Args:
        items: List of hardware items to aggregate.

    Returns:
        Aggregated list with combined quantities.
    """
    by_key: Dict[Tuple[str, Optional[str]], EmbeddedHardware] = {}

    for item in items:
        key = (item.standard.upper(), item.thread_size)

        if key in by_key:
            by_key[key].quantity += item.quantity
            by_key[key].raw_callout += f"; {item.raw_callout}"
        else:
            by_key[key] = EmbeddedHardware(
                standard=item.standard.upper(),
                thread_size=item.thread_size,
                quantity=item.quantity,
                inferred_material=item.inferred_material,
                inferred_spec=item.inferred_spec,
                raw_callout=item.raw_callout,
                confidence=item.confidence,
            )

    result = list(by_key.values())

    if len(result) < len(items):
        LOGGER.info(
            f"Aggregated {len(items)} hardware callouts into {len(result)} unique types"
        )

    return result


def resolve_hardware_material(hw: EmbeddedHardware) -> None:
    """Look up and set material from hardware standard.

    Args:
        hw: Hardware item to resolve (modified in place).
    """
    std_base = hw.standard.upper()

    # Strip dash numbers for lookup (MS16562-1032 → MS16562)
    # But keep AN bolt suffix (AN4-7A stays AN4)
    if "-" in std_base:
        parts = std_base.split("-")
        # For AN bolts, just take the base (AN4-7A → AN4)
        if parts[0].startswith("AN") and len(parts[0]) <= 5:
            std_base = parts[0]
        # For MS/NAS with long dash numbers, strip them
        elif parts[0].startswith(("MS", "NAS")):
            std_base = parts[0]

    # Normalize NASM vs NAS naming
    if std_base.startswith("NAS") and not std_base.startswith("NASM"):
        # Check if it should be NASM (thread inserts)
        if std_base in ("NAS33537", "NAS33538", "NAS1130"):
            std_base = "NASM" + std_base[3:]

    std_info = HARDWARE_STANDARD_MATERIALS.get(std_base)
    if std_info:
        hw.inferred_material = std_info.get("material")
        hw.inferred_spec = std_info.get("spec")
        hw.confidence = std_info.get("confidence", 0.5)
        LOGGER.debug(
            f"Resolved {hw.standard} -> {hw.inferred_material} "
            f"(confidence: {hw.confidence:.0%})"
        )
    else:
        LOGGER.warning(f"No material mapping for standard: {hw.standard}")
        hw.confidence = 0.0


def check_material_compatibility(
    primary_material: str,
    hardware_items: List[EmbeddedHardware],
) -> List[str]:
    """Check for material compatibility issues.

    Args:
        primary_material: Primary material designation from title block.
        hardware_items: List of embedded hardware with inferred materials.

    Returns:
        List of warning messages for incompatible material combinations.
    """
    warnings: List[str] = []
    primary_upper = primary_material.upper()

    for hw in hardware_items:
        if not hw.inferred_material:
            continue

        inferred_upper = hw.inferred_material.upper()

        # Check aluminum parent with stainless inserts
        if "ALUMINUM" in primary_upper and "CRES" in inferred_upper:
            warnings.append(
                f"Material mismatch: Parent is aluminum but {hw.standard} "
                f"({hw.quantity}X) inserts are typically {hw.inferred_material}. "
                f"Separate MUA tracking required per NASA-STD-6016."
            )

        # Check for dissimilar metals (galvanic corrosion risk)
        if "ALUMINUM" in primary_upper and "STEEL" in inferred_upper:
            if "STAINLESS" not in inferred_upper and "CRES" not in inferred_upper:
                warnings.append(
                    f"Galvanic corrosion risk: Aluminum parent with carbon steel "
                    f"hardware ({hw.standard}). Verify corrosion protection."
                )

    return warnings
