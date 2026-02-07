#!/usr/bin/env python3
"""
Module: Miul To Excel
Purpose: MIUL JSON to MAPTIS Excel Converter.

BoundState AI 2025
Version: 1.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Fran OpenAI 5 <noreply@openai.com>
Co-Authored-By: Grok 4.0 <noreply@x.ai>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: NASA-STD-6016C, SSP 30234
Safety Critical: True
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
import uuid

__all__ = ["json_to_maptis_excel", "MIULToExcelConverter"]
__safety_critical__ = False

logger = logging.getLogger(__name__)


# MAPTIS MIUL column specification - matches DMLLV template.xlsx exactly (38 columns)
# (Header, json_key, column_width)
MAPTIS_COLUMNS = [
    ("Index", "index", 8),
    ("Parent", "parent_index", 8),
    ("Detail Drawing", "part_number", 25),  # Drawing number / part number
    ("Next Assembly", "nha", 20),  # NHA - parent drawing number string
    ("Change Letter", "change_letter", 12),
    ("Drawing Source", "source_drawing", 20),
    ("Material Form", "form", 15),
    ("Material Manufacturer", "manufacturer", 18),
    ("Designation", "designation", 40),
    ("Material Specification", "material_spec", 22),
    ("Process Specification", "process_spec", 30),
    ("Environment", "environment", 18),
    ("Material Code", "material_code", 12),
    ("Standard Part Number", "std_part_number", 20),
    ("Contractor", "contractor", 15),
    ("System", "system", 15),
    ("Subsystem", "subsystem", 15),
    ("Max Temperature", "max_temp", 14),
    ("Min Temperature", "min_temp", 14),
    ("Fluid Type", "fluid_type", 15),
    ("Associate Contractor", "assoc_contractor", 18),
    ("Project", "project", 15),
    ("Document Title", "description", 35),
    ("Criticality", "criticality", 12),
    ("Line Number", "line_number", 12),
    ("Overall Evaluation", "overall_eval", 16),
    ("Configuration Test", "config_test", 16),
    ("Max Pressure", "max_pressure", 12),
    ("Min Pressure", "min_pressure", 12),
    ("MUA Rationale", "mua_rationale", 15),
    ("Cure Codes", "cure_codes", 12),
    ("FLAM", "flamm_rating", 8),
    ("SCC", "scc_rating", 8),
    ("CORR", "corr_rating", 8),
    ("TVS", "tvs_rating", 8),
    ("TOX", "tox_rating", 8),
    ("FS", "fs_rating", 8),
    ("Remarks", "remarks", 40),
]


class MIULToExcelConverter:
    """Converts MIUL extractor v2 JSON to MAPTIS Excel format.

    Matches the exact DMLLV template.xlsx structure:
    - Index starts at 1
    - Parent 0 = top-level assembly
    - Parent column links to parent's Index value
    - Detail Drawing = part/drawing number
    - Next Assembly = NHA (parent drawing number string)
    """

    # Style definitions
    HEADER_FILL = PatternFill(start_color="1F4E79", end_color="1F4E79", fill_type="solid")
    HEADER_FONT = Font(bold=True, color="FFFFFF", size=10)
    ASSEMBLY_FILL = PatternFill(start_color="D6EAF8", end_color="D6EAF8", fill_type="solid")
    HELICOIL_FILL = PatternFill(start_color="E8DAEF", end_color="E8DAEF", fill_type="solid")
    THIN_BORDER = Border(
        left=Side(style="thin"),
        right=Side(style="thin"),
        top=Side(style="thin"),
        bottom=Side(style="thin"),
    )

    def __init__(
        self,
        project_name: str = "",
        contractor: str = "",
        system: str = "",
        subsystem: str = "",
    ):
        """Initialize converter.

        Args:
            project_name: Project name for Project column
            contractor: Contractor name
            system: System name
            subsystem: Subsystem name
        """
        self.project_name = project_name
        self.contractor = contractor
        self.system = system
        self.subsystem = subsystem

    def convert(
        self,
        json_path: Union[str, Path],
        output_path: Optional[Union[str, Path]] = None,
    ) -> Path:
        """Convert extractor v2 JSON to MAPTIS Excel.

        Args:
            json_path: Path to extractor v2 JSON output
            output_path: Output Excel path (default: same name with .xlsx)

        Returns:
            Path to generated Excel file
        """
        json_path = Path(json_path)
        if output_path is None:
            output_path = json_path.with_suffix(".xlsx")
        output_path = Path(output_path)

        # Load JSON
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        # Infer project name from file or metadata
        if not self.project_name:
            self.project_name = data.get("project", json_path.stem.replace("_MIUL", "").replace("_v2", "").replace("_bedrock", ""))

        # Create workbook
        wb = Workbook()
        ws_miul = wb.active
        ws_miul.title = "MIUL"

        # Write MIUL sheet
        self._write_miul_sheet(ws_miul, data)

        # Add summary sheet
        ws_summary = wb.create_sheet("Summary")
        self._write_summary_sheet(ws_summary, data)

        # Add helicoils sheet if present
        helicoils = [m for m in data.get("materials", []) if m.get("is_helicoil")]
        if helicoils:
            ws_helicoils = wb.create_sheet("Helicoils")
            self._write_helicoils_sheet(ws_helicoils, helicoils)

        # Add finishes sheet if present
        finishes = data.get("surface_finishes", []) or data.get("finishes", [])
        if finishes:
            ws_finishes = wb.create_sheet("Surface Finishes")
            self._write_finishes_sheet(ws_finishes, finishes)

        # Save
        wb.save(str(output_path))
        logger.info(f"[MIUL Excel] Wrote {output_path} with {len(data.get('materials', []))} rows")

        return output_path

    def _write_miul_sheet(self, ws, data: Dict[str, Any]) -> None:
        """Write main MIUL data sheet matching template exactly."""
        materials = data.get("materials", [])
        # Note: JSON uses 'surface_finishes' key from extractor
        finishes = data.get("surface_finishes", []) or data.get("finishes", [])

        # Build a finish lookup by source drawing - construct full process spec string
        finish_by_drawing: Dict[str, str] = {}
        for f in finishes:
            src = f.get("source_drawing", "")
            if not src:
                continue

            # Build full process spec: "CHEM FILM PER MIL-DTL-5541, TYPE 1, CLASS 3, YELLOW"
            parts = []
            finish_type = f.get("finish_type", "")
            spec = f.get("spec", "")
            class_info = f.get("class", "")
            color = f.get("color", "")

            if finish_type:
                parts.append(finish_type)
            if spec:
                parts.append(f"PER {spec}")
            if class_info:
                parts.append(class_info)
            if color and color.lower() not in ("not specified", "null", "none", ""):
                parts.append(color)

            if parts:
                finish_by_drawing[src] = ", ".join(parts)

        # Write headers
        for col_idx, (header, _, width) in enumerate(MAPTIS_COLUMNS, start=1):
            cell = ws.cell(row=1, column=col_idx, value=header)
            cell.fill = self.HEADER_FILL
            cell.font = self.HEADER_FONT
            cell.border = self.THIN_BORDER
            cell.alignment = Alignment(horizontal="center", wrap_text=True)
            ws.column_dimensions[get_column_letter(col_idx)].width = width

        # Write material rows
        row_idx = 2
        for mat in materials:
            self._write_material_row(ws, row_idx, mat, finish_by_drawing)
            row_idx += 1

        # Freeze header row
        ws.freeze_panes = "A2"

    def _clean_drawing_name(self, name: str) -> str:
        """Clean up drawing/part number by removing descriptive suffixes.

        Examples:
            "GPE-010-A (TOP PLATE DRAWING)" -> "GPE-010-A"
            "GPE-052-A (Rod Connector Drawing)" -> "GPE-052-A"
        """
        if not name:
            return ""
        # Remove parenthetical descriptions like " (TOP PLATE DRAWING)"
        if " (" in name:
            name = name.split(" (")[0]
        return name.strip()

    def _write_material_row(
        self,
        ws,
        row_idx: int,
        mat: Dict[str, Any],
        finish_by_drawing: Dict[str, str],
    ) -> None:
        """Write single material row matching template columns."""
        is_helicoil = mat.get("is_helicoil", False)
        is_assembly = mat.get("material_type") == "ASSEMBLY"

        # Get and clean the source drawing for finish lookup
        source_drawing_raw = mat.get("source_drawing", "")
        source_drawing = self._clean_drawing_name(source_drawing_raw)

        # Clean up part number - remove descriptive suffixes
        part_number_raw = mat.get("part_number", "")
        part_number = self._clean_drawing_name(part_number_raw)

        for col_idx, (header, key, _) in enumerate(MAPTIS_COLUMNS, start=1):
            # Map JSON keys to template columns
            if header == "Index":
                value = mat.get("index", row_idx - 1)
            elif header == "Parent":
                value = mat.get("parent_index", 0)
            elif header == "Detail Drawing":
                value = part_number
            elif header == "Next Assembly":
                # NHA is the parent drawing number (string), not the index
                value = mat.get("nha", "")
            elif header == "Drawing Source":
                # Clean up source drawing name
                value = source_drawing
            elif header == "Process Specification":
                # Use finish from finishes lookup if available (use raw name for lookup)
                value = mat.get("process_spec", "")
                if not value and source_drawing_raw in finish_by_drawing:
                    value = finish_by_drawing[source_drawing_raw]
            elif header == "Document Title":
                value = mat.get("description", "")
            elif header == "Project":
                value = self.project_name
            elif header == "Contractor":
                value = self.contractor
            elif header == "System":
                value = self.system
            elif header == "Subsystem":
                value = self.subsystem
            elif header == "Remarks" and is_helicoil:
                # Add helicoil details to remarks
                details = mat.get("helicoil_details", {})
                value = f"Thread: {details.get('thread_size', '')} {details.get('thread_class', '')}"
            elif key in mat:
                value = mat[key]
            else:
                value = ""

            cell = ws.cell(row=row_idx, column=col_idx, value=value)
            cell.border = self.THIN_BORDER

            # Apply row highlighting
            if is_helicoil:
                cell.fill = self.HELICOIL_FILL
            elif is_assembly:
                cell.fill = self.ASSEMBLY_FILL

    def _write_summary_sheet(self, ws, data: Dict[str, Any]) -> None:
        """Write summary statistics sheet."""
        ws.column_dimensions["A"].width = 30
        ws.column_dimensions["B"].width = 20

        summary = data.get("summary", {})
        materials = data.get("materials", [])

        rows = [
            ("MIUL Summary", ""),
            ("", ""),
            ("Project", self.project_name),
            ("Generated", datetime.now().strftime("%Y-%m-%d %H:%M")),
            ("Extraction Method", data.get("extraction_method", "unknown")),
            ("API Type", data.get("api_type", "unknown")),
            ("", ""),
            ("Statistics", ""),
            ("Total Materials", summary.get("total_materials", len(materials))),
            ("Total Helicoils", summary.get("total_helicoils", 0)),
            ("Assemblies", summary.get("assemblies", 0)),
            ("Details", summary.get("details", 0)),
            ("Surface Finishes", summary.get("surface_finishes", 0)),
            ("", ""),
            ("Material Types", ""),
        ]

        # Count by material type
        type_counts: Dict[str, int] = {}
        for mat in materials:
            mt = mat.get("material_type", "UNKNOWN")
            type_counts[mt] = type_counts.get(mt, 0) + 1

        for mtype, count in sorted(type_counts.items()):
            rows.append((f"  {mtype}", count))

        # Count unique materials
        rows.append(("", ""))
        rows.append(("Unique Designations", ""))
        designation_counts: Dict[str, int] = {}
        for mat in materials:
            desig = mat.get("designation", "")
            if desig:
                designation_counts[desig] = designation_counts.get(desig, 0) + 1

        for desig, count in sorted(designation_counts.items(), key=lambda x: -x[1])[:15]:
            rows.append((f"  {desig[:40]}", count))

        # Write rows
        for row_idx, (label, value) in enumerate(rows, start=1):
            ws.cell(row=row_idx, column=1, value=label)
            ws.cell(row=row_idx, column=2, value=value)

            if label in ("MIUL Summary", "Statistics", "Material Types", "Unique Designations"):
                ws.cell(row=row_idx, column=1).font = Font(bold=True)

    def _write_helicoils_sheet(self, ws, helicoils: List[Dict[str, Any]]) -> None:
        """Write helicoils detail sheet."""
        headers = [
            "Thread Size", "Spec", "Thread Class", "Quantity",
            "Source Drawing", "Parent (NHA)", "Installations", "Notes"
        ]

        for col_idx, header in enumerate(headers, start=1):
            cell = ws.cell(row=1, column=col_idx, value=header)
            cell.fill = self.HEADER_FILL
            cell.font = self.HEADER_FONT
            ws.column_dimensions[get_column_letter(col_idx)].width = 18

        for row_idx, h in enumerate(helicoils, start=2):
            details = h.get("helicoil_details", {})
            ws.cell(row=row_idx, column=1, value=details.get("thread_size", ""))
            ws.cell(row=row_idx, column=2, value=details.get("spec", ""))
            ws.cell(row=row_idx, column=3, value=details.get("thread_class", ""))
            ws.cell(row=row_idx, column=4, value=h.get("quantity", 0))
            ws.cell(row=row_idx, column=5, value=h.get("source_drawing", ""))
            ws.cell(row=row_idx, column=6, value=h.get("nha", ""))
            ws.cell(row=row_idx, column=7, value=details.get("installations", ""))
            # Individual callout details
            callouts = details.get("individual_callouts", [])
            if callouts:
                notes = "; ".join(f"{c.get('quantity')}x {c.get('location', '')}" for c in callouts if c.get('location'))
                ws.cell(row=row_idx, column=8, value=notes)

    def _write_finishes_sheet(self, ws, finishes: List[Dict[str, Any]]) -> None:
        """Write surface finishes detail sheet."""
        headers = ["Finish Type", "Spec", "Color", "Source Drawing", "Notes"]

        for col_idx, header in enumerate(headers, start=1):
            cell = ws.cell(row=1, column=col_idx, value=header)
            cell.fill = self.HEADER_FILL
            cell.font = self.HEADER_FONT
            ws.column_dimensions[get_column_letter(col_idx)].width = 25

        for row_idx, f in enumerate(finishes, start=2):
            ws.cell(row=row_idx, column=1, value=f.get("finish_type", ""))
            ws.cell(row=row_idx, column=2, value=f.get("spec", ""))
            ws.cell(row=row_idx, column=3, value=f.get("color", ""))
            ws.cell(row=row_idx, column=4, value=f.get("source_drawing", ""))
            ws.cell(row=row_idx, column=5, value=f.get("notes", ""))


def json_to_maptis_excel(
    json_path: Union[str, Path],
    output_path: Optional[Union[str, Path]] = None,
    project_name: str = "",
    contractor: str = "",
    system: str = "",
    subsystem: str = "",
) -> Path:
    """Convert extractor v2 JSON to MAPTIS-compatible Excel.

    Args:
        json_path: Path to miul_extractor_v2 JSON output
        output_path: Output Excel path (default: same name with .xlsx)
        project_name: Project name
        contractor: Contractor name
        system: System name
        subsystem: Subsystem name

    Returns:
        Path to generated Excel file
    """
    converter = MIULToExcelConverter(project_name, contractor, system, subsystem)
    return converter.convert(json_path, output_path)


# =============================================================================
# CLI
# =============================================================================

def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Convert MIUL extractor v2 JSON to MAPTIS Excel format (DMLLV template)"
    )
    parser.add_argument("json_file", type=Path, help="Input JSON file from miul_extractor_v2")
    parser.add_argument("-o", "--output", type=Path, help="Output Excel path")
    parser.add_argument("-p", "--project", default="", help="Project name")
    parser.add_argument("-c", "--contractor", default="", help="Contractor name")
    parser.add_argument("-s", "--system", default="", help="System name")
    parser.add_argument("--subsystem", default="", help="Subsystem name")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    output = json_to_maptis_excel(
        args.json_file,
        args.output,
        project_name=args.project,
        contractor=args.contractor,
        system=args.system,
        subsystem=args.subsystem,
    )
    print(f"Generated: {output}")


if __name__ == "__main__":
    main()
