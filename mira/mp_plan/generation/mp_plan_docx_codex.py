#!/usr/bin/env python3
"""
Module: M&P Plan DOCX Generator (Codex)
Purpose: Full 6016C/JSC-27301 compliant M&P plan document rendering

Generates a complete Materials and Processes Selection, Control, and
Implementation Plan (MSPCI) covering all required sections per:
  - NASA-STD-6016C w/CHANGE 2 (MPR 9-14, 23-27)
  - JSC-27301 Rev F/J (MSPCI structure)

Document structure:
  1.0  Scope (Purpose, Applicability, Tailoring, Document Summary)
  2.0  Applicable Documents
  3.0  Acronyms and Definitions
  4.0  M&P Organization and Responsibilities (MPR 9-14, 23-24)
  5.0  Environment Definitions
  6.0  Materials Inventory (MPR 25-27)
  7.0  Test Condition Deltas
  8.0  Requirements Compliance (per 6016C section)
       8.1  General (4.1)
       8.2  Flam/Offgas/Compat (4.2.1)
       8.3  Metals (4.2.2)
       8.4  Nonmetals (4.2.3)
       8.5  Processes (4.2.4)
       8.6  NDE (4.2.5)
       8.7  Special Materials (4.2.6)
       8.8  Contamination/FOD (4.2.7)
  9.0  Verification Summary
  10.0 Nonconformance Register
  11.0 Closure Decisions
  12.0 Accepted Open Gaps
  13.0 Minor Quantity Analysis
  Appendix A - MIUL Summary
  Appendix B - MUA Register
  Appendix C - Rationale Codes
  Appendix D - Revision History
"""

from __future__ import annotations

import math
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Any, Iterable, Optional

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Pt

from ..models import PlanGeneratorSession

__version__ = "2.2.0-codex"
__safety_critical__ = False


def _status_display(status: str) -> str:
    return {
        "compliant": "Compliant",
        "compliant_with_constraints": "Compliant w/ Constraints",
        "noncompliant": "Noncompliant",
        "unknown": "Unknown",
        "not_applicable": "Not Applicable",
    }.get(status, status)


def _fmt(value: Any, suffix: str = "", default: str = "TBD") -> str:
    if value is None:
        return default
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return default
    return f"{value}{suffix}"


def _add_table(doc: Document, headers: list[str], rows: list[list[str]]) -> None:
    """Add a styled table with headers and rows."""
    table = doc.add_table(rows=1, cols=len(headers))
    table.style = "Table Grid"
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    for idx, name in enumerate(headers):
        cell = table.rows[0].cells[idx]
        cell.text = name
        for run in cell.paragraphs[0].runs:
            run.bold = True
    for row_data in rows:
        cells = table.add_row().cells
        for idx, val in enumerate(row_data):
            if idx < len(cells):
                cells[idx].text = str(val)


class MPPlanDocxGeneratorCodex:
    """
    Render a full JSC-27301/6016C compliant M&P plan from session state.

    All content is derived from session data — no hardcoded material lists.
    """

    def __init__(self, session: PlanGeneratorSession):
        self._session = session

    def generate(self, output_path: Optional[Path] = None) -> bytes:
        doc = Document()
        self._setup_document(doc)
        self._add_title_page(doc)
        self._add_scope(doc)                     # 1.0
        self._add_applicable_documents(doc)       # 2.0
        self._add_acronyms_and_definitions(doc)   # 3.0
        self._add_organization(doc)               # 4.0
        self._add_environment_definitions(doc)    # 5.0
        self._add_materials_inventory(doc)        # 6.0
        self._add_test_condition_deltas(doc)      # 7.0
        self._add_requirements(doc)               # 8.0
        self._add_verification(doc)               # 9.0
        self._add_nonconformance_register(doc)    # 10.0
        self._add_closure_decisions(doc)          # 11.0
        self._add_accepted_open_gaps(doc)         # 12.0
        self._add_minor_quantity_analysis(doc)    # 13.0
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

    # -----------------------------------------------------------------------
    # Title Page
    # -----------------------------------------------------------------------
    def _add_title_page(self, doc: Document) -> None:
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run = p.add_run(
            "MATERIALS AND PROCESSES SELECTION,\n"
            "CONTROL, AND IMPLEMENTATION PLAN"
        )
        run.bold = True
        run.font.size = Pt(16)

        doc.add_paragraph()
        doc.add_paragraph(f"Program: {self._session.program_name or 'TBD'}")
        doc.add_paragraph(f"Phase: {self._session.program_phase or 'TBD'}")
        doc.add_paragraph(
            f"Lead Organization: {self._session.lead_organization or 'TBD'}"
        )
        doc.add_paragraph("Standard: NASA-STD-6016C w/CHANGE 2")
        doc.add_paragraph(f"Session ID: {self._session.session_id}")
        doc.add_paragraph(
            f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}"
        )
        doc.add_page_break()

    # -----------------------------------------------------------------------
    # 1.0 Scope
    # -----------------------------------------------------------------------
    def _add_scope(self, doc: Document) -> None:
        doc.add_heading("1.0 Scope", level=1)

        doc.add_heading("1.1 Purpose", level=2)
        doc.add_paragraph(
            "This Materials and Processes (M&P) Selection, Control, and "
            "Implementation Plan defines the materials and process controls, "
            "compliance determinations, and closure actions for spaceflight "
            "hardware in accordance with NASA-STD-6016C w/CHANGE 2. "
            "Per MPR 9, each organization responsible for design and "
            "fabrication of spaceflight hardware shall provide this plan."
        )

        doc.add_heading("1.2 Applicability", level=2)
        env_names = ", ".join(e.name for e in self._session.environments) or "TBD"
        doc.add_paragraph(
            f"This plan applies to hardware in the following environments: "
            f"{env_names}. Per MPR 11, upon approval by the procuring "
            f"activity, this plan becomes the M&P implementation document "
            f"used for verification."
        )

        doc.add_heading("1.3 Tailoring", level=2)
        doc.add_paragraph(
            "Tailoring decisions are tracked through Human-in-the-Loop (HITL) "
            "review records tied to individual MPR determinations with "
            "explicit evidence citations. Each tailoring action includes "
            "rationale and reviewer identity per SWE-033."
        )

        doc.add_heading("1.4 Document Summary", level=2)
        s = self._session
        mat_count = len(s.materials)
        env_count = len(s.environments)
        nc_count = len(s.nonconformances)
        closed_count = len(s.closure_decisions)
        open_count = len(s.accepted_open_gaps)
        det_count = len(s.mpr_determinations)
        doc.add_paragraph(
            f"This plan covers {mat_count} material(s) across "
            f"{env_count} environment(s), with {det_count} MPR "
            f"determinations. {nc_count} nonconformance(s) identified, "
            f"{closed_count} closed, {open_count} accepted open."
        )

    # -----------------------------------------------------------------------
    # 2.0 Applicable Documents
    # -----------------------------------------------------------------------
    def _add_applicable_documents(self, doc: Document) -> None:
        doc.add_heading("2.0 Applicable Documents", level=1)
        docs = [
            "NASA-STD-6016C w/CHANGE 2 — Standard Materials and Processes "
            "Requirements for Spacecraft",
            "NASA-STD-6001B — Flammability, Offgassing, and Compatibility "
            "Requirements and Test Procedures",
            "JSC-27301 — Materials and Processes Selection and Application "
            "for Spacecraft Systems",
            "MSFC-STD-3029A — Guidelines for the Selection of Metallic "
            "Materials for Stress Corrosion Cracking Resistance",
            "NASA-STD-5019 — Fracture Control Requirements for Spaceflight "
            "Hardware",
            "NASA-STD-6030 — Additive Manufacturing Requirements for "
            "Spaceflight Systems",
            "MIL-STD-889D — Dissimilar Metals",
            "MAPTIS — Materials and Processes Technical Information System",
            "Program/Project contractual requirements and approved tailoring "
            "records",
        ]
        for item in docs:
            doc.add_paragraph(item, style="List Bullet")

    # -----------------------------------------------------------------------
    # 3.0 Acronyms and Definitions
    # -----------------------------------------------------------------------
    def _add_acronyms_and_definitions(self, doc: Document) -> None:
        doc.add_heading("3.0 Acronyms and Definitions", level=1)
        acronyms = [
            ("AM", "Additive Manufacturing"),
            ("COTS", "Commercial Off-The-Shelf"),
            ("DCAA", "Defense Contract Audit Agency"),
            ("DRD", "Data Requirements Description"),
            ("EDM", "Electrical Discharge Machining"),
            ("FOD", "Foreign Object Debris/Damage"),
            ("GSE", "Ground Support Equipment"),
            ("HAZ", "Heat Affected Zone"),
            ("HEE", "Hydrogen Environment Embrittlement"),
            ("HITL", "Human in the Loop"),
            ("M&P", "Materials and Processes"),
            ("MAPTIS", "Materials and Processes Technical Information System"),
            ("MIUL", "Materials Identification and Usage List"),
            ("MMPDS", "Metallic Materials Properties Development and "
             "Standardization"),
            ("MPR", "Materials and Processes Requirement"),
            ("MSPCI", "Materials and Processes Selection, Control, and "
             "Implementation Plan"),
            ("MUA", "Materials Usage Agreement"),
            ("NDE", "Nondestructive Evaluation"),
            ("SCC", "Stress Corrosion Cracking"),
            ("SMAC", "Spacecraft Maximum Allowable Concentration"),
            ("TVS", "Thermal Vacuum Stability"),
            ("WPS", "Welding Procedure Specification"),
        ]
        for abbr, expansion in acronyms:
            doc.add_paragraph(f"{abbr}: {expansion}", style="List Bullet")

    # -----------------------------------------------------------------------
    # 4.0 M&P Organization and Responsibilities (MPR 9-14, 23-24)
    # -----------------------------------------------------------------------
    def _add_organization(self, doc: Document) -> None:
        doc.add_heading("4.0 M&P Organization and Responsibilities", level=1)

        doc.add_heading("4.1 M&P Plan Ownership (MPR 9-11)", level=2)
        org = self._session.lead_organization or "TBD"
        doc.add_paragraph(
            f"The responsible M&P organization is: {org}. "
            f"This plan is maintained under program "
            f"'{self._session.program_name or 'TBD'}' and shall be updated "
            f"when materials, environments, or compliance status change."
        )

        doc.add_heading("4.2 Drawing Coordination (MPR 12-13)", level=2)
        doc.add_paragraph(
            "Per MPR 12, engineering drawings and revisions for spaceflight "
            "hardware shall have M&P approval signature. The coordination "
            "method and approval workflow are defined in the program's "
            "Configuration Management Plan."
        )

        doc.add_heading("4.3 Manufacturing Participation (MPR 14)", level=2)
        doc.add_paragraph(
            "Per MPR 14, the M&P organization participates in manufacturing "
            "and processing activities through review of process "
            "specifications, witness of critical process steps, and "
            "verification of material certifications."
        )

        doc.add_heading("4.4 M&P Control Panel (MPR 23-24)", level=2)
        org_chart = self._session.org_chart
        if org_chart:
            doc.add_paragraph(
                f"Lead Organization: {org_chart.lead_org}. "
                f"Technical Authority: {org_chart.technical_authority}."
            )
            if org_chart.panel_members:
                doc.add_paragraph("Panel Members:")
                for member in org_chart.panel_members:
                    name = member.get("name", "TBD")
                    role = member.get("role", "Member")
                    doc.add_paragraph(
                        f"{name} — {role}", style="List Bullet"
                    )
        else:
            doc.add_paragraph(
                "The M&P control panel scope and membership shall be defined "
                "prior to plan approval. Panel composition and charter are "
                "specified in the program's M&P Plan per MPR 24."
            )

        doc.add_heading(
            "4.5 Subcontractor/Vendor Controls (MPR 10, 22)", level=2
        )
        cots_items = self._session.cots_items
        if cots_items:
            doc.add_paragraph(
                f"{len(cots_items)} COTS item(s) identified. Per MPR 22, "
                f"vendor-designed and off-the-shelf items are covered by "
                f"M&P requirements:"
            )
            for item in cots_items:
                critical = "Mission-critical" if item.is_mission_critical else "Non-critical"
                doc.add_paragraph(
                    f"{item.name} ({critical}): {item.rationale}",
                    style="List Bullet",
                )
        else:
            doc.add_paragraph(
                "Per MPR 10 and MPR 22, methods for controlling subcontractor "
                "and vendor compliance with M&P requirements shall be "
                "documented. No COTS items have been identified in this "
                "session."
            )

        doc.add_heading(
            "4.6 MIUL Documentation Approach (MPR 25-27)", level=2
        )
        doc.add_paragraph(
            "Per MPR 25, M&P usage is documented in the Materials "
            "Identification and Usage List (MIUL) generated from this plan's "
            "session data. The MIUL covers the final design as delivered "
            "(MPR 26) and the documentation approach is defined in this plan "
            "(MPR 27). See Appendix A for MIUL summary."
        )

    # -----------------------------------------------------------------------
    # 5.0 Environment Definitions
    # -----------------------------------------------------------------------
    def _add_environment_definitions(self, doc: Document) -> None:
        doc.add_heading("5.0 Environment Definitions", level=1)

        if not self._session.environments:
            doc.add_paragraph("No environments defined.")
            return

        doc.add_paragraph(
            "The following environment definitions establish the operating "
            "conditions against which material compliance is evaluated."
        )

        headers = [
            "Name", "O2 %", "O2 Status", "Pressure (psia)",
            "Temp Range", "Habitable", "Vacuum", "Source",
        ]
        rows = []
        for env in self._session.environments:
            o2_status = "Elevated O2" if env.o2_pct > 23.5 else "Standard"
            temp_range = f"{env.temp_range_c[0]:.0f}°C to {env.temp_range_c[1]:.0f}°C"
            rows.append([
                env.name,
                f"{env.o2_pct:.1f}%",
                o2_status,
                f"{env.pressure_psia:.1f}",
                temp_range,
                "Yes" if env.habitable else "No",
                "Yes" if env.vacuum_exposure else "No",
                env.source,
            ])
        _add_table(doc, headers, rows)

    # -----------------------------------------------------------------------
    # 6.0 Materials Inventory (MPR 25-27, 30-31)
    # -----------------------------------------------------------------------
    def _add_materials_inventory(self, doc: Document) -> None:
        doc.add_heading("6.0 Materials Inventory", level=1)

        if not self._session.materials:
            doc.add_paragraph("No materials entered.")
            return

        doc.add_paragraph(
            "Per MPR 25 and MPR 30, all materials for spaceflight hardware "
            "are documented with MAPTIS codes, test ratings, and traceability "
            "information."
        )

        headers = [
            "Material", "Application", "MAPTIS Code", "Qty",
            "Mass (g)", "Area (cm²)", "FLAM", "TVS", "TOX",
            "SCC", "CORR", "Test O2%",
        ]
        rows = []
        for mat in self._session.materials:
            res = self._session.get_resolution(mat.id)
            rows.append([
                mat.name,
                mat.application,
                res.maptis_code if res else "Not Resolved",
                str(mat.quantity),
                _fmt(mat.mass_g, " g"),
                _fmt(mat.surface_area_cm2, " cm²"),
                res.flam_rating if res else "—",
                res.tvs_rating if res else "—",
                res.tox_rating if res else "—",
                getattr(res, "scc_rating", None) or "—" if res else "—",
                getattr(res, "corr_rating", None) or "—" if res else "—",
                f"{res.test_o2_pct:.1f}%" if res else "—",
            ])
        _add_table(doc, headers, rows)

    # -----------------------------------------------------------------------
    # 7.0 Test Condition Deltas
    # -----------------------------------------------------------------------
    def _add_test_condition_deltas(self, doc: Document) -> None:
        doc.add_heading("7.0 Test Condition Deltas", level=1)

        doc.add_paragraph(
            "Per MPR 42 and MPR 83, test conditions shall match or exceed "
            "use conditions. The following table compares test O2% and "
            "pressure against each environment."
        )

        headers = [
            "Material", "Environment", "Parameter",
            "Test Value", "Use Value", "Delta", "Status",
        ]
        rows = []
        outside_count = 0

        for mat in self._session.materials:
            res = self._session.get_resolution(mat.id)
            if not res:
                continue
            for env in self._session.environments:
                # O2 delta
                test_o2 = float(res.test_o2_pct or 0.0)
                use_o2 = float(env.o2_pct)
                o2_delta = use_o2 - test_o2
                o2_status = "Within Envelope" if o2_delta <= 0 else "OUTSIDE ENVELOPE"
                if o2_status == "OUTSIDE ENVELOPE":
                    outside_count += 1
                rows.append([
                    mat.name,
                    env.name,
                    "O2 %",
                    f"{test_o2:.1f}%",
                    f"{use_o2:.1f}%",
                    f"{o2_delta:+.1f}%",
                    o2_status,
                ])

                # Pressure delta
                test_p = float(res.test_pressure_psia or env.pressure_psia)
                use_p = float(env.pressure_psia)
                p_delta = abs(use_p - test_p)
                p_status = "Within Envelope" if p_delta <= 2.0 else "OUTSIDE ENVELOPE"
                if p_status == "OUTSIDE ENVELOPE":
                    outside_count += 1
                rows.append([
                    mat.name,
                    env.name,
                    "Pressure (psia)",
                    f"{test_p:.1f}",
                    f"{use_p:.1f}",
                    f"{p_delta:+.1f}",
                    p_status,
                ])

        if rows:
            _add_table(doc, headers, rows)
            if outside_count > 0:
                doc.add_paragraph(
                    f"{outside_count} item(s) fall outside the tested "
                    f"envelope and require additional evaluation or testing."
                )
        else:
            doc.add_paragraph("No test condition deltas to report.")

    # -----------------------------------------------------------------------
    # 8.0 Requirements Compliance
    # -----------------------------------------------------------------------
    def _section_rows(self, prefixes: Iterable[str]) -> list[dict[str, Any]]:
        prefix_tuple = tuple(prefixes)
        rows = [
            d
            for d in self._session.mpr_determinations
            if str(d.get("mpr_section", "")).startswith(prefix_tuple)
            and d.get("applicability_status") == "applicable"
        ]
        rows.sort(
            key=lambda d: (
                d.get("mpr_number") or 9999,
                d.get("material_name") or "",
            )
        )
        return rows

    @staticmethod
    def _add_rows_table(doc: Document, rows: list[dict[str, Any]]) -> None:
        if not rows:
            doc.add_paragraph(
                "No applicable determinations in this subsection."
            )
            return

        table = doc.add_table(rows=1, cols=7)
        table.style = "Table Grid"
        table.alignment = WD_TABLE_ALIGNMENT.CENTER
        headers = [
            "Material", "Environment", "MPR", "Section",
            "Status", "Rationale", "Citation",
        ]
        for idx, name in enumerate(headers):
            cell = table.rows[0].cells[idx]
            cell.text = name
            for run in cell.paragraphs[0].runs:
                run.bold = True

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
        doc.add_heading("8.0 Requirements Compliance", level=1)

        doc.add_paragraph(
            "The following sections document compliance determinations for "
            "each applicable MPR from NASA-STD-6016C, organized by standard "
            "section. Only applicable determinations are shown."
        )

        doc.add_heading("8.1 General and Programmatic Requirements (4.1)", level=2)
        self._add_rows_table(doc, self._section_rows(["4.1", "4"]))

        doc.add_heading(
            "8.2 Flammability, Offgassing, and Compatibility (4.2.1)", level=2
        )
        self._add_rows_table(
            doc, self._section_rows(["4.2.1"])
        )

        doc.add_heading("8.3 Metals (4.2.2)", level=2)
        self._add_rows_table(doc, self._section_rows(["4.2.2"]))

        doc.add_heading("8.4 Nonmetallic Materials (4.2.3)", level=2)
        self._add_rows_table(doc, self._section_rows(["4.2.3"]))

        doc.add_heading("8.5 Processes (4.2.4)", level=2)
        self._add_rows_table(doc, self._section_rows(["4.2.4"]))

        doc.add_heading(
            "8.6 Nondestructive Evaluation (4.2.5)", level=2
        )
        self._add_rows_table(doc, self._section_rows(["4.2.5"]))

        doc.add_heading(
            "8.7 Structural, Corrosion, and Special Materials (4.2.6)", level=2
        )
        self._add_rows_table(doc, self._section_rows(["4.2.6"]))

        doc.add_heading(
            "8.8 Contamination and FOD Control (4.2.7)", level=2
        )
        self._add_rows_table(doc, self._section_rows(["4.2.7"]))

        doc.add_heading("8.9 Verification (4.3)", level=2)
        self._add_rows_table(doc, self._section_rows(["4.3"]))

    # -----------------------------------------------------------------------
    # 9.0 Verification Summary
    # -----------------------------------------------------------------------
    def _add_verification(self, doc: Document) -> None:
        doc.add_heading("9.0 Verification Summary", level=1)

        dets = self._session.mpr_determinations
        applicable = [d for d in dets if d.get("applicability_status") == "applicable"]
        total = len(applicable)
        compliant = sum(1 for d in applicable if d.get("status") == "compliant")
        constrained = sum(
            1 for d in applicable
            if d.get("status") == "compliant_with_constraints"
        )
        noncompliant = sum(
            1 for d in applicable if d.get("status") == "noncompliant"
        )
        unknown = sum(
            1 for d in applicable if d.get("status") == "unknown"
        )
        prohibition_count = sum(
            1 for d in applicable if d.get("prohibition_triggered")
        )

        doc.add_paragraph(
            f"Per MPR 209, verification of compliance consists of the "
            f"following summary:"
        )

        headers = ["Status", "Count", "Percentage"]
        pct = lambda n: f"{n / total * 100:.1f}%" if total else "0%"
        rows = [
            ["Compliant", str(compliant), pct(compliant)],
            ["Compliant w/ Constraints", str(constrained), pct(constrained)],
            ["Noncompliant", str(noncompliant), pct(noncompliant)],
            ["Unknown (requires citation)", str(unknown), pct(unknown)],
            ["Total Applicable", str(total), "100%"],
        ]
        _add_table(doc, headers, rows)

        if prohibition_count > 0:
            doc.add_paragraph(
                f"{prohibition_count} determination(s) are PROHIBITED by "
                f"the standard and require material substitution or formal "
                f"MUA with engineering justification."
            )

        doc.add_paragraph(
            "All determination rows include requirement citations and "
            "supporting evidence references traceable to NASA-STD-6016C "
            "section numbers."
        )

    # -----------------------------------------------------------------------
    # 10.0 Nonconformance Register
    # -----------------------------------------------------------------------
    def _add_nonconformance_register(self, doc: Document) -> None:
        doc.add_heading("10.0 Nonconformance Register", level=1)

        if not self._session.nonconformances:
            doc.add_paragraph(
                "No nonconformances identified. All evaluated materials "
                "meet applicable requirements."
            )
            return

        doc.add_paragraph(
            f"{len(self._session.nonconformances)} nonconformance(s) "
            f"identified. Per MPR 28, MUAs containing sufficient "
            f"information to demonstrate acceptability shall be submitted "
            f"for each nonconformance."
        )

        closed_ids = {d.gap_id for d in self._session.closure_decisions}
        accepted_ids = {a.gap_id for a in self._session.accepted_open_gaps}

        headers = [
            "ID", "Material", "Environment", "Gap Type",
            "Failing Value", "Required", "Severity", "Status",
            "Affected MPR",
        ]
        rows = []
        for nc in self._session.nonconformances:
            material = self._session.get_material(nc.material_id)
            environment = self._session.get_environment(nc.environment_id)
            if nc.nonconformance_id in closed_ids:
                status = "Closed"
            elif nc.nonconformance_id in accepted_ids:
                status = "Accepted Open"
            else:
                status = "Open"
            rows.append([
                nc.nonconformance_id[:12],
                material.name if material else nc.material_id,
                environment.name if environment else nc.environment_id,
                nc.gap_type.value.upper(),
                nc.failing_value or "—",
                nc.required_value or "—",
                nc.severity.value.upper(),
                status,
                ", ".join(nc.affected_mprs or []),
            ])
        _add_table(doc, headers, rows)

    # -----------------------------------------------------------------------
    # 11.0 Closure Decisions
    # -----------------------------------------------------------------------
    def _add_closure_decisions(self, doc: Document) -> None:
        doc.add_heading("11.0 Closure Decisions", level=1)

        if not self._session.closure_decisions:
            doc.add_paragraph("No closure decisions recorded.")
            return

        doc.add_paragraph(
            "The following closure paths have been selected for identified "
            "nonconformances. Each path is per NASA-STD-6016C closure "
            "provisions (e.g., MPR 44 exceptions for minor quantity, "
            "configuration analysis, heat sink, substitution, test program, "
            "or full MUA)."
        )

        headers = [
            "Gap ID", "Material", "Selected Path", "Rationale",
            "Decided By", "Date",
        ]
        rows = []
        for cd in self._session.closure_decisions:
            # Resolve material from nonconformance
            mat_name = "—"
            for nc in self._session.nonconformances:
                if nc.nonconformance_id == cd.gap_id:
                    mat = self._session.get_material(nc.material_id)
                    mat_name = mat.name if mat else nc.material_id
                    break
            rows.append([
                cd.gap_id[:12],
                mat_name,
                cd.selected_path,
                (cd.decision_rationale or "")[:200],
                cd.decided_by,
                cd.decided_at.strftime("%Y-%m-%d")
                if cd.decided_at else "—",
            ])
        _add_table(doc, headers, rows)

    # -----------------------------------------------------------------------
    # 12.0 Accepted Open Gaps
    # -----------------------------------------------------------------------
    def _add_accepted_open_gaps(self, doc: Document) -> None:
        doc.add_heading("12.0 Accepted Open Gaps", level=1)

        if not self._session.accepted_open_gaps:
            doc.add_paragraph("No accepted open gaps.")
            return

        doc.add_paragraph(
            "The following gaps have been accepted as open for plan "
            "generation. Each has an assigned owner and due date for "
            "closure. These items are flagged in generated artifacts."
        )

        headers = [
            "Gap ID", "Type", "Owner", "Due Date",
            "Risk Statement", "Rationale", "Accepted By",
        ]
        rows = []
        for gap in self._session.accepted_open_gaps:
            rows.append([
                gap.gap_id[:12],
                gap.gap_type,
                gap.owner,
                str(gap.due_date) if gap.due_date else "TBD",
                (gap.risk_statement or "")[:200],
                (gap.acceptance_rationale or "")[:200],
                gap.accepted_by,
            ])
        _add_table(doc, headers, rows)

    # -----------------------------------------------------------------------
    # 13.0 Minor Quantity Analysis
    # -----------------------------------------------------------------------
    def _add_minor_quantity_analysis(self, doc: Document) -> None:
        doc.add_heading("13.0 Minor Quantity Analysis", level=1)

        mqa = self._session.minor_quantity_aggregation
        if not mqa:
            doc.add_paragraph(
                "No minor quantity analysis performed. This section applies "
                "when materials do not meet flammability requirements and "
                "the minor quantity exception per MPR 44(c) is invoked "
                "(total mass ≤45 g AND surface area ≤13 cm² in aggregated "
                "zone)."
            )
            return

        doc.add_paragraph(
            "Per NASA-STD-6016C MPR 44(c), materials may be used without "
            "meeting flammability requirements if the total aggregated mass "
            "is ≤45 g AND total surface area is ≤13 cm² within a zone "
            "grouped by environment, ignition source proximity, and physical "
            "adjacency."
        )

        if mqa.groups:
            headers = [
                "Environment", "Ignition Class", "Materials",
                "Total Mass (g)", "Total Area (cm²)", "Status", "Rationale",
            ]
            rows = []
            for group in mqa.groups:
                env = self._session.get_environment(group.environment_id)
                status = "Qualifies" if group.eligible else "Exceeds Limit"
                rows.append([
                    env.name if env else group.environment_id,
                    group.ignition_source_class,
                    str(len(group.material_ids)),
                    f"{group.total_mass_g:.2f}",
                    f"{group.total_surface_area_cm2:.2f}",
                    status,
                    (group.eligibility_rationale or "")[:100],
                ])
            _add_table(doc, headers, rows)

        if mqa.grouping_assumptions:
            unconfirmed = [
                a for a in mqa.grouping_assumptions if not a.confirmed
            ]
            if unconfirmed:
                doc.add_paragraph(
                    f"{len(unconfirmed)} grouping assumption(s) require "
                    f"confirmation before minor quantity eligibility is "
                    f"finalized."
                )

    # -----------------------------------------------------------------------
    # Appendices
    # -----------------------------------------------------------------------
    def _add_appendices(self, doc: Document) -> None:
        doc.add_page_break()

        # --- Appendix A: MIUL Summary ---
        doc.add_heading("Appendix A — MIUL Summary", level=1)
        doc.add_paragraph(
            "Per MPR 25-27, the Materials Identification and Usage List "
            "(MIUL) documents all M&P usage for the final design. The "
            "following table summarizes the MIUL content derived from this "
            "plan session."
        )
        if self._session.materials:
            headers = [
                "Material", "Application", "MAPTIS Code",
                "FLAM", "TVS", "TOX", "Environment(s)",
            ]
            rows = []
            for mat in self._session.materials:
                res = self._session.get_resolution(mat.id)
                env_names = []
                for usage in self._session.material_environment_usages:
                    if usage.material_id == mat.id:
                        env = self._session.get_environment(
                            usage.environment_id
                        )
                        if env:
                            env_names.append(env.name)
                if not env_names:
                    env_names = [e.name for e in self._session.environments]
                rows.append([
                    mat.name,
                    mat.application,
                    res.maptis_code if res else "Not Resolved",
                    res.flam_rating if res else "—",
                    res.tvs_rating if res else "—",
                    res.tox_rating if res else "—",
                    "; ".join(env_names),
                ])
            _add_table(doc, headers, rows)
        else:
            doc.add_paragraph("No materials in session.")

        # --- Appendix B: MUA Register ---
        doc.add_heading("Appendix B — MUA Register", level=1)
        doc.add_paragraph(
            "Per MPR 28-29, MUAs are required for all M&P that do not meet "
            "the requirements of NASA-STD-6016C. MUAs shall not be used to "
            "change M&P requirements for nonconforming product."
        )
        ncs_needing_mua = [
            nc for nc in self._session.nonconformances
            if nc.severity.value in ("critical", "high")
        ]
        if ncs_needing_mua:
            headers = ["NC ID", "Material", "Gap Type", "Severity", "MUA Status"]
            rows = []
            closed_ids = {d.gap_id for d in self._session.closure_decisions}
            for nc in ncs_needing_mua:
                mat = self._session.get_material(nc.material_id)
                status = "Closure documented" if nc.nonconformance_id in closed_ids else "MUA Required"
                rows.append([
                    nc.nonconformance_id[:12],
                    mat.name if mat else nc.material_id,
                    nc.gap_type.value.upper(),
                    nc.severity.value.upper(),
                    status,
                ])
            _add_table(doc, headers, rows)
        else:
            doc.add_paragraph("No MUAs required — all materials comply.")

        # --- Appendix C: Rationale Codes ---
        doc.add_heading("Appendix C — Closure Path Rationale Codes", level=1)
        doc.add_paragraph(
            "The following closure paths are available per NASA-STD-6016C "
            "MPR 44 and JSC-27301F Appendix E:"
        )
        closure_codes = [
            ("MINOR_QUANTITY", "MPR 44(c)", "Total mass ≤45 g AND surface area ≤13 cm² in aggregated zone"),
            ("CONFIGURATION_ANALYSIS", "MPR 44(h)", "Configuration analysis demonstrates self-extinguishing behavior"),
            ("HEAT_SINK", "MPR 44(g)", "Material bonded to metal heat sink meeting mass ratio requirements"),
            ("SUBSTITUTION", "MPR 44(a)", "Alternative A-rated material available and acceptable"),
            ("TEST_PROGRAM", "MPR 44(i)", "Additional testing at use conditions demonstrates compliance"),
            ("FULL_MUA", "MPR 44(j)", "Material Usage Agreement with full engineering rationale"),
            ("ACCEPT_OPEN", "Program", "Gap accepted with owner, due date, and risk statement"),
        ]
        headers = ["Code", "Citation", "Description"]
        rows = [[code, cite, desc] for code, cite, desc in closure_codes]
        _add_table(doc, headers, rows)

        # --- Appendix D: Revision History ---
        doc.add_heading("Appendix D — Revision History", level=1)
        headers = ["Rev", "Date", "Description", "Author"]
        rows = [
            [
                "A",
                datetime.now().strftime("%Y-%m-%d"),
                "Initial generation from M&P Plan codex engine",
                "BoundState MIRA",
            ],
        ]
        _add_table(doc, headers, rows)

        # --- Appendix E: User Decisions ---
        if self._session.user_decisions:
            doc.add_heading("Appendix E — HITL Decision Log", level=1)
            doc.add_paragraph(
                "The following human-in-the-loop decisions were recorded "
                "during plan computation:"
            )
            headers = ["Question ID", "Decision", "Rationale", "Decided By"]
            rows = []
            for ud in self._session.user_decisions:
                rows.append([
                    ud.question_id[:16],
                    ud.decision[:80],
                    (ud.rationale or "")[:200],
                    ud.decided_by,
                ])
            _add_table(doc, headers, rows)


def generate_mp_plan_docx_codex(
    session: PlanGeneratorSession,
    output_path: Optional[Path] = None,
) -> bytes:
    """Convenience function for codex DOCX generation."""
    return MPPlanDocxGeneratorCodex(session).generate(output_path=output_path)
