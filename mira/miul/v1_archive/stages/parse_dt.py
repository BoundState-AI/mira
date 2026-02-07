#!/usr/bin/env python3
"""
Module: Parse Dt
Purpose: Stage 1 - Drawing Tree Parser

BoundState AI 2025
Version: 1.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Fran OpenAI 5 <noreply@openai.com>
Co-Authored-By: Grok 4.0 <noreply@x.ai>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: SWE-013, SWE-033, JSC-27301F Section 4.2.1
Safety Critical: True
"""

from __future__ import annotations

import base64
import json
import logging
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

__all__ = ["parse_drawing_tree", "DTHierarchy", "DTNode"]
__safety_critical__ = True


@dataclass
class DTNode:
    """Node in the Drawing Tree hierarchy.

    Represents a single drawing (assembly or detail) with its
    relationship to parent assembly.
    """
    part_number: str
    description: str = ""
    parent_pn: str = ""  # Parent part number (empty for root)
    is_assembly: bool = False  # True if has children in DT

    def to_dict(self) -> Dict[str, Any]:
        return {
            "part_number": self.part_number,
            "description": self.description,
            "parent_pn": self.parent_pn,
            "is_assembly": self.is_assembly,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> DTNode:
        return cls(
            part_number=data["part_number"],
            description=data.get("description", ""),
            parent_pn=data.get("parent_pn", ""),
            is_assembly=data.get("is_assembly", False),
        )


@dataclass
class DTHierarchy:
    """Complete hierarchy extracted from Drawing Tree.

    This is the SINGLE SOURCE OF TRUTH for MIUL structure.
    All Index/Parent/NHA values derive from this hierarchy.
    """
    miul_number: str  # Project acronym (e.g., "DMLLV")
    top_assembly: str  # Top-level assembly PN
    nodes: Dict[str, DTNode] = field(default_factory=dict)  # PN -> Node
    root_nodes: List[str] = field(default_factory=list)  # PNs with no parent

    # Metadata for traceability (SWE-033)
    source_file: str = ""
    extracted_at: str = ""
    extractor_version: str = "1.0.0"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "miul_number": self.miul_number,
            "top_assembly": self.top_assembly,
            "nodes": {pn: node.to_dict() for pn, node in self.nodes.items()},
            "root_nodes": self.root_nodes,
            "metadata": {
                "source_file": self.source_file,
                "extracted_at": self.extracted_at,
                "extractor_version": self.extractor_version,
                "stage": "parse_dt",
            }
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> DTHierarchy:
        metadata = data.get("metadata", {})
        hierarchy = cls(
            miul_number=data["miul_number"],
            top_assembly=data["top_assembly"],
            root_nodes=data.get("root_nodes", []),
            source_file=metadata.get("source_file", ""),
            extracted_at=metadata.get("extracted_at", ""),
            extractor_version=metadata.get("extractor_version", "1.0.0"),
        )
        for pn, node_data in data.get("nodes", {}).items():
            hierarchy.nodes[pn] = DTNode.from_dict(node_data)
        return hierarchy

    def save(self, path: Path) -> None:
        """Save hierarchy to JSON file."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=2)
        logger.info(f"[Stage 1] Saved hierarchy to {path}")

    @classmethod
    def load(cls, path: Path) -> DTHierarchy:
        """Load hierarchy from JSON file."""
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return cls.from_dict(data)


def parse_drawing_tree(
    dt_pdf_path: Path,
    miul_number: str,
    output_path: Optional[Path] = None,
    cache: bool = True,
) -> DTHierarchy:
    """Parse Drawing Tree PDF to extract complete hierarchy.

    This is Stage 1 of the MIUL pipeline. The Drawing Tree is the
    SINGLE SOURCE OF TRUTH for assembly hierarchy.

    Args:
        dt_pdf_path: Path to -DT PDF file
        miul_number: MIUL identifier (e.g., "DMLLV")
        output_path: Where to save hierarchy.json (default: same dir as PDF)
        cache: If True and output exists, load from cache

    Returns:
        DTHierarchy with all nodes and relationships

    Compliance: SWE-013 (Traceability via source_file, extracted_at)
    """
    dt_pdf_path = Path(dt_pdf_path)

    if output_path is None:
        output_path = dt_pdf_path.parent / "hierarchy.json"
    output_path = Path(output_path)

    # Check cache
    if cache and output_path.exists():
        logger.info(f"[Stage 1] Loading cached hierarchy from {output_path}")
        return DTHierarchy.load(output_path)

    logger.info(f"[Stage 1] Parsing Drawing Tree: {dt_pdf_path.name}")

    # Convert PDF to images for AI Vision
    images = _pdf_to_images(dt_pdf_path)
    if not images:
        raise ValueError(f"Could not convert PDF to images: {dt_pdf_path}")

    # Extract hierarchy using AI Vision
    hierarchy = _extract_hierarchy_with_ai(images, miul_number, dt_pdf_path.name)

    # Save to cache
    hierarchy.save(output_path)

    return hierarchy


def _extract_hierarchy_with_ai(
    images: List[str],
    miul_number: str,
    source_filename: str,
) -> DTHierarchy:
    """Extract hierarchy from DT images using Claude Vision.

    Args:
        images: List of base64-encoded page images
        miul_number: MIUL identifier
        source_filename: Original PDF filename for traceability

    Returns:
        DTHierarchy with extracted structure
    """
    from anthropic import Anthropic

    prompt = """Analyze this Drawing Tree diagram and extract the COMPLETE assembly hierarchy.

TASK: Extract every drawing number and its parent-child relationship from the visual tree structure.

OUTPUT FORMAT (JSON):
{
    "top_assembly": "MER07540-001",
    "hierarchy": [
        {"part_number": "MER07540-001", "parent": "", "description": "10-INCH VALVE ASSEMBLY", "is_assembly": true},
        {"part_number": "MER07584-001", "parent": "MER07540-001", "description": "INLET HOUSING", "is_assembly": true},
        {"part_number": "MER07570-001", "parent": "MER07540-001", "description": "OUTLET HOUSING", "is_assembly": true},
        {"part_number": "MER07545-001", "parent": "MER07584-001", "description": "DETAIL PART", "is_assembly": false}
    ]
}

RULES:
1. Extract EVERY drawing number visible in the tree
2. Parent = the drawing number this item connects TO (going UP the tree)
3. Top assembly has parent = "" (empty string)
4. is_assembly = true if the item has children in the tree
5. Drawing numbers follow patterns like: MER07540-001, GPE-010-A, ABC12345-001
6. Include description/title for each drawing if visible

Return ONLY valid JSON, no other text."""

    client = Anthropic()

    content = [{"type": "text", "text": prompt}]
    for img_b64 in images:
        content.append({
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": "image/png",
                "data": img_b64,
            }
        })

    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=8000,
        messages=[{"role": "user", "content": content}]
    )

    response_text = response.content[0].text

    # Parse JSON from response
    json_str = response_text
    if "```json" in response_text:
        json_str = response_text.split("```json")[1].split("```")[0]
    elif "```" in response_text:
        json_str = response_text.split("```")[1].split("```")[0]

    data = json.loads(json_str.strip())

    # Build hierarchy
    hierarchy = DTHierarchy(
        miul_number=miul_number,
        top_assembly=_clean_pn(data.get("top_assembly", "")),
        source_file=source_filename,
        extracted_at=datetime.now().isoformat(),
    )

    for item in data.get("hierarchy", []):
        pn = _clean_pn(item.get("part_number", ""))
        if not pn:
            continue

        parent_pn = _clean_pn(item.get("parent", ""))

        node = DTNode(
            part_number=pn,
            description=item.get("description", ""),
            parent_pn=parent_pn,
            is_assembly=item.get("is_assembly", False),
        )
        hierarchy.nodes[pn] = node

        if not parent_pn:
            hierarchy.root_nodes.append(pn)

    # Mark assemblies based on children (in case AI missed is_assembly)
    children_of = {}
    for pn, node in hierarchy.nodes.items():
        if node.parent_pn:
            children_of.setdefault(node.parent_pn, []).append(pn)

    for pn in children_of:
        if pn in hierarchy.nodes:
            hierarchy.nodes[pn].is_assembly = True

    logger.info(f"[Stage 1] Extracted {len(hierarchy.nodes)} nodes, "
                f"top={hierarchy.top_assembly}, roots={len(hierarchy.root_nodes)}")

    return hierarchy


def _pdf_to_images(pdf_path: Path, max_pages: int = 10) -> List[str]:
    """Convert PDF pages to base64 images for AI Vision."""
    try:
        import fitz  # PyMuPDF
        doc = fitz.open(str(pdf_path))
        result = []
        for page_num in range(min(len(doc), max_pages)):
            page = doc[page_num]
            pix = page.get_pixmap(dpi=150)
            result.append(base64.b64encode(pix.tobytes("png")).decode())
        doc.close()
        return result
    except ImportError:
        # Fallback to pdf2image
        from pdf2image import convert_from_path
        import io
        images = convert_from_path(str(pdf_path), dpi=150, first_page=1, last_page=max_pages)
        result = []
        for img in images:
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            result.append(base64.b64encode(buf.getvalue()).decode())
        return result


def _clean_pn(pn: str) -> str:
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
