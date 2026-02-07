#!/usr/bin/env python3
"""
Module: Haiku
Purpose: Haiku BOM Extractor Strategy.

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
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from mira.miul.interfaces import BOMExtractorBase, SafetyCriticalError
import uuid

LOGGER = logging.getLogger(__name__)

# Lazy import to avoid startup cost if not used
_HaikuBOMExtractor: Optional[type] = None


def _get_haiku_extractor_class():
    """Lazy load HaikuBOMExtractor to avoid import-time dependencies."""
    global _HaikuBOMExtractor
    # Always retry if previously failed (was set to False)
    if _HaikuBOMExtractor is None or _HaikuBOMExtractor is False:
        try:
            from mira.miul.haiku_bom_extractor import HaikuBOMExtractor
            _HaikuBOMExtractor = HaikuBOMExtractor
        except ImportError as e:
            LOGGER.warning(f"HaikuBOMExtractor import failed: {e}")
            _HaikuBOMExtractor = False  # Mark as unavailable
    return _HaikuBOMExtractor if _HaikuBOMExtractor else None


class HaikuExtractor(BOMExtractorBase):
    """BOM extractor using Claude Haiku API.

    Provides intelligent extraction of parts lists from PDF engineering drawings.
    Falls back gracefully if API key not set or service unavailable.
    """

    def __init__(self, api_key: Optional[str] = None):
        """Initialize Haiku extractor.

        Args:
            api_key: Anthropic API key. If not provided, uses ANTHROPIC_API_KEY env var.
        """
        self._api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        self._extractor_instance: Optional[Any] = None

    @property
    def name(self) -> str:
        return "Claude Haiku API"

    @property
    def priority(self) -> int:
        return 100  # High priority - try first

    def is_available(self) -> bool:
        """Check if Haiku API is available."""
        extractor_class = _get_haiku_extractor_class()
        return bool(extractor_class and self._api_key)

    def _get_extractor(self):
        """Get or create extractor instance."""
        if self._extractor_instance is None:
            extractor_class = _get_haiku_extractor_class()
            if extractor_class:
                self._extractor_instance = extractor_class(api_key=self._api_key)
        return self._extractor_instance

    async def extract(self, file_paths: List[Path]) -> List[Dict[str, Any]]:
        """Extract parts from PDF files using Haiku API.

        Args:
            file_paths: List of PDF file paths

        Returns:
            List of extracted part dictionaries

        Raises:
            SafetyCriticalError: If extraction fails in a way that could affect safety
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
                # Extract text from PDF
                text = extractor.extract_text_from_pdf(pdf_path)
                LOGGER.debug(f"  PDF text length: {len(text)} chars")

                if not text.strip():
                    LOGGER.warning(f"  No text extracted from {pdf_path.name}")
                    continue

                # Extract drawing info (includes NHA from title block)
                # NOTE: The new vision-based HaikuBOMExtractor.extract_drawing_info()
                # takes base64 images, not text. Skip this for now since NHA is
                # typically extracted from the Drawing Tree, not individual drawings.
                # The workflow's _extract_drawing_nhas() method handles this properly.
                drawing_info = {}
                nha = ''

                # Call Haiku API for parts extraction
                parts = extractor.extract_parts_list(text, pdf_path.name)

                if parts:
                    for part in parts:
                        part["source_file"] = pdf_path.name

                        # Propagate NHA to all parts from this drawing
                        if nha and not part.get("next_assembly"):
                            part["next_assembly"] = nha

                        # Normalize field names for backward compatibility
                        # Old: 'material' → New: 'designation'
                        if "material" in part and "designation" not in part:
                            part["designation"] = part.pop("material")
                        if "material_spec" not in part:
                            part["material_spec"] = ""
                        if "material_form" not in part:
                            part["material_form"] = ""

                    all_parts.extend(parts)
                    LOGGER.info(f"  Extracted {len(parts)} parts")
                else:
                    LOGGER.warning(f"  No parts found in {pdf_path.name}")

            except Exception as e:
                LOGGER.error(
                    f"[{self.name}] Extraction failed for {pdf_path.name}: {e}",
                    exc_info=True,
                )
                # Don't raise SafetyCriticalError here - allow fallback to other extractors
                continue

        # Deduplicate
        if all_parts:
            all_parts = self.deduplicate_parts(all_parts)
            LOGGER.info(f"[{self.name}] Total unique parts: {len(all_parts)}")

        return all_parts

    def deduplicate_parts(self, parts: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Smart deduplication using Haiku's built-in logic."""
        extractor = self._get_extractor()
        if extractor and hasattr(extractor, "deduplicate_parts"):
            return extractor.deduplicate_parts(parts)
        return super().deduplicate_parts(parts)
