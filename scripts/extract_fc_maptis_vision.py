#!/usr/bin/env python3
"""Extract FC MAPTIS data using existing vision infrastructure.

Reuses VisionClient from MIUL v3 for proven reliability.
"""

from __future__ import annotations

import argparse
import base64
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mira.miul.v3.extract import VisionClient, pdf_to_images


FC_EXTRACTION_PROMPT = """Extract ALL fluid compatibility test rows from this table page.

Return a JSON array where each object has:
- material_code (integer): e.g., 16, 128
- designation (string): full material name with proper spacing, e.g., "POLYTETRAFLUOROETHYLENE (PTFE)"
- report_number (string): test report ID, e.g., "W21751-A"
- rating (string): A, B, X, or I
- media (string): chemical name with formula, e.g., "HYDRAZINE (N2H4)"

IMPORTANT:
1. Skip the header row "Mtrl. Code | Material Designation | Report Number | Fluid Compatibility Rating | Media"
2. Extract EVERY data row
3. Keep full material names with correct spacing
4. Material codes must be integers
5. Preserve chemical formulas in parentheses

Example output:
[
  {"material_code": 16, "designation": "POLYTETRAFLUOROETHYLENE (PTFE)", "report_number": "W21751-A", "rating": "A", "media": "HYDRAZINE (N2H4)"},
  {"material_code": 16, "designation": "POLYTETRAFLUOROETHYLENE (PTFE)", "report_number": "W21751-B", "rating": "A", "media": "MONOMETHYLHYDRAZINE (MMH)"}
]

Return ONLY valid JSON array, no other text."""


def extract_fc_data(pdf_path: Path, output_path: Path, limit_pages: int = None):
    """Extract FC data using vision API - same pattern as MIUL v4."""

    print(f"Converting PDF to base64 images: {pdf_path}")
    b64_images = pdf_to_images(pdf_path)  # Returns List[str] of base64 PNGs

    if limit_pages:
        b64_images = b64_images[:limit_pages]
        print(f"Limited to first {limit_pages} pages")

    print(f"Processing {len(b64_images)} pages with vision API...")

    client = VisionClient()
    all_records = []
    errors = []

    for i, img_b64 in enumerate(b64_images, 1):
        print(f"Page {i}/{len(b64_images)}")

        try:
            # Call vision API (returns parsed dict/list)
            result = client.call_vision(
                image_b64=img_b64,
                prompt=FC_EXTRACTION_PROMPT
            )

            # Handle different response formats
            records = None
            if isinstance(result, list):
                # Direct array response
                records = result
            elif isinstance(result, dict):
                # Check for records/tests/data key
                for key in ['records', 'tests', 'data', 'rows']:
                    if key in result:
                        records = result[key]
                        break
                if records is None and 'error' in result:
                    print(f"  ✗ Error: {result['error']}")
                    errors.append((i, result['error']))
                    continue

            if records:
                print(f"  ✓ Extracted {len(records)} records")
                all_records.extend(records)
            else:
                print(f"  ✗ No records found (response keys: {list(result.keys()) if isinstance(result, dict) else 'not a dict'})")
                errors.append((i, f"No records found in response"))

        except Exception as e:
            print(f"  ✗ Exception: {e}")
            errors.append((i, str(e)))

    # Save results
    print(f"\nSaving {len(all_records)} records to {output_path}")
    with output_path.open('w', encoding='utf-8') as f:
        json.dump(all_records, f, indent=2)

    # Summary
    print(f"\n{'='*60}")
    print(f"Extraction Complete")
    print(f"{'='*60}")
    print(f"Total records extracted: {len(all_records)}")
    print(f"Pages processed: {len(b64_images)}")
    print(f"Errors: {len(errors)}")

    if errors:
        print(f"\nErrors by page:")
        for page, error in errors[:10]:  # Show first 10
            print(f"  Page {page}: {error}")

    print(f"\nOutput saved to: {output_path}")

    # Show samples
    if all_records:
        print(f"\nFirst 5 records:")
        for rec in all_records[:5]:
            print(f"  {rec}")

    return all_records


def main():
    parser = argparse.ArgumentParser(description='Extract FC MAPTIS data using vision API')
    parser.add_argument('--pdf', type=Path,
                        default=Path('C:/BoundState/docs/FC maptis.pdf'),
                        help='Path to FC MAPTIS PDF')
    parser.add_argument('--output', type=Path,
                        default=Path('C:/BoundState/temp/fc_vision_extracted.json'),
                        help='Output JSON file')
    parser.add_argument('--limit', type=int, default=None,
                        help='Limit to first N pages (for testing)')

    args = parser.parse_args()

    if not args.pdf.exists():
        print(f"Error: PDF not found at {args.pdf}")
        return 1

    args.output.parent.mkdir(parents=True, exist_ok=True)

    extract_fc_data(args.pdf, args.output, limit_pages=args.limit)

    return 0


if __name__ == '__main__':
    sys.exit(main())
