#!/usr/bin/env python3
"""
Module: Parse Drawings
Purpose: Stage 2-3 - Drawing Parser

BoundState AI 2025
Version: 1.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Fran OpenAI 5 <noreply@openai.com>
Co-Authored-By: Grok 4.0 <noreply@x.ai>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: SWE-013, SWE-033, NASA-STD-6016C
Safety Critical: True
"""

from __future__ import annotations

import base64
import json
import logging
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

logger = logging.getLogger(__name__)

__all__ = [
    "parse_detail_drawings",
    "parse_assembly_epls",
    "DrawingData",
    "EPLItem",
]
__safety_critical__ = True


@dataclass
class EPLItem:
    """Single item from Engineering Parts List (EPL)."""
    find_no: str = ""
    part_number: str = ""
    qty: int = 1
    description: str = ""
    material: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> EPLItem:
        return cls(
            find_no=str(data.get("find_no", "")),
            part_number=data.get("part_number", ""),
            qty=_parse_qty(data.get("qty", 1)),
            description=data.get("description", ""),
            material=data.get("material", ""),
        )


@dataclass
class DrawingData:
    """Extracted data from a single drawing.

    Contains materials for detail drawings, EPL for assembly drawings.
    Each drawing gets its own JSON file for caching/debugging.
    """
    part_number: str
    title: str = ""
    is_assembly: bool = False

    # Material data (detail drawings)
    designation: str = ""  # e.g., "15-5 PH STEEL"
    material_spec: str = ""  # e.g., "AMS 5659"
    process_spec: str = ""  # e.g., "MIL-DTL-5541 CLASS 3"
    form: str = ""  # e.g., "FORGING"

    # EPL items (assembly drawings)
    epl: List[EPLItem] = field(default_factory=list)

    # Metadata for traceability (SWE-033)
    source_file: str = ""
    extracted_at: str = ""
    extractor_version: str = "1.0.0"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "part_number": self.part_number,
            "title": self.title,
            "is_assembly": self.is_assembly,
            "material": {
                "designation": self.designation,
                "material_spec": self.material_spec,
                "process_spec": self.process_spec,
                "form": self.form,
            },
            "epl": [item.to_dict() for item in self.epl],
            "metadata": {
                "source_file": self.source_file,
                "extracted_at": self.extracted_at,
                "extractor_version": self.extractor_version,
                "stage": "parse_drawings",
            }
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> DrawingData:
        material = data.get("material", {})
        metadata = data.get("metadata", {})
        drawing = cls(
            part_number=data["part_number"],
            title=data.get("title", ""),
            is_assembly=data.get("is_assembly", False),
            designation=material.get("designation", ""),
            material_spec=material.get("material_spec", ""),
            process_spec=material.get("process_spec", ""),
            form=material.get("form", ""),
            source_file=metadata.get("source_file", ""),
            extracted_at=metadata.get("extracted_at", ""),
            extractor_version=metadata.get("extractor_version", "1.0.0"),
        )
        for item_data in data.get("epl", []):
            drawing.epl.append(EPLItem.from_dict(item_data))
        return drawing

    def save(self, output_dir: Path) -> Path:
        """Save drawing data to JSON file."""
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        path = output_dir / f"{self.part_number}.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=2)
        return path

    @classmethod
    def load(cls, path: Path) -> DrawingData:
        """Load drawing data from JSON file."""
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return cls.from_dict(data)


def parse_detail_drawings(
    drawing_dir: Path,
    known_pns: Set[str],
    output_dir: Optional[Path] = None,
    cache: bool = True,
) -> Dict[str, DrawingData]:
    """Parse detail drawings to extract material data.

    Stage 2 of the MIUL pipeline. Extracts materials from title blocks.

    Args:
        drawing_dir: Directory containing PDF drawings
        known_pns: Set of part numbers from DT hierarchy
        output_dir: Where to save drawings/*.json (default: drawing_dir/drawings)
        cache: If True, skip drawings that already have JSON

    Returns:
        Dict mapping part_number -> DrawingData
    """
    drawing_dir = Path(drawing_dir)
    if output_dir is None:
        output_dir = drawing_dir / "drawings"
    output_dir = Path(output_dir)

    # Find detail PDFs (exclude -DT, -DOC, -ICD, etc.)
    pdf_files = list(drawing_dir.glob("*.pdf"))
    exclude_suffixes = ["-DT", "-DOC", "-ICD", "DRAWING TREE", "_SPEC"]
    detail_pdfs = [
        p for p in pdf_files
        if not any(x in p.stem.upper() for x in exclude_suffixes)
    ]

    logger.info(f"[Stage 2] Found {len(detail_pdfs)} detail drawings")

    results = {}

    # Process in batches for efficiency
    batch_size = 5
    for i in range(0, len(detail_pdfs), batch_size):
        batch = detail_pdfs[i:i+batch_size]
        batch_results = _extract_materials_batch(batch, output_dir, cache)
        results.update(batch_results)

    logger.info(f"[Stage 2] Extracted materials from {len(results)} drawings")
    return results


def parse_assembly_epls(
    drawing_dir: Path,
    assembly_pns: Set[str],
    output_dir: Optional[Path] = None,
    cache: bool = True,
) -> Dict[str, DrawingData]:
    """Parse assembly drawings to extract EPL (Engineering Parts List).

    Stage 3 of the MIUL pipeline. Extracts fasteners, seals, hardware.

    Args:
        drawing_dir: Directory containing PDF drawings
        assembly_pns: Set of assembly part numbers (from DT hierarchy)
        output_dir: Where to save drawings/*.json
        cache: If True, skip assemblies that already have JSON with EPL

    Returns:
        Dict mapping assembly_pn -> DrawingData (with epl populated)
    """
    drawing_dir = Path(drawing_dir)
    if output_dir is None:
        output_dir = drawing_dir / "drawings"
    output_dir = Path(output_dir)

    logger.info(f"[Stage 3] Extracting EPL from {len(assembly_pns)} assemblies")

    results = {}

    for assy_pn in assembly_pns:
        # Check cache
        cached_path = output_dir / f"{assy_pn}.json"
        if cache and cached_path.exists():
            drawing = DrawingData.load(cached_path)
            if drawing.epl:  # Already has EPL
                results[assy_pn] = drawing
                continue

        # Find PDF for this assembly
        pdf_candidates = list(drawing_dir.glob(f"*{assy_pn}*.pdf"))
        if not pdf_candidates:
            logger.warning(f"[Stage 3] No PDF found for assembly {assy_pn}")
            continue

        pdf_path = pdf_candidates[0]

        try:
            epl_items = _extract_epl_from_pdf(pdf_path, assy_pn)

            # Load existing or create new
            if cached_path.exists():
                drawing = DrawingData.load(cached_path)
            else:
                drawing = DrawingData(
                    part_number=assy_pn,
                    is_assembly=True,
                    source_file=pdf_path.name,
                    extracted_at=datetime.now().isoformat(),
                )

            drawing.epl = epl_items
            drawing.is_assembly = True
            drawing.save(output_dir)
            results[assy_pn] = drawing

            logger.debug(f"[Stage 3] {assy_pn}: {len(epl_items)} EPL items")

        except Exception as e:
            logger.warning(f"[Stage 3] EPL extraction failed for {assy_pn}: {e}")

    logger.info(f"[Stage 3] Extracted EPL from {len(results)} assemblies")
    return results


def _extract_materials_batch(
    pdf_paths: List[Path],
    output_dir: Path,
    cache: bool,
) -> Dict[str, DrawingData]:
    """Extract materials from a batch of PDFs using AI Vision."""
    from anthropic import Anthropic

    results = {}
    pdfs_to_process = []

    # Check cache first
    for pdf_path in pdf_paths:
        pn = _extract_pn_from_filename(pdf_path.stem)
        cached_path = output_dir / f"{pn}.json"

        if cache and cached_path.exists():
            drawing = DrawingData.load(cached_path)
            results[pn] = drawing
        else:
            pdfs_to_process.append((pdf_path, pn))

    if not pdfs_to_process:
        return results

    prompt = """Extract material information from these engineering drawings.

For EACH drawing, extract from the title block and notes:
- Part Number (from title block)
- Title/Description
- Material/Designation (e.g., "15-5 PH STEEL", "6061-T6 ALUMINUM")
- Material Specification (e.g., "AMS 5659", "QQ-A-250/11")
- Process Specification (e.g., "MIL-DTL-5541", "AMS 2700")
- Material Form (e.g., "BAR", "PLATE", "FORGING")

OUTPUT FORMAT (JSON):
{
    "drawings": [
        {
            "part_number": "MER07584-001",
            "title": "INLET HOUSING",
            "designation": "15-5 PH STEEL",
            "material_spec": "AMS 5659",
            "process_spec": "MIL-DTL-5541 CLASS 3",
            "form": "FORGING"
        }
    ]
}

RULES:
1. Only extract materials explicitly stated in drawing
2. Do NOT infer or guess materials
3. Return empty string for missing fields
4. One entry per drawing

Return ONLY valid JSON."""

    client = Anthropic()

    content = [{"type": "text", "text": prompt}]

    for pdf_path, pn in pdfs_to_process:
        try:
            images = _pdf_to_images(pdf_path, max_pages=1)
            if images:
                content.append({
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": "image/png",
                        "data": images[0],
                    }
                })
        except Exception as e:
            logger.warning(f"[Stage 2] Failed to convert {pdf_path.name}: {e}")

    if len(content) == 1:
        return results  # No images to process

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

        for item in data.get("drawings", []):
            pn = _clean_pn(item.get("part_number", ""))
            if not pn:
                continue

            # Find matching PDF for source_file
            source_file = ""
            for pdf_path, orig_pn in pdfs_to_process:
                if orig_pn == pn or pn in pdf_path.stem.upper():
                    source_file = pdf_path.name
                    break

            drawing = DrawingData(
                part_number=pn,
                title=item.get("title", ""),
                designation=item.get("designation", ""),
                material_spec=item.get("material_spec", ""),
                process_spec=item.get("process_spec", ""),
                form=item.get("form", ""),
                source_file=source_file,
                extracted_at=datetime.now().isoformat(),
            )
            drawing.save(output_dir)
            results[pn] = drawing

    except Exception as e:
        logger.warning(f"[Stage 2] Material batch extraction failed: {e}")

    return results


def _extract_epl_from_pdf(pdf_path: Path, assembly_pn: str) -> List[EPLItem]:
    """Extract EPL table from a single assembly PDF."""
    from anthropic import Anthropic

    images = _pdf_to_images(pdf_path, max_pages=3)  # EPL may span pages
    if not images:
        return []

    prompt = f"""Extract the Engineering Parts List (EPL) or PARTS LIST table from this assembly drawing.

ASSEMBLY: {assembly_pn}

Extract ONLY items from the PARTS LIST / EPL table. These are typically:
- Fasteners (bolts, nuts, screws, washers)
- Seals (O-rings, backup rings)
- Hardware (pins, retaining rings)
- Helicoil inserts

OUTPUT FORMAT (JSON):
{{
    "parts": [
        {{"find_no": "1", "part_number": "NAS1352C3-8", "qty": 4, "description": "SCREW", "material": "A286 CRES"}},
        {{"find_no": "2", "part_number": "MS21042-3", "qty": 4, "description": "NUT", "material": "A286 CRES"}},
        {{"find_no": "3", "part_number": "2-218", "qty": 1, "description": "O-RING", "material": "VITON"}}
    ]
}}

RULES:
1. Only extract items from the PARTS LIST / EPL table
2. Do NOT include drawing references (other assembly/detail drawings)
3. Find numbers may be numeric or alphanumeric
4. Qty may be "AR" (as required) - return as 0
5. Material may be in a separate column or part of description

Return ONLY valid JSON. If no EPL found, return {{"parts": []}}"""

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

        items = []
        for item in data.get("parts", []):
            items.append(EPLItem.from_dict(item))
        return items

    except Exception as e:
        logger.warning(f"[Stage 3] EPL parse error for {assembly_pn}: {e}")
        return []


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
    """Clean part number."""
    if not pn:
        return ""
    cleaned = pn.strip()
    if ".DRW" in cleaned.upper():
        idx = cleaned.upper().find(".DRW")
        cleaned = cleaned[:idx]
    if "(" in cleaned:
        cleaned = cleaned.split("(")[0].strip()
    return cleaned.strip().upper()


def _extract_pn_from_filename(filename: str) -> str:
    """Extract part number from PDF filename."""
    # Handle formats like: MER07584-001.DRW_-.12_RELEASED
    pn = filename.upper()
    if ".DRW" in pn:
        pn = pn.split(".DRW")[0]
    if "_-." in pn:
        pn = pn.split("_-.")[0]
    return pn.strip()


def _parse_qty(qty_raw) -> int:
    """Parse quantity, handling AR/REF."""
    if isinstance(qty_raw, int):
        return qty_raw
    qty_str = str(qty_raw).strip().upper()
    if qty_str in ("AR", "A/R", "REF", ""):
        return 0
    try:
        return int(float(qty_str))
    except (ValueError, TypeError):
        return 1
