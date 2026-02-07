#!/usr/bin/env python3
"""
Module: O2
Purpose: ATHENA O2 Validation Gate.

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

from athena.interpreters.models.o2 import FlammabilityRecord
from athena.validation.models import GateProtocol, ValidationResult, ValidationStatus

__all__ = ["O2ValidationGate"]
__safety_critical__ = True


class O2ValidationGate(GateProtocol[list[FlammabilityRecord]]):
    """
    Validates O2 flammability records.

    Criteria:
    - Records have required fields
    - Compatibility classes are valid
    - Temperature values in valid range
    """

    def __init__(
        self,
        min_records: int = 1,
        valid_classes: set[str] = None,
        temp_range_k: tuple[float, float] = (50.0, 1500.0),
    ):
        self.min_records = min_records
        self.valid_classes = valid_classes or {"A", "B", "C", "D"}
        self.temp_range_k = temp_range_k

    @property
    def name(self) -> str:
        return "o2_validation_gate"

    def validate(self, records: list[FlammabilityRecord]) -> ValidationResult:
        """Validate O2 records."""
        if not records:
            return ValidationResult.fail_result(
                self.name,
                "No O2 flammability records extracted",
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
        with_class_count = 0

        for record in records:
            record_issues = self._validate_record(record)
            if not record_issues:
                valid_count += 1
                if record.compatibility_class:
                    with_class_count += 1
            else:
                issues.extend(record_issues)

        # Determine overall status
        if valid_count == 0:
            return ValidationResult.fail_result(
                self.name,
                "No valid O2 records",
                issues=issues[:10],
            )

        if valid_count < len(records):
            return ValidationResult.warn_result(
                self.name,
                f"Some records have issues: {valid_count}/{len(records)} valid",
                valid_records=valid_count,
                total_records=len(records),
                records_with_class=with_class_count,
            )

        return ValidationResult.pass_result(
            self.name,
            f"Validated {len(records)} O2 records",
            total_records=len(records),
            records_with_class=with_class_count,
        )

    def _validate_record(self, record: FlammabilityRecord) -> list[str]:
        """Validate individual record, return list of issues."""
        issues: list[str] = []

        # Check material name
        if not record.material_name:
            issues.append(f"{record.record_id}: missing material name")

        # Check compatibility class
        if record.compatibility_class:
            if record.compatibility_class.upper() not in self.valid_classes:
                issues.append(
                    f"{record.record_id}: invalid compatibility class "
                    f"'{record.compatibility_class}'"
                )

        # Check temperature ranges
        for temp_value, temp_name in [
            (record.temperature_k, "temperature"),
            (record.ignition_temperature_k, "ignition_temperature"),
        ]:
            if temp_value is not None:
                if not self.temp_range_k[0] <= temp_value <= self.temp_range_k[1]:
                    issues.append(
                        f"{record.record_id}: {temp_name}={temp_value}K outside valid range "
                        f"[{self.temp_range_k[0]}, {self.temp_range_k[1]}]K"
                    )

        return issues
