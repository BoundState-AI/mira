#!/usr/bin/env python3
"""
Module: Drawing Cli
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

import argparse
import json
import logging
import sys
from pathlib import Path
import uuid

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def cmd_extract_drawing(args: argparse.Namespace) -> int:
    """Extract materials from a single MSFC drawing."""
    from extractor import MSFCExtractor

    pdf_path = Path(args.pdf)
    if not pdf_path.exists():
        logger.error(f"File not found: {pdf_path}")
        return 1

    extractor = MSFCExtractor()
    result = extractor.extract_drawing(pdf_path)

    # Output
    if args.json:
        output = result.model_dump(mode="json")
        print(json.dumps(output, indent=2))
    else:
        print(f"\n{'=' * 60}")
        print(f"Drawing: {result.drawing_number}")
        print(f"Title: {result.title}")
        print(f"Type: {result.drawing_type.value}")
        print(f"{'=' * 60}")

        if result.primary_material:
            print(f"\nPRIMARY MATERIAL:")
            print(f"  Designation: {result.primary_material.designation}")
            print(f"  Specification: {result.primary_material.specification}")
            print(f"  UNS: {result.primary_material.uns_number}")

        if result.embedded_hardware:
            print(f"\nEMBEDDED HARDWARE ({len(result.embedded_hardware)} types):")
            for hw in result.embedded_hardware:
                print(f"  {hw.quantity}x {hw.standard} {hw.thread_size or ''}")
                print(f"     Material: {hw.inferred_material} (confidence: {hw.confidence:.0%})")

        if result.extraction_warnings:
            print(f"\n⚠️ WARNINGS:")
            for warn in result.extraction_warnings:
                print(f"  - {warn}")

        print(f"\nReferenced Standards: {len(result.referenced_standards)}")
        for std in result.referenced_standards[:10]:
            print(f"  - {std}")

    # Save to file if requested
    if args.output:
        output_path = Path(args.output)
        with open(output_path, "w") as f:
            json.dump(result.model_dump(mode="json"), f, indent=2)
        logger.info(f"Saved extraction to {output_path}")

    return 0


def cmd_extract_dt(args: argparse.Namespace) -> int:
    """Extract hierarchy from a Drawing Tree."""
    from extractor import MSFCExtractor

    pdf_path = Path(args.pdf)
    if not pdf_path.exists():
        logger.error(f"File not found: {pdf_path}")
        return 1

    extractor = MSFCExtractor()
    result = extractor.extract_drawing_tree(pdf_path)

    # Output
    if args.json:
        output = result.model_dump(mode="json")
        print(json.dumps(output, indent=2))
    else:
        print(f"\n{'=' * 60}")
        print(f"Drawing Tree: {result.dt_drawing_number}")
        print(f"Top Assembly: {result.top_assembly}")
        print(f"Total Weight: {result.total_weight_lbs} lbs")
        print(f"Total Nodes: {len(result.nodes)}")
        print(f"{'=' * 60}")

        # Print tree structure
        print("\nASSEMBLY HIERARCHY:")
        _print_tree(result, result.top_assembly, 0)

        # Summary by type
        from models import DrawingType
        by_type: dict[DrawingType, int] = {}
        for node in result.nodes.values():
            by_type[node.drawing_type] = by_type.get(node.drawing_type, 0) + 1

        print("\nDRAWING TYPES:")
        for dt, count in sorted(by_type.items(), key=lambda x: -x[1]):
            print(f"  {dt.value}: {count}")

    # Save to file if requested
    if args.output:
        output_path = Path(args.output)
        with open(output_path, "w") as f:
            json.dump(result.model_dump(mode="json"), f, indent=2)
        logger.info(f"Saved extraction to {output_path}")

    return 0


def _print_tree(dt, drawing_num: str, indent: int, visited: set | None = None) -> None:
    """Recursively print tree structure."""
    from models import DrawingTreeExtraction

    if visited is None:
        visited = set()

    if drawing_num in visited:
        return
    visited.add(drawing_num)

    node = dt.nodes.get(drawing_num)
    if not node:
        return

    prefix = "  " * indent + ("├─ " if indent > 0 else "")
    type_badge = f"[{node.drawing_type.value[:3].upper()}]"
    print(f"{prefix}{type_badge} {drawing_num}: {node.title[:40]}")

    for child in node.children:
        _print_tree(dt, child, indent + 1, visited)


def cmd_build_miul(args: argparse.Namespace) -> int:
    """Build MIUL from Drawing Tree and detail drawings."""
    from extractor import MSFCExtractor
    from miul_builder import MIULBuilder, MIULExporter

    dt_path = Path(args.dt_pdf)
    if not dt_path.exists():
        logger.error(f"Drawing Tree not found: {dt_path}")
        return 1

    extractor = MSFCExtractor()

    # Extract Drawing Tree
    logger.info(f"Extracting Drawing Tree from {dt_path.name}")
    dt = extractor.extract_drawing_tree(dt_path)
    logger.info(f"Found {len(dt.nodes)} drawings in tree")

    # Create MIUL builder
    builder = MIULBuilder(
        dt=dt,
        project=args.project,
        contractor=args.contractor,
    )

    # Find and process detail drawings
    if args.drawings:
        drawings_dir = Path(args.drawings)
        if drawings_dir.is_dir():
            pdf_files = list(drawings_dir.glob("*.pdf")) + list(drawings_dir.glob("*.PDF"))
            logger.info(f"Found {len(pdf_files)} PDF files in {drawings_dir}")

            for pdf_path in pdf_files:
                # Skip the DT itself
                if "-DT" in pdf_path.stem.upper():
                    continue

                try:
                    logger.info(f"Processing {pdf_path.name}")
                    extraction = extractor.extract_drawing(pdf_path)
                    builder.add_extraction(extraction)
                except Exception as e:
                    logger.error(f"Failed to process {pdf_path.name}: {e}")
                    continue
        else:
            logger.warning(f"Drawings directory not found: {drawings_dir}")

    # Finalize and export
    miul = builder.finalize()
    status = builder.get_status()

    # Print summary
    print(MIULExporter.summary_report(miul))

    # Export
    if args.output:
        output_base = Path(args.output)

        # JSON
        json_path = output_base.with_suffix(".json")
        MIULExporter.to_json(miul, json_path)

        # CSV
        csv_path = output_base.with_suffix(".csv")
        MIULExporter.to_csv(miul, csv_path)

        # MAPTIS format
        maptis_path = output_base.with_name(f"{output_base.stem}_maptis.csv")
        MIULExporter.to_maptis_format(miul, maptis_path)

        print(f"\nExported to:")
        print(f"  JSON: {json_path}")
        print(f"  CSV: {csv_path}")
        print(f"  MAPTIS: {maptis_path}")

    return 0


def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="MSFC Drawing Parser - Extract materials for MIUL generation",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # extract-drawing command
    p_extract = subparsers.add_parser(
        "extract-drawing",
        help="Extract materials from a single MSFC drawing",
    )
    p_extract.add_argument("pdf", help="Path to PDF file")
    p_extract.add_argument("--json", action="store_true", help="Output as JSON")
    p_extract.add_argument("-o", "--output", help="Save extraction to file")
    p_extract.set_defaults(func=cmd_extract_drawing)

    # extract-dt command
    p_dt = subparsers.add_parser(
        "extract-dt",
        help="Extract hierarchy from a Drawing Tree",
    )
    p_dt.add_argument("pdf", help="Path to DT PDF file")
    p_dt.add_argument("--json", action="store_true", help="Output as JSON")
    p_dt.add_argument("-o", "--output", help="Save extraction to file")
    p_dt.set_defaults(func=cmd_extract_dt)

    # build-miul command
    p_miul = subparsers.add_parser(
        "build-miul",
        help="Build MIUL from Drawing Tree and detail drawings",
    )
    p_miul.add_argument("dt_pdf", help="Path to Drawing Tree PDF")
    p_miul.add_argument("-d", "--drawings", help="Directory containing detail drawing PDFs")
    p_miul.add_argument("-p", "--project", default="DMLLV", help="Project name")
    p_miul.add_argument("-c", "--contractor", help="Contractor name")
    p_miul.add_argument("-o", "--output", help="Output file base name")
    p_miul.set_defaults(func=cmd_build_miul)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
