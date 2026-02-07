#!/usr/bin/env python3
"""
Module: Extraction
Purpose: ATHENA Extraction Validation Gate.

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

from athena.core.models.result import ExtractionResult
from athena.validation.models import GateProtocol, ValidationResult, ValidationStatus

__all__ = ["ExtractionGate"]
__safety_critical__ = True


class ExtractionGate(GateProtocol[ExtractionResult]):
    """
    Validates extraction results.

    Criteria:
    - At least one table extracted
    - No critical errors
    - Minimum coverage threshold
    """

    def __init__(
        self,
        min_tables: int = 1,
        min_coverage: float = 0.5,
        max_error_rate: float = 0.3,
    ):
        self.min_tables = min_tables
        self.min_coverage = min_coverage
        self.max_error_rate = max_error_rate

    @property
    def name(self) -> str:
        return "extraction_gate"

    def validate(self, result: ExtractionResult) -> ValidationResult:
        """Validate extraction result."""
        # Check for tables
        if len(result.tables) == 0:
            return ValidationResult.fail_result(
                self.name,
                "No tables extracted from document",
                pages_scanned=result.pages_scanned,
            )

        if len(result.tables) < self.min_tables:
            return ValidationResult.warn_result(
                self.name,
                f"Fewer tables than expected: {len(result.tables)} < {self.min_tables}",
                tables_found=len(result.tables),
                min_expected=self.min_tables,
            )

        # Check error rate
        if result.tables:
            error_count = sum(1 for t in result.tables if t.error)
            error_rate = error_count / len(result.tables)

            if error_rate > self.max_error_rate:
                return ValidationResult.fail_result(
                    self.name,
                    f"High error rate: {error_rate:.1%} > {self.max_error_rate:.1%}",
                    error_count=error_count,
                    total_tables=len(result.tables),
                    error_rate=error_rate,
                )

        # Check coverage
        coverage_values = [t.structural_coverage for t in result.tables if not t.error]
        if coverage_values:
            avg_coverage = sum(coverage_values) / len(coverage_values)

            if avg_coverage < self.min_coverage:
                return ValidationResult.warn_result(
                    self.name,
                    f"Low average coverage: {avg_coverage:.1%} < {self.min_coverage:.1%}",
                    avg_coverage=avg_coverage,
                    min_coverage=self.min_coverage,
                )

        return ValidationResult.pass_result(
            self.name,
            f"Extracted {len(result.tables)} tables successfully",
            tables_extracted=len(result.tables),
            pages_scanned=result.pages_scanned,
        )
