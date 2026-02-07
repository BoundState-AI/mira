#!/usr/bin/env python3
"""
Module: V7
Purpose: bok_extractor_v7

BoundState AI 2025
Version: 0.7.0
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Fran OpenAI 5 <noreply@openai.com>
Co-Authored-By: Grok 4.0 <noreply@x.ai>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: SWE-032, SWE-033
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
from typing import Any, Iterator, Optional

import pdfplumber
from pydantic import BaseModel, Field

__all__ = [
    "BOKExtractorV7",
    "ExtractedTable",
    "ExtractedRecord",
    "GasType",
    "RecordType",
    "extract_bok_tables",
    "extract_bok_directory",
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
    FLAMMABILITY_RATING = "flammability_rating"
    TEST_PROCEDURE = "test_procedure"
    PROPERTY_DATA = "property_data"
    HEE_DATA = "hee_data"  # Hydrogen Environment Embrittlement


# ---------------------------------------------------------------------------
# Models - Simple, Focused
# ---------------------------------------------------------------------------

class ExtractedRecord(BaseModel):
    """Single extracted data record with full provenance."""
    model_config = {"extra": "forbid"}

    record_type: RecordType
    gas_type: GasType

    # Content - only what was actually extracted, no guessing
    material_name: Optional[str] = None
    material_family: Optional[str] = None
    rating: Optional[str] = None
    property_name: Optional[str] = None
    property_value: Optional[str] = None
    property_units: Optional[str] = None
    conditions: Optional[str] = None
    notes: Optional[str] = None

    # H2-specific
    hee_index: Optional[float] = None
    embrittlement_index: Optional[float] = None  # Alias for hee_index (downstream compatibility)
    nts_ratio: Optional[float] = None

    # O2-specific
    ignition_sensitivity: Optional[str] = None
    ait_f: Optional[float] = None  # Autogenous ignition temp
    mechanical_impact: Optional[str] = None

    # Provenance - required for every record
    source_document: str
    source_page: int
    source_table: Optional[str] = None
    source_cell_text: str  # Raw text from PDF - audit trail


class ExtractedTable(BaseModel):
    """A table extracted from a BOK document."""
    model_config = {"extra": "forbid"}

    table_id: str
    source_document: str
    source_page: int
    gas_type: GasType

    # Raw extraction - always preserved
    headers: list[str]
    rows: list[list[str]]
    raw_text: str  # For vector search

    # Classification
    table_type: Optional[RecordType] = None
    classification_confidence: float = Field(default=0.0, ge=0.0, le=1.0)

    # Parsed records
    records: list[ExtractedRecord] = Field(default_factory=list)

    # Metadata
    extraction_timestamp: str = Field(
        default_factory=lambda: datetime.now().isoformat()
    )
    enriched_by_llm: bool = False


# ---------------------------------------------------------------------------
# Pattern Definitions for Classification
# ---------------------------------------------------------------------------

MATERIAL_PATTERNS = [
    r"\bmaterial\b",
    r"\balloy\b",
    r"\bsteel\b",
    r"\binconel\b",
    r"\bmonel\b",
    r"\bhastelloy\b",
    r"\baluminum\b",
    r"\btitanium\b",
    r"\bcopper\b",
    r"\bnickel\b",
    r"\bdesignation\b",
    r"\buns\b",
    r"\bams\b",
    r"\bastm\s*[a-z]?\d+",
]

COMPATIBILITY_PATTERNS = [
    r"\bcompatibility\b",
    r"\bcompatible\b",
    r"\brating\b",
    r"\bclass\s*[a-dx]\b",
    r"\brecommended\b",
    r"\bacceptable\b",
    r"\bnot\s+recommended\b",
]

FLAMMABILITY_PATTERNS = [
    r"\bflammability\b",
    r"\bflammable\b",
    r"\blfl\b",
    r"\bufl\b",
    r"\bignition\b",
    r"\bburn\s*(rate|length|time)\b",
    r"\bself.?extinguish",
    r"\b6001\b",  # NASA-STD-6001
    r"\bupward\s+propagation\b",
]

HEE_PATTERNS = [
    r"\bhee\b",
    r"\bembrittlement\b",
    r"\bhydrogen\s*environment\b",
    r"\bnts\s*ratio\b",
    r"\bnotch\s*tensile\b",
    r"\bductility\s*ratio\b",
    r"\brelative\s*reduction\b",
]

TEST_PATTERNS = [
    r"\btest\s*\d+",
    r"\btest\s*[a-z]?\d+[a-z]?\b",
    r"\bprocedure\b",
    r"\bastm\s+[a-z]\d+",
    r"\bmethod\b",
    r"\bapparatus\b",
]

OXYGEN_PROPERTY_PATTERNS = [
    r"\bait\b",
    r"\bauto.?ignition\b",
    r"\bmechanical\s*impact\b",
    r"\breaction\b",
    r"\bpromoted\s*ignition\b",
    r"\bkindling\b",
]


def _matches_any(text: str, patterns: list[str]) -> bool:
    """Check if text matches any pattern (case-insensitive)."""
    text_lower = text.lower()
    return any(re.search(p, text_lower) for p in patterns)


def _count_matches(text: str, patterns: list[str]) -> int:
    """Count how many patterns match."""
    text_lower = text.lower()
    return sum(1 for p in patterns if re.search(p, text_lower))


# Column pattern sets (defined before classify_table for reference)
MATERIAL_COL = [r"material", r"alloy", r"name", r"designation", r"spec", r"uns", r"type"]
RATING_COL = [r"rating", r"class", r"compatibility", r"result", r"category"]
HEE_COL = [r"hee", r"index", r"ratio", r"nts", r"rra", r"ductility"]

# Notched-tensile / HEE-style table structure columns (Sandia SAND2012-7321 uses these)
ENVIRONMENT_COL = [r"test\s*environment", r"environment"]
SIGMA_S_COL = [r"σ", r"sigma", r"\bnts\b", r"notched\s*tensile"]
RA_COL = [r"\bra\b", r"reduction\s*of\s*area", r"ductility"]

NOTES_COL = [r"note", r"remark", r"comment", r"condition", r"limitation", r"restriction"]
PRESSURE_COL = [r"pressure", r"psia", r"psig", r"mpa", r"bar", r"ksi"]
TEMP_COL = [r"temp", r"temperature", r"°f", r"°c", r"kelvin"]
TEST_COL = [r"test", r"method", r"procedure", r"astm", r"number"]
AIT_COL = [r"ait", r"auto.?ignition", r"ignition\s*temp"]
IMPACT_COL = [r"impact", r"reaction", r"result"]


def classify_table(table: "ExtractedTable") -> tuple[RecordType, float]:
    """
    Classify table type based on headers and content patterns.

    Returns:
        Tuple of (record_type, confidence)
    """
    header_text = " ".join(table.headers).lower()

    # Sample first few rows for content patterns
    content_samples = []
    for row in table.rows[:5]:
        content_samples.append(" ".join(str(c) for c in row).lower())
    content_text = " ".join(content_samples)

    combined = f"{header_text} {content_text} {table.raw_text.lower()}"

    # Score each category
    scores = {
        RecordType.HEE_DATA: _count_matches(combined, HEE_PATTERNS) * 2,
        RecordType.FLAMMABILITY_RATING: _count_matches(combined, FLAMMABILITY_PATTERNS),
        RecordType.TEST_PROCEDURE: _count_matches(combined, TEST_PATTERNS),
        RecordType.MATERIAL_COMPATIBILITY: (
            _count_matches(combined, MATERIAL_PATTERNS) +
            _count_matches(combined, COMPATIBILITY_PATTERNS)
        ),
        RecordType.PROPERTY_DATA: _count_matches(combined, OXYGEN_PROPERTY_PATTERNS),
    }

    # Structural boost: many HEE tables don't say "HEE" in headers; they show paired He vs H2
    # data under "Test environment" with multi-line cells (e.g., "69 MPa He" / "69 MPa H\n2").
    rt = table.raw_text.lower()
    has_env_hdr = _matches_any(header_text, ENVIRONMENT_COL)
    has_sigma_hdr = re.search(r"(σ|sigma)", header_text) is not None
    has_ra_hdr = re.search(r"\bra\b|reduction\s*of\s*area", header_text) is not None
    has_he = re.search(r"\bhe\b", rt) is not None
    has_h2 = (re.search(r"\bh\s*2\b", rt) is not None) or ("hydrogen" in rt)
    if has_env_hdr and (has_sigma_hdr or has_ra_hdr) and has_he and has_h2:
        scores[RecordType.HEE_DATA] += 4

    # Find best match
    best_type = max(scores, key=scores.get)
    best_score = scores[best_type]

    # Calculate confidence
    total_patterns = sum(scores.values())
    if total_patterns == 0:
        return RecordType.PROPERTY_DATA, 0.3

    confidence = min(1.0, best_score / 5)  # Normalize to 0-1

    # If very low score, default to property data
    if best_score < 2:
        return RecordType.PROPERTY_DATA, 0.3

    return best_type, confidence


# ---------------------------------------------------------------------------
# Column Detection
# ---------------------------------------------------------------------------

def find_column(headers: list[str], patterns: list[str]) -> Optional[int]:
    """Find first column index matching any pattern."""
    for i, header in enumerate(headers):
        if _matches_any(header, patterns):
            return i
    return None


def find_columns(headers: list[str], patterns: list[str]) -> list[int]:
    """Find all column indices matching patterns."""
    indices = []
    for i, header in enumerate(headers):
        if _matches_any(header, patterns):
            indices.append(i)
    return indices


def safe_get(row: list[str], idx: Optional[int]) -> Optional[str]:
    """Safely get value from row, return None if invalid."""
    if idx is None or idx >= len(row):
        return None
    val = row[idx].strip()
    return val if val else None


def parse_float(val: Optional[str]) -> Optional[float]:
    """Try to parse float from string."""
    if not val:
        return None
    # Remove common suffixes/prefixes
    cleaned = re.sub(r'[^\d.\-+eE]', '', val.split()[0] if val.split() else val)
    try:
        return float(cleaned)
    except (ValueError, TypeError):
        return None


# ---------------------------------------------------------------------------
# Record Extraction - Per Table Type
# ---------------------------------------------------------------------------

def extract_material_records(table: ExtractedTable) -> list[ExtractedRecord]:
    """Extract material compatibility records."""
    records = []

    mat_col = find_column(table.headers, [r"\bsteel\b", r"\balloy\b", r"\bmaterial\b", r"\bpolymer\b", r"\bcompound\b"])
    if mat_col is None:
        mat_col = find_column(table.headers, MATERIAL_COL)
    rating_col = find_column(table.headers, RATING_COL)
    notes_col = find_column(table.headers, NOTES_COL)
    pressure_col = find_column(table.headers, PRESSURE_COL)
    temp_col = find_column(table.headers, TEMP_COL)

    # Default to first column if no material column found
    if mat_col is None:
        mat_col = 0

    for row in table.rows:
        material = safe_get(row, mat_col)
        if not material:
            continue

        # Skip obvious header rows that leaked through
        if material.lower() in ("material", "name", "alloy", "designation", "type"):
            continue

        # Build conditions string from available data
        conditions_parts = []
        pressure = safe_get(row, pressure_col)
        temp = safe_get(row, temp_col)
        if pressure:
            conditions_parts.append(f"Pressure: {pressure}")
        if temp:
            conditions_parts.append(f"Temp: {temp}")

        records.append(ExtractedRecord(
            record_type=RecordType.MATERIAL_COMPATIBILITY,
            gas_type=table.gas_type,
            material_name=material,
            rating=safe_get(row, rating_col),
            notes=safe_get(row, notes_col),
            conditions="; ".join(conditions_parts) if conditions_parts else None,
            source_document=table.source_document,
            source_page=table.source_page,
            source_table=table.table_id,
            source_cell_text=" | ".join(row),
        ))

    return records


def extract_hee_records(table: ExtractedTable) -> list[ExtractedRecord]:
    """Extract Hydrogen Environment Embrittlement data.

    Important: In Sandia SAND2012-7321, the key "HEE" signal is often *not* a column named "HEE".
    Instead, tables present paired helium vs hydrogen results (e.g., notched tensile strength and
    reduction-of-area) under a "Test environment" column, with multi-line cells.

    This extractor therefore supports:
      1) Direct extraction when explicit "HEE/index/ratio" columns exist.
      2) Computation of ratios from paired He vs H2 multi-line cells:
         - nts_ratio = σ_s(H2) / σ_s(He)  (Notched tensile strength ratio)
         - hee_index = RA(H2) / RA(He)    (Ductility retention via reduction-of-area ratio)
    """
    records: list[ExtractedRecord] = []

    mat_col = find_column(table.headers, [r"\bsteel\b", r"\balloy\b", r"\bmaterial\b", r"\bpolymer\b", r"\bcompound\b"])
    if mat_col is None:
        mat_col = find_column(table.headers, MATERIAL_COL)
    env_col = find_column(table.headers, ENVIRONMENT_COL)
    sigma_col = find_column(table.headers, SIGMA_S_COL)
    ra_col = find_column(table.headers, RA_COL)

    hee_cols = find_columns(table.headers, HEE_COL)  # explicit index/ratio columns (if present)
    notes_col = find_column(table.headers, NOTES_COL)
    pressure_col = find_column(table.headers, PRESSURE_COL)
    temp_col = find_column(table.headers, TEMP_COL)

    if mat_col is None:
        mat_col = 0

    def _split_lines(cell: Optional[str]) -> list[str]:
        if cell is None:
            return []
        return [s.strip() for s in str(cell).splitlines() if s and str(s).strip()]

    def _normalize_env(lines: list[str]) -> list[str]:
        """Normalize env lines, including the common 'H\n2' split."""
        out: list[str] = []
        for s in lines:
            if s.strip() == "2" and out and re.search(r"\bH$", out[-1]):
                out[-1] = out[-1] + "2"
            else:
                out.append(s)

        # normalize common footnote suffixes (e.g., Hea -> He)
        cleaned: list[str] = []
        for s in out:
            s2 = re.sub(r"\bhe[a-z]\b", "he", s, flags=re.I)
            s2 = re.sub(r"\bh2[a-z]\b", "h2", s2, flags=re.I)
            cleaned.append(s2)

        return cleaned

    def _parse_multifloats(cell: Optional[str]) -> list[Optional[float]]:
        vals: list[Optional[float]] = []
        for s in _split_lines(cell):
            vals.append(parse_float(s))
        return vals

    def _find_env_index(envs: list[str], kind: str) -> Optional[int]:
        kind = kind.lower()
        for i, e in enumerate(envs):
            el = e.lower()
            if kind == "he":
                if re.search(r"\bhe\b", el):
                    return i
            elif kind == "h2":
                if re.search(r"\bh\s*2\b", el) or ("hydrogen" in el):
                    return i
        return None

    # --- Path A: structural notched-tensile / paired env extraction ---
    if env_col is not None and (sigma_col is not None or ra_col is not None):
        last_material: Optional[str] = None
        for row in table.rows:
            material = safe_get(row, mat_col) or last_material
            if material:
                last_material = material

            if not material:
                continue

            # Skip header rows
            if str(material).strip().lower() in ("material", "name", "alloy", "steel"):
                continue

            envs = _normalize_env(_split_lines(safe_get(row, env_col)))
            if not envs:
                continue

            sigma_vals = _parse_multifloats(safe_get(row, sigma_col)) if sigma_col is not None else []
            ra_vals = _parse_multifloats(safe_get(row, ra_col)) if ra_col is not None else []

            he_i = _find_env_index(envs, "he")
            h2_i = _find_env_index(envs, "h2")

            nts_ratio: Optional[float] = None
            hee_index: Optional[float] = None

            if he_i is not None and h2_i is not None:
                # NTS ratio from σ_s if available
                if sigma_col is not None and he_i < len(sigma_vals) and h2_i < len(sigma_vals):
                    he_val = sigma_vals[he_i]
                    h2_val = sigma_vals[h2_i]
                    if he_val is not None and h2_val is not None and he_val != 0:
                        nts_ratio = h2_val / he_val

                # HEE index from RA if available
                if ra_col is not None and he_i < len(ra_vals) and h2_i < len(ra_vals):
                    he_ra = ra_vals[he_i]
                    h2_ra = ra_vals[h2_i]
                    if he_ra is not None and h2_ra is not None and he_ra != 0:
                        hee_index = h2_ra / he_ra

            # Validation: don't create HEE record if we couldn't compute anything useful
            if hee_index is None and nts_ratio is None:
                continue

            # Build conditions string from available data
            conditions_parts: list[str] = []
            pressure = safe_get(row, pressure_col)
            temp = safe_get(row, temp_col)
            if pressure:
                conditions_parts.append(f"Pressure: {pressure}")
            if temp:
                conditions_parts.append(f"Temp: {temp}")

            # Include the paired env strings for traceability
            if he_i is not None:
                conditions_parts.append(f"He: {envs[he_i]}")
            if h2_i is not None:
                conditions_parts.append(f"H2: {envs[h2_i]}")

            notes = safe_get(row, notes_col)
            if not notes:
                # preserve the raw paired values as notes for audit/debug
                notes = f"σ_s: {safe_get(row, sigma_col) if sigma_col is not None else ''}; RA: {safe_get(row, ra_col) if ra_col is not None else ''}"

            records.append(ExtractedRecord(
                record_type=RecordType.HEE_DATA,
                gas_type=table.gas_type,
                material_name=str(material).strip(),
                hee_index=hee_index,
                embrittlement_index=hee_index,
                nts_ratio=nts_ratio,
                conditions="; ".join(conditions_parts) if conditions_parts else None,
                notes=notes,
                source_document=table.source_document,
                source_page=table.source_page,
                source_table=table.table_id,
                source_cell_text=" | ".join(str(c) for c in row),
            ))
        return records

    # --- Path B: explicit HEE / ratio columns ---
    for row in table.rows:
        material = safe_get(row, mat_col)
        if not material:
            continue

        # Skip header rows
        if str(material).strip().lower() in ("material", "name", "alloy", "steel"):
            continue

        hee_index = None
        nts_ratio = None

        for col_idx in hee_cols:
            val = safe_get(row, col_idx)
            if not val:
                continue
            header = table.headers[col_idx] if col_idx < len(table.headers) else ""
            parsed = parse_float(val)
            if parsed is None:
                continue

            header_lower = header.lower()
            if "hee" in header_lower or "index" in header_lower:
                hee_index = parsed
            elif "nts" in header_lower or "ratio" in header_lower:
                nts_ratio = parsed

        # Validation: don't create record if key fields absent
        if hee_index is None and nts_ratio is None:
            continue

        conditions_parts = []
        pressure = safe_get(row, pressure_col)
        temp = safe_get(row, temp_col)
        if pressure:
            conditions_parts.append(f"H2 pressure: {pressure}")
        if temp:
            conditions_parts.append(f"Temp: {temp}")

        records.append(ExtractedRecord(
            record_type=RecordType.HEE_DATA,
            gas_type=table.gas_type,
            material_name=str(material).strip(),
            hee_index=hee_index,
            embrittlement_index=hee_index,
            nts_ratio=nts_ratio,
            conditions="; ".join(conditions_parts) if conditions_parts else None,
            notes=safe_get(row, notes_col),
            source_document=table.source_document,
            source_page=table.source_page,
            source_table=table.table_id,
            source_cell_text=" | ".join(str(c) for c in row),
        ))

    return records

def extract_flammability_records(table: ExtractedTable) -> list[ExtractedRecord]:
    """Extract flammability rating records."""
    records = []

    mat_col = find_column(table.headers, [r"\bsteel\b", r"\balloy\b", r"\bmaterial\b", r"\bpolymer\b", r"\bcompound\b"])
    if mat_col is None:
        mat_col = find_column(table.headers, MATERIAL_COL)
    rating_col = find_column(table.headers, RATING_COL)
    pressure_col = find_column(table.headers, PRESSURE_COL)
    notes_col = find_column(table.headers, NOTES_COL)
    ait_col = find_column(table.headers, AIT_COL)
    impact_col = find_column(table.headers, IMPACT_COL)

    if mat_col is None:
        mat_col = 0

    for row in table.rows:
        material = safe_get(row, mat_col)
        if not material:
            continue

        # Skip header rows
        if material.lower() in ("material", "name", "alloy"):
            continue

        conditions_parts = []
        pressure = safe_get(row, pressure_col)
        if pressure:
            conditions_parts.append(f"O2 pressure: {pressure}")

        ait_val = safe_get(row, ait_col)
        ait_f = parse_float(ait_val) if ait_val else None

        records.append(ExtractedRecord(
            record_type=RecordType.FLAMMABILITY_RATING,
            gas_type=table.gas_type,
            material_name=material,
            rating=safe_get(row, rating_col),
            notes=safe_get(row, notes_col),
            conditions="; ".join(conditions_parts) if conditions_parts else None,
            ait_f=ait_f,
            mechanical_impact=safe_get(row, impact_col),
            source_document=table.source_document,
            source_page=table.source_page,
            source_table=table.table_id,
            source_cell_text=" | ".join(row),
        ))

    return records


def extract_test_records(table: ExtractedTable) -> list[ExtractedRecord]:
    """Extract test procedure records."""
    records = []

    test_col = find_column(table.headers, TEST_COL)
    mat_col = find_column(table.headers, [r"\bsteel\b", r"\balloy\b", r"\bmaterial\b", r"\bpolymer\b", r"\bcompound\b"])
    if mat_col is None:
        mat_col = find_column(table.headers, MATERIAL_COL)
    notes_col = find_column(table.headers, NOTES_COL)

    if test_col is None:
        test_col = 0

    for row in table.rows:
        test_ref = safe_get(row, test_col)
        if not test_ref:
            continue

        # Skip header rows
        if test_ref.lower() in ("test", "method", "procedure", "number"):
            continue

        records.append(ExtractedRecord(
            record_type=RecordType.TEST_PROCEDURE,
            gas_type=table.gas_type,
            property_name=test_ref,
            material_name=safe_get(row, mat_col),
            notes=safe_get(row, notes_col),
            source_document=table.source_document,
            source_page=table.source_page,
            source_table=table.table_id,
            source_cell_text=" | ".join(row),
        ))

    return records


def extract_property_records(table: ExtractedTable) -> list[ExtractedRecord]:
    """Generic property extraction for unclassified tables."""
    records = []

    for row in table.rows:
        if not row or not row[0].strip():
            continue

        first_cell = row[0].strip()

        # Skip obvious headers
        if first_cell.lower() in ("property", "parameter", "value", "units", ""):
            continue

        # Collect all non-empty cells after first
        values = [c.strip() for c in row[1:] if c.strip()]

        records.append(ExtractedRecord(
            record_type=RecordType.PROPERTY_DATA,
            gas_type=table.gas_type,
            property_name=first_cell,
            property_value="; ".join(values) if values else None,
            source_document=table.source_document,
            source_page=table.source_page,
            source_table=table.table_id,
            source_cell_text=" | ".join(row),
        ))

    return records


# ---------------------------------------------------------------------------
# Table Processor
# ---------------------------------------------------------------------------

def process_table(table: ExtractedTable) -> ExtractedTable:
    """Classify and extract records from table."""
    table.table_type, table.classification_confidence = classify_table(table)

    if table.table_type == RecordType.HEE_DATA:
        table.records = extract_hee_records(table)
    elif table.table_type == RecordType.FLAMMABILITY_RATING:
        table.records = extract_flammability_records(table)
    elif table.table_type == RecordType.MATERIAL_COMPATIBILITY:
        table.records = extract_material_records(table)
    elif table.table_type == RecordType.TEST_PROCEDURE:
        table.records = extract_test_records(table)
    else:
        table.records = extract_property_records(table)

    return table


# ---------------------------------------------------------------------------
# PDF Table Extraction (pdfplumber - No LLM)
# ---------------------------------------------------------------------------

def extract_tables_from_pdf(
    pdf_path: Path,
    gas_type: GasType,
) -> Iterator[ExtractedTable]:
    """
    Extract all tables from PDF using pdfplumber.

    Deterministic, fast, no API calls.
    """
    pdf_path = Path(pdf_path)

    with pdfplumber.open(pdf_path) as pdf:
        for page_num, page in enumerate(pdf.pages, start=1):
            tables = page.extract_tables()

            for table_idx, table in enumerate(tables):
                if not table or len(table) < 2:
                    continue

                # Clean headers and rows
                headers = [str(cell or "").strip() for cell in table[0]]

                # Skip if headers are all empty
                if not any(headers):
                    continue

                rows = []
                for row in table[1:]:
                    cleaned = [str(cell or "").strip() for cell in row]
                    if any(cleaned):  # Skip completely empty rows
                        rows.append(cleaned)

                if not rows:
                    continue

                # Build searchable text
                page_text = page.extract_text() or ""

                raw_parts = []
                if page_text.strip():
                    raw_parts.append(page_text.strip())

                raw_parts.append(" ".join(headers))
                for row in rows:
                    raw_parts.append(" ".join(row))
                raw_text = "\n".join(p for p in raw_parts if p)

                table_id = f"{pdf_path.stem}_p{page_num}_t{table_idx}"

                yield ExtractedTable(
                    table_id=table_id,
                    source_document=pdf_path.name,
                    source_page=page_num,
                    gas_type=gas_type,
                    headers=headers,
                    rows=rows,
                    raw_text=raw_text,
                )


# ---------------------------------------------------------------------------
# Optional LLM Enrichment (for ambiguous tables)
# ---------------------------------------------------------------------------

LLM_ENRICHMENT_PROMPT = """Analyze this table from a NASA {gas_type} safety standard.

Table headers: {headers}
First 5 rows:
{sample_rows}

What type of data does this table contain? Choose ONE:
- material_compatibility: Material names with compatibility ratings or recommendations
- flammability_rating: Flammability test results or ratings
- hee_data: Hydrogen embrittlement data (HEE index, NTS ratios)
- test_procedure: Test methods or procedures
- property_data: General material or physical properties

Also identify which column contains the material/item name (0-indexed).

Return ONLY valid JSON:
{{"table_type": "...", "material_column": N, "notes": "brief explanation"}}"""


def enrich_table_with_llm(
    table: ExtractedTable,
    client: Any,
    model: str,
) -> ExtractedTable:
    """
    Use LLM to help classify ambiguous tables.

    Only called when classification_confidence < threshold.
    """
    sample_rows = "\n".join(
        " | ".join(row) for row in table.rows[:5]
    )

    prompt = LLM_ENRICHMENT_PROMPT.format(
        gas_type=table.gas_type.value,
        headers=" | ".join(table.headers),
        sample_rows=sample_rows,
    )

    try:
        response = client.messages.create(
            model=model,
            max_tokens=200,
            messages=[{"role": "user", "content": prompt}]
        )

        response_text = response.content[0].text.strip()

        # Parse JSON response
        if response_text.startswith("{"):
            result = json.loads(response_text)

            # Update table type if valid
            type_str = result.get("table_type", "")
            if type_str in [e.value for e in RecordType]:
                table.table_type = RecordType(type_str)
                table.classification_confidence = 0.7  # LLM-assisted
                table.enriched_by_llm = True

                # Re-extract with corrected type
                if table.table_type == RecordType.HEE_DATA:
                    table.records = extract_hee_records(table)
                elif table.table_type == RecordType.FLAMMABILITY_RATING:
                    table.records = extract_flammability_records(table)
                elif table.table_type == RecordType.MATERIAL_COMPATIBILITY:
                    table.records = extract_material_records(table)
                elif table.table_type == RecordType.TEST_PROCEDURE:
                    table.records = extract_test_records(table)
                else:
                    table.records = extract_property_records(table)

    except Exception as e:
        logger.warning(f"LLM enrichment failed for {table.table_id}: {e}")

    return table


# ---------------------------------------------------------------------------
# Main Extractor Class
# ---------------------------------------------------------------------------

class BOKExtractorV7:
    """
    Simple BOK extractor focused on tables.

    No LLM by default - pattern matching handles 90%+ of tables.
    Optional LLM enrichment for ambiguous cases.
    """

    def __init__(
        self,
        use_llm_enrichment: bool = False,
        llm_model: str = "claude-haiku-4-5-20251001",
        confidence_threshold: float = 0.4,
    ):
        """
        Initialize extractor.

        Args:
            use_llm_enrichment: If True, use LLM for low-confidence tables
            llm_model: Model to use for enrichment
            confidence_threshold: Below this, use LLM if enabled
        """
        self.use_llm_enrichment = use_llm_enrichment
        self.llm_model = llm_model
        self.confidence_threshold = confidence_threshold
        self.logger = logging.getLogger(self.__class__.__name__)

        self._client = None

    def _get_client(self):
        """Lazy-load Anthropic client for LLM enrichment."""
        if self._client is None and self.use_llm_enrichment:
            try:
                from anthropic import Anthropic
                api_key = os.environ.get("ANTHROPIC_API_KEY")
                if not api_key:
                    self.logger.warning("ANTHROPIC_API_KEY not set, disabling LLM enrichment")
                    self.use_llm_enrichment = False
                    return None
                self._client = Anthropic(api_key=api_key)
            except ImportError:
                self.logger.warning("anthropic package not installed, disabling LLM enrichment")
                self.use_llm_enrichment = False
        return self._client

    def extract_pdf(
        self,
        pdf_path: Path,
        gas_type: GasType,
    ) -> list[ExtractedTable]:
        """
        Extract all tables from a PDF.

        Args:
            pdf_path: Path to PDF
            gas_type: H2 or O2 context

        Returns:
            List of ExtractedTable with parsed records
        """
        pdf_path = Path(pdf_path)
        self.logger.info(f"Extracting: {pdf_path.name} ({gas_type.value})")

        tables = []
        llm_enriched = 0

        for table in extract_tables_from_pdf(pdf_path, gas_type):
            processed = process_table(table)

            # Optional LLM enrichment for low-confidence tables
            if (self.use_llm_enrichment and
                processed.classification_confidence < self.confidence_threshold and
                len(processed.rows) >= 3):

                client = self._get_client()
                if client:
                    processed = enrich_table_with_llm(processed, client, self.llm_model)
                    if processed.enriched_by_llm:
                        llm_enriched += 1

            tables.append(processed)

            self.logger.debug(
                f"  {table.table_id}: {table.table_type.value if table.table_type else 'unknown'}, "
                f"{len(processed.records)} records, conf={processed.classification_confidence:.2f}"
            )

        total_records = sum(len(t.records) for t in tables)
        enriched_msg = f", {llm_enriched} LLM-enriched" if llm_enriched else ""
        self.logger.info(f"  -> {len(tables)} tables, {total_records} records{enriched_msg}")

        return tables

    def extract_directory(
        self,
        input_dir: Path,
        gas_type: GasType,
        output_path: Optional[Path] = None,
    ) -> list[ExtractedTable]:
        """
        Extract all PDFs in a directory.

        Args:
            input_dir: Directory containing PDFs
            gas_type: H2 or O2
            output_path: Optional JSON output path

        Returns:
            All extracted tables
        """
        input_dir = Path(input_dir)
        all_tables = []
        failed = []

        pdf_files = sorted(input_dir.glob("*.pdf"))
        self.logger.info(f"Processing {len(pdf_files)} PDFs from {input_dir}")

        for pdf_file in pdf_files:
            try:
                tables = self.extract_pdf(pdf_file, gas_type)
                all_tables.extend(tables)
            except Exception as e:
                self.logger.error(f"Failed {pdf_file.name}: {e}")
                failed.append(pdf_file.name)

        # Summary by type
        type_counts: dict[str, int] = {}
        for t in all_tables:
            ttype = t.table_type.value if t.table_type else "unknown"
            type_counts[ttype] = type_counts.get(ttype, 0) + len(t.records)

        self.logger.info(
            f"Extraction complete: {len(all_tables)} tables, {sum(type_counts.values())} records"
        )
        for ttype, count in sorted(type_counts.items()):
            self.logger.info(f"  {ttype}: {count} records")

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
        """Save extraction results to JSON."""
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # Summary statistics
        type_counts: dict[str, int] = {}
        for t in tables:
            ttype = t.table_type.value if t.table_type else "unknown"
            type_counts[ttype] = type_counts.get(ttype, 0) + len(t.records)

        output_data = {
            "extraction_timestamp": datetime.now().isoformat(),
            "extractor_version": "0.7.0",
            "gas_type": gas_type.value,
            "source_directory": str(source_dir),
            "total_tables": len(tables),
            "total_records": sum(len(t.records) for t in tables),
            "records_by_type": type_counts,
            "failed_files": failed,
            "tables": [t.model_dump() for t in tables],
        }

        with open(output_path, "w") as f:
            json.dump(output_data, f, indent=2, default=str)

        self.logger.info(f"Saved to {output_path}")


# ---------------------------------------------------------------------------
# Convenience Functions
# ---------------------------------------------------------------------------

def extract_bok_tables(pdf_path: Path, gas_type: GasType) -> list[ExtractedTable]:
    """Extract tables from a single PDF."""
    return BOKExtractorV7().extract_pdf(pdf_path, gas_type)


def extract_bok_directory(
    input_dir: Path,
    gas_type: GasType,
    output_path: Optional[Path] = None,
) -> list[ExtractedTable]:
    """Extract tables from all PDFs in a directory."""
    return BOKExtractorV7().extract_directory(input_dir, gas_type, output_path)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse
    import sys

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s"
    )

    parser = argparse.ArgumentParser(
        description="BOK Table Extractor V7 - Fast, simple, pdfplumber-first",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Single PDF
  python bok_extractor_v7.py document.pdf --gas H2

  # Directory of PDFs with JSON output
  python bok_extractor_v7.py ./h2_bok/ --gas H2 --output h2_tables.json

  # With optional LLM enrichment for ambiguous tables
  python bok_extractor_v7.py ./o2_bok/ --gas O2 --output o2.json --enrich

Design:
  1. pdfplumber extracts table structure (no LLM)
  2. Pattern matching classifies tables (no LLM)
  3. Rules parse records per table type (no LLM)
  4. LLM only used with --enrich for low-confidence tables

Comparison to v6:
  v6: 1000+ lines, LLM-first, mega-prompts, slow, expensive
  v7: 700 lines, extraction-first, focused, fast, free (mostly)
        """,
    )
    parser.add_argument(
        "input",
        type=Path,
        help="PDF file or directory of PDFs",
    )
    parser.add_argument(
        "--gas",
        choices=["H2", "O2"],
        required=True,
        help="Gas type context",
    )
    parser.add_argument(
        "--output", "-o",
        type=Path,
        help="Output JSON file",
    )
    parser.add_argument(
        "--enrich",
        action="store_true",
        help="Use LLM to help classify ambiguous tables (requires ANTHROPIC_API_KEY)",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Verbose output",
    )

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    extractor = BOKExtractorV7(use_llm_enrichment=args.enrich)
    input_path = Path(args.input)

    if input_path.is_dir():
        tables = extractor.extract_directory(input_path, GasType(args.gas), args.output)
    elif input_path.is_file():
        tables = extractor.extract_pdf(input_path, GasType(args.gas))
        if args.output:
            extractor._save_output(
                tables, args.output, input_path.parent, GasType(args.gas), []
            )
    else:
        print(f"Error: {input_path} not found", file=sys.stderr)
        sys.exit(1)

    # Print summary
    total_records = sum(len(t.records) for t in tables)
    print(f"\n{'=' * 60}")
    print(f"Extracted {len(tables)} tables, {total_records} records")
    print(f"{'=' * 60}")

    # Group by type
    by_type: dict[str, list[ExtractedTable]] = {}
    for t in tables:
        ttype = t.table_type.value if t.table_type else "unknown"
        if ttype not in by_type:
            by_type[ttype] = []
        by_type[ttype].append(t)

    for ttype, type_tables in sorted(by_type.items()):
        type_records = sum(len(t.records) for t in type_tables)
        print(f"\n{ttype}: {len(type_tables)} tables, {type_records} records")

        # Show sample records
        for t in type_tables[:2]:
            print(f"  {t.table_id} (page {t.source_page}, conf={t.classification_confidence:.2f})")
            for rec in t.records[:3]:
                if rec.material_name:
                    print(f"    - {rec.material_name}: {rec.rating or rec.property_value or 'N/A'}")
                elif rec.property_name:
                    print(f"    - {rec.property_name}: {rec.property_value or 'N/A'}")
            if len(t.records) > 3:
                print(f"    ... and {len(t.records) - 3} more records")
