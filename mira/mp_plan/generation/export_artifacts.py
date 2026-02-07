#!/usr/bin/env python3
"""
Module: Export Artifacts
Purpose: Generate export artifacts for M&P Plan Generator V2

BoundState AI 2026
Version: 2.0.0
Classification: BoundState Proprietary

Generates exportable artifacts:
- Applicability Matrix (Excel)
- Gap Register (Excel)
- Session Manifest (JSON)

Compliance: NASA-STD-8739.8B, SWE-013, SWE-033
Safety Critical: False
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from io import BytesIO
from typing import TYPE_CHECKING

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

if TYPE_CHECKING:
    from ..models import PlanGeneratorSession

LOGGER = logging.getLogger(__name__)

__version__ = "2.0.0"
__safety_critical__ = False


# Excel styles
HEADER_FILL = PatternFill(start_color="1F4E79", end_color="1F4E79", fill_type="solid")
HEADER_FONT = Font(color="FFFFFF", bold=True, size=11)
APPLICABLE_FILL = PatternFill(start_color="C6EFCE", end_color="C6EFCE", fill_type="solid")
NOT_APPLICABLE_FILL = PatternFill(start_color="DDDDDD", end_color="DDDDDD", fill_type="solid")
OPEN_GAP_FILL = PatternFill(start_color="FFC7CE", end_color="FFC7CE", fill_type="solid")
CLOSED_GAP_FILL = PatternFill(start_color="C6EFCE", end_color="C6EFCE", fill_type="solid")
ACCEPTED_FILL = PatternFill(start_color="FFEB9C", end_color="FFEB9C", fill_type="solid")
THIN_BORDER = Border(
    left=Side(style="thin"),
    right=Side(style="thin"),
    top=Side(style="thin"),
    bottom=Side(style="thin"),
)


def generate_applicability_matrix_xlsx(session: "PlanGeneratorSession") -> bytes:
    """
    Generate applicability matrix as Excel file.

    Creates a matrix showing which MPRs apply to which materials
    in each environment.

    Args:
        session: Plan generator session.

    Returns:
        Excel file bytes.
    """
    wb = Workbook()
    ws = wb.active
    ws.title = "Applicability Matrix"

    # Headers
    headers = [
        "Material",
        "Environment",
        "MPR ID",
        "MPR Title",
        "Applicable",
        "Rationale",
        "Evidence",
    ]
    for col, header in enumerate(headers, 1):
        cell = ws.cell(row=1, column=col, value=header)
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.border = THIN_BORDER

    # Data rows
    row = 2
    for det in session.mpr_determinations:
        material = next(
            (m for m in session.materials if m.id == det.material_id),
            None,
        )
        environment = next(
            (e for e in session.environments if e.environment_id == det.environment_id),
            None,
        )

        ws.cell(row=row, column=1, value=material.name if material else "Unknown")
        ws.cell(row=row, column=2, value=environment.name if environment else "Unknown")
        ws.cell(row=row, column=3, value=det.mpr_id)
        ws.cell(row=row, column=4, value=det.mpr_title)
        ws.cell(row=row, column=5, value="Yes" if det.applicable else "No")
        ws.cell(row=row, column=6, value=det.rationale)
        ws.cell(
            row=row,
            column=7,
            value=f"{det.evidence.document_id} {det.evidence.section}" if det.evidence else "",
        )

        # Style applicable/not applicable
        fill = APPLICABLE_FILL if det.applicable else NOT_APPLICABLE_FILL
        for col in range(1, 8):
            cell = ws.cell(row=row, column=col)
            cell.fill = fill
            cell.border = THIN_BORDER
            cell.alignment = Alignment(wrap_text=True, vertical="top")

        row += 1

    # Auto-size columns
    for col in range(1, 8):
        ws.column_dimensions[get_column_letter(col)].width = 20

    # Summary sheet
    summary_ws = wb.create_sheet("Summary")
    summary_ws.cell(row=1, column=1, value="Applicability Matrix Summary")
    summary_ws.cell(row=1, column=1).font = Font(bold=True, size=14)

    summary_ws.cell(row=3, column=1, value="Session ID:")
    summary_ws.cell(row=3, column=2, value=session.session_id)

    summary_ws.cell(row=4, column=1, value="Generated:")
    summary_ws.cell(row=4, column=2, value=datetime.now().isoformat())

    summary_ws.cell(row=5, column=1, value="Total Materials:")
    summary_ws.cell(row=5, column=2, value=len(session.materials))

    summary_ws.cell(row=6, column=1, value="Total Environments:")
    summary_ws.cell(row=6, column=2, value=len(session.environments))

    summary_ws.cell(row=7, column=1, value="Total Determinations:")
    summary_ws.cell(row=7, column=2, value=len(session.mpr_determinations))

    applicable_count = sum(1 for d in session.mpr_determinations if d.applicable)
    summary_ws.cell(row=8, column=1, value="Applicable MPRs:")
    summary_ws.cell(row=8, column=2, value=applicable_count)

    output = BytesIO()
    wb.save(output)
    return output.getvalue()


def generate_gap_register_xlsx(session: "PlanGeneratorSession") -> bytes:
    """
    Generate gap register as Excel file.

    Creates a register of all deficiencies and nonconformances
    with their current status.

    Args:
        session: Plan generator session.

    Returns:
        Excel file bytes.
    """
    wb = Workbook()

    # Deficiencies sheet
    def_ws = wb.active
    def_ws.title = "Deficiencies"

    def_headers = [
        "Deficiency ID",
        "Material",
        "Field",
        "Severity",
        "Description",
        "Resolved",
    ]
    for col, header in enumerate(def_headers, 1):
        cell = def_ws.cell(row=1, column=col, value=header)
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.border = THIN_BORDER

    row = 2
    for d in session.deficiencies:
        material = next(
            (m for m in session.materials if m.id == d.material_id),
            None,
        )
        def_ws.cell(row=row, column=1, value=d.deficiency_id[:12])
        def_ws.cell(row=row, column=2, value=material.name if material else "Unknown")
        def_ws.cell(row=row, column=3, value=d.field_name)
        def_ws.cell(
            row=row,
            column=4,
            value=d.severity.value if hasattr(d.severity, "value") else str(d.severity),
        )
        def_ws.cell(row=row, column=5, value=d.description)
        def_ws.cell(row=row, column=6, value="Yes" if d.resolved else "No")

        for col in range(1, 7):
            cell = def_ws.cell(row=row, column=col)
            cell.border = THIN_BORDER
            cell.alignment = Alignment(wrap_text=True, vertical="top")

        row += 1

    for col in range(1, 7):
        def_ws.column_dimensions[get_column_letter(col)].width = 18

    # Nonconformances sheet
    nc_ws = wb.create_sheet("Nonconformances")

    nc_headers = [
        "NC ID",
        "Material",
        "Environment",
        "Gap Type",
        "MPR",
        "Severity",
        "Description",
        "Status",
        "Closure Path",
    ]
    for col, header in enumerate(nc_headers, 1):
        cell = nc_ws.cell(row=1, column=col, value=header)
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.border = THIN_BORDER

    row = 2
    for nc in session.nonconformances:
        material = next(
            (m for m in session.materials if m.id == nc.material_id),
            None,
        )
        environment = next(
            (e for e in session.environments if e.environment_id == nc.environment_id),
            None,
        )
        closure = next(
            (c for c in session.closure_decisions if c.gap_id == nc.nonconformance_id),
            None,
        )
        accepted = next(
            (a for a in session.accepted_open_gaps if a.gap_id == nc.nonconformance_id),
            None,
        )

        status = "Open"
        closure_path = ""
        if closure:
            status = "Closed"
            closure_path = closure.selected_path
        elif accepted:
            status = "Accepted Open"

        nc_ws.cell(row=row, column=1, value=nc.nonconformance_id[:12])
        nc_ws.cell(row=row, column=2, value=material.name if material else "Unknown")
        nc_ws.cell(row=row, column=3, value=environment.name if environment else "Unknown")
        nc_ws.cell(
            row=row,
            column=4,
            value=nc.gap_type.value if hasattr(nc.gap_type, "value") else str(nc.gap_type),
        )
        nc_ws.cell(row=row, column=5, value=nc.mpr_id)
        nc_ws.cell(
            row=row,
            column=6,
            value=nc.severity.value if hasattr(nc.severity, "value") else str(nc.severity),
        )
        nc_ws.cell(row=row, column=7, value=nc.description)
        nc_ws.cell(row=row, column=8, value=status)
        nc_ws.cell(row=row, column=9, value=closure_path)

        # Style based on status
        if status == "Open":
            fill = OPEN_GAP_FILL
        elif status == "Closed":
            fill = CLOSED_GAP_FILL
        else:
            fill = ACCEPTED_FILL

        for col in range(1, 10):
            cell = nc_ws.cell(row=row, column=col)
            cell.fill = fill
            cell.border = THIN_BORDER
            cell.alignment = Alignment(wrap_text=True, vertical="top")

        row += 1

    for col in range(1, 10):
        nc_ws.column_dimensions[get_column_letter(col)].width = 16

    # Summary sheet
    summary_ws = wb.create_sheet("Summary")
    summary_ws.cell(row=1, column=1, value="Gap Register Summary")
    summary_ws.cell(row=1, column=1).font = Font(bold=True, size=14)

    summary_ws.cell(row=3, column=1, value="Session ID:")
    summary_ws.cell(row=3, column=2, value=session.session_id)

    summary_ws.cell(row=4, column=1, value="Generated:")
    summary_ws.cell(row=4, column=2, value=datetime.now().isoformat())

    summary_ws.cell(row=6, column=1, value="Deficiencies:")
    summary_ws.cell(row=6, column=2, value=len(session.deficiencies))

    resolved = sum(1 for d in session.deficiencies if d.resolved)
    summary_ws.cell(row=7, column=1, value="  - Resolved:")
    summary_ws.cell(row=7, column=2, value=resolved)

    summary_ws.cell(row=8, column=1, value="  - Unresolved:")
    summary_ws.cell(row=8, column=2, value=len(session.deficiencies) - resolved)

    summary_ws.cell(row=10, column=1, value="Nonconformances:")
    summary_ws.cell(row=10, column=2, value=len(session.nonconformances))

    closed = len(session.closure_decisions)
    accepted_open = len(session.accepted_open_gaps)
    open_count = len(session.nonconformances) - closed - accepted_open

    summary_ws.cell(row=11, column=1, value="  - Open:")
    summary_ws.cell(row=11, column=2, value=open_count)

    summary_ws.cell(row=12, column=1, value="  - Closed:")
    summary_ws.cell(row=12, column=2, value=closed)

    summary_ws.cell(row=13, column=1, value="  - Accepted Open:")
    summary_ws.cell(row=13, column=2, value=accepted_open)

    output = BytesIO()
    wb.save(output)
    return output.getvalue()


def generate_session_manifest(session: "PlanGeneratorSession") -> dict:
    """
    Generate session manifest as JSON-serializable dict.

    Creates a complete manifest of the session for audit trail.

    Args:
        session: Plan generator session.

    Returns:
        Manifest dictionary.
    """
    manifest = {
        "manifest_version": "2.0.0",
        "generated_at": datetime.now().isoformat(),
        "session": {
            "session_id": session.session_id,
            "program_name": session.program_name,
            "program_phase": session.program_phase,
            "policy_pack_id": session.policy_pack_id,
            "created_at": session.created_at.isoformat(),
            "updated_at": session.updated_at.isoformat(),
        },
        "materials": [
            {
                "id": m.id,
                "name": m.name,
                "application": m.application,
                "maptis_code": m.maptis_code,
                "quantity": m.quantity,
                "mass_g": m.mass_g,
                "surface_area_cm2": m.surface_area_cm2,
            }
            for m in session.materials
        ],
        "environments": [
            {
                "environment_id": e.environment_id,
                "name": e.name,
                "o2_pct": e.o2_pct,
                "pressure_psia": e.pressure_psia,
                "temp_range_c": e.temp_range_c,
                "habitable": e.habitable,
                "vacuum_exposure": e.vacuum_exposure,
                "lunar_dust": e.lunar_dust,
            }
            for e in session.environments
        ],
        "statistics": {
            "material_count": len(session.materials),
            "environment_count": len(session.environments),
            "determination_count": len(session.mpr_determinations),
            "deficiency_count": len(session.deficiencies),
            "nonconformance_count": len(session.nonconformances),
            "closure_count": len(session.closure_decisions),
            "accepted_open_count": len(session.accepted_open_gaps),
            "artifact_count": len(session.generated_artifacts),
        },
        "compliance_status": {
            "can_generate": session.can_generate()[0],
            "blockers": session.can_generate()[1],
            "open_nonconformances": sum(
                1
                for nc in session.nonconformances
                if nc.nonconformance_id not in [c.gap_id for c in session.closure_decisions]
                and nc.nonconformance_id not in [a.gap_id for a in session.accepted_open_gaps]
            ),
        },
        "closure_summary": {
            "total_gaps": len(session.nonconformances),
            "closed_by_path": {},
            "accepted_open": len(session.accepted_open_gaps),
        },
    }

    # Count closures by path
    for c in session.closure_decisions:
        path = c.selected_path
        manifest["closure_summary"]["closed_by_path"][path] = (
            manifest["closure_summary"]["closed_by_path"].get(path, 0) + 1
        )

    return manifest


def generate_manifest_json(session: "PlanGeneratorSession") -> bytes:
    """
    Generate session manifest as JSON bytes.

    Args:
        session: Plan generator session.

    Returns:
        JSON file bytes.
    """
    manifest = generate_session_manifest(session)
    return json.dumps(manifest, indent=2).encode("utf-8")
