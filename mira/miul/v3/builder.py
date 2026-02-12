#!/usr/bin/env python3
"""
Module: MIUL Builder v3
Purpose: Complete MIUL generation using v3 enhanced extraction.

Workflow:
1. Extract all drawings from PDF directory using v3 vision extraction
2. Build drawing graph with parent-child relationships
3. Traverse graph to generate MIUL entries
4. Enrich with material codes and ratings
5. Export to Excel

BoundState AI 2025
Version: 3.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: SWE-013, NASA-STD-8739.8B, JSC 27301F
Safety Critical: True
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter, column_index_from_string

from .extract import (
    extract_drawing_page,
    extract_drawing_tree,
    extract_parts_json,
    VisionClient,
    postprocess_extraction,
)
from .text_extract import (
    extract_drawing as extract_drawing_text,
    has_text_layer,
)
from .ocr_correction import (
    correct_ocr_errors,
    clean_material_spec,
    clean_designation,
    correct_part_number,
    lookup_standard_part_material,
    normalize_designation,
    normalize_material_spec,
)

LOGGER = logging.getLogger(__name__)

# JSC 27301F Section 4.2.1 MIUL columns
MIUL_COLUMNS = [
    "Index",
    "Parent",
    "Part Number",
    "Part Description",
    "Nomenclature",
    "NHA",
    "Change Letter",
    "Drawing Source",
    "Material Form",
    "Material Manufacturer",
    "Designation",
    "Material Specification",
    "Process Specification",
    "Environment",
    "Material Code",
    "Standard Part Number",
    "Contractor",
    "System",
    "Subsystem",
    "Max Temperature",
    "Min Temperature",
    "Fluid Type",
    "Associate Contractor",
    "Project",
    "Document Title",
    "Criticality",
    "Line Number",
    "Overall Evaluation",
    "Configuration Test",
    "Max Pressure",
    "Min Pressure",
    "MUA Rationale",
    "Cure Codes",
    "FLAM",
    "SCC",
    "CORR",
    "TVS",
    "TOX",
    "FS",
    "Remarks",
]


@dataclass
class DrawingData:
    """Extracted data for a single drawing."""
    drawing_number: str
    title: str = ""
    revision: str = ""
    material_designation: str = ""
    material_spec: str = ""
    uns_number: str = ""
    process_spec: str = ""
    nha: str = ""
    drawing_type: str = "DETAIL"
    source_file: str = ""
    parts_list: List[Dict[str, Any]] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)
    extraction_method: str = ""  # "text_layer" or "vision"


@dataclass
class MIULRow:
    """Single row in the MIUL output."""
    index: int
    parent: int
    part_number: str
    part_description: str = ""
    nomenclature: str = ""
    nha: str = ""
    change_letter: str = ""
    drawing_source: str = ""
    material_form: str = ""
    material_manufacturer: str = ""
    designation: str = ""
    material_specification: str = ""
    process_specification: str = ""
    material_code: str = ""


@dataclass
class EnvironmentConfig:
    """
    Environment parameters for MIUL generation.

    Per MIUL_GENERATION_INSTRUCTIONS.md Section "Secondary Payload Default Environment":
    - O2 %: 20.9
    - Max Pressure: 14.7 psia
    - Min Pressure: 0 psia (vacuum exposure)
    - Max Temp: 120°F
    - Min Temp: 0°F
    - Media: Air, VAC

    Fluid Type indicates the service environment (O2, H2, etc.) which affects
    rating requirements per NASA-STD-6016.
    """
    max_temp: float = 120.0       # Max temperature °F
    min_temp: float = 0.0         # Min temperature °F
    max_pressure: float = 14.7    # Max pressure psia
    min_pressure: float = 0.0     # Min pressure psia (0 = vacuum)
    fluid_type: str = "Air"       # Service fluid: Air, O2, H2, N2, etc.
    environment: str = "Air, VAC" # Environment media description
    o2_percent: float = 20.9      # Oxygen percentage (ambient = 20.9)


# Default environment for secondary payloads
SECONDARY_PAYLOAD_ENV = EnvironmentConfig()

# Hydrogen environment preset
H2_ENVIRONMENT = EnvironmentConfig(
    max_temp=200.0,
    min_temp=-423.0,  # LH2 boiling point
    max_pressure=6000.0,
    min_pressure=0.0,
    fluid_type="H2",
    environment="GH2, LH2",
    o2_percent=0.0,
)

# Oxygen environment preset
O2_ENVIRONMENT = EnvironmentConfig(
    max_temp=120.0,
    min_temp=-297.0,  # LOX boiling point
    max_pressure=3000.0,
    min_pressure=0.0,
    fluid_type="O2",
    environment="GOX, LOX",
    o2_percent=100.0,
)


# =============================================================================
# Drawing Tree File Detection
# =============================================================================

def _is_dt_file(filename: str) -> bool:
    """
    Check if a file is a Drawing Tree document.

    Supports multiple naming conventions:
    - MER07540-DT.DRW_-.6.pdf (MSFC style with -DT suffix)
    - GPE-DOC-004-D (GPE Drawing Tree).pdf (descriptive name)
    - DrawingTree.pdf (simple name)

    Args:
        filename: The filename to check (just the name, not full path)

    Returns:
        True if the file appears to be a Drawing Tree document
    """
    name_upper = filename.upper()
    return (
        "-DT." in name_upper or         # MER07540-DT.DRW
        "-DT " in name_upper or         # Something-DT (with space)
        "-DT_" in name_upper or         # MER07540-DT_something.pdf
        "_DT." in name_upper or         # Something_DT.pdf
        "DRAWING TREE" in name_upper or # GPE-DOC-004 (GPE Drawing Tree).pdf
        "DRAWINGTREE" in name_upper or  # DrawingTree.pdf
        " DT." in name_upper or         # Something DT.pdf
        name_upper.endswith("-DT.PDF")  # Ends with -DT.pdf
    )


# =============================================================================
# Material Form Inference
# =============================================================================

# Map spec numbers/patterns to material forms
# Based on common aerospace material specifications
SPEC_FORM_MAP = {
    # Bar / Rod
    "B211": "BAR",
    "AMS 5737": "BAR",
    "AMS 5731": "BAR",
    "AMS 5732": "BAR",
    "AMS 5525": "BAR",
    "AMS 5853": "BAR",
    "AMS 5664": "BAR",
    "AMS 5666": "BAR",
    "AMS 5596": "SHEET",  # Inconel 718 sheet/strip
    "QQ-A-200": "BAR",
    "QQ-A-225": "BAR",

    # Plate / Sheet
    "AMS-QQ-A-250": "PLATE",
    "QQ-A-250": "PLATE",
    "AMS 4027": "PLATE",
    "AMS 4037": "PLATE",
    "AMS 4044": "PLATE",
    "AMS 4050": "PLATE",

    # Casting
    "AMS-4217": "CASTING",
    "AMS 4217": "CASTING",
    "B505": "CASTING",

    # Forging
    "AMS 5735": "FORGING",
    "AMS 5736": "FORGING",
    "AMS 5738": "FORGING",

    # Sheet / Strip
    "D1710": "SHEET",  # PCTFE sheet

    # Tubing
    "AMS 5556": "TUBING",
    "AMS 5557": "TUBING",
}

# Designation keywords that indicate form
DESIGNATION_FORM_KEYWORDS = {
    "PLATE": "PLATE",
    "SHEET": "SHEET",
    "BAR": "BAR",
    "ROD": "BAR",
    "FORGING": "FORGING",
    "CASTING": "CASTING",
    "TUBING": "TUBING",
    "TUBE": "TUBING",
    "WIRE": "WIRE",
}


def _infer_material_form(spec: str, designation: str) -> str:
    """
    Infer material form (bar, plate, sheet, casting, etc.) from
    the material specification and designation.

    Args:
        spec: Material specification (e.g., 'SAE AMS 5737', 'ASTM B211')
        designation: Material designation (e.g., 'A286 CRES', '7075-T6 ALUMINUM')

    Returns:
        Material form string, or empty if can't be determined
    """
    if not spec and not designation:
        return ""

    # Check spec against known mappings
    if spec:
        spec_upper = spec.upper()
        for spec_key, form in SPEC_FORM_MAP.items():
            if spec_key.upper() in spec_upper:
                return form

    # Check designation for form keywords
    if designation:
        desig_upper = designation.upper()
        for keyword, form in DESIGNATION_FORM_KEYWORDS.items():
            # Use word boundary matching to avoid false positives
            if keyword in desig_upper.split():
                return form

    return ""


class MIULBuilderV3:
    """
    MIUL Builder using v3 enhanced extraction.

    Extracts materials from:
    - Title block MATERIAL field
    - NOTES section (MSFC format with "MATERIAL:" keyword)
    - Flag notes (numbered balloons pointing to material)
    - EPL MATERIAL column

    NHA Assignment Priority:
    1. Manual overrides from JSON file (highest authority)
    2. Drawing Tree (DT) extraction (authoritative for MER parts)
    3. EPL-based inference (only for standard hardware MS/NAS/AN)
    """

    def __init__(self, client: VisionClient = None):
        """Initialize builder with optional vision client."""
        self.client = client or VisionClient()
        self.drawings: Dict[str, DrawingData] = {}
        self.dt_tree: Dict[str, Any] = {}  # Drawing Tree hierarchy
        self.nha_overrides: Dict[str, str] = {}  # Manual NHA overrides
        self.issues: List[str] = []

    def load_nha_overrides(self, override_path: Path) -> Dict[str, str]:
        """
        Load manual NHA overrides from a JSON file.

        The override file provides authoritative NHA mappings that take
        precedence over both DT extraction and EPL inference. Use this
        to correct any extraction errors or provide mappings for complex
        drawing tree structures that the vision model struggles with.

        Args:
            override_path: Path to JSON file with format:
                {
                    "MER07546-001": "MER07545-001",
                    "MER07553-001": "MER07545-001",
                    ...
                }

        Returns:
            Dict mapping child_pn -> parent_pn
        """
        if not override_path.exists():
            LOGGER.warning(f"[MIULBuilder] NHA override file not found: {override_path}")
            return {}

        try:
            with open(override_path, "r", encoding="utf-8") as f:
                overrides = json.load(f)

            # Validate and clean the overrides
            cleaned = {}
            for child, parent in overrides.items():
                child = correct_part_number(str(child).strip())
                parent = str(parent).strip()
                if child and parent:
                    cleaned[child] = parent

            LOGGER.info(f"[MIULBuilder] Loaded {len(cleaned)} NHA overrides from {override_path}")
            return cleaned

        except json.JSONDecodeError as e:
            LOGGER.error(f"[MIULBuilder] Invalid JSON in NHA override file: {e}")
            self.issues.append(f"NHA override file JSON error: {e}")
            return {}
        except Exception as e:
            LOGGER.error(f"[MIULBuilder] Error loading NHA overrides: {e}")
            self.issues.append(f"NHA override load error: {e}")
            return {}

    def _extract_alpha_prefix(self, part_number: str) -> str:
        """
        Extract alphabetic prefix from a part number.

        Handles various part number patterns:
        - MER07540-001 -> "MER"
        - GPE-A000-1 -> "GPE"
        - ABC12345-001 -> "ABC"

        Args:
            part_number: The part number to extract prefix from

        Returns:
            Alphabetic prefix (uppercase), or empty string if none found
        """
        import re
        if not part_number:
            return ""
        # Match leading letters, optionally followed by hyphen (for GPE- style)
        match = re.match(r'^([A-Z]+)-?', part_number.upper())
        return match.group(1) if match else ""

    def _detect_project_prefix(self) -> str:
        """
        Auto-detect the project drawing number prefix.

        Detection priority:
        1. From DT tree root (top-level assembly)
        2. From DT tree entries (first root node found)
        3. From extracted drawings (most common prefix)

        Examples:
            MER07540-001 -> "MER"
            GPE-A000-1 -> "GPE"
            ABC12345-001 -> "ABC"

        Returns:
            Detected prefix (uppercase), or empty string if can't detect
        """
        from collections import Counter

        # Priority 1: From DT tree top_level
        if self.dt_tree and self.dt_tree.get("top_level"):
            root_pn = self.dt_tree["top_level"]
            prefix = self._extract_alpha_prefix(root_pn)
            if prefix:
                return prefix

        # Priority 2: From DT tree entries (find root node)
        if self.dt_tree and self.dt_tree.get("tree"):
            for entry in self.dt_tree["tree"]:
                if not entry.get("parent"):  # Root node has no parent
                    pn = entry.get("drawing_number", "")
                    if pn:
                        prefix = self._extract_alpha_prefix(pn)
                        if prefix:
                            return prefix

        # Priority 3: From extracted drawings (most common prefix)
        if self.drawings:
            prefixes = []
            for dwg_num in self.drawings.keys():
                prefix = self._extract_alpha_prefix(dwg_num)
                if prefix:
                    prefixes.append(prefix)
            if prefixes:
                # Return most common prefix
                return Counter(prefixes).most_common(1)[0][0]

        return ""

    def _is_project_part(self, part_number: str, project_prefix: str) -> bool:
        """
        Check if a part number belongs to this project (not standard hardware).

        Standard hardware parts (MS, NAS, AN, etc.) don't belong to any specific
        project and should use EPL inference for NHA assignment.

        Args:
            part_number: The part number to check
            project_prefix: The detected project prefix (e.g., "MER", "GPE")

        Returns:
            True if this is a project-specific drawing, False if standard hardware
        """
        if not project_prefix or not part_number:
            return False
        return part_number.upper().startswith(project_prefix.upper())

    def extract_directory(
        self,
        directory: Path,
        nha_override_path: Path = None
    ) -> Dict[str, DrawingData]:
        """
        Extract all PDFs in a directory.

        Strategy:
        1. Load NHA overrides if provided (highest priority)
        2. Extract Drawing Tree (DT) file first to get assembly hierarchy
        3. Extract each drawing PDF (all pages) for material/EPL data
        4. Use DT hierarchy + overrides to validate and correct NHA assignments

        Args:
            directory: Path to directory containing PDFs
            nha_override_path: Optional path to JSON file with manual NHA overrides

        Returns:
            Dict mapping drawing_number to DrawingData
        """
        # Load NHA overrides if provided
        if nha_override_path:
            self.nha_overrides = self.load_nha_overrides(nha_override_path)
        from .extract import pdf_to_images

        pdf_files = sorted(directory.glob("*.pdf"))
        # Use generic DT detection that handles multiple naming conventions
        dt_files = [f for f in pdf_files if _is_dt_file(f.name)]
        drawing_files = [f for f in pdf_files if not _is_dt_file(f.name)]

        LOGGER.info(f"[MIULBuilder] Found {len(drawing_files)} drawings, {len(dt_files)} DT files in {directory}")

        # Step 1: Extract Drawing Tree (if present) for assembly hierarchy
        for dt_path in dt_files:
            try:
                LOGGER.info(f"[MIULBuilder] Extracting Drawing Tree: {dt_path.name}")
                self.dt_tree = extract_drawing_tree(dt_path, self.client)
                if self.dt_tree and self.dt_tree.get("tree"):
                    LOGGER.info(
                        f"[MIULBuilder] DT extracted: {len(self.dt_tree['tree'])} entries, "
                        f"top_level={self.dt_tree.get('top_level', '?')}"
                    )
                else:
                    self.issues.append(f"DT extraction returned no tree: {dt_path.name}")
            except Exception as e:
                self.issues.append(f"DT extraction error {dt_path.name}: {e}")
                LOGGER.error(f"  Error extracting DT {dt_path.name}: {e}")

        # Step 2: Extract each drawing PDF (all pages)
        # Strategy: Try text extraction first (free, fast, accurate for CAD PDFs)
        # Fall back to Vision only for scanned PDFs without text layers
        for pdf_path in drawing_files:
            try:
                # Try text layer extraction first (for CAD-generated PDFs)
                use_text_extraction = False
                try:
                    if has_text_layer(pdf_path):
                        text_result = extract_drawing_text(pdf_path)
                        if text_result and text_result.get("drawing_number") != "UNKNOWN":
                            use_text_extraction = True
                            LOGGER.info(f"  Extracting {pdf_path.name} via TEXT LAYER (fast)")
                            result = self._convert_text_result(text_result, pdf_path)
                except Exception as e:
                    LOGGER.warning(f"  Text extraction failed for {pdf_path.name}: {e}")
                    use_text_extraction = False

                # Fall back to Vision extraction for scans
                if not use_text_extraction:
                    images = pdf_to_images(pdf_path)
                    num_pages = len(images)

                    if num_pages == 0:
                        self.issues.append(f"No pages in PDF: {pdf_path.name}")
                        continue

                    LOGGER.info(f"  Extracting {pdf_path.name} via VISION ({num_pages} page{'s' if num_pages > 1 else ''})")

                    # Extract first page (always — contains title block)
                    result = extract_drawing_page(pdf_path, 0, self.client)
                    if not result:
                        self.issues.append(f"No extraction result: {pdf_path.name}")
                        continue

                    # For multi-page PDFs, extract additional pages and merge EPL data
                    if num_pages > 1:
                        drawing = self._result_to_drawing_data(result)
                        for page_idx in range(1, num_pages):
                            try:
                                page_result = extract_drawing_page(pdf_path, page_idx, self.client)
                                if page_result:
                                    self._merge_page_data(drawing, page_result)
                                    LOGGER.info(
                                        f"    Page {page_idx+1}: +{len(page_result.get('parts_list', []))} parts"
                                    )
                            except Exception as e:
                                LOGGER.warning(f"    Page {page_idx+1} extraction failed: {e}")
                        self.drawings[drawing.drawing_number] = drawing
                        LOGGER.info(
                            f"  {drawing.drawing_number}: {drawing.material_designation or 'NO MATERIAL'}"
                            f" ({len(drawing.parts_list)} EPL parts)"
                        )
                        continue

                drawing = self._result_to_drawing_data(result)
                if not drawing.drawing_number:
                    self.issues.append(f"No drawing number: {pdf_path.name}")
                    continue

                self.drawings[drawing.drawing_number] = drawing
                LOGGER.info(
                    f"  {drawing.drawing_number}: {drawing.material_designation or 'NO MATERIAL'}"
                    f" ({len(drawing.parts_list)} EPL parts)"
                )

            except Exception as e:
                self.issues.append(f"Extraction error {pdf_path.name}: {e}")
                LOGGER.error(f"  Error extracting {pdf_path.name}: {e}")

        LOGGER.info(f"[MIULBuilder] Extracted {len(self.drawings)} drawings")
        return self.drawings

    def _merge_page_data(self, drawing: DrawingData, page_result: Dict[str, Any]) -> None:
        """
        Merge extraction data from an additional page into the main drawing.

        Additional pages may contain:
        - More EPL rows (continuation of parts list)
        - Additional notes (material notes, process specs)
        - Material data not on page 1

        Args:
            drawing: The main DrawingData to merge into
            page_result: Extraction result from an additional page
        """
        # Merge EPL parts (avoid duplicates by find_no)
        existing_find_nos = {
            str(p.get("find_no", "")).strip()
            for p in drawing.parts_list
            if p.get("find_no")
        }
        for part in page_result.get("parts_list", []):
            find_no = str(part.get("find_no", "")).strip()
            if find_no and find_no in existing_find_nos:
                continue  # Skip duplicate
            drawing.parts_list.append(part)
            if find_no:
                existing_find_nos.add(find_no)

        # Merge notes
        existing_notes = set(drawing.notes)
        for note in page_result.get("notes", []):
            if note not in existing_notes:
                drawing.notes.append(note)
                existing_notes.add(note)

        # Fill in material if page 1 was empty
        tb = page_result.get("title_block", {})
        if not drawing.material_designation and tb.get("material_designation"):
            drawing.material_designation = tb["material_designation"]
            drawing.material_spec = tb.get("material_spec", drawing.material_spec)
            drawing.uns_number = tb.get("uns_number", drawing.uns_number)
            drawing.process_spec = tb.get("process_spec", drawing.process_spec)
            LOGGER.info(
                f"    Material found on later page: {drawing.material_designation}"
            )

    def _convert_text_result(self, text_result: Dict[str, Any], pdf_path: Path) -> Dict[str, Any]:
        """
        Convert text_extract result format to the format expected by _result_to_drawing_data.

        The text extractor returns a different structure than the Vision extractor,
        so we normalize it here.
        """
        tb = text_result.get("title_block", {})
        epl = text_result.get("epl") or {}
        parts = epl.get("parts", [])

        # Convert parts list format
        converted_parts = []
        for p in parts:
            converted_parts.append({
                "find_no": str(p.get("find_no", "")),
                "part_number": p.get("part_number", ""),
                "description": p.get("description", ""),
                "quantity": p.get("qty_001") or p.get("qty_003") or 1,
                "material_callout": p.get("material", ""),  # Key must match _process_assembly()
                "spec_callout": "",  # Text layer EPL doesn't have separate spec column
                "cage_code": p.get("cage_code", ""),
                "is_alternate": p.get("is_alternate", False),
            })

        # Convert notes format
        notes = [n.get("text", "") for n in text_result.get("notes", [])]

        return {
            "title_block": {
                "drawing_number": text_result.get("drawing_number", ""),
                "title": tb.get("title", ""),
                "revision": tb.get("revision", ""),
                "material_designation": tb.get("material", ""),
                "material_spec": tb.get("material_spec", ""),
                "uns_number": tb.get("uns_number", ""),
                "process_spec": tb.get("process_spec", ""),
                "nha_part_number": tb.get("nha", ""),
                "weight": tb.get("weight_lbs"),
                "cage_code": tb.get("cage_code", ""),
                "designer": tb.get("designer", ""),
                "engineer": tb.get("engineer", ""),
            },
            "drawing_type": "ASSEMBLY" if text_result.get("has_epl") else "DETAIL",
            "source_file": str(pdf_path),
            "parts_list": converted_parts,
            "notes": notes,
            "extraction_method": "text_layer",
        }

    def _result_to_drawing_data(self, result: Dict[str, Any]) -> DrawingData:
        """Convert extraction result to DrawingData."""
        tb = result.get("title_block", {})

        return DrawingData(
            drawing_number=tb.get("drawing_number", ""),
            title=tb.get("title", ""),
            revision=tb.get("revision", ""),
            material_designation=tb.get("material_designation", ""),
            material_spec=tb.get("material_spec", ""),
            uns_number=tb.get("uns_number", ""),
            process_spec=tb.get("process_spec", ""),
            nha=tb.get("nha_part_number", ""),
            drawing_type=result.get("drawing_type", "DETAIL"),
            source_file=result.get("source_file", ""),
            parts_list=result.get("parts_list", []),
            notes=result.get("notes", []),
            extraction_method=result.get("extraction_method", ""),
        )

    def _validate_dt_tree(self) -> List[str]:
        """
        Validate the extracted Drawing Tree for structural issues.

        Checks for:
        1. Cycles (A -> B -> A)
        2. Self-references (A -> A)
        3. Missing parents (child references non-existent parent)
        4. Multiple roots (more than one node with null parent)
        5. Orphaned subtrees (nodes disconnected from root)
        6. Structural anomalies suggesting extraction errors

        Returns:
            List of validation warning messages
        """
        warnings = []

        if not self.dt_tree or not self.dt_tree.get("tree"):
            return warnings

        tree_entries = self.dt_tree["tree"]

        # Build lookup structures
        all_nodes = set()
        children_of: Dict[str, List[str]] = {}  # parent -> [children]
        parent_of: Dict[str, str] = {}  # child -> parent
        roots = []

        for entry in tree_entries:
            child = entry.get("drawing_number", "").strip()
            parent = (entry.get("parent") or "").strip()

            if not child:
                continue

            all_nodes.add(child)
            if parent:
                all_nodes.add(parent)
                parent_of[child] = parent
                if parent not in children_of:
                    children_of[parent] = []
                children_of[parent].append(child)
            else:
                roots.append(child)

        # Check 1: Self-references
        for child, parent in parent_of.items():
            if child == parent:
                warnings.append(f"DT VALIDATION: Self-reference detected: {child} -> {child}")

        # Check 2: Cycles
        def has_cycle(node: str, visited: set, path: set) -> bool:
            if node in path:
                return True
            if node in visited:
                return False
            visited.add(node)
            path.add(node)
            for child in children_of.get(node, []):
                if has_cycle(child, visited, path):
                    return True
            path.remove(node)
            return False

        visited = set()
        for root in roots:
            if has_cycle(root, visited, set()):
                warnings.append(f"DT VALIDATION: Cycle detected in tree starting from {root}")

        # Check 3: Multiple roots
        if len(roots) > 1:
            warnings.append(
                f"DT VALIDATION: Multiple roots detected: {roots}. "
                f"Expected single top-level assembly."
            )
        elif len(roots) == 0 and tree_entries:
            warnings.append("DT VALIDATION: No root node (null parent) found in tree!")

        # Check 4: Missing parents (child references non-existent parent)
        missing_parent_count = 0
        for child, parent in parent_of.items():
            parent_has_entry = any(
                e.get("drawing_number", "").strip() == parent
                for e in tree_entries
            )
            if not parent_has_entry:
                missing_parent_count += 1
                warnings.append(
                    f"DT VALIDATION: {child} references parent {parent} "
                    f"which has no entry in the tree"
                )

        # Check 5: Depth sanity - if a DT has > 10 levels, something is likely wrong
        def get_max_depth(node: str, current_depth: int, visited: set) -> int:
            if node in visited:
                return current_depth
            visited.add(node)
            max_d = current_depth
            for child in children_of.get(node, []):
                max_d = max(max_d, get_max_depth(child, current_depth + 1, visited))
            return max_d

        for root in roots:
            max_depth = get_max_depth(root, 0, set())
            if max_depth > 10:
                warnings.append(
                    f"DT VALIDATION: Unusually deep tree ({max_depth} levels) from {root}. "
                    f"Verify hierarchy is correct."
                )

        # Check 6: Structural anomaly - too many direct children of root suggests flattening
        if roots:
            root = roots[0]
            direct_children = len(children_of.get(root, []))
            if direct_children > 15 and len(tree_entries) > 20:
                warnings.append(
                    f"DT VALIDATION WARNING: Root {root} has {direct_children} direct children. "
                    f"This may indicate the hierarchy was flattened (intermediate levels missed). "
                    f"Consider providing an NHA override file for accurate hierarchy."
                )
                self.issues.append(
                    "DT extraction may have flattened hierarchy - recommend using NHA overrides"
                )

        # Log warnings
        for w in warnings:
            LOGGER.warning(f"[MIULBuilder] {w}")
            if w not in self.issues:
                self.issues.append(w)

        if not warnings:
            LOGGER.info(
                f"[MIULBuilder] DT validation passed: {len(tree_entries)} entries, "
                f"{len(roots)} root(s), max depth OK"
            )
        elif missing_parent_count > len(tree_entries) * 0.1:
            # More than 10% missing parents = unreliable extraction
            LOGGER.warning(
                f"[MIULBuilder] DT extraction quality is LOW ({missing_parent_count} missing parents). "
                f"STRONGLY recommend providing an NHA override file."
            )
            self.issues.append(
                "DT extraction has many missing parents - NHA override file recommended"
            )

        return warnings

    def generate_nha_overrides_from_dt(self) -> Dict[str, str]:
        """
        Auto-generate NHA override JSON from Drawing Tree extraction.

        This removes the human from the loop by converting the extracted
        DT structure directly into the override format. The quality depends
        on extraction accuracy, but even imperfect extraction is better than
        pure EPL inference for project-specific parts.

        Returns:
            Dict mapping child_pn -> parent_pn (can be saved as JSON)
        """
        if not self.dt_tree or not self.dt_tree.get("tree"):
            LOGGER.warning("[MIULBuilder] No DT tree available for override generation")
            return {}

        overrides: Dict[str, str] = {}
        tree_entries = self.dt_tree["tree"]
        top_level = self.dt_tree.get("top_level", "")

        # Add top-level assembly if present
        if top_level:
            # Top level's parent is the project/system name (derive from prefix)
            prefix = self._extract_alpha_prefix(top_level)
            project_name = prefix if prefix else "SYSTEM"
            overrides[top_level] = project_name
            LOGGER.info(f"[MIULBuilder] Auto-override: {top_level} -> {project_name} (top level)")

        # Add all tree entries
        for entry in tree_entries:
            child = entry.get("drawing_number", "").strip()
            parent = entry.get("parent", "")
            if parent:
                parent = parent.strip()

            if child and parent:
                overrides[child] = parent
                LOGGER.debug(f"[MIULBuilder] Auto-override: {child} -> {parent}")

        # Validate: check for orphans (parts that reference non-existent parents)
        all_children = set(overrides.keys())
        all_parents = set(overrides.values())
        orphan_parents = all_parents - all_children - {top_level} - {"DMLLV", "SYSTEM", ""}

        # Only warn about project-prefixed orphans (not standard hardware)
        project_prefix = self._detect_project_prefix()
        project_orphans = [p for p in orphan_parents if self._is_project_part(p, project_prefix)]

        if project_orphans:
            LOGGER.warning(
                f"[MIULBuilder] Auto-generated overrides reference {len(project_orphans)} "
                f"parents not in tree: {project_orphans[:5]}..."
            )

        LOGGER.info(
            f"[MIULBuilder] Auto-generated {len(overrides)} NHA overrides from DT extraction"
        )

        return overrides

    def export_nha_overrides(self, output_path: Path, project: str = "") -> None:
        """
        Export auto-generated NHA overrides to JSON file.

        Args:
            output_path: Path to write JSON file
            project: Project name for metadata
        """
        import json
        from datetime import datetime

        overrides = self.generate_nha_overrides_from_dt()

        if not overrides:
            LOGGER.warning("[MIULBuilder] No overrides to export")
            return

        # Add metadata
        output = {
            "_comment": f"Auto-generated NHA overrides for {project or 'project'}",
            "_generated": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "_source": "DT extraction (auto-generated)",
            "_confidence": self._calculate_dt_confidence(),
        }
        output.update(overrides)

        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(output, f, indent=2)

        LOGGER.info(f"[MIULBuilder] Exported {len(overrides)} NHA overrides to {output_path}")

    def _enhance_dt_from_epl(self) -> int:
        """
        Enhance DT tree by cross-referencing with EPL data.

        When DT extraction misses intermediate assemblies, we can infer
        some relationships from the EPL structure:
        - If part X appears in assembly Y's EPL, Y could be X's parent
        - If Y also appears in Z's EPL, the chain is X -> Y -> Z

        This doesn't guarantee correctness (EPL may list grandchildren too),
        but it helps repair obviously flat extractions.

        Returns:
            Number of relationships added/enhanced
        """
        if not self.dt_tree:
            self.dt_tree = {"tree": [], "top_level": ""}

        tree_entries = self.dt_tree.get("tree", [])
        existing_children = {e.get("drawing_number", "").strip() for e in tree_entries}

        # Build EPL parent map: which assemblies list which parts
        epl_parents: Dict[str, List[str]] = {}  # child -> [possible parents]
        for dwg_num, drawing in self.drawings.items():
            if drawing.drawing_type != "ASSEMBLY":
                continue
            for part in drawing.parts_list:
                child_pn = correct_part_number(part.get("part_number", ""))
                if child_pn:
                    if child_pn not in epl_parents:
                        epl_parents[child_pn] = []
                    epl_parents[child_pn].append(dwg_num)

        # Find project prefix
        project_prefix = self._detect_project_prefix()

        # For project parts not in DT, try to add them from EPL
        additions = 0
        for child_pn, possible_parents in epl_parents.items():
            # Skip if already in DT
            if child_pn in existing_children:
                continue

            # Only enhance project-specific parts (not standard hardware)
            if not self._is_project_part(child_pn, project_prefix):
                continue

            # If only one assembly lists this part, that's likely the parent
            if len(possible_parents) == 1:
                parent = possible_parents[0]
                tree_entries.append({
                    "drawing_number": child_pn,
                    "parent": parent,
                    "type": "DETAIL",
                    "_source": "EPL_INFERRED"
                })
                existing_children.add(child_pn)
                additions += 1
                LOGGER.info(f"[MIULBuilder] EPL-inferred: {child_pn} -> {parent}")

        if additions > 0:
            self.dt_tree["tree"] = tree_entries
            LOGGER.info(f"[MIULBuilder] Enhanced DT with {additions} EPL-inferred relationships")

        return additions

    def _calculate_dt_confidence(self) -> str:
        """
        Calculate confidence score for DT extraction quality.

        Returns:
            "HIGH", "MEDIUM", or "LOW" based on validation results
        """
        if not self.dt_tree or not self.dt_tree.get("tree"):
            return "NONE"

        tree_entries = self.dt_tree["tree"]
        if not tree_entries:
            return "NONE"

        # Check for warning indicators
        issues_count = len([i for i in self.issues if "DT" in i.upper()])

        # Check parent coverage
        parent_of = {
            (e.get("drawing_number") or "").strip(): (e.get("parent") or "").strip()
            for e in tree_entries
        }
        missing_parents = sum(
            1 for child, parent in parent_of.items()
            if parent and not any(e.get("drawing_number", "").strip() == parent for e in tree_entries)
        )
        missing_rate = missing_parents / len(tree_entries) if tree_entries else 1

        # Check for flat structure
        roots = [e.get("drawing_number") for e in tree_entries if not e.get("parent")]
        if roots:
            direct_children = sum(1 for e in tree_entries if e.get("parent") == roots[0])
            flat_ratio = direct_children / len(tree_entries) if tree_entries else 0
        else:
            flat_ratio = 1

        # Score
        if missing_rate > 0.2 or flat_ratio > 0.7 or issues_count > 3:
            return "LOW"
        elif missing_rate > 0.1 or flat_ratio > 0.5 or issues_count > 1:
            return "MEDIUM"
        else:
            return "HIGH"

    def _build_graph(self) -> Dict[str, str]:
        """
        Build parent-child graph for NHA assignment.

        Strategy (prioritized):
        1. Manual overrides from JSON file (highest authority)
        2. Drawing Tree (DT) extraction (authoritative for project-specific parts)
        3. EPL-based inference (ONLY for standard hardware like NAS, MS, AN)

        The key insight: Project-specific parts (MER*, GPE*, etc.) should ONLY
        get their NHA from the drawing tree or manual overrides, never from
        EPL inference. EPL inference creates flat relationships that ignore
        intermediate assemblies.

        Returns:
            Dict mapping child_pn -> parent_assembly_pn
        """
        # Validate DT tree structure first
        self._validate_dt_tree()

        # If no manual overrides and DT extraction quality is low, enhance with EPL data
        if not self.nha_overrides:
            confidence = self._calculate_dt_confidence()
            LOGGER.info(f"[MIULBuilder] DT extraction confidence: {confidence}")

            if confidence in ("LOW", "MEDIUM", "NONE"):
                LOGGER.info("[MIULBuilder] Enhancing DT with EPL-inferred relationships...")
                additions = self._enhance_dt_from_epl()
                if additions > 0:
                    # Recalculate confidence after enhancement
                    new_confidence = self._calculate_dt_confidence()
                    LOGGER.info(f"[MIULBuilder] Post-enhancement confidence: {new_confidence}")

        # Detect project prefix for this drawing set (e.g., "MER", "GPE", "ABC")
        project_prefix = self._detect_project_prefix()
        if project_prefix:
            LOGGER.info(f"[MIULBuilder] Detected project prefix: {project_prefix}")
        else:
            LOGGER.warning(
                "[MIULBuilder] Could not detect project prefix - "
                "all parts will use EPL inference for NHA"
            )

        # child_pn -> parent_assembly_pn
        graph: Dict[str, str] = {}
        override_pns: set = set()  # PNs from manual overrides (highest authority)
        dt_pns: set = set()  # PNs from DT (authoritative for project parts)

        # --- Priority 1: Manual NHA overrides (highest authority) ---
        if self.nha_overrides:
            LOGGER.info(f"[MIULBuilder] Applying {len(self.nha_overrides)} manual NHA overrides")
            for child, parent in self.nha_overrides.items():
                graph[child] = parent
                override_pns.add(child)
                LOGGER.debug(f"  OVERRIDE: {child} -> NHA: {parent}")

        # --- Priority 2: Drawing Tree (DT) hierarchy ---
        if self.dt_tree and self.dt_tree.get("tree"):
            tree_entries = self.dt_tree["tree"]
            LOGGER.info(f"[MIULBuilder] Processing DT tree with {len(tree_entries)} entries")

            for entry in tree_entries:
                child = entry.get("drawing_number", "").strip()
                parent = entry.get("parent", "")
                if parent:
                    parent = parent.strip()

                if child and parent:
                    # Don't override manual overrides
                    if child not in override_pns:
                        graph[child] = parent
                        dt_pns.add(child)
                        LOGGER.debug(f"  DT: {child} -> NHA: {parent}")

                    # Update drawing type from DT if we have the drawing
                    entry_type = entry.get("type", "").upper()
                    if child in self.drawings and entry_type in ("ASSEMBLY", "DETAIL"):
                        if self.drawings[child].drawing_type != entry_type:
                            LOGGER.info(
                                f"  DT type correction: {child} "
                                f"{self.drawings[child].drawing_type} -> {entry_type}"
                            )
                            self.drawings[child].drawing_type = entry_type

        # --- Priority 3: EPL-based inference (ONLY for standard hardware) ---
        # Project-specific parts should NEVER use EPL inference - it creates flat
        # relationships that ignore intermediate assemblies. EPL inference is only
        # appropriate for standard hardware (MS, NAS, AN, etc.) where the assembly
        # listing them IS the correct parent.
        epl_count = 0
        project_part_warnings = 0
        for dwg_num, drawing in self.drawings.items():
            if drawing.drawing_type != "ASSEMBLY":
                continue
            for part in drawing.parts_list:
                child_pn = correct_part_number(part.get("part_number", ""))
                if not child_pn:
                    continue

                # Skip if already assigned by override or DT
                if child_pn in override_pns or child_pn in dt_pns:
                    continue

                # Skip if already in graph
                if child_pn in graph:
                    continue

                # CRITICAL: Only use EPL inference for non-project standard parts
                # Project parts need to come from DT or overrides to preserve hierarchy
                is_project_part = self._is_project_part(child_pn, project_prefix)
                if is_project_part:
                    # Log a warning - this project part is missing from DT and overrides
                    LOGGER.warning(
                        f"[MIULBuilder] Project part {child_pn} (prefix: {project_prefix}) "
                        f"found in {dwg_num} EPL but not in DT or overrides. "
                        f"NHA may be incorrect. Consider adding to NHA override file."
                    )
                    self.issues.append(
                        f"Project part {child_pn} missing from DT - NHA may be wrong"
                    )
                    project_part_warnings += 1
                    # Still assign it (better than nothing), but flag the issue
                    graph[child_pn] = dwg_num
                    epl_count += 1
                else:
                    # Standard hardware - EPL parent is correct
                    graph[child_pn] = dwg_num
                    epl_count += 1

        # --- Log summary ---
        LOGGER.info(
            f"[MIULBuilder] Built NHA graph with {len(graph)} entries: "
            f"{len(override_pns)} from overrides, {len(dt_pns)} from DT, "
            f"{epl_count} from EPL inference"
        )

        return graph

    def build_miul(self) -> pd.DataFrame:
        """
        Build MIUL DataFrame from extracted drawings.

        Strategy:
        1. Build parent-child graph from all assembly EPLs
        2. For each assembly, create EPL rows with NHA = that assembly
        3. For each detail/sub-assembly drawing, create a row with:
           - NHA from graph (which assembly's EPL lists it)
           - Drawing Source = its own drawing number
           - Material from its own title block extraction
        4. Deduplicate by (Part Number, NHA, Drawing Source)

        Returns:
            MIUL DataFrame
        """
        # Step 1: Build the parent-child graph
        graph = self._build_graph()

        rows: List[Dict[str, Any]] = []
        seen_keys: set = set()  # (PN, NHA, DrawingSource) dedup
        index = 1

        # Step 2: Process each assembly — create EPL child rows
        for dwg_num, drawing in self.drawings.items():
            if drawing.drawing_type != "ASSEMBLY":
                continue
            assembly_rows = self._process_assembly(drawing, index, graph)
            rows.extend(assembly_rows)
            index += len(assembly_rows)

            # Track what we've emitted
            for r in assembly_rows:
                key = (r["Part Number"], r.get("NHA", ""), r.get("Drawing Source", ""))
                seen_keys.add(key)

        # Step 3: Create detail drawing rows (self-sourced material)
        for dwg_num, drawing in self.drawings.items():
            # For every drawing (detail or assembly), emit a row sourced
            # from its own title block if it has material info
            nha = graph.get(dwg_num, drawing.nha or "")

            # Check if we already have this exact row
            key = (dwg_num, nha, dwg_num)
            if key in seen_keys:
                continue

            row = self._create_detail_row(drawing, index, nha_override=nha)
            rows.append(row)
            seen_keys.add(key)
            index += 1

        df = pd.DataFrame(rows)

        # Step 4: Postprocess — remove DELETED rows, flag duplicates
        df = self._postprocess_miul(df)

        # Ensure all columns exist
        for col in MIUL_COLUMNS:
            if col not in df.columns:
                df[col] = ""

        # Reorder columns
        df = df[[c for c in MIUL_COLUMNS if c in df.columns]]

        LOGGER.info(f"[MIULBuilder] Generated MIUL with {len(df)} rows")
        return df

    def _postprocess_miul(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Postprocess the MIUL DataFrame:
        1. Remove DELETED / garbage rows
        2. Detect duplicate PNs in same assembly EPL (likely OCR errors)
        3. Clean up CAGE codes that leaked into Designation
        """
        initial = len(df)

        # Remove DELETED-like rows (EH-FITTED, FELT FED, etc.)
        garbage_pns = {"EH-FITTED", "FELT FED", "FELT-FED"}
        mask = df["Part Number"].astype(str).str.strip().isin(garbage_pns)
        if mask.any():
            LOGGER.info(f"[MIULBuilder] Removing {mask.sum()} DELETED/garbage rows")
            df = df[~mask].copy()

        # Clean CAGE codes that leaked into Designation field
        # CAGE codes are 5-char alphanumeric (e.g., 33982, 0KV64)
        import re
        for idx, row in df.iterrows():
            desig = str(row.get("Designation", "")).strip()
            if desig and re.match(r"^[A-Z0-9]{5}$", desig) and desig.isalnum():
                # Looks like a CAGE code, not a material designation
                LOGGER.info(f"[MIULBuilder] Clearing CAGE code designation: {desig} for {row['Part Number']}")
                df.at[idx, "Designation"] = ""

        # Detect duplicate PNs within same assembly EPL
        # (same Part Number and same NHA = likely vision API misread)
        for nha_val in df["NHA"].dropna().unique():
            nha_str = str(nha_val).strip()
            if not nha_str:
                continue
            children = df[df["NHA"].astype(str).str.strip() == nha_str]
            pn_counts = children["Part Number"].astype(str).str.strip().value_counts()
            dupes = pn_counts[pn_counts > 1]
            for dup_pn, count in dupes.items():
                # Some duplicates are legitimate (e.g., same fastener used twice)
                # Only flag if descriptions differ significantly
                dup_rows = children[children["Part Number"].astype(str).str.strip() == dup_pn]
                descs = dup_rows["Part Description"].astype(str).str.strip().unique()
                if len(descs) > 1:
                    LOGGER.warning(
                        f"[MIULBuilder] Duplicate PN {dup_pn} in {nha_str} EPL "
                        f"with {len(descs)} different descriptions: {list(descs)[:3]}. "
                        f"Likely OCR error — check source drawing."
                    )

        removed = initial - len(df)
        if removed:
            LOGGER.info(f"[MIULBuilder] Postprocessing removed {removed} rows")

        return df

    def _create_detail_row(
        self, drawing: DrawingData, index: int, nha_override: str = ""
    ) -> Dict[str, Any]:
        """Create MIUL row for a detail drawing."""
        # Normalize designation and extract UNS for spec
        raw_designation = clean_designation(drawing.material_designation)
        designation, uns = normalize_designation(raw_designation)

        # Normalize spec with UNS if available
        raw_spec = clean_material_spec(drawing.material_spec)
        spec = normalize_material_spec(raw_spec, uns)

        return {
            "Index": index,
            "Parent": 0,
            "Part Number": drawing.drawing_number,
            "Part Description": drawing.title,
            "Nomenclature": drawing.title,
            "NHA": nha_override or drawing.nha,
            "Change Letter": drawing.revision,
            "Drawing Source": drawing.drawing_number,
            "Designation": designation,
            "Material Specification": spec,
            "Material Form": _infer_material_form(drawing.material_spec, drawing.material_designation),
            "Process Specification": drawing.process_spec,
        }

    def _process_assembly(
        self, drawing: DrawingData, start_index: int,
        graph: Dict[str, str] = None
    ) -> List[Dict[str, Any]]:
        """
        Process an assembly drawing into MIUL rows.

        Creates rows for:
        1. The assembly itself (header row with NHA from graph)
        2. Each part in the EPL (NHA = this assembly's drawing number)

        The NHA for each EPL child is this assembly (since it directly
        lists the part). The NHA for the assembly itself comes from the
        graph (which parent assembly lists THIS assembly).

        Material resolution priority:
        1. EPL material_callout (direct from parts list table)
        2. Child drawing title block / notes material
        3. Standard parts material database (MS, NAS, AN series)
        """
        rows = []
        parent_index = start_index

        # Assembly's own NHA: look up in graph
        assembly_nha = ""
        if graph:
            assembly_nha = graph.get(drawing.drawing_number, "")
        if not assembly_nha:
            assembly_nha = drawing.nha or ""

        # Assembly header row
        rows.append({
            "Index": parent_index,
            "Parent": 0,
            "Part Number": drawing.drawing_number,
            "Part Description": drawing.title,
            "Nomenclature": drawing.title,
            "NHA": assembly_nha,
            "Change Letter": drawing.revision,
            "Drawing Source": drawing.drawing_number,
            "Designation": "",  # Assemblies don't have their own material
            "Material Specification": "",
        })

        # EPL parts — NHA = this assembly (it directly lists them)
        is_text_layer = drawing.extraction_method == "text_layer"

        for i, part in enumerate(drawing.parts_list, 1):
            child_index = start_index + i
            # Gate OCR corrections by extraction method:
            # - Text layer (pdfplumber): reads exact embedded Unicode, no OCR involved
            # - Vision extraction: needs OCR error correction
            if is_text_layer:
                part_number = part.get("part_number", "").strip()
            else:
                part_number = correct_part_number(part.get("part_number", ""))

            # For text-layer extraction: use literal material from drawing (no transformation)
            # For vision extraction: use fallback chain with normalization
            if is_text_layer:
                # Text layer data is clean - use it verbatim
                material = part.get("material_callout", "") or part.get("material", "")
                material = material.strip()
                spec = ""

                # Fallback 1: child drawing (detail drawings have full material in notes)
                if not material and part_number in self.drawings:
                    child_dwg = self.drawings[part_number]
                    material = child_dwg.material_designation
                    spec = child_dwg.material_spec

                # Enrich MatSpec from standard parts DB (even if we have material)
                if not spec:
                    std_lookup = lookup_standard_part_material(part_number)
                    if std_lookup and std_lookup.get("material_spec"):
                        spec = std_lookup["material_spec"]
            else:
                # Vision/OCR extraction - apply corrections and fallback chain
                raw_material = correct_ocr_errors(part.get("material_callout", "") or part.get("material", "") or "")
                raw_material = clean_designation(raw_material)
                raw_spec = clean_material_spec(part.get("spec_callout", "") or "")

                # Fallback 1: child drawing extraction
                if not raw_material and part_number in self.drawings:
                    child_dwg = self.drawings[part_number]
                    raw_material = clean_designation(child_dwg.material_designation)
                    raw_spec = clean_material_spec(child_dwg.material_spec) or raw_spec

                # Fallback 2: standard parts material database
                if not raw_material:
                    std_lookup = lookup_standard_part_material(part_number)
                    if std_lookup:
                        raw_material = std_lookup["designation"]
                        if not raw_spec and std_lookup.get("material_spec"):
                            raw_spec = std_lookup["material_spec"]
                        LOGGER.info(
                            f"Standard part lookup: {part_number} -> {raw_material}"
                        )
                elif not raw_spec:
                    # Even if we have material, check for spec from standard parts DB
                    std_lookup = lookup_standard_part_material(part_number)
                    if std_lookup and std_lookup.get("material_spec"):
                        raw_spec = std_lookup["material_spec"]

                # Normalize designation and spec to James's format
                material, uns = normalize_designation(raw_material)
                spec = normalize_material_spec(raw_spec, uns)

            rows.append({
                "Index": child_index,
                "Parent": parent_index,
                "Part Number": part_number,
                "Part Description": part.get("description", ""),
                "Nomenclature": part.get("description", ""),
                "NHA": drawing.drawing_number,
                "Drawing Source": drawing.drawing_number,
                "Designation": material,
                "Material Specification": spec,
                "Material Form": _infer_material_form(spec, material) if not is_text_layer else "",
            })

        return rows

    # Excel styling (matches V1 DTMIULBuilder exactly)
    HEADER_FILL = PatternFill(start_color="1F4E79", end_color="1F4E79", fill_type="solid")
    HEADER_FONT = Font(bold=True, color="FFFFFF", size=10)
    ASSEMBLY_FILL = PatternFill(start_color="D6EAF8", end_color="D6EAF8", fill_type="solid")
    MIUL_ID_FILL = PatternFill(start_color="E8F5E9", end_color="E8F5E9", fill_type="solid")
    SUBPART_FILL = PatternFill(start_color="FFF3E0", end_color="FFF3E0", fill_type="solid")
    THIN_BORDER = Border(
        left=Side(style="thin"), right=Side(style="thin"),
        top=Side(style="thin"), bottom=Side(style="thin"),
    )

    def export_to_excel(
        self, df: pd.DataFrame, output_path: Path, project: str = ""
    ) -> None:
        """Export MIUL DataFrame to Excel with MAPTIS-compliant formatting.

        Uses MAPTIS-style formatting:
        - Dark blue headers with white bold font
        - Neutral (unshaded) data rows
        - Freeze panes on header row
        - Summary statistics sheet
        """
        from mira.miul.v1_archive.dt_miul_builder import MAPTIS_COLUMNS

        wb = Workbook()
        ws = wb.active
        ws.title = "MIUL"

        # Map from MIUL_COLUMNS display names to MAPTIS_COLUMNS keys
        # V3 uses display names as dict keys, V1 uses internal keys
        display_to_v1_key = {
            "Index": "index",
            "Parent": "parent",
            "Part Number": "part_number",
            "Part Description": "part_description",
            "Nomenclature": "nomenclature",
            "NHA": "nha",
            "Change Letter": "change_letter",
            "Drawing Source": "source_drawing",
            "Material Form": "form",
            "Material Manufacturer": "manufacturer",
            "Designation": "designation",
            "Material Specification": "material_spec",
            "Process Specification": "process_spec",
            "Environment": "environment",
            "Material Code": "material_code",
            "Standard Part Number": "std_part_number",
            "Contractor": "contractor",
            "System": "system",
            "Subsystem": "subsystem",
            "Max Temperature": "max_temp",
            "Min Temperature": "min_temp",
            "Fluid Type": "fluid_type",
            "Associate Contractor": "assoc_contractor",
            "Project": "project",
            "Document Title": "title",
            "Criticality": "criticality",
            "Line Number": "line_number",
            "Overall Evaluation": "overall_eval",
            "Configuration Test": "config_test",
            "Max Pressure": "max_pressure",
            "Min Pressure": "min_pressure",
            "MUA Rationale": "mua_rationale",
            "Cure Codes": "cure_codes",
            "FLAM": "flamm_rating",
            "SCC": "scc_rating",
            "CORR": "corr_rating",
            "TVS": "tvs_rating",
            "TOX": "tox_rating",
            "FS": "fs_rating",
            "Remarks": "remarks",
        }

        # Write headers with V1 styling
        for col_idx, (header, _, width) in enumerate(MAPTIS_COLUMNS, start=1):
            cell = ws.cell(row=1, column=col_idx, value=header)
            cell.fill = self.HEADER_FILL
            cell.font = self.HEADER_FONT
            cell.border = self.THIN_BORDER
            cell.alignment = Alignment(horizontal="center", wrap_text=True)
            ws.column_dimensions[get_column_letter(col_idx)].width = width

        # Write data rows
        for row_idx, (_, row) in enumerate(df.iterrows(), start=2):
            for col_idx, (header, _, _) in enumerate(MAPTIS_COLUMNS, start=1):
                # Get value from DataFrame row using display name
                if header in row.index:
                    value = row[header]
                elif header == "Project":
                    value = project
                else:
                    value = ""

                # Handle NaN
                if pd.isna(value):
                    value = ""

                cell = ws.cell(row=row_idx, column=col_idx, value=value)
                cell.border = self.THIN_BORDER

        # Freeze header row
        ws.freeze_panes = "A2"

        # Add summary sheet
        ws_summary = wb.create_sheet("Summary")
        self._write_summary(ws_summary, df, project)

        wb.save(str(output_path))
        LOGGER.info(f"[MIULBuilder] Exported to {output_path}")

    def _write_summary(
        self, ws, df: pd.DataFrame, project: str = ""
    ) -> None:
        """Write summary statistics sheet (matches V1 format)."""
        ws.column_dimensions["A"].width = 35
        ws.column_dimensions["B"].width = 25

        assemblies = sum(
            1 for _, r in df.iterrows()
            if str(r.get("Part Number", "")) in self.drawings
            and self.drawings[str(r.get("Part Number", ""))].drawing_type == "ASSEMBLY"
        )
        total_rows = len(df)
        materials_found = sum(
            1 for _, r in df.iterrows()
            if pd.notna(r.get("Designation")) and str(r.get("Designation")).strip()
        )

        summary = [
            ("V3 Enhanced MIUL Summary", ""),
            ("", ""),
            ("Project", project or "MIUL"),
            ("Generated", datetime.now().strftime("%Y-%m-%d %H:%M")),
            ("Architecture", "V3 Enhanced (Multi-Location Material Search)"),
            ("", ""),
            ("Statistics", ""),
            ("Total Rows", total_rows),
            ("Drawings Extracted", len(self.drawings)),
            ("Assemblies", assemblies),
            ("Materials Found", materials_found),
            ("Materials Missing", total_rows - materials_found),
            ("", ""),
            ("V3 Enhancements", ""),
            ("NOTES Section Parsing", "Yes"),
            ("OCR Error Correction", "Yes"),
            ("Material Spec Validation", "Yes"),
            ("Part Number Correction", "Yes"),
            ("Material Form Inference", "Yes"),
        ]

        for row_idx, (label, value) in enumerate(summary, start=1):
            ws.cell(row=row_idx, column=1, value=label)
            ws.cell(row=row_idx, column=2, value=value)
            if label in ("V3 Enhanced MIUL Summary", "Statistics", "V3 Enhancements"):
                ws.cell(row=row_idx, column=1).font = Font(bold=True)

    def export_inventory(self, output_path: Path) -> None:
        """Export extraction results to JSON inventory file."""
        inventory = {
            "project": output_path.stem,
            "drawings_count": len(self.drawings),
            "issues": self.issues,
            "drawings": [
                {
                    "drawing_number": dwg.drawing_number,
                    "title": dwg.title,
                    "revision": dwg.revision,
                    "type": dwg.drawing_type,
                    "material": dwg.material_designation,
                    "material_spec": dwg.material_spec,
                    "uns": dwg.uns_number,
                    "nha": dwg.nha,
                    "source_file": dwg.source_file,
                    "parts_count": len(dwg.parts_list),
                }
                for dwg in self.drawings.values()
            ],
        }

        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(inventory, f, indent=2, ensure_ascii=False)

        LOGGER.info(f"[MIULBuilder] Exported inventory to {output_path}")


def build_miul_from_directory(
    directory: Path,
    output_excel: Path = None,
    output_inventory: Path = None,
    nha_override_path: Path = None,
) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """
    Convenience function to build MIUL from a directory of PDFs.

    Args:
        directory: Directory containing drawing PDFs
        output_excel: Optional path for Excel output
        output_inventory: Optional path for JSON inventory output
        nha_override_path: Optional path to JSON file with manual NHA overrides.
            Format: {"child_pn": "parent_pn", ...}
            These take highest priority over DT extraction and EPL inference.

    Returns:
        Tuple of (MIUL DataFrame, stats dict)
    """
    builder = MIULBuilderV3()

    # Extract all drawings (with optional NHA overrides)
    builder.extract_directory(directory, nha_override_path=nha_override_path)

    # Build MIUL
    df = builder.build_miul()

    # Derive project name from directory
    project_name = directory.name

    # Export if paths provided
    if output_excel:
        builder.export_to_excel(df, output_excel, project=project_name)

    if output_inventory:
        builder.export_inventory(output_inventory)

    stats = {
        "drawings_extracted": len(builder.drawings),
        "miul_rows": len(df),
        "issues": builder.issues,
        "materials_found": df["Designation"].notna().sum(),
    }

    return df, stats


# =============================================================================
# Phase 3: Merge DT JSON + Parts JSON -> MIUL (2-Phase Pipeline)
# =============================================================================


def _fuzzy_lookup(d: Dict[str, Any], key: str) -> Tuple[str, Dict[str, Any]]:
    """
    Try exact match, then base part number (strip revision suffix).

    Handles cases like: "GPE-015" (Parts JSON) vs "GPE-015-1" (DT)

    Returns (matched_key, value) or ("", {}).
    """
    # Exact match
    if key in d:
        return key, d[key]

    # Strip revision suffix: GPE-015-1 -> GPE-015, MER07540-001 -> MER07540
    base = re.sub(r'-\d+$', '', key)
    if base != key and base in d:
        LOGGER.debug(f"[Merge] Fuzzy match: {key} -> {base}")
        return base, d[base]

    # Try reverse: maybe key is base and dict has suffixed version
    for dict_key in d.keys():
        if re.sub(r'-\d+$', '', dict_key) == key:
            LOGGER.debug(f"[Merge] Fuzzy match: {key} <- {dict_key}")
            return dict_key, d[dict_key]

    return "", {}


def merge_dt_and_parts(
    dt_json: Dict[str, Any],
    parts_json: Dict[str, Any],
    project_name: str = "",
    environment: Optional[EnvironmentConfig] = None,
) -> pd.DataFrame:
    """
    Phase 3: Merge Drawing Tree hierarchy with Parts JSON to create MIUL.

    This is the core of the 2-phase pipeline:
    1. DT JSON provides the hierarchy (NHA relationships)
    2. Parts JSON provides materials, specs, descriptions
    3. This function merges them into the MIUL format

    The algorithm:
    - For each part in DT, look up material/spec from Parts JSON
    - Use DT parent as NHA (authoritative)
    - Fill in details from Parts JSON
    - Add standard hardware from Parts JSON not in DT

    Args:
        dt_json: Drawing Tree JSON from extract_drawing_tree()
            {
                "top_level": "MER07540-001",
                "tree": [
                    {"drawing_number": "MER07543-001", "parent": "MER07540-001", ...}
                ]
            }
        parts_json: Parts JSON from extract_parts_json()
            {
                "parts": {"MER07543-001": {"material": "A286", ...}, ...},
                "drawings": {"MER07543-001": {"title": "...", ...}, ...}
            }
        project_name: Project name for metadata
        environment: Environment configuration (temp, pressure, fluid type).
            Defaults to SECONDARY_PAYLOAD_ENV if not specified.
            Use H2_ENVIRONMENT or O2_ENVIRONMENT presets for gas service.

    Returns:
        MIUL DataFrame ready for Excel export
    """
    # Use default secondary payload environment if not specified
    env = environment or SECONDARY_PAYLOAD_ENV
    rows: List[Dict[str, Any]] = []
    seen_pns: set = set()
    pn_to_index: Dict[str, int] = {}  # Map Part Number -> row Index

    parts = parts_json.get("parts", {})
    drawings = parts_json.get("drawings", {})
    tree = dt_json.get("tree", [])
    top_level = dt_json.get("top_level", "")

    # Detect project prefix for later use (e.g., "MER" from "MER07540-001")
    project_prefix = ""
    if top_level:
        import re
        match = re.match(r'^([A-Z]+)', top_level.upper())
        if match:
            project_prefix = match.group(1)

    # Extract MIUL number (project identifier without revision suffix)
    # Examples: "MER07540-001" -> "MER07540", "GPE-A000-1" -> "GPE-A000"
    miul_number = ""
    if top_level:
        # Try NASA format first: letters + digits (e.g., MER07540)
        match = re.match(r'^([A-Z]+\d+)', top_level.upper())
        if match:
            miul_number = match.group(1)
        else:
            # Try other formats: everything before final "-N" revision suffix
            # e.g., "GPE-A000-1" -> "GPE-A000"
            match = re.match(r'^([A-Z]+-?[A-Z0-9]+)', top_level.upper())
            if match:
                candidate = match.group(1)
                # Remove trailing revision suffix like "-1", "-001"
                candidate = re.sub(r'-\d+$', '', candidate)
                if candidate:
                    miul_number = candidate

    LOGGER.info(
        f"[Merge] Starting merge: {len(tree)} DT entries, {len(parts)} parts, "
        f"prefix={project_prefix}, miul_number={miul_number}"
    )

    # Build lookup: drawing_number -> parent (NHA string)
    nha_map = {}
    for entry in tree:
        dwg_num = entry.get("drawing_number", "").strip()
        parent = (entry.get("parent") or "").strip()
        if dwg_num:
            nha_map[dwg_num] = parent

    # Row 1: Project root (no NHA) - per MIUL_GENERATION_INSTRUCTIONS.md
    rows.append({
        "Index": 1,
        "Parent": 0,
        "Part Number": miul_number or project_name,
        "Part Description": f"{miul_number or project_name} Material Identification Usage List",
        "Nomenclature": f"{miul_number or project_name} MIUL",
        "NHA": "",  # Project root has no NHA
        "Change Letter": "",
        "Drawing Source": "",
        "Material Form": "",
        "Designation": "",
        "Material Specification": "",
        "Process Specification": "",
        "Project": project_name,
    })

    # Row 2: MIUL root (NHA = miul_number) - per MIUL_GENERATION_INSTRUCTIONS.md
    rows.append({
        "Index": 2,
        "Parent": 0,
        "Part Number": miul_number or project_name,
        "Part Description": f"{miul_number or project_name} Material Identification Usage List",
        "Nomenclature": f"{miul_number or project_name} MIUL",
        "NHA": miul_number or project_name,  # MIUL root appears in tree
        "Change Letter": "",
        "Drawing Source": "",
        "Material Form": "",
        "Designation": "",
        "Material Specification": "",
        "Process Specification": "",
        "Project": project_name,
    })
    # Map the MIUL number to header row 2 (data rows point to row 2)
    if miul_number:
        pn_to_index[miul_number] = 2

    # Start data rows at Index 3
    index = 3

    # Phase 3a: Process DT tree entries (project-specific parts with hierarchy)
    for entry in tree:
        dwg_num = entry.get("drawing_number", "").strip()
        if not dwg_num:
            continue

        nha = nha_map.get(dwg_num, "")
        # Top-level assemblies (no parent) should use miul_number as NHA
        if not nha and miul_number:
            nha = miul_number
        entry_type = entry.get("type", "DETAIL").upper()

        # Look up part info from Parts JSON (with fuzzy matching for revision variants)
        _, part_info = _fuzzy_lookup(parts, dwg_num)
        _, drawing_info = _fuzzy_lookup(drawings, dwg_num)

        # Prefer drawing info for title, fall back to part info
        title = drawing_info.get("title") or part_info.get("description") or entry.get("title", "")

        # Material from Parts JSON (fall back to drawings dict)
        material = part_info.get("material", "") or drawing_info.get("material", "")
        spec = part_info.get("material_spec", "") or drawing_info.get("material_spec", "")
        uns = part_info.get("uns", "") or drawing_info.get("uns", "")
        process_spec = part_info.get("process_spec", "") or drawing_info.get("process_spec", "")

        # Fall back to standard parts database if no material/spec found
        if not material or not spec:
            std_lookup = lookup_standard_part_material(dwg_num)
            if std_lookup:
                if not material:
                    material = std_lookup.get("designation", "")
                if not spec:
                    spec = std_lookup.get("material_spec", "")
                LOGGER.debug(f"Standard parts fallback for {dwg_num}: {material}, {spec}")

        # Normalize
        if material:
            material = clean_designation(material)
            designation, extracted_uns = normalize_designation(material)
            if extracted_uns and not uns:
                uns = extracted_uns
        else:
            designation = ""

        if spec:
            spec = normalize_material_spec(clean_material_spec(spec), uns)

        # Material form inference
        form = _infer_material_form(spec, material)

        # Revision from drawing info
        revision = drawing_info.get("revision", "")

        # Store the index for this part number BEFORE adding the row
        pn_to_index[dwg_num] = index

        row = {
            "Index": index,
            "Parent": 0,  # Will be calculated after all rows are created
            "Part Number": dwg_num,
            "Part Description": title,
            "Nomenclature": title,
            "NHA": nha,
            "Change Letter": revision,
            "Drawing Source": dwg_num,
            "Material Form": form,
            "Designation": designation,
            "Material Specification": spec,
            "Process Specification": process_spec,
            "Project": project_name,
        }
        rows.append(row)
        seen_pns.add(dwg_num)
        index += 1

    LOGGER.info(f"[Merge] Added {len(rows) - 2} rows from DT hierarchy (plus 2 header rows)")

    # Phase 3a': Add assembly drawings from Parts JSON not in DT
    # When DT extraction fails or is incomplete, assemblies might be missing
    assemblies_added = 0
    for dwg_num, drawing_info in drawings.items():
        if dwg_num in seen_pns:
            continue

        # Only add assemblies here - details come from parts dict
        if drawing_info.get("drawing_type", "").upper() != "ASSEMBLY":
            continue

        # Use miul_number as NHA for top-level assemblies
        nha = miul_number if miul_number else ""

        # Material from drawing info (assemblies usually don't have material)
        material = drawing_info.get("material", "")
        spec = drawing_info.get("material_spec", "")
        uns = drawing_info.get("uns", "")

        if material:
            material = clean_designation(material)
            designation, extracted_uns = normalize_designation(material)
            if extracted_uns and not uns:
                uns = extracted_uns
        else:
            designation = ""

        if spec:
            spec = normalize_material_spec(clean_material_spec(spec), uns)

        pn_to_index[dwg_num] = index

        row = {
            "Index": index,
            "Parent": 0,  # Will be calculated in Phase 3c
            "Part Number": dwg_num,
            "Part Description": drawing_info.get("title", ""),
            "Nomenclature": drawing_info.get("title", ""),
            "NHA": nha,
            "Change Letter": drawing_info.get("revision", ""),
            "Drawing Source": dwg_num,
            "Material Form": "",
            "Designation": designation,
            "Material Specification": spec,
            "Process Specification": drawing_info.get("process_spec", ""),
            "Project": project_name,
        }
        rows.append(row)
        seen_pns.add(dwg_num)
        index += 1
        assemblies_added += 1

    if assemblies_added > 0:
        LOGGER.info(f"[Merge] Added {assemblies_added} assembly rows from drawings (DT fallback)")

    # Phase 3b: Add standard hardware from Parts JSON not in DT
    # These are parts found in assembly EPLs (MS, NAS, AN, etc.)
    std_hw_added = 0
    for pn, part_info in parts.items():
        if pn in seen_pns:
            continue

        # GPE fix: Also check if DT version (with -1 suffix) was already added
        # Parts JSON has GPE-052, DT has GPE-052-1 - skip if DT version exists
        pn_with_dash1 = f"{pn}-1"
        if pn_with_dash1 in seen_pns:
            LOGGER.debug(f"[Merge] Skipping {pn} - DT version {pn_with_dash1} already exists")
            continue

        # Check if it's standard hardware (not project-specific)
        is_project = project_prefix and pn.upper().startswith(project_prefix)
        if is_project:
            # Project part not in DT - log warning but still add
            LOGGER.warning(f"[Merge] Project part {pn} in Parts JSON but not in DT")

        # Get source drawing as NHA (for EPL-sourced parts)
        source_drawing = part_info.get("source_drawing", "")
        nha = source_drawing if source_drawing in nha_map or source_drawing in seen_pns else ""

        material = part_info.get("material", "")
        spec = part_info.get("material_spec", "")
        uns = part_info.get("uns", "")

        # Try standard parts lookup if no material
        if not material:
            std_lookup = lookup_standard_part_material(pn)
            if std_lookup:
                material = std_lookup.get("designation", "")
                if not spec:
                    spec = std_lookup.get("material_spec", "")
        # Even if we have material, still enrich spec from standard parts DB
        elif not spec:
            std_lookup = lookup_standard_part_material(pn)
            if std_lookup and std_lookup.get("material_spec"):
                spec = std_lookup["material_spec"]

        # Normalize
        if material:
            material = clean_designation(material)
            designation, extracted_uns = normalize_designation(material)
            if extracted_uns and not uns:
                uns = extracted_uns
        else:
            designation = ""

        if spec:
            spec = normalize_material_spec(clean_material_spec(spec), uns)

        form = _infer_material_form(spec, material)

        # Track the index for this part number
        pn_to_index[pn] = index

        row = {
            "Index": index,
            "Parent": 0,  # Will be calculated below
            "Part Number": pn,
            "Part Description": part_info.get("description", ""),
            "Nomenclature": part_info.get("description", ""),
            "NHA": nha,
            "Change Letter": "",
            "Drawing Source": source_drawing,
            "Material Form": form,
            "Designation": designation,
            "Material Specification": spec,
            "Process Specification": part_info.get("process_spec", ""),
            "Project": project_name,
        }
        rows.append(row)
        seen_pns.add(pn)
        index += 1
        std_hw_added += 1

    LOGGER.info(f"[Merge] Added {std_hw_added} standard hardware rows from Parts JSON")

    # Phase 3c: Calculate Parent column based on NHA -> Index mapping
    # Parent = Index of the row whose Part Number equals this row's NHA
    parent_updates = 0
    for row in rows:
        row_index = row["Index"]
        # Skip header rows (Index 1 and 2 already have Parent=0)
        if row_index <= 2:
            continue

        nha = row.get("NHA", "")
        if nha:
            # Look up the Index of the parent row
            parent_index = pn_to_index.get(nha)
            if parent_index:
                row["Parent"] = parent_index
                parent_updates += 1
            else:
                # NHA not found in pn_to_index - use header row 2 as fallback
                row["Parent"] = 2
                parent_updates += 1
        else:
            # No NHA - this is a top-level item, parent is header row 2
            row["Parent"] = 2
            parent_updates += 1

    LOGGER.info(f"[Merge] Updated Parent column for {parent_updates} rows")

    # NOTE: Phase 3e (NHA normalization) was REMOVED per builder_fix_spec.md
    # The NHA values set in Phase 3a (from DT JSON nha_map) are already correct.
    # Phase 3c used those NHA values to calculate Parent indices correctly.
    # The old Phase 3e was destroying correct NHA values by blanking them for Parent>2.
    # Now NHA carries the actual parent drawing number for every row, as needed for MAPTIS.

    # Phase 3f: Apply environment parameters to data rows
    # Per MIUL_GENERATION_INSTRUCTIONS.md, environment values apply to all material rows
    env_applied = 0
    for row in rows:
        row_index = row["Index"]
        # Skip header rows (they don't have environment conditions)
        if row_index <= 2:
            continue

        # Apply environment configuration
        row["Max Temperature"] = env.max_temp
        row["Min Temperature"] = env.min_temp
        row["Max Pressure"] = env.max_pressure
        row["Min Pressure"] = env.min_pressure
        row["Fluid Type"] = env.fluid_type
        row["Environment"] = env.environment
        env_applied += 1

    LOGGER.info(
        f"[Merge] Applied environment to {env_applied} rows: "
        f"{env.fluid_type}, {env.min_temp}°F-{env.max_temp}°F, "
        f"{env.min_pressure}-{env.max_pressure} psia"
    )

    # Phase 3d: Add EOF row (Index=-1, per MAPTIS spec)
    # All columns should be blank except Index
    rows.append({
        "Index": -1,
        "Parent": "",
        "Part Number": "",
        "Part Description": "",
        "Nomenclature": "",
        "NHA": "",
        "Change Letter": "",
        "Drawing Source": "",
        "Material Form": "",
        "Designation": "",
        "Material Specification": "",
        "Process Specification": "",
        "Project": "",
    })

    # Create DataFrame
    df = pd.DataFrame(rows)

    # Ensure all MIUL columns exist
    for col in MIUL_COLUMNS:
        if col not in df.columns:
            df[col] = ""

    # Reorder columns
    df = df[[c for c in MIUL_COLUMNS if c in df.columns]]

    LOGGER.info(f"[Merge] Complete: {len(df)} total MIUL rows (including 2 headers + EOF)")

    return df


def build_miul_2phase(
    directory: Path,
    output_excel: Path = None,
    dt_json_path: Path = None,
    parts_json_path: Path = None,
    client: VisionClient = None,
    environment: Optional[EnvironmentConfig] = None,
    project_name: str = "",
    use_multipass: bool = True,
    multipass_passes: int = 3,
) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """
    Build MIUL using the 2-phase pipeline.

    This is the new recommended API that separates concerns:
    - Phase 1: Extract DT JSON (hierarchy only)
    - Phase 2: Extract Parts JSON (materials/specs only)
    - Phase 3: Merge into MIUL

    Benefits:
    - DT JSON can be manually corrected if needed
    - Parts JSON can be cached/reused
    - Clear separation of hierarchy vs material extraction
    - Easier debugging (inspect intermediate JSONs)

    Args:
        directory: Directory containing drawing PDFs
        output_excel: Optional path for Excel output
        dt_json_path: Optional path to save/load DT JSON
        parts_json_path: Optional path to save/load Parts JSON
        client: Optional VisionClient instance
        environment: Environment configuration (temp, pressure, fluid type).
            Defaults to SECONDARY_PAYLOAD_ENV if not specified.
        project_name: Project name for metadata
        use_multipass: Use multi-pass EPL extraction with consensus voting (default True)
        multipass_passes: Number of passes for multi-pass extraction (default 3)

    Returns:
        Tuple of (MIUL DataFrame, stats dict)
    """
    from .extract import extract_drawing_tree, extract_parts_json, _is_dt_file

    if client is None:
        client = VisionClient()

    # Only use directory name as fallback if project_name not provided
    if not project_name:
        project_name = directory.name
    issues: List[str] = []

    # Phase 1: Extract or load DT JSON
    dt_json = None
    if dt_json_path and dt_json_path.exists():
        LOGGER.info(f"[2Phase] Loading existing DT JSON from {dt_json_path}")
        with open(dt_json_path, "r", encoding="utf-8") as f:
            dt_json = json.load(f)
    else:
        # Find DT file and extract
        pdf_files = sorted(directory.glob("*.pdf"))
        dt_files = [f for f in pdf_files if _is_dt_file(f.name)]

        if dt_files:
            LOGGER.info(f"[2Phase] Phase 1: Extracting DT from {dt_files[0].name}")
            dt_json = extract_drawing_tree(dt_files[0], client)

            if dt_json_path:
                with open(dt_json_path, "w", encoding="utf-8") as f:
                    json.dump(dt_json, f, indent=2)
                LOGGER.info(f"[2Phase] Saved DT JSON to {dt_json_path}")
        else:
            LOGGER.warning("[2Phase] No DT file found - hierarchy will be flat")
            dt_json = {"top_level": "", "tree": []}
            issues.append("No Drawing Tree file found")

    # Phase 2: Extract or load Parts JSON
    parts_json = None
    if parts_json_path and parts_json_path.exists():
        LOGGER.info(f"[2Phase] Loading existing Parts JSON from {parts_json_path}")
        with open(parts_json_path, "r", encoding="utf-8") as f:
            parts_json = json.load(f)
    else:
        LOGGER.info(f"[2Phase] Phase 2: Extracting Parts JSON (multipass={use_multipass}, passes={multipass_passes})")
        parts_json = extract_parts_json(
            directory, client, parts_json_path,
            use_multipass=use_multipass,
            multipass_passes=multipass_passes,
        )

    # Phase 3: Merge
    LOGGER.info("[2Phase] Phase 3: Merging DT + Parts -> MIUL")
    df = merge_dt_and_parts(dt_json, parts_json, project_name, environment)

    # Export Excel if path provided
    if output_excel:
        _export_miul_excel(
            df,
            output_excel,
            project_name,
            dt_json,
            parts_json,
            environment=environment,
        )

    # Stats
    metadata = parts_json.get("metadata", {})
    stats = {
        "drawings_extracted": len(parts_json.get("drawings", {})),
        "parts_found": len(parts_json.get("parts", {})),
        "dt_entries": len(dt_json.get("tree", [])),
        "miul_rows": len(df),
        "materials_found": (df["Designation"].notna() & (df["Designation"] != "")).sum(),
        "multipass_enabled": metadata.get("multipass_enabled", use_multipass),
        "multipass_passes": metadata.get("multipass_passes", multipass_passes),
        "issues": issues + metadata.get("issues", []),
    }

    return df, stats


def _export_miul_excel(
    df: pd.DataFrame,
    output_path: Path,
    project_name: str,
    dt_json: Dict[str, Any],
    parts_json: Dict[str, Any],
    environment: Optional[Any] = None,
) -> None:
    """Export MIUL DataFrame to Excel.

    Standard output uses the OPIV macro-enabled template format.
    Falls back to the legacy generated workbook if template export fails.
    """
    from mira.miul.v1_archive.dt_miul_builder import MAPTIS_COLUMNS

    def _as_cell(value: Any) -> Any:
        if value is None:
            return None
        if pd.isna(value):
            return None
        if isinstance(value, str):
            text = value.strip()
            return text if text else None
        if isinstance(value, float) and value.is_integer():
            return int(value)
        return value

    def _safe_int(value: Any) -> Any:
        v = _as_cell(value)
        if v is None:
            return None
        try:
            return int(float(v))
        except (TypeError, ValueError):
            return v

    def _filter_sentinel_rows(frame: pd.DataFrame) -> pd.DataFrame:
        if "Index" not in frame.columns:
            return frame

        def _is_not_sentinel(idx_val: Any) -> bool:
            try:
                return int(float(idx_val)) != -1
            except (TypeError, ValueError):
                return str(idx_val).strip() != "-1"

        return frame[frame["Index"].map(_is_not_sentinel)]

    def _data_rows_only(frame: pd.DataFrame) -> pd.DataFrame:
        if "Index" not in frame.columns:
            return frame
        idx_series = pd.to_numeric(frame["Index"], errors="coerce")
        return frame[idx_series >= 3]

    def _as_text(value: Any) -> str:
        cell = _as_cell(value)
        if cell is None:
            return ""
        return str(cell).strip()

    def _ordered_rows(frame: pd.DataFrame) -> pd.DataFrame:
        if "Index" not in frame.columns:
            return frame
        work = frame.copy()
        work["__sort_idx"] = pd.to_numeric(work["Index"], errors="coerce")
        work = work.sort_values("__sort_idx", na_position="last")
        return work.drop(columns=["__sort_idx"])

    # Defaults reused for MIUL cells and Notes tab.
    env_defaults = {
        "o2_percent": getattr(environment, "o2_percent", None),
        "max_pressure": getattr(environment, "max_pressure", None),
        "min_pressure": getattr(environment, "min_pressure", None),
        "max_temp": getattr(environment, "max_temp", None),
        "min_temp": getattr(environment, "min_temp", None),
        "fluid_type": getattr(environment, "fluid_type", None),
    }

    def _build_parent_rows(frame: pd.DataFrame) -> List[Tuple[int, str, str]]:
        data_rows = _ordered_rows(_data_rows_only(frame))
        parent_rows: List[Tuple[int, str, str]] = []
        seen: set[str] = set()

        pn_to_nha: Dict[str, str] = {}
        if "Part Number" in data_rows.columns and "NHA" in data_rows.columns:
            for _, row in data_rows.iterrows():
                pn = _as_text(row.get("Part Number", ""))
                if pn and pn not in pn_to_nha:
                    pn_to_nha[pn] = _as_text(row.get("NHA", ""))

        tree_entries = dt_json.get("tree", []) if isinstance(dt_json, dict) else []
        if tree_entries:
            for entry in tree_entries:
                drawing = _as_text(entry.get("drawing_number", ""))
                if not drawing or drawing in seen:
                    continue
                nha_val = _as_text(entry.get("parent", "")) or pn_to_nha.get(drawing, "")
                parent_rows.append((len(parent_rows) + 1, drawing, nha_val))
                seen.add(drawing)

        if not parent_rows:
            for _, row in data_rows.iterrows():
                drawing = _as_text(row.get("Drawing Source", "")) or _as_text(row.get("Part Number", ""))
                if not drawing or drawing in seen:
                    continue
                nha_val = _as_text(row.get("NHA", "")) or pn_to_nha.get(drawing, "")
                parent_rows.append((len(parent_rows) + 1, drawing, nha_val))
                seen.add(drawing)

        return parent_rows

    def _extract_rationale_codes(frame: pd.DataFrame) -> Dict[str, int]:
        code_counts: Dict[str, int] = {}
        if "MUA Rationale" not in frame.columns:
            return code_counts

        data_rows = _data_rows_only(frame)
        for raw in data_rows["MUA Rationale"].tolist():
            text = _as_text(raw)
            if not text:
                continue
            for token in re.split(r"[,\n;/|]+", text):
                code = token.strip()
                if not code:
                    continue
                code_counts[code] = code_counts.get(code, 0) + 1
        return code_counts

    def _populate_parents_sheet(ws: Any, parent_rows: List[Tuple[int, str, str]]) -> None:
        ws["A1"] = "Count"
        ws["B1"] = "Drawing"
        ws["C1"] = "NHA"

        max_clear_row = max(ws.max_row, len(parent_rows) + 20)
        for row_idx in range(2, max_clear_row + 1):
            for col_idx in range(1, 7):
                try:
                    ws.cell(row=row_idx, column=col_idx).value = None
                except AttributeError:
                    continue

        for out_row_idx, (count, drawing, nha_val) in enumerate(parent_rows, start=2):
            ws.cell(row=out_row_idx, column=1, value=count)
            ws.cell(row=out_row_idx, column=2, value=drawing)
            ws.cell(row=out_row_idx, column=3, value=nha_val)

    def _populate_codes_sheet(ws: Any, frame: pd.DataFrame) -> None:
        code_sections: List[Tuple[str, List[Tuple[str, str]]]] = [
            (
                "FLAMMABILITY RATIONALE CODES",
                [
                    ("101", "Approved materials usage agreement (MUA) Category I."),
                    ("102", "Approved materials usage agreement (MUA) Category II."),
                    ("103", "Materials passed requirements when tested in configuration."),
                    ("104", "Unexposed, over coated or sandwiched between non-flammable material and no ignition source or propagation path."),
                    ("105", "Minor usage (less than 0.1 LB. and 2 SQ-IN surface area); no propagation path or ignition source."),
                    ("106", "Material is used in hermetically sealed container."),
                    ("107", "Passes test No. 8 of NHB 8060.1, Flammability test for materials in vented containers, by test or analysis."),
                    ("108", "Of the shelf equipment having material acceptable in configuration; no ignition source or propagation path."),
                    ("109", "Material not exposed; totally immersed in fluid; evaluated for fluid compatibility only."),
                    ("110", "Material is acceptable when used on a metal substrate that provides a good heat sink. Material considered noncombustible in this configuration by test or analysis."),
                    ("111", "Material not A-rated for Flam is sandwiched between non-flammable materials with edges only exposed and is more than 2 IN. from an ignition source or more than 12 IN. from other materials not A-rated."),
                    ("112", "Material not A-rated for Flam is unexposed or is over coated with a non-flammable material."),
                    ("113", "Material (not more than 0.010 IN. thickness) no A-rated for Flam is sprayed or bonded to a metallic surface > 0.062 IN. thick."),
                    ("114", "Material not A-rated for Flam is used in 'small amounts' and is more than 2 IN. from an ignition source or more than 12 IN. from other materials not A-rated for Flam. 'Small amounts' for Flam may be quantified as follows: Total weight < 0.1 LB. and < 2.0 SQ. IN. surface area."),
                ],
            ),
            (
                "TOXICITY (OFFGASSING) RATIONALE CODES",
                [
                    ("201", "Approved materials usage agreement (MUA) Category I."),
                    ("202", "Approved materials usage agreement (MUA) Category II."),
                    ("203", "T value for material/component in usage weight is less than 0.5 in each 118 cubic meter volume."),
                    ("204", "Materials usage in hermetically sealed container."),
                ],
            ),
            (
                "FLUID SYSTEM COMPATIBILITY RATIONALE CODES",
                [
                    ("301", "Approved materials usage agreement (MUA) Category I."),
                    ("302", "Passes requirements in configuration."),
                    ("303", "'B' rated material passed in batch lot test."),
                    ("304", "Approved materials usage agreement (MUA) Category II."),
                ],
            ),
            (
                "THERMAL VACUUM STABILITY (TVS) RATIONALE CODES",
                [
                    ("401", "Approved materials usage agreement (MUA) Category I."),
                    ("402", "Approved materials usage agreement (MUA) Category II."),
                    ("403", "'C' rated material; exposed area is not more than 2 SQ. IN. and not near a critical surface."),
                    ("404", "'X' rated material; exposed area less than 1/4 SQ. IN."),
                    ("405", "Unexposed, over coated or encapsulated with approved material."),
                    ("406", "'B' rated material cured to meet the requirements of an 'A' rated material."),
                    ("407", "Meets TVS requirements in configuration."),
                    ("408", "Materials usage in hermetically sealed container."),
                    ("409", "Material not A-rated for TVS in enclosed in a sealed container (i.e., designed with a leakage rate of <0.0001 standard CC/SEC. with atmosphere pressure differential - ref. MSFC-PROC-1301, Section 1.3)."),
                ],
            ),
            (
                "STRESS CORROSION CRACKING (SCC) RATIONALE CODES",
                [
                    ("501", "Approved materials usage agreement (MUA) Category I."),
                    ("502", "Approved materials usage agreement (MUA) Category II."),
                    ("503", "Maximum tensile stress less than 50% of yield strength for part on electrical/electronic assemblies."),
                    ("504", "Martensitic or PH stainless steels used in ball bearing, race or similar applications where the primary loading is compressive."),
                    ("505", "Metal not A-rated for SCC is not exposed to a corrosive environment after final assembly through end item use."),
                    ("506", "Carbon & low alloy high strength steels in greater than 180 KSI used in ball bearings, springs, or similar applications where primary loading is compressive, low tensile stresses, or history of satisfactory performance."),
                ],
            ),
            (
                "CORROSION (Corr) RATIONALE CODES",
                [
                    ("601", "Approved materials usage agreement (MUA) Category I."),
                    ("602", "Approved materials usage agreement (MUA) Category II."),
                    ("603", "Adequately finished for corrosion protection."),
                    ("604", "Acceptable for use environment."),
                    ("606", "Electrical grounding required, cladding plus conversion coating adequate."),
                    ("607", "Thermal conductance and electrical bonding requirements preclude painting. Conversion coating is adequate (for aluminum only)."),
                    ("608", "Finished on a higher assembly."),
                    ("609", "Laminated shim - minimum exposure of corrosion resistant material."),
                    ("610", "Surface of a metal not A-rated for Corr is treated or coated in a manner which meets or exceeds the requirements of MSFC-SPEC-250A. Actual surface treatment shall be listed."),
                    ("611", "Metal not A-rated for Corr is not exposed to a corrosive environment after final assembly and through end item use."),
                    ("612", "Welding of titanium alloy-to-alloy or CP-to-alloy using CP filler metal in mixed alloy welds where hydrogen embrittlement is not predicted in service."),
                ],
            ),
            (
                "GENERAL CODES",
                [
                    ("701", "Material ratings in MAPTIS (Material and Processes Technical Information System) are used for acceptance in place of MSFC-HDBK-527/JSC 09604. (Date of MAPTIS rating usage to be documented.)"),
                    ("702", "Generic materials controlled by MIL-SPEC or industry specification using MAPTIS averages for ratings or test results. Material codes for generic material shall be used."),
                    ("703", "MIL-SPEC or industry spec allowing several material options where all options have acceptable ratings."),
                    ("704", "Materials controlled by SSQ specification."),
                ],
            ),
        ]

        code_counts = _extract_rationale_codes(frame)

        max_clear_row = max(ws.max_row, 320)
        for row_idx in range(1, max_clear_row + 1):
            for col_idx in range(1, 8):
                try:
                    ws.cell(row=row_idx, column=col_idx).value = None
                except AttributeError:
                    continue

        ws["A1"] = "MUA III Codes"
        out_row_idx = 3
        known_codes = {code for _, entries in code_sections for code, _ in entries}

        for section_title, entries in code_sections:
            ws.cell(row=out_row_idx, column=1, value=section_title)
            out_row_idx += 1
            ws.cell(row=out_row_idx, column=1, value="Code")
            ws.cell(row=out_row_idx, column=2, value="Rationale")
            ws.cell(row=out_row_idx, column=3, value="Count")
            out_row_idx += 1

            for code, rationale in entries:
                ws.cell(row=out_row_idx, column=1, value=code)
                ws.cell(row=out_row_idx, column=2, value=rationale)
                ws.cell(row=out_row_idx, column=3, value=code_counts.get(code, 0))
                out_row_idx += 1

            out_row_idx += 2

        extra_codes = [
            code for code in code_counts.keys()
            if code not in known_codes
        ]
        if extra_codes:
            def _code_sort(code: str) -> Tuple[int, Any]:
                if re.fullmatch(r"\d+", code):
                    return (0, int(code))
                return (1, code)

            ws.cell(row=out_row_idx, column=1, value="ADDITIONAL CODES FOUND")
            out_row_idx += 1
            ws.cell(row=out_row_idx, column=1, value="Code")
            ws.cell(row=out_row_idx, column=2, value="Rationale")
            ws.cell(row=out_row_idx, column=3, value="Count")
            out_row_idx += 1

            for code in sorted(extra_codes, key=_code_sort):
                ws.cell(row=out_row_idx, column=1, value=code)
                ws.cell(row=out_row_idx, column=2, value="(Not in standard MUA III reference list)")
                ws.cell(row=out_row_idx, column=3, value=code_counts.get(code, 0))
                out_row_idx += 1

    def _populate_notes_sheet(ws: Any, frame: pd.DataFrame, parent_rows: List[Tuple[int, str, str]]) -> None:
        max_clear_row = max(ws.max_row, 40)
        for row_idx in range(1, max_clear_row + 1):
            for col_idx in range(1, 15):
                try:
                    ws.cell(row=row_idx, column=col_idx).value = None
                except AttributeError:
                    continue

        top_level = _as_text((dt_json or {}).get("top_level", ""))
        data_rows = _data_rows_only(frame)

        notes = [
            "Assembly Notes",
            "",
            f"1. Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
            f"2. Project: {project_name or top_level or 'N/A'}",
            f"3. Top-Level Drawing: {top_level or 'N/A'}",
            f"4. Drawing Count: {len(parent_rows)}",
            f"5. Material Rows: {len(data_rows)}",
            (
                "6. Environment: "
                f"{_as_text(env_defaults['fluid_type']) or 'N/A'}, "
                f"O2 {_as_text(env_defaults['o2_percent']) or 'N/A'}%, "
                f"P {_as_text(env_defaults['min_pressure']) or 'N/A'}-"
                f"{_as_text(env_defaults['max_pressure']) or 'N/A'} psia, "
                f"T {_as_text(env_defaults['min_temp']) or 'N/A'}-"
                f"{_as_text(env_defaults['max_temp']) or 'N/A'} F"
            ),
            "7. Add assembly-specific engineering notes below as needed.",
        ]

        for row_idx, note in enumerate(notes, start=1):
            ws.cell(row=row_idx, column=1, value=note)

    def _ensure_required_tabs(wb: Workbook, miul_ws: Any) -> Tuple[Any, Any, Any]:
        if miul_ws.title != "MIUL":
            miul_ws.title = "MIUL"

        required = {"MIUL", "Parents", "Codes", "Notes"}
        for sheet_name in list(wb.sheetnames):
            if sheet_name not in required:
                try:
                    del wb[sheet_name]
                except Exception:
                    LOGGER.debug("[2Phase] Could not remove extra sheet '%s'", sheet_name, exc_info=True)

        parents_ws = wb["Parents"] if "Parents" in wb.sheetnames else wb.create_sheet("Parents")
        codes_ws = wb["Codes"] if "Codes" in wb.sheetnames else wb.create_sheet("Codes")
        notes_ws = wb["Notes"] if "Notes" in wb.sheetnames else wb.create_sheet("Notes")
        return parents_ws, codes_ws, notes_ws

    template_path = Path(__file__).resolve().parents[3] / "docs" / "OPIV_MIUL_Updated.xlsm"
    if template_path.exists():
        try:
            # Load template without preserving VBA so output workbook is macro-free.
            wb = load_workbook(template_path, keep_vba=False)
            ws = wb["MIUL"] if "MIUL" in wb.sheetnames else (wb["Sheet1"] if "Sheet1" in wb.sheetnames else wb.active)

            data_df = _filter_sentinel_rows(df)
            parents_rows = _build_parent_rows(data_df)

            # Managed columns for data population. Leave formula helper columns
            # (AN/AO/AP) untouched so template logic remains available.
            managed_cols = [
                "A", "B", "C", "D", "E", "F", "G", "H", "I", "J", "K", "L",
                "P", "Q", "R", "S", "T", "U", "V", "W", "X", "Y", "Z",
                "AA", "AB", "AC", "AD", "AE", "AF", "AG", "AH", "AI", "AJ", "AK", "AL",
            ]
            managed_idx = [column_index_from_string(col) for col in managed_cols]
            data_no_fill = PatternFill(fill_type=None)

            # Clear previous sample data in managed columns.
            for row_idx in range(2, ws.max_row + 1):
                for col_idx in managed_idx:
                    cell = ws.cell(row=row_idx, column=col_idx)
                    cell.value = None
                    cell.fill = data_no_fill

            # New builds should not carry template conditional color shading.
            try:
                ws.conditional_formatting._cf_rules.clear()
            except Exception:
                LOGGER.debug("[2Phase] Could not clear conditional formatting on MIUL sheet", exc_info=True)

            # Populate template rows.
            last_dwg_number: str = ""
            for out_row_idx, (_, row) in enumerate(data_df.iterrows(), start=2):
                part_number = _as_cell(row.get("Part Number", ""))
                nomenclature = _as_cell(row.get("Nomenclature", "")) or _as_cell(row.get("Part Description", ""))
                source_dwg = _as_cell(row.get("Drawing Source", ""))
                nha_val = _as_cell(row.get("NHA", ""))

                # Dwg Number should be the source drawing when available.
                # Fall back to part number when source drawing is blank.
                dwg_number = source_dwg or part_number
                dwg_display = dwg_number if dwg_number and dwg_number != last_dwg_number else None
                if dwg_number:
                    last_dwg_number = str(dwg_number)

                material_code = _as_cell(row.get("Material Code", ""))

                qty_value = _as_cell(row.get("Qty", None))

                opiv_cells = {
                    "A": _safe_int(row.get("Index", None)),  # Index
                    "B": _safe_int(row.get("Parent", None)),  # Parent
                    "C": dwg_display,  # Dwg Number (only at first row for each drawing group)
                    "D": nha_val,  # NHAssy
                    "E": _as_cell(row.get("Line Number", None)),  # Find No.
                    "F": part_number,  # Part Number
                    "G": nomenclature,  # Nomenclature
                    "H": material_code,  # Material Code
                    "I": _as_cell(row.get("Designation", "")),  # Designation
                    "J": source_dwg,  # Dwg Source
                    "K": _as_cell(row.get("Material Specification", "")),  # Material Spec.
                    "L": _as_cell(row.get("Process Specification", "")),  # Process Spec.
                    "P": qty_value,  # Qty
                    "Q": _as_cell(row.get("Cure Codes", "")),  # Cure No.
                    "R": _as_cell(row.get("FLAM", "")),  # FLAMM Rating
                    "S": _as_cell(row.get("SCC", "")),  # SCC Rating
                    "T": _as_cell(row.get("CORR", "")),  # CORR Rating
                    "U": _as_cell(row.get("TVS", "")),  # TVS Rating
                    "V": _as_cell(row.get("TOX", "")),  # TOX Rating
                    "W": _as_cell(row.get("FS", "")),  # FS Rating
                    "X": _as_cell(row.get("Overall Evaluation", "")),  # MUA
                    "Y": _as_cell(row.get("MUA Rationale", "")),  # Rationale Code
                    "Z": _as_cell(row.get("Remarks", "")),  # Remarks
                    "AA": _as_cell(row.get("Change Letter", "")),  # Dwg Rev
                    "AB": _as_cell(row.get("Document Title", "")) or _as_cell(row.get("Part Description", "")),  # Dwg Description
                    "AC": _as_cell(row.get("Part Description", "")),  # Part Description
                    "AD": _as_cell(row.get("System", "")),  # System
                    "AE": _as_cell(row.get("Subsystem", "")),  # Subsystem
                    "AF": _as_cell(row.get("O2 %", None)) if "O2 %" in row.index else _as_cell(env_defaults["o2_percent"]),  # O2 %
                    "AG": _as_cell(row.get("Max Pressure", None)) or _as_cell(env_defaults["max_pressure"]),  # Max Pressure
                    "AH": _as_cell(row.get("Min Pressure", None)) or _as_cell(env_defaults["min_pressure"]),  # Min Pressure
                    "AI": _as_cell(row.get("Max Temperature", None)) or _as_cell(env_defaults["max_temp"]),  # Max Temp
                    "AJ": _as_cell(row.get("Min Temperature", None)) or _as_cell(env_defaults["min_temp"]),  # Min Temp
                    "AK": _as_cell(row.get("Fluid Type", "")) or _as_cell(env_defaults["fluid_type"]),  # Media
                    "AL": _as_cell(row.get("Criticality", "")),  # Criticality
                }

                for col_letter, value in opiv_cells.items():
                    target = ws[f"{col_letter}{out_row_idx}"]
                    target.value = value
                    target.fill = data_no_fill

            parents_ws, codes_ws, notes_ws = _ensure_required_tabs(wb, ws)
            _populate_parents_sheet(parents_ws, parents_rows)
            _populate_codes_sheet(codes_ws, data_df)
            _populate_notes_sheet(notes_ws, data_df, parents_rows)

            output_path.parent.mkdir(parents=True, exist_ok=True)
            wb.save(str(output_path))
            LOGGER.info(f"[2Phase] Exported MIUL using OPIV template: {output_path}")
            return
        except Exception as exc:
            LOGGER.exception(
                "[2Phase] OPIV template export failed; falling back to legacy exporter: %s",
                exc,
            )

    # Legacy fallback export (non-template)
    HEADER_FILL = PatternFill(start_color="1F4E79", end_color="1F4E79", fill_type="solid")
    HEADER_FONT = Font(bold=True, color="FFFFFF", size=10)
    THIN_BORDER = Border(
        left=Side(style="thin"), right=Side(style="thin"),
        top=Side(style="thin"), bottom=Side(style="thin"),
    )

    wb = Workbook()
    ws = wb.active
    ws.title = "MIUL"
    data_df = _filter_sentinel_rows(df)
    parents_rows = _build_parent_rows(data_df)

    for col_idx, (header, _, width) in enumerate(MAPTIS_COLUMNS, start=1):
        cell = ws.cell(row=1, column=col_idx, value=header)
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
        cell.border = THIN_BORDER
        cell.alignment = Alignment(horizontal="center", wrap_text=True)
        ws.column_dimensions[get_column_letter(col_idx)].width = width

    for row_idx, (_, row) in enumerate(df.iterrows(), start=2):
        for col_idx, (header, _, _) in enumerate(MAPTIS_COLUMNS, start=1):
            if header in row.index:
                value = row[header]
            elif header == "Project":
                value = project_name
            else:
                value = ""

            if pd.isna(value):
                value = ""

            cell = ws.cell(row=row_idx, column=col_idx, value=value)
            cell.border = THIN_BORDER

    ws.freeze_panes = "A2"

    parents_ws, codes_ws, notes_ws = _ensure_required_tabs(wb, ws)
    _populate_parents_sheet(parents_ws, parents_rows)
    _populate_codes_sheet(codes_ws, data_df)
    _populate_notes_sheet(notes_ws, data_df, parents_rows)

    wb.save(str(output_path))
    LOGGER.info(f"[2Phase] Exported MIUL (legacy fallback) to {output_path}")
