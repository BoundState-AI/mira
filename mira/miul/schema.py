#!/usr/bin/env python3
"""
Module: Schema
Purpose: MIUL schema models per SSP 30234 and MAPTIS import spec.

BoundState AI 2025
Version: 1.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Fran OpenAI 5 <noreply@openai.com>
Co-Authored-By: Grok 4.0 <noreply@x.ai>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: SWE-013 (Data requirements), SWE-033 (Requirements Traceability)
Safety Critical: True
"""

from __future__ import annotations

import logging
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field, field_validator
import uuid

__all__ = [
    "CriticalityCode",
    "RatingCode",
    "MIULRow",
    "MIULTree",
    "MIULDocument",
]

__safety_critical__ = True

logger = logging.getLogger(__name__)


class CriticalityCode(str, Enum):
    """SSP 30234 Table 5.13.1-1 criticality definitions.

    Category 1: Loss of Space Station or life
    Category 2: Loss of mission capability
    Category 3: All others
    """

    CRIT_1 = "1"        # Single failure point -> loss of station/life
    CRIT_1R = "1R"      # Redundant items, all failed -> loss of station/life
    CRIT_1S = "1S"      # Single failure in safety system during catastrophic condition
    CRIT_1SR = "1SR"    # Redundant safety items, all failed -> loss of station/life
    CRIT_2 = "2"        # Single failure point -> loss of mission
    CRIT_2R = "2R"      # Redundant items, all failed -> loss of mission
    CRIT_2N = "2N"      # Single failure, non-critical item
    CRIT_2NR = "2NR"    # Redundant non-critical items
    CRIT_3 = "3"        # All others

    @property
    def is_critical_item(self) -> bool:
        """Per SSP 30234 Section 6.1 - critical items criteria."""
        return self in {
            CriticalityCode.CRIT_1,
            CriticalityCode.CRIT_1S,
            CriticalityCode.CRIT_2,
        }

    @property
    def requires_mua_if_gap(self) -> bool:
        """Criticality 1/1S/2 with rating gaps require MUA."""
        return self.is_critical_item

    @property
    def category(self) -> int:
        """Return criticality category (1, 2, or 3)."""
        if self.value.startswith("1"):
            return 1
        if self.value.startswith("2"):
            return 2
        return 3


class RatingCode(str, Enum):
    """MAPTIS material rating codes.

    Ordered from best (A) to worst (X) for comparison.
    """

    A = "A"  # Acceptable
    B = "B"  # Acceptable with restrictions
    C = "C"  # Caution - limited use
    D = "D"  # Conditional
    I = "I"  # Insufficient data
    K = "K"  # Known issues
    N = "N"  # Not recommended
    U = "U"  # Unknown/untested
    X = "X"  # Prohibited

    @classmethod
    def worst_case(cls, ratings: List[Optional[RatingCode | str]]) -> Optional[RatingCode]:
        """Return worst-case rating from a list.

        Args:
            ratings: List of rating codes (RatingCode, str, or None)

        Returns:
            Worst-case RatingCode, or None if no valid ratings
        """
        order = ["A", "B", "C", "D", "I", "K", "N", "U", "X"]
        valid = [r for r in ratings if r is not None]
        if not valid:
            return None
        try:
            worst_idx = max(order.index(str(r)) for r in valid if str(r) in order)
            return cls(order[worst_idx])
        except ValueError:
            return None

    @property
    def requires_rationale(self) -> bool:
        """Ratings C or worse typically require rationale."""
        return self in {
            RatingCode.C, RatingCode.D, RatingCode.I,
            RatingCode.K, RatingCode.N, RatingCode.U, RatingCode.X,
        }


class MIULRow(BaseModel):
    """Single row in MIUL per MAPTIS import specification.

    Full 42-field schema. Fields marked Optional are populated during
    different pipeline stages (extraction, enrichment, user input).

    Invariant: criticality MUST be provided by engineer - never inferred.
    Compliance: SWE-013
    """

    model_config = {"extra": "forbid", "populate_by_name": True}

    # === Tree Structure (populated by tree builder) ===
    index: int = Field(..., ge=-1, description="Row index, -1 for EOF marker")
    parent: int = Field(0, ge=0, description="Parent index, 0 for root items")

    # === Part Identification (from BOM/extraction) ===
    part_number: str = Field(..., min_length=1, alias="PartNumber")
    part_description: str = Field("", alias="PartDescription")
    nha: Optional[str] = Field(None, description="Next Higher Assembly part number")

    # === Criticality (USER PROVIDED - safety critical) ===
    criticality: Optional[CriticalityCode] = Field(
        None,
        description="SSP 30234 criticality code - MUST be provided by engineer",
    )

    # === Drawing/Source ===
    drawing_source: Optional[str] = Field(None, alias="DrawingSource")
    drawing_rev: Optional[str] = Field(None, alias="DrawingRev")
    source_file: Optional[str] = Field(None, alias="SourceFile")

    # === Material Identification ===
    material_code: Optional[str] = Field(None, alias="MaterialCode")
    designation: Optional[str] = Field(None, description="Material name/designation")
    material_spec: Optional[str] = Field(None, alias="MaterialSpec")
    manufacturer: Optional[str] = Field(None)
    cage_code: Optional[str] = Field(None, alias="CAGECode")

    # === Quantity/Usage ===
    quantity: int = Field(1, ge=0)
    usage_code: Optional[str] = Field(None, alias="UsageCode")

    # === Ratings (populated by enrichment) ===
    flam_rating: Optional[RatingCode] = Field(None, alias="FLAM")
    scc_rating: Optional[RatingCode] = Field(None, alias="SCC")
    corr_rating: Optional[RatingCode] = Field(None, alias="CORR")
    tvs_rating: Optional[RatingCode] = Field(None, alias="TVS")
    tox_rating: Optional[RatingCode] = Field(None, alias="TOX")
    fs_rating: Optional[RatingCode] = Field(None, alias="FS")

    # === MUA/Rationale (populated by MUA generator) ===
    mua_number: Optional[str] = Field(None, alias="MUA")
    rationale_code: Optional[str] = Field(None, alias="RatCode")
    rationale_text: Optional[str] = Field(None, alias="RatText")

    # === Program/Configuration ===
    program: Optional[str] = Field(None)
    end_item: Optional[str] = Field(None, alias="EndItem")
    configuration_status: Optional[str] = Field(None, alias="ConfigStatus")
    application: Optional[str] = Field(None)

    # === Provenance (NASA-STD-8739.8B) ===
    source: str = Field(..., description="Origin: extraction, user, enrichment")

    @field_validator("criticality", mode="before")
    @classmethod
    def validate_criticality(cls, v: str | CriticalityCode | None) -> Optional[CriticalityCode]:
        """Accept string or enum for criticality."""
        if v is None or v == "":
            return None
        if isinstance(v, CriticalityCode):
            return v
        try:
            return CriticalityCode(str(v).upper().strip())
        except ValueError as e:
            valid = [c.value for c in CriticalityCode]
            raise ValueError(f"Invalid criticality '{v}'. Valid: {valid}") from e

    @property
    def has_rating_gap(self) -> bool:
        """Check if any rating is missing or insufficient.

        Returns:
            True if any rating is None, U, I, or X
        """
        ratings = [
            self.flam_rating, self.scc_rating, self.corr_rating,
            self.tvs_rating, self.tox_rating, self.fs_rating,
        ]
        for r in ratings:
            if r is None or r in {RatingCode.U, RatingCode.I, RatingCode.X}:
                return True
        return False

    @property
    def requires_mua(self) -> bool:
        """Determine if this row needs an MUA based on criticality and ratings.

        Invariant: Cannot determine MUA requirement without criticality.
        """
        if self.criticality is None:
            logger.warning(
                "[MIUL] Cannot determine MUA requirement without criticality: %s",
                self.part_number,
            )
            return False
        if not self.criticality.requires_mua_if_gap:
            return False
        return self.has_rating_gap

    @property
    def worst_rating(self) -> Optional[RatingCode]:
        """Return worst-case rating across all categories."""
        return RatingCode.worst_case([
            self.flam_rating, self.scc_rating, self.corr_rating,
            self.tvs_rating, self.tox_rating, self.fs_rating,
        ])


class MIULTree(BaseModel):
    """Validates MIUL tree structure integrity.

    Invariants:
        - Index values must be continuous (1, 2, 3, ...)
        - Parent references must point to existing indices or 0 (root)
        - No circular references allowed
        - EOF marker at index=-1 required

    Compliance: SWE-033
    """

    model_config = {"extra": "forbid"}

    rows: List[MIULRow]

    @field_validator("rows", mode="after")
    @classmethod
    def validate_tree_structure(cls, rows: List[MIULRow]) -> List[MIULRow]:
        """Ensure tree integrity per MIUL spec."""
        if not rows:
            return rows

        # Check EOF marker
        if rows[-1].index != -1:
            raise ValueError("MIUL must end with index=-1 EOF marker")

        # Build index set (excluding EOF)
        data_rows = [r for r in rows if r.index != -1]
        indices = {r.index for r in data_rows}

        # Validate index continuity (1, 2, 3, ...)
        expected = set(range(1, len(data_rows) + 1))
        if indices != expected:
            missing = expected - indices
            extra = indices - expected
            raise ValueError(f"Index continuity violation. Missing: {missing}, Extra: {extra}")

        # Validate parent references
        for row in data_rows:
            if row.parent != 0 and row.parent not in indices:
                raise ValueError(
                    f"Row {row.index} references non-existent parent {row.parent}"
                )

        # Check for circular references
        for row in data_rows:
            visited = {row.index}
            current = row.parent
            while current != 0:
                if current in visited:
                    raise ValueError(f"Circular reference detected at index {row.index}")
                visited.add(current)
                parent_row = next((r for r in data_rows if r.index == current), None)
                if parent_row is None:
                    break
                current = parent_row.parent

        return rows

    def get_children(self, parent_index: int) -> List[MIULRow]:
        """Get all direct children of a given index."""
        return [r for r in self.rows if r.parent == parent_index and r.index != -1]

    def get_descendants(self, parent_index: int) -> List[MIULRow]:
        """Get all descendants (children, grandchildren, etc.) recursively."""
        children = self.get_children(parent_index)
        descendants = list(children)
        for child in children:
            descendants.extend(self.get_descendants(child.index))
        return descendants


class MIULDocument(BaseModel):
    """Complete MIUL document with metadata.

    Compliance: SWE-013, SWE-033
    """

    model_config = {"extra": "forbid"}

    tree: MIULTree
    program: str
    end_item: str
    revision: str = "A"
    source: str  # Provenance per NASA-STD-8739.8B

    @property
    def critical_items(self) -> List[MIULRow]:
        """Return rows that are critical items per SSP 30234 Section 6.1."""
        return [
            r for r in self.tree.rows
            if r.criticality is not None and r.criticality.is_critical_item
        ]

    @property
    def mua_required_items(self) -> List[MIULRow]:
        """Return rows needing MUA generation."""
        return [r for r in self.tree.rows if r.requires_mua]

    @property
    def missing_criticality(self) -> List[MIULRow]:
        """Return rows missing criticality assignment."""
        return [
            r for r in self.tree.rows
            if r.index != -1 and r.criticality is None
        ]

    def validate_completeness(self) -> List[str]:
        """Return list of validation warnings.

        Returns:
            List of warning messages for incomplete data
        """
        warnings = []

        missing_crit = self.missing_criticality
        if missing_crit:
            warnings.append(
                f"{len(missing_crit)} rows missing criticality assignment - "
                "MUA requirements cannot be determined"
            )

        for row in self.tree.rows:
            if row.index == -1:
                continue
            if row.material_code is None and row.criticality and row.criticality.category <= 2:
                warnings.append(
                    f"Row {row.index} ({row.part_number}): Criticality {row.criticality.value} "
                    "but no Material Code - cannot enrich ratings"
                )

        return warnings
