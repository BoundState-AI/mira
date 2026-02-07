#!/usr/bin/env python3
"""
Module: Haiku Bom Extractor Old
Purpose: Strip NASA-identifying info before sending to external LLM.

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
import os
import sys
from pathlib import Path
from typing import Dict, List, Any, Optional
from datetime import datetime
import uuid

# Add project root to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

# Try to load .env file
try:
    from dotenv import load_dotenv
    env_paths = [
        Path(__file__).parent.parent / '.env',
        Path(__file__).parent / '.env',
        Path('C:/BoundState/.env'),
    ]
    for env_path in env_paths:
        if env_path.exists():
            load_dotenv(env_path)
            print(f"Loaded .env from: {env_path}")
            break
except ImportError:
    pass

import re
import PyPDF2
import pandas as pd
from anthropic import Anthropic

# Import material code lookup service - updated for boundstate_mira
try:
    from boundstate_mira.api.material_code_lookup import MaterialCodeLookupService, get_lookup_service
    MATERIAL_LOOKUP_AVAILABLE = True
except ImportError:
    MATERIAL_LOOKUP_AVAILABLE = False
    MaterialCodeLookupService = None
    get_lookup_service = None


def anonymize_for_extraction(text: str, filename: str) -> tuple[str, dict]:
    """
    Strip NASA-identifying info before sending to external LLM.

    Removes organizational headers and masks drawing numbers while preserving
    the parts list structure needed for extraction.

    Returns:
        tuple: (anonymized_text, redaction_map for restoring)
    """
    redaction_map = {}

    # Remove NASA organizational headers
    nasa_patterns = [
        (r'GEORGE\s+C\.?\s+MARSHALL', '[ORG]'),
        (r'MARSHALL\s+SPACE\s+FLIGHT\s+CENTER', '[ORG]'),
        (r'SPACE\s+FLIGHT\s+CENTER', '[ORG]'),
        (r'NATIONAL\s+AERONAUTICS.*?ADMINISTRATION', '[ORG]'),
        (r'HUNTSVILLE,?\s*ALABAMA', '[LOC]'),
        (r'\bNASA\b', '[ORG]'),
        (r'\bMSFC\b', '[ORG]'),
    ]

    for pattern, replacement in nasa_patterns:
        text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)

    # Mask NASA MSFC CAGE code (339B2)
    text = re.sub(r'\b339B2\b', '[CAGE]', text)

    # Mask MER drawing numbers but keep structure for context
    # Store mapping to restore later
    mer_numbers = re.findall(r'(MER\d{5}-\d{3})', text, re.IGNORECASE)
    for i, mer_num in enumerate(set(mer_numbers)):
        masked = f'DRW-{i+1:03d}'
        redaction_map[masked] = mer_num.upper()
        text = re.sub(re.escape(mer_num), masked, text, flags=re.IGNORECASE)

    # Also anonymize filename
    anon_filename = re.sub(r'MER\d{5}-\d{3}', 'DRW-XXX', filename, flags=re.IGNORECASE)
    anon_filename = re.sub(r'339B2', '[CAGE]', anon_filename)

    return text, redaction_map, anon_filename


class HaikuBOMExtractor:
    """Extract parts and materials from engineering drawings using Claude Haiku."""

    def __init__(self, api_key: Optional[str] = None):
        """Initialize the Haiku extractor."""
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not self.api_key:
            print("ERROR: ANTHROPIC_API_KEY not set")
            print("Options:")
            print("  1. Pass --api-key sk-ant-... on command line")
            print("  2. Set ANTHROPIC_API_KEY environment variable")
            print("  3. Add to C:\\BoundState\\.env file")
            raise ValueError("ANTHROPIC_API_KEY not set")

        self.client = Anthropic(api_key=self.api_key)
        self.model = "claude-3-haiku-20240307"

    def extract_text_from_pdf(self, pdf_path: Path) -> str:
        """Extract text from PDF file."""
        with open(pdf_path, 'rb') as f:
            reader = PyPDF2.PdfReader(f)
            text = ""
            for page in reader.pages:
                page_text = page.extract_text()
                if page_text:
                    text += page_text + "\n"
        return text

    def extract_parts_list(self, pdf_text: str, filename: str) -> List[Dict[str, Any]]:
        """
        Use Haiku to extract parts list from drawing text.

        Returns list of parts with:
        - QTY: quantity required
        - FIND_NO: find number (item reference)
        - PART_NUMBER: part/drawing number
        - CAGE_CODE: commercial and government entity code (if present)
        - DESCRIPTION: part description/nomenclature
        - DESIGNATION: material alloy/name (e.g., "A286 CRES", "INCONEL 718")
        - MATERIAL_SPEC: specification (e.g., "AMS 5737", "ASTM A564")
        - MATERIAL_FORM: form (e.g., "BAR", "SHEET", "PLATE")
        """
        # Anonymize NASA-identifying info before sending to external API
        anon_text, redaction_map, anon_filename = anonymize_for_extraction(pdf_text, filename)

        # Short-circuit drawing trees (-DT files show hierarchy only, no BOM)
        # Short-circuit ICD files (Interface Control Documents have no BOM)
        filename_upper = filename.upper()
        if "DRAWING TREE" in anon_text.upper() or "-DT" in filename_upper:
            return []
        if "-ICD" in filename_upper or "INTERFACE CONTROL" in anon_text.upper():
            return []

        # Focus on the parts-list region (if present) and allow a larger context window.
        # If the table text is "smushed" into one line, inject newlines before each row pattern.
        parts_header = re.search(r'ENGINEERING\s+PARTS\s+LIST', anon_text, flags=re.IGNORECASE)
        max_chars = 16000  # Haiku can handle this comfortably; keeps the full table
        if parts_header:
            start = max(0, parts_header.start() - 500)  # include a little lead-in for context
            end = min(len(anon_text), parts_header.start() + max_chars)
            parts_block = anon_text[start:end]

            # Add a newline before each row-like sequence: QTY FIND_NO PART_NUMBER ...
            row_pattern = re.compile(r'(?<!\n)(?=\b(?:AR|\d+)\s+\d+\s+[A-Z0-9])')
            parts_block = row_pattern.sub('\n', parts_block)
            text_sample = parts_block
        else:
            text_sample = anon_text[:max_chars]

        prompt = f"""You are extracting parts list data from an aerospace engineering drawing.

CRITICAL: First determine the DRAWING TYPE:

1. ASSEMBLY DRAWINGS (have parts lists):
   - Title contains "ASSEMBLY"
   - Have ENGINEERING PARTS LIST table with QTY, FIND NO, PART NUMBER columns
   - Multiple parts called out with find numbers (1, 2, 3...)
   - Parts have BOTH qty values AND material specifications
   - Extract all parts from the parts list table

2. DETAIL DRAWINGS (NO parts list - define ONE machined/fabricated part):
   - Title is a single part name like "SHAFT", "HOUSING", "BRACKET"
   - Have dimensions, tolerances, GD&T callouts
   - Have "MATERIAL:" note specifying material (e.g., "MATERIAL: A286 CRES")
   - Have "USED ON NEXT ASSY" reference to parent assembly
   - DO NOT have ENGINEERING PARTS LIST table
   - For these: return ONLY ONE part - the drawing itself with material from title block

3. DRAWING TREE (-DT files):
   - Show assembly hierarchy/structure only
   - List part numbers WITHOUT qty values or material specs
   - Used for documentation, NOT for parts extraction
   - Return empty array []

4. ICD DRAWINGS (Interface Control Documents):
   - May have interface requirements but NOT a parts list
   - Return empty array []

CRITICAL: If parts are listed WITHOUT qty values or materials, this is likely a DRAWING TREE - return []

EXTRACTION RULES for ASSEMBLY drawings:
- Extract ALL parts from ENGINEERING PARTS LIST table - DO NOT MISS ANY FIND NUMBERS
- Part number formats vary widely:
  * NASA MER drawings: DRW-001, DRW-002, MER07543-001
  * NAS/AN/MS standards: NAS1351N4-20, AN4-10, MS21209C2010
  * McMaster-Carr: 2934T6, 97345A624, 95878A310, 9713K64
  * Smalley retaining rings: WSM-137-C86, WHM-244-S86
  * Vendor parts: AS4307K04, F-400521-04
- QTY can be a number (1, 2, 4) or "AR" (As Required)
- LUBRICANTS: If QTY is "AR" and find_no references a note (like "5."), extract it with description "LUBRICANT" and the note reference as part_number
- Material often at END of description: "SCREW, SHOULDER, 316 SST" -> material is "316 SST"
- CAGE codes are 4-5 alphanumeric (may show as [CAGE])

MATERIAL PARSING (CRITICAL - separate correctly):
The material string must be SPLIT into THREE fields:
  - "designation": The ALLOY NAME only (A286, INCONEL 718, 316L, BRONZE, TITANIUM 6AL-4V)
  - "material_spec": The SPECIFICATION only (AMS 5737, ASTM A564, AMS 5662, MIL-S-7720)
  - "material_form": The FORM only (BAR, SHEET, PLATE, TUBE, WIRE, FORGING)

PARSING EXAMPLES:
  "A286, UNS S66286, PER AMS 5737" → designation="A286", material_spec="AMS 5737", material_form=""
  "INCONEL 718 PER AMS 5662 BAR" → designation="INCONEL 718", material_spec="AMS 5662", material_form="BAR"
  "316L CRES PER ASTM A276" → designation="316L CRES", material_spec="ASTM A276", material_form=""
  "7075-T6 ALUMINUM PLATE" → designation="7075-T6 ALUMINUM", material_spec="", material_form="PLATE"
  "BRONZE, C93200" → designation="BRONZE C93200", material_spec="", material_form=""
  "416 SST BAR" → designation="416 SST", material_spec="", material_form="BAR"

IGNORE these in parsing:
  - UNS numbers (S66286, N07718, etc.) - do NOT put in designation
  - "PER" prefix before specs - it's just a connector word

EXTRACTION RULES for DETAIL drawings:
- Return exactly ONE part: the drawing number itself
- Get material from "MATERIAL:" note in drawing (e.g., "A286 CRES", "7075-T6 AL")
- Get description from drawing title

Source file: {anon_filename}

DRAWING TEXT:
{text_sample}

Return JSON array:
- For ASSEMBLY: array of all parts from parts list
- For DETAIL: array with ONE part (the drawing itself)
- For ICD/unknown: empty array []

Format (include ALL find numbers - do not skip any):
[
  {{"qty": "1", "find_no": "1", "part_number": "DRW-001", "cage_code": "[CAGE]", "description": "SHAFT ASSEMBLY, VALVE", "designation": "", "material_spec": "", "material_form": ""}},
  {{"qty": "2", "find_no": "2", "part_number": "98380A542", "cage_code": "0KVE6", "description": "PIN, DOWEL", "designation": "416 SST", "material_spec": "", "material_form": "BAR"}},
  {{"qty": "4", "find_no": "5", "part_number": "2934T6", "cage_code": "0KVE6", "description": "BEARING, FLANGED SLEEVE", "designation": "BRONZE", "material_spec": "", "material_form": ""}},
  {{"qty": "1", "find_no": "6", "part_number": "WSM-137-C86", "cage_code": "51814", "description": "RETAINING RING, EXTERIOR", "designation": "A286", "material_spec": "AMS 5737", "material_form": ""}},
  {{"qty": "AR", "find_no": "14", "part_number": "NOTE-5", "cage_code": "", "description": "LUBRICANT, LOX COMPATIBLE", "designation": "", "material_spec": "", "material_form": ""}}
]

For DETAIL drawing (ONE part only):
[
 {{"qty": "1", "find_no": "1", "part_number": "DRW-001", "cage_code": "[CAGE]", "description": "LOWER, OFFSET ROTARY SHAFT, 10 INCH VALVE", "designation": "A286 CRES", "material_spec": "AMS 5737", "material_form": "BAR"}}
]

IMPORTANT: Table text may be condensed. Look for EVERY find number (1, 2, 3...13, 14 etc). Do NOT skip McMaster parts (2934T6), Smalley rings (WSM-xxx), or lubricants (AR qty with note reference).

Return ONLY the JSON array, no markdown, no explanation."""

        try:
            message = self.client.messages.create(
                model=self.model,
                max_tokens=4000,
                temperature=0,
                messages=[{"role": "user", "content": prompt}]
            )

            response_text = message.content[0].text.strip()
            parts = self._parse_json_array(response_text)

            # Restore original drawing numbers from redaction_map
            for part in parts:
                pn = part.get('part_number', '')
                # Restore masked drawing numbers (DRW-001 -> MER07560-001)
                if pn in redaction_map:
                    part['part_number'] = redaction_map[pn]
                # Also restore CAGE codes
                cage = part.get('cage_code', '')
                if cage == '[CAGE]':
                    part['cage_code'] = '339B2'  # NASA MSFC CAGE

            return parts

        except Exception as e:
            print(f"  Haiku API error for {filename}: {e}")
            return []

    def extract_drawing_info(self, pdf_text: str, filename: str) -> Dict[str, Any]:
        """
        Extract drawing title block info (drawing number, title, revision, etc.)
        """
        # Anonymize NASA-identifying info before sending to external API
        anon_text, redaction_map, anon_filename = anonymize_for_extraction(pdf_text, filename)

        text_sample = anon_text[:4000]

        prompt = f"""Extract drawing title block information from this engineering drawing.

Look for:
- Drawing number (format like DRW-001, DRW-002)
- Drawing title/name (like "SHAFT ASSEMBLY, VALVE")
- Revision letter/number
- Drawing type (ASSEMBLY, DETAIL, SCHEMATIC, INSERT)
- Parent drawing reference (if this drawing is called out by another)
- Material from title block (if this is a detail drawing with material specified)

DRAWING TEXT:
{text_sample}

Return ONLY a JSON object:
{{
  "drawing_number": "the drawing number",
  "title": "drawing title",
  "revision": "revision letter or number",
  "drawing_type": "ASSEMBLY or DETAIL or SCHEMATIC or INSERT",
  "parent_drawing": "parent drawing number if referenced, or null",
  "title_block_material": "material from title block if present, or null"
}}

Return ONLY the JSON, no markdown, no explanation."""

        try:
            message = self.client.messages.create(
                model=self.model,
                max_tokens=500,
                temperature=0,
                messages=[{"role": "user", "content": prompt}]
            )

            response_text = message.content[0].text.strip()
            result = self._parse_json_object(response_text)

            if result:
                # Restore original drawing numbers from redaction_map
                drw_num = result.get('drawing_number', '')
                if drw_num in redaction_map:
                    result['drawing_number'] = redaction_map[drw_num]

                parent_drw = result.get('parent_drawing', '')
                if parent_drw and parent_drw in redaction_map:
                    result['parent_drawing'] = redaction_map[parent_drw]

                result['source_file'] = filename

            return result or {'source_file': filename, 'drawing_number': None}

        except Exception as e:
            print(f"  Haiku API error for drawing info {filename}: {e}")
            return {'source_file': filename, 'drawing_number': None}

    def _parse_json_array(self, response_text: str) -> List[Dict[str, Any]]:
        """Parse JSON array from Haiku response."""
        import re

        # Remove markdown code blocks
        if "```" in response_text:
            parts = response_text.split("```")
            for part in parts:
                part = part.strip()
                if part.startswith("json"):
                    part = part[4:].strip()
                if part.startswith("["):
                    try:
                        return json.loads(part)
                    except json.JSONDecodeError:
                        continue

        # Try direct parse
        try:
            return json.loads(response_text)
        except json.JSONDecodeError:
            pass

        # Find array in text
        match = re.search(r'\[[\s\S]*\]', response_text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                pass

        return []

    def _parse_json_object(self, response_text: str) -> Optional[Dict[str, Any]]:
        """Parse JSON object from Haiku response."""
        import re

        # Remove markdown code blocks
        if "```" in response_text:
            parts = response_text.split("```")
            for part in parts:
                part = part.strip()
                if part.startswith("json"):
                    part = part[4:].strip()
                if part.startswith("{"):
                    try:
                        return json.loads(part)
                    except json.JSONDecodeError:
                        continue

        # Try direct parse
        try:
            return json.loads(response_text)
        except json.JSONDecodeError:
            pass

        # Find object in text
        match = re.search(r'\{[\s\S]*\}', response_text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                pass

        return None

    def process_directory(self, directory: Path) -> Dict[str, Any]:
        """
        Process all PDFs in directory and create base MIUL data.

        Returns:
            Dict with 'drawings' (drawing info) and 'parts' (all extracted parts)
        """
        # Use set to dedupe (Windows is case-insensitive)
        pdf_files = list(set(directory.glob("*.pdf")) | set(directory.glob("*.PDF")))
        pdf_files.sort(key=lambda p: p.name.lower())  # Sort for consistent ordering
        print(f"Found {len(pdf_files)} PDF files in {directory}")

        all_parts = []
        all_drawings = []

        for i, pdf_file in enumerate(pdf_files, 1):
            print(f"\n[{i}/{len(pdf_files)}] Processing: {pdf_file.name}")

            try:
                # Extract text from PDF
                text = self.extract_text_from_pdf(pdf_file)
                if not text.strip():
                    print(f"  Warning: No text extracted from {pdf_file.name}")
                    continue

                # Extract drawing info
                drawing_info = self.extract_drawing_info(text, pdf_file.name)
                all_drawings.append(drawing_info)
                print(f"  Drawing: {drawing_info.get('drawing_number', 'N/A')} - {drawing_info.get('title', 'N/A')[:40]}")

                # Extract parts list
                parts = self.extract_parts_list(text, pdf_file.name)
                if parts:
                    # Add source file to each part
                    for part in parts:
                        part['source_file'] = pdf_file.name
                        part['source_drawing'] = drawing_info.get('drawing_number', '')
                    all_parts.extend(parts)
                    print(f"  Extracted {len(parts)} parts")

                    # Show first few
                    for p in parts[:3]:
                        mat = f" [{p.get('material', '')}]" if p.get('material') else ""
                        print(f"    {p.get('find_no', '?'):>3}: {p.get('part_number', '?'):<20} {p.get('description', '?')[:30]}{mat}")
                    if len(parts) > 3:
                        print(f"    ... and {len(parts) - 3} more")
                else:
                    print(f"  No parts list found (might be a detail drawing)")

            except Exception as e:
                print(f"  Error processing {pdf_file.name}: {e}")

        return {
            'drawings': all_drawings,
            'parts': all_parts,
            'summary': {
                'total_files': len(pdf_files),
                'total_drawings': len(all_drawings),
                'total_parts': len(all_parts),
                'parts_with_material': sum(1 for p in all_parts if p.get('material')),
                'extraction_date': datetime.now().isoformat()
            }
        }

    def deduplicate_parts(self, parts: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Intelligently deduplicate parts extracted from multiple drawing sheets.
        """
        import re

        # Group parts by (parent_drawing, part_number)
        part_groups = {}

        for part in parts:
            parent = part.get('source_drawing', '') or ''
            pn = part.get('part_number', '') or ''
            src_file = part.get('source_file', '') or ''

            # Skip empty part numbers
            if not pn.strip():
                continue

            key = (parent, pn)

            if key not in part_groups:
                part_groups[key] = []
            part_groups[key].append(part)

        # Select best record from each group
        deduped = []
        for (parent, pn), candidates in part_groups.items():
            if len(candidates) == 1:
                deduped.append(candidates[0])
            else:
                # Score each candidate - prefer -DT files
                def score_candidate(p):
                    score = 0
                    src_file = p.get('source_file', '')

                    # Strong preference for -DT (Detail Tree) files
                    if '-DT' in src_file.upper():
                        score += 100

                    # Prefer records with material info
                    if p.get('material', '').strip():
                        score += 10

                    # Prefer records with cage code
                    if p.get('cage_code', '').strip():
                        score += 5

                    # Prefer longer descriptions
                    score += len(p.get('description', '')) / 100

                    return score

                best = max(candidates, key=score_candidate)
                deduped.append(best)

        return deduped

    def create_base_miul(self, data: Dict[str, Any], output_path: Path):
        """
        Create base MIUL Excel file from extracted data per JSC 27301F Section 4.2.1.
        """
        raw_parts = data.get('parts', [])

        # Deduplicate parts intelligently
        parts = self.deduplicate_parts(raw_parts)
        print(f"\nDeduplication: {len(raw_parts)} raw -> {len(parts)} unique (removed {len(raw_parts)-len(parts)} duplicates)")
        if not parts:
            print("No parts to export")
            return

        # Create DataFrame
        df = pd.DataFrame(parts)

        # Rename columns to MIUL format per JSC 27301F Section 4.2.1
        column_map = {
            'find_no': 'Line Number',                    # (25)
            'part_number': 'Detail Drawing',             # (1)
            'description': 'Document Title',             # (23)
            'designation': 'Designation',                # (7) Material designation/alloy
            'material': 'Designation',                   # (7) Legacy field name support
            'material_spec': 'Material Specification',   # (8)
            'material_form': 'Material Form',            # (5)
            'qty': '_qty_temp',                          # Not in JSC 27301F
            'cage_code': '_cage_temp',                   # Not in JSC 27301F
            'source_drawing': 'Next Assembly',           # (2)
            'source_file': '_source_temp'                # Not in JSC 27301F
        }

        df = df.rename(columns=column_map)

        # Add MAPTIS tree columns
        df['Index'] = range(1, len(df) + 1)
        df['Parent'] = 0

        # Ensure columns exist and look up MAPTIS material codes for each designation
        if 'Material Code' not in df.columns:
            df['Material Code'] = ''
        if 'Material Specification' not in df.columns:
            df['Material Specification'] = ''
        if 'Material Form' not in df.columns:
            df['Material Form'] = ''
        if 'Designation' not in df.columns:
            df['Designation'] = ''

        if MATERIAL_LOOKUP_AVAILABLE:
            print("\nLooking up MAPTIS material codes...")
            lookup_service = MaterialCodeLookupService()
            lookup_stats = {'found': 0, 'not_found': 0, 'empty': 0}

            try:
                for idx, row in df.iterrows():
                    designation = row.get('Designation', '')
                    if not designation or pd.isna(designation) or str(designation).strip() == '':
                        lookup_stats['empty'] += 1
                        continue

                    # Look up the material code
                    try:
                        matches = lookup_service.lookup_by_designation(str(designation))
                        if matches:
                            # Take the best match (highest confidence)
                            best_match = matches[0]
                            df.at[idx, 'Material Code'] = best_match.material_code
                            df.at[idx, 'Material Specification'] = best_match.specification or ''
                            lookup_stats['found'] += 1
                            print(f"  [{best_match.confidence.upper()}] '{designation}' -> {best_match.material_code} ({best_match.designation[:40]})")
                        else:
                            lookup_stats['not_found'] += 1
                            print(f"  [MISS] '{designation}' - no MAPTIS match")
                    except Exception as e:
                        lookup_stats['not_found'] += 1
                        print(f"  [ERROR] '{designation}' - {e}")

                print(f"\nMaterial code lookup complete:")
                print(f"  Found: {lookup_stats['found']}")
                print(f"  Not found: {lookup_stats['not_found']}")
                print(f"  Empty designation: {lookup_stats['empty']}")
            finally:
                lookup_service.close()
        else:
            print("\nWARNING: Material lookup service not available - Material Code column will be empty")

        # Add rating columns per JSC 27301F (32) - expanded to individual ratings
        for rating in ['FLAM', 'SCC', 'CORR', 'TVS', 'TOX', 'FS']:
            df[rating] = ''

        # Add Remarks column (33)
        df['Remarks'] = ''

        # Drop temporary columns not in JSC 27301F
        temp_cols = [c for c in df.columns if c.startswith('_') and c.endswith('_temp')]
        df = df.drop(columns=temp_cols, errors='ignore')

        # Reorder columns per JSC 27301F Section 4.2.1
        column_order = [
            'Index', 'Parent',
            'Detail Drawing', 'Next Assembly',
            'Material Code', 'Designation', 'Material Specification', 'Material Form',
            'Document Title', 'Line Number',
            'FLAM', 'SCC', 'CORR', 'TVS', 'TOX', 'FS',
            'Remarks'
        ]

        # Only include columns that exist
        columns = [c for c in column_order if c in df.columns]
        df = df[columns]

        # Save to Excel
        with pd.ExcelWriter(output_path, engine='openpyxl') as writer:
            df.to_excel(writer, sheet_name='MIUL', index=False)

            # Also save drawings info
            drawings_df = pd.DataFrame(data.get('drawings', []))
            if not drawings_df.empty:
                drawings_df.to_excel(writer, sheet_name='Drawings', index=False)

            # Summary sheet
            summary_df = pd.DataFrame([data.get('summary', {})])
            summary_df.to_excel(writer, sheet_name='Summary', index=False)

        print(f"\nBase MIUL saved to: {output_path}")
        print(f"  Total parts: {len(df)}")
        print(f"  Parts with designations: {len(df[df['Designation'].str.len() > 0])}")
        print(f"  Parts with material codes: {len(df[df['Material Code'].str.len() > 0])}")

        return df


def main():
    """Main entry point."""
    import argparse

    parser = argparse.ArgumentParser(description="Haiku BOM Extractor - Base MIUL Generator")
    parser.add_argument("directory", help="Directory containing PDF drawings")
    parser.add_argument("--api-key", help="Anthropic API key (or set ANTHROPIC_API_KEY env var)")
    args = parser.parse_args()

    directory = Path(args.directory)
    if not directory.exists():
        print(f"Directory not found: {directory}")
        sys.exit(1)

    print("="*70)
    print("HAIKU BOM EXTRACTOR - Base MIUL Generator")
    print("="*70)
    print(f"Directory: {directory}")
    print()

    # Initialize extractor with optional API key
    api_key = args.api_key or os.environ.get("ANTHROPIC_API_KEY")
    extractor = HaikuBOMExtractor(api_key=api_key)

    # Process directory
    data = extractor.process_directory(directory)

    # Create base MIUL
    output_file = directory / "base_miul.xlsx"
    extractor.create_base_miul(data, output_file)

    # Also save raw JSON for reference
    json_file = directory / "haiku_extraction_results.json"
    with open(json_file, 'w') as f:
        json.dump(data, f, indent=2)
    print(f"Raw JSON saved to: {json_file}")

    print("\n" + "="*70)
    print("EXTRACTION COMPLETE")
    print("="*70)
    print(f"Total drawings processed: {data['summary']['total_drawings']}")
    print(f"Total parts extracted: {data['summary']['total_parts']}")
    print(f"Parts with material specified: {data['summary']['parts_with_material']}")


if __name__ == "__main__":
    main()
