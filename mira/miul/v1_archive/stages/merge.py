#!/usr/bin/env python3
"""
Module: Merge
Purpose: Stage 4 - Merge (DFS + Interleave)

BoundState AI 2025
Version: 1.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Fran OpenAI 5 <noreply@openai.com>
Co-Authored-By: Grok 4.0 <noreply@x.ai>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: SWE-013, SWE-033, NASA-STD-6016C, MAPTIS Import Spec
Safety Critical: True
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from .parse_dt import DTHierarchy, DTNode
from .parse_drawings import DrawingData, EPLItem

logger = logging.getLogger(__name__)

__all__ = ["merge_to_miul", "MIULDocument", "MIULRow"]
__safety_critical__ = True


@dataclass
class MIULRow:
    """Single row in MIUL output.

    Per MAPTIS spec, each row has Index, Parent, and conditionally NHA.
    """
    index: int
    parent: int
    part_number: str
    part_description: str = ""
    nomenclature: str = ""
    nha: str = ""  # Next Higher Assembly (blank for subparts)

    # Material data
    designation: str = ""
    material_spec: str = ""
    process_spec: str = ""
    form: str = ""
    material_code: str = ""
    manufacturer: str = ""

    # Source traceability
    source_drawing: str = ""
    find_no: str = ""
    qty: int = 1

    # Classification
    row_type: str = ""  # MIUL_ID, ASSEMBLY, PART, SUBPART, EOF

    def to_dict(self) -> Dict[str, Any]:
        return {
            "index": self.index,
            "parent": self.parent,
            "part_number": self.part_number,
            "part_description": self.part_description,
            "nomenclature": self.nomenclature,
            "nha": self.nha,
            "designation": self.designation,
            "material_spec": self.material_spec,
            "process_spec": self.process_spec,
            "form": self.form,
            "material_code": self.material_code,
            "manufacturer": self.manufacturer,
            "source_drawing": self.source_drawing,
            "find_no": self.find_no,
            "qty": self.qty,
            "row_type": self.row_type,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> MIULRow:
        return cls(
            index=data["index"],
            parent=data["parent"],
            part_number=data["part_number"],
            part_description=data.get("part_description", ""),
            nomenclature=data.get("nomenclature", ""),
            nha=data.get("nha", ""),
            designation=data.get("designation", ""),
            material_spec=data.get("material_spec", ""),
            process_spec=data.get("process_spec", ""),
            form=data.get("form", ""),
            material_code=data.get("material_code", ""),
            manufacturer=data.get("manufacturer", ""),
            source_drawing=data.get("source_drawing", ""),
            find_no=data.get("find_no", ""),
            qty=data.get("qty", 1),
            row_type=data.get("row_type", ""),
        )


@dataclass
class MIULDocument:
    """Complete MIUL document ready for export.

    Contains all rows in proper order with statistics.
    """
    miul_number: str
    project: str
    rows: List[MIULRow] = field(default_factory=list)

    # Statistics
    assembly_count: int = 0
    part_count: int = 0
    subpart_count: int = 0

    # Metadata for traceability (SWE-033)
    generated_at: str = ""
    hierarchy_source: str = ""
    extractor_version: str = "1.0.0"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "miul_number": self.miul_number,
            "project": self.project,
            "rows": [row.to_dict() for row in self.rows],
            "statistics": {
                "total_rows": len(self.rows),
                "assemblies": self.assembly_count,
                "parts": self.part_count,
                "subparts": self.subpart_count,
            },
            "metadata": {
                "generated_at": self.generated_at,
                "hierarchy_source": self.hierarchy_source,
                "extractor_version": self.extractor_version,
                "stage": "merge",
            }
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> MIULDocument:
        stats = data.get("statistics", {})
        metadata = data.get("metadata", {})
        doc = cls(
            miul_number=data["miul_number"],
            project=data["project"],
            assembly_count=stats.get("assemblies", 0),
            part_count=stats.get("parts", 0),
            subpart_count=stats.get("subparts", 0),
            generated_at=metadata.get("generated_at", ""),
            hierarchy_source=metadata.get("hierarchy_source", ""),
            extractor_version=metadata.get("extractor_version", "1.0.0"),
        )
        for row_data in data.get("rows", []):
            doc.rows.append(MIULRow.from_dict(row_data))
        return doc

    def save(self, path: Path) -> None:
        """Save MIUL document to JSON file."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=2)
        logger.info(f"[Stage 4] Saved MIUL to {path}")

    @classmethod
    def load(cls, path: Path) -> MIULDocument:
        """Load MIUL document from JSON file."""
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return cls.from_dict(data)


def merge_to_miul(
    hierarchy: DTHierarchy,
    drawings: Dict[str, DrawingData],
    project: str = "",
    output_path: Optional[Path] = None,
) -> MIULDocument:
    """Merge DT hierarchy + drawing data into MIUL structure.

    Stage 4 of the MIUL pipeline. Uses DFS traversal to ensure
    parents are indexed before children.

    Args:
        hierarchy: DTHierarchy from Stage 1
        drawings: Dict of DrawingData from Stages 2-3
        project: Project name for MIUL
        output_path: Where to save miul.json

    Returns:
        MIULDocument with all rows in proper order

    Key algorithm:
    1. Add MIUL header rows (Index 1, 2 with Parent=0)
    2. DFS traverse DT hierarchy starting from roots
    3. For each node: assign Index, set Parent to parent's Index
    4. After each assembly: interleave its EPL subparts
    5. Add EOF marker (Index=-1)

    NHA Logic (per MAPTIS spec):
    - Row 1-2 (headers): NHA = blank
    - Top-level assembly (Parent=2): NHA = MIUL Number
    - Sub-assemblies: NHA = parent part number
    - Subparts (EPL items): NHA = blank
    """
    miul_number = hierarchy.miul_number
    if not project:
        project = miul_number

    doc = MIULDocument(
        miul_number=miul_number,
        project=project,
        generated_at=datetime.now().isoformat(),
        hierarchy_source=hierarchy.source_file,
    )

    # === Row 1 & 2: MIUL Headers (Parent=0) ===
    for i in [1, 2]:
        doc.rows.append(MIULRow(
            index=i,
            parent=0,
            part_number=miul_number,
            part_description=f"{miul_number} Material Identification Usage List",
            nomenclature=f"{miul_number} MIUL",
            nha="",
            row_type="MIUL_ID",
        ))

    # === DFS Traversal with EPL Interleaving ===
    # Build children map from hierarchy
    children_of: Dict[str, List[str]] = {}
    for pn, node in hierarchy.nodes.items():
        if node.parent_pn:
            children_of.setdefault(node.parent_pn, []).append(pn)

    # Track index assignment (start at 3, after headers)
    current_index = 3
    pn_to_index: Dict[str, int] = {}  # Map PN -> assigned row index

    def traverse(pn: str, parent_row_index: int) -> None:
        """DFS traverse node, then its EPL, then its children."""
        nonlocal current_index

        if pn not in hierarchy.nodes:
            return

        node = hierarchy.nodes[pn]
        drawing = drawings.get(pn)

        # Determine NHA per MAPTIS spec
        if parent_row_index == 2:
            # Top-level (parent is header row 2): NHA = MIUL Number
            nha = miul_number
        elif node.parent_pn:
            # Sub-assembly/part: NHA = parent part number
            nha = node.parent_pn
        else:
            nha = ""

        # Create row for this node
        row = MIULRow(
            index=current_index,
            parent=parent_row_index,
            part_number=pn,
            part_description=node.description or (drawing.title if drawing else ""),
            nomenclature=node.description or (drawing.title if drawing else ""),
            nha=nha,
            source_drawing=pn,
            row_type="ASSEMBLY" if node.is_assembly else "PART",
        )

        # Merge material data from drawing if available
        if drawing:
            row.designation = drawing.designation
            row.material_spec = drawing.material_spec
            row.process_spec = drawing.process_spec
            row.form = drawing.form

        doc.rows.append(row)
        pn_to_index[pn] = current_index
        my_index = current_index
        current_index += 1

        # Count
        if node.is_assembly:
            doc.assembly_count += 1
        else:
            doc.part_count += 1

        # === Interleave EPL subparts AFTER this assembly ===
        if drawing and drawing.epl:
            for epl_item in drawing.epl:
                subpart_pn = epl_item.part_number
                if not subpart_pn:
                    continue

                # Subparts have: Parent = containing assembly, NHA = blank
                subpart_row = MIULRow(
                    index=current_index,
                    parent=my_index,  # Parent = assembly's index
                    part_number=subpart_pn,
                    part_description=epl_item.description,
                    nomenclature=epl_item.description,
                    nha="",  # Subparts have blank NHA per MAPTIS spec
                    designation=epl_item.material,
                    source_drawing=pn,  # Source = containing assembly
                    find_no=epl_item.find_no,
                    qty=epl_item.qty,
                    row_type="SUBPART",
                )
                doc.rows.append(subpart_row)
                current_index += 1
                doc.subpart_count += 1

        # === Recurse to children ===
        for child_pn in children_of.get(pn, []):
            traverse(child_pn, my_index)

    # Start DFS from root nodes
    for root_pn in hierarchy.root_nodes:
        traverse(root_pn, 2)  # Parent = row 2 (MIUL header)

    # Handle orphans (nodes not reached via DFS)
    for pn in hierarchy.nodes:
        if pn not in pn_to_index:
            logger.warning(f"[Stage 4] Orphan node not in tree: {pn}")
            node = hierarchy.nodes[pn]
            drawing = drawings.get(pn)

            row = MIULRow(
                index=current_index,
                parent=2,  # Orphan goes under header
                part_number=pn,
                part_description=node.description or (drawing.title if drawing else ""),
                nomenclature=node.description or (drawing.title if drawing else ""),
                nha=miul_number,  # Treat as top-level
                source_drawing=pn,
                row_type="ASSEMBLY" if node.is_assembly else "PART",
            )

            if drawing:
                row.designation = drawing.designation
                row.material_spec = drawing.material_spec
                row.process_spec = drawing.process_spec
                row.form = drawing.form

            doc.rows.append(row)
            pn_to_index[pn] = current_index
            current_index += 1

            if node.is_assembly:
                doc.assembly_count += 1
            else:
                doc.part_count += 1

    # === EOF Marker ===
    doc.rows.append(MIULRow(
        index=-1,
        parent=0,
        part_number="",
        part_description="",
        nha="",
        row_type="EOF",
    ))

    logger.info(f"[Stage 4] Merged MIUL: {doc.assembly_count} assemblies, "
                f"{doc.part_count} parts, {doc.subpart_count} subparts")

    # Save if output path provided
    if output_path:
        doc.save(output_path)

    return doc
