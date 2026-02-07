#!/usr/bin/env python3
"""
Module: Pipeline
Purpose: MIUL Pipeline Orchestrator

BoundState AI 2025
Version: 1.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Fran OpenAI 5 <noreply@openai.com>
Co-Authored-By: Grok 4.0 <noreply@x.ai>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: SWE-013, SWE-033, NASA-STD-6016C, MAPTIS Import Spec
Safety Critical: True
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from .parse_dt import parse_drawing_tree, DTHierarchy
from .parse_drawings import parse_detail_drawings, parse_assembly_epls, DrawingData
from .merge import merge_to_miul, MIULDocument
from .export import export_to_excel
from .validate import validate_against_dt, ValidationResult

logger = logging.getLogger(__name__)

__all__ = ["MIULPipeline", "PipelineConfig", "run_pipeline"]
__safety_critical__ = True


@dataclass
class PipelineConfig:
    """Configuration for MIUL pipeline execution.

    Args:
        miul_number: Project identifier (e.g., "DMLLV")
        dt_pdf_path: Path to Drawing Tree PDF (Stage 1 input)
        drawings_dir: Directory containing all drawing PDFs
        output_dir: Where to save all outputs (default: same as dt_pdf_path)
        cache: If True, skip stages with existing outputs
        stages: Which stages to run (default: all)
    """
    miul_number: str
    dt_pdf_path: Path
    drawings_dir: Path
    output_dir: Optional[Path] = None
    cache: bool = True
    stages: List[str] = field(default_factory=lambda: [
        "parse_dt", "parse_details", "parse_epls", "merge", "export", "validate"
    ])

    def __post_init__(self):
        self.dt_pdf_path = Path(self.dt_pdf_path)
        self.drawings_dir = Path(self.drawings_dir)
        if self.output_dir is None:
            self.output_dir = self.dt_pdf_path.parent
        self.output_dir = Path(self.output_dir)


@dataclass
class PipelineResult:
    """Result of pipeline execution."""
    miul_number: str
    status: str  # PASS, FAIL, PARTIAL
    completed_stages: List[str] = field(default_factory=list)
    failed_stage: str = ""
    error_message: str = ""

    # Outputs
    hierarchy_path: Optional[Path] = None
    drawings_dir: Optional[Path] = None
    miul_json_path: Optional[Path] = None
    excel_path: Optional[Path] = None
    validation_path: Optional[Path] = None

    # Final documents
    hierarchy: Optional[DTHierarchy] = None
    miul: Optional[MIULDocument] = None
    validation: Optional[ValidationResult] = None

    # Timing
    started_at: str = ""
    completed_at: str = ""

    def summary(self) -> str:
        """Human-readable pipeline summary."""
        lines = [
            f"=== MIUL Pipeline: {self.status} ===",
            f"MIUL Number: {self.miul_number}",
            f"Completed: {', '.join(self.completed_stages)}",
        ]

        if self.failed_stage:
            lines.append(f"Failed at: {self.failed_stage}")
            lines.append(f"Error: {self.error_message}")

        if self.excel_path:
            lines.append(f"Output: {self.excel_path}")

        if self.validation:
            lines.append(f"Validation: {self.validation.status}")
            lines.append(f"  Matched: {self.validation.matched_count}/{self.validation.total_dt_nodes}")
            lines.append(f"  Errors: {len(self.validation.errors)}")

        return "\n".join(lines)


class MIULPipeline:
    """Orchestrates the staged MIUL extraction pipeline.

    Each stage saves its output to JSON, enabling:
    - Resume from any stage if interrupted
    - Debug individual stages
    - Share intermediate results

    Example:
        pipeline = MIULPipeline(config)
        result = pipeline.run()
        print(result.summary())
    """

    def __init__(self, config: PipelineConfig):
        self.config = config
        self.output_dir = config.output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # Stage output paths
        self.hierarchy_path = self.output_dir / "hierarchy.json"
        self.drawings_output_dir = self.output_dir / "drawings"
        self.miul_json_path = self.output_dir / "miul.json"
        self.excel_path = self.output_dir / f"{config.miul_number}_MIUL.xlsx"
        self.validation_path = self.output_dir / "validation.json"

        # Runtime state
        self.hierarchy: Optional[DTHierarchy] = None
        self.drawings: Dict[str, DrawingData] = {}
        self.miul: Optional[MIULDocument] = None
        self.validation: Optional[ValidationResult] = None

    def run(self) -> PipelineResult:
        """Execute pipeline stages sequentially.

        Returns:
            PipelineResult with all outputs and status
        """
        result = PipelineResult(
            miul_number=self.config.miul_number,
            status="PENDING",
            started_at=datetime.now().isoformat(),
        )

        try:
            # Stage 1: Parse Drawing Tree
            if "parse_dt" in self.config.stages:
                logger.info("=" * 60)
                logger.info("[Pipeline] Stage 1: Parsing Drawing Tree")
                self.hierarchy = parse_drawing_tree(
                    dt_pdf_path=self.config.dt_pdf_path,
                    miul_number=self.config.miul_number,
                    output_path=self.hierarchy_path,
                    cache=self.config.cache,
                )
                result.completed_stages.append("parse_dt")
                result.hierarchy_path = self.hierarchy_path
                result.hierarchy = self.hierarchy
                logger.info(f"[Pipeline] Stage 1 complete: {len(self.hierarchy.nodes)} nodes")
            else:
                # Load from cache if skipped
                if self.hierarchy_path.exists():
                    self.hierarchy = DTHierarchy.load(self.hierarchy_path)

            if self.hierarchy is None:
                raise ValueError("No hierarchy available - run parse_dt stage first")

            # Get list of part numbers from hierarchy
            all_pns = list(self.hierarchy.nodes.keys())
            assembly_pns = [pn for pn, node in self.hierarchy.nodes.items() if node.is_assembly]

            # Stage 2: Parse Detail Drawings
            if "parse_details" in self.config.stages:
                logger.info("=" * 60)
                logger.info("[Pipeline] Stage 2: Parsing Detail Drawings")
                detail_drawings = parse_detail_drawings(
                    drawing_dir=self.config.drawings_dir,
                    known_pns=all_pns,
                    output_dir=self.drawings_output_dir,
                    cache=self.config.cache,
                )
                self.drawings.update(detail_drawings)
                result.completed_stages.append("parse_details")
                logger.info(f"[Pipeline] Stage 2 complete: {len(detail_drawings)} drawings")

            # Stage 3: Parse Assembly EPLs
            if "parse_epls" in self.config.stages:
                logger.info("=" * 60)
                logger.info("[Pipeline] Stage 3: Parsing Assembly EPLs")
                epl_drawings = parse_assembly_epls(
                    drawing_dir=self.config.drawings_dir,
                    assembly_pns=assembly_pns,
                    output_dir=self.drawings_output_dir,
                    cache=self.config.cache,
                )
                # Merge EPL data into existing drawings
                for pn, drawing in epl_drawings.items():
                    if pn in self.drawings:
                        self.drawings[pn].epl = drawing.epl
                    else:
                        self.drawings[pn] = drawing
                result.completed_stages.append("parse_epls")
                result.drawings_dir = self.drawings_output_dir
                logger.info(f"[Pipeline] Stage 3 complete: {len(epl_drawings)} EPLs")

            # Load drawings from cache if stages 2-3 were skipped
            if not self.drawings and self.drawings_output_dir.exists():
                self.drawings = self._load_drawings_from_cache()

            # Stage 4: Merge to MIUL
            if "merge" in self.config.stages:
                logger.info("=" * 60)
                logger.info("[Pipeline] Stage 4: Merging to MIUL")
                self.miul = merge_to_miul(
                    hierarchy=self.hierarchy,
                    drawings=self.drawings,
                    project=self.config.miul_number,
                    output_path=self.miul_json_path,
                )
                result.completed_stages.append("merge")
                result.miul_json_path = self.miul_json_path
                result.miul = self.miul
                logger.info(f"[Pipeline] Stage 4 complete: {len(self.miul.rows)} rows")
            else:
                # Load from cache if skipped
                if self.miul_json_path.exists():
                    self.miul = MIULDocument.load(self.miul_json_path)

            if self.miul is None:
                raise ValueError("No MIUL available - run merge stage first")

            # Stage 5: Export to Excel
            if "export" in self.config.stages:
                logger.info("=" * 60)
                logger.info("[Pipeline] Stage 5: Exporting to Excel")
                self.excel_path = export_to_excel(
                    miul=self.miul,
                    output_path=self.excel_path,
                )
                result.completed_stages.append("export")
                result.excel_path = self.excel_path
                logger.info(f"[Pipeline] Stage 5 complete: {self.excel_path}")

            # Stage 6: Validate against DT
            if "validate" in self.config.stages:
                logger.info("=" * 60)
                logger.info("[Pipeline] Stage 6: Validating against DT")
                self.validation = validate_against_dt(
                    miul=self.miul,
                    hierarchy=self.hierarchy,
                    output_path=self.validation_path,
                )
                result.completed_stages.append("validate")
                result.validation_path = self.validation_path
                result.validation = self.validation
                logger.info(f"[Pipeline] Stage 6 complete: {self.validation.status}")

            # Determine final status
            if result.validation and result.validation.status == "FAIL":
                result.status = "FAIL"
            elif len(result.completed_stages) == len(self.config.stages):
                result.status = "PASS"
            else:
                result.status = "PARTIAL"

        except Exception as e:
            result.status = "FAIL"
            result.failed_stage = result.completed_stages[-1] if result.completed_stages else "init"
            result.error_message = str(e)
            logger.error(f"[Pipeline] Failed at stage: {result.failed_stage}")
            logger.error(f"[Pipeline] Error: {e}")
            raise

        finally:
            result.completed_at = datetime.now().isoformat()
            logger.info("=" * 60)
            logger.info(f"[Pipeline] Complete: {result.status}")
            logger.info(f"[Pipeline] Stages: {', '.join(result.completed_stages)}")

        return result

    def _load_drawings_from_cache(self) -> Dict[str, DrawingData]:
        """Load all cached drawings from drawings/ directory."""
        drawings = {}
        if not self.drawings_output_dir.exists():
            return drawings

        for json_path in self.drawings_output_dir.glob("*.json"):
            try:
                drawing = DrawingData.load(json_path)
                drawings[drawing.part_number] = drawing
            except Exception as e:
                logger.warning(f"[Pipeline] Could not load {json_path}: {e}")

        logger.info(f"[Pipeline] Loaded {len(drawings)} drawings from cache")
        return drawings


def run_pipeline(
    miul_number: str,
    dt_pdf_path: Path,
    drawings_dir: Path,
    output_dir: Optional[Path] = None,
    cache: bool = True,
    stages: Optional[List[str]] = None,
) -> PipelineResult:
    """Convenience function to run MIUL pipeline.

    Args:
        miul_number: Project identifier (e.g., "DMLLV")
        dt_pdf_path: Path to Drawing Tree PDF
        drawings_dir: Directory containing all drawing PDFs
        output_dir: Where to save outputs (default: same as DT)
        cache: Skip stages with existing outputs
        stages: Which stages to run (default: all)

    Returns:
        PipelineResult with all outputs

    Example:
        result = run_pipeline(
            miul_number="DMLLV",
            dt_pdf_path=Path("drawings/DMLLV-DT.pdf"),
            drawings_dir=Path("drawings/"),
        )
        print(result.summary())
    """
    config = PipelineConfig(
        miul_number=miul_number,
        dt_pdf_path=dt_pdf_path,
        drawings_dir=drawings_dir,
        output_dir=output_dir,
        cache=cache,
        stages=stages or [
            "parse_dt", "parse_details", "parse_epls", "merge", "export", "validate"
        ],
    )

    pipeline = MIULPipeline(config)
    return pipeline.run()


# === CLI Entry Point ===
if __name__ == "__main__":
    import argparse
    import sys

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    parser = argparse.ArgumentParser(
        description="Run MIUL extraction pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Full pipeline
  python -m mira.miul.stages.pipeline DMLLV drawings/DMLLV-DT.pdf drawings/

  # Resume from merge stage
  python -m mira.miul.stages.pipeline DMLLV drawings/DMLLV-DT.pdf drawings/ --stages merge,export,validate

  # Force re-run (no cache)
  python -m mira.miul.stages.pipeline DMLLV drawings/DMLLV-DT.pdf drawings/ --no-cache
""",
    )

    parser.add_argument("miul_number", help="MIUL identifier (e.g., DMLLV)")
    parser.add_argument("dt_pdf", help="Path to Drawing Tree PDF")
    parser.add_argument("drawings_dir", help="Directory containing drawing PDFs")
    parser.add_argument("--output", "-o", help="Output directory (default: same as DT)")
    parser.add_argument("--stages", help="Comma-separated stages to run (default: all)")
    parser.add_argument("--no-cache", action="store_true", help="Force re-run all stages")

    args = parser.parse_args()

    stages = None
    if args.stages:
        stages = [s.strip() for s in args.stages.split(",")]

    try:
        result = run_pipeline(
            miul_number=args.miul_number,
            dt_pdf_path=Path(args.dt_pdf),
            drawings_dir=Path(args.drawings_dir),
            output_dir=Path(args.output) if args.output else None,
            cache=not args.no_cache,
            stages=stages,
        )

        print("\n" + result.summary())

        if result.status == "FAIL":
            sys.exit(1)

    except Exception as e:
        logger.error(f"Pipeline failed: {e}")
        sys.exit(1)
