#!/usr/bin/env python3
"""
Module: H2
Purpose: ATHENA H2 Validation Gate.

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

from athena.interpreters.models.h2 import EmbrittlementRecord
from athena.validation.models import GateProtocol, ValidationResult, ValidationStatus

__all__ = ["H2ValidationGate"]
__safety_critical__ = True


class H2ValidationGate(GateProtocol[list[EmbrittlementRecord]]):
    """
    Validates H2 embrittlement records.

    Criteria:
    - Records have required fields
    - RA values in valid range (0-100%)
    - Embrittlement index calculable
    """

    def __init__(
        self,
        min_records: int = 1,
        require_embrittlement_index: bool = False,
        ra_range: tuple[float, float] = (0.0, 100.0),
    ):
        self.min_records = min_records
        self.require_embrittlement_index = require_embrittlement_index
        self.ra_range = ra_range

    @property
    def name(self) -> str:
        return "h2_validation_gate"

    def validate(self, records: list[EmbrittlementRecord]) -> ValidationResult:
        """Validate H2 records."""
        if not records:
            return ValidationResult.fail_result(
                self.name,
                "No H2 embrittlement records extracted",
            )

        if len(records) < self.min_records:
            return ValidationResult.warn_result(
                self.name,
                f"Fewer records than expected: {len(records)} < {self.min_records}",
                records_found=len(records),
                min_expected=self.min_records,
            )

        # Validate each record
        issues: list[str] = []
        valid_count = 0
        hei_count = 0

        for record in records:
            record_issues = self._validate_record(record)
            if not record_issues:
                valid_count += 1
                if record.embrittlement_index is not None:
                    hei_count += 1
            else:
                issues.extend(record_issues)

        # Check HEI requirement
        if self.require_embrittlement_index and hei_count == 0:
            return ValidationResult.fail_result(
                self.name,
                "No records with calculable embrittlement index",
                total_records=len(records),
                valid_records=valid_count,
            )

        # Determine overall status
        if valid_count == 0:
            return ValidationResult.fail_result(
                self.name,
                "No valid H2 records",
                issues=issues[:10],  # First 10 issues
            )

        if valid_count < len(records):
            return ValidationResult.warn_result(
                self.name,
                f"Some records have issues: {valid_count}/{len(records)} valid",
                valid_records=valid_count,
                total_records=len(records),
                records_with_hei=hei_count,
            )

        return ValidationResult.pass_result(
            self.name,
            f"Validated {len(records)} H2 records",
            total_records=len(records),
            records_with_hei=hei_count,
        )

    def _validate_record(self, record: EmbrittlementRecord) -> list[str]:
        """Validate individual record, return list of issues."""
        issues: list[str] = []

        # Check material name
        if not record.material_name:
            issues.append(f"{record.record_id}: missing material name")

        # Check RA ranges
        for ra_value, ra_name in [
            (record.ra_h2, "RA_H2"),
            (record.ra_he, "RA_He"),
        ]:
            if ra_value is not None:
                if not self.ra_range[0] <= ra_value <= self.ra_range[1]:
                    issues.append(
                        f"{record.record_id}: {ra_name}={ra_value} outside valid range "
                        f"[{self.ra_range[0]}, {self.ra_range[1]}]"
                    )

        # Check for physically impossible values
        if record.embrittlement_index is not None:
            if record.embrittlement_index < -100 or record.embrittlement_index > 100:
                issues.append(
                    f"{record.record_id}: HEI={record.embrittlement_index:.1f}% outside valid range"
                )

        return issues
