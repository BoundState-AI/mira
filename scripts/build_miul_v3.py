#!/usr/bin/env python3
"""
Build MIUL using v3 enhanced extraction.

Usage:
    python scripts/build_miul_v3.py <directory> [--nha-overrides <path>]

    # Basic usage
    python scripts/build_miul_v3.py C:\\Users\\jwilde2\\Desktop\\DMLLV

    # With NHA override file for correct hierarchy
    python scripts/build_miul_v3.py C:\\Users\\jwilde2\\Desktop\\DMLLV --nha-overrides nha_overrides.json

Output:
    - <directory>_MIUL_v3.xlsx - MIUL spreadsheet
    - <directory>_inventory_v3.json - Extraction inventory

NHA Override File Format (JSON):
    {
        "MER07546-001": "MER07545-001",
        "MER07553-001": "MER07545-001",
        ...
    }

    The override file provides authoritative NHA mappings that take precedence
    over both DT extraction and EPL inference. Use this to correct extraction
    errors or provide mappings for complex drawing trees.
"""

import argparse
import sys
import logging
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from mira.miul.v3.builder import build_miul_from_directory

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)


def main():
    parser = argparse.ArgumentParser(
        description="Build MIUL using v3 enhanced extraction",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    python scripts/build_miul_v3.py C:\\Users\\jwilde2\\Desktop\\DMLLV
    python scripts/build_miul_v3.py C:\\Users\\jwilde2\\Desktop\\DMLLV --nha-overrides nha_overrides.json
        """
    )
    parser.add_argument("directory", type=Path, help="Directory containing drawing PDFs")
    parser.add_argument(
        "--nha-overrides", "-n",
        type=Path,
        dest="nha_overrides",
        help="Path to JSON file with manual NHA overrides (takes highest priority)"
    )

    args = parser.parse_args()

    directory = args.directory
    if not directory.exists():
        print(f"Directory not found: {directory}")
        sys.exit(1)

    # Resolve NHA override path (relative to directory if not absolute)
    nha_override_path = None
    if args.nha_overrides:
        if args.nha_overrides.is_absolute():
            nha_override_path = args.nha_overrides
        else:
            nha_override_path = directory / args.nha_overrides

        if not nha_override_path.exists():
            print(f"NHA override file not found: {nha_override_path}")
            sys.exit(1)

    # Output paths
    project_name = directory.name
    output_excel = directory / f"{project_name}_MIUL_v3.xlsx"
    output_inventory = directory / f"{project_name}_inventory_v3.json"

    print(f"=" * 60)
    print(f"MIUL Builder v3 - Enhanced Material Extraction")
    print(f"=" * 60)
    print(f"Input:  {directory}")
    print(f"Output: {output_excel}")
    if nha_override_path:
        print(f"NHA Overrides: {nha_override_path}")
    print(f"=" * 60)

    # Build MIUL
    df, stats = build_miul_from_directory(
        directory,
        output_excel=output_excel,
        output_inventory=output_inventory,
        nha_override_path=nha_override_path,
    )

    # Print summary
    print()
    print(f"=" * 60)
    print(f"Results")
    print(f"=" * 60)
    print(f"Drawings extracted: {stats['drawings_extracted']}")
    print(f"MIUL rows:          {stats['miul_rows']}")
    print(f"Materials found:    {stats['materials_found']}")

    if stats['issues']:
        print(f"\nIssues ({len(stats['issues'])}):")
        for issue in stats['issues'][:10]:
            print(f"  - {issue}")
        if len(stats['issues']) > 10:
            print(f"  ... and {len(stats['issues']) - 10} more")

    print()
    print(f"Output files:")
    print(f"  - {output_excel}")
    print(f"  - {output_inventory}")
    print(f"=" * 60)


if __name__ == "__main__":
    main()
