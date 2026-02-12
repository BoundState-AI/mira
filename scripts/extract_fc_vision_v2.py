#!/usr/bin/env python3
"""Extract FC MAPTIS data using Claude vision API.

Uses same proven pattern as bok extractor_v10.
"""

from __future__ import annotations

import argparse
import base64
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

try:
    from anthropic import Anthropic
except ImportError:
    print("ERROR: pip install anthropic")
    sys.exit(1)

try:
    import fitz  # PyMuPDF
except ImportError:
    print("ERROR: pip install PyMuPDF")
    sys.exit(1)


FC_EXTRACTION_PROMPT = """Extract ALL fluid compatibility test rows from this MAPTIS table page.

Return JSON with this structure:
{
  "records": [
    {
      "material_code": 16,
      "designation": "POLYTETRAFLUOROETHYLENE (PTFE)",
      "report_number": "W21751-A",
      "rating": "A",
      "media": "HYDRAZINE (N2H4)"
    }
  ]
}

Field requirements:
- material_code: integer material code
- designation: FULL material name (e.g., "POLYTETRAFLUOROETHYLENE (PTFE)", "ALUMINUM ALLOY, 6061-T6")
- report_number: test report ID (e.g., "W21751-A")
- rating: A, B, X, or I
- media: chemical name with formula (e.g., "HYDRAZINE (N2H4)")

CRITICAL:
1. Skip the header row
2. Extract EVERY data row
3. Preserve exact material names with proper spacing
4. Material codes must be integers
5. Preserve chemical formulas in parentheses

Return ONLY valid JSON, no markdown fences."""


def pdf_to_base64_images(pdf_path: Path, dpi: int = 150) -> List[str]:
    """Convert PDF pages to base64-encoded PNG images."""
    doc = fitz.open(pdf_path)
    images = []

    for page in doc:
        # Render at specified DPI
        mat = fitz.Matrix(dpi / 72, dpi / 72)
        pix = page.get_pixmap(matrix=mat)

        # Convert to PNG bytes
        img_bytes = pix.tobytes("png")

        # Base64 encode
        b64 = base64.b64encode(img_bytes).decode("utf-8")
        images.append(b64)

    doc.close()
    return images


def call_vision(
    client: Anthropic,
    image_b64: str,
    prompt: str,
    model: str = "claude-sonnet-4-5-20250929",
    max_tokens: int = 8192,
) -> str:
    """Call Claude vision API with base64 image."""
    response = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        temperature=0,
        messages=[{
            "role": "user",
            "content": [
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": "image/png",
                        "data": image_b64,
                    },
                },
                {
                    "type": "text",
                    "text": prompt,
                },
            ],
        }],
    )
    return response.content[0].text


def parse_json_response(response_text: str) -> Dict[str, Any]:
    """Parse JSON from vision model response."""
    text = response_text.strip()

    # Remove markdown code blocks
    if text.startswith("```"):
        lines = text.split("\n")
        start = 1
        end = len(lines) - 1 if lines[-1].strip() == "```" else len(lines)
        text = "\n".join(lines[start:end])

    # Find JSON object
    start_idx = text.find("{")
    end_idx = text.rfind("}")

    if start_idx == -1 or end_idx == -1:
        # Try array
        start_idx = text.find("[")
        end_idx = text.rfind("]")
        if start_idx == -1 or end_idx == -1:
            return {"error": "No JSON found in response"}

    json_str = text[start_idx : end_idx + 1]

    try:
        return json.loads(json_str)
    except json.JSONDecodeError as e:
        return {"error": f"JSON parse error: {e}"}


def extract_fc_data(
    pdf_path: Path,
    output_path: Path,
    api_key: str,
    limit_pages: int = None,
) -> List[Dict]:
    """Extract FC data from PDF using vision API."""

    print(f"Converting PDF to images: {pdf_path}")
    images = pdf_to_base64_images(pdf_path)
    print(f"Rendered {len(images)} pages")

    if limit_pages:
        images = images[:limit_pages]
        print(f"Limited to first {limit_pages} pages")

    client = Anthropic(api_key=api_key)
    all_records = []
    errors = []

    for i, img_b64 in enumerate(images, 1):
        print(f"Page {i}/{len(images)}...", end=" ", flush=True)

        try:
            # Call vision API
            response_text = call_vision(client, img_b64, FC_EXTRACTION_PROMPT)

            # Parse JSON
            result = parse_json_response(response_text)

            if "error" in result:
                print(f"✗ Error: {result['error']}")
                errors.append((i, result['error']))
                continue

            # Extract records
            records = None
            if isinstance(result, list):
                records = result
            elif isinstance(result, dict):
                for key in ['records', 'tests', 'data', 'rows']:
                    if key in result:
                        records = result[key]
                        break

            if records:
                print(f"✓ {len(records)} records")
                all_records.extend(records)
            else:
                print(f"✗ No records found")
                errors.append((i, "No records in response"))

        except Exception as e:
            print(f"✗ Exception: {e}")
            errors.append((i, str(e)))

        # SAVE INCREMENTALLY - every 10 pages and on last page
        if i % 10 == 0 or i == len(images):
            with output_path.open('w', encoding='utf-8') as f:
                json.dump(all_records, f, indent=2)
            print(f"  💾 Saved {len(all_records)} records (checkpoint)")

    # Final save
    print(f"\nFinal save: {len(all_records)} records to {output_path}")
    with output_path.open('w', encoding='utf-8') as f:
        json.dump(all_records, f, indent=2)

    # Summary
    print(f"\n{'='*60}")
    print(f"Extraction Complete")
    print(f"{'='*60}")
    print(f"Total records: {len(all_records)}")
    print(f"Pages processed: {len(images)}")
    print(f"Errors: {len(errors)}")

    if errors:
        print(f"\nErrors:")
        for page, error in errors[:10]:
            print(f"  Page {page}: {error}")

    if all_records:
        print(f"\nFirst 3 records:")
        for rec in all_records[:3]:
            print(f"  {rec}")

    return all_records


def main():
    parser = argparse.ArgumentParser(description='Extract FC MAPTIS using vision API')
    parser.add_argument('--pdf', type=Path,
                        default=Path('C:/BoundState/docs/FC maptis.pdf'),
                        help='Path to FC MAPTIS PDF')
    parser.add_argument('--output', type=Path,
                        default=Path('C:/BoundState/temp/fc_vision_v2.json'),
                        help='Output JSON file')
    parser.add_argument('--limit', type=int, default=None,
                        help='Limit to first N pages')
    parser.add_argument('--api-key', type=str, default=None,
                        help='Anthropic API key (or set ANTHROPIC_API_KEY env var)')

    args = parser.parse_args()

    if not args.pdf.exists():
        print(f"Error: PDF not found at {args.pdf}")
        return 1

    import os
    api_key = args.api_key or os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("Error: No API key provided. Use --api-key or set ANTHROPIC_API_KEY")
        return 1

    args.output.parent.mkdir(parents=True, exist_ok=True)

    extract_fc_data(args.pdf, args.output, api_key, limit_pages=args.limit)

    return 0


if __name__ == '__main__':
    sys.exit(main())
