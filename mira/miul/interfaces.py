#!/usr/bin/env python3
"""
Module: Interfaces
Purpose: MIUL Interface Definitions.

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

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Dict, List, Optional, Protocol, Tuple, runtime_checkable

import pandas as pd
import uuid


@runtime_checkable
class IBOMExtractor(Protocol):
    """Interface for BOM extraction strategies.

    Implementations must extract parts from source files (PDFs, Excel, etc.)
    and return a standardized list of part dictionaries.
    """

    @property
    def name(self) -> str:
        """Human-readable name for this extractor."""
        ...

    @property
    def priority(self) -> int:
        """Priority for fallback ordering (higher = try first)."""
        ...

    def is_available(self) -> bool:
        """Check if this extractor is available (dependencies met, API keys set)."""
        ...

    async def extract(self, file_paths: List[Path]) -> List[Dict[str, Any]]:
        """Extract parts from source files.

        Args:
            file_paths: List of file paths to extract from

        Returns:
            List of part dictionaries with keys:
            - part_number: str
            - description: str (optional)
            - material: str (optional)
            - qty: str (optional)
            - source_file: str
            - source_drawing: str (optional)
            - cage_code: str (optional)
        """
        ...


@runtime_checkable
class IEnrichmentService(Protocol):
    """Interface for MIUL enrichment services.

    Single method interface - clients only need enrich_miul_dataframe().
    """

    def enrich_miul_dataframe(
        self, miul_df: pd.DataFrame
    ) -> Tuple[pd.DataFrame, Dict[str, Any]]:
        """Enrich MIUL DataFrame with ratings from database.

        Workflow:
        1. Look up Material Code from Manufacturer Designation if missing
        2. Fetch ratings (FLAM, SCC, CORR, TVS, TOX, FS) using Material Code

        Args:
            miul_df: MIUL DataFrame with Material Code and/or Manufacturer Designation

        Returns:
            Tuple of (enriched_df, stats_dict)
        """
        ...


@runtime_checkable
class IMIULTransformer(Protocol):
    """Interface for transforming parts to MIUL format."""

    def to_miul_dataframe(self, parts: List[Dict[str, Any]]) -> pd.DataFrame:
        """Convert extracted parts to MIUL-formatted DataFrame.

        Args:
            parts: List of part dictionaries from extractor

        Returns:
            MIUL-formatted DataFrame per JSC 27301F Section 4.2.1
        """
        ...


class BOMExtractorBase(ABC):
    """Abstract base class for BOM extractors.

    Provides common functionality and enforces interface contract.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable name for this extractor."""
        pass

    @property
    @abstractmethod
    def priority(self) -> int:
        """Priority for fallback ordering (higher = try first)."""
        pass

    @abstractmethod
    def is_available(self) -> bool:
        """Check if this extractor is available."""
        pass

    @abstractmethod
    async def extract(self, file_paths: List[Path]) -> List[Dict[str, Any]]:
        """Extract parts from source files."""
        pass

    def deduplicate_parts(self, parts: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Remove duplicate parts based on part_number.

        Default implementation - subclasses can override for smarter deduplication.
        """
        seen = set()
        unique = []
        for part in parts:
            key = part.get("part_number", "")
            if key and key not in seen:
                seen.add(key)
                unique.append(part)
            elif not key:
                # Keep parts without part_number (may have other identifying info)
                unique.append(part)
        return unique


class SafetyCriticalError(Exception):
    """Exception for safety-critical failures that must not be suppressed.

    Use this for:
    - Material safety violations
    - Extraction failures that could affect safety assessments
    - Data integrity issues in safety-critical paths
    """

    def __init__(self, message: str, context: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.context = context or {}


__all__ = [
    "IBOMExtractor",
    "IEnrichmentService",
    "IMIULTransformer",
    "BOMExtractorBase",
    "SafetyCriticalError",
]
