#!/usr/bin/env python3
"""
Module: O2
Purpose: ATHENA O2 Interpreter.

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

import logging
import re
from typing import Optional

from athena.interpreters.protocol import DomainInterpreter
from athena.interpreters.models.o2 import (
    FlammabilityRecord,
    OxygenPhase,
    IgnitionTestType,
)
from athena.semantic.ontology import SemanticTag
from athena.semantic.mapper import SemanticMapper, DomainHint
from athena.semantic.cleaner import ValueCleaner
from athena.semantic.materials import MaterialResolver
from athena.stitching.models import LogicalTable

__all__ = ["O2Interpreter"]
__safety_critical__ = True

logger = logging.getLogger(__name__)

# Unit conversion constants
MPA_TO_PA = 1e6
PSI_TO_PA = 6894.757


class O2Interpreter(DomainInterpreter[FlammabilityRecord]):
    """
    Interprets O2 compatibility tables into FlammabilityRecords.

    Handles:
    - Material identification
    - Flammability test results
    - Compatibility classifications
    """

    def __init__(self) -> None:
        self.mapper = SemanticMapper(domain=DomainHint.O2)
        self.cleaner = ValueCleaner()
        self.resolver = MaterialResolver()
        self.logger = logging.getLogger(self.__class__.__name__)

    @property
    def domain(self) -> str:
        return "o2"

    def can_interpret(self, table: LogicalTable) -> bool:
        """Check if table contains O2-relevant data."""
        mappings = self.mapper.map_headers(table)

        # Look for O2-specific indicators
        for m in mappings:
            if m.tag == SemanticTag.COMPATIBILITY_CLASS:
                return True
            if m.tag == SemanticTag.TEST_TYPE:
                # Check for O2 test types
                if any(kw in m.header_text.lower() for kw in
                       ("promoted", "ignition", "impact", "friction", "odi", "mdi")):
                    return True

        # Check for O2 environment indicators
        for m in mappings:
            if m.tag == SemanticTag.ENVIRONMENT_GAS:
                if any(kw in m.header_text.lower() for kw in ("o2", "oxygen", "lox", "gox")):
                    return True

        return False

    def interpret(self, table: LogicalTable) -> list[FlammabilityRecord]:
        """Extract FlammabilityRecords from table."""
        records: list[FlammabilityRecord] = []

        # Map headers
        mappings = self.mapper.map_headers(table)
        tag_to_col: dict[SemanticTag, list[int]] = {}

        for m in mappings:
            if m.tag not in tag_to_col:
                tag_to_col[m.tag] = []
            tag_to_col[m.tag].append(m.col_index)

        # Process each data row
        for row_idx in range(table.header_row_count, table.row_count):
            record = self._extract_row(table, row_idx, tag_to_col)
            if record and record.is_complete:
                records.append(record)

        self.logger.info(
            f"Extracted {len(records)} FlammabilityRecords from {table.table_id}"
        )

        return records

    def _extract_row(
        self,
        table: LogicalTable,
        row_idx: int,
        tag_to_col: dict[SemanticTag, list[int]],
    ) -> Optional[FlammabilityRecord]:
        """Extract a single record from a row."""
        # Get material name (required)
        material_name = self._get_text(table, row_idx, tag_to_col, SemanticTag.MATERIAL_NAME)
        if not material_name:
            return None

        # Resolve material
        material = self.resolver.resolve(material_name)

        # Create record
        record_id = f"{table.table_id}_r{row_idx}"

        record = FlammabilityRecord(
            record_id=record_id,
            table_id=table.table_id,
            row_index=row_idx,
            material_name=material.canonical_name or material_name,
            material_uns=self._get_text(table, row_idx, tag_to_col, SemanticTag.MATERIAL_UNS) or material.uns_number,
            material_spec=self._get_text(table, row_idx, tag_to_col, SemanticTag.MATERIAL_SPEC) or material.spec_number,
            material_form=self._get_text(table, row_idx, tag_to_col, SemanticTag.MATERIAL_FORM),
            material_condition=self._get_text(table, row_idx, tag_to_col, SemanticTag.MATERIAL_CONDITION),
        )

        # Extract pressure
        pressure_text = self._get_text(table, row_idx, tag_to_col, SemanticTag.ENVIRONMENT_PRESSURE)
        if pressure_text:
            pressure = self.cleaner.clean_pressure(pressure_text)
            if pressure:
                record.pressure_pa = self._convert_pressure_to_pa(pressure[0], pressure[1])

        # Extract temperature
        temp_text = self._get_text(table, row_idx, tag_to_col, SemanticTag.ENVIRONMENT_TEMPERATURE)
        if temp_text:
            temp = self.cleaner.clean_temperature(temp_text)
            if temp:
                record.temperature_k = self._convert_temp_to_k(temp[0], temp[1])

                # This might be ignition temperature
                header = table.get_column_header_signature(tag_to_col[SemanticTag.ENVIRONMENT_TEMPERATURE][0])
                if "ignit" in header.lower() or "ait" in header.lower():
                    record.ignition_temperature_k = record.temperature_k

        # Detect oxygen phase from context
        record.oxygen_phase = self._detect_phase(table, row_idx, tag_to_col)

        # Extract compatibility class
        compat_text = self._get_text(table, row_idx, tag_to_col, SemanticTag.COMPATIBILITY_CLASS)
        if compat_text:
            record.compatibility_class = self._normalize_compatibility_class(compat_text)

        # Extract test type and result
        test_type_text = self._get_text(table, row_idx, tag_to_col, SemanticTag.TEST_TYPE)
        if test_type_text:
            record.test_type = self._parse_test_type(test_type_text)
            record.test_result = test_type_text  # May contain result info

        # Extract reference and notes
        record.reference = self._get_text(table, row_idx, tag_to_col, SemanticTag.TEST_REFERENCE)
        record.notes = self._get_text(table, row_idx, tag_to_col, SemanticTag.NOTES)

        return record

    def _get_text(
        self,
        table: LogicalTable,
        row: int,
        tag_to_col: dict[SemanticTag, list[int]],
        tag: SemanticTag,
    ) -> Optional[str]:
        """Get text from first column matching tag."""
        cols = tag_to_col.get(tag, [])
        if not cols:
            return None

        cell = table.get_cell(row, cols[0])
        if cell and cell.text:
            return cell.text.strip()
        return None

    def _detect_phase(
        self,
        table: LogicalTable,
        row_idx: int,
        tag_to_col: dict[SemanticTag, list[int]],
    ) -> OxygenPhase:
        """Detect oxygen phase from table context."""
        # Check gas environment column
        gas_cols = tag_to_col.get(SemanticTag.ENVIRONMENT_GAS, [])
        for col in gas_cols:
            cell = table.get_cell(row_idx, col)
            if cell and cell.text:
                text = cell.text.lower()
                if "lox" in text or "liquid" in text:
                    return OxygenPhase.LOX
                if "gox" in text or "gaseous" in text:
                    return OxygenPhase.GOX

        # Check table context
        if table.context_text:
            context = table.context_text.lower()
            if "lox" in context or "liquid oxygen" in context:
                return OxygenPhase.LOX
            if "gox" in context or "gaseous oxygen" in context:
                return OxygenPhase.GOX

        return OxygenPhase.UNKNOWN

    def _normalize_compatibility_class(self, text: str) -> str:
        """Normalize compatibility class to standard form."""
        text = text.strip().upper()

        # Handle common formats
        if re.match(r"^[A-D]$", text):
            return text

        # Handle "Class A", "Category B", etc.
        match = re.search(r"(?:class|category|rating)?\s*([A-D])", text, re.IGNORECASE)
        if match:
            return match.group(1).upper()

        # Return as-is if can't normalize
        return text

    def _parse_test_type(self, text: str) -> Optional[IgnitionTestType]:
        """Parse test type from text."""
        text_lower = text.lower()

        if "promoted" in text_lower:
            return IgnitionTestType.PROMOTED_IGNITION
        if "mechanical" in text_lower and "impact" in text_lower:
            return IgnitionTestType.MECHANICAL_IMPACT
        if "particle" in text_lower and "impact" in text_lower:
            return IgnitionTestType.PARTICLE_IMPACT
        if "pneumatic" in text_lower and "impact" in text_lower:
            return IgnitionTestType.PNEUMATIC_IMPACT
        if "friction" in text_lower:
            return IgnitionTestType.FRICTION
        if "auto" in text_lower and "ignit" in text_lower:
            return IgnitionTestType.AUTOIGNITION
        if "odi" in text_lower or "mdi" in text_lower:
            return IgnitionTestType.MECHANICAL_IMPACT

        return IgnitionTestType.OTHER

    def _convert_pressure_to_pa(self, value: float, unit: str) -> float:
        """Convert pressure to Pascals."""
        unit_lower = unit.lower()
        if unit_lower == "mpa":
            return value * MPA_TO_PA
        elif unit_lower == "psi" or unit_lower == "psia" or unit_lower == "psig":
            return value * PSI_TO_PA
        elif unit_lower == "bar":
            return value * 1e5
        elif unit_lower == "atm":
            return value * 101325
        return value

    def _convert_temp_to_k(self, value: float, unit: str) -> float:
        """Convert temperature to Kelvin."""
        unit_upper = unit.upper()
        if unit_upper == "C":
            return value + 273.15
        elif unit_upper == "F":
            return (value - 32) * 5/9 + 273.15
        return value
