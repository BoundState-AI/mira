#!/usr/bin/env python3
"""
Module: Knowledge Pipeline
Purpose: ATHENA Knowledge Twin Pipeline.

BoundState AI 2025
Version: 1.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Fran OpenAI 5 <noreply@openai.com>
Co-Authored-By: Grok 4.0 <noreply@x.ai>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: SWE-032, SWE-033
Safety Critical: True
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional, Union

from athena.core.models.result import ExtractionResult
from athena.core.models.grid import TableGrid
from athena.extraction.extractor import TableExtractor
from athena.stitching.stitcher import TableStitcher
from athena.stitching.models import LogicalTable
from athena.semantic.mapper import SemanticMapper, DomainHint
from athena.interpreters.protocol import DomainInterpreter
from athena.interpreters.h2 import H2Interpreter
from athena.interpreters.o2 import O2Interpreter
from athena.interpreters.models.h2 import EmbrittlementRecord
from athena.interpreters.models.o2 import FlammabilityRecord
from athena.validation.models import ValidationResult, ValidationStatus
from athena.validation.gates.extraction import ExtractionGate
from athena.validation.gates.h2 import H2ValidationGate
from athena.validation.gates.o2 import O2ValidationGate

__all__ = ["KnowledgeTwinPipeline", "PipelineResult", "PipelineConfig"]
__safety_critical__ = True

logger = logging.getLogger(__name__)


@dataclass
class PipelineConfig:
    """Configuration for the knowledge twin pipeline."""
    domain: DomainHint = DomainHint.GENERIC
    vision_fallback: bool = True
    min_extraction_tables: int = 1
    min_records: int = 1
    skip_validation: bool = False


@dataclass
class PipelineResult:
    """Result of pipeline execution."""
    # Source info
    pdf_path: str
    domain: str
    timestamp: str

    # Extraction results
    extraction_result: Optional[ExtractionResult] = None
    logical_tables: list[LogicalTable] = field(default_factory=list)

    # Interpretation results
    h2_records: list[EmbrittlementRecord] = field(default_factory=list)
    o2_records: list[FlammabilityRecord] = field(default_factory=list)

    # Validation results
    validation_results: list[ValidationResult] = field(default_factory=list)

    # Overall status
    success: bool = False
    error: Optional[str] = None

    @property
    def records(self) -> list:
        """Get all domain records."""
        return self.h2_records + self.o2_records

    @property
    def record_count(self) -> int:
        """Total number of extracted records."""
        return len(self.h2_records) + len(self.o2_records)

    @property
    def validation_passed(self) -> bool:
        """Check if all validations passed."""
        return all(v.passed for v in self.validation_results)


class KnowledgeTwinPipeline:
    """
    Orchestrates the ATHENA knowledge extraction pipeline.

    Stages:
    1. Extract - PDF to TableGrids
    2. Stitch - Multi-page table merging
    3. Map - Semantic header tagging
    4. Interpret - Domain record extraction
    5. Validate - Quality gates
    """

    def __init__(self, config: Optional[PipelineConfig] = None):
        self.config = config or PipelineConfig()
        self.logger = logging.getLogger(self.__class__.__name__)

        # Initialize components
        self._extractor: Optional[TableExtractor] = None
        self._stitcher: Optional[TableStitcher] = None
        self._mapper: Optional[SemanticMapper] = None
        self._interpreter: Optional[DomainInterpreter] = None

    @property
    def extractor(self) -> TableExtractor:
        """Lazy-init extractor."""
        if self._extractor is None:
            self._extractor = TableExtractor(
                vision_fallback=self.config.vision_fallback
            )
        return self._extractor

    @property
    def stitcher(self) -> TableStitcher:
        """Lazy-init stitcher."""
        if self._stitcher is None:
            self._stitcher = TableStitcher()
        return self._stitcher

    @property
    def mapper(self) -> SemanticMapper:
        """Lazy-init mapper based on domain."""
        if self._mapper is None:
            self._mapper = SemanticMapper(domain=self.config.domain)
        return self._mapper

    def get_interpreter(self) -> Optional[DomainInterpreter]:
        """Get interpreter for configured domain."""
        if self.config.domain == DomainHint.H2:
            return H2Interpreter()
        elif self.config.domain == DomainHint.O2:
            return O2Interpreter()
        return None

    def process(self, pdf_path: Union[str, Path]) -> PipelineResult:
        """
        Process a PDF through the full pipeline.

        Args:
            pdf_path: Path to PDF file

        Returns:
            PipelineResult with all extracted data
        """
        pdf_path = Path(pdf_path)
        start_time = datetime.now()

        result = PipelineResult(
            pdf_path=str(pdf_path),
            domain=self.config.domain.value,
            timestamp=start_time.isoformat(),
        )

        try:
            # Stage 1: Extract
            self.logger.info(f"Stage 1: Extracting tables from {pdf_path.name}")
            extraction_result = self.extractor.extract_pdf(pdf_path)
            result.extraction_result = extraction_result

            if not extraction_result.tables:
                result.error = "No tables extracted"
                return result

            self.logger.info(f"  Extracted {len(extraction_result.tables)} tables")

            # Stage 2: Stitch
            self.logger.info("Stage 2: Stitching multi-page tables")
            logical_tables = self.stitcher.stitch(extraction_result.tables)
            result.logical_tables = logical_tables

            self.logger.info(f"  Stitched into {len(logical_tables)} logical tables")

            # Stage 3: Map
            self.logger.info("Stage 3: Applying semantic mapping")
            for table in logical_tables:
                self.mapper.apply_to_grid(table)

            # Stage 4: Interpret
            interpreter = self.get_interpreter()
            if interpreter:
                self.logger.info(f"Stage 4: Interpreting as {self.config.domain.value} domain")

                for table in logical_tables:
                    if interpreter.can_interpret(table):
                        if self.config.domain == DomainHint.H2:
                            records = interpreter.interpret(table)
                            result.h2_records.extend(records)
                        elif self.config.domain == DomainHint.O2:
                            records = interpreter.interpret(table)
                            result.o2_records.extend(records)

                self.logger.info(f"  Extracted {result.record_count} records")
            else:
                self.logger.info("Stage 4: Skipping interpretation (generic domain)")

            # Stage 5: Validate
            if not self.config.skip_validation:
                self.logger.info("Stage 5: Running validation gates")
                result.validation_results = self._run_validation(result)

                passed = sum(1 for v in result.validation_results if v.passed)
                total = len(result.validation_results)
                self.logger.info(f"  Validation: {passed}/{total} gates passed")

            result.success = True

        except Exception as e:
            self.logger.error(f"Pipeline failed: {e}")
            result.error = str(e)
            result.success = False

        elapsed = (datetime.now() - start_time).total_seconds()
        self.logger.info(f"Pipeline completed in {elapsed:.1f}s")

        return result

    def _run_validation(self, result: PipelineResult) -> list[ValidationResult]:
        """Run all applicable validation gates."""
        validations: list[ValidationResult] = []

        # Extraction gate
        if result.extraction_result:
            gate = ExtractionGate(min_tables=self.config.min_extraction_tables)
            validations.append(gate.validate(result.extraction_result))

        # Domain-specific gates
        if self.config.domain == DomainHint.H2 and result.h2_records:
            gate = H2ValidationGate(min_records=self.config.min_records)
            validations.append(gate.validate(result.h2_records))

        if self.config.domain == DomainHint.O2 and result.o2_records:
            gate = O2ValidationGate(min_records=self.config.min_records)
            validations.append(gate.validate(result.o2_records))

        return validations

    def extract_only(self, pdf_path: Union[str, Path]) -> ExtractionResult:
        """Run only extraction stage."""
        return self.extractor.extract_pdf(pdf_path)

    def stitch_tables(self, grids: list[TableGrid]) -> list[LogicalTable]:
        """Run only stitching stage."""
        return self.stitcher.stitch(grids)
