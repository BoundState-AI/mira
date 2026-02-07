#!/usr/bin/env python3
"""
Module: Miul Builder Compliant
Purpose: Builds MAPTIS-compliant MIUL from extraction JSON.

BoundState AI 2025
Version: 1.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Fran OpenAI 5 <noreply@openai.com>
Co-Authored-By: Grok 4.0 <noreply@x.ai>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: SWE-013, NASA-STD-8739.8B
Safety Critical: False
"""

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from datetime import datetime

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from mira.miul.v1_archive.tree_builder import TreeBuilder, BOMRow
from mira.miul.material_form_inference import infer_material_form

logger = logging.getLogger(__name__)

# MAPTIS MIUL column specification (38 columns)
MAPTIS_COLUMNS = [
    ("Index", "index", 8),
    ("Parent", "parent", 8),
    ("Part Number", "part_number", 25),
    ("Part Description", "part_description", 35),
    ("Nomenclature", "nomenclature", 35),
    ("NHA", "nha", 20),
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
    ("Document Title", "title", 35),
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


class MIULCompliantBuilder:
    """Builds MAPTIS-compliant MIUL from extraction JSON."""

    # Style definitions
    HEADER_FILL = PatternFill(start_color="1F4E79", end_color="1F4E79", fill_type="solid")
    HEADER_FONT = Font(bold=True, color="FFFFFF", size=10)
    ASSEMBLY_FILL = PatternFill(start_color="D6EAF8", end_color="D6EAF8", fill_type="solid")
    MIUL_ID_FILL = PatternFill(start_color="E8F5E9", end_color="E8F5E9", fill_type="solid")
    THIN_BORDER = Border(
        left=Side(style="thin"),
        right=Side(style="thin"),
        top=Side(style="thin"),
        bottom=Side(style="thin"),
    )

    def __init__(self, miul_number: str = "", miul_title: str = "", project: str = ""):
        """Initialize builder.

        Args:
            miul_number: MIUL identifier (e.g., "GPE" or "GPE-MIUL-001")
            miul_title: MIUL title/description
            project: Project name
        """
        self.miul_number = miul_number
        self.miul_title = miul_title
        self.project = project

    def build_from_json(self, json_path: Path, output_path: Optional[Path] = None) -> Path:
        """Build compliant MIUL from extractor v2 JSON.

        Args:
            json_path: Path to MIUL JSON from miul_extractor_v2
            output_path: Output Excel path (default: same name with .xlsx)

        Returns:
            Path to generated Excel file
        """
        json_path = Path(json_path)
        if output_path is None:
            output_path = json_path.with_name(json_path.stem + "_compliant.xlsx")
        output_path = Path(output_path)

        # Load JSON
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        # Infer MIUL number from filename if not set
        if not self.miul_number:
            self.miul_number = json_path.stem.replace("_MIUL", "").replace("_v2", "")
        if not self.miul_title:
            self.miul_title = f"{self.miul_number} Material Identification Usage List"
        if not self.project:
            self.project = data.get("project", self.miul_number)

        # Build compliant materials list
        compliant_materials = self._build_compliant_tree(data)

        # Create workbook
        wb = Workbook()
        ws = wb.active
        ws.title = "MIUL"

        # Write MIUL sheet
        self._write_miul_sheet(ws, compliant_materials)

        # Add summary sheet
        ws_summary = wb.create_sheet("Summary")
        self._write_summary_sheet(ws_summary, data, compliant_materials)

        # Save
        wb.save(str(output_path))
        logger.info(f"[MIUL] Wrote compliant MIUL to {output_path}")

        return output_path

    def _is_garbage_entry(self, part_number: str) -> bool:
        """Check if part number is garbage from bad title block extraction."""
        if not part_number:
            return True

        pn_upper = part_number.upper()
        clean_pn = part_number.split('(')[0].strip().upper()

        # Known garbage patterns from bad title block extractions
        garbage_patterns = [
            'UNLESS', 'OTHERWISE', 'SPECIFIED', 'TOLERANCES', 'INTERPRET',
            'NOTES', 'FINISH', 'CAMPUS BOX', 'DIMENSIONS',
            'PROPRIETARY', 'CONFIDENTIAL', 'THIRD ANGLE',
            'DO NOT SCALE', 'SHEET', 'SCALE',
        ]

        # Check for garbage words in the clean part number (before parentheses)
        for pattern in garbage_patterns:
            if pattern in clean_pn:
                return True

        # Reject pure material names like "15-5 PH SS"
        # These are materials, not part numbers
        if ' SS' in clean_pn and not clean_pn.startswith('SS'):
            return True
        if clean_pn.startswith('15-5') or clean_pn.startswith('17-4'):
            return True

        # Reject descriptive names without proper part number format
        # Valid part numbers have format like: GPE-010, MER07540-001, NAS1234
        # Invalid: "DOOR SHIM", "BRACKET", "PLATE" (no dashes or alphanumeric pattern)
        if '-' not in clean_pn:
            # Allow NAS/AN/MS standard parts (e.g., NAS1234, AN3-5)
            if not any(clean_pn.startswith(prefix) for prefix in ['NAS', 'AN', 'MS', 'HCC']):
                return True

        return False

    def _build_compliant_tree(self, data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Build compliant MIUL tree structure using TreeBuilder.

        Uses TreeBuilder for correct depth-first traversal and Parent/NHA assignment
        per MIUL_spec.pdf and MIUL_MUA.pdf Appendix F:
        - Row 1: MIUL Number, Parent=0 (identifier row)
        - Row 2: MIUL Number, Parent=0 (kicks off tree)
        - Row 3+: Parts with proper Parent/NHA from TreeBuilder
        - Last row: Index=-1 (EOF marker)

        Returns:
            List of compliant material dicts with proper Index/Parent/NHA
        """
        raw_materials = data.get("materials", [])

        # Load hierarchy map from extraction (child -> parent relationships)
        # This ensures we can populate NHA for materials where extraction missed it
        hierarchy = data.get("hierarchy", {})

        # Build set of known material part numbers for validation
        known_materials = set()
        for m in raw_materials:
            pn = self._clean_part_number(m.get("part_number", ""))
            if pn and pn != "Not provided":
                known_materials.add(pn.upper())

        # Clean hierarchy keys for easier lookup (remove .DRW suffixes, etc.)
        # Only include entries where parent exists in materials OR is a known assembly
        clean_hierarchy = {}
        invalid_parents = ("N/A", "NONE", "-", "NOT PROVIDED", "PRELIMINARY", "USED ON", "")

        for child, parent in hierarchy.items():
            child_clean = self._clean_part_number(child)
            parent_clean = self._clean_part_number(parent) if parent else ""

            # Skip invalid parent values
            if not parent_clean or parent_clean.upper() in invalid_parents:
                continue

            # Skip self-references (top assembly often points to itself)
            if child_clean.upper() == parent_clean.upper():
                continue

            # Validate parent exists in materials OR hierarchy (as another child)
            # This filters out bad title block extractions like -003 sub-components
            parent_upper = parent_clean.upper()
            parent_is_known = (
                parent_upper in known_materials or
                any(self._clean_part_number(k).upper() == parent_upper for k in hierarchy.keys())
            )

            if parent_is_known:
                clean_hierarchy[child_clean] = parent_clean
            else:
                logger.debug(f"Skipping invalid parent: {child_clean} -> {parent_clean} (parent not in materials)")

        if clean_hierarchy:
            logger.info(f"Loaded {len(clean_hierarchy)} hierarchy relationships from extraction")

        # Find top assembly and assign orphan assemblies to it
        # Orphans = parts that appear as parents in hierarchy but have no parent themselves
        top_assembly = data.get("top_assembly", "")
        if not top_assembly:
            # Infer top assembly: look for self-reference or part with most children
            for child, parent in hierarchy.items():
                child_clean = self._clean_part_number(child)
                parent_clean = self._clean_part_number(parent) if parent else ""
                if child_clean.upper() == parent_clean.upper() and child_clean:
                    top_assembly = child_clean
                    break

        if top_assembly:
            top_clean = self._clean_part_number(top_assembly)
            # Find parts that are parents but have no parent themselves
            children_in_hierarchy = set(k.upper() for k in clean_hierarchy.keys())
            parents_in_hierarchy = set(v.upper() for v in clean_hierarchy.values() if v)

            orphan_parents = parents_in_hierarchy - children_in_hierarchy - {top_clean.upper()}

            for orphan in orphan_parents:
                # Find the original case version
                for pn in known_materials:
                    if pn.upper() == orphan:
                        clean_hierarchy[pn] = top_clean
                        logger.info(f"Assigned orphan assembly {pn} -> {top_clean}")
                        break

        # Filter out garbage entries first
        filtered_garbage = []
        materials = []
        for m in raw_materials:
            pn = m.get("part_number", "")
            if self._is_garbage_entry(pn):
                filtered_garbage.append(pn)
            else:
                materials.append(m)

        if filtered_garbage:
            logger.info(f"Filtered {len(filtered_garbage)} garbage entries: {filtered_garbage[:5]}{'...' if len(filtered_garbage) > 5 else ''}")

        # Start building compliant list
        compliant = []

        # === Row 1: MIUL Identifier (Parent=0) ===
        cleaned_miul_number = self._clean_part_number(self.miul_number)
        row1 = {
            "index": 1,
            "parent": 0,
            "part_number": cleaned_miul_number,
            "part_description": self.miul_title,
            "nomenclature": self.miul_title,
            "nha": "",  # Row 1 has no NHA
            "material_type": "MIUL_ID",
            "project": self.project,
        }
        compliant.append(row1)

        # === Row 2: MIUL Identifier again (Parent=0, starts tree) ===
        row2 = {
            "index": 2,
            "parent": 0,
            "part_number": cleaned_miul_number,
            "part_description": self.miul_title,
            "nomenclature": self.miul_title,
            "nha": "",  # Row 2 - NHA blank per example
            "material_type": "MIUL_ID",
            "project": self.project,
        }
        compliant.append(row2)

        # Convert materials to BOMRow objects for TreeBuilder
        # TreeBuilder uses parent_ref field to build hierarchy
        bom_rows = []
        material_lookup = {}  # Map part_number -> original material dict
        seen_parts: set = set()

        for m in materials:
            pn = self._clean_part_number(m.get("part_number", ""))

            # Skip duplicates
            if pn in seen_parts:
                logger.debug(f"Skipping duplicate: {pn}")
                continue
            seen_parts.add(pn)

            # Store original material data for later
            material_lookup[pn] = m

            # Create BOMRow for TreeBuilder
            # parent_ref = NHA field from extraction OR hierarchy lookup
            nha_from_material = m.get("nha", "")

            # Treat invalid NHA values as empty (need to check hierarchy)
            invalid_nha_values = ("", "NOT PROVIDED", "N/A", "NONE", "-", "PRELIMINARY")
            nha_is_invalid = (
                not nha_from_material or
                not nha_from_material.strip() or
                nha_from_material.strip().upper() in invalid_nha_values
            )

            if nha_is_invalid:
                # Try hierarchy lookup if NHA is missing/invalid
                nha_from_material = clean_hierarchy.get(pn, "")
                if nha_from_material:
                    logger.debug(f"  {pn}: NHA from hierarchy -> {nha_from_material}")

            # If still no NHA, use source_drawing as parent (for components)
            if not nha_from_material or not nha_from_material.strip():
                source_drawing = self._clean_part_number(m.get("source_drawing", ""))
                if source_drawing and source_drawing.upper() != pn.upper():
                    # Use source_drawing as parent - TreeBuilder will handle orphans
                    nha_from_material = source_drawing
                    logger.debug(f"  {pn}: NHA from source_drawing -> {nha_from_material}")

            bom_row = BOMRow(
                part_number=pn,
                part_description=m.get("part_description", m.get("title", "")),
                parent_ref=nha_from_material,  # NHA from extraction OR hierarchy
                designation=m.get("designation", ""),
                material_code=m.get("material_code"),
                material_spec=m.get("material_spec"),
                drawing_source=self._clean_part_number(m.get("source_drawing", "")),
                manufacturer=m.get("manufacturer"),
            )
            bom_rows.append(bom_row)

        # Use TreeBuilder for correct DFS traversal and Parent/NHA assignment
        if bom_rows:
            builder = TreeBuilder(source=self.miul_number)
            result = builder.build(bom_rows)

            if result.warnings:
                for warning in result.warnings[:5]:
                    logger.warning(f"[TreeBuilder] {warning}")

            # Convert TreeBuilder result to compliant dict format
            # Offset indices by 2 (for header rows 1 & 2)
            for miul_row in result.tree.rows:
                if miul_row.index == -1:
                    continue  # Skip EOF - we'll add our own

                pn = miul_row.part_number
                orig = material_lookup.get(pn, {})

                # Offset index and parent by 2 for MIUL header rows
                new_index = miul_row.index + 2
                new_parent = miul_row.parent + 2 if miul_row.parent > 0 else 2

                # For top-level parts (parent=0 in TreeBuilder), set NHA to MIUL number
                # For other tree parts, NHA comes from TreeBuilder (parent's part number)
                # For components (no children), NHA is blank
                if miul_row.parent == 0:
                    # Top-level assembly: NHA = MIUL Number per MAPTIS spec
                    nha = cleaned_miul_number
                else:
                    # Sub-parts: TreeBuilder sets nha to parent part number for tree parts
                    # or blank for leaf components
                    nha = miul_row.nha or ""

                # Build base entry
                part_desc = miul_row.part_description or orig.get("part_description", "")
                nomenclature = orig.get("nomenclature", miul_row.part_description or "")
                designation = miul_row.designation or orig.get("designation", "")
                material_spec = miul_row.material_spec or orig.get("material_spec", "")
                existing_form = orig.get("form", "")

                # Infer material form if not already specified
                form_result = infer_material_form(
                    nomenclature=nomenclature,
                    part_description=part_desc,
                    designation=designation,
                    material_spec=material_spec,
                    existing_form=existing_form,
                )
                inferred_form = form_result.form

                if form_result.form and form_result.source != "existing":
                    logger.debug(
                        f"[FormInference] {pn}: form='{form_result.form}' "
                        f"(source={form_result.source}, conf={form_result.confidence:.2f})"
                    )

                entry = {
                    "index": new_index,
                    "parent": new_parent,
                    "part_number": pn,
                    "part_description": part_desc,
                    "nomenclature": nomenclature,
                    "nha": nha,
                    "change_letter": orig.get("change_letter", ""),
                    "source_drawing": miul_row.drawing_source or orig.get("source_drawing", ""),
                    "form": inferred_form,
                    "manufacturer": miul_row.manufacturer or orig.get("manufacturer", ""),
                    "designation": designation,
                    "material_spec": material_spec,
                    "process_spec": orig.get("process_spec", ""),
                    "material_code": miul_row.material_code or orig.get("material_code", ""),
                    "material_type": orig.get("material_type", ""),
                    "qty": orig.get("qty", 1),
                    "project": self.project,
                    "is_helicoil": orig.get("is_helicoil", False),
                    "helicoil_details": orig.get("helicoil_details"),
                }
                compliant.append(entry)

            logger.info(f"[TreeBuilder] Built tree: format={result.detected_format.value}, "
                       f"roots={result.root_count}, orphans={result.orphan_count}")

        # === Final Row: EOF marker (Index=-1) ===
        eof_row = {
            "index": -1,
            "parent": None,
            "part_number": "",
            "part_description": "",
            "nomenclature": "",
            "nha": "",
            "material_type": "EOF",
        }
        compliant.append(eof_row)

        logger.info(f"Built compliant tree: {len(compliant)-1} data rows + EOF marker")
        return compliant

    def _clean_part_number(self, pn: str) -> str:
        """Clean part number - remove description in parentheses and file extensions.

        GPE-052-A (ROD CONNECTOR DRAWING) -> GPE-052-A
        MER07540-001.DRW_-.20_RELEASED -> MER07540-001
        """
        if not pn:
            return ""
        cleaned = pn
        # Remove content in parentheses
        if "(" in cleaned:
            cleaned = cleaned.split("(")[0].strip()
        # Remove .DRW and everything after it (file extension/version info)
        if ".DRW" in cleaned.upper():
            idx = cleaned.upper().find(".DRW")
            cleaned = cleaned[:idx]
        return cleaned.strip()

    def _write_miul_sheet(self, ws, materials: List[Dict[str, Any]]) -> None:
        """Write main MIUL data sheet."""
        # Write headers
        for col_idx, (header, _, width) in enumerate(MAPTIS_COLUMNS, start=1):
            cell = ws.cell(row=1, column=col_idx, value=header)
            cell.fill = self.HEADER_FILL
            cell.font = self.HEADER_FONT
            cell.border = self.THIN_BORDER
            cell.alignment = Alignment(horizontal="center", wrap_text=True)
            ws.column_dimensions[get_column_letter(col_idx)].width = width

        # Write material rows
        for row_idx, mat in enumerate(materials, start=2):
            self._write_material_row(ws, row_idx, mat)

        # Freeze header row
        ws.freeze_panes = "A2"

    def _write_material_row(self, ws, row_idx: int, mat: Dict[str, Any]) -> None:
        """Write single material row."""
        is_miul_id = mat.get("material_type") == "MIUL_ID"
        is_eof = mat.get("material_type") == "EOF"
        is_assembly = mat.get("material_type") == "ASSEMBLY"

        for col_idx, (header, key, _) in enumerate(MAPTIS_COLUMNS, start=1):
            if header == "Index":
                value = mat.get("index", "")
            elif header == "Parent":
                value = mat.get("parent", "")
                if value is None:
                    value = ""
            elif header == "Part Number":
                value = mat.get("part_number", "")
            elif header == "Part Description":
                value = mat.get("part_description", "")
            elif header == "Nomenclature":
                value = mat.get("nomenclature", mat.get("part_description", ""))
            elif header == "NHA":
                value = mat.get("nha", "")
            elif header == "Project":
                value = mat.get("project", self.project)
            elif header == "Remarks" and mat.get("is_helicoil"):
                details = mat.get("helicoil_details", {})
                value = f"Thread: {details.get('thread_size', '')} {details.get('thread_class', '')}"
            elif key in mat:
                value = mat[key]
            else:
                value = ""

            cell = ws.cell(row=row_idx, column=col_idx, value=value)
            cell.border = self.THIN_BORDER

            # Apply row highlighting
            if is_miul_id:
                cell.fill = self.MIUL_ID_FILL
            elif is_assembly:
                cell.fill = self.ASSEMBLY_FILL

    def _write_summary_sheet(self, ws, data: Dict[str, Any], materials: List[Dict[str, Any]]) -> None:
        """Write summary statistics sheet."""
        ws.column_dimensions["A"].width = 35
        ws.column_dimensions["B"].width = 25

        # Count material types (excluding MIUL_ID and EOF rows)
        data_materials = [m for m in materials if m.get("material_type") not in ("MIUL_ID", "EOF")]

        rows = [
            ("MIUL Summary - MAPTIS Compliant", ""),
            ("", ""),
            ("MIUL Number", self.miul_number),
            ("MIUL Title", self.miul_title),
            ("Project", self.project),
            ("Generated", datetime.now().strftime("%Y-%m-%d %H:%M")),
            ("Extraction Method", data.get("extraction_method", "unknown")),
            ("", ""),
            ("Structure Compliance", ""),
            ("Row 1-2: MIUL Identifier", "Yes (Parent=0)"),
            ("Row 3+: Parts", f"{len(data_materials)} parts"),
            ("EOF Row (Index=-1)", "Yes"),
            ("", ""),
            ("Statistics", ""),
            ("Total Data Rows", len(data_materials)),
            ("Assemblies", sum(1 for m in data_materials if m.get("material_type") == "ASSEMBLY")),
            ("Detail Parts", sum(1 for m in data_materials if m.get("material_type") != "ASSEMBLY")),
            ("Helicoils", sum(1 for m in data_materials if m.get("is_helicoil"))),
        ]

        for row_idx, (label, value) in enumerate(rows, start=1):
            ws.cell(row=row_idx, column=1, value=label)
            ws.cell(row=row_idx, column=2, value=value)

            if label in ("MIUL Summary - MAPTIS Compliant", "Structure Compliance", "Statistics"):
                ws.cell(row=row_idx, column=1).font = Font(bold=True)


def build_compliant_miul(json_path: str, output_path: str = None,
                         miul_number: str = "", project: str = "") -> Path:
    """Build MAPTIS-compliant MIUL Excel from extractor JSON.

    Args:
        json_path: Path to MIUL JSON file
        output_path: Output Excel path (optional)
        miul_number: MIUL identifier
        project: Project name

    Returns:
        Path to generated Excel file
    """
    builder = MIULCompliantBuilder(miul_number=miul_number, project=project)
    return builder.build_from_json(Path(json_path), Path(output_path) if output_path else None)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Build MAPTIS-compliant MIUL from extraction JSON")
    parser.add_argument("json_file", type=Path, help="Input JSON from miul_extractor_v2")
    parser.add_argument("-o", "--output", type=Path, help="Output Excel path")
    parser.add_argument("-n", "--miul-number", default="", help="MIUL identifier number")
    parser.add_argument("-p", "--project", default="", help="Project name")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    output = build_compliant_miul(
        args.json_file,
        args.output,
        miul_number=args.miul_number,
        project=args.project,
    )
    print(f"Generated: {output}")
