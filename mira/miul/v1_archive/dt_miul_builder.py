#!/usr/bin/env python3
"""
Module: Dt Miul Builder
Purpose: DT-First MIUL Builder - Drawing Tree as Single Source of Truth.

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

from __future__ import annotations

import base64
import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from datetime import datetime

# Load .env if present
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

# Import extraction fixes
try:
    from mira.miul.extraction_fixes import (
        clean_solidworks_designation,
        parse_embedded_material,
        is_drawing_reference,
        normalize_part_number,
        PurchasedPartLookup,
        ChildDrawingResolver,
        DrawingMaterial,
    )
    EXTRACTION_FIXES_AVAILABLE = True
except ImportError:
    EXTRACTION_FIXES_AVAILABLE = False

logger = logging.getLogger(__name__)

__all__ = ["DTMIULBuilder", "build_miul_from_dt"]


# MAPTIS MIUL columns (38 per spec)
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


@dataclass
class DTNode:
    """Node in the Drawing Tree hierarchy."""
    part_number: str
    description: str = ""
    parent_pn: str = ""  # Parent part number (NHA)
    children: List[DTNode] = field(default_factory=list)
    is_assembly: bool = False  # True if has EPL/children

    # Assigned during DFS traversal
    index: int = 0
    parent_index: int = 0

    # Material data (merged from detail drawings)
    designation: str = ""
    material_spec: str = ""
    process_spec: str = ""
    form: str = ""
    material_code: str = ""
    manufacturer: str = ""

    # Subparts from EPL (populated separately)
    subparts: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class DTHierarchy:
    """Complete hierarchy extracted from Drawing Tree."""
    miul_number: str  # Project acronym (e.g., "DMLLV")
    top_assembly: str  # Top-level assembly PN
    nodes: Dict[str, DTNode] = field(default_factory=dict)  # PN -> Node
    root_nodes: List[str] = field(default_factory=list)  # PNs with no parent


class DTMIULBuilder:
    """Build MIUL from Drawing Tree as single source of truth.

    The DT provides:
    - Complete assembly hierarchy
    - Parent-child relationships
    - Index assignment via DFS
    - NHA = parent part number

    Detail drawings provide:
    - Material designation
    - Material specification
    - Process specification
    - Material form
    """

    # Excel styling
    HEADER_FILL = PatternFill(start_color="1F4E79", end_color="1F4E79", fill_type="solid")
    HEADER_FONT = Font(bold=True, color="FFFFFF", size=10)
    ASSEMBLY_FILL = PatternFill(start_color="D6EAF8", end_color="D6EAF8", fill_type="solid")
    MIUL_ID_FILL = PatternFill(start_color="E8F5E9", end_color="E8F5E9", fill_type="solid")
    SUBPART_FILL = PatternFill(start_color="FFF3E0", end_color="FFF3E0", fill_type="solid")  # Light orange
    THIN_BORDER = Border(
        left=Side(style="thin"), right=Side(style="thin"),
        top=Side(style="thin"), bottom=Side(style="thin"),
    )

    def __init__(self, miul_number: str, project: str = ""):
        """Initialize builder.

        Args:
            miul_number: MIUL identifier (e.g., "DMLLV")
            project: Project name for Excel
        """
        self.miul_number = miul_number
        self.project = project or miul_number
        self._client = None  # Lazy init Anthropic client

    def _get_client(self):
        """Get Anthropic client (lazy init)."""
        if self._client is None:
            from anthropic import Anthropic
            self._client = Anthropic()
        return self._client

    def _sanitize_material_designation(
        self,
        designation: str,
        source: str = "unknown",
        context: str = ""
    ) -> str:
        """Centralized material designation sanitization.

        Applies uniform cleaning/filtering to materials from any source.

        Args:
            designation: Raw material designation
            source: Origin of material (for logging)
            context: Additional context (part number, etc.)

        Returns:
            Cleaned designation, or empty string if invalid
        """
        if not designation:
            return ""

        original = designation
        cleaned = designation.strip()

        # Step 1: Filter non-material sentinel values
        if cleaned.upper() in ("AR", "A/R", "REF", "-", "N/A", "TBD", "SEE NOTES"):
            logger.debug(f"[DT-MIUL] Filtered non-material from {source}: '{cleaned}' {context}")
            return ""

        # Step 2: Clean SolidWorks simulation suffixes
        if EXTRACTION_FIXES_AVAILABLE:
            cleaned = clean_solidworks_designation(cleaned)

        # Step 3: Normalize whitespace
        cleaned = " ".join(cleaned.split())

        # Log transformations
        if cleaned != original:
            logger.debug(f"[DT-MIUL] Sanitized {source}: '{original}' -> '{cleaned}' {context}")

        return cleaned

    def build(
        self,
        dt_pdf_path: Path,
        drawing_dir: Optional[Path] = None,
        output_path: Optional[Path] = None,
        extract_epl: bool = True,
        strict_validation: bool = False,
    ) -> Path:
        """Build MIUL from Drawing Tree PDF.

        Args:
            dt_pdf_path: Path to -DT PDF file
            drawing_dir: Directory with detail drawings (for materials)
            output_path: Output Excel path
            extract_epl: If True, extract EPL tables from assembly drawings
            strict_validation: If True, raise error on orphan nodes

        Returns:
            Path to generated Excel file
        """
        dt_pdf_path = Path(dt_pdf_path)
        if drawing_dir is None:
            drawing_dir = dt_pdf_path.parent
        if output_path is None:
            output_path = drawing_dir / f"MIUL_{self.miul_number}.xlsx"

        logger.info(f"[DT-MIUL] Building MIUL from {dt_pdf_path.name}")

        # Step 1: Extract hierarchy from Drawing Tree (SSOT)
        hierarchy = self._extract_dt_hierarchy(dt_pdf_path)
        logger.info(f"[DT-MIUL] Extracted {len(hierarchy.nodes)} nodes, top={hierarchy.top_assembly}")

        # Step 2: Validate hierarchy
        validation_errors = self._validate_hierarchy(hierarchy)
        if validation_errors:
            for err in validation_errors:
                logger.warning(f"[DT-MIUL] Validation: {err}")

        # Step 3: Assign indices via DFS traversal
        orphans = self._assign_indices_dfs(hierarchy)
        if orphans:
            msg = f"Orphan nodes (not in DT hierarchy): {orphans}"
            if strict_validation:
                raise ValueError(msg)
            logger.warning(f"[DT-MIUL] {msg}")

        # Step 4: Extract materials from detail drawings
        if drawing_dir and drawing_dir.exists():
            materials = self._extract_materials(drawing_dir, set(hierarchy.nodes.keys()))
            self._merge_materials(hierarchy, materials)
            logger.info(f"[DT-MIUL] Merged materials for {len(materials)} parts")
        else:
            materials = {}
            logger.warning(f"[DT-MIUL] Skipping material extraction - drawing_dir not found: {drawing_dir}")

        # Step 5: Extract EPL tables from assembly drawings (subparts)
        if extract_epl and drawing_dir.exists():
            epl_count = self._extract_epl_tables(hierarchy, drawing_dir)
            logger.info(f"[DT-MIUL] Extracted {epl_count} subparts from EPL tables")

        # Step 5b: Resolve child drawing materials for EPL parts that reference drawings
        if EXTRACTION_FIXES_AVAILABLE and extract_epl and drawing_dir.exists():
            resolved_count = self._resolve_child_drawing_materials(hierarchy, materials, drawing_dir)
            if resolved_count:
                logger.info(f"[DT-MIUL] Resolved {resolved_count} materials from child drawings")

        # Step 6: Build compliant MIUL rows
        rows = self._build_miul_rows(hierarchy)

        # Step 7: Write Excel
        self._write_excel(rows, output_path)
        logger.info(f"[DT-MIUL] Wrote {len(rows)} rows to {output_path}")

        return output_path

    def _validate_hierarchy(self, hierarchy: DTHierarchy) -> List[str]:
        """Validate hierarchy integrity.

        Returns:
            List of validation error messages (empty if valid)
        """
        errors = []

        # Check for missing parents
        for pn, node in hierarchy.nodes.items():
            if node.parent_pn and node.parent_pn not in hierarchy.nodes:
                errors.append(f"{pn} references unknown parent '{node.parent_pn}'")

        # Check for circular references
        def has_cycle(node: DTNode, visited: set) -> bool:
            if node.part_number in visited:
                return True
            visited.add(node.part_number)
            for child in node.children:
                if has_cycle(child, visited.copy()):
                    return True
            return False

        for root_pn in hierarchy.root_nodes:
            if root_pn in hierarchy.nodes:
                if has_cycle(hierarchy.nodes[root_pn], set()):
                    errors.append(f"Circular reference detected from root {root_pn}")

        # Check for multiple roots (may be intentional but worth noting)
        if len(hierarchy.root_nodes) > 1:
            errors.append(f"Multiple root nodes: {hierarchy.root_nodes}")

        return errors

    def _extract_dt_hierarchy(self, dt_pdf_path: Path) -> DTHierarchy:
        """Extract complete hierarchy from Drawing Tree using AI Vision.

        Uses native PDF support for better accuracy.

        The AI extracts:
        - All drawing numbers
        - Parent-child relationships from visual tree structure
        - Descriptions

        Returns:
            DTHierarchy with nodes and relationships
        """
        import re as _re

        # Read PDF directly - native PDF support is better than image conversion
        pdf_bytes = dt_pdf_path.read_bytes()
        pdf_base64 = base64.b64encode(pdf_bytes).decode('utf-8')

        # Build AI prompt - generic to handle different DT visual formats
        prompt = """Analyze this Engineering Drawing Tree document and extract the COMPLETE assembly hierarchy.

TASK: Extract every drawing number and its parent-child relationship from the document.

This document may be in various formats:
- Visual tree diagram with boxes and connecting lines
- Indented list/outline format
- Table format with columns for Level, Drawing Number, Parent, Description
- Hierarchical flowchart

OUTPUT FORMAT (JSON):
{
    "top_assembly": "ABC-A000-D",  // The root/top-level assembly (the one with no parent)
    "hierarchy": [
        {"part_number": "ABC-A000-D", "parent": "", "description": "TOP ASSEMBLY"},
        {"part_number": "ABC-A100-A", "parent": "ABC-A000-D", "description": "SUBASSEMBLY 1"},
        {"part_number": "ABC-101-A", "parent": "ABC-A100-A", "description": "DETAIL PART"},
        {"part_number": "ABC-A200-B", "parent": "ABC-A000-D", "description": "SUBASSEMBLY 2"}
    ]
}

DRAWING NUMBER FORMATS TO LOOK FOR:
- Any alphanumeric code that appears to be a drawing/part number
- PREFIX-NUMBER-REVISION format (e.g., ABC-12345-A, XYZ-001-B)
- MER#####-### format (e.g., MER07540-001)
- Custom project formats with dashes, numbers, and letters

RULES:
1. Extract EVERY drawing number visible in the document
2. Parent = the assembly this item belongs to (one level up in the hierarchy)
3. Top assembly has parent = "" (empty string)
4. Include the description/title for each drawing if shown
5. IMPORTANT: Drawing numbers are alphanumeric codes, NOT file paths or URLs
6. If the document shows assembly levels (1, 2, 3, etc.), use them to determine parent-child relationships
7. If you see "NHA" or "Next Higher Assembly", that indicates the parent

Return ONLY valid JSON, no other text."""

        # Call AI Vision with native PDF support
        client = self._get_client()

        content = [
            {
                "type": "document",
                "source": {
                    "type": "base64",
                    "media_type": "application/pdf",
                    "data": pdf_base64,
                },
            },
            {"type": "text", "text": prompt},
        ]

        logger.info(f"[DT-MIUL] Sending DT PDF to Vision API: {dt_pdf_path.name}")

        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=8000,
            messages=[{"role": "user", "content": content}]
        )

        # Parse response
        response_text = response.content[0].text
        logger.debug(f"[DT-MIUL] Vision API response length: {len(response_text)} chars")

        # Extract JSON from response
        json_match = response_text
        if "```json" in response_text:
            json_match = response_text.split("```json")[1].split("```")[0]
        elif "```" in response_text:
            json_match = response_text.split("```")[1].split("```")[0]

        try:
            data = json.loads(json_match.strip())
        except json.JSONDecodeError as e:
            logger.error(f"[DT-MIUL] Failed to parse JSON from Vision response: {e}")
            logger.error(f"[DT-MIUL] Response text: {response_text[:500]}...")
            # Return empty hierarchy - will be populated by fallback logic
            return DTHierarchy(miul_number=self.miul_number, top_assembly="")

        # Validate top_assembly is a valid drawing number, not a file path
        top_assembly = data.get("top_assembly", "")
        if top_assembly:
            # Check if it looks like a file path (contains / or \ or looks like a directory)
            if "/" in top_assembly or "\\" in top_assembly or ":" in top_assembly:
                logger.warning(f"[DT-MIUL] Invalid top_assembly (looks like file path): {top_assembly}")
                top_assembly = ""
            # Also validate it has some alphanumeric characters typical of drawing numbers
            elif not _re.search(r'[A-Z0-9]{3,}', top_assembly, _re.IGNORECASE):
                logger.warning(f"[DT-MIUL] Invalid top_assembly (doesn't look like drawing number): {top_assembly}")
                top_assembly = ""

        # Build hierarchy
        hierarchy = DTHierarchy(
            miul_number=self.miul_number,
            top_assembly=top_assembly,
        )

        hierarchy_list = data.get("hierarchy", [])
        if not hierarchy_list:
            logger.warning("[DT-MIUL] Vision API returned empty hierarchy list")
        else:
            logger.info(f"[DT-MIUL] Vision API returned {len(hierarchy_list)} hierarchy items")

        for item in hierarchy_list:
            pn = self._clean_pn(item.get("part_number", ""))
            if not pn:
                continue

            # Skip if it looks like a file path
            if "/" in pn or "\\" in pn or ":" in pn:
                logger.warning(f"[DT-MIUL] Skipping invalid part_number (file path): {pn}")
                continue

            parent_pn = self._clean_pn(item.get("parent", ""))

            node = DTNode(
                part_number=pn,
                description=item.get("description", ""),
                parent_pn=parent_pn,
            )
            hierarchy.nodes[pn] = node

            if not parent_pn:
                hierarchy.root_nodes.append(pn)

        # Build children lists
        for pn, node in hierarchy.nodes.items():
            if node.parent_pn and node.parent_pn in hierarchy.nodes:
                hierarchy.nodes[node.parent_pn].children.append(node)

        # If we have nodes but no valid top_assembly, use the first root node
        if not hierarchy.top_assembly and hierarchy.root_nodes:
            hierarchy.top_assembly = hierarchy.root_nodes[0]
            logger.info(f"[DT-MIUL] Auto-selected top_assembly from roots: {hierarchy.top_assembly}")

        logger.info(f"[DT-MIUL] Extracted hierarchy: {len(hierarchy.nodes)} nodes, "
                    f"{len(hierarchy.root_nodes)} roots, top={hierarchy.top_assembly}")

        return hierarchy

    def _assign_indices_dfs(self, hierarchy: DTHierarchy) -> List[str]:
        """Assign sequential indices via depth-first traversal.

        This ensures parents are ALWAYS indexed before children,
        which is required for proper MIUL Parent column values.

        Returns:
            List of orphan part numbers (nodes not reachable from roots)
        """
        index = 1  # Start at 1 (rows 1-2 are MIUL headers, data starts at 3)
        orphans = []

        def traverse(node: DTNode, parent_idx: int) -> None:
            nonlocal index
            node.index = index
            node.parent_index = parent_idx
            node.is_assembly = len(node.children) > 0
            index += 1

            # Process children in order
            for child in node.children:
                traverse(child, node.index)

        # Start from root nodes
        for root_pn in hierarchy.root_nodes:
            if root_pn in hierarchy.nodes:
                traverse(hierarchy.nodes[root_pn], 0)

        # Handle orphans (nodes not reachable from roots)
        for pn, node in hierarchy.nodes.items():
            if node.index == 0:
                orphans.append(pn)
                node.index = index
                node.parent_index = 0  # Orphan becomes root
                index += 1

        return orphans

    def _extract_epl_tables(
        self,
        hierarchy: DTHierarchy,
        drawing_dir: Path
    ) -> int:
        """Extract EPL (Engineering Parts List) from assembly drawings.

        For each assembly in the hierarchy, find its PDF and extract
        the parts list table (fasteners, seals, hardware, etc.).

        Returns:
            Count of subparts extracted
        """
        total_subparts = 0

        # Find assembly drawings using multiple criteria:
        # 1. Nodes with children in hierarchy (is_assembly flag)
        # 2. Nodes with "ASSEMBLY" in description
        # 3. Part numbers matching assembly patterns (e.g., PREFIX-Axxx)
        # 4. Part numbers ending with common assembly suffixes
        import re as _re

        def is_likely_assembly(pn: str, node: DTNode) -> bool:
            # Already marked as assembly
            if node.is_assembly or node.children:
                return True
            # Description contains "assembly"
            if node.description and "ASSEMBL" in node.description.upper():
                return True
            # Pattern: PREFIX-Axxx (A followed by digits indicates assembly)
            if _re.match(r'^[A-Z]+-A\d+', pn, _re.IGNORECASE):
                return True
            # Pattern: PREFIX-A000 style (top assembly)
            if _re.match(r'^[A-Z]+-A0+', pn, _re.IGNORECASE):
                return True
            return False

        # List all PDFs in directory first (needed for assembly detection and matching)
        # Handle both .pdf and .PDF extensions (case sensitivity varies by OS)
        all_pdfs = list(drawing_dir.glob("*.pdf")) + list(drawing_dir.glob("*.PDF"))
        # Deduplicate (on case-insensitive systems, both globs may return same files)
        all_pdfs = list({p.resolve(): p for p in all_pdfs}.values())
        logger.info(f"[DT-MIUL] Available PDFs in {drawing_dir}: {[p.name for p in all_pdfs]}")

        assembly_pns = [
            pn for pn, node in hierarchy.nodes.items()
            if is_likely_assembly(pn, node)
        ]

        # Helper to get base PN (strip trailing single char/digit suffix)
        def get_base_for_comparison(pn: str) -> str:
            """Strip trailing -1, -A, -D etc. for comparison."""
            if '-' in pn:
                parts = pn.rsplit('-', 1)
                suffix = parts[1]
                # Strip if single digit, single letter, or short numeric
                if len(suffix) == 1 or (suffix.isdigit() and len(suffix) <= 2):
                    return parts[0]
            return pn

        # Build set of base PNs already in assembly list
        existing_bases = {get_base_for_comparison(pn) for pn in assembly_pns}

        # Also scan the drawing directory for files with "Assembly" in the name
        # even if they're not in the hierarchy
        for pdf in all_pdfs:
            if "ASSEMBLY" in pdf.name.upper():
                # Extract base part number from filename (e.g., "ABC-A100-A" from "ABC-A100-A (Assembly).pdf")
                stem = pdf.stem.split("(")[0].strip()
                stem_base = get_base_for_comparison(stem)
                # Check if base PN already covered
                if stem_base not in existing_bases:
                    assembly_pns.append(stem)
                    existing_bases.add(stem_base)
                    logger.info(f"[DT-MIUL] Added assembly from filename: {stem}")

        if not assembly_pns:
            logger.warning("[DT-MIUL] No assemblies identified for EPL extraction")
            return 0

        logger.info(f"[DT-MIUL] Extracting EPL from {len(assembly_pns)} assemblies: {assembly_pns}")

        for assy_pn in assembly_pns:
            # Find the PDF for this assembly
            # Part numbers may have dash numbers (ABC-A100-1) but files have revisions (ABC-A100-A)
            # Extract base drawing number by removing the last dash-suffix if it's numeric
            base_pn = assy_pn
            if '-' in assy_pn:
                parts = assy_pn.rsplit('-', 1)
                # If the last part is numeric (dash number like -1, -2, -001), use just the base
                if parts[1].isdigit() or (len(parts[1]) <= 3 and parts[1][0].isdigit()):
                    base_pn = parts[0]

            # Try multiple search patterns (both .pdf and .PDF)
            pdf_candidates = []
            for search_pn in [assy_pn, base_pn]:
                pdf_candidates = list(drawing_dir.glob(f"*{search_pn}*.pdf")) + list(drawing_dir.glob(f"*{search_pn}*.PDF"))
                if pdf_candidates:
                    break

            # Also try case-insensitive matching
            if not pdf_candidates:
                assy_lower = assy_pn.lower()
                base_lower = base_pn.lower()
                for pdf in all_pdfs:
                    pdf_lower = pdf.name.lower()
                    if assy_lower in pdf_lower or base_lower in pdf_lower:
                        pdf_candidates = [pdf]
                        break

            if not pdf_candidates:
                logger.warning(f"[DT-MIUL] No PDF found for assembly {assy_pn} (tried base: {base_pn})")
                continue

            pdf_path = pdf_candidates[0]  # Use first match
            logger.info(f"[DT-MIUL] Extracting EPL from {pdf_path.name} for {assy_pn} (base: {base_pn})")
            try:
                subparts = self._extract_epl_from_pdf(pdf_path, assy_pn)
                logger.info(f"[DT-MIUL] {assy_pn}: extracted {len(subparts)} subparts")
                if subparts:
                    # Ensure node exists in hierarchy (may have been added from filename scan)
                    if assy_pn not in hierarchy.nodes:
                        # Create node for assembly discovered from filename
                        hierarchy.nodes[assy_pn] = DTNode(
                            part_number=assy_pn,
                            description=f"Assembly (from {pdf_path.stem})",
                            is_assembly=True,
                        )
                        logger.info(f"[DT-MIUL] Created node for {assy_pn} from filename")
                    hierarchy.nodes[assy_pn].subparts = subparts
                    total_subparts += len(subparts)
            except Exception as e:
                logger.warning(f"[DT-MIUL] EPL extraction failed for {assy_pn}: {e}", exc_info=True)

        return total_subparts

    def _extract_epl_from_pdf(
        self,
        pdf_path: Path,
        assembly_pn: str
    ) -> List[Dict[str, Any]]:
        """Extract EPL table from a single assembly PDF.

        Uses native PDF support for better text extraction accuracy.

        Returns:
            List of subpart dicts with find_no, part_number, qty, description, material
        """
        # Read PDF directly - native PDF support is better than image conversion
        pdf_bytes = pdf_path.read_bytes()
        pdf_base64 = base64.b64encode(pdf_bytes).decode('utf-8')

        # CORRECTED EPL PROMPT - Distinguishes MATERIAL PART NUMBER from MATERIAL columns
        # BioServe EPLs have TWO material-related columns:
        #   - MATERIAL PART NUMBER: McMaster P/N (89015K28) or "AR"
        #   - MATERIAL: Actual designation (Al 6061-T6, 18-8 SS)
        prompt = f"""Extract ALL items from the PARTS LIST or EPL table on this assembly drawing.

ASSEMBLY: {assembly_pn}

CRITICAL - BioServe EPL tables have specific column formats. Look carefully for these columns:

COLUMN IDENTIFICATION:
1. ITEM NO / FIND NO - Row identifier (1, 2, 3, etc.)
2. QTY - Quantity (number or "AR" for As Required)
3. MATERIAL PART NUMBER - This is often a McMaster-Carr P/N (like 89015K28) or "AR" - NOT the material itself!
4. PART NUMBER - The drawing/part number (GPE-051-1, FH100-1M4-32, NAS1149, etc.)
5. PART TITLE / DESCRIPTION / NOMENCLATURE - What the part is (SCREW, BRACKET, ROD, etc.)
6. MATERIAL - The actual material designation (6061-T6, Al 6061-T6, 18-8 SS, AISI 304, etc.)
7. LOT - S/N - Lot/serial tracking (usually empty)

IMPORTANT: Some EPL tables do NOT have a MATERIAL column at all (especially for assemblies).
If there is no MATERIAL column, return material="" for all parts.

OUTPUT FORMAT (JSON):
{{
    "has_material_column": true,
    "parts": [
        {{"find_no": "1", "part_number": "GPE-051-1", "material_part_number": "AR", "description": "ROD", "qty": 4, "material": "6061-T6"}},
        {{"find_no": "2", "part_number": "89015K28", "material_part_number": "89015K28", "description": "SHIM", "qty": 8, "material": "Al 6061-T6"}},
        {{"find_no": "3", "part_number": "91732A355", "material_part_number": "91732A355", "description": "HELICAL INSERT, 6-32 X .138\\", 18-8 SS", "qty": 33, "material": "18-8 SS"}},
        {{"find_no": "4", "part_number": "FH100-1M4-32-625", "material_part_number": "", "description": "SCREW, 100 DEG FLAT HEAD", "qty": 6, "material": ""}}
    ]
}}

MATERIAL EXTRACTION RULES:
1. The "material" field comes ONLY from the MATERIAL column (rightmost data column, before LOT-S/N)
2. If there's no MATERIAL column, set has_material_column=false and material="" for all parts
3. DO NOT confuse MATERIAL PART NUMBER (McMaster P/N) with the MATERIAL (designation)
4. If material is embedded in description (like "HELICOIL, 18-8 SS"), extract it to material field
5. Common material formats: "6061-T6", "Al 6061-T6", "18-8 SS", "AISI 304 STAINLESS", "A286 CRES"
6. "(SS)" suffix like "6061-T6 (SS)" is SolidWorks notation - include as-is, we strip it later

CHARACTER ACCURACY - READ EACH CHARACTER TWICE:
7. Common misreads: 5 vs 8, 6 vs 8 vs 9, 0 vs O vs D, 1 vs I vs l
8. Copy part numbers EXACTLY as shown - character for character
9. For NAS/MS/AN hardware: double-check every digit

Return ONLY valid JSON. If no parts list table found, return {{"has_material_column": false, "parts": []}}"""

        client = self._get_client()

        # Send PDF directly using native document support (better than 150 DPI images)
        content = [
            {
                "type": "document",
                "source": {
                    "type": "base64",
                    "media_type": "application/pdf",
                    "data": pdf_base64,
                },
            },
            {"type": "text", "text": prompt},
        ]

        try:
            response = client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=4000,
                messages=[{"role": "user", "content": content}]
            )

            response_text = response.content[0].text
            logger.debug(f"[DT-MIUL] EPL response for {assembly_pn}: {response_text[:500]}...")

            # Parse JSON
            if "```json" in response_text:
                json_str = response_text.split("```json")[1].split("```")[0]
            elif "```" in response_text:
                json_str = response_text.split("```")[1].split("```")[0]
            else:
                json_str = response_text

            data = json.loads(json_str.strip())
            parts = data.get("parts", [])
            has_material_column = data.get("has_material_column", True)

            # Post-process extracted parts with extraction fixes
            if EXTRACTION_FIXES_AVAILABLE:
                parts = self._postprocess_epl_parts(parts, has_material_column, assembly_pn)

            logger.info(f"[DT-MIUL] EPL parsed {len(parts)} parts for {assembly_pn}")
            for p in parts[:5]:  # Log first 5 for debugging
                logger.debug(f"[DT-MIUL]   - {p.get('part_number')}: {p.get('description')} mat={p.get('material')} qty={p.get('qty')}")
            return parts

        except json.JSONDecodeError as e:
            logger.error(f"[DT-MIUL] EPL JSON parse error for {assembly_pn}: {e}")
            logger.error(f"[DT-MIUL] Response was: {response_text[:1000]}...")
            return []
        except Exception as e:
            logger.error(f"[DT-MIUL] EPL extraction error for {assembly_pn}: {e}", exc_info=True)
            return []

    def _postprocess_epl_parts(
        self,
        parts: List[Dict[str, Any]],
        has_material_column: bool,
        assembly_pn: str
    ) -> List[Dict[str, Any]]:
        """Post-process EPL parts with extraction fixes.

        Applies:
        1. SolidWorks suffix cleaning (removes "(SS)", "(SN)" from designations)
        2. Embedded material parsing (extracts "18-8 SS" from descriptions)
        3. Purchased parts lookup (McMaster patterns, helicoils, etc.)

        Args:
            parts: Raw extracted parts from EPL
            has_material_column: Whether the EPL had a material column
            assembly_pn: Parent assembly part number (for logging)

        Returns:
            Processed parts with cleaned/enriched materials
        """
        processed = []

        # Initialize purchased parts lookup if not already done
        if not hasattr(self, '_purchased_lookup'):
            self._purchased_lookup = PurchasedPartLookup()

        for part in parts:
            pn = part.get("part_number", "")
            desc = part.get("description", "")
            material = part.get("material", "")
            material_pn = part.get("material_part_number", "")

            # Step 0: Filter out non-material values (AR = As Required, typically qty marker)
            if material and material.upper() in ("AR", "A/R", "REF", "-", "N/A", "TBD"):
                logger.debug(f"[DT-MIUL] Filtered non-material value: '{material}'")
                part["material"] = ""
                material = ""

            # Also check material_part_number (shouldn't be used as material)
            if material_pn and material_pn.upper() in ("AR", "A/R", "REF", "-", "N/A", "TBD"):
                logger.debug(f"[DT-MIUL] Filtered non-material from material_part_number: '{material_pn}'")
                material_pn = ""  # Don't use for lookup

            # Step 1: Sanitize material designation
            if material:
                original_material = material
                material = self._sanitize_material_designation(
                    material,
                    source="epl_extraction",
                    context=f"(part={pn})"
                )
                if material != original_material:
                    part["material_original"] = original_material
                part["material"] = material

            # Step 2: If material is empty, try parsing from description
            if not material and desc:
                parsed = parse_embedded_material(desc, pn)
                if parsed and parsed.designation:
                    sanitized = self._sanitize_material_designation(
                        parsed.designation,
                        source="embedded_parsing",
                        context=f"(part={pn}, desc='{desc[:40]}')"
                    )
                    if sanitized:
                        part["material"] = sanitized
                        part["material_source"] = "embedded_in_description"
                        part["material_confidence"] = parsed.confidence
                        logger.debug(f"[DT-MIUL] Parsed embedded: {sanitized} (conf={parsed.confidence:.2f})")
                        material = sanitized

            # Step 3: If still empty, try purchased parts lookup
            if not material:
                # Try looking up by part number or material part number
                lookup_pn = material_pn if material_pn and material_pn != "AR" else pn
                lookup_result = self._purchased_lookup.lookup(lookup_pn, desc)
                # Only use result if confidence is reasonable (>= 0.7)
                # Low-confidence defaults like "ALLOY STEEL" are too generic for aerospace
                if lookup_result and lookup_result.material_designation and lookup_result.confidence >= 0.7:
                    sanitized = self._sanitize_material_designation(
                        lookup_result.material_designation,
                        source=f"purchased_lookup:{lookup_result.source}",
                        context=f"(lookup_pn={lookup_pn}, conf={lookup_result.confidence:.2f})"
                    )
                    if sanitized:
                        part["material"] = sanitized
                        part["material_source"] = f"purchased_parts:{lookup_result.source}"
                        part["material_confidence"] = lookup_result.confidence
                        if lookup_result.uns_number:
                            part["uns_number"] = lookup_result.uns_number
                        logger.debug(f"[DT-MIUL] Purchased lookup: {sanitized} (conf={lookup_result.confidence:.2f})")
                        material = sanitized
                elif lookup_result and lookup_result.material_designation:
                    # Low confidence - flag for review but don't auto-assign
                    part["material_needs_review"] = True
                    part["material_suggestion"] = lookup_result.material_designation
                    part["material_suggestion_confidence"] = lookup_result.confidence
                    logger.debug(f"[DT-MIUL] Low-conf suggestion for '{lookup_pn}': {lookup_result.material_designation} (conf={lookup_result.confidence:.2f}) - flagged for review")

            # Step 4: Mark drawing references for child resolution
            if is_drawing_reference(pn):
                part["is_drawing_reference"] = True

            processed.append(part)

        # Log summary
        enriched_count = sum(1 for p in processed if p.get("material_source"))
        if enriched_count:
            logger.info(f"[DT-MIUL] Enriched {enriched_count}/{len(processed)} parts for {assembly_pn}")

        return processed

    def _resolve_child_drawing_materials(
        self,
        hierarchy: DTHierarchy,
        materials: Dict[str, Dict[str, str]],
        drawing_dir: Path
    ) -> int:
        """Resolve materials for EPL parts that reference child drawings.

        When an EPL part has no material but its part_number references a
        drawing (e.g., GPE-051-1 -> GPE-051), try to find the material from:
        1. The already-extracted materials dict
        2. The child drawing PDF if needed

        Args:
            hierarchy: The drawing hierarchy with EPL subparts
            materials: Already-extracted materials from detail drawings
            drawing_dir: Directory containing drawing PDFs

        Returns:
            Count of materials resolved
        """
        resolved_count = 0
        unresolved_count = 0
        unresolved_parts = []

        # Convert materials dict to DrawingMaterial objects for the resolver
        # Apply same cleaning/filtering as _merge_materials()
        invalid_designations = {"AR", "A/R", "REF", "-", "N/A", "TBD", ""}

        drawing_materials = {}
        for pn, mat_info in materials.items():
            designation = mat_info.get("designation", "") or ""
            material_spec = mat_info.get("material_spec", "") or ""

            # Salvage: If designation is invalid but material_spec looks like a material, use it
            if designation.upper().strip() in invalid_designations and material_spec:
                # Check if material_spec looks like a material (contains common material keywords)
                spec_upper = material_spec.upper()
                material_keywords = ['ALUMINUM', 'AL ', 'STEEL', 'STAINLESS', 'CRES', 'TITANIUM',
                                     'BRASS', 'COPPER', 'PLASTIC', 'DELRIN', 'PEEK', 'ULTEM',
                                     '6061', '7075', '2024', '303', '304', '316', '17-4']
                if any(kw in spec_upper for kw in material_keywords):
                    logger.info(f"[DT-MIUL] Salvaging material for {pn}: designation='{designation}' -> using material_spec='{material_spec}'")
                    designation = material_spec
                    material_spec = ""  # Clear spec since we moved it to designation
                else:
                    logger.debug(f"[DT-MIUL] Filtered invalid designation '{designation}' in child resolver for {pn} (material_spec not usable)")
                    continue  # Skip this entry entirely
            elif designation.upper().strip() in invalid_designations:
                logger.debug(f"[DT-MIUL] Filtered invalid designation '{designation}' in child resolver for {pn}")
                continue  # Skip this entry entirely

            # Clean SolidWorks suffixes
            if EXTRACTION_FIXES_AVAILABLE and designation:
                cleaned = clean_solidworks_designation(designation)
                if cleaned != designation:
                    logger.debug(f"[DT-MIUL] Cleaned SW suffix in child resolver: '{designation}' -> '{cleaned}'")
                    designation = cleaned

            if designation:  # Only add if we have a valid designation
                drawing_materials[pn] = DrawingMaterial(
                    drawing_number=pn,
                    designation=designation,
                    material_spec=material_spec,
                    process_spec=mat_info.get("process_spec", ""),
                    form=mat_info.get("form", ""),
                    source="detail_drawing",
                )

        resolver = ChildDrawingResolver(drawing_materials)

        # Log what's available for resolution
        logger.info(f"[DT-MIUL] Child drawing resolver initialized with {len(drawing_materials)} drawings")
        if drawing_materials and len(drawing_materials) <= 15:
            for dwg_pn in sorted(drawing_materials.keys()):
                mat = drawing_materials[dwg_pn]
                logger.debug(f"[DT-MIUL]   - {dwg_pn}: {mat.designation}")
        elif drawing_materials:
            sample = sorted(drawing_materials.keys())[:5]
            for dwg_pn in sample:
                mat = drawing_materials[dwg_pn]
                logger.debug(f"[DT-MIUL]   - {dwg_pn}: {mat.designation}")
            logger.debug(f"[DT-MIUL]   ... and {len(drawing_materials) - 5} more")

        for pn, node in hierarchy.nodes.items():
            if not node.subparts:
                continue

            for subpart in node.subparts:
                # Skip if already has material
                if subpart.get("material"):
                    continue

                # Skip if not a drawing reference
                if not subpart.get("is_drawing_reference", False):
                    continue

                sub_pn = subpart.get("part_number", "")
                if not sub_pn:
                    continue

                # Try to resolve material using the resolver
                result = resolver.resolve(sub_pn)
                if result and result.designation:
                    subpart["material"] = result.designation
                    subpart["material_source"] = f"child_drawing:{result.drawing_number}"
                    subpart["material_confidence"] = 0.9  # High confidence from actual drawing
                    if result.material_spec:
                        subpart["material_spec"] = result.material_spec
                    resolved_count += 1
                    logger.debug(f"[DT-MIUL] Resolved {sub_pn} from child drawing: {result.designation}")
                else:
                    # Drawing reference but no material found
                    unresolved_count += 1
                    unresolved_parts.append(sub_pn)
                    subpart["material"] = ''
                    subpart["material_source"] = 'child_drawing_missing'
                    logger.debug(f"[DT-MIUL] Could not resolve {sub_pn} - not in materials dict")

        # Log resolution summary
        logger.info(f"[DT-MIUL] Child drawing resolution: {resolved_count} resolved, {unresolved_count} unresolved")
        if unresolved_parts:
            logger.warning(f"[DT-MIUL] Unresolved child drawings (no material found):")
            for part_pn in sorted(set(unresolved_parts))[:10]:
                logger.warning(f"[DT-MIUL]   - {part_pn}")
            if len(set(unresolved_parts)) > 10:
                logger.warning(f"[DT-MIUL]   ... and {len(set(unresolved_parts)) - 10} more")

        return resolved_count

    def _extract_materials(
        self,
        drawing_dir: Path,
        known_pns: set
    ) -> Dict[str, Dict[str, str]]:
        """Extract materials from detail drawings.

        Only extracts material info, NO hierarchy inference.

        Returns:
            Dict mapping part_number -> {designation, material_spec, ...}
        """
        materials = {}

        # Find all PDFs (both .pdf and .PDF - handle case sensitivity)
        pdf_files = list(drawing_dir.glob("*.pdf")) + list(drawing_dir.glob("*.PDF"))
        # Deduplicate (on case-insensitive systems, both globs may return same files)
        pdf_files = list({p.resolve(): p for p in pdf_files}.values())

        detail_pdfs = [
            p for p in pdf_files
            if not any(x in p.stem.upper() for x in ["-DT", "-DOC", "-ICD", "DRAWING TREE"])
        ]

        if not detail_pdfs:
            logger.warning(f"[DT-MIUL] No detail drawings found in {drawing_dir} (found {len(pdf_files)} PDFs but all filtered)")
            return materials

        logger.info(f"[DT-MIUL] Extracting materials from {len(detail_pdfs)} detail drawings")

        # Batch extract with AI Vision (process multiple at once for efficiency)
        batch_size = 5
        for i in range(0, len(detail_pdfs), batch_size):
            batch = detail_pdfs[i:i+batch_size]
            batch_materials = self._extract_materials_batch(batch)
            materials.update(batch_materials)

        return materials

    def _extract_materials_batch(
        self,
        pdf_paths: List[Path]
    ) -> Dict[str, Dict[str, str]]:
        """Extract materials from a batch of PDFs using native PDF support."""
        materials = {}

        prompt = """Extract material and process specifications from these engineering drawings.

CRITICAL - WHERE TO FIND MATERIALS:
1. MATERIALS TABLE - Look for a small table with "MATERIALS" header listing items like:
   | ITEM | DESCRIPTION | SPECIFICATION |
   |  1   | ALUMINUM    | AMS 4027      |
   |  2   | STAINLESS   | AMS 5643      |

2. TWO-COLUMN MATERIAL TABLES (BioServe/University of Colorado format):
   Some drawings have a table with TWO material-related columns:
   ┌──────────────────────┬──────────────────────┐
   │ MATERIAL PART NUMBER │ MATERIAL             │
   ├──────────────────────┼──────────────────────┤
   │ AR                   │ Al 6061-T6 MMPDS     │
   └──────────────────────┴──────────────────────┘

   CRITICAL: In this format:
   - "MATERIAL PART NUMBER" contains procurement codes (often "AR" = As Required)
   - "MATERIAL" column contains the ACTUAL ALLOY SPECIFICATION

   ALWAYS extract the alloy from the "MATERIAL" column (right side), NEVER from "MATERIAL PART NUMBER"!
   Example: If you see "AR | Al 6061-T6 MMPDS", extract "6061-T6 ALUMINUM" as designation.

3. FLAGGED NOTES - Look for notes with a triangle/flag symbol (▷ or △) pointing at them.
   These flags indicate important callouts including materials. Example:
   △1 MATERIAL: 6061-T6 ALUMINUM PER AMS 4027

3. TITLE BLOCK - Fields labeled MATERIAL, MAT'L, MATL, or MATERIAL SPEC

4. NUMBERED NOTES - Notes section with entries like:
   1. MATERIAL: ALUMINUM 6061-T6 PER AMS 4027
   2. FINISH: ANODIZE PER MIL-A-8625 TYPE II

CRITICAL - MSFC DRAWING FORMAT:
Many NASA MSFC drawings have EMPTY title block MATERIAL fields but specify material in NUMBERED NOTES.
Look for notes like: "3. MATERIAL: A286 CRES, UNS S66286, PER SAE AMS 5737"
When you find "MATERIAL:" in notes, parse it:
- designation = alloy name (e.g., "A286 CRES", "INCONEL 718", "INCONEL 625")
- material_spec = spec after "PER" (e.g., "SAE AMS 5737", "SAE AMS 5666")
THIS IS THE PRIMARY SOURCE for MSFC detail drawing materials!

5. GENERAL NOTES area - Usually bottom left or right of drawing

6. MATERIAL SPECIFICATIONS - If you see "MMFPDS", "MMFDS", or similar codes after a material,
   these are procurement specs that belong in material_spec, NOT designation.

Common material formats:
- "6061-T6 ALUMINUM", "7075-T73 AL", "2024-T3"
- "STAINLESS STEEL", "303 SS", "17-4 PH CRES"
- "DELRIN", "ULTEM", "PEEK", "VESPEL"

Common specification formats:
- AMS: "AMS 4027", "AMS 5643", "AMS-QQ-A-250"
- ASTM: "ASTM B209", "ASTM A276"
- MIL: "MIL-DTL-5541", "MIL-A-8625"
- MMFPDS, MMFDS: Military procurement specs (put in material_spec, not designation)

OUTPUT FORMAT (JSON):
{
    "materials": [
        {
            "part_number": "ABC-101-A",
            "designation": "6061-T6 ALUMINUM",
            "material_spec": "AMS 4027",
            "process_spec": "ANODIZE PER MIL-A-8625 TYPE II",
            "form": "PLATE"
        },
        {
            "part_number": "XYZ-201-1",
            "designation": "15-5 PH CRES",
            "material_spec": "AMS 5659",
            "process_spec": "PASSIVATE PER AMS-QQ-P-35",
            "form": "BAR"
        }
    ]
}

CRITICAL RULES FOR DESIGNATION FIELD:
1. NEVER use "AR", "A/R", "AS REQUIRED", "TBD", "REF", or "N/A" in designation
2. If the drawing shows "AR" in one column, CHECK THE ADJACENT "MATERIAL" COLUMN:
   - Two-column tables: "MATERIAL PART NUMBER" (left) has AR, "MATERIAL" (right) has the alloy
   - ALWAYS extract from the column labeled "MATERIAL", not "MATERIAL PART NUMBER"
   - Example: "AR | Al 6061-T6 MMPDS" → designation = "6061-T6 ALUMINUM"
3. If there's no adjacent material column, look elsewhere:
   - Check notes, flagged callouts, or specification codes for actual material
   - Extract the base material (e.g., "Al 6061-T6" from "Al 6061-T6 MMFPDS")
4. Designation = base material ONLY (aluminum alloy, steel grade, plastic type)
   - Examples: "6061-T6 ALUMINUM", "303 STAINLESS STEEL", "DELRIN"
   - NOT: "Al 6061-T6 MMFPDS" (MMFPDS goes in material_spec)
5. Put specifications (AMS, ASTM, MMFPDS) in material_spec, NOT designation
6. If you absolutely cannot find a material and only see "AR", leave designation empty

GENERAL RULES:
1. LOOK CAREFULLY at tables labeled "MATERIALS" - extract ALL items listed
2. LOOK for triangle/flag symbols (△ ▷) pointing at notes - these often contain material info
3. Extract the part number from the TITLE BLOCK (bottom right corner)
4. One entry per drawing document
5. Return empty strings for fields not explicitly stated on the drawing

Return ONLY valid JSON."""

        client = self._get_client()

        # Build content with native PDF documents
        content = []

        for pdf_path in pdf_paths:
            try:
                pdf_bytes = pdf_path.read_bytes()
                pdf_base64 = base64.b64encode(pdf_bytes).decode('utf-8')
                content.append({
                    "type": "document",
                    "source": {
                        "type": "base64",
                        "media_type": "application/pdf",
                        "data": pdf_base64,
                    }
                })
            except Exception as e:
                logger.warning(f"[DT-MIUL] Failed to read {pdf_path.name}: {e}")

        if not content:
            return materials  # No PDFs to process

        # Add prompt after documents
        content.append({"type": "text", "text": prompt})

        try:
            response = client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=4000,
                messages=[{"role": "user", "content": content}]
            )

            response_text = response.content[0].text

            # Parse JSON
            if "```json" in response_text:
                json_str = response_text.split("```json")[1].split("```")[0]
            elif "```" in response_text:
                json_str = response_text.split("```")[1].split("```")[0]
            else:
                json_str = response_text

            data = json.loads(json_str.strip())

            # Build expected part numbers from filenames for tracking
            expected_pns = {}
            for pdf_path in pdf_paths:
                filename_pn = self._extract_pn_from_filename(pdf_path)
                if filename_pn:
                    expected_pns[filename_pn] = pdf_path

            for item in data.get("materials", []):
                pn = self._clean_pn(item.get("part_number", ""))
                if pn:
                    mat_data = {
                        "designation": item.get("designation", ""),
                        "material_spec": item.get("material_spec", ""),
                        "process_spec": item.get("process_spec", ""),
                        "form": item.get("form", ""),
                    }
                    materials[pn] = mat_data
                    # Log what we found
                    has_material = any(v for v in mat_data.values())
                    if has_material:
                        logger.info(f"[DT-MIUL] Material found for {pn}: {mat_data}")
                    else:
                        logger.debug(f"[DT-MIUL] No material data for {pn}")

            # Detect missed PDFs - expected from filename but not in extraction results
            extracted_pns = set(materials.keys())
            for expected_pn, pdf_path in expected_pns.items():
                # Check if this expected PN (or a close variant) was extracted
                if expected_pn not in extracted_pns:
                    # Also check for partial matches (e.g., MER07560-001 vs MER07560-001-A)
                    found_match = any(
                        expected_pn in ext_pn or ext_pn in expected_pn
                        for ext_pn in extracted_pns
                    )
                    if not found_match:
                        logger.warning(f"[DT-MIUL] Batch missed {expected_pn} (from {pdf_path.name}) - retrying single extraction")
                        # Retry this single PDF
                        single_result = self._extract_single_pdf_material(pdf_path)
                        if single_result:
                            materials.update(single_result)
                            logger.info(f"[DT-MIUL] Single retry succeeded for {expected_pn}")
                        else:
                            # Add placeholder with filename-based PN so child resolver can find it later
                            logger.warning(f"[DT-MIUL] Single retry failed for {expected_pn} - adding placeholder")
                            materials[expected_pn] = {
                                "designation": "",
                                "material_spec": "",
                                "process_spec": "",
                                "form": "",
                                "_extraction_failed": True,
                            }

            # Retry PDFs that returned AR/empty designation (material likely in flagged notes)
            ar_designations = {"AR", "A/R", "TBD", "N/A", "REF", "-", ""}
            for pn, mat_data in list(materials.items()):
                designation = mat_data.get("designation", "").upper().strip()
                if designation in ar_designations and not mat_data.get("_ar_retried"):
                    # Find the PDF path for this PN
                    if pn in expected_pns:
                        logger.warning(f"[DT-MIUL] AR/empty designation for {pn} - retrying with flag-focused extraction")
                        single_result = self._extract_single_pdf_material(expected_pns[pn])
                        if single_result:
                            # Check if retry found a real material
                            for retry_pn, retry_data in single_result.items():
                                retry_designation = retry_data.get("designation", "").upper().strip()
                                if retry_designation and retry_designation not in ar_designations:
                                    logger.info(f"[DT-MIUL] Flag-focused retry found material for {retry_pn}: {retry_data['designation']}")
                                    materials[retry_pn] = retry_data
                                else:
                                    logger.debug(f"[DT-MIUL] Flag-focused retry still returned AR/empty for {retry_pn}")
                                    mat_data["_ar_retried"] = True  # Don't retry again
                        else:
                            mat_data["_ar_retried"] = True  # Don't retry again

            logger.info(f"[DT-MIUL] Batch extracted materials for {len(materials)} drawings")

        except json.JSONDecodeError as e:
            logger.error(f"[DT-MIUL] Material JSON parse error: {e}")
            logger.debug(f"[DT-MIUL] Response was: {response_text[:1000]}...")
        except Exception as e:
            logger.warning(f"[DT-MIUL] Material extraction failed: {e}", exc_info=True)

        return materials

    def _extract_single_pdf_material(
        self,
        pdf_path: Path
    ) -> Dict[str, Dict[str, str]]:
        """Extract material from a single PDF (retry for missed batch extractions).

        Uses a focused prompt for single-PDF extraction with the filename
        as a hint to improve accuracy.

        Args:
            pdf_path: Path to the PDF file

        Returns:
            Dict mapping part_number -> material data, or empty dict on failure
        """
        materials = {}
        filename_pn = self._extract_pn_from_filename(pdf_path)

        prompt = f"""STOP! This is an MSFC drawing. The material is NOT in the title block - look for FLAGGED NOTES.

PART NUMBER: {filename_pn} (verify against title block)

WHERE TO FIND THE MATERIAL:
1. FLAGGED NOTES - Look for triangle/flag symbols (△ ▷) or numbered notes with "MATERIAL:"
   Example formats:
   △1 MATERIAL: A286 CRES, UNS S66286, PER SAE AMS 5737
   3. MATERIAL: INCONEL 718, UNS N07718, PER AMS 5663

2. The title block MATERIAL field is likely EMPTY or says "AR" - IGNORE IT!
   The REAL material is in the flagged notes.

PARSE THE MATERIAL NOTE:
- "A286 CRES, UNS S66286, PER SAE AMS 5737" means:
  - designation = "A286 CRES" (the alloy name)
  - material_spec = "SAE AMS 5737" (spec after "PER")

- "INCONEL 718, UNS N07718, PER AMS 5663" means:
  - designation = "INCONEL 718"
  - material_spec = "AMS 5663"

NEVER return "AR", "A/R", "TBD", or empty for designation if there's a flagged note with material!

Return JSON:
{{"materials": [{{"part_number": "{filename_pn}", "designation": "...", "material_spec": "...", "process_spec": "...", "form": ""}}]}}

Return ONLY valid JSON."""

        client = self._get_client()

        try:
            pdf_bytes = pdf_path.read_bytes()
            pdf_base64 = base64.b64encode(pdf_bytes).decode('utf-8')

            response = client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=1000,
                messages=[{
                    "role": "user",
                    "content": [
                        {
                            "type": "document",
                            "source": {
                                "type": "base64",
                                "media_type": "application/pdf",
                                "data": pdf_base64,
                            }
                        },
                        {"type": "text", "text": prompt}
                    ]
                }]
            )

            response_text = response.content[0].text

            # Parse JSON
            if "```json" in response_text:
                json_str = response_text.split("```json")[1].split("```")[0]
            elif "```" in response_text:
                json_str = response_text.split("```")[1].split("```")[0]
            else:
                json_str = response_text

            data = json.loads(json_str.strip())

            for item in data.get("materials", []):
                pn = self._clean_pn(item.get("part_number", ""))
                if pn:
                    mat_data = {
                        "designation": item.get("designation", ""),
                        "material_spec": item.get("material_spec", ""),
                        "process_spec": item.get("process_spec", ""),
                        "form": item.get("form", ""),
                    }
                    materials[pn] = mat_data
                    logger.info(f"[DT-MIUL] Single extraction for {pn}: {mat_data}")

        except Exception as e:
            logger.warning(f"[DT-MIUL] Single PDF extraction failed for {pdf_path.name}: {e}")

        return materials

    def _merge_materials(
        self,
        hierarchy: DTHierarchy,
        materials: Dict[str, Dict[str, str]]
    ) -> None:
        """Merge material data into hierarchy nodes.

        Uses multi-level matching to handle part number format variations:
        1. Exact match: GPE-010-1 == GPE-010-1
        2. Material PN is prefix of hierarchy PN: GPE-010 matches GPE-010-1
        3. Hierarchy PN is prefix of material PN: MER07540-001 matches MER07540-001-A
        """
        merged_count = 0
        unmatched = []

        # Build lookups for prefix matching
        # Key: PN, Value: node
        # We'll match if material_pn.startswith(hierarchy_pn) or vice versa
        hierarchy_pns = list(hierarchy.nodes.keys())

        def normalize_for_matching(part_number: str) -> str:
            """Strip revision suffixes for base part number matching.

            Examples:
                GPE-010-A → GPE-010  (strips letter revision)
                GPE-014-1 → GPE-014  (strips number revision)
                GPE-015-B → GPE-015

            This handles cases where files are named with letter revisions (GPE-010-A)
            but EPLs reference them with number revisions (GPE-010-1).
            """
            import re
            base = part_number
            # Strip trailing dash + single letter (A, B, C, etc.)
            base = re.sub(r'-[A-Z]$', '', base)
            # Strip trailing dash + single digit (1, 2, 3, etc.)
            base = re.sub(r'-\d$', '', base)
            return base

        def find_matching_node(material_pn: str) -> Optional[DTNode]:
            """Find hierarchy node matching material PN using multi-level strategy."""
            # Level 0: Match on base part number (strip revision suffixes)
            # Handles: GPE-010-A (file) matches GPE-010-1 (EPL reference)
            base_material_pn = normalize_for_matching(material_pn)
            for h_pn in hierarchy_pns:
                if normalize_for_matching(h_pn) == base_material_pn:
                    logger.debug(f"[DT-MIUL] Base matched {material_pn} -> {h_pn} (base: {base_material_pn})")
                    return hierarchy.nodes[h_pn]

            # Level 1: Exact match
            if material_pn in hierarchy.nodes:
                return hierarchy.nodes[material_pn]

            # Level 2: Material PN is prefix of hierarchy PN
            # e.g., GPE-010 matches GPE-010-1
            for h_pn in hierarchy_pns:
                if h_pn.startswith(material_pn + "-"):
                    logger.debug(f"[DT-MIUL] Prefix matched {material_pn} -> {h_pn}")
                    return hierarchy.nodes[h_pn]

            # Level 3: Hierarchy PN is prefix of material PN
            # e.g., MER07540-001 matches MER07540-001-A
            for h_pn in hierarchy_pns:
                if material_pn.startswith(h_pn + "-"):
                    logger.debug(f"[DT-MIUL] Suffix matched {material_pn} -> {h_pn}")
                    return hierarchy.nodes[h_pn]

            return None

        # Values to filter out (AR = As Required, not a material)
        invalid_designations = {"AR", "A/R", "REF", "-", "N/A", "TBD", ""}

        for pn, mat in materials.items():
            node = find_matching_node(pn)

            if node:
                designation = mat.get("designation", "") or ""

                # Filter invalid designations (AR = As Required qty marker, not a material)
                if designation.upper().strip() in invalid_designations:
                    logger.debug(f"[DT-MIUL] Filtered invalid designation '{designation}' for {pn}")
                    designation = ""

                # Sanitize designation from detail drawing
                if designation:
                    designation = self._sanitize_material_designation(
                        designation,
                        source="detail_drawing_merge",
                        context=f"(drawing={pn})"
                    )
                node.designation = designation
                node.material_spec = mat.get("material_spec", "")
                node.process_spec = mat.get("process_spec", "")
                node.form = mat.get("form", "")
                if any(v for v in mat.values()):
                    merged_count += 1
                    logger.debug(f"[DT-MIUL] Merged material for {node.part_number}")
            else:
                unmatched.append(pn)

        if unmatched:
            logger.warning(f"[DT-MIUL] Materials found but no hierarchy node for: {unmatched}")
        logger.info(f"[DT-MIUL] Merged materials: {merged_count} parts with material data")

    def _build_miul_rows(self, hierarchy: DTHierarchy) -> List[Dict[str, Any]]:
        """Build MAPTIS-compliant MIUL rows.

        Structure per MAPTIS spec:
        - Row 1: MIUL ID (Parent=0)
        - Row 2: MIUL ID (Parent=0, kicks off tree)
        - Row 3+: Data with proper Index/Parent/NHA
        - Last: EOF (Index=-1)

        Key: Parts and subparts are interleaved following the DT hierarchy.
        Each assembly is followed immediately by its subparts (EPL items),
        then by its children from the DT. This matches the DT structure.
        """
        rows = []

        # Row 1 & 2: MIUL Headers
        for i in [1, 2]:
            rows.append({
                "index": i,
                "parent": 0,
                "part_number": self.miul_number,
                "part_description": f"{self.miul_number} Material Identification Usage List",
                "nomenclature": f"{self.miul_number} MIUL",
                "nha": "",
                "material_type": "MIUL_ID",
                "project": self.project,
            })

        # Build rows via DFS traversal to maintain hierarchy order
        # Subparts are added immediately after their parent assembly
        current_index = 3  # Start after header rows

        # Track part_number -> actual row index (for parent references)
        pn_to_row_index: Dict[str, int] = {}

        def add_node_and_subparts(node: DTNode, parent_row_idx: int) -> None:
            """Add a node and its subparts, then recurse to children."""
            nonlocal current_index

            # NHA logic per MAPTIS spec
            if parent_row_idx == 2:  # Direct child of MIUL header
                nha = self.miul_number
            elif node.parent_pn:
                nha = node.parent_pn
            else:
                nha = ""

            my_row_index = current_index
            pn_to_row_index[node.part_number] = my_row_index

            # Add the node itself
            rows.append({
                "index": my_row_index,
                "parent": parent_row_idx,
                "part_number": node.part_number,
                "part_description": node.description,
                "nomenclature": node.description,
                "nha": nha,
                "designation": node.designation,
                "material_spec": node.material_spec,
                "process_spec": node.process_spec,
                "form": node.form,
                "material_code": node.material_code,
                "manufacturer": node.manufacturer,
                "source_drawing": node.part_number,
                "material_type": "ASSEMBLY" if node.is_assembly or node.children or node.subparts else "PART",
                "project": self.project,
            })
            current_index += 1

            # Add subparts (EPL items) immediately after the assembly
            for subpart in node.subparts:
                subpart_pn = self._clean_pn(subpart.get("part_number", ""))
                if not subpart_pn:
                    continue

                # Parse quantity
                qty_raw = subpart.get("qty", 1)
                try:
                    qty = int(qty_raw) if qty_raw not in ("AR", "A/R", "REF") else 0
                except (ValueError, TypeError):
                    qty = 1

                rows.append({
                    "index": current_index,
                    "parent": my_row_index,  # Parent = containing assembly
                    "part_number": subpart_pn,
                    "part_description": subpart.get("description", ""),
                    "nomenclature": subpart.get("description", ""),
                    "nha": node.part_number,  # NHA = containing assembly
                    "designation": subpart.get("material", ""),
                    "material_spec": "",
                    "process_spec": "",
                    "form": "",
                    "material_code": "",
                    "manufacturer": "",
                    "source_drawing": node.part_number,
                    "qty": qty,
                    "find_no": subpart.get("find_no", ""),
                    "material_type": "SUBPART",
                    "project": self.project,
                })
                current_index += 1

            # Recurse to children (DT hierarchy)
            for child in node.children:
                add_node_and_subparts(child, my_row_index)

        # Start traversal from root nodes
        for root_pn in hierarchy.root_nodes:
            if root_pn in hierarchy.nodes:
                add_node_and_subparts(hierarchy.nodes[root_pn], 2)  # Parent = row 2 (MIUL header)

        # Handle orphan nodes (not reachable from roots)
        for pn, node in hierarchy.nodes.items():
            if pn not in pn_to_row_index:
                add_node_and_subparts(node, 2)

        # EOF marker
        rows.append({
            "index": -1,
            "parent": None,
            "part_number": "",
            "part_description": "",
            "nha": "",
            "material_type": "EOF",
        })

        return rows

    def _write_excel(self, rows: List[Dict[str, Any]], output_path: Path) -> None:
        """Write MIUL to Excel with MAPTIS formatting."""
        wb = Workbook()
        ws = wb.active
        ws.title = "MIUL"

        # Write headers
        for col_idx, (header, _, width) in enumerate(MAPTIS_COLUMNS, start=1):
            cell = ws.cell(row=1, column=col_idx, value=header)
            cell.fill = self.HEADER_FILL
            cell.font = self.HEADER_FONT
            cell.border = self.THIN_BORDER
            cell.alignment = Alignment(horizontal="center", wrap_text=True)
            ws.column_dimensions[get_column_letter(col_idx)].width = width

        # Write data rows
        for row_idx, mat in enumerate(rows, start=2):
            is_miul_id = mat.get("material_type") == "MIUL_ID"
            is_eof = mat.get("material_type") == "EOF"
            is_assembly = mat.get("material_type") == "ASSEMBLY"
            is_subpart = mat.get("material_type") == "SUBPART"

            for col_idx, (header, key, _) in enumerate(MAPTIS_COLUMNS, start=1):
                if header == "Index":
                    value = mat.get("index", "")
                elif header == "Parent":
                    value = mat.get("parent", "")
                    if value is None:
                        value = ""
                elif header == "Project":
                    value = mat.get("project", self.project)
                elif key in mat:
                    value = mat[key]
                else:
                    value = ""

                cell = ws.cell(row=row_idx, column=col_idx, value=value)
                cell.border = self.THIN_BORDER

                # Row highlighting
                if is_miul_id:
                    cell.fill = self.MIUL_ID_FILL
                elif is_assembly:
                    cell.fill = self.ASSEMBLY_FILL
                elif is_subpart:
                    cell.fill = self.SUBPART_FILL

        # Freeze header row
        ws.freeze_panes = "A2"

        # Add summary sheet
        ws_summary = wb.create_sheet("Summary")
        self._write_summary(ws_summary, rows)

        wb.save(str(output_path))

    def _write_summary(self, ws, rows: List[Dict[str, Any]]) -> None:
        """Write summary statistics sheet."""
        ws.column_dimensions["A"].width = 35
        ws.column_dimensions["B"].width = 25

        data_rows = [r for r in rows if r.get("material_type") not in ("MIUL_ID", "EOF")]
        assemblies = sum(1 for r in data_rows if r.get("material_type") == "ASSEMBLY")
        subparts = sum(1 for r in data_rows if r.get("material_type") == "SUBPART")
        tree_parts = sum(1 for r in data_rows if r.get("material_type") == "PART")

        summary = [
            ("DT-First MIUL Summary", ""),
            ("", ""),
            ("MIUL Number", self.miul_number),
            ("Project", self.project),
            ("Generated", datetime.now().strftime("%Y-%m-%d %H:%M")),
            ("Architecture", "DT-First (Drawing Tree as SSOT)"),
            ("", ""),
            ("Statistics", ""),
            ("Total Data Rows", len(data_rows)),
            ("Assemblies (from DT)", assemblies),
            ("Detail Parts (from DT)", tree_parts),
            ("Subparts (from EPL)", subparts),
            ("", ""),
            ("Compliance", ""),
            ("Row 1-2: MIUL Headers", "Yes (Parent=0)"),
            ("EOF Row (Index=-1)", "Yes"),
            ("Hierarchy Source", "Drawing Tree Only"),
            ("EPL Extraction", "Yes" if subparts > 0 else "No"),
        ]

        for row_idx, (label, value) in enumerate(summary, start=1):
            ws.cell(row=row_idx, column=1, value=label)
            ws.cell(row=row_idx, column=2, value=value)
            if label in ("DT-First MIUL Summary", "Statistics", "Compliance"):
                ws.cell(row=row_idx, column=1).font = Font(bold=True)

    def _clean_pn(self, pn: str) -> str:
        """Clean part number - remove extensions and garbage."""
        if not pn:
            return ""
        cleaned = pn.strip()
        # Remove .DRW and everything after
        if ".DRW" in cleaned.upper():
            idx = cleaned.upper().find(".DRW")
            cleaned = cleaned[:idx]
        # Remove parenthetical descriptions
        if "(" in cleaned:
            cleaned = cleaned.split("(")[0].strip()
        return cleaned.strip().upper()

    def _extract_pn_from_filename(self, pdf_path: Path) -> str:
        """Extract part number from PDF filename.

        Handles common naming patterns:
        - MER07560-001.DRW_-.12_RELEASED.pdf -> MER07560-001
        - MER07560-001.pdf -> MER07560-001
        - GPE-010-1.DRW.pdf -> GPE-010-1

        Returns cleaned part number or empty string if extraction fails.
        """
        stem = pdf_path.stem  # filename without extension

        # Pattern 1: NAME.DRW_-... (most common MSFC format)
        if ".DRW" in stem.upper():
            idx = stem.upper().find(".DRW")
            pn = stem[:idx]
            return pn.strip().upper()

        # Pattern 2: NAME_REV_STATUS or NAME-REV
        # Try to extract before first underscore if it looks like metadata
        if "_" in stem:
            parts = stem.split("_")
            # First part is usually the part number
            pn = parts[0]
            return pn.strip().upper()

        # Pattern 3: Just the part number (simple case)
        return stem.strip().upper()


def build_miul_from_dt(
    dt_pdf_path: str,
    miul_number: str,
    drawing_dir: str = None,
    output_path: str = None,
    project: str = "",
) -> Path:
    """Convenience function to build MIUL from Drawing Tree.

    Args:
        dt_pdf_path: Path to -DT PDF file
        miul_number: MIUL identifier (e.g., "DMLLV")
        drawing_dir: Directory with detail drawings
        output_path: Output Excel path
        project: Project name

    Returns:
        Path to generated Excel
    """
    builder = DTMIULBuilder(miul_number=miul_number, project=project)
    return builder.build(
        dt_pdf_path=Path(dt_pdf_path),
        drawing_dir=Path(drawing_dir) if drawing_dir else None,
        output_path=Path(output_path) if output_path else None,
    )


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Build MIUL from Drawing Tree")
    parser.add_argument("dt_pdf", type=Path, help="Path to -DT PDF file")
    parser.add_argument("-n", "--miul-number", required=True, help="MIUL identifier")
    parser.add_argument("-d", "--drawing-dir", type=Path, help="Directory with detail drawings")
    parser.add_argument("-o", "--output", type=Path, help="Output Excel path")
    parser.add_argument("-p", "--project", default="", help="Project name")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    output = build_miul_from_dt(
        dt_pdf_path=args.dt_pdf,
        miul_number=args.miul_number,
        drawing_dir=args.drawing_dir,
        output_path=args.output,
        project=args.project,
    )
    print(f"Generated: {output}")
