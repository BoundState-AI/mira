#!/usr/bin/env python3
"""
Module: Extractor
Purpose: ATHENA Table Extractor.

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

import hashlib
import logging
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional, Union

import pdfplumber

from athena.core.models import TableGrid, ExtractionResult
from athena.extraction.detector import TableDetector
from athena.extraction.transcriber import TableTranscriber

__all__ = ["TableExtractor", "extract_tables"]
__safety_critical__ = True

logger = logging.getLogger(__name__)


class TableExtractor:
    """
    Main table extraction orchestrator.

    Coordinates:
    1. TableDetector - finds table regions
    2. TableTranscriber - converts regions to TableGrid
    """

    def __init__(
        self,
        model: str = "claude-haiku-4-5-20251001",
        render_dpi: int = 150,
        vision_fallback: bool = True,
    ):
        self.model = model
        self.render_dpi = render_dpi
        self.vision_fallback = vision_fallback

        self.detector = TableDetector(
            model=model,
            vision_fallback=vision_fallback,
            render_dpi=render_dpi,
        )
        self.transcriber = TableTranscriber(
            model=model,
            render_dpi=render_dpi,
        )

        self.logger = logging.getLogger(self.__class__.__name__)

    def extract_pdf(self, pdf_path: Union[str, Path]) -> ExtractionResult:
        """
        Extract all tables from a PDF.

        Args:
            pdf_path: Path to PDF file

        Returns:
            ExtractionResult with all extracted tables
        """
        pdf_path = Path(pdf_path)
        start_time = datetime.now()

        self.logger.info(f"Extracting: {pdf_path.name}")

        # Initialize result
        result = ExtractionResult(
            extraction_id=str(uuid.uuid4()),
            extraction_timestamp=datetime.now().isoformat(),
            source_paths=[str(pdf_path)],
            source_hashes=[self._compute_file_hash(pdf_path)],
        )

        tables: list[TableGrid] = []
        api_calls = 0

        try:
            with pdfplumber.open(pdf_path) as pdf:
                result.documents_processed = 1
                result.pages_scanned = len(pdf.pages)

                for page_num, page in enumerate(pdf.pages, start=1):
                    # Detect tables
                    detected_tables = self.detector.detect_tables(page, page_num)

                    for detected in detected_tables:
                        if detected.detection_method == "pdfplumber":
                            result.tables_found_pdfplumber += 1
                        else:
                            result.tables_found_vision_fallback += 1
                            api_calls += 1  # Detection call

                        # Transcribe
                        grid = self.transcriber.transcribe(
                            page=page,
                            detected=detected,
                            pdf_path=str(pdf_path),
                        )
                        api_calls += 1  # Transcription call

                        if grid.error:
                            result.tables_failed += 1
                            result.errors.append(f"{grid.table_id}: {grid.error}")
                        else:
                            result.table_grids_transcribed += 1
                            tables.append(grid)

        except Exception as e:
            self.logger.error(f"Failed to process {pdf_path.name}: {e}")
            result.failed_documents.append(str(pdf_path))
            result.errors.append(str(e))

        # Finalize result
        result.tables = tables
        result.api_calls = api_calls

        total_time = (datetime.now() - start_time).total_seconds()
        self.logger.info(
            f"  -> {len(tables)} tables extracted, "
            f"{result.tables_failed} failed, "
            f"{api_calls} API calls, "
            f"{total_time:.1f}s"
        )

        return result

    def extract_directory(
        self,
        directory: Union[str, Path],
        pattern: str = "*.pdf",
    ) -> ExtractionResult:
        """
        Extract tables from all PDFs in a directory.

        Args:
            directory: Directory containing PDFs
            pattern: Glob pattern for PDFs

        Returns:
            Combined ExtractionResult
        """
        directory = Path(directory)
        pdf_files = sorted(directory.glob(pattern))

        self.logger.info(f"Processing {len(pdf_files)} PDFs from {directory}")

        # Combined result
        combined = ExtractionResult(
            extraction_id=str(uuid.uuid4()),
            extraction_timestamp=datetime.now().isoformat(),
            source_paths=[],
            source_hashes=[],
        )

        for pdf_file in pdf_files:
            try:
                result = self.extract_pdf(pdf_file)

                # Merge results
                combined.source_paths.extend(result.source_paths)
                combined.source_hashes.extend(result.source_hashes)
                combined.tables.extend(result.tables)
                combined.errors.extend(result.errors)
                combined.failed_documents.extend(result.failed_documents)

                combined.documents_processed += result.documents_processed
                combined.pages_scanned += result.pages_scanned
                combined.tables_found_pdfplumber += result.tables_found_pdfplumber
                combined.tables_found_vision_fallback += result.tables_found_vision_fallback
                combined.table_grids_transcribed += result.table_grids_transcribed
                combined.tables_failed += result.tables_failed
                combined.api_calls += result.api_calls

            except Exception as e:
                self.logger.error(f"Failed: {pdf_file.name} - {e}")
                combined.failed_documents.append(str(pdf_file))
                combined.errors.append(f"{pdf_file.name}: {e}")

        return combined

    def _compute_file_hash(self, file_path: Path) -> str:
        """Compute SHA256 hash of file."""
        sha256 = hashlib.sha256()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                sha256.update(chunk)
        return sha256.hexdigest()


def extract_tables(
    input_path: Union[str, Path],
    output_path: Optional[Union[str, Path]] = None,
) -> ExtractionResult:
    """
    Convenience function to extract tables from PDF or directory.

    Args:
        input_path: PDF file or directory
        output_path: Optional path to save JSON results

    Returns:
        ExtractionResult
    """
    extractor = TableExtractor()
    input_path = Path(input_path)

    if input_path.is_dir():
        result = extractor.extract_directory(input_path)
    else:
        result = extractor.extract_pdf(input_path)

    if output_path:
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(result.model_dump_json(indent=2))
        logger.info(f"Saved to {output_path}")

    return result
