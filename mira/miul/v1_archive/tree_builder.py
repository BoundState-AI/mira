#!/usr/bin/env python3
"""
Module: Tree Builder
Purpose: MIUL tree builder for converting flat BOMs to hierarchical structure.

BoundState AI 2025
Version: 1.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Fran OpenAI 5 <noreply@openai.com>
Co-Authored-By: Grok 4.0 <noreply@x.ai>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: SWE-013, SWE-033, JSC 27301F Section 4.2.1
Safety Critical: True
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

import PyPDF2
import re
from pydantic import BaseModel, Field

from mira.miul.schema import CriticalityCode, MIULRow, MIULTree, RatingCode
import uuid

__all__ = [
    "BOMInputFormat",
    "BOMRow",
    "TreeBuilder",
    "TreeBuildResult",
    "build_miul_tree",
    # Drawing Tree parsing (new)
    "DrawingTreeParser",
    "MIULTreeBuilder",
    "is_noise_part",
]

logger = logging.getLogger(__name__)

__safety_critical__ = True


class BOMInputFormat(str, Enum):
    """Supported BOM input formats for tree detection."""

    PARENT_REFERENCE = "parent_reference"  # Parent column has part number/drawing
    INDENTED = "indented"                  # Hierarchy from indentation/level column
    WBS_NUMBERED = "wbs_numbered"          # WBS-style: 1.1, 1.2, 1.2.1
    FLAT = "flat"                          # No hierarchy - all root level


class BOMRow(BaseModel):
    """Input BOM row before tree transformation.

    Accepts various column naming conventions and normalizes them.
    """

    model_config = {"extra": "allow", "populate_by_name": True}

    # Required
    part_number: str = Field(..., alias="PartNumber")

    # Optional - used for tree building
    parent_ref: Optional[str] = Field(None, alias="Parent")
    find_number: Optional[str] = Field(None, alias="Index")
    level: Optional[int] = Field(None, alias="Level")
    wbs: Optional[str] = Field(None, alias="WBS")

    # Pass-through fields
    part_description: str = Field("", alias="PartDescription")
    designation: Optional[str] = Field(None, alias="Designation")
    material_code: Optional[str] = Field(None, alias="MaterialCode")
    material_spec: Optional[str] = Field(None, alias="MaterialSpec")
    quantity: int = Field(1, alias="Quantity")
    cage_code: Optional[str] = Field(None, alias="CAGECode")
    drawing_source: Optional[str] = Field(None, alias="DrawingSource")
    drawing_rev: Optional[str] = Field(None, alias="DrawingRev")
    source_file: Optional[str] = Field(None, alias="SourceFile")
    manufacturer: Optional[str] = Field(None, alias="Manufacturer")

    # Criticality - user provided
    criticality: Optional[str] = Field(None, alias="Criticality")

    # Ratings - may be pre-populated
    flam_rating: Optional[str] = Field(None, alias="FLAM")
    scc_rating: Optional[str] = Field(None, alias="SCC")
    corr_rating: Optional[str] = Field(None, alias="CORR")
    tvs_rating: Optional[str] = Field(None, alias="TVS")
    tox_rating: Optional[str] = Field(None, alias="TOX")
    fs_rating: Optional[str] = Field(None, alias="FS")

    # MUA fields
    mua_number: Optional[str] = Field(None, alias="MUA")
    rationale_code: Optional[str] = Field(None, alias="RatCode")


@dataclass
class TreeNode:
    """Internal node for tree construction."""

    bom_row: BOMRow
    index: int = 0
    parent_index: int = 0
    children: List[TreeNode] = field(default_factory=list)
    nha: Optional[str] = None
    source: str = ""  # NASA SWE-013 traceability


    @property
    def part_number(self) -> str:
        return self.bom_row.part_number


@dataclass
class TreeBuildResult:
    """Result of tree building operation."""

    tree: MIULTree
    warnings: List[str] = field(default_factory=list)
    orphan_count: int = 0
    root_count: int = 0
    detected_format: BOMInputFormat = BOMInputFormat.FLAT
    source: str = ""  # NASA SWE-013 traceability



class TreeBuilder:
    """Builds MIUL tree structure from various BOM formats.

    Compliance: SWE-013, SWE-033
    """

    def __init__(self, source: str = "tree_builder"):
        self.source = source
        self._warnings: List[str] = []

    def build(self, rows: List[BOMRow]) -> TreeBuildResult:
        """Build MIUL tree from BOM rows.

        Auto-detects input format and applies appropriate parsing strategy.
        """
        if not rows:
            return TreeBuildResult(
                tree=MIULTree(rows=[self._create_eof_row()]),
                warnings=["Empty BOM provided"],
                detected_format=BOMInputFormat.FLAT,
            )

        self._warnings = []
        detected_format = self._detect_format(rows)
        logger.info("[TreeBuilder] Detected BOM format: %s", detected_format.value)

        if detected_format == BOMInputFormat.PARENT_REFERENCE:
            nodes = self._build_from_parent_reference(rows)
        elif detected_format == BOMInputFormat.WBS_NUMBERED:
            nodes = self._build_from_wbs(rows)
        elif detected_format == BOMInputFormat.INDENTED:
            nodes = self._build_from_indentation(rows)
        else:
            nodes = self._build_flat(rows)

        # Assign sequential indices
        self._assign_indices(nodes)

        # Convert to MIULRow objects
        miul_rows = self._nodes_to_miul_rows(nodes)
        miul_rows.append(self._create_eof_row())

        # Count statistics
        root_count = sum(1 for n in nodes if n.parent_index == 0)
        orphan_count = sum(1 for w in self._warnings if "orphan" in w.lower())

        return TreeBuildResult(
            tree=MIULTree(rows=miul_rows),
            warnings=self._warnings,
            orphan_count=orphan_count,
            root_count=root_count,
            detected_format=detected_format,
        )

    def _detect_format(self, rows: List[BOMRow]) -> BOMInputFormat:
        """Auto-detect BOM format from data patterns."""
        # Check for WBS numbering (e.g., "1.1", "1.2.3")
        wbs_pattern = re.compile(r"^\d+(\.\d+)*$")
        wbs_count = sum(1 for r in rows if r.wbs and wbs_pattern.match(r.wbs))
        if wbs_count > len(rows) * 0.8:
            return BOMInputFormat.WBS_NUMBERED

        # Check for level/indentation column
        level_count = sum(1 for r in rows if r.level is not None)
        if level_count > len(rows) * 0.8:
            return BOMInputFormat.INDENTED

        # Check for parent references (part numbers or drawing names)
        parent_count = sum(1 for r in rows if r.parent_ref and r.parent_ref.strip())
        if parent_count > len(rows) * 0.3:
            return BOMInputFormat.PARENT_REFERENCE

        return BOMInputFormat.FLAT

    def _build_from_parent_reference(self, rows: List[BOMRow]) -> List[TreeNode]:
        """Build tree using parent column references.

        Parent column may contain:
        - Part number of parent assembly
        - Drawing number of parent
        - Empty/None for root items
        """
        nodes = [TreeNode(bom_row=r) for r in rows]

        # Build lookup maps
        by_part_number: Dict[str, TreeNode] = {}
        by_drawing: Dict[str, TreeNode] = {}

        for node in nodes:
            pn = node.part_number.strip().upper()
            by_part_number[pn] = node
            if node.bom_row.drawing_source:
                dwg = node.bom_row.drawing_source.strip().upper()
                by_drawing[dwg] = node

        # Resolve parent references
        for node in nodes:
            parent_ref = node.bom_row.parent_ref
            if not parent_ref or not parent_ref.strip():
                continue  # Root item

            ref = parent_ref.strip().upper()

            # Try to find parent by part number first
            parent = by_part_number.get(ref)
            if parent is None:
                # Try by drawing number
                parent = by_drawing.get(ref)

            if parent is not None and parent is not node:
                parent.children.append(node)
                node.nha = parent.part_number
            else:
                self._warnings.append(
                    f"Orphan: '{node.part_number}' references unknown parent '{parent_ref}'"
                )

        # Return all nodes - orphans become roots
        return nodes

    def _build_from_wbs(self, rows: List[BOMRow]) -> List[TreeNode]:
        """Build tree from WBS-style numbering (1.1, 1.2, 1.2.1)."""
        nodes = [TreeNode(bom_row=r) for r in rows]

        # Map WBS to node
        wbs_map: Dict[str, TreeNode] = {}
        for node in nodes:
            if node.bom_row.wbs:
                wbs_map[node.bom_row.wbs] = node

        for node in nodes:
            wbs = node.bom_row.wbs
            if not wbs:
                continue

            # Find parent WBS (e.g., "1.2.3" -> "1.2")
            parts = wbs.split(".")
            if len(parts) > 1:
                parent_wbs = ".".join(parts[:-1])
                parent = wbs_map.get(parent_wbs)
                if parent:
                    parent.children.append(node)
                    node.nha = parent.part_number
                else:
                    self._warnings.append(
                        f"WBS '{wbs}' references missing parent WBS '{parent_wbs}'"
                    )

        return nodes

    def _build_from_indentation(self, rows: List[BOMRow]) -> List[TreeNode]:
        """Build tree from level/indentation column."""
        nodes = [TreeNode(bom_row=r) for r in rows]

        # Stack tracks parent at each level
        parent_stack: List[TreeNode] = []

        for node in nodes:
            level = node.bom_row.level or 0

            # Pop stack to find parent at level-1
            while len(parent_stack) > level:
                parent_stack.pop()

            if parent_stack:
                parent = parent_stack[-1]
                parent.children.append(node)
                node.nha = parent.part_number

            # Push current node for potential children
            if len(parent_stack) <= level:
                parent_stack.append(node)
            else:
                parent_stack[level] = node

        return nodes

    def _build_flat(self, rows: List[BOMRow]) -> List[TreeNode]:
        """Build flat structure - all items at root level."""
        self._warnings.append(
            "No hierarchy detected - all items placed at root level"
        )
        return [TreeNode(bom_row=r) for r in rows]

    def _assign_indices(self, nodes: List[TreeNode]) -> None:
        """Assign sequential indices via depth-first traversal."""
        # Find root nodes (no parent assigned yet)
        roots = [n for n in nodes if n.nha is None]

        # Build parent lookup for non-roots
        children_of: Dict[str, List[TreeNode]] = {}
        for node in nodes:
            if node.nha:
                children_of.setdefault(node.nha, []).append(node)

        index = 1

        def traverse(node: TreeNode, parent_idx: int) -> None:
            nonlocal index
            node.index = index
            node.parent_index = parent_idx
            index += 1

            # Process children
            for child in children_of.get(node.part_number, []):
                traverse(child, node.index)

        for root in roots:
            traverse(root, 0)

        # Handle any orphans not reached by traversal
        for node in nodes:
            if node.index == 0:
                node.index = index
                node.parent_index = 0
                index += 1
                self._warnings.append(
                    f"Unreachable node assigned as root: {node.part_number}"
                )

    def _nodes_to_miul_rows(self, nodes: List[TreeNode]) -> List[MIULRow]:
        """Convert TreeNodes to MIULRow objects."""
        miul_rows = []

        for node in sorted(nodes, key=lambda n: n.index):
            bom = node.bom_row

            # Parse criticality if provided
            crit = None
            if bom.criticality:
                try:
                    crit = CriticalityCode(bom.criticality.upper().strip())
                except ValueError:
                    self._warnings.append(
                        f"Invalid criticality '{bom.criticality}' for {bom.part_number}"
                    )

            # Parse ratings
            def parse_rating(val: Optional[str]) -> Optional[RatingCode]:
                if not val or not val.strip():
                    return None
                try:
                    return RatingCode(val.strip().upper())
                except ValueError:
                    return None

            row = MIULRow(
                index=node.index,
                parent=node.parent_index,
                part_number=bom.part_number,
                part_description=bom.part_description,
                nha=node.nha,
                criticality=crit,
                drawing_source=bom.drawing_source,
                drawing_rev=bom.drawing_rev,
                source_file=bom.source_file,
                material_code=bom.material_code,
                designation=bom.designation,
                material_spec=bom.material_spec,
                manufacturer=bom.manufacturer,
                cage_code=bom.cage_code,
                quantity=bom.quantity,
                flam_rating=parse_rating(bom.flam_rating),
                scc_rating=parse_rating(bom.scc_rating),
                corr_rating=parse_rating(bom.corr_rating),
                tvs_rating=parse_rating(bom.tvs_rating),
                tox_rating=parse_rating(bom.tox_rating),
                fs_rating=parse_rating(bom.fs_rating),
                mua_number=bom.mua_number,
                rationale_code=bom.rationale_code,
                source=self.source,
            )
            miul_rows.append(row)

        return miul_rows

    def _create_eof_row(self) -> MIULRow:
        """Create EOF marker row per MIUL spec."""
        return MIULRow(
            index=-1,
            parent=0,
            part_number="EOF",
            source=self.source,
        )


def build_miul_tree(
    rows: List[dict],
    source: str = "api",
    format_hint: Optional[BOMInputFormat] = None,
) -> TreeBuildResult:
    """Convenience function to build MIUL tree from dict rows.

    Args:
        rows: List of row dictionaries from Excel/CSV
        source: Provenance string for audit trail
        format_hint: Optional format override (skips auto-detection)

    Returns:
        TreeBuildResult with validated MIUL tree
    """
    # Normalize column names (handle various conventions)
    normalized = []
    for row in rows:
        norm = {}
        for k, v in row.items():
            # Normalize key
            key = k.strip().replace(" ", "").replace("_", "")
            norm[key] = v
        normalized.append(norm)

    # Parse into BOMRow objects
    bom_rows = []
    for i, row in enumerate(normalized):
        try:
            # Map common column name variations
            mapped = _map_column_names(row)
            bom_rows.append(BOMRow.model_validate(mapped))
        except Exception as e:
            logger.warning("[TreeBuilder] Row %d parse error: %s", i + 1, e)

    builder = TreeBuilder(source=source)
    return builder.build(bom_rows)


def _map_column_names(row: dict) -> dict:
    """Map common column name variations to canonical names."""
    mappings = {
        # Part number variations
        "partnumber": "PartNumber",
        "partno": "PartNumber",
        "pn": "PartNumber",
        "itemnumber": "PartNumber",
        "itemno": "PartNumber",
        # Description
        "description": "PartDescription",
        "partdescription": "PartDescription",
        "desc": "PartDescription",
        "nomenclature": "PartDescription",
        # Parent
        "parent": "Parent",
        "parentassembly": "Parent",
        "parentpn": "Parent",
        "nha": "Parent",
        # Level/indent
        "level": "Level",
        "indent": "Level",
        "indentlevel": "Level",
        "bomlevel": "Level",
        # WBS
        "wbs": "WBS",
        "wbsnumber": "WBS",
        "findnumber": "Index",
        "findno": "Index",
        "index": "Index",
        # Material
        "materialcode": "MaterialCode",
        "matcode": "MaterialCode",
        "matlcode": "MaterialCode",
        "material": "Designation",
        "materialname": "Designation",
        "designation": "Designation",
        "materialspec": "MaterialSpec",
        "spec": "MaterialSpec",
        "specification": "MaterialSpec",
        # Other
        "quantity": "Quantity",
        "qty": "Quantity",
        "cagecode": "CAGECode",
        "cage": "CAGECode",
        "manufacturer": "Manufacturer",
        "mfr": "Manufacturer",
        "drawingsource": "DrawingSource",
        "drawing": "DrawingSource",
        "dwg": "DrawingSource",
        "sourcefile": "SourceFile",
        # Criticality
        "criticality": "Criticality",
        "crit": "Criticality",
        "critcode": "Criticality",
        # Ratings
        "flam": "FLAM",
        "flamm": "FLAM",
        "flammrating": "FLAM",
        "scc": "SCC",
        "sccrating": "SCC",
        "corr": "CORR",
        "corrrating": "CORR",
        "tvs": "TVS",
        "tvsrating": "TVS",
        "tox": "TOX",
        "toxrating": "TOX",
        "fs": "FS",
        "fsrating": "FS",
        # MUA
        "mua": "MUA",
        "muanumber": "MUA",
        "ratcode": "RatCode",
        "rationalecode": "RatCode",
    }

    result = {}
    for k, v in row.items():
        normalized_key = k.lower().replace(" ", "").replace("_", "").replace("-", "")
        canonical = mappings.get(normalized_key, k)
        result[canonical] = v

    return result


# =============================================================================
# Drawing Tree (-DT) PDF Parsing
# =============================================================================


class DrawingTreeParser:
    """Parse -DT (Drawing Tree) PDF files to extract assembly hierarchy.

    Drawing Tree files show the complete assembly structure visually.
    This parser extracts all drawing numbers and their descriptions.

    Compliance: JSC 27301F Section 4.2.1, SWE-033 (Traceability)
    """

    def extract_text_from_pdf(self, pdf_path: Path) -> str:
        """Extract text from PDF file.

        Args:
            pdf_path: Path to PDF file

        Returns:
            Extracted text content
        """
        with open(pdf_path, 'rb') as f:
            reader = PyPDF2.PdfReader(f)
            text = ""
            for page in reader.pages:
                page_text = page.extract_text()
                if page_text:
                    text += page_text + "\n"
        return text

    def parse(self, pdf_path: Path) -> Dict[str, Any]:
        """Parse Drawing Tree PDF to extract parts and hierarchy.

        The DT file shows the complete assembly structure visually.
        We extract all drawing numbers and their descriptions.

        Args:
            pdf_path: Path to -DT PDF file

        Returns:
            Dictionary with:
            - parts: List of {part_number, description, source_file}
            - root: Top-level assembly number
            - source_file: DT filename
        """
        text = self.extract_text_from_pdf(pdf_path)

        # Extract root assembly from title block
        # The -001 or -1 version is typically first, or matches the -DT name
        dt_name = pdf_path.stem.upper()
        # Remove -DT, -DOC, Drawing Tree, etc. suffixes
        base_name = re.sub(r'[-_]?(DT|DOC).*', '', dt_name, flags=re.IGNORECASE)
        base_name = re.sub(r'\s*\(.*\)', '', base_name).strip()

        # Try to find the TOP assembly (typically XXX-A000-1 or XXX-001 pattern)
        # Look for patterns like "GPE-A000-1" followed by "ASSEMBLY" or at document top
        prefix = base_name.split("-")[0] if "-" in base_name else base_name

        # First try: Look for -A000- pattern (common for top assembly)
        top_assembly_match = re.search(
            rf'({re.escape(prefix)}[-]?A000[-]?\d{{0,3}})',
            text, re.IGNORECASE
        )
        if top_assembly_match:
            root_assembly = top_assembly_match.group(1).upper()
        else:
            # Second try: Look for -001 pattern with "ASSEMBLY" keyword
            assembly_match = re.search(
                rf'({re.escape(prefix)}[-]?\d{{3,5}}[-]?001)\s*\n?\s*(?:.*?ASSEMBLY|ASSY)',
                text, re.IGNORECASE
            )
            if assembly_match:
                root_assembly = assembly_match.group(1).upper()
            elif '-' in base_name:
                # Fallback: use base project prefix with -A000-1
                root_assembly = f"{prefix}-A000-1"
            else:
                root_assembly = f"{base_name}-001"

        # Find all drawing numbers with descriptions
        parts: List[Dict[str, Any]] = []
        seen: set = set()

        # Two-pass approach for reliability:
        # 1. Find ALL part number positions
        # 2. Extract description between each part number and the next

        # Auto-detect part number pattern from DT filename
        # Supports: MER07540-001, GPE-010-1, ABC-A100-2, etc.
        prefix = re.sub(r'-DT.*|[-_]DOC.*', '', dt_name, flags=re.IGNORECASE)
        prefix_match = re.match(r'^([A-Z]{2,6})', prefix)
        detected_prefix = prefix_match.group(1) if prefix_match else None

        if detected_prefix:
            # Match detected prefix with flexible number/letter patterns
            # e.g., GPE-010-1, GPE-A100-1, MER07540-001
            part_pattern = re.compile(
                rf'({re.escape(detected_prefix)}[-]?[A-Z]?\d{{2,5}}[-]?\d{{0,3}})',
                re.IGNORECASE
            )
            logger.info(f"[DT Parser] Auto-detected prefix '{detected_prefix}' from {dt_name}")
        else:
            # Fallback to generic aerospace part number pattern
            part_pattern = re.compile(r'([A-Z]{2,6}[-]?[A-Z]?\d{2,5}[-]?\d{0,3})', re.IGNORECASE)
        matches = list(part_pattern.finditer(text))

        for i, match in enumerate(matches):
            part_number = match.group(1).upper()

            # Skip the DT drawing itself
            if '-DT' in part_number:
                continue

            # Skip duplicates
            if part_number in seen:
                continue
            seen.add(part_number)

            # Extract description: text after this part number until next part number
            start_pos = match.end()
            if i + 1 < len(matches):
                end_pos = matches[i + 1].start()
            else:
                # Last part - go until PRELIMINARY or end
                prelim_match = re.search(r'\s*PRELIMINARY', text[start_pos:], re.IGNORECASE)
                end_pos = start_pos + prelim_match.start() if prelim_match else len(text)

            desc_raw = text[start_pos:end_pos].strip()

            # Clean description - take first few meaningful lines
            desc_lines = [ln.strip() for ln in desc_raw.split('\n') if ln.strip()]
            # Filter out noise lines (numbers, single chars, etc.)
            desc_lines = [ln for ln in desc_lines if len(ln) > 2 and not re.match(r'^[\d\s\.]+$', ln)]
            description = ', '.join(desc_lines[:3])
            description = re.sub(r',\s*,', ',', description)
            description = re.sub(r',\s*$', '', description).strip()

            parts.append({
                'part_number': part_number,
                'description': description,
                'source_file': pdf_path.name,
            })

        logger.info(
            "[DT Parser] Found %d parts from %s, root=%s",
            len(parts), pdf_path.name, root_assembly
        )

        return {
            'parts': parts,
            'root': root_assembly,
            'source_file': pdf_path.name,
        }


class MIULTreeBuilder:
    """Build MIUL tree structure from Drawing Tree + detail drawings.

    Orchestrates:
    1. Finding and parsing -DT files
    2. Building Index/Parent tree using NHA relationships
    3. Merging material data from detail drawings

    Compliance: JSC 27301F Section 4.2.1, SWE-033 (Traceability)
    """

    def __init__(self):
        """Initialize tree builder with DT parser."""
        self._dt_parser = DrawingTreeParser()

    def find_drawing_tree(self, directory: Path) -> Optional[Path]:
        """Find -DT file in directory.

        Args:
            directory: Path to search

        Returns:
            Path to -DT file or None
        """
        dt_files = list(directory.glob("*-DT*.pdf")) + list(directory.glob("*-dt*.pdf"))
        if dt_files:
            logger.info("[MIULTreeBuilder] Found Drawing Tree: %s", dt_files[0].name)
            return dt_files[0]
        return None

    def parse_drawing_tree(self, dt_path: Path) -> Dict[str, Any]:
        """Parse Drawing Tree file.

        Args:
            dt_path: Path to -DT PDF

        Returns:
            Parsed tree data with parts list
        """
        return self._dt_parser.parse(dt_path)

    def build_tree(
        self,
        parts: List[Dict[str, Any]],
        nha_map: Optional[Dict[str, str]] = None,
    ) -> List[Dict[str, Any]]:
        """Build Index/Parent tree structure using NHA relationships.

        Args:
            parts: List of parts with 'part_number'
            nha_map: Optional mapping of part_number -> next_assembly

        Returns:
            Parts with Index and Parent populated

        Compliance: SWE-033 (Traceability via Index/Parent)
        """
        nha_map = nha_map or {}

        # First pass: assign indices and build lookup
        part_to_index: Dict[str, int] = {}
        root_index = 1  # Default root is first part (index 1)
        for i, part in enumerate(parts, 1):
            part['Index'] = i
            pn = str(part.get('part_number', '')).strip().upper()
            if pn:
                part_to_index[pn] = i

        # Detect part number pattern from the parts in this BOM
        # Most aerospace part numbers follow patterns like: MER07540-001, 123-45678, etc.
        part_number_patterns = set()
        for pn in part_to_index.keys():
            # Extract prefix pattern (letters before first digit)
            prefix_match = re.match(r'^([A-Z]+)', pn)
            if prefix_match:
                part_number_patterns.add(prefix_match.group(1))

        # Generic project-level keywords that are never part numbers
        PROJECT_KEYWORDS = {'FINAL', 'PROJECT', 'PROGRAM', 'TBD', 'N/A', 'NONE', 'ASSEMBLY'}

        def is_project_nha(nha: str) -> bool:
            """Check if NHA is a project-level reference, not a part number.

            Works generically by:
            1. Checking for common project keywords
            2. Checking if NHA matches the part number pattern in this BOM
            """
            if not nha:
                return False
            nha_upper = nha.upper()

            # Check for project keywords
            for keyword in PROJECT_KEYWORDS:
                if keyword in nha_upper:
                    return True

            # If NHA doesn't look like a part number at all (no digits or no dash)
            if not re.search(r'\d', nha) or '-' not in nha:
                return True

            # If we know what part numbers look like, check if NHA matches
            if part_number_patterns:
                nha_prefix = re.match(r'^([A-Z]+)', nha_upper)
                if nha_prefix and nha_prefix.group(1) not in part_number_patterns:
                    # NHA has a different prefix than any part in this BOM
                    # Could be a project code or different assembly family
                    return True

            return False

        # Second pass: resolve Parent from Next Assembly
        for part in parts:
            pn = str(part.get('part_number', '')).strip().upper()
            # Check nha_map first, then fall back to part's own next_assembly
            nha = nha_map.get(pn, str(part.get('next_assembly', '') or '')).strip().upper()

            if nha and nha in part_to_index:
                part['Parent'] = part_to_index[nha]
                part['Next Assembly'] = nha
            elif nha and is_project_nha(nha) and part['Index'] != root_index:
                # Project-level NHA (like "DMLLV FINAL") means this is a child of root
                part['Parent'] = root_index
                part['Next Assembly'] = nha
                logger.debug(f"  {pn}: project NHA '{nha}' -> parent={root_index}")
            else:
                part['Parent'] = 0
                if nha:
                    part['Next Assembly'] = nha  # Keep even if not in tree

        logger.debug(
            "[MIULTreeBuilder] Built tree with %d parts, %d with parents",
            len(parts), sum(1 for p in parts if p.get('Parent', 0) > 0)
        )

        return parts

    def merge_material_data(
        self,
        dt_parts: List[Dict[str, Any]],
        material_data: Dict[str, Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """Merge material data from detail drawings into DT parts list.

        Args:
            dt_parts: Parts from Drawing Tree
            material_data: Dict mapping part_number -> material fields

        Returns:
            Merged parts list with material data populated
        """
        merged_count = 0
        for part in dt_parts:
            pn = str(part.get('part_number', '')).strip().upper()
            if pn in material_data:
                mat = material_data[pn]
                part['designation'] = mat.get('designation', '')
                part['material_spec'] = mat.get('material_spec', '')
                part['material_form'] = mat.get('material_form', '')
                part['process_spec'] = mat.get('process_spec', '')
                merged_count += 1

        logger.info(
            "[MIULTreeBuilder] Merged material data for %d/%d parts",
            merged_count, len(dt_parts)
        )

        return dt_parts


def is_noise_part(part: Dict[str, Any]) -> bool:
    """Check if part should be filtered out.

    Filters:
    - Lubricants (AR qty with lubricant/grease/oil description)
    - Note references (NOTE-5, etc.)
    - Empty part numbers

    Args:
        part: Part dictionary

    Returns:
        True if part should be excluded

    Compliance: SWE-032 (Data validation)
    """
    pn = str(part.get('part_number', '')).strip().upper()
    qty = str(part.get('qty', '')).strip().upper()
    desc = str(part.get('description', '')).upper()

    # Skip note references
    if pn.startswith('NOTE') or re.match(r'^NOTE-?\d+$', pn):
        return True

    # Skip lubricants (AR qty with lubricant description)
    if qty == 'AR' and ('LUBRICANT' in desc or 'GREASE' in desc or 'OIL' in desc):
        return True

    # Skip empty
    if not pn:
        return True

    return False
