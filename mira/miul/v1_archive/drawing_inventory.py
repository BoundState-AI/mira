#!/usr/bin/env python3
"""
Module: Drawing Inventory
Purpose: Drawing Inventory Extractor - Complete parts inventory from engineering drawings.

BoundState AI 2025
Version: 1.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Fran OpenAI 5 <noreply@openai.com>
Co-Authored-By: Grok 4.0 <noreply@x.ai>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: NASA-STD-6016C, SWE-013
Safety Critical: True
"""

from __future__ import annotations

import base64
import json
import logging
import os
import re
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Optional

# Environment setup
try:
    from dotenv import load_dotenv
    for p in [Path(__file__).parent / '.env', Path('C:/BoundState/.env'), Path.home() / '.env']:
        if p.exists():
            load_dotenv(p, override=True)
            break
except ImportError:
    pass

USE_BEDROCK = os.getenv("USE_BEDROCK", "0").lower() in ("1", "true", "yes")
BEDROCK_REGION = os.getenv("AWS_REGION", "us-gov-west-1")

# Models
SONNET_BEDROCK = "us-gov.anthropic.claude-sonnet-4-5-20250929-v1:0"
SONNET_DIRECT = "claude-sonnet-4-5-20250929"

logger = logging.getLogger(__name__)


# =============================================================================
# DATA STRUCTURES
# =============================================================================

@dataclass
class Part:
    """A single part entry."""
    part_number: str
    description: str = ""
    quantity: int = 1
    material: str = ""
    material_spec: str = ""
    find_number: str = ""
    source_drawing: str = ""  # Which drawing this part came from
    part_type: str = ""  # DETAIL, HARDWARE, COTS, SUBASSEMBLY


@dataclass
class EmbeddedHardware:
    """Embedded hardware (helicoils, inserts, etc.)."""
    callout: str  # Raw callout text from drawing
    standard: str = ""  # NASM33537, MS33537, etc.
    thread_size: str = ""
    thread_class: str = ""
    quantity: int = 1
    material: str = ""
    source_drawing: str = ""


@dataclass
class SurfaceFinish:
    """Surface finish specification."""
    finish_type: str  # CHEM FILM, PASSIVATE, ANODIZE, etc.
    spec: str = ""  # MIL-DTL-5541, ASTM-A967, etc.
    class_type: str = ""  # Class 1A, Class 3, etc.
    color: str = ""
    source_drawing: str = ""


@dataclass
class Drawing:
    """Complete extraction for a single drawing."""
    file_path: str
    drawing_number: str = ""
    revision: str = ""
    title: str = ""
    drawing_type: str = ""  # ASSEMBLY, DETAIL, DOCUMENT

    # Title block material (for detail drawings)
    primary_material: str = ""
    material_spec: str = ""

    # Parent assembly from "USED ON" or drawing tree
    parent_assembly: str = ""

    # Parts list (for assemblies)
    parts: list[Part] = field(default_factory=list)

    # Embedded hardware (for details)
    hardware: list[EmbeddedHardware] = field(default_factory=list)

    # Surface finishes
    finishes: list[SurfaceFinish] = field(default_factory=list)

    # Extraction metadata
    is_scanned: bool = False
    extraction_warnings: list[str] = field(default_factory=list)


@dataclass
class DrawingTree:
    """Drawing tree hierarchy."""
    top_assembly: str = ""
    hierarchy: dict[str, str] = field(default_factory=dict)  # child -> parent
    all_assemblies: set[str] = field(default_factory=set)


@dataclass
class Inventory:
    """Complete inventory for a drawing package."""
    project: str = ""
    drawings: list[Drawing] = field(default_factory=list)
    tree: DrawingTree = field(default_factory=DrawingTree)

    def to_dict(self) -> dict[str, Any]:
        """Convert to JSON-serializable dict."""
        # Count totals - EXCLUDE subassemblies from part count
        # Subassemblies are structure nodes, not leaf parts
        total_parts = 0
        total_subassemblies = 0
        for d in self.drawings:
            for p in d.parts:
                if p.part_type == "SUBASSEMBLY":
                    total_subassemblies += 1
                else:
                    total_parts += 1

        total_hardware = sum(len(d.hardware) for d in self.drawings)

        # Unique part numbers (excluding subassemblies)
        part_numbers = set()
        for d in self.drawings:
            for p in d.parts:
                if p.part_number and p.part_type != "SUBASSEMBLY":
                    part_numbers.add(p.part_number)

        return {
            "project": self.project,
            "summary": {
                "total_drawings": len(self.drawings),
                "total_parts": total_parts,
                "total_subassemblies": total_subassemblies,
                "total_hardware": total_hardware,
                "unique_part_numbers": len(part_numbers),
            },
            "tree": {
                "top_assembly": self.tree.top_assembly,
                "hierarchy": self.tree.hierarchy,
                "assemblies": sorted(self.tree.all_assemblies),
            },
            "drawings": [self._drawing_to_dict(d) for d in self.drawings],
        }

    def _drawing_to_dict(self, d: Drawing) -> dict:
        return {
            "file": d.file_path,
            "drawing_number": d.drawing_number,
            "revision": d.revision,
            "title": d.title,
            "type": d.drawing_type,
            "parent": d.parent_assembly,
            "material": d.primary_material,
            "material_spec": d.material_spec,
            "parts": [asdict(p) for p in d.parts],
            "hardware": [asdict(h) for h in d.hardware],
            "finishes": [asdict(f) for f in d.finishes],
            "warnings": d.extraction_warnings,
        }


# =============================================================================
# VISION CLIENT
# =============================================================================

class VisionClient:
    """Claude Vision API client."""

    def __init__(self, use_bedrock: bool = USE_BEDROCK, api_key: str = None):
        self.use_bedrock = use_bedrock
        self._client = None
        self._api_key = api_key

        if use_bedrock:
            self.model = SONNET_BEDROCK
        else:
            self.model = SONNET_DIRECT

    @property
    def client(self):
        if self._client is None:
            if self.use_bedrock:
                from anthropic import AnthropicBedrock
                self._client = AnthropicBedrock(aws_region=BEDROCK_REGION)
                logger.info(f"Using Bedrock in {BEDROCK_REGION}")
            else:
                from anthropic import Anthropic
                self._client = Anthropic(api_key=self._api_key)
                logger.info("Using direct Anthropic API")
        return self._client

    def call(self, images: list[str], prompt: str, max_tokens: int = 4096) -> str:
        """Call vision API with images and prompt."""
        content = []
        for img in images:
            content.append({
                "type": "image",
                "source": {"type": "base64", "media_type": "image/png", "data": img}
            })
        content.append({"type": "text", "text": prompt})

        response = self.client.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            temperature=0,
            messages=[{"role": "user", "content": content}]
        )
        return response.content[0].text.strip()

    def parse_json(self, text: str) -> Any:
        """Parse JSON from API response."""
        # Strip markdown fences
        text = text.strip()
        if text.startswith("```json"):
            text = text[7:]
        elif text.startswith("```"):
            text = text[3:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()

        try:
            return json.loads(text)
        except json.JSONDecodeError:
            # Try to find JSON object/array
            match = re.search(r'[\[{][\s\S]*[\]}]', text)
            if match:
                try:
                    return json.loads(match.group())
                except json.JSONDecodeError:
                    pass
            return None


# =============================================================================
# PDF UTILITIES
# =============================================================================

def pdf_to_images(pdf_path: Path, dpi: int = 200) -> list[str]:
    """Convert PDF to base64 PNG images."""
    import fitz  # PyMuPDF

    doc = fitz.open(pdf_path)
    images = []

    for page in doc:
        # Scale down very large pages
        pix = page.get_pixmap(dpi=dpi)
        if max(pix.width, pix.height) > 7500:
            scale = 7500 / max(pix.width, pix.height)
            pix = page.get_pixmap(dpi=int(dpi * scale))

        img_bytes = pix.tobytes("png")
        images.append(base64.b64encode(img_bytes).decode())

    doc.close()
    return images


def extract_text(pdf_path: Path) -> str:
    """Extract text from PDF for validation."""
    import fitz

    doc = fitz.open(pdf_path)
    text = "\n".join(page.get_text("text") for page in doc)
    doc.close()
    return text


# =============================================================================
# EXTRACTION PROMPTS
# =============================================================================

PROMPT_DRAWING_TREE = """Analyze this Drawing Tree document and extract the COMPLETE hierarchy.

The drawing tree shows which parts/assemblies belong to which parent assemblies.

Extract:
1. The TOP-LEVEL assembly (root of the tree, has no parent)
2. ALL parent-child relationships
3. ALL assemblies (drawings that contain other parts)

RULES:
- Read drawing numbers EXACTLY as shown (e.g., MER07540-001, GPE-A000-1)
- Do NOT include document numbers (-DT, -DOC, -ICD, -BOM)
- Each child has ONE immediate parent

Return ONLY valid JSON:
{
  "top_assembly": "TOP_LEVEL_DRAWING_NUMBER",
  "hierarchy": {
    "CHILD_NUMBER": "PARENT_NUMBER",
    "CHILD_NUMBER_2": "PARENT_NUMBER"
  },
  "all_assemblies": ["ASSEMBLY1", "ASSEMBLY2"]
}"""


PROMPT_TITLE_BLOCK = """Extract the TITLE BLOCK information from this engineering drawing.

The title block is typically in the lower-right corner and contains:
- DRAWING NUMBER / PART NUMBER
- REVISION letter or number
- TITLE / PART NAME (short descriptive name like "TOP PLATE", "VALVE ASSEMBLY")
- MATERIAL (may be in title block OR labeled elsewhere on drawing)
- MATERIAL SPEC (e.g., AMS 5737, QQ-A-250)
- USED ON / NEXT ASSY (parent assembly number)

ALSO check the drawing for:
- Is there a PARTS LIST or EPL table? (indicates ASSEMBLY drawing)
- Material callouts anywhere on the drawing

Return ONLY valid JSON:
{
  "drawing_number": "exact number as shown",
  "revision": "revision letter/number",
  "title": "part name from title block",
  "drawing_type": "ASSEMBLY or DETAIL",
  "material": "full material designation if shown",
  "material_spec": "material specification",
  "used_on": "parent assembly number if shown"
}"""


PROMPT_PARTS_LIST = """Extract the COMPLETE PARTS LIST / EPL table from this assembly drawing.

The parts list table typically has columns:
- FIND NO. / ITEM (reference number)
- QTY / QTY REQD (quantity)
- PART NUMBER / DWG NO (part/drawing number)
- DESCRIPTION / NOMENCLATURE (part name)
- MATERIAL (material designation)

CRITICAL RULES:
1. Extract EVERY row from the table - do not skip any
2. Read the QTY column for EACH row - don't assume quantities
3. Read part numbers EXACTLY as shown
4. Include standard hardware (NAS, MS, AN parts)
5. Include sub-assembly references
6. If a part appears on multiple rows, include each occurrence

Return ONLY valid JSON array:
[
  {
    "find_no": "1",
    "qty": 2,
    "part_number": "MER07543-001",
    "description": "SHAFT SUB-ASSEMBLY",
    "material": "A286"
  }
]

If no parts list found, return empty array: []"""


PROMPT_EMBEDDED_HARDWARE = """Extract ALL embedded hardware callouts from this DETAIL drawing.

Look in the NOTES section and on the drawing for:

1. HELICOIL / HELICAL COIL INSERTS:
   - Pattern: "24X .2500-20 UNC-3B HELICAL COIL INSERT PER NASM33537"
   - Extract: quantity (24X), thread size, thread class, spec

2. THREAD INSERTS:
   - NASM33537, NASM33538, MS33537, HCC-xxx

3. PRESS-FIT HARDWARE:
   - Dowel pins, bushings with specifications

For EACH item, extract the COMPLETE callout text plus parsed details.

Return ONLY valid JSON:
{
  "hardware": [
    {
      "callout": "24X .2500-20 UNC-3B HELICAL COIL INSERT PER NASM33537",
      "quantity": 24,
      "thread_size": ".2500-20",
      "thread_class": "UNC-3B",
      "standard": "NASM33537",
      "material": "302/304 CRES"
    }
  ]
}

If no hardware found, return: {"hardware": []}"""


PROMPT_SURFACE_FINISH = """Extract ALL surface finish specifications from this drawing.

Look in NOTES section for:
- Chemical conversion coating: MIL-DTL-5541, Chem Film, Alodine
- Passivation: ASTM-A967, AMS-QQ-P-35, AMS 2700
- Anodize: MIL-A-8625
- Paint/Primer: MIL-PRF-23377, FED-STD-595
- Plating: QQ-N-290, AMS 2404

For each finish, extract:
- Finish type (CHEM FILM, PASSIVATE, ANODIZE, etc.)
- Specification number
- Class/Type if specified
- Color if specified

Return ONLY valid JSON:
{
  "finishes": [
    {
      "type": "CHEM FILM",
      "spec": "MIL-DTL-5541",
      "class": "TYPE 1, CLASS 3",
      "color": "GOLD"
    }
  ]
}

If no finishes found, return: {"finishes": []}"""


# =============================================================================
# EXTRACTOR
# =============================================================================

class DrawingInventoryExtractor:
    """Extract complete parts inventory from engineering drawings."""

    # Files to skip (documents, not drawings)
    SKIP_PATTERNS = ["-DT", "-DOC", "-ICD", "-BOM", "MIUL", "TREE", "LIST"]

    def __init__(self, use_bedrock: bool = USE_BEDROCK, api_key: str = None):
        self.vision = VisionClient(use_bedrock=use_bedrock, api_key=api_key)
        self.inventory = Inventory()

    def extract(self, directory: Path, output_path: Path = None) -> Inventory:
        """Extract complete inventory from drawing directory.

        Args:
            directory: Path to folder containing drawing PDFs
            output_path: Optional JSON output path

        Returns:
            Inventory with all extracted data
        """
        directory = Path(directory)
        self.inventory = Inventory(project=directory.name)

        logger.info("=" * 60)
        logger.info(f"DRAWING INVENTORY EXTRACTOR - {directory.name}")
        logger.info("=" * 60)

        # Find all PDFs
        all_pdfs = sorted(directory.glob("*.pdf"))

        # Separate drawing tree from drawings
        dt_pdf = None
        drawing_pdfs = []

        for pdf in all_pdfs:
            if self._is_document(pdf.name):
                if "-DT" in pdf.name.upper() or "TREE" in pdf.name.upper():
                    dt_pdf = pdf
                    logger.info(f"Found drawing tree: {pdf.name}")
                else:
                    logger.info(f"Skipping document: {pdf.name}")
            else:
                drawing_pdfs.append(pdf)

        logger.info(f"Found {len(drawing_pdfs)} drawing PDFs")

        # Step 1: Extract drawing tree if present
        if dt_pdf:
            self._extract_drawing_tree(dt_pdf)

        # Step 2: Extract each drawing
        for pdf in drawing_pdfs:
            logger.info(f"\nProcessing: {pdf.name}")
            drawing = self._extract_drawing(pdf)
            self.inventory.drawings.append(drawing)

        # Step 3: Build parent relationships from tree
        self._apply_tree_hierarchy()

        # Save output
        if output_path is None:
            output_path = directory / f"{directory.name}_inventory.json"

        with open(output_path, "w") as f:
            json.dump(self.inventory.to_dict(), f, indent=2)

        logger.info(f"\nSaved inventory to: {output_path}")
        self._print_summary()

        return self.inventory

    def _is_document(self, filename: str) -> bool:
        """Check if file is a document (not a drawing)."""
        fn_upper = filename.upper()
        return any(pat in fn_upper for pat in self.SKIP_PATTERNS)

    def _extract_drawing_tree(self, pdf_path: Path) -> None:
        """Extract drawing tree hierarchy."""
        logger.info("Extracting drawing tree hierarchy...")

        images = pdf_to_images(pdf_path)
        if not images:
            logger.warning("Could not convert drawing tree PDF")
            return

        try:
            response = self.vision.call(images, PROMPT_DRAWING_TREE)
            data = self.vision.parse_json(response)

            if data:
                self.inventory.tree.top_assembly = data.get("top_assembly", "")
                self.inventory.tree.hierarchy = data.get("hierarchy", {})
                self.inventory.tree.all_assemblies = set(data.get("all_assemblies", []))

                logger.info(f"  Top assembly: {self.inventory.tree.top_assembly}")
                logger.info(f"  Hierarchy entries: {len(self.inventory.tree.hierarchy)}")
                logger.info(f"  Assemblies: {len(self.inventory.tree.all_assemblies)}")
        except Exception as e:
            logger.error(f"Drawing tree extraction failed: {e}")

    def _extract_drawing(self, pdf_path: Path) -> Drawing:
        """Extract all data from a single drawing."""
        drawing = Drawing(file_path=pdf_path.name)

        # Convert to images
        images = pdf_to_images(pdf_path)
        if not images:
            drawing.extraction_warnings.append("Failed to convert PDF")
            return drawing

        # Check if scanned (for validation later)
        text = extract_text(pdf_path)
        drawing.is_scanned = len(text) < 500

        # Extract title block
        self._extract_title_block(drawing, images[0])

        # Extract based on drawing type
        if drawing.drawing_type == "ASSEMBLY":
            self._extract_parts_list(drawing, images)
        else:
            # Detail drawing - add itself as a part
            if drawing.drawing_number:
                drawing.parts.append(Part(
                    part_number=drawing.drawing_number,
                    description=drawing.title,
                    quantity=1,
                    material=drawing.primary_material,
                    material_spec=drawing.material_spec,
                    source_drawing=drawing.drawing_number,
                    part_type="DETAIL"
                ))

            # Extract embedded hardware
            self._extract_hardware(drawing, images)

        # Extract surface finishes (all drawings)
        self._extract_finishes(drawing, images[0])

        return drawing

    def _extract_title_block(self, drawing: Drawing, image: str) -> None:
        """Extract title block information."""
        try:
            response = self.vision.call([image], PROMPT_TITLE_BLOCK, max_tokens=1000)
            data = self.vision.parse_json(response)

            if data:
                drawing.drawing_number = data.get("drawing_number", "")
                drawing.revision = data.get("revision", "")
                drawing.title = data.get("title", "")
                drawing.drawing_type = data.get("drawing_type", "DETAIL")
                drawing.primary_material = data.get("material", "")
                drawing.material_spec = data.get("material_spec", "")
                drawing.parent_assembly = data.get("used_on", "")

                logger.info(f"  Type: {drawing.drawing_type}")
                logger.info(f"  Title: {drawing.title}")
                if drawing.primary_material:
                    logger.info(f"  Material: {drawing.primary_material}")
        except Exception as e:
            logger.warning(f"  Title block extraction failed: {e}")
            drawing.extraction_warnings.append(f"Title block: {e}")

    def _extract_parts_list(self, drawing: Drawing, images: list[str]) -> None:
        """Extract parts list from assembly drawing."""
        logger.info("  Extracting parts list...")

        try:
            # Check all pages for parts list
            all_parts = []
            for i, image in enumerate(images[:5]):  # First 5 pages
                response = self.vision.call([image], PROMPT_PARTS_LIST)
                data = self.vision.parse_json(response)

                if data and isinstance(data, list):
                    for p in data:
                        part = Part(
                            find_number=str(p.get("find_no", "")),
                            part_number=p.get("part_number", ""),
                            description=p.get("description", ""),
                            quantity=self._parse_qty(p.get("qty", 1)),
                            material=p.get("material", ""),
                            source_drawing=drawing.drawing_number,
                            part_type=self._classify_part(p.get("part_number", ""))
                        )
                        all_parts.append(part)

                    if data:
                        logger.info(f"    Page {i+1}: {len(data)} parts")

            drawing.parts = all_parts
            logger.info(f"  Total parts: {len(all_parts)}")

        except Exception as e:
            logger.warning(f"  Parts list extraction failed: {e}")
            drawing.extraction_warnings.append(f"Parts list: {e}")

    def _extract_hardware(self, drawing: Drawing, images: list[str]) -> None:
        """Extract embedded hardware from detail drawing."""
        logger.info("  Extracting embedded hardware...")

        try:
            # Check all pages
            for image in images:
                response = self.vision.call([image], PROMPT_EMBEDDED_HARDWARE)
                data = self.vision.parse_json(response)

                if data and "hardware" in data:
                    for h in data["hardware"]:
                        hw = EmbeddedHardware(
                            callout=h.get("callout", ""),
                            standard=h.get("standard", ""),
                            thread_size=h.get("thread_size", ""),
                            thread_class=h.get("thread_class", ""),
                            quantity=h.get("quantity", 1),
                            material=h.get("material", ""),
                            source_drawing=drawing.drawing_number
                        )
                        drawing.hardware.append(hw)

            if drawing.hardware:
                logger.info(f"  Found {len(drawing.hardware)} hardware items")

        except Exception as e:
            logger.warning(f"  Hardware extraction failed: {e}")
            drawing.extraction_warnings.append(f"Hardware: {e}")

    def _extract_finishes(self, drawing: Drawing, image: str) -> None:
        """Extract surface finishes."""
        try:
            response = self.vision.call([image], PROMPT_SURFACE_FINISH)
            data = self.vision.parse_json(response)

            if data and "finishes" in data:
                for f in data["finishes"]:
                    finish = SurfaceFinish(
                        finish_type=f.get("type", ""),
                        spec=f.get("spec", ""),
                        class_type=f.get("class", ""),
                        color=f.get("color", ""),
                        source_drawing=drawing.drawing_number
                    )
                    drawing.finishes.append(finish)

                if drawing.finishes:
                    logger.info(f"  Found {len(drawing.finishes)} surface finishes")

        except Exception as e:
            drawing.extraction_warnings.append(f"Finishes: {e}")

    def _apply_tree_hierarchy(self) -> None:
        """Apply drawing tree parent relationships."""
        if not self.inventory.tree.hierarchy:
            return

        for drawing in self.inventory.drawings:
            if not drawing.parent_assembly:
                # Look up in tree hierarchy
                dn = drawing.drawing_number
                if dn in self.inventory.tree.hierarchy:
                    drawing.parent_assembly = self.inventory.tree.hierarchy[dn]

    def _parse_qty(self, val) -> int:
        """Parse quantity value."""
        if isinstance(val, int):
            return val
        if isinstance(val, str):
            val = val.strip().upper()
            if val in ("A/R", "AR", "REF", "-", ""):
                return 1
            try:
                return int(val)
            except ValueError:
                return 1
        return 1

    def _classify_part(self, part_number: str) -> str:
        """Classify part type from part number."""
        pn = (part_number or "").upper()

        # Standard hardware
        if any(pn.startswith(p) for p in ["NAS", "MS", "AN", "AS"]):
            return "HARDWARE"

        # COTS parts (vendor parts with non-drawing numbers)
        if re.match(r'^[A-Z]{2,3}-\d+', pn):
            return "COTS"

        # Drawing reference (matches project drawing number pattern)
        if re.match(r'^MER\d{5}-\d{3}', pn) or re.match(r'^[A-Z]{3}-[A-Z0-9]+-\d', pn):
            return "SUBASSEMBLY"

        return "PART"

    def _print_summary(self) -> None:
        """Print extraction summary."""
        inv = self.inventory

        # Count parts excluding subassemblies (they are structure, not leaf items)
        total_parts = 0
        total_subassemblies = 0
        for d in inv.drawings:
            for p in d.parts:
                if p.part_type == "SUBASSEMBLY":
                    total_subassemblies += 1
                else:
                    total_parts += 1

        total_hardware = sum(len(d.hardware) for d in inv.drawings)
        assemblies = sum(1 for d in inv.drawings if d.drawing_type == "ASSEMBLY")
        details = sum(1 for d in inv.drawings if d.drawing_type == "DETAIL")

        print("\n" + "=" * 60)
        print("EXTRACTION SUMMARY")
        print("=" * 60)
        print(f"Project: {inv.project}")
        print(f"Drawings: {len(inv.drawings)} ({assemblies} assemblies, {details} details)")
        print(f"Parts (leaf items): {total_parts}")
        print(f"Subassemblies (structure): {total_subassemblies}")
        print(f"Embedded hardware: {total_hardware}")
        if inv.tree.top_assembly:
            print(f"Top assembly: {inv.tree.top_assembly}")
        print("=" * 60)


# =============================================================================
# CLI
# =============================================================================

def main():
    import argparse

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s"
    )

    parser = argparse.ArgumentParser(
        description="Extract complete parts inventory from engineering drawings"
    )
    parser.add_argument("directory", type=Path, help="Directory containing drawing PDFs")
    parser.add_argument("-o", "--output", type=Path, help="Output JSON path")
    parser.add_argument("--bedrock", action="store_true", help="Use AWS Bedrock")
    parser.add_argument("--api-key", help="Anthropic API key")

    args = parser.parse_args()

    if args.bedrock:
        os.environ["USE_BEDROCK"] = "1"

    extractor = DrawingInventoryExtractor(
        use_bedrock=args.bedrock or USE_BEDROCK,
        api_key=args.api_key
    )
    extractor.extract(args.directory, args.output)


if __name__ == "__main__":
    main()
