#!/usr/bin/env python3
"""
Module: Mapper
Purpose: ATHENA Semantic Mapper.

BoundState AI 2025
Version: 1.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Fran OpenAI 5 <noreply@openai.com>
Co-Authored-By: Grok 4.0 <noreply@x.ai>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: SWE-032
Safety Critical: True
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from athena.core.models.grid import TableGrid
from athena.semantic.ontology import SemanticTag
from athena.semantic.rules.base import EXACT_RULES, PATTERN_RULES
from athena.semantic.rules.h2 import H2_EXACT_RULES, H2_PATTERN_RULES
from athena.semantic.rules.o2 import O2_EXACT_RULES, O2_PATTERN_RULES
from athena.semantic.rules.composition import COMPOSITION_RULES, is_element_header

__all__ = ["SemanticMapper", "DomainHint", "MappingResult"]
__safety_critical__ = True

logger = logging.getLogger(__name__)


class DomainHint(str, Enum):
    """Domain hints for specialized rule sets."""
    GENERIC = "generic"
    H2 = "h2"
    O2 = "o2"


@dataclass
class MappingResult:
    """Result of semantic mapping for a column."""
    col_index: int
    header_text: str
    tag: SemanticTag
    confidence: float
    matched_rule: Optional[str] = None  # Which rule matched


@dataclass
class SemanticMapper:
    """
    Maps table column headers to semantic tags.

    Uses a rules-first approach:
    1. Exact match against known headers
    2. Pattern match against regex rules
    3. Domain-specific rules (H2, O2)
    4. Composition element detection
    5. Fallback to UNKNOWN
    """

    domain: DomainHint = DomainHint.GENERIC

    def __post_init__(self) -> None:
        self.logger = logging.getLogger(self.__class__.__name__)

        # Build combined rule sets based on domain
        self._exact_rules: dict[str, SemanticTag] = dict(EXACT_RULES)
        self._pattern_rules: list[tuple[re.Pattern, SemanticTag]] = list(PATTERN_RULES)

        if self.domain == DomainHint.H2:
            self._exact_rules.update(H2_EXACT_RULES)
            self._pattern_rules = list(H2_PATTERN_RULES) + self._pattern_rules
        elif self.domain == DomainHint.O2:
            self._exact_rules.update(O2_EXACT_RULES)
            self._pattern_rules = list(O2_PATTERN_RULES) + self._pattern_rules

        # Add composition rules at the end
        self._pattern_rules.extend(COMPOSITION_RULES)

    def map_headers(self, grid: TableGrid) -> list[MappingResult]:
        """
        Map all column headers in a grid to semantic tags.

        Args:
            grid: TableGrid with headers

        Returns:
            List of MappingResult for each column
        """
        results: list[MappingResult] = []

        for col in range(grid.col_count):
            header = grid.get_column_header_signature(col)
            result = self.map_header(header, col)
            results.append(result)

        return results

    def map_header(self, header: str, col_index: int = 0) -> MappingResult:
        """
        Map a single header to a semantic tag.

        Args:
            header: Column header text
            col_index: Column index for result

        Returns:
            MappingResult with tag and confidence
        """
        if not header or not header.strip():
            return MappingResult(
                col_index=col_index,
                header_text=header or "",
                tag=SemanticTag.UNKNOWN,
                confidence=0.0,
            )

        # Normalize for matching
        normalized = self._normalize(header)

        # 1. Exact match (highest confidence)
        if normalized in self._exact_rules:
            return MappingResult(
                col_index=col_index,
                header_text=header,
                tag=self._exact_rules[normalized],
                confidence=1.0,
                matched_rule=f"exact:{normalized}",
            )

        # 2. Pattern match
        for pattern, tag in self._pattern_rules:
            if pattern.search(header):
                return MappingResult(
                    col_index=col_index,
                    header_text=header,
                    tag=tag,
                    confidence=0.9,
                    matched_rule=f"pattern:{pattern.pattern[:30]}",
                )

        # 3. Element header check
        if is_element_header(header):
            return MappingResult(
                col_index=col_index,
                header_text=header,
                tag=SemanticTag.COMPOSITION_ELEMENT,
                confidence=0.85,
                matched_rule="element_check",
            )

        # 4. Fallback to UNKNOWN
        self.logger.debug(f"No match for header: '{header}'")
        return MappingResult(
            col_index=col_index,
            header_text=header,
            tag=SemanticTag.UNKNOWN,
            confidence=0.0,
        )

    def _normalize(self, text: str) -> str:
        """Normalize header text for exact matching."""
        # Lowercase
        text = text.lower()

        # Remove extra whitespace
        text = re.sub(r"\s+", " ", text.strip())

        # Remove trailing punctuation except parentheses
        text = re.sub(r"[.:;,]+$", "", text)

        return text

    def apply_to_grid(self, grid: TableGrid) -> TableGrid:
        """
        Apply semantic mappings to grid cells.

        Updates the semantic_tag field on header cells.

        Args:
            grid: TableGrid to update

        Returns:
            Same grid with semantic tags applied
        """
        mappings = self.map_headers(grid)

        for mapping in mappings:
            for row in range(grid.header_row_count):
                cell = grid.get_cell(row, mapping.col_index)
                if cell:
                    cell.semantic_tag = mapping.tag

        return grid

    def get_columns_by_tag(
        self,
        grid: TableGrid,
        tag: SemanticTag,
    ) -> list[int]:
        """Get column indices that match a specific tag."""
        mappings = self.map_headers(grid)
        return [m.col_index for m in mappings if m.tag == tag]

    def get_material_columns(self, grid: TableGrid) -> list[int]:
        """Get columns that contain material information."""
        mappings = self.map_headers(grid)
        return [
            m.col_index for m in mappings
            if SemanticTag.is_material_tag(m.tag)
        ]

    def get_property_columns(self, grid: TableGrid) -> list[int]:
        """Get columns that contain property measurements."""
        mappings = self.map_headers(grid)
        return [
            m.col_index for m in mappings
            if SemanticTag.is_property_tag(m.tag)
        ]
