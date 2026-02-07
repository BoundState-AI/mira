#!/usr/bin/env python3
"""
Module: Prompts
Purpose: [Automatically migrated - needs manual review]

BoundState AI 2025
Version: 1.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Fran OpenAI 5 <noreply@openai.com>
Co-Authored-By: Grok 4.0 <noreply@x.ai>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: SWE-013
Safety Critical: True
"""

from __future__ import annotations
import uuid

__all__ = ["MSFCPrompts"]


class MSFCPrompts:
    """Prompts optimized for MSFC drawing format extraction."""

    @staticmethod
    def title_block_extraction() -> str:
        """Extract title block from MSFC format drawing."""
        return """Analyze this MSFC-format engineering drawing and extract the TITLE BLOCK information.

The title block is in the LOWER RIGHT corner and follows MSFC standard format.

Extract these fields and return as JSON:
{
    "drawing_number": "string - Part/drawing number (e.g., MER07564-001)",
    "revision": "string or null - Revision letter after the dash",
    "title": "string - Part name/title (e.g., 'BODY, VALVE, 10 INCH')",
    "cage_code": "string or null - CAGE code (e.g., '339B2')",
    "material_line": "string - Complete material callout as written",
    "material_designation": "string - Material name (e.g., 'ALUMINUM ALLOY 7075-T6')",
    "material_spec": "string or null - Specification (e.g., 'SAE AMS4124')",
    "uns_number": "string or null - UNS number (e.g., 'A97075')",
    "calc_weight_lbs": number or null - Calculated weight in pounds,
    "sheet_number": number - Current sheet number,
    "total_sheets": number - Total sheets in drawing,
    "next_assembly": "string or null - Next assembly drawing number"
}

MSFC Title Block Layout:
- Drawing number and CAGE code are at TOP of title block
- Title/description is below that
- Material callout is in the MATERIAL field (look for 'MATERIAL' label)
- Weight is near bottom right (look for 'CALC WEIGHT' or 'LBS')
- Sheet info shows as 'SHEET X OF Y'

Return ONLY valid JSON. No explanation."""

    @staticmethod
    def embedded_hardware_extraction() -> str:
        """Find all embedded hardware requiring separate material tracking."""
        return """Analyze this engineering drawing for EMBEDDED HARDWARE that requires separate
material tracking. These are standard parts INSTALLED INTO the main part.

Look for these patterns in the drawing body (NOT in the title block):

1. HELICAL COIL INSERTS:
   Pattern: "nX .XXXX-XX UNC-3B HELICAL COIL INSERT THD PER NASMxxxxx"
   Example: "4X .3125-18 UNC-3B HELICAL COIL INSERT THD PER NASM33537"

2. FASTENER CALLOUTS:
   Pattern: "nX NASxxxx" or "nX MSxxxxx" or "nX ANxxx"
   Example: "8X NAS1351-3-8"

3. PRESS-FIT HARDWARE:
   Pattern: Dowel pins, bushings with material specs
   Example: "2X DOWEL PIN .250 DIA x 1.00 LG, SS 303"

ALSO LOOK FOR INSERT TABLES:
- MSFC drawings often have a TABLE listing inserts with their MATERIAL
- Look for tables with columns like: THREAD SIZE, QTY, STANDARD, MATERIAL
- The material column tells you exactly what material the insert is made of
- Common materials: CRES 302, CRES 304, A-286, INCONEL

For EACH embedded hardware item, extract:
{
    "items": [
        {
            "standard": "NASM33537",
            "thread_size": ".3125-18",
            "quantity": 4,
            "material": "CRES 302",
            "raw_callout": "4X .3125-18 UNC-3B HELICAL COIL INSERT THD PER NASM33537 .53 MIN FULL THD DEPTH"
        }
    ]
}

CRITICAL RULES:
- The prefix number (4X, 24X, etc.) indicates QUANTITY
- If you see "4X" that means 4 pieces
- Count ALL callouts on ALL views - they may repeat on different sheets
- Same standard with same thread size = aggregate quantities
- Different thread sizes = separate entries
- If a material is specified in the table or callout, include it in "material" field
- If no material specified, omit the "material" field

Return ONLY valid JSON with an "items" array."""

    @staticmethod
    def referenced_standards_extraction() -> str:
        """Extract all referenced standards and specifications."""
        return """List ALL standards, specifications, and reference documents on this drawing.

Look for:
- Material specs: AMS, MIL-SPEC, QQ-, ASTM, SAE, UNS
- Hardware standards: NASM, NAS, MS, AN
- Process specs: MIL-STD, NASA-STD, MSFC-SPEC, ASME
- Drawing standards: ASME Y14.xx, ASME B46.1
- Test methods: ASTM E, ASTM G

Search in:
- Notes section (usually left side or bottom)
- Title block material callout
- Finish/coating callouts
- Thread insert callouts
- Any callout referencing a document number

Return JSON:
{
    "material_specs": ["SAE AMS4124", "UNS A97075"],
    "hardware_standards": ["NASM33537"],
    "process_specs": ["MIL-STD-130", "SAE AS478-35D", "ASME B46.1"],
    "drawing_standards": ["ASME Y14.41-2003"],
    "other_references": []
}

Return ONLY valid JSON."""

    @staticmethod
    def drawing_tree_extraction() -> str:
        """Extract assembly hierarchy from an MSFC Drawing Tree."""
        return """Analyze this MSFC Drawing Tree (DT) and extract the complete assembly hierarchy.

A Drawing Tree shows boxes connected by lines. The visual layout indicates parent-child
relationships between assemblies and detail parts.

HIERARCHY RULES:
- The TOPMOST box is the top-level assembly
- Lines connecting boxes show parent-child relationships
- A box BELOW and connected to another is its CHILD
- Boxes at the same level with the same parent are SIBLINGS

For this Drawing Tree, extract:
{
    "dt_drawing_number": "MER07540-DT",
    "top_assembly": "MER07540-001",
    "total_weight_lbs": 98.47,
    "nodes": [
        {
            "drawing_number": "MER07540-001",
            "title": "10 INCH VALVE",
            "parent": null,
            "children": ["MER07560-001", "MER07570-001", "MER07543-001"]
        },
        {
            "drawing_number": "MER07560-001",
            "title": "VALVE BODY SUB-ASSEMBLY, 10 INCH VALVE",
            "parent": "MER07540-001",
            "children": ["MER07563-001", "MER07550-001"]
        },
        {
            "drawing_number": "MER07563-001",
            "title": "BODY INSERT ASSEMBLY, 10 INCH VALVE",
            "parent": "MER07560-001",
            "children": ["MER07564-001", "MER07562-001"]
        }
    ]
}

EXTRACTION RULES:
1. Every node except top has exactly ONE parent
2. Follow visual connections carefully
3. Capture the COMPLETE title from each box
4. Drawing numbers follow pattern: MERnnnnn-nnn
5. If a box has no children, children array should be empty []

Return ONLY valid JSON."""

    @staticmethod
    def notes_extraction() -> str:
        """Extract notes section from MSFC drawing."""
        return """Extract the NOTES section from this MSFC engineering drawing.

Notes are typically numbered (1., 2., 3., etc.) and located on the left side or
bottom of the drawing.

Extract each note with its number:
{
    "notes": [
        {
            "number": 1,
            "text": "DRAWING PREPARED PER ASME Y14.41-2003, EXCEPT AS NOTED BELOW..."
        },
        {
            "number": 2,
            "text": "REMOVE ALL BURRS AND SHARP EDGES."
        },
        {
            "number": 3,
            "text": "MATERIAL: ALUMINUM ALLOY 7075-T6, UNS A97075, PER SAE AMS4124."
        }
    ]
}

Focus on notes that contain:
- Material specifications
- Process requirements
- Surface finish requirements
- Cleanliness requirements
- Identification/marking requirements

Return ONLY valid JSON."""

    @staticmethod
    def multi_material_detection() -> str:
        """Detect if drawing has multiple materials."""
        return """Analyze this drawing to determine if it contains MULTIPLE MATERIALS.

A drawing may have multiple materials when:
1. Main part material in title block PLUS installed inserts/hardware
2. Multiple material callouts in notes (e.g., "Item 1: Material A, Item 2: Material B")
3. Weldments with different base metals and filler metals
4. Assemblies showing constituent parts with different materials

For this drawing, identify:
{
    "is_multi_material": true/false,
    "primary_material": {
        "designation": "ALUMINUM ALLOY 7075-T6",
        "spec": "SAE AMS4124",
        "source": "title_block"
    },
    "additional_materials": [
        {
            "designation": "CRES 302/304",
            "spec": "AMS 5688",
            "source": "NASM33537 helical inserts",
            "quantity_indicator": "61 inserts total"
        }
    ],
    "material_mismatch_warning": "Parent is aluminum but inserts are stainless steel"
}

Return ONLY valid JSON."""
