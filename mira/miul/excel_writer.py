#!/usr/bin/env python3
"""
Module: Excel Writer
Purpose: MIUL Excel writer for MAPTIS import format.

BoundState AI 2025
Version: 1.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Fran OpenAI 5 <noreply@openai.com>
Co-Authored-By: Grok 4.0 <noreply@x.ai>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: SWE-013 (Data requirements), SWE-033 (Requirements Traceability)
Safety Critical: True
"""

from __future__ import annotations

import logging
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import List, Tuple, Union

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from .schema import MIULDocument, MIULRow, MIULTree
import uuid

__all__ = [
    "write_miul_excel",
    "MIULExcelWriter",
    "MIUL_COLUMNS",
]

__safety_critical__ = False  # Output formatting, not decision logic

logger = logging.getLogger(__name__)


# MIUL column specification per MAPTIS import spec
# (Header, attribute_name, column_width)
MIUL_COLUMNS: List[Tuple[str, str, int]] = [
    ("Index", "index", 8),
    ("Parent", "parent", 8),
    ("Part Number", "part_number", 20),
    ("Part Description", "part_description", 40),
    ("NHA", "nha", 20),
    ("Criticality", "criticality", 12),
    ("Drawing Source", "drawing_source", 20),
    ("Drawing Rev", "drawing_rev", 10),
    ("Material Code", "material_code", 15),
    ("Designation", "designation", 30),
    ("Material Spec", "material_spec", 20),
    ("Manufacturer", "manufacturer", 20),
    ("CAGE Code", "cage_code", 12),
    ("Quantity", "quantity", 10),
    ("Usage Code", "usage_code", 12),
    ("FLAM", "flam_rating", 8),
    ("SCC", "scc_rating", 8),
    ("CORR", "corr_rating", 8),
    ("TVS", "tvs_rating", 8),
    ("TOX", "tox_rating", 8),
    ("FS", "fs_rating", 8),
    ("MUA", "mua_number", 15),
    ("Rat Code", "rationale_code", 12),
    ("Rat Text", "rationale_text", 40),
    ("Program", "program", 15),
    ("End Item", "end_item", 15),
    ("Config Status", "configuration_status", 15),
    ("Application", "application", 20),
    ("Source File", "source_file", 25),
    ("Source", "source", 15),
]


class MIULExcelWriter:
    """Writes MIUL data to Excel format per MAPTIS spec.

    Compliance: SWE-013
    """

    # Style definitions
    HEADER_FILL = PatternFill(start_color="4472C4", end_color="4472C4", fill_type="solid")
    HEADER_FONT = Font(bold=True, color="FFFFFF")
    CRIT_1_FILL = PatternFill(start_color="FF6B6B", end_color="FF6B6B", fill_type="solid")
    CRIT_2_FILL = PatternFill(start_color="FFE066", end_color="FFE066", fill_type="solid")
    GAP_FILL = PatternFill(start_color="FFA500", end_color="FFA500", fill_type="solid")
    THIN_BORDER = Border(
        left=Side(style="thin"),
        right=Side(style="thin"),
        top=Side(style="thin"),
        bottom=Side(style="thin"),
    )

    def __init__(self, highlight_gaps: bool = True, highlight_critical: bool = True):
        """Initialize writer with formatting options.

        Args:
            highlight_gaps: Highlight rating gaps (U, I, X) in orange
            highlight_critical: Highlight Category 1/2 items in red/yellow
        """
        self.highlight_gaps = highlight_gaps
        self.highlight_critical = highlight_critical

    def write(self, document: MIULDocument, output: Union[Path, BytesIO]) -> None:
        """Write MIUL document to Excel file.

        Args:
            document: MIULDocument to write
            output: File path or BytesIO buffer
        """
        wb = Workbook()

        # Main MIUL sheet
        ws_miul = wb.active
        ws_miul.title = "MIUL"
        self._write_miul_sheet(ws_miul, document)

        # Summary sheet
        ws_summary = wb.create_sheet("Summary")
        self._write_summary_sheet(ws_summary, document)

        # Validation sheet
        ws_validation = wb.create_sheet("Validation")
        self._write_validation_sheet(ws_validation, document)

        if isinstance(output, BytesIO):
            wb.save(output)
        else:
            wb.save(str(output))

        logger.info("[MIUL Excel] Wrote MIUL with %d rows", len(document.tree.rows))

    def _write_miul_sheet(self, ws, document: MIULDocument) -> None:
        """Write main MIUL data sheet."""
        # Write headers
        for col_idx, (header, _, width) in enumerate(MIUL_COLUMNS, start=1):
            cell = ws.cell(row=1, column=col_idx, value=header)
            cell.fill = self.HEADER_FILL
            cell.font = self.HEADER_FONT
            cell.border = self.THIN_BORDER
            cell.alignment = Alignment(horizontal="center")
            ws.column_dimensions[get_column_letter(col_idx)].width = width

        # Write data rows
        for row_idx, miul_row in enumerate(document.tree.rows, start=2):
            self._write_data_row(ws, row_idx, miul_row, document)

        # Freeze header row
        ws.freeze_panes = "A2"

    def _write_data_row(
        self, ws, row_idx: int, miul_row: MIULRow, document: MIULDocument
    ) -> None:
        """Write single data row with conditional formatting."""
        for col_idx, (_, attr, _) in enumerate(MIUL_COLUMNS, start=1):
            value = getattr(miul_row, attr, None)

            # Handle enums
            if hasattr(value, "value"):
                value = value.value

            # Handle None for EOF row
            if miul_row.index == -1 and attr not in ("index", "parent"):
                value = ""

            cell = ws.cell(row=row_idx, column=col_idx, value=value)
            cell.border = self.THIN_BORDER

            # Apply conditional highlighting
            if self.highlight_critical and miul_row.criticality:
                if miul_row.criticality.category == 1:
                    cell.fill = self.CRIT_1_FILL
                elif miul_row.criticality.category == 2:
                    cell.fill = self.CRIT_2_FILL

            # Highlight rating gaps
            if self.highlight_gaps and attr.endswith("_rating"):
                if value in (None, "", "U", "I", "X"):
                    cell.fill = self.GAP_FILL

    def _write_summary_sheet(self, ws, document: MIULDocument) -> None:
        """Write summary statistics sheet."""
        ws.column_dimensions["A"].width = 30
        ws.column_dimensions["B"].width = 15

        data = [
            ("MIUL Summary", ""),
            ("", ""),
            ("Program", document.program),
            ("End Item", document.end_item),
            ("Revision", document.revision),
            ("Generated", datetime.now().isoformat()),
            ("Source", document.source),
            ("", ""),
            ("Statistics", ""),
            ("Total Rows", len(document.tree.rows) - 1),  # Exclude EOF
            ("Critical Items (Cat 1/1S/2)", len(document.critical_items)),
            ("MUA Required", len(document.mua_required_items)),
            ("Missing Criticality", len(document.missing_criticality)),
            ("", ""),
            ("Criticality Breakdown", ""),
        ]

        # Count by criticality
        crit_counts: dict = {}
        for row in document.tree.rows:
            if row.index == -1:
                continue
            key = row.criticality.value if row.criticality else "Unassigned"
            crit_counts[key] = crit_counts.get(key, 0) + 1

        for crit, count in sorted(crit_counts.items()):
            data.append((f"  {crit}", count))

        for row_idx, (label, value) in enumerate(data, start=1):
            ws.cell(row=row_idx, column=1, value=label)
            ws.cell(row=row_idx, column=2, value=value)

            if label in ("MIUL Summary", "Statistics", "Criticality Breakdown"):
                ws.cell(row=row_idx, column=1).font = Font(bold=True)

    def _write_validation_sheet(self, ws, document: MIULDocument) -> None:
        """Write validation warnings sheet."""
        ws.column_dimensions["A"].width = 15
        ws.column_dimensions["B"].width = 20
        ws.column_dimensions["C"].width = 60

        # Headers
        headers = ["Severity", "Part Number", "Issue"]
        for col_idx, header in enumerate(headers, start=1):
            cell = ws.cell(row=1, column=col_idx, value=header)
            cell.fill = self.HEADER_FILL
            cell.font = self.HEADER_FONT

        row_idx = 2

        # Document-level warnings
        for warning in document.validate_completeness():
            ws.cell(row=row_idx, column=1, value="WARNING")
            ws.cell(row=row_idx, column=2, value="Document")
            ws.cell(row=row_idx, column=3, value=warning)
            row_idx += 1

        # Row-level issues
        for miul_row in document.tree.rows:
            if miul_row.index == -1:
                continue

            issues = self._validate_row(miul_row)
            for severity, issue in issues:
                ws.cell(row=row_idx, column=1, value=severity)
                ws.cell(row=row_idx, column=2, value=miul_row.part_number)
                ws.cell(row=row_idx, column=3, value=issue)
                row_idx += 1

        if row_idx == 2:
            ws.cell(row=2, column=1, value="No issues found")

    def _validate_row(self, row: MIULRow) -> List[Tuple[str, str]]:
        """Validate single row, return list of (severity, message)."""
        issues = []

        if row.criticality is None:
            issues.append(("WARNING", "Missing criticality assignment"))

        if row.criticality and row.criticality.category <= 2:
            if row.material_code is None:
                issues.append(("ERROR", "Critical item missing Material Code"))

            if row.has_rating_gap and row.mua_number is None:
                issues.append(("WARNING", "Rating gap without MUA reference"))

        return issues


def write_miul_excel(
    tree: MIULTree,
    program: str,
    end_item: str,
    output: Union[Path, BytesIO],
    source: str = "miul_writer",
    revision: str = "A",
) -> None:
    """Convenience function to write MIUL tree to Excel.

    Args:
        tree: Validated MIUL tree
        program: Program name (e.g., "ORION")
        end_item: End item name (e.g., "SM Propulsion")
        output: File path or BytesIO buffer
        source: Provenance string
        revision: Document revision
    """
    document = MIULDocument(
        tree=tree,
        program=program,
        end_item=end_item,
        revision=revision,
        source=source,
    )

    writer = MIULExcelWriter()
    writer.write(document, output)
