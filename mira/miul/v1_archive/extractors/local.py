#!/usr/bin/env python3
"""
Module: Local
Purpose: Local BOM Extractor Strategy.

BoundState AI 2025
Version: 1.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Fran OpenAI 5 <noreply@openai.com>
Co-Authored-By: Grok 4.0 <noreply@x.ai>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: SWE-032 (Data validation), SWE-033 (Requirements Traceability)
Safety Critical: True
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from mira.miul.interfaces import BOMExtractorBase
import uuid

LOGGER = logging.getLogger(__name__)

# Lazy import
_BOMExtractor: Optional[type] = None


def _get_local_extractor_class():
    """Lazy load BOMExtractor to avoid import-time dependencies."""
    global _BOMExtractor
    if _BOMExtractor is None:
        try:
            from mira.miul.pdf_extractor import BOMExtractor
            _BOMExtractor = BOMExtractor
        except ImportError as e:
            LOGGER.warning(f"BOMExtractor import failed: {e}")
            _BOMExtractor = False
    return _BOMExtractor if _BOMExtractor else None


class LocalExtractor(BOMExtractorBase):
    """BOM extractor using local Camelot/pdfplumber.

    Provides basic table extraction from PDF files without external API dependencies.
    Used as fallback when Haiku API is unavailable.
    """

    def __init__(self, max_pages: int = 10):
        """Initialize local extractor.

        Args:
            max_pages: Maximum pages to process per PDF
        """
        self._max_pages = max_pages
        self._extractor_instance: Optional[Any] = None

    @property
    def name(self) -> str:
        return "Local Camelot/pdfplumber"

    @property
    def priority(self) -> int:
        return 50  # Lower priority - use as fallback

    def is_available(self) -> bool:
        """Local extractor is always available if library is installed."""
        return _get_local_extractor_class() is not None

    def _get_extractor(self):
        """Get or create extractor instance."""
        if self._extractor_instance is None:
            extractor_class = _get_local_extractor_class()
            if extractor_class:
                self._extractor_instance = extractor_class(max_pages=self._max_pages)
        return self._extractor_instance

    async def extract(self, file_paths: List[Path]) -> List[Dict[str, Any]]:
        """Extract parts from PDF files using local table extraction.

        Args:
            file_paths: List of PDF file paths

        Returns:
            List of extracted part dictionaries
        """
        if not self.is_available():
            LOGGER.warning(f"[{self.name}] Not available - skipping")
            return []

        extractor = self._get_extractor()
        if not extractor:
            return []

        all_parts: List[Dict[str, Any]] = []

        for pdf_path in file_paths:
            LOGGER.info(f"[{self.name}] Processing: {pdf_path.name}")

            try:
                bom_df = extractor.extract_bom(pdf_path)

                if not bom_df.empty:
                    for _, row in bom_df.iterrows():
                        all_parts.append({
                            "part_number": row.get("Part Number", ""),
                            "qty": row.get("Quantity", ""),
                            "description": "",
                            "designation": "",       # Material name/alloy
                            "material_spec": "",     # Specification (AMS, ASTM)
                            "material_form": "",     # BAR, SHEET, PLATE, etc.
                            "source_file": pdf_path.name,
                        })
                    LOGGER.info(f"  Extracted {len(bom_df)} parts")
                else:
                    LOGGER.warning(f"  No parts found in {pdf_path.name}")

            except Exception as e:
                LOGGER.error(
                    f"[{self.name}] Extraction failed for {pdf_path.name}: {e}",
                    exc_info=True,
                )
                continue

        if all_parts:
            all_parts = self.deduplicate_parts(all_parts)
            LOGGER.info(f"[{self.name}] Total unique parts: {len(all_parts)}")

        return all_parts
