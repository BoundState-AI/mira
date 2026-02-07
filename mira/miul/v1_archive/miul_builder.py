#!/usr/bin/env python3
"""
Module: Miul Builder
Purpose: miul_builder.py

BoundState AI 2025
Version: 1.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Fran OpenAI 5 <noreply@openai.com>
Co-Authored-By: Grok 4.0 <noreply@x.ai>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: SWE-013, SWE-033, NASA-STD-6016 Section 4.1.2.3
Safety Critical: True
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import uuid

from .msfc.models import (
    DrawingExtraction,
    DrawingTreeExtraction,
    DrawingType,
    MIULDocument,
    MIULLineItem,
)

__all__ = ["MIULBuilder", "MIULExporter"]

logger = logging.getLogger(__name__)


@dataclass
class MIULBuilder:
    """Builds MIUL from Drawing Tree and detail drawing extractions."""

    dt: DrawingTreeExtraction
    project: str = "DMLLV"
    contractor: str | None = None
    system: str | None = None
    subsystem: str | None = None

    _extractions: dict[str, DrawingExtraction] = field(default_factory=dict, init=False)
    _miul: MIULDocument = field(init=False)
    source: str = ""  # NASA SWE-013 traceability


    def __post_init__(self) -> None:
        """Initialize MIUL document."""
        self._miul = MIULDocument(
            project=self.project,
            top_assembly=self.dt.top_assembly,
            contractor=self.contractor,
            system=self.system,
            subsystem=self.subsystem,
            document_title=f"MIUL for {self.dt.top_assembly}",
            drawings_pending=list(self.dt.nodes.keys()),
        )

    def add_extraction(self, extraction: DrawingExtraction) -> int:
        """Add a parsed detail drawing to the MIUL.

        Args:
            extraction: Extraction result from a detail drawing.

        Returns:
            Number of line items added.
        """
        dwg_num = extraction.drawing_number
        self._extractions[dwg_num] = extraction

        # Get parent from DT
        node = self.dt.nodes.get(dwg_num)
        parent = node.parent_drawing if node else None

        items_added = 0

        # Add primary material
        if extraction.primary_material:
            self._miul.line_items.append(
                MIULLineItem(
                    detail_drawing=dwg_num,
                    next_assembly=parent,
                    material_designation=extraction.primary_material.designation,
                    material_specification=extraction.primary_material.specification,
                    source="title_block",
                    confidence=1.0,
                )
            )
            items_added += 1

        # Add subordinate materials
        for mat in extraction.subordinate_materials:
            self._miul.line_items.append(
                MIULLineItem(
                    detail_drawing=dwg_num,
                    next_assembly=parent,
                    material_designation=mat.designation,
                    material_specification=mat.specification,
                    source=mat.source.value,
                    quantity=mat.quantity,
                    confidence=1.0,
                )
            )
            items_added += 1

        # Add embedded hardware materials
        for hw in extraction.embedded_hardware:
            if hw.inferred_material:
                self._miul.line_items.append(
                    MIULLineItem(
                        detail_drawing=dwg_num,
                        next_assembly=parent,
                        material_designation=hw.inferred_material,
                        material_specification=hw.inferred_spec,
                        standard_part_number=hw.standard,
                        quantity=hw.quantity,
                        source=f"inferred_from_{hw.standard}",
                        confidence=hw.confidence,
                        remarks=f"{hw.quantity}x {hw.standard} {hw.thread_size or ''} inserts",
                    )
                )
                items_added += 1

        # Propagate warnings
        self._miul.warnings.extend(extraction.extraction_warnings)

        # Update tracking
        if dwg_num in self._miul.drawings_pending:
            self._miul.drawings_pending.remove(dwg_num)
        if dwg_num not in self._miul.drawings_processed:
            self._miul.drawings_processed.append(dwg_num)

        # Update DT node
        if node:
            node.materials_extracted = True
            if extraction.primary_material:
                node.primary_material = extraction.primary_material.designation
            node.embedded_hardware_count = len(extraction.embedded_hardware)

        logger.info(f"Added {items_added} line items from {dwg_num}")
        return items_added

    def get_miul(self) -> MIULDocument:
        """Get the current MIUL document."""
        return self._miul

    def get_status(self) -> dict[str, Any]:
        """Get extraction progress status."""
        total = len(self.dt.nodes)
        done = len(self._miul.drawings_processed)
        pending = len(self._miul.drawings_pending)

        return {
            "project": self.project,
            "top_assembly": self.dt.top_assembly,
            "total_drawings": total,
            "processed": done,
            "pending": pending,
            "percent_complete": round(100 * done / total, 1) if total > 0 else 0,
            "line_items": len(self._miul.line_items),
            "unique_materials": len(self._miul.material_summary()),
            "warnings": len(self._miul.warnings),
        }

    def get_pending_drawings(self) -> list[str]:
        """Get list of drawings still needing extraction."""
        return self._miul.drawings_pending.copy()

    def get_material_summary(self) -> dict[str, dict[str, Any]]:
        """Get detailed summary of all materials.

        Returns:
            Dict mapping material designation to usage info.
        """
        summary: dict[str, dict[str, Any]] = {}

        for item in self._miul.line_items:
            mat = item.material_designation
            if mat not in summary:
                summary[mat] = {
                    "total_quantity": 0,
                    "specifications": set(),
                    "drawings": set(),
                    "sources": set(),
                    "has_low_confidence": False,
                }

            summary[mat]["total_quantity"] += item.quantity
            if item.material_specification:
                summary[mat]["specifications"].add(item.material_specification)
            summary[mat]["drawings"].add(item.detail_drawing)
            summary[mat]["sources"].add(item.source)
            if item.confidence < 0.8:
                summary[mat]["has_low_confidence"] = True

        # Convert sets to lists for JSON serialization
        for mat in summary:
            summary[mat]["specifications"] = list(summary[mat]["specifications"])
            summary[mat]["drawings"] = list(summary[mat]["drawings"])
            summary[mat]["sources"] = list(summary[mat]["sources"])

        return summary

    def finalize(self) -> MIULDocument:
        """Finalize MIUL: assign line numbers and validate.

        Returns:
            Finalized MIUL document.
        """
        self._miul.assign_line_numbers()

        # Add final warning if drawings still pending
        if self._miul.drawings_pending:
            self._miul.warnings.append(
                f"{len(self._miul.drawings_pending)} drawings not yet processed: "
                f"{', '.join(self._miul.drawings_pending[:5])}"
                + ("..." if len(self._miul.drawings_pending) > 5 else "")
            )

        return self._miul


class MIULExporter:
    """Export MIUL to various formats."""

    @staticmethod
    def to_json(miul: MIULDocument, path: Path) -> None:
        """Export MIUL to JSON file.

        Args:
            miul: MIUL document to export.
            path: Output file path.
        """
        data = miul.model_dump(by_alias=True)
        data["export_timestamp"] = datetime.now().isoformat()

        with open(path, "w") as f:
            json.dump(data, f, indent=2)

        logger.info(f"Exported MIUL to {path}")

    @staticmethod
    def to_csv(miul: MIULDocument, path: Path) -> None:
        """Export MIUL line items to CSV.

        Args:
            miul: MIUL document to export.
            path: Output file path.
        """
        import csv

        fieldnames = [
            "lineNumber", "detailDrawing", "nextAssembly",
            "materialDesignation", "materialSpecification",
            "standardPartNumber", "quantity", "source",
            "confidence", "remarks",
        ]

        with open(path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()

            for item in miul.line_items:
                writer.writerow({
                    "lineNumber": item.line_number,
                    "detailDrawing": item.detail_drawing,
                    "nextAssembly": item.next_assembly or "",
                    "materialDesignation": item.material_designation,
                    "materialSpecification": item.material_specification or "",
                    "standardPartNumber": item.standard_part_number or "",
                    "quantity": item.quantity,
                    "source": item.source,
                    "confidence": item.confidence,
                    "remarks": item.remarks or "",
                })

        logger.info(f"Exported {len(miul.line_items)} line items to {path}")

    @staticmethod
    def to_maptis_format(miul: MIULDocument, path: Path) -> None:
        """Export MIUL in MAPTIS-compatible format.

        Per NASA-STD-6016: 'A copy of the stored data shall be provided to NASA
        in a form compatible with the Materials and Processes Technical Information
        System (MAPTIS)'

        Args:
            miul: MIUL document to export.
            path: Output file path.
        """
        # MAPTIS expects specific column ordering
        import csv

        fieldnames = [
            "LINE_NUMBER",
            "DETAIL_DRAWING",
            "NEXT_ASSEMBLY",
            "MATERIAL_DESIGNATION",
            "MATERIAL_SPECIFICATION",
            "MATERIAL_CODE",  # MAPTIS code - to be filled by MAPTIS lookup
            "MATERIAL_FORM",
            "MATERIAL_MANUFACTURER",
            "STANDARD_PART_NUMBER",
            "ENVIRONMENT",
            "MAX_TEMP_F",
            "MIN_TEMP_F",
            "MAX_PRESSURE_PSIA",
            "FLUID_TYPE",
            "QUANTITY",
            "MUA_NUMBER",
            "MATERIALS_RATING",
            "REMARKS",
        ]

        with open(path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()

            for item in miul.line_items:
                writer.writerow({
                    "LINE_NUMBER": item.line_number or "",
                    "DETAIL_DRAWING": item.detail_drawing,
                    "NEXT_ASSEMBLY": item.next_assembly or "",
                    "MATERIAL_DESIGNATION": item.material_designation,
                    "MATERIAL_SPECIFICATION": item.material_specification or "",
                    "MATERIAL_CODE": item.maptis_material_code or "",
                    "MATERIAL_FORM": item.material_form or "",
                    "MATERIAL_MANUFACTURER": item.material_manufacturer or "",
                    "STANDARD_PART_NUMBER": item.standard_part_number or "",
                    "ENVIRONMENT": item.environment or "",
                    "MAX_TEMP_F": item.max_temperature_f or "",
                    "MIN_TEMP_F": item.min_temperature_f or "",
                    "MAX_PRESSURE_PSIA": item.max_pressure_psia or "",
                    "FLUID_TYPE": item.fluid_type or "",
                    "QUANTITY": item.quantity,
                    "MUA_NUMBER": item.mua_number or "",
                    "MATERIALS_RATING": item.materials_rating or "",
                    "REMARKS": item.remarks or "",
                })

        logger.info(f"Exported MAPTIS-format MIUL to {path}")

    @staticmethod
    def summary_report(miul: MIULDocument) -> str:
        """Generate human-readable summary report.

        Args:
            miul: MIUL document.

        Returns:
            Formatted summary string.
        """
        lines = [
            "=" * 60,
            f"MIUL SUMMARY REPORT",
            f"Project: {miul.project}",
            f"Top Assembly: {miul.top_assembly}",
            "=" * 60,
            "",
            f"Total Line Items: {len(miul.line_items)}",
            f"Drawings Processed: {len(miul.drawings_processed)}",
            f"Drawings Pending: {len(miul.drawings_pending)}",
            "",
            "MATERIAL SUMMARY:",
            "-" * 40,
        ]

        for mat, count in miul.material_summary().items():
            lines.append(f"  {mat}: {count} usage(s)")

        if miul.warnings:
            lines.extend([
                "",
                "WARNINGS:",
                "-" * 40,
            ])
            for warn in miul.warnings:
                lines.append(f"  ⚠ {warn}")

        missing_maptis = miul.missing_maptis_codes()
        if missing_maptis:
            lines.extend([
                "",
                f"ITEMS MISSING MAPTIS CODES: {len(missing_maptis)}",
                "-" * 40,
            ])
            for item in missing_maptis[:10]:
                lines.append(f"  - {item.material_designation} ({item.detail_drawing})")
            if len(missing_maptis) > 10:
                lines.append(f"  ... and {len(missing_maptis) - 10} more")

        lines.append("")
        lines.append("=" * 60)

        return "\n".join(lines)
