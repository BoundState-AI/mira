#!/usr/bin/env python3
"""
Module: Cli
Purpose: MIUL Builder v2.3 - CLI Entry Point

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

import argparse
import json
import sys
import uuid
from pathlib import Path
from typing import Optional

try:
    import anthropic
    ANTHROPIC_AVAILABLE = True
except ImportError:
    ANTHROPIC_AVAILABLE = False

from .config import PipelineConfig
from .models import PackageExtract, Issue, IssueSeverity


def print_banner():
    """Print MIUL Builder banner."""
    print("=" * 60)
    print("MIUL Builder v2.3 - Simplified Pipeline")
    print("4-Phase: Extract -> Assemble -> Graph -> MIUL")
    print("=" * 60)
    print()


def print_issues(issues: list[Issue], verbose: bool = False):
    """Print issues to console."""
    blockers = [i for i in issues if i.severity == IssueSeverity.BLOCKER]
    warnings = [i for i in issues if i.severity == IssueSeverity.WARNING]

    if blockers:
        print(f"\n{'='*60}")
        print(f"BLOCKERS ({len(blockers)} issues - pipeline halted)")
        print("=" * 60)
        for issue in blockers:
            print(f"  [{issue.issue_type.value}] {issue.affected}")
            print(f"    {issue.message}")
            if verbose and issue.evidence_page_ids:
                print(f"    Evidence: {issue.evidence_page_ids}")

    if warnings and verbose:
        print(f"\n{'='*60}")
        print(f"WARNINGS ({len(warnings)} issues)")
        print("=" * 60)
        for issue in warnings:
            print(f"  [{issue.issue_type.value}] {issue.affected}")
            print(f"    {issue.message}")


def run_pipeline(
    input_dir: Path,
    output_path: Optional[Path] = None,
    json_path: Optional[Path] = None,
    dt_pdf_path: Optional[Path] = None,
    cache_dir: Optional[Path] = None,
    root_drawing: Optional[str] = None,
    config: Optional[PipelineConfig] = None,
    anthropic_client: Optional['anthropic.Anthropic'] = None,
) -> PackageExtract:
    """
    Run the complete 4-phase pipeline.

    Per v2.3: PDF → Vision → Assemble → Graph → MIUL
    No separate ingest phase.

    Args:
        input_dir: Directory containing PDF drawings
        output_path: Output Excel file path
        json_path: Output JSON file path
        dt_pdf_path: Drawing Tree PDF path
        cache_dir: Cache directory for vision results
        root_drawing: Explicit root drawing number
        config: Pipeline configuration
        anthropic_client: Anthropic client for vision

    Returns:
        PackageExtract with all results
    """
    from .extract import extract_directory
    from .assemble import assemble_package
    from .graph import build_drawing_graph, detect_dt_pdf
    from .miul import generate_miul, export_to_excel, export_to_json

    if config is None:
        config = PipelineConfig.default()

    # Generate package ID
    package_id = str(uuid.uuid4())[:8]

    print(f"Package ID: {package_id}")
    print(f"Input: {input_dir}")
    print(f"Drawing Tree: {dt_pdf_path or 'auto-detect'}")
    print(f"Cache: {cache_dir or 'disabled'}")
    print()

    # ==========================================================================
    # Phase 1: Extract (v2.3 - PDF direct to Vision)
    # ==========================================================================
    print("Phase 1: Extract - Sending PDFs to Vision API...")

    all_extracts, all_issues = extract_directory(
        input_dir,
        anthropic_client=anthropic_client if not config.skip_vision else None,
        cache_dir=cache_dir,
        skip_vision=config.skip_vision,
        max_workers=config.max_workers,
    )

    print(f"  Extracted {len(all_extracts)} pages")

    # Collect unique drawing numbers found
    all_drawings = set()
    for extract in all_extracts:
        all_drawings.update(extract.key_candidates)
    print(f"  Found {len(all_drawings)} unique drawing numbers")

    if not all_extracts:
        print("ERROR: No pages found in input directory")
        return PackageExtract(package_id=package_id)

    # ==========================================================================
    # Phase 2: Assemble
    # ==========================================================================
    print("\nPhase 2: Assemble - Binding pages to drawings...")

    package = assemble_package(
        all_extracts,
        package_id,
        strict_revision=config.binding.strict_revision,
    )
    package.issues.extend(all_issues)

    print(f"  Created {len(package.drawings)} DrawingEntity objects")
    print(f"  Orphan pages: {len(package.orphan_page_ids)}")

    # Check for blockers
    if package.has_blockers:
        print_issues(package.issues, config.verbose)
        print("\nPipeline halted due to BLOCKER issues.")
        print("Resolve these issues and re-run.")
        return package

    # ==========================================================================
    # Phase 3: Graph
    # ==========================================================================
    print("\nPhase 3: Graph - Building drawing hierarchy...")

    # Auto-detect DT if not specified
    if not dt_pdf_path:
        dt_pdf_path = detect_dt_pdf(input_dir)
        if dt_pdf_path:
            print(f"  Auto-detected Drawing Tree: {dt_pdf_path.name}")

    package = build_drawing_graph(
        package,
        dt_pdf_path=dt_pdf_path,
        root_drawing=root_drawing,
    )

    if package.graph:
        print(f"  Root assembly: {package.graph.root.drawing_number if package.graph.root else 'None'}")
        print(f"  Graph edges: {len(package.graph.edges)}")

    # Check for blockers
    if package.has_blockers:
        print_issues(package.issues, config.verbose)
        print("\nPipeline halted due to BLOCKER issues.")
        return package

    # ==========================================================================
    # Phase 4: MIUL
    # ==========================================================================
    print("\nPhase 4: MIUL - Generating parts list...")

    package = generate_miul(
        package,
        deduplicate=config.miul.deduplicate_by_part_number,
    )

    print(f"  Generated {len(package.miul)} MIUL entries")

    # ==========================================================================
    # Output
    # ==========================================================================
    print("\nExporting results...")

    if output_path:
        export_to_excel(package.miul, output_path)
        print(f"  Excel: {output_path}")

    if json_path:
        export_to_json(package.miul, json_path)
        print(f"  JSON: {json_path}")

    # Print summary
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"  Package ID: {package.package_id}")
    print(f"  Total pages: {len(package.pages)}")
    print(f"  Drawings: {len(package.drawings)}")
    print(f"  MIUL entries: {len(package.miul)}")
    print(f"  Blockers: {package.blocker_count}")
    print(f"  Warnings: {package.warning_count}")

    if package.orphan_page_ids:
        print(f"  Orphan pages: {len(package.orphan_page_ids)}")

    # Print issues if verbose
    if package.issues:
        print_issues(package.issues, config.verbose)

    return package


def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="MIUL Builder v2.3 - Simplified Pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Process a directory of PDFs (skip vision for testing)
  python -m mira.miul.v2.cli --input ./drawings --output ./miul.xlsx --skip-vision

  # Process with vision extraction (requires ANTHROPIC_API_KEY)
  python -m mira.miul.v2.cli --input ./drawings --output ./miul.xlsx

  # Process with Drawing Tree PDF
  python -m mira.miul.v2.cli --input ./drawings --dt ./DT.pdf --output ./miul.xlsx

  # Export intermediate JSON
  python -m mira.miul.v2.cli --input ./drawings --json ./inventory.json

  # Specify root assembly explicitly
  python -m mira.miul.v2.cli --input ./drawings --root MER07540-001 --output ./miul.xlsx

  # Use cache for faster re-runs
  python -m mira.miul.v2.cli --input ./drawings --cache-dir ./.cache --output ./miul.xlsx
        """,
    )

    parser.add_argument(
        "--input", "-i",
        type=Path,
        required=True,
        help="Input directory containing PDF drawings",
    )
    parser.add_argument(
        "--dt",
        type=Path,
        help="Drawing Tree PDF (optional - auto-detected if not specified)",
    )
    parser.add_argument(
        "--output", "-o",
        type=Path,
        help="Output MIUL Excel file",
    )
    parser.add_argument(
        "--json", "-j",
        type=Path,
        help="Export intermediate JSON inventory",
    )
    parser.add_argument(
        "--cache-dir",
        type=Path,
        help="Cache directory for vision API results",
    )
    parser.add_argument(
        "--root",
        type=str,
        help="Root drawing number (auto-detected if not specified)",
    )
    parser.add_argument(
        "--skip-vision",
        action="store_true",
        help="Skip vision extraction (for testing without API)",
    )
    parser.add_argument(
        "--no-dedupe",
        action="store_true",
        help="Don't deduplicate MIUL entries by part number",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Verbose output",
    )
    parser.add_argument(
        "--config",
        type=Path,
        help="Configuration JSON file",
    )

    args = parser.parse_args()

    # Validate inputs
    if not args.input.exists():
        parser.error(f"Input directory does not exist: {args.input}")

    if args.dt and not args.dt.exists():
        parser.error(f"Drawing Tree PDF does not exist: {args.dt}")

    if not args.output and not args.json:
        parser.error("Must specify at least one of --output or --json")

    # Load configuration
    if args.config and args.config.exists():
        with open(args.config) as f:
            config_data = json.load(f)
        config = PipelineConfig.from_dict(config_data)
    else:
        config = PipelineConfig.default()

    # Override config with CLI args
    config.verbose = args.verbose
    config.skip_vision = args.skip_vision
    config.miul.deduplicate_by_part_number = not args.no_dedupe

    # Create Anthropic client if not skipping vision
    anthropic_client = None
    if not args.skip_vision:
        if not ANTHROPIC_AVAILABLE:
            print("WARNING: anthropic package not installed. Using skip-vision mode.")
            config.skip_vision = True
        else:
            try:
                anthropic_client = anthropic.Anthropic()
            except Exception as e:
                print(f"WARNING: Failed to create Anthropic client: {e}")
                print("Using skip-vision mode.")
                config.skip_vision = True

    # Print banner
    print_banner()

    # Run pipeline
    try:
        package = run_pipeline(
            input_dir=args.input,
            output_path=args.output,
            json_path=args.json,
            dt_pdf_path=args.dt,
            cache_dir=args.cache_dir,
            root_drawing=args.root,
            config=config,
            anthropic_client=anthropic_client,
        )

        # Exit with error if blockers
        if package.has_blockers:
            sys.exit(1)

    except KeyboardInterrupt:
        print("\nInterrupted by user.")
        sys.exit(130)
    except Exception as e:
        print(f"\nERROR: {e}")
        if args.verbose:
            import traceback
            traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
