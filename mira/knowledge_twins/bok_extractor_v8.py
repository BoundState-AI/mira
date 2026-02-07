#!/usr/bin/env python3
"""
Module: Bok Extractor V8
Purpose: Single test result for a material in a specific environment.

BoundState AI 2025
Version: 1.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Fran OpenAI 5 <noreply@openai.com>
Co-Authored-By: Grok 4.0 <noreply@x.ai>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: SWE-013, NASA-STD-8739.8B
Safety Critical: True
"""

from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Optional

import pdfplumber
from pydantic import BaseModel, Field
import uuid

__all__ = [
    "BOKExtractorV8",
    "ExtractedRecord",
    "MaterialTestResult",
    "extract_bok",
]
__safety_critical__ = True

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class GasType(str, Enum):
    H2 = "H2"
    O2 = "O2"


class RecordType(str, Enum):
    MATERIAL_COMPATIBILITY = "material_compatibility"
    PAIRED_TEST_COMPARISON = "paired_test_comparison"
    MECHANICAL_PROPERTIES = "mechanical_properties"
    PERMEABILITY_DATA = "permeability_data"
    COMPOSITION_DATA = "composition_data"
    FLAMMABILITY_RATING = "flammability_rating"
    TEST_PROCEDURE = "test_procedure"
    GENERIC_PROPERTY = "generic_property"


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class MaterialTestResult(BaseModel):
    """Single test result for a material in a specific environment."""
    model_config = {"extra": "forbid"}

    environment: str  # "69 MPa He", "69 MPa H2", "Air", etc.
    yield_strength_mpa: Optional[float] = None  # Sy
    ultimate_strength_mpa: Optional[float] = None  # Su
    elongation_uniform_pct: Optional[float] = None  # El_u
    elongation_total_pct: Optional[float] = None  # El_t
    reduction_of_area_pct: Optional[float] = None  # RA
    fracture_toughness_mpa_sqrt_m: Optional[float] = None  # KIc, KIH, KTH
    strain_rate_per_s: Optional[str] = None
    temperature_k: Optional[float] = None
    displacement_rate_mm_s: Optional[str] = None


class ExtractedRecord(BaseModel):
    """Extracted material compatibility record with calculated embrittlement."""
    model_config = {"extra": "forbid"}

    record_type: RecordType
    gas_type: GasType

    # Material identification
    material_name: str
    material_spec: Optional[str] = None  # UNS, heat number, etc.
    heat_treatment: Optional[str] = None
    product_form: Optional[str] = None

    # For paired comparison tables - the key data
    baseline_result: Optional[MaterialTestResult] = None  # He or Air
    hydrogen_result: Optional[MaterialTestResult] = None  # H2

    # Calculated embrittlement metrics
    embrittlement_index_ra: Optional[float] = None  # RA_H2 / RA_baseline
    embrittlement_index_el: Optional[float] = None  # El_H2 / El_baseline
    strength_ratio: Optional[float] = None  # Su_H2 / Su_baseline

    # For non-paired data
    test_results: list[MaterialTestResult] = Field(default_factory=list)

    # Composition (when available)
    composition: Optional[dict[str, float]] = None  # {"Fe": 70.5, "Cr": 18.0, ...}

    # Generic properties
    property_name: Optional[str] = None
    property_value: Optional[str] = None
    property_units: Optional[str] = None

    # Conditions
    pressure_mpa: Optional[float] = None
    temperature_k: Optional[float] = None
    thermal_precharging: Optional[str] = None

    # O2-specific
    ait_k: Optional[float] = None
    mechanical_impact_result: Optional[str] = None
    flammability_rating: Optional[str] = None

    # Notes and references
    notes: Optional[str] = None
    references: list[str] = Field(default_factory=list)

    # Provenance - required
    source_document: str
    source_page: int
    source_table_id: str
    raw_text: str  # For audit trail


class ExtractedTable(BaseModel):
    """A table extracted from a BOK document."""
    model_config = {"extra": "forbid"}

    table_id: str
    source_document: str
    source_page: int
    gas_type: GasType

    headers: list[str]
    rows: list[list[str]]
    raw_text: str

    table_type: RecordType = RecordType.GENERIC_PROPERTY
    is_paired_comparison: bool = False
    has_multivalue_cells: bool = False

    records: list[ExtractedRecord] = Field(default_factory=list)
    extraction_method: str = "pattern"  # "pattern" or "llm"
    extraction_timestamp: str = Field(
        default_factory=lambda: datetime.now().isoformat()
    )


# ---------------------------------------------------------------------------
# Table Detection and Classification
# ---------------------------------------------------------------------------

def detect_paired_comparison(headers: list[str], rows: list[list[str]]) -> bool:
    """
    Detect if table contains paired He vs H2 comparisons.

    Look for:
    - "Test environment" column with He/H2 pairs
    - Multi-line cells with paired values
    """
    header_text = " ".join(headers).lower()

    # Must have test environment column
    if not re.search(r"test\s*environ|environment", header_text):
        return False

    # Check first few rows for He/H2 pattern in cells
    for row in rows[:5]:
        row_text = " ".join(str(c) for c in row).lower()
        # Look for He and H2 in same row (stacked in cells)
        if re.search(r"(he|helium)", row_text) and re.search(r"h\s*2|hydrogen", row_text):
            return True
        # Or Air vs H2
        if re.search(r"\bair\b", row_text) and re.search(r"h\s*2|hydrogen", row_text):
            return True

    return False


def detect_multivalue_cells(rows: list[list[str]]) -> bool:
    """Check if cells contain multiple values (newline-separated)."""
    for row in rows[:5]:
        for cell in row:
            if cell and "\n" in cell:
                # Check if it looks like paired values, not just wrapped text
                lines = [l.strip() for l in cell.split("\n") if l.strip()]
                if len(lines) >= 2:
                    # Check if lines look like values (numbers, short codes)
                    numeric_lines = sum(1 for l in lines if re.match(r"^[\d.\-—–]+", l))
                    if numeric_lines >= 2:
                        return True
    return False


def classify_table(headers: list[str], rows: list[list[str]], gas_type: GasType) -> RecordType:
    """Classify table type based on headers."""
    header_text = " ".join(headers).lower()

    # Composition tables
    if re.search(r"\b(fe|cr|ni|mo|mn|si|c)\b.*\b(fe|cr|ni|mo|mn|si|c)\b", header_text):
        return RecordType.COMPOSITION_DATA

    # Permeability/diffusivity tables
    if re.search(r"(permeab|diffus|solubil)", header_text):
        return RecordType.PERMEABILITY_DATA

    # Mechanical test tables (most common in Sandia)
    if re.search(r"(s\s*y|s\s*u|ra\s*\(%\)|el\s*[tu]|strain\s*rate)", header_text):
        return RecordType.MECHANICAL_PROPERTIES

    # Fracture toughness
    if re.search(r"k\s*(ic|ih|th|q)", header_text):
        return RecordType.MECHANICAL_PROPERTIES

    # O2-specific
    if gas_type == GasType.O2:
        if re.search(r"(ait|ignition|flammab|impact)", header_text):
            return RecordType.FLAMMABILITY_RATING

    return RecordType.GENERIC_PROPERTY


# ---------------------------------------------------------------------------
# Cell Parsing Utilities
# ---------------------------------------------------------------------------

def parse_float(val: str) -> Optional[float]:
    """Parse float from string, handling common formats."""
    if not val:
        return None
    val = val.strip()
    # Handle dashes meaning "no value"
    if val in ("—", "–", "-", "nr", "NR", "*", "†", "‡"):
        return None
    # Remove footnote markers
    val = re.sub(r"[*†‡§]", "", val)
    # Extract first number
    match = re.search(r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?", val)
    if match:
        try:
            return float(match.group())
        except ValueError:
            return None
    return None


def split_multivalue_cell(cell: str) -> list[str]:
    """Split cell with multiple values into list."""
    if not cell:
        return []
    lines = [l.strip() for l in cell.split("\n") if l.strip()]
    return lines


def find_column_index(headers: list[str], patterns: list[str]) -> Optional[int]:
    """Find column index matching any pattern."""
    for i, header in enumerate(headers):
        header_lower = header.lower()
        for pattern in patterns:
            if re.search(pattern, header_lower):
                return i
    return None


# Column pattern definitions
COL_MATERIAL = [r"material", r"alloy", r"steel", r"heat\b"]
COL_ENVIRONMENT = [r"test\s*environ", r"environment"]
COL_STRAIN_RATE = [r"strain\s*rate"]
COL_YIELD = [r"s\s*y\b", r"yield"]
COL_ULTIMATE = [r"s\s*u\b", r"ultimate"]
COL_ELONGATION_U = [r"el\s*u", r"uniform.*elong"]
COL_ELONGATION_T = [r"el\s*t", r"total.*elong"]
COL_RA = [r"\bra\b", r"reduction.*area"]
COL_TOUGHNESS = [r"k\s*(ic|ih|th|q)", r"toughness", r"threshold"]
COL_PRECHARGE = [r"precharg", r"thermal"]
COL_REF = [r"ref\.?$", r"reference"]
COL_TEMP = [r"temp", r"\(k\)"]
COL_DISPL_RATE = [r"displ.*rate", r"displacement"]
COL_SPECIMEN = [r"specimen"]


# ---------------------------------------------------------------------------
# Paired Comparison Extraction (The Key Logic)
# ---------------------------------------------------------------------------

def normalize_environment_lines(env_lines: list[str]) -> list[str]:
    """
    Fix PDF subscript issue where H2 becomes "H" + "2" on separate lines.

    Input:  ["Air", "6.9 MPa H", "2"]
    Output: ["Air", "6.9 MPa H2"]
    """
    result = []
    i = 0
    while i < len(env_lines):
        line = env_lines[i]
        # Check if line ends with "H" and next line is just "2"
        if (line.rstrip().endswith("H") and
            i + 1 < len(env_lines) and
            env_lines[i + 1].strip() == "2"):
            # Merge: "6.9 MPa H" + "2" -> "6.9 MPa H2"
            result.append(line.rstrip() + "2")
            i += 2  # Skip the "2" line
        else:
            result.append(line)
            i += 1
    return result


def extract_paired_records(
    table: ExtractedTable,
    headers: list[str],
    rows: list[list[str]],
) -> list[ExtractedRecord]:
    """
    Extract records from paired He vs H2 comparison tables.

    These tables have multi-value cells where:
    - Row 1 in cell = baseline (He or Air)
    - Row 2 in cell = H2 result

    Note: PDF subscripts often split H2 as "H" + "2" on separate lines.
    """
    records = []

    # Find column indices
    mat_col = find_column_index(headers, COL_MATERIAL) or 0
    env_col = find_column_index(headers, COL_ENVIRONMENT)
    sy_col = find_column_index(headers, COL_YIELD)
    su_col = find_column_index(headers, COL_ULTIMATE)
    el_u_col = find_column_index(headers, COL_ELONGATION_U)
    el_t_col = find_column_index(headers, COL_ELONGATION_T)
    ra_col = find_column_index(headers, COL_RA)
    rate_col = find_column_index(headers, COL_STRAIN_RATE)
    precharge_col = find_column_index(headers, COL_PRECHARGE)
    ref_col = find_column_index(headers, COL_REF)

    for row in rows:
        if not row or len(row) <= mat_col:
            continue

        # Get material name (may be multi-line with spec info)
        mat_cell = row[mat_col] if mat_col < len(row) else ""
        mat_lines = split_multivalue_cell(mat_cell)
        if not mat_lines:
            continue

        material_name = mat_lines[0]
        material_spec = mat_lines[1] if len(mat_lines) > 1 else None

        # Skip header rows that leaked through
        if material_name.lower() in ("material", "steel", "alloy", "heat"):
            continue

        # Parse environment column to determine baseline vs H2
        env_cell = row[env_col] if env_col and env_col < len(row) else ""
        env_lines_raw = split_multivalue_cell(env_cell)

        # Fix PDF subscript issue: "H" + "2" -> "H2"
        env_lines = normalize_environment_lines(env_lines_raw)

        if len(env_lines) < 2:
            # Not a paired comparison row
            continue

        # Determine which line is baseline and which is H2
        baseline_idx = None
        h2_idx = None
        for i, env in enumerate(env_lines):
            env_lower = env.lower()
            if re.search(r"h\s*2|h2|hydrogen", env_lower):
                h2_idx = i
            elif re.search(r"(he\b|helium|\bair\b)", env_lower):
                baseline_idx = i

        if baseline_idx is None or h2_idx is None:
            continue

        # Helper to get value at index from multi-value cell
        def get_val(col: Optional[int], idx: int) -> Optional[float]:
            if col is None or col >= len(row):
                return None
            lines = split_multivalue_cell(row[col])
            if idx < len(lines):
                return parse_float(lines[idx])
            return None

        # Extract baseline result
        baseline = MaterialTestResult(
            environment=env_lines[baseline_idx],
            yield_strength_mpa=get_val(sy_col, baseline_idx),
            ultimate_strength_mpa=get_val(su_col, baseline_idx),
            elongation_uniform_pct=get_val(el_u_col, baseline_idx),
            elongation_total_pct=get_val(el_t_col, baseline_idx),
            reduction_of_area_pct=get_val(ra_col, baseline_idx),
        )

        # Extract H2 result
        h2_result = MaterialTestResult(
            environment=env_lines[h2_idx],
            yield_strength_mpa=get_val(sy_col, h2_idx),
            ultimate_strength_mpa=get_val(su_col, h2_idx),
            elongation_uniform_pct=get_val(el_u_col, h2_idx),
            elongation_total_pct=get_val(el_t_col, h2_idx),
            reduction_of_area_pct=get_val(ra_col, h2_idx),
        )

        # Calculate embrittlement indices
        emb_ra = None
        emb_el = None
        strength_ratio = None

        if baseline.reduction_of_area_pct and h2_result.reduction_of_area_pct:
            if baseline.reduction_of_area_pct > 0:
                emb_ra = round(h2_result.reduction_of_area_pct / baseline.reduction_of_area_pct, 3)

        if baseline.elongation_total_pct and h2_result.elongation_total_pct:
            if baseline.elongation_total_pct > 0:
                emb_el = round(h2_result.elongation_total_pct / baseline.elongation_total_pct, 3)

        if baseline.ultimate_strength_mpa and h2_result.ultimate_strength_mpa:
            if baseline.ultimate_strength_mpa > 0:
                strength_ratio = round(
                    h2_result.ultimate_strength_mpa / baseline.ultimate_strength_mpa, 3
                )

        # Get strain rate and precharging
        rate_cell = row[rate_col] if rate_col and rate_col < len(row) else None
        precharge_cell = row[precharge_col] if precharge_col and precharge_col < len(row) else None

        # Get references
        refs = []
        if ref_col and ref_col < len(row):
            ref_text = row[ref_col]
            # Extract reference numbers like [1], [2, 3]
            ref_matches = re.findall(r"\[([^\]]+)\]", ref_text)
            refs = ref_matches

        records.append(ExtractedRecord(
            record_type=RecordType.PAIRED_TEST_COMPARISON,
            gas_type=table.gas_type,
            material_name=material_name,
            material_spec=material_spec,
            baseline_result=baseline,
            hydrogen_result=h2_result,
            embrittlement_index_ra=emb_ra,
            embrittlement_index_el=emb_el,
            strength_ratio=strength_ratio,
            thermal_precharging=precharge_cell,
            references=refs,
            source_document=table.source_document,
            source_page=table.source_page,
            source_table_id=table.table_id,
            raw_text=" | ".join(str(c) for c in row),
        ))

    return records


# ---------------------------------------------------------------------------
# Composition Table Extraction
# ---------------------------------------------------------------------------

def extract_composition_records(
    table: ExtractedTable,
    headers: list[str],
    rows: list[list[str]],
) -> list[ExtractedRecord]:
    """Extract composition data from alloy specification tables."""
    records = []

    # Find material column
    mat_col = find_column_index(headers, COL_MATERIAL) or 0

    # Build element column map
    element_cols: dict[str, int] = {}
    elements = ["Fe", "Cr", "Ni", "Mo", "Mn", "Si", "C", "N", "Al", "Ti", "Cu", "Co", "W", "Nb", "V"]
    for elem in elements:
        for i, h in enumerate(headers):
            if h.strip().lower() == elem.lower():
                element_cols[elem] = i
                break

    if not element_cols:
        return records

    for row in rows:
        if not row or len(row) <= mat_col:
            continue

        material = row[mat_col].strip().replace("\n", " ")
        if not material or material.lower() in ("steel", "material", "alloy", "heat", "uns"):
            continue

        # Extract composition
        composition: dict[str, float] = {}
        for elem, col in element_cols.items():
            if col < len(row):
                val = row[col]
                # Handle range values like "16.00\n18.00" - take midpoint
                lines = split_multivalue_cell(val)
                if len(lines) == 2:
                    v1 = parse_float(lines[0])
                    v2 = parse_float(lines[1])
                    if v1 is not None and v2 is not None:
                        composition[elem] = round((v1 + v2) / 2, 2)
                elif lines:
                    v = parse_float(lines[0])
                    if v is not None:
                        composition[elem] = v

        if composition:
            records.append(ExtractedRecord(
                record_type=RecordType.COMPOSITION_DATA,
                gas_type=table.gas_type,
                material_name=material,
                composition=composition,
                source_document=table.source_document,
                source_page=table.source_page,
                source_table_id=table.table_id,
                raw_text=" | ".join(str(c) for c in row),
            ))

    return records


# ---------------------------------------------------------------------------
# Generic Property Extraction
# ---------------------------------------------------------------------------

def extract_generic_records(
    table: ExtractedTable,
    headers: list[str],
    rows: list[list[str]],
) -> list[ExtractedRecord]:
    """Extract generic property data when specific patterns don't match."""
    records = []

    mat_col = find_column_index(headers, COL_MATERIAL) or 0

    for row in rows:
        if not row or len(row) <= mat_col:
            continue

        material = row[mat_col].strip().replace("\n", " ")
        if not material or len(material) < 2:
            continue

        # Skip obvious headers
        if material.lower() in ("material", "steel", "alloy", "heat", "", "uns"):
            continue

        # Collect all values with their headers
        properties = []
        for i, cell in enumerate(row):
            if i != mat_col and cell.strip():
                header = headers[i] if i < len(headers) else f"col_{i}"
                properties.append(f"{header}: {cell.strip()}")

        if properties:
            records.append(ExtractedRecord(
                record_type=table.table_type,
                gas_type=table.gas_type,
                material_name=material,
                property_value="; ".join(properties),
                source_document=table.source_document,
                source_page=table.source_page,
                source_table_id=table.table_id,
                raw_text=" | ".join(str(c) for c in row),
            ))

    return records


# ---------------------------------------------------------------------------
# LLM Fallback for Complex Tables (Optional)
# ---------------------------------------------------------------------------

PAIRED_TABLE_PROMPT = """You are extracting hydrogen embrittlement data from a materials test table.

This table compares material properties tested in inert gas (He or Air) vs hydrogen (H2).
The data is in paired rows or multi-value cells where values are stacked.

Table headers: {headers}
Table data:
{table_text}

For each material in the table, extract:
1. material_name: The alloy/steel designation
2. baseline_environment: "He" or "Air"
3. baseline_ra_pct: Reduction of area in baseline environment
4. h2_environment: The H2 test condition (e.g., "69 MPa H2")
5. h2_ra_pct: Reduction of area in H2
6. embrittlement_index: Calculate as h2_ra_pct / baseline_ra_pct (ratio, not percentage)

Return ONLY valid JSON array:
[
  {{
    "material_name": "304L",
    "baseline_environment": "69 MPa He",
    "baseline_ra_pct": 78,
    "h2_environment": "69 MPa H2",
    "h2_ra_pct": 71,
    "embrittlement_index": 0.91
  }}
]

Rules:
- If a value is missing or "—", use null
- Calculate embrittlement_index only if both RA values exist
- Do not invent data - only extract what's in the table"""


def extract_with_llm(
    table: ExtractedTable,
    client: Any,
    model: str,
) -> list[ExtractedRecord]:
    """Use LLM for complex tables that pattern matching can't handle."""
    records = []

    # Format table for prompt
    table_lines = [" | ".join(table.headers)]
    for row in table.rows[:15]:  # Limit to avoid token explosion
        table_lines.append(" | ".join(str(c) for c in row))
    table_text = "\n".join(table_lines)

    prompt = PAIRED_TABLE_PROMPT.format(
        headers=" | ".join(table.headers),
        table_text=table_text,
    )

    try:
        response = client.messages.create(
            model=model,
            max_tokens=1500,
            messages=[{"role": "user", "content": prompt}]
        )

        response_text = response.content[0].text.strip()

        # Extract JSON from response
        json_match = re.search(r"\[[\s\S]*\]", response_text)
        if json_match:
            data = json.loads(json_match.group())

            for item in data:
                if not item.get("material_name"):
                    continue

                baseline = None
                h2_result = None

                if item.get("baseline_ra_pct") is not None:
                    baseline = MaterialTestResult(
                        environment=item.get("baseline_environment", "He"),
                        reduction_of_area_pct=item.get("baseline_ra_pct"),
                    )

                if item.get("h2_ra_pct") is not None:
                    h2_result = MaterialTestResult(
                        environment=item.get("h2_environment", "H2"),
                        reduction_of_area_pct=item.get("h2_ra_pct"),
                    )

                records.append(ExtractedRecord(
                    record_type=RecordType.PAIRED_TEST_COMPARISON,
                    gas_type=table.gas_type,
                    material_name=item["material_name"],
                    baseline_result=baseline,
                    hydrogen_result=h2_result,
                    embrittlement_index_ra=item.get("embrittlement_index"),
                    source_document=table.source_document,
                    source_page=table.source_page,
                    source_table_id=table.table_id,
                    raw_text=table_text[:500],
                ))

    except Exception as e:
        logger.warning(f"LLM extraction failed for {table.table_id}: {e}")

    return records


# ---------------------------------------------------------------------------
# Main Extractor
# ---------------------------------------------------------------------------

class BOKExtractorV8:
    """
    Hybrid BOK extractor: pdfplumber structure + semantic understanding.

    For paired He/H2 comparison tables:
    1. Detect paired structure from headers and cell patterns
    2. Parse multi-value cells to separate baseline vs H2 results
    3. Calculate embrittlement indices from ratios

    Falls back to LLM only for tables where pattern matching fails.
    """

    def __init__(
        self,
        use_llm_fallback: bool = True,
        llm_model: str = "claude-haiku-4-5-20251001",
    ):
        self.use_llm_fallback = use_llm_fallback
        self.llm_model = llm_model
        self.logger = logging.getLogger(self.__class__.__name__)
        self._client = None

    def _get_client(self):
        """Lazy-load Anthropic client."""
        if self._client is None and self.use_llm_fallback:
            try:
                from anthropic import Anthropic
                api_key = os.environ.get("ANTHROPIC_API_KEY")
                if not api_key:
                    self.logger.warning("ANTHROPIC_API_KEY not set, disabling LLM fallback")
                    self.use_llm_fallback = False
                    return None
                self._client = Anthropic(api_key=api_key)
            except ImportError:
                self.logger.warning("anthropic not installed, disabling LLM fallback")
                self.use_llm_fallback = False
        return self._client

    def extract_pdf(self, pdf_path: Path, gas_type: GasType) -> list[ExtractedTable]:
        """Extract all tables from a PDF."""
        pdf_path = Path(pdf_path)
        self.logger.info(f"Extracting: {pdf_path.name} ({gas_type.value})")

        tables: list[ExtractedTable] = []
        total_records = 0
        paired_tables = 0
        llm_tables = 0

        with pdfplumber.open(pdf_path) as pdf:
            for page_num, page in enumerate(pdf.pages, start=1):
                page_tables = page.extract_tables()

                for t_idx, raw_table in enumerate(page_tables):
                    if not raw_table or len(raw_table) < 2:
                        continue

                    # Clean headers and rows
                    headers = [str(c or "").strip() for c in raw_table[0]]
                    if not any(headers):
                        continue

                    rows = []
                    for row in raw_table[1:]:
                        cleaned = [str(c or "").strip() for c in row]
                        if any(cleaned):
                            rows.append(cleaned)

                    if not rows:
                        continue

                    # Build table object
                    table_id = f"{pdf_path.stem}_p{page_num}_t{t_idx}"
                    raw_text = "\n".join([" | ".join(headers)] + [" | ".join(r) for r in rows])

                    # Classify table
                    table_type = classify_table(headers, rows, gas_type)
                    is_paired = detect_paired_comparison(headers, rows)
                    has_multivalue = detect_multivalue_cells(rows)

                    table = ExtractedTable(
                        table_id=table_id,
                        source_document=pdf_path.name,
                        source_page=page_num,
                        gas_type=gas_type,
                        headers=headers,
                        rows=rows,
                        raw_text=raw_text,
                        table_type=table_type,
                        is_paired_comparison=is_paired,
                        has_multivalue_cells=has_multivalue,
                    )

                    # Extract records based on table type
                    if is_paired and has_multivalue:
                        table.records = extract_paired_records(table, headers, rows)
                        table.extraction_method = "pattern_paired"
                        paired_tables += 1

                        # If pattern extraction got nothing, try LLM
                        if not table.records and self.use_llm_fallback:
                            client = self._get_client()
                            if client:
                                table.records = extract_with_llm(table, client, self.llm_model)
                                table.extraction_method = "llm"
                                llm_tables += 1

                    elif table_type == RecordType.COMPOSITION_DATA:
                        table.records = extract_composition_records(table, headers, rows)
                        table.extraction_method = "pattern_composition"

                    else:
                        table.records = extract_generic_records(table, headers, rows)
                        table.extraction_method = "pattern_generic"

                    tables.append(table)
                    total_records += len(table.records)

                    self.logger.debug(
                        f"  {table_id}: {table_type.value}, "
                        f"paired={is_paired}, {len(table.records)} records"
                    )

        self.logger.info(
            f"  -> {len(tables)} tables, {total_records} records "
            f"({paired_tables} paired, {llm_tables} LLM-assisted)"
        )

        return tables

    def extract_directory(
        self,
        input_dir: Path,
        gas_type: GasType,
        output_path: Optional[Path] = None,
    ) -> list[ExtractedTable]:
        """Extract all PDFs in directory."""
        input_dir = Path(input_dir)
        all_tables: list[ExtractedTable] = []
        failed: list[str] = []

        pdf_files = sorted(input_dir.glob("*.pdf"))
        self.logger.info(f"Processing {len(pdf_files)} PDFs from {input_dir}")

        for pdf_file in pdf_files:
            try:
                tables = self.extract_pdf(pdf_file, gas_type)
                all_tables.extend(tables)
            except Exception as e:
                self.logger.error(f"Failed {pdf_file.name}: {e}")
                failed.append(pdf_file.name)

        # Summary
        total_records = sum(len(t.records) for t in all_tables)
        paired_records = sum(
            len(t.records) for t in all_tables
            if t.table_type == RecordType.PAIRED_TEST_COMPARISON
            or t.is_paired_comparison
        )
        emb_records = sum(
            1 for t in all_tables for r in t.records
            if r.embrittlement_index_ra is not None
        )

        self.logger.info(f"\nExtraction complete:")
        self.logger.info(f"  Tables: {len(all_tables)}")
        self.logger.info(f"  Records: {total_records}")
        self.logger.info(f"  Paired comparisons: {paired_records}")
        self.logger.info(f"  With embrittlement index: {emb_records}")

        if output_path:
            self._save_output(all_tables, output_path, input_dir, gas_type, failed)

        return all_tables

    def _save_output(
        self,
        tables: list[ExtractedTable],
        output_path: Path,
        source_dir: Path,
        gas_type: GasType,
        failed: list[str],
    ) -> None:
        """Save results to JSON."""
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # Collect embrittlement data for summary
        emb_data = []
        for t in tables:
            for r in t.records:
                if r.embrittlement_index_ra is not None:
                    emb_data.append({
                        "material": r.material_name,
                        "embrittlement_index_ra": r.embrittlement_index_ra,
                        "baseline_ra": r.baseline_result.reduction_of_area_pct if r.baseline_result else None,
                        "h2_ra": r.hydrogen_result.reduction_of_area_pct if r.hydrogen_result else None,
                        "source": f"{r.source_document} p{r.source_page}",
                    })

        output_data = {
            "extraction_timestamp": datetime.now().isoformat(),
            "extractor_version": "0.8.0",
            "gas_type": gas_type.value,
            "source_directory": str(source_dir),
            "summary": {
                "total_tables": len(tables),
                "total_records": sum(len(t.records) for t in tables),
                "paired_comparison_records": sum(
                    1 for t in tables for r in t.records
                    if r.record_type == RecordType.PAIRED_TEST_COMPARISON
                ),
                "records_with_embrittlement_index": len(emb_data),
            },
            "embrittlement_data": emb_data,
            "failed_files": failed,
            "tables": [t.model_dump() for t in tables],
        }

        with open(output_path, "w") as f:
            json.dump(output_data, f, indent=2, default=str)

        self.logger.info(f"Saved to {output_path}")

        # Also save embrittlement summary separately
        if emb_data:
            emb_path = output_path.with_suffix(".embrittlement.json")
            with open(emb_path, "w") as f:
                json.dump(emb_data, f, indent=2)
            self.logger.info(f"Embrittlement summary: {emb_path}")


# ---------------------------------------------------------------------------
# Convenience Function
# ---------------------------------------------------------------------------

def extract_bok(
    input_path: Path,
    gas_type: GasType,
    output_path: Optional[Path] = None,
    use_llm: bool = True,
) -> list[ExtractedTable]:
    """Extract BOK data from PDF or directory."""
    extractor = BOKExtractorV8(use_llm_fallback=use_llm)
    input_path = Path(input_path)

    if input_path.is_dir():
        return extractor.extract_directory(input_path, gas_type, output_path)
    else:
        tables = extractor.extract_pdf(input_path, gas_type)
        if output_path:
            extractor._save_output(
                tables, output_path, input_path.parent, gas_type, []
            )
        return tables


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s"
    )

    parser = argparse.ArgumentParser(
        description="BOK Extractor V8 - Hybrid pdfplumber + semantic understanding",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python bok_extractor_v8.py ./h2_bok/ --gas H2 --output h2_bok.json
  python bok_extractor_v8.py document.pdf --gas O2 --output o2_data.json
  python bok_extractor_v8.py ./h2_bok/ --gas H2 --output h2.json --no-llm

Key insight:
  Sandia H2 tables don't label "HEE" explicitly. Embrittlement is IMPLICIT
  in paired He vs H2 test results. This extractor:
  1. Detects paired comparison tables
  2. Parses multi-value cells (stacked He/H2 results)
  3. Calculates embrittlement_index = RA_H2 / RA_baseline
        """,
    )
    parser.add_argument("input", type=Path, help="PDF file or directory")
    parser.add_argument("--gas", choices=["H2", "O2"], required=True)
    parser.add_argument("--output", "-o", type=Path, help="Output JSON path")
    parser.add_argument("--no-llm", action="store_true", help="Disable LLM fallback")
    parser.add_argument("--verbose", "-v", action="store_true")

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    tables = extract_bok(
        args.input,
        GasType(args.gas),
        args.output,
        use_llm=not args.no_llm,
    )

    # Print summary
    print(f"\n{'=' * 70}")
    print(f"EXTRACTION SUMMARY")
    print(f"{'=' * 70}")

    total_records = sum(len(t.records) for t in tables)
    print(f"Tables extracted: {len(tables)}")
    print(f"Total records: {total_records}")

    # Show embrittlement data
    emb_records = [
        r for t in tables for r in t.records
        if r.embrittlement_index_ra is not None
    ]

    if emb_records:
        print(f"\nEmbrittlement data found: {len(emb_records)} materials")
        print("-" * 70)
        print(f"{'Material':<30} {'RA(He)':<10} {'RA(H2)':<10} {'Index':<10}")
        print("-" * 70)

        for r in sorted(emb_records, key=lambda x: x.embrittlement_index_ra or 0)[:20]:
            baseline_ra = r.baseline_result.reduction_of_area_pct if r.baseline_result else "—"
            h2_ra = r.hydrogen_result.reduction_of_area_pct if r.hydrogen_result else "—"
            idx = r.embrittlement_index_ra

            # Color code: <0.9 = concerning, <0.7 = severe
            if idx and idx < 0.7:
                status = "⚠️"
            elif idx and idx < 0.9:
                status = "⚡"
            else:
                status = "✓"

            print(f"{r.material_name[:28]:<30} {str(baseline_ra):<10} {str(h2_ra):<10} {idx:<10} {status}")

        if len(emb_records) > 20:
            print(f"... and {len(emb_records) - 20} more")
    else:
        print("\nNo embrittlement data extracted.")
        print("This may indicate:")
        print("  - Tables don't contain paired He/H2 comparisons")
        print("  - Cell format differs from expected pattern")
        print("  - Try --verbose to see table detection details")
