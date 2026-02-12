#!/usr/bin/env python3
"""Vision-based FC MAPTIS PDF extractor using Claude API.

Uses the same proven pattern as MIUL v4 extraction.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mira.miul.v3.extract import VisionClient, pdf_to_images


EXTRACTION_PROMPT = """You are extracting fluid compatibility test data from a MAPTIS database table.

Extract ALL rows from this table page into a JSON array. Each row should have:
- material_code: integer (e.g., 16, 128, 1023)
- designation: string (full material name, e.g., "POLYTETRAFLUOROETHYLENE (PTFE)")
- report_number: string (e.g., "W21751-A")
- rating: string (A, B, X, or I)
- media: string (chemical name, e.g., "HYDRAZINE (N2H4)")

IMPORTANT:
1. Extract EVERY row from the table, including the header if present
2. Skip the header row (Mtrl. Code, Material Designation, etc.)
3. For designation, include the FULL material name with proper spacing
4. Material codes are always integers
5. Ratings are single letters: A, B, X, or I
6. Media should include the chemical formula in parentheses

Return ONLY a JSON array of objects. Example:
[
  {
    "material_code": 16,
    "designation": "POLYTETRAFLUOROETHYLENE (PTFE)",
    "report_number": "W21751-A",
    "rating": "A",
    "media": "HYDRAZINE (N2H4)"
  },
  {
    "material_code": 16,
    "designation": "POLYTETRAFLUOROETHYLENE (PTFE)",
    "report_number": "W21751-B",
    "rating": "A",
    "media": "MONOMETHYLHYDRAZINE (MMH)"
  }
]

Return ONLY valid JSON, no explanatory text."""


def extract_fc_from_pdf_vision(pdf_path: Path, output_path: Path) -> list[dict]:
    """Extract FC data using vision API.

    Returns:
        List of FC test records
    """
    print(f"Converting PDF to images: {pdf_path}")
    image_files = pdf_to_images(pdf_path)
    print(f"Generated {len(image_files)} page images")

    client = VisionClient()
    all_records = []

    for i, image_path_str in enumerate(image_files, 1):
        image_path = Path(image_path_str) if isinstance(image_path_str, str) else image_path_str
        print(f"Processing page {i}/{len(image_files)}: {image_path.name}")

        try:
            # Extract data from this page
            response = client.extract_with_vision(
                image_path=str(image_path),
                prompt=EXTRACTION_PROMPT
            )

            # Parse JSON response
            page_records = client.parse_json_response(response)

            if isinstance(page_records, list):
                print(f"  Extracted {len(page_records)} records from page {i}")
                all_records.extend(page_records)
            else:
                print(f"  Warning: Expected list, got {type(page_records)}")

        except Exception as e:
            print(f"  Error processing page {i}: {e}")
            continue

    # Save all records to JSON
    print(f"\nSaving {len(all_records)} total records to {output_path}")
    with output_path.open('w', encoding='utf-8') as f:
        json.dump(all_records, f, indent=2)

    return all_records


def main():
    parser = argparse.ArgumentParser(description='Extract FC data using vision API')
    parser.add_argument('--pdf', type=Path,
                        default=Path('C:/BoundState/docs/FC maptis.pdf'),
                        help='Path to FC MAPTIS PDF')
    parser.add_argument('--output', type=Path,
                        default=Path('C:/BoundState/temp/fc_vision_extract.json'),
                        help='Output JSON file')

    args = parser.parse_args()

    if not args.pdf.exists():
        print(f"Error: PDF not found at {args.pdf}")
        return 1

    args.output.parent.mkdir(parents=True, exist_ok=True)

    print("Starting vision-based FC extraction")
    print(f"PDF: {args.pdf}")
    print(f"Output: {args.output}")

    records = extract_fc_from_pdf_vision(args.pdf, args.output)

    print(f"\nExtraction complete!")
    print(f"Total records: {len(records)}")
    print(f"\nSample records:")
    for record in records[:5]:
        print(f"  {record}")

    return 0


if __name__ == '__main__':
    sys.exit(main())
