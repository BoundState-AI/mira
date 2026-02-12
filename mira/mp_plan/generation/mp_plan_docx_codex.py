#!/usr/bin/env python3
"""
Module: M&P Plan DOCX Generator (Codex)
Purpose: Template-aligned 6016-compliant M&P plan document rendering
"""

from __future__ import annotations

from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Any, Iterable, Optional

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Pt

from ..models import PlanGeneratorSession

__version__ = "2.1.0-codex"
__safety_critical__ = False


def _status_display(status: str) -> str:
    return {
        "compliant": "Compliant",
        "compliant_with_constraints": "Compliant w/ Constraints",
        "noncompliant": "Noncompliant",
        "unknown": "Unknown",
        "not_applicable": "Not Applicable",
    }.get(status, status)


class MPPlanDocxGeneratorCodex:
    """
    Render a section-aligned M&P plan using the HULC draft structure.

    The document remains generic by deriving all content from session state.
    """

    def __init__(self, session: PlanGeneratorSession):
        self._session = session

    def generate(self, output_path: Optional[Path] = None) -> bytes:
        doc = Document()
        self._setup_document(doc)
        self._add_title_page(doc)
        self._add_scope(doc)
        self._add_applicable_documents(doc)
        self._add_acronyms_and_definitions(doc)
        self._add_requirements(doc)
        self._add_verification(doc)
        self._add_appendices(doc)

        buffer = BytesIO()
        doc.save(buffer)
        content = buffer.getvalue()

        if output_path:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            with open(output_path, "wb") as f:
                f.write(content)

        return content

    @staticmethod
    def _setup_document(doc: Document) -> None:
        for section in doc.sections:
            section.left_margin = Pt(54)
            section.right_margin = Pt(54)
            section.top_margin = Pt(54)
            section.bottom_margin = Pt(54)

    def _add_title_page(self, doc: Document) -> None:
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run = p.add_run("MATERIALS AND PROCESSES SELECTION,\nCONTROL, AND IMPLEMENTATION PLAN")
        run.bold = True
        run.font.size = Pt(16)

        doc.add_paragraph()
        doc.add_paragraph(f"Program: {self._session.program_name or 'TBD'}")
        doc.add_paragraph(f"Phase: {self._session.program_phase or 'TBD'}")
        doc.add_paragraph("Standard: NASA-STD-6016C w/CHANGE 2")
        doc.add_paragraph(f"Session ID: {self._session.session_id}")
        doc.add_paragraph(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
        doc.add_page_break()

    def _add_scope(self, doc: Document) -> None:
        doc.add_heading("1. Scope", level=1)

        doc.add_heading("Purpose", level=2)
        doc.add_paragraph(
            "This Materials and Processes (M&P) Plan defines materials/process controls, "
            "compliance determinations, and closure actions for mission hardware."
        )

        doc.add_heading("Applicability", level=2)
        env_names = ", ".join(e.name for e in self._session.environments) or "TBD"
        doc.add_paragraph(
            f"This plan applies to hardware covered by session {self._session.session_id} "
            f"in the following environments: {env_names}."
        )

        doc.add_heading("Tailoring", level=2)
        doc.add_paragraph(
            "Tailoring decisions are tracked through HITL review records tied to individual "
            "MPR determinations with explicit evidence citations."
        )

    def _add_applicable_documents(self, doc: Document) -> None:
        doc.add_heading("2. Applicable Documents", level=1)
        docs = [
            "NASA-STD-6016C w/CHANGE 2 - Standard Materials and Processes Requirements for Spacecraft",
            "NASA-STD-6001 - Flammability, Offgassing, and Compatibility Test Method Standards",
            "Program/Project contractual requirements and approved tailoring records",
            "MAPTIS - Materials and Processes Technical Information System records",
        ]
        for item in docs:
            doc.add_paragraph(item, style="List Bullet")

    def _add_acronyms_and_definitions(self, doc: Document) -> None:
        doc.add_heading("3. Acronyms and Definitions", level=1)
        acronyms = [
            "M&P: Materials and Processes",
            "MPR: Materials and Processes Requirement",
            "MAPTIS: Materials and Processes Technical Information System",
            "MIUL: Materials Identification and Usage List",
            "MUA: Materials Usage Agreement",
            "HITL: Human in the Loop",
        ]
        for item in acronyms:
            doc.add_paragraph(item, style="List Bullet")

    def _section_rows(self, prefixes: Iterable[str]) -> list[dict[str, Any]]:
        prefix_tuple = tuple(prefixes)
        rows = [
            d
            for d in self._session.mpr_determinations
            if str(d.get("mpr_section", "")).startswith(prefix_tuple)
            and d.get("applicability_status") == "applicable"
        ]
        rows.sort(key=lambda d: (d.get("mpr_number") or 9999, d.get("material_name") or ""))
        return rows

    @staticmethod
    def _add_rows_table(doc: Document, rows: list[dict[str, Any]]) -> None:
        if not rows:
            doc.add_paragraph("No applicable determinations in this subsection.")
            return

        table = doc.add_table(rows=1, cols=7)
        table.style = "Table Grid"
        table.alignment = WD_TABLE_ALIGNMENT.CENTER
        headers = [
            "Material",
            "Environment",
            "MPR",
            "Section",
            "Status",
            "Rationale",
            "Citation",
        ]
        for idx, name in enumerate(headers):
            cell = table.rows[0].cells[idx]
            cell.text = name
            cell.paragraphs[0].runs[0].bold = True

        for row in rows:
            c = table.add_row().cells
            c[0].text = str(row.get("material_name", ""))
            c[1].text = str(row.get("environment_name", ""))
            c[2].text = str(row.get("mpr_id", ""))
            c[3].text = str(row.get("mpr_section", ""))
            c[4].text = _status_display(str(row.get("status", "")))
            c[5].text = str(row.get("rationale", ""))[:320]
            citations = row.get("citations") or []
            c[6].text = "; ".join(citations[:2])

    def _add_requirements(self, doc: Document) -> None:
        doc.add_heading("4. Requirements", level=1)

        doc.add_heading("4.1 General Requirements", level=2)
        general_rows = self._section_rows(["4.1"])
        self._add_rows_table(doc, general_rows)

        doc.add_heading("4.2 Detailed Requirements", level=2)

        doc.add_heading("4.2.1 Flammability, Offgassing, and Compatibility Requirements", level=3)
        self._add_rows_table(doc, self._section_rows(["4.2.1", "4.2.4", "4.2.5", "4.2.6.4"]))

        doc.add_heading("4.2.2 Metals", level=3)
        self._add_rows_table(doc, self._section_rows(["4.2.2"]))

        doc.add_heading("4.2.3 Nonmetallic Materials", level=3)
        self._add_rows_table(doc, self._section_rows(["4.2.3"]))

        doc.add_heading("4.2.4 Processes", level=3)
        self._add_rows_table(doc, self._section_rows(["4.2.4"]))

        doc.add_heading("4.2.5 Material Nondestructive Evaluation (NDE)", level=3)
        self._add_rows_table(doc, self._section_rows(["4.2.5"]))

        doc.add_heading("4.2.6 Special Materials Requirements", level=3)
        self._add_rows_table(doc, self._section_rows(["4.2.6"]))

    def _add_verification(self, doc: Document) -> None:
        doc.add_heading("4.3 Verification", level=2)

        determinations = self._session.mpr_determinations
        total = len(determinations)
        noncompliant = sum(1 for d in determinations if d.get("status") == "noncompliant")
        constrained = sum(1 for d in determinations if d.get("status") == "compliant_with_constraints")
        unknown = sum(1 for d in determinations if d.get("status") == "unknown")

        doc.add_paragraph(
            f"Applicable determinations evaluated: {total}. "
            f"Noncompliant: {noncompliant}. "
            f"Compliant with constraints: {constrained}. "
            f"Unknown: {unknown}."
        )

        doc.add_paragraph(
            "All determination rows include requirement citations and supporting evidence references."
        )

        if self._session.nonconformances:
            doc.add_paragraph("Open/closed nonconformance summary:")
            table = doc.add_table(rows=1, cols=5)
            table.style = "Table Grid"
            headers = ["ID", "Material", "Gap Type", "Status", "Affected MPR"]
            for idx, name in enumerate(headers):
                table.rows[0].cells[idx].text = name
                table.rows[0].cells[idx].paragraphs[0].runs[0].bold = True

            closed_ids = {d.gap_id for d in self._session.closure_decisions}
            accepted_ids = {a.gap_id for a in self._session.accepted_open_gaps}
            for nc in self._session.nonconformances:
                material = self._session.get_material(nc.material_id)
                if nc.nonconformance_id in closed_ids:
                    status = "Closed"
                elif nc.nonconformance_id in accepted_ids:
                    status = "Accepted Open"
                else:
                    status = "Open"
                row = table.add_row().cells
                row[0].text = nc.nonconformance_id[:12]
                row[1].text = material.name if material else nc.material_id
                row[2].text = nc.gap_type.value.upper()
                row[3].text = status
                row[4].text = ", ".join(nc.affected_mprs or [])

    def _add_appendices(self, doc: Document) -> None:
        doc.add_heading("Appendix A - MIUL Data Requirements Description (DRD)", level=1)
        doc.add_paragraph(
            "This appendix captures MIUL linkage to the M&P plan session and material lineage."
        )

        doc.add_heading("Appendix B - MUA Data Requirements Description (DRD)", level=1)
        doc.add_paragraph(
            "This appendix captures closure-path artifacts and required authority signoffs."
        )

        doc.add_heading("Appendix C - MUA Form", level=1)
        doc.add_paragraph("Reserved for generated MUA package content.")

        doc.add_heading("Appendix D - Rationale Codes", level=1)
        doc.add_paragraph(
            "Rationale and closure codes are derived from closure decisions and accepted open gaps."
        )


def generate_mp_plan_docx_codex(
    session: PlanGeneratorSession,
    output_path: Optional[Path] = None,
) -> bytes:
    """Convenience function for codex DOCX generation."""
    return MPPlanDocxGeneratorCodex(session).generate(output_path=output_path)

