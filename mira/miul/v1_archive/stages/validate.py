#!/usr/bin/env python3
"""
Module: Validate
Purpose: Stage 6 - Validate (DT Verification)

BoundState AI 2025
Version: 1.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Fran OpenAI 5 <noreply@openai.com>
Co-Authored-By: Grok 4.0 <noreply@x.ai>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: SWE-013, SWE-033, NASA-STD-6016C
Safety Critical: True
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from .parse_dt import DTHierarchy
from .merge import MIULDocument, MIULRow

logger = logging.getLogger(__name__)

__all__ = ["validate_against_dt", "ValidationResult", "ValidationIssue"]
__safety_critical__ = True


@dataclass
class ValidationIssue:
    """Single validation issue found during verification."""
    severity: str  # ERROR, WARNING, INFO
    category: str  # MISSING_PN, EXTRA_PN, WRONG_PARENT, WRONG_NHA, etc.
    part_number: str
    message: str
    expected: str = ""
    actual: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "severity": self.severity,
            "category": self.category,
            "part_number": self.part_number,
            "message": self.message,
            "expected": self.expected,
            "actual": self.actual,
        }


@dataclass
class ValidationResult:
    """Complete validation result for MIUL against DT."""
    status: str  # PASS, FAIL, WARNING
    miul_number: str
    total_dt_nodes: int = 0
    total_miul_rows: int = 0
    matched_count: int = 0
    missing_count: int = 0
    extra_count: int = 0
    issues: List[ValidationIssue] = field(default_factory=list)

    # Metadata for traceability (SWE-033)
    validated_at: str = ""
    dt_source: str = ""
    miul_source: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status,
            "miul_number": self.miul_number,
            "summary": {
                "total_dt_nodes": self.total_dt_nodes,
                "total_miul_rows": self.total_miul_rows,
                "matched": self.matched_count,
                "missing_from_miul": self.missing_count,
                "extra_in_miul": self.extra_count,
            },
            "issues": [i.to_dict() for i in self.issues],
            "metadata": {
                "validated_at": self.validated_at,
                "dt_source": self.dt_source,
                "miul_source": self.miul_source,
                "stage": "validate",
            }
        }

    def save(self, path: Path) -> None:
        """Save validation result to JSON file."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=2)
        logger.info(f"[Stage 6] Saved validation result to {path}")

    @property
    def errors(self) -> List[ValidationIssue]:
        return [i for i in self.issues if i.severity == "ERROR"]

    @property
    def warnings(self) -> List[ValidationIssue]:
        return [i for i in self.issues if i.severity == "WARNING"]

    def summary(self) -> str:
        """Human-readable summary of validation result."""
        lines = [
            f"=== MIUL Validation: {self.status} ===",
            f"MIUL Number: {self.miul_number}",
            f"DT Nodes: {self.total_dt_nodes}",
            f"MIUL Rows: {self.total_miul_rows}",
            f"Matched: {self.matched_count}",
            f"Missing from MIUL: {self.missing_count}",
            f"Extra in MIUL: {self.extra_count}",
            f"Errors: {len(self.errors)}",
            f"Warnings: {len(self.warnings)}",
        ]

        if self.errors:
            lines.append("\n--- Errors ---")
            for issue in self.errors[:10]:
                lines.append(f"  [{issue.category}] {issue.part_number}: {issue.message}")
            if len(self.errors) > 10:
                lines.append(f"  ... and {len(self.errors) - 10} more errors")

        if self.warnings:
            lines.append("\n--- Warnings ---")
            for issue in self.warnings[:5]:
                lines.append(f"  [{issue.category}] {issue.part_number}: {issue.message}")
            if len(self.warnings) > 5:
                lines.append(f"  ... and {len(self.warnings) - 5} more warnings")

        return "\n".join(lines)


def validate_against_dt(
    miul: MIULDocument,
    hierarchy: DTHierarchy,
    output_path: Optional[Path] = None,
) -> ValidationResult:
    """Validate MIUL document against Drawing Tree hierarchy.

    Stage 6 of the MIUL pipeline. Ensures MIUL structure matches
    the single source of truth (Drawing Tree).

    Args:
        miul: MIULDocument from Stage 4/5
        hierarchy: DTHierarchy from Stage 1
        output_path: Where to save validation_result.json

    Returns:
        ValidationResult with pass/fail and detailed issues

    Compliance: SWE-013 (Traceability), NASA-STD-6016C
    """
    logger.info(f"[Stage 6] Validating MIUL {miul.miul_number} against DT")

    result = ValidationResult(
        status="PENDING",
        miul_number=miul.miul_number,
        validated_at=datetime.now().isoformat(),
        dt_source=hierarchy.source_file,
        miul_source="miul.json",
    )

    # Collect part numbers from each source
    dt_pns: Set[str] = set(hierarchy.nodes.keys())
    result.total_dt_nodes = len(dt_pns)

    # MIUL part numbers (excluding headers and EOF)
    miul_pns: Set[str] = set()
    miul_rows_by_pn: Dict[str, MIULRow] = {}

    for row in miul.rows:
        if row.row_type in ("MIUL_ID", "EOF"):
            continue
        if row.part_number:
            miul_pns.add(row.part_number)
            miul_rows_by_pn[row.part_number] = row

    result.total_miul_rows = len(miul_pns)

    # === Check 1: Missing from MIUL ===
    missing = dt_pns - miul_pns
    result.missing_count = len(missing)

    for pn in missing:
        node = hierarchy.nodes[pn]
        result.issues.append(ValidationIssue(
            severity="ERROR",
            category="MISSING_PN",
            part_number=pn,
            message=f"Part number in DT but not in MIUL",
            expected=f"Should be in MIUL (parent={node.parent_pn})",
            actual="Not found",
        ))

    # === Check 2: Extra in MIUL (not in DT) ===
    # Subparts from EPL are expected to be "extra" - they're not in DT
    extra = miul_pns - dt_pns
    subpart_pns = {row.part_number for row in miul.rows if row.row_type == "SUBPART"}
    true_extra = extra - subpart_pns

    result.extra_count = len(true_extra)

    for pn in true_extra:
        row = miul_rows_by_pn.get(pn)
        result.issues.append(ValidationIssue(
            severity="WARNING",
            category="EXTRA_PN",
            part_number=pn,
            message=f"Part number in MIUL but not in DT (row_type={row.row_type if row else 'unknown'})",
            expected="Should be in DT hierarchy",
            actual=f"Found in MIUL at index {row.index if row else 'unknown'}",
        ))

    # === Check 3: Matched count ===
    result.matched_count = len(dt_pns & miul_pns)

    # === Check 4: Parent-child relationships ===
    # Build index mapping from MIUL
    pn_to_index: Dict[str, int] = {}
    index_to_pn: Dict[int, str] = {}

    for row in miul.rows:
        if row.part_number and row.row_type not in ("MIUL_ID", "EOF"):
            pn_to_index[row.part_number] = row.index
            index_to_pn[row.index] = row.part_number

    # Check each DT node's parent relationship
    for pn, node in hierarchy.nodes.items():
        if pn not in miul_rows_by_pn:
            continue  # Already flagged as missing

        miul_row = miul_rows_by_pn[pn]

        if node.parent_pn:
            # Node has a parent in DT - check MIUL parent matches
            expected_parent_index = pn_to_index.get(node.parent_pn)

            if expected_parent_index is None:
                # Parent not in MIUL (will be caught by MISSING_PN)
                continue

            if miul_row.parent != expected_parent_index:
                actual_parent_pn = index_to_pn.get(miul_row.parent, "unknown")
                result.issues.append(ValidationIssue(
                    severity="ERROR",
                    category="WRONG_PARENT",
                    part_number=pn,
                    message=f"Parent mismatch",
                    expected=f"Parent index {expected_parent_index} ({node.parent_pn})",
                    actual=f"Parent index {miul_row.parent} ({actual_parent_pn})",
                ))

    # === Check 5: NHA logic per MAPTIS spec ===
    for row in miul.rows:
        if row.row_type == "MIUL_ID":
            # Header rows should have blank NHA
            if row.nha:
                result.issues.append(ValidationIssue(
                    severity="ERROR",
                    category="WRONG_NHA",
                    part_number=row.part_number,
                    message="Header row should have blank NHA",
                    expected="",
                    actual=row.nha,
                ))

        elif row.row_type == "SUBPART":
            # Subparts should have blank NHA
            if row.nha:
                result.issues.append(ValidationIssue(
                    severity="WARNING",
                    category="WRONG_NHA",
                    part_number=row.part_number,
                    message="Subpart should have blank NHA per MAPTIS spec",
                    expected="",
                    actual=row.nha,
                ))

        elif row.parent == 2 and row.row_type in ("ASSEMBLY", "PART"):
            # Top-level (parent=header): NHA should be MIUL Number
            if row.nha != miul.miul_number:
                result.issues.append(ValidationIssue(
                    severity="ERROR",
                    category="WRONG_NHA",
                    part_number=row.part_number,
                    message="Top-level assembly NHA should be MIUL Number",
                    expected=miul.miul_number,
                    actual=row.nha,
                ))

    # === Check 6: Index ordering (parents before children) ===
    for row in miul.rows:
        if row.row_type in ("MIUL_ID", "EOF"):
            continue

        # Parent index should be less than child index (DFS guarantee)
        if row.parent > 0 and row.index <= row.parent:
            result.issues.append(ValidationIssue(
                severity="ERROR",
                category="INDEX_ORDER",
                part_number=row.part_number,
                message="Child index must be greater than parent index",
                expected=f"Index > {row.parent}",
                actual=f"Index = {row.index}",
            ))

    # === Determine final status ===
    if result.errors:
        result.status = "FAIL"
    elif result.warnings:
        result.status = "WARNING"
    else:
        result.status = "PASS"

    logger.info(f"[Stage 6] Validation {result.status}: "
                f"{result.matched_count}/{result.total_dt_nodes} matched, "
                f"{len(result.errors)} errors, {len(result.warnings)} warnings")

    # Save if output path provided
    if output_path:
        result.save(output_path)

    return result


def validate_miul_structure(miul: MIULDocument) -> List[ValidationIssue]:
    """Validate internal MIUL structure without DT comparison.

    Quick sanity checks on MIUL document structure.

    Args:
        miul: MIULDocument to validate

    Returns:
        List of ValidationIssue (structural issues only)
    """
    issues = []

    # Check header rows exist
    header_rows = [r for r in miul.rows if r.row_type == "MIUL_ID"]
    if len(header_rows) < 2:
        issues.append(ValidationIssue(
            severity="ERROR",
            category="STRUCTURE",
            part_number="",
            message="MIUL must have 2 header rows (Index 1 and 2)",
            expected="2 header rows",
            actual=f"{len(header_rows)} header rows",
        ))

    # Check EOF marker exists
    eof_rows = [r for r in miul.rows if r.row_type == "EOF"]
    if not eof_rows:
        issues.append(ValidationIssue(
            severity="WARNING",
            category="STRUCTURE",
            part_number="",
            message="MIUL should have EOF marker (Index=-1)",
            expected="EOF row with index=-1",
            actual="No EOF row found",
        ))

    # Check for duplicate indices
    indices = [r.index for r in miul.rows if r.index > 0]
    if len(indices) != len(set(indices)):
        duplicates = [i for i in indices if indices.count(i) > 1]
        issues.append(ValidationIssue(
            severity="ERROR",
            category="DUPLICATE_INDEX",
            part_number="",
            message=f"Duplicate indices found: {set(duplicates)}",
            expected="Unique indices",
            actual=f"Duplicates: {set(duplicates)}",
        ))

    # Check parent references are valid
    valid_indices = set(indices) | {0, 2}  # 0 for headers, 2 for top-level parent
    for row in miul.rows:
        if row.row_type == "EOF":
            continue
        if row.parent not in valid_indices:
            issues.append(ValidationIssue(
                severity="ERROR",
                category="INVALID_PARENT",
                part_number=row.part_number,
                message=f"Parent index {row.parent} does not exist",
                expected=f"Valid index from {valid_indices}",
                actual=str(row.parent),
            ))

    return issues
