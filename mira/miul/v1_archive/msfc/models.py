#!/usr/bin/env python3
"""
Module: Models
Purpose: [Automatically migrated - needs manual review]

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
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, field_validator

__all__ = [
    "MaterialSource",
    "DrawingType",
    "DrawingMaterial",
    "EmbeddedHardware",
    "DrawingExtraction",
    "AssemblyNode",
    "DrawingTreeExtraction",
    "MIULLineItem",
    "MIULDocument",
    "HARDWARE_STANDARD_MATERIALS",
]

logger = logging.getLogger(__name__)


class MaterialSource(str, Enum):
    """Where material was identified on the drawing."""

    TITLE_BLOCK = "title_block"
    NOTE = "note"
    CALLOUT = "callout"
    BOM = "bill_of_materials"
    INFERRED = "inferred_from_standard"


class DrawingType(str, Enum):
    """Types of engineering drawings per ASME Y14.24."""

    DRAWING_TREE = "drawing_tree"
    DETAIL = "detail"
    ASSEMBLY = "assembly"
    SUBASSEMBLY = "subassembly"
    INSTALLATION = "installation"
    WELDMENT = "weldment"
    SCHEMATIC = "schematic"
    UNKNOWN = "unknown"


# =============================================================================
# Hardware Standard Material Lookup
# =============================================================================

HARDWARE_STANDARD_MATERIALS: dict[str, dict[str, Any]] = {
    # Helical coil inserts - NASM standards
    "NASM33537": {
        "material": "CRES 302/304",
        "spec": "AMS 5688 or AMS 5697",
        "description": "Helical coil screw thread insert, free running",
        "confidence": 0.85,
        "note": "Actual material depends on dash number. -1xx series is CRES.",
    },
    "NASM33538": {
        "material": "Phosphor Bronze",
        "spec": "QQ-B-750",
        "description": "Helical coil screw thread insert, phosphor bronze",
        "confidence": 0.90,
    },
    "NASM33540": {
        "material": "CRES 302/304",
        "spec": "AMS 5688",
        "description": "Helical coil insert, screw-locking",
        "confidence": 0.85,
    },
    # Helical coil inserts - HCC (Heli-Coil Corporation) brand
    # Format: HCC-XXX-YY-ZZZ where XXX=size, YY=pitch, ZZZ=length
    "HCC": {
        "material": "CRES 302/304",
        "spec": "AMS 5688",
        "description": "Heli-Coil brand helical insert (18-8 SS unless marked)",
        "confidence": 0.90,
        "note": "18-8 SS = CRES 302/304 (18% Cr, 8% Ni)",
    },
    # Washers
    "NAS1149": {
        "material": "CRES 300 Series or Alloy Steel",
        "spec": "Various per dash number",
        "description": "Flat washer",
        "confidence": 0.70,
        "note": "Material code suffix determines material.",
    },
    "NAS1515": {
        "material": "CRES 300 Series",
        "spec": "AMS 5510",
        "description": "Washer, flat, corrosion resistant steel",
        "confidence": 0.85,
    },
    # Nuts
    "MS21042": {
        "material": "Alloy Steel or CRES",
        "spec": "Various per dash number",
        "description": "Nut, self-locking, plate",
        "confidence": 0.70,
    },
    "MS21043": {
        "material": "Alloy Steel, Cadmium Plated",
        "spec": "MIL-N-25027",
        "description": "Nut, self-locking, high temperature",
        "confidence": 0.75,
    },
    "MS21044": {
        "material": "CRES A-286",
        "spec": "AMS 5525 or AMS 5726",
        "description": "Nut, self-locking, high strength",
        "confidence": 0.80,
    },
    # Bolts
    "NAS1351": {
        "material": "A-286",
        "spec": "AMS 5525 / AMS 5726",
        "description": "Bolt, internal wrenching, corrosion resistant",
        "confidence": 0.90,
    },
    "NAS1352": {
        "material": "A-286",
        "spec": "AMS 5525 / AMS 5726",
        "description": "Bolt, internal wrenching, NAS close tolerance",
        "confidence": 0.90,
    },
    # Pins
    "MS16555": {
        "material": "CRES 300 Series",
        "spec": "QQ-S-763",
        "description": "Pin, spring, slotted",
        "confidence": 0.80,
    },
    "NAS561": {
        "material": "CRES 302/304",
        "spec": "AMS 5639",
        "description": "Pin, straight, headless",
        "confidence": 0.85,
    },
    # Rivets
    "MS20470": {
        "material": "Aluminum 2117-T4",
        "spec": "QQ-A-430",
        "description": "Rivet, solid, universal head",
        "confidence": 0.85,
    },
    # O-rings and seals (placeholder - material varies widely)
    "AS568": {
        "material": "VARIES - Check dash number",
        "spec": "Various elastomer specs",
        "description": "O-ring, standard sizes",
        "confidence": 0.30,
        "note": "Material depends entirely on dash number suffix.",
    },
}


# =============================================================================
# Drawing Material Models
# =============================================================================

class DrawingMaterial(BaseModel):
    """A material identified on an engineering drawing.

    Compliance: NASA-STD-6016 Section 4.1.2.3
    """

    model_config = {"extra": "forbid", "populate_by_name": True}

    designation: str = Field(..., description="Material name/designation")
    specification: str | None = Field(None, description="Spec number (AMS, MIL, etc.)")
    uns_number: str | None = Field(None, description="UNS number if present")
    source: MaterialSource = Field(..., description="Where on drawing this was found")
    quantity: int = Field(1, ge=1, description="Quantity of this material usage")
    location_description: str | None = Field(None, description="Where on part")
    raw_text: str = Field("", description="Original text from drawing")


class EmbeddedHardware(BaseModel):
    """Standard hardware embedded in the drawing (inserts, fasteners, etc.).

    These require separate MUA tracking because their material differs from parent.
    """

    model_config = {"extra": "forbid", "populate_by_name": True}

    standard: str = Field(..., description="Standard number (NASM33537, NAS1149, etc.)")
    thread_size: str | None = Field(None, description="Thread size if applicable")
    quantity: int = Field(1, ge=1)
    inferred_material: str | None = Field(None, description="Material from standard lookup")
    inferred_spec: str | None = Field(None, description="Material spec from standard lookup")
    raw_callout: str = Field("", description="Original callout text")
    confidence: float = Field(1.0, ge=0.0, le=1.0)

    def resolve_material(self) -> None:
        """Look up material from hardware standard database."""
        import re
        std_base = self.standard.upper()

        # Handle HCC helicoil format: HCC-138-40-138
        # These are Heli-Coil Corporation part numbers (letters-only prefix)
        if std_base.startswith("HCC"):
            std_base = "HCC"
        else:
            # Strip dash number suffix (e.g., NAS1351-3-8 -> NAS1351)
            # Dash numbers indicate size/length, not material
            base_match = re.match(r"^([A-Z]+\d+)", std_base)
            if base_match:
                std_base = base_match.group(1)

        # Normalize NAS -> NASM for inserts
        if std_base.startswith("NAS") and not std_base.startswith("NASM"):
            # Check if it's actually a NASM standard
            nasm_key = "NASM" + std_base[3:]
            if nasm_key in HARDWARE_STANDARD_MATERIALS:
                std_base = nasm_key

        std_info = HARDWARE_STANDARD_MATERIALS.get(std_base)
        if std_info:
            self.inferred_material = std_info.get("material")
            self.inferred_spec = std_info.get("spec")
            self.confidence = std_info.get("confidence", 0.5)
        else:
            logger.warning(f"No material mapping for standard: {self.standard}")
            self.confidence = 0.0


# =============================================================================
# Drawing Extraction Models
# =============================================================================

class DrawingExtraction(BaseModel):
    """Complete extraction result from an engineering drawing.

    Compliance: NASA-STD-6016 MIUL requirements
    """

    model_config = {"extra": "forbid", "populate_by_name": True}

    drawing_number: str = Field(..., description="Drawing number from title block")
    revision: str | None = Field(None, description="Revision letter/number")
    title: str | None = Field(None, description="Part title")
    cage_code: str | None = Field(None, description="CAGE code (e.g., 339B2)")

    primary_material: DrawingMaterial | None = Field(
        None, description="Main material from title block"
    )
    subordinate_materials: list[DrawingMaterial] = Field(
        default_factory=list, description="Additional materials from notes/callouts"
    )
    embedded_hardware: list[EmbeddedHardware] = Field(
        default_factory=list, description="Standard hardware requiring separate tracking"
    )
    referenced_standards: list[str] = Field(
        default_factory=list, description="All standards/specs referenced"
    )
    process_specs: list[str] = Field(
        default_factory=list, description="Process specifications (finishes, etc.)"
    )

    # Metadata
    sheet_count: int = Field(1, ge=1)
    calc_weight_lbs: float | None = Field(None, description="Calculated weight from title block")
    drawing_type: DrawingType = Field(DrawingType.UNKNOWN)

    extraction_warnings: list[str] = Field(default_factory=list)

    def all_materials_for_miul(self) -> list[dict[str, Any]]:
        """Flatten all materials into MIUL line items."""
        items: list[dict[str, Any]] = []

        if self.primary_material:
            items.append({
                "material_designation": self.primary_material.designation,
                "material_specification": self.primary_material.specification,
                "source": "primary",
                "quantity": self.primary_material.quantity,
                "confidence": 1.0,
            })

        for mat in self.subordinate_materials:
            items.append({
                "material_designation": mat.designation,
                "material_specification": mat.specification,
                "source": mat.source.value,
                "quantity": mat.quantity,
                "confidence": 1.0,
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
                })

        return items


# =============================================================================
# Drawing Tree Models
# =============================================================================

class AssemblyNode(BaseModel):
    """A node in the assembly hierarchy extracted from a Drawing Tree."""

    model_config = {"extra": "forbid", "populate_by_name": True}

    drawing_number: str = Field(..., description="Drawing/part number")
    title: str = Field("", description="Part title from DT")
    parent_drawing: str | None = Field(None, description="Parent assembly drawing number")
    children: list[str] = Field(default_factory=list, description="Child drawing numbers")
    level: int = Field(0, ge=0, description="Depth in assembly tree (0 = top)")
    drawing_type: DrawingType = Field(DrawingType.UNKNOWN)

    # Populated when detail drawing is parsed
    materials_extracted: bool = Field(False)
    primary_material: str | None = Field(None)
    embedded_hardware_count: int = Field(0)


class DrawingTreeExtraction(BaseModel):
    """Complete extraction from a Drawing Tree."""

    model_config = {"extra": "forbid", "populate_by_name": True}

    dt_drawing_number: str = Field(..., description="The DT drawing number itself")
    top_assembly: str = Field(..., description="Top-level assembly drawing number")
    total_weight_lbs: float | None = Field(None)
    nodes: dict[str, AssemblyNode] = Field(
        default_factory=dict, description="All nodes keyed by drawing number"
    )
    extraction_warnings: list[str] = Field(default_factory=list)

    def get_all_detail_drawings(self) -> list[str]:
        """Get list of all drawings that need material extraction."""
        return [
            num for num, node in self.nodes.items()
            if node.drawing_type in (DrawingType.DETAIL, DrawingType.UNKNOWN)
        ]

    def get_assembly_path(self, drawing_number: str) -> list[str]:
        """Get path from top assembly to a specific drawing."""
        path: list[str] = []
        current = drawing_number

        while current:
            path.append(current)
            node = self.nodes.get(current)
            if node and node.parent_drawing:
                current = node.parent_drawing
            else:
                break

        return list(reversed(path))

    def get_children_recursive(self, drawing_number: str) -> list[str]:
        """Get all descendants of a drawing."""
        result: list[str] = []
        node = self.nodes.get(drawing_number)
        if not node:
            return result

        for child in node.children:
            result.append(child)
            result.extend(self.get_children_recursive(child))

        return result


# =============================================================================
# MIUL Models
# =============================================================================

class MIULLineItem(BaseModel):
    """Single line item for MIUL per NASA-STD-6016 Section 4.1.2.3."""

    model_config = {"extra": "forbid", "populate_by_name": True}

    # Required fields per NASA-STD-6016
    detail_drawing: str = Field(..., alias="detailDrawing")
    next_assembly: str | None = Field(None, alias="nextAssembly")
    material_designation: str = Field(..., alias="materialDesignation")
    material_specification: str | None = Field(None, alias="materialSpecification")
    material_form: str | None = Field(None, alias="materialForm")
    material_manufacturer: str | None = Field(None, alias="materialManufacturer")

    # Standard part info (for inserts, fasteners, etc.)
    standard_part_number: str | None = Field(None, alias="standardPartNumber")

    # Environment (populated from usage context)
    environment: str | None = Field(None)
    max_temperature_f: float | None = Field(None, alias="maxTemperatureF")
    min_temperature_f: float | None = Field(None, alias="minTemperatureF")
    max_pressure_psia: float | None = Field(None, alias="maxPressurePsia")
    fluid_type: str | None = Field(None, alias="fluidType")

    # MAPTIS integration
    maptis_material_code: str | None = Field(None, alias="maptisMaterialCode")
    mua_number: str | None = Field(None, alias="muaNumber")
    materials_rating: str | None = Field(None, alias="materialsRating")

    # Tracking
    quantity: int = Field(1, ge=1)
    line_number: int | None = Field(None, alias="lineNumber")
    source: str = Field("drawing_extraction")
    confidence: float = Field(1.0, ge=0.0, le=1.0)
    remarks: str | None = Field(None)


class MIULDocument(BaseModel):
    """Complete MIUL document structure per NASA-STD-6016."""

    model_config = {"extra": "forbid", "populate_by_name": True}

    # Header info
    project: str = Field(...)
    top_assembly: str = Field(..., alias="topAssembly")
    contractor: str | None = Field(None)
    system: str | None = Field(None)
    subsystem: str | None = Field(None)
    document_title: str | None = Field(None, alias="documentTitle")

    # Line items
    line_items: list[MIULLineItem] = Field(default_factory=list, alias="lineItems")

    # Tracking
    drawings_processed: list[str] = Field(default_factory=list)
    drawings_pending: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

    def material_summary(self) -> dict[str, int]:
        """Summarize materials by designation."""
        summary: dict[str, int] = {}
        for item in self.line_items:
            mat = item.material_designation
            summary[mat] = summary.get(mat, 0) + item.quantity
        return dict(sorted(summary.items(), key=lambda x: -x[1]))

    def missing_maptis_codes(self) -> list[MIULLineItem]:
        """Find line items without MAPTIS codes."""
        return [item for item in self.line_items if not item.maptis_material_code]

    def assign_line_numbers(self) -> None:
        """Assign sequential line numbers to all items."""
        for i, item in enumerate(self.line_items, start=1):
            item.line_number = i
