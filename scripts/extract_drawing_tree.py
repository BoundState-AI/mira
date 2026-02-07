#!/usr/bin/env python3
"""
Extract Drawing Tree hierarchy from a DT PDF using Claude Vision.

This script:
1. Sends the DT PDF to Claude Vision API
2. Extracts the hierarchy using level-by-level methodology
3. Validates and self-corrects up to 3 iterations
4. Outputs JSON in flat format (compatible with MIUL Builder and DT Editor)

Usage:
    python extract_drawing_tree.py <dt_pdf_path> [--output <output_path>]

Example:
    python extract_drawing_tree.py "C:\\path\\to\\MER07540-DT.DRW_-.6.pdf"

Output:
    Creates <input_name>.dt_hierarchy.json in the same directory as the PDF

BoundState AI 2025
"""

import sys
import os
import json
import argparse
import logging
from pathlib import Path

# Add BoundState to path
sys.path.insert(0, str(Path(__file__).parent.parent))

# Load API key from .env
env_path = Path(__file__).parent.parent / ".env"
if env_path.exists():
    with open(env_path) as f:
        for line in f:
            if line.strip() and '=' in line and not line.startswith('#'):
                key, val = line.strip().split('=', 1)
                os.environ[key] = val

from mira.miul.v3.extract import extract_drawing_tree, VisionClient

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(message)s'
)
logger = logging.getLogger(__name__)


def main():
    parser = argparse.ArgumentParser(
        description="Extract Drawing Tree hierarchy from PDF using Claude Vision"
    )
    parser.add_argument(
        "pdf_path",
        help="Path to the Drawing Tree PDF file"
    )
    parser.add_argument(
        "--output", "-o",
        help="Output JSON path (default: <input>.dt_hierarchy.json)"
    )
    parser.add_argument(
        "--max-iterations", "-n",
        type=int,
        default=3,
        help="Maximum validation/correction iterations (default: 3)"
    )

    args = parser.parse_args()

    pdf_path = Path(args.pdf_path)
    if not pdf_path.exists():
        logger.error(f"PDF not found: {pdf_path}")
        sys.exit(1)

    # Determine output path
    if args.output:
        output_path = Path(args.output)
    else:
        output_path = pdf_path.with_suffix(".dt_hierarchy.json")

    logger.info("=" * 60)
    logger.info(f"Drawing Tree Extractor")
    logger.info("=" * 60)
    logger.info(f"Input:  {pdf_path}")
    logger.info(f"Output: {output_path}")
    logger.info("")

    # Create vision client
    try:
        client = VisionClient()
        if not client.is_available():
            logger.error("Vision API not available. Check ANTHROPIC_API_KEY.")
            sys.exit(1)
    except Exception as e:
        logger.error(f"Failed to initialize vision client: {e}")
        sys.exit(1)

    # Extract
    logger.info("Starting extraction...")
    result = extract_drawing_tree(pdf_path, client, max_iterations=args.max_iterations)

    if not result or not result.get("tree"):
        logger.error("Extraction failed - no tree data returned")
        sys.exit(1)

    # Save result
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)

    # Print summary
    logger.info("")
    logger.info("=" * 60)
    logger.info("EXTRACTION COMPLETE")
    logger.info("=" * 60)
    logger.info(f"Top Level: {result.get('top_level', 'N/A')}")
    logger.info(f"Total Entries: {len(result.get('tree', []))}")

    # Count types
    assemblies = sum(1 for n in result.get("tree", []) if n.get("type") == "ASSEMBLY")
    details = sum(1 for n in result.get("tree", []) if n.get("type") == "DETAIL")
    logger.info(f"Assemblies: {assemblies}")
    logger.info(f"Details: {details}")
    logger.info("")
    logger.info(f"Saved to: {output_path}")

    # Print tree structure
    logger.info("")
    logger.info("HIERARCHY:")
    logger.info("-" * 40)

    tree = result.get("tree", [])
    by_parent = {}
    for entry in tree:
        parent = entry.get("parent") or "ROOT"
        if parent not in by_parent:
            by_parent[parent] = []
        by_parent[parent].append(entry)

    def print_branch(parent_pn, indent=0):
        children = by_parent.get(parent_pn, [])
        for child in children:
            pn = child.get("drawing_number", "?")
            name = (child.get("title") or "")[:35]
            typ = child.get("type", "?")
            prefix = "  " * indent + "+- " if indent > 0 else ""
            logger.info(f"{prefix}{pn} [{typ[0]}] {name}")
            print_branch(pn, indent + 1)

    # Print from root
    for entry in by_parent.get("ROOT", []):
        pn = entry.get("drawing_number", "?")
        name = (entry.get("title") or "")[:35]
        typ = entry.get("type", "?")
        logger.info(f"{pn} [{typ[0]}] {name}")
        print_branch(pn, 1)

    logger.info("")
    logger.info("Next steps:")
    logger.info("  1. Review the hierarchy above for accuracy")
    logger.info("  2. If corrections needed, load JSON in DT Editor (/dt-editor)")
    logger.info("  3. Use corrected JSON as 'drawing_tree' input in MIUL Builder")

    return 0


if __name__ == "__main__":
    sys.exit(main())
