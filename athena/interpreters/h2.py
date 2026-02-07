#!/usr/bin/env python3
"""
Module: H2
Purpose: ATHENA H2 Interpreter.

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
from typing import Optional

from athena.interpreters.protocol import DomainInterpreter
from athena.interpreters.models.h2 import EmbrittlementRecord
from athena.semantic.ontology import SemanticTag
from athena.semantic.mapper import SemanticMapper, DomainHint
from athena.semantic.cleaner import ValueCleaner
from athena.semantic.materials import MaterialResolver
from athena.stitching.models import LogicalTable

__all__ = ["H2Interpreter"]
__safety_critical__ = True

logger = logging.getLogger(__name__)

# Unit conversion constants
MPA_TO_PA = 1e6
KSI_TO_PA = 6.894757e6
PSI_TO_PA = 6894.757


class H2Interpreter(DomainInterpreter[EmbrittlementRecord]):
    """
    Interprets H2 compatibility tables into EmbrittlementRecords.

    Handles:
    - Material identification
    - Property extraction with SI normalization
    - Embrittlement index calculation
    """

    def __init__(self) -> None:
        self.mapper = SemanticMapper(domain=DomainHint.H2)
        self.cleaner = ValueCleaner()
        self.resolver = MaterialResolver()
        self.logger = logging.getLogger(self.__class__.__name__)

    @property
    def domain(self) -> str:
        return "h2"

    def can_interpret(self, table: LogicalTable) -> bool:
        """Check if table contains H2-relevant data."""
        mappings = self.mapper.map_headers(table)

        # Look for H2-specific indicators
        for m in mappings:
            if m.tag in (
                SemanticTag.PROPERTY_RA,
                SemanticTag.PROPERTY_EMBRITTLEMENT_INDEX,
                SemanticTag.PROPERTY_RATIO,
            ):
                return True

        # Check for environment indicators
        for m in mappings:
            if m.tag == SemanticTag.ENVIRONMENT_GAS:
                # Check if header mentions H2
                if "h2" in m.header_text.lower() or "hydrogen" in m.header_text.lower():
                    return True

        return False

    def interpret(self, table: LogicalTable) -> list[EmbrittlementRecord]:
        """Extract EmbrittlementRecords from table."""
        records: list[EmbrittlementRecord] = []

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
            f"Extracted {len(records)} EmbrittlementRecords from {table.table_id}"
        )

        return records

    def _extract_row(
        self,
        table: LogicalTable,
        row_idx: int,
        tag_to_col: dict[SemanticTag, list[int]],
    ) -> Optional[EmbrittlementRecord]:
        """Extract a single record from a row."""
        # Get material name (required)
        material_name = self._get_text(table, row_idx, tag_to_col, SemanticTag.MATERIAL_NAME)
        if not material_name:
            return None

        # Resolve material
        material = self.resolver.resolve(material_name)

        # Create record
        record_id = f"{table.table_id}_r{row_idx}"

        record = EmbrittlementRecord(
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

        # Extract RA values
        # This is simplified - in practice, would need to distinguish H2 vs He columns
        ra_cols = tag_to_col.get(SemanticTag.PROPERTY_RA, [])
        if len(ra_cols) >= 2:
            # Assume first is H2, second is He (common convention)
            ra_h2_text = self._get_cell_text(table, row_idx, ra_cols[0])
            ra_he_text = self._get_cell_text(table, row_idx, ra_cols[1])

            if ra_h2_text:
                record.ra_h2 = self.cleaner.clean_percentage(ra_h2_text)
            if ra_he_text:
                record.ra_he = self.cleaner.clean_percentage(ra_he_text)
        elif len(ra_cols) == 1:
            # Single RA column - need context to determine environment
            ra_text = self._get_cell_text(table, row_idx, ra_cols[0])
            header = table.get_column_header_signature(ra_cols[0])

            if "h2" in header.lower() or "hydrogen" in header.lower():
                record.ra_h2 = self.cleaner.clean_percentage(ra_text)
            elif "he" in header.lower() or "air" in header.lower():
                record.ra_he = self.cleaner.clean_percentage(ra_text)

        # Extract elongation
        el_cols = tag_to_col.get(SemanticTag.PROPERTY_ELONGATION, [])
        if len(el_cols) >= 2:
            el_h2_text = self._get_cell_text(table, row_idx, el_cols[0])
            el_he_text = self._get_cell_text(table, row_idx, el_cols[1])

            if el_h2_text:
                record.elongation_h2 = self.cleaner.clean_percentage(el_h2_text)
            if el_he_text:
                record.elongation_he = self.cleaner.clean_percentage(el_he_text)

        # Extract tensile properties
        uts_cols = tag_to_col.get(SemanticTag.PROPERTY_TENSILE, [])
        if uts_cols:
            for col in uts_cols:
                uts_text = self._get_cell_text(table, row_idx, col)
                header = table.get_column_header_signature(col)

                if uts_text:
                    uts_val = self.cleaner.clean(uts_text)
                    if uts_val:
                        # Assume MPa unless otherwise specified
                        pa_value = uts_val.value * MPA_TO_PA

                        if "h2" in header.lower():
                            record.uts_h2_pa = pa_value
                        else:
                            record.uts_he_pa = pa_value

        # Extract strain rate
        sr_text = self._get_text(table, row_idx, tag_to_col, SemanticTag.TEST_STRAIN_RATE)
        if sr_text:
            sr = self.cleaner.clean(sr_text)
            if sr:
                record.strain_rate_s = sr.value

        # Extract test type
        record.test_type = self._get_text(table, row_idx, tag_to_col, SemanticTag.TEST_TYPE)
        record.specimen_type = self._get_text(table, row_idx, tag_to_col, SemanticTag.TEST_SPECIMEN)
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

        return self._get_cell_text(table, row, cols[0])

    def _get_cell_text(
        self,
        table: LogicalTable,
        row: int,
        col: int,
    ) -> Optional[str]:
        """Get cell text."""
        cell = table.get_cell(row, col)
        if cell and cell.text:
            return cell.text.strip()
        return None

    def _convert_pressure_to_pa(self, value: float, unit: str) -> float:
        """Convert pressure to Pascals."""
        unit_lower = unit.lower()
        if unit_lower == "mpa":
            return value * MPA_TO_PA
        elif unit_lower == "ksi":
            return value * KSI_TO_PA
        elif unit_lower == "psi":
            return value * PSI_TO_PA
        elif unit_lower == "gpa":
            return value * 1e9
        elif unit_lower == "bar":
            return value * 1e5
        elif unit_lower == "atm":
            return value * 101325
        return value  # Assume Pa

    def _convert_temp_to_k(self, value: float, unit: str) -> float:
        """Convert temperature to Kelvin."""
        unit_upper = unit.upper()
        if unit_upper == "C":
            return value + 273.15
        elif unit_upper == "F":
            return (value - 32) * 5/9 + 273.15
        return value  # Assume K
