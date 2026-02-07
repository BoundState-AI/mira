#!/usr/bin/env python3
"""
Module: Service
Purpose: BOM Extractor Service with Registry Pattern.

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
from typing import Any, Dict, List, Optional, Type

from mira.miul.interfaces import BOMExtractorBase, SafetyCriticalError
import uuid

LOGGER = logging.getLogger(__name__)


class ExtractorService:
    """Service for orchestrating BOM extraction with fallback support.

    Implements Strategy pattern with automatic fallback to lower-priority
    extractors when higher-priority ones fail or are unavailable.

    Usage:
        service = ExtractorService()
        service.register(HaikuExtractor())
        service.register(LocalExtractor())
        parts = await service.extract(pdf_paths)
    """

    def __init__(self):
        """Initialize extractor service with empty registry."""
        self._extractors: List[BOMExtractorBase] = []

    def register(self, extractor: BOMExtractorBase) -> "ExtractorService":
        """Register an extractor strategy.

        Args:
            extractor: Extractor implementing BOMExtractorBase

        Returns:
            Self for chaining

        Raises:
            TypeError: If extractor doesn't implement required interface
        """
        if not isinstance(extractor, BOMExtractorBase):
            raise TypeError(
                f"Extractor must inherit from BOMExtractorBase, got {type(extractor)}"
            )

        self._extractors.append(extractor)
        # Keep sorted by priority (highest first)
        self._extractors.sort(key=lambda e: e.priority, reverse=True)

        LOGGER.info(f"Registered extractor: {extractor.name} (priority={extractor.priority})")
        return self

    def get_available_extractors(self) -> List[BOMExtractorBase]:
        """Get list of currently available extractors.

        Returns:
            List of extractors that report is_available() == True
        """
        return [e for e in self._extractors if e.is_available()]

    async def extract(
        self,
        file_paths: List[Path],
        require_extraction: bool = True,
    ) -> List[Dict[str, Any]]:
        """Extract parts from PDF files using registered extractors.

        Tries extractors in priority order, falling back on failure.

        Args:
            file_paths: List of PDF file paths to process
            require_extraction: If True, raise error when no parts extracted

        Returns:
            List of extracted part dictionaries

        Raises:
            SafetyCriticalError: If require_extraction=True and no parts found
        """
        if not file_paths:
            LOGGER.warning("No files provided for extraction")
            return []

        available = self.get_available_extractors()
        if not available:
            msg = "No extractors available. Check API keys and dependencies."
            LOGGER.error(msg)
            if require_extraction:
                raise SafetyCriticalError(msg, {"registered_count": len(self._extractors)})
            return []

        LOGGER.info(
            f"Extracting from {len(file_paths)} file(s) using {len(available)} extractor(s)"
        )

        last_error: Optional[Exception] = None
        all_parts: List[Dict[str, Any]] = []

        for extractor in available:
            LOGGER.info(f"Trying extractor: {extractor.name}")

            try:
                parts = await extractor.extract(file_paths)

                if parts:
                    all_parts = parts
                    LOGGER.info(
                        f"[{extractor.name}] Successfully extracted {len(parts)} parts"
                    )
                    break
                else:
                    LOGGER.warning(f"[{extractor.name}] No parts extracted, trying next")

            except SafetyCriticalError:
                # Don't catch safety-critical errors - propagate immediately
                raise

            except Exception as e:
                last_error = e
                LOGGER.warning(
                    f"[{extractor.name}] Extraction failed: {e}, trying next extractor"
                )
                continue

        if not all_parts:
            if require_extraction:
                msg = f"All {len(available)} extractors failed to extract parts"
                context = {
                    "file_count": len(file_paths),
                    "extractor_count": len(available),
                    "last_error": str(last_error) if last_error else None,
                }
                raise SafetyCriticalError(msg, context)
            else:
                LOGGER.warning("No parts extracted from any extractor")

        return all_parts


# Global service instance (singleton pattern)
_extractor_service: Optional[ExtractorService] = None


def get_extractor_service() -> ExtractorService:
    """Get singleton extractor service with default extractors registered.

    Returns:
        Configured ExtractorService instance
    """
    global _extractor_service

    if _extractor_service is None:
        from mira.miul.v1_archive.extractors.haiku import HaikuExtractor
        from mira.miul.v1_archive.extractors.local import LocalExtractor

        _extractor_service = ExtractorService()
        _extractor_service.register(HaikuExtractor())
        _extractor_service.register(LocalExtractor())

        LOGGER.info("Initialized extractor service with default extractors")

    return _extractor_service


def reset_extractor_service() -> None:
    """Reset singleton for testing purposes."""
    global _extractor_service
    _extractor_service = None


__all__ = [
    "ExtractorService",
    "get_extractor_service",
    "reset_extractor_service",
]
