#!/usr/bin/env python3
"""
Module: Maptis Test Data
Purpose: MAPTIS Test Data Query with Expiration Filtering.

BoundState AI 2025
Version: 1.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Fran OpenAI 5 <noreply@openai.com>
Co-Authored-By: Grok 4.0 <noreply@x.ai>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: SWE-013 (Traceability), SWE-032 (Data validation)
Safety Critical: True
"""

from __future__ import annotations

import asyncio
import logging
import os
from concurrent.futures import ThreadPoolExecutor
from enum import Enum
from typing import Dict, List, Optional

import psycopg2
from psycopg2.extras import DictCursor
from pydantic import BaseModel, Field

__all__ = [
    "TestDataCurrency",
    "TestEnvelope",
    "FlammabilityTestResult",
    "TestDataStatus",
    "query_maptis_test_data",
    "query_maptis_test_data_bulk",
]

__safety_critical__ = True

LOGGER = logging.getLogger(__name__)

# Thread pool for async database queries (psycopg2 is synchronous)
_executor = ThreadPoolExecutor(max_workers=4)


class TestDataCurrency(str, Enum):
    """Currency status of MAPTIS test data.

    Maps to flam_dataexpireflag values in silver_report_rows.
    """
    CURRENT = "current"      # flam_dataexpireflag = '2'
    EXPIRED = "expired"      # flam_dataexpireflag = '1'
    UNKNOWN = "unknown"      # flam_dataexpireflag is NULL
    NOT_FOUND = "not_found"  # No test data exists for this material


class TestEnvelope(BaseModel):
    """Test envelope bounds from MAPTIS flammability data.

    Represents the tested conditions for a flammability test.
    """
    model_config = {"extra": "forbid"}

    pressure_psia: Optional[float] = Field(
        default=None,
        description="Test pressure in psia (flam_pressure)"
    )
    moc_o2_pct: Optional[float] = Field(
        default=None,
        description="Maximum oxygen concentration percentage (flam_moc_o2_pct)"
    )
    temperature_f: Optional[float] = Field(
        default=None,
        description="Test temperature in Fahrenheit (flam_temperature)"
    )
    sample_temperature_f: Optional[float] = Field(
        default=None,
        description="Sample temperature in Fahrenheit (flam_sampletemperature)"
    )


class FlammabilityTestResult(BaseModel):
    """Single flammability test result from MAPTIS.

    SWE-013: Includes source field for traceability.
    """
    model_config = {"extra": "forbid"}

    material_code: str = Field(description="MAPTIS material code (materialkey)")
    rating: str = Field(description="Flammability rating (A, B, C, D, I, K, N, U, X)")
    envelope: TestEnvelope = Field(description="Test envelope conditions")
    currency: TestDataCurrency = Field(description="Data currency status")
    report_id: Optional[str] = Field(
        default=None,
        description="Source report identifier (row_uid or id)"
    )
    source: str = Field(
        default="silver_report_rows:flammability_report",
        description="SWE-013: Data source for traceability"
    )


class TestDataStatus(BaseModel):
    """Summary status of test data for a material.

    Aggregates all flammability test results for a material code,
    separated by currency status (current vs expired).

    SWE-013: Includes source field for traceability.
    """
    model_config = {"extra": "forbid"}

    material_code: str = Field(description="MAPTIS material code")
    has_current_data: bool = Field(
        default=False,
        description="Whether current test data exists (flag='2')"
    )
    has_expired_data: bool = Field(
        default=False,
        description="Whether expired test data exists (flag='1')"
    )
    current_rating: Optional[str] = Field(
        default=None,
        description="Best rating from current data (A > B > C > ... > X)"
    )
    expired_rating: Optional[str] = Field(
        default=None,
        description="Best rating from expired data (for reference)"
    )
    current_results: List[FlammabilityTestResult] = Field(
        default_factory=list,
        description="Current test results (flag='2')"
    )
    expired_results: List[FlammabilityTestResult] = Field(
        default_factory=list,
        description="Expired test results (flag='1') - included if requested"
    )
    envelope: Optional[TestEnvelope] = Field(
        default=None,
        description="Most restrictive envelope from current data"
    )
    total_records: int = Field(
        default=0,
        description="Total number of flammability records found"
    )
    source: str = Field(
        default="silver_report_rows:flammability_report",
        description="SWE-013: Data source for traceability"
    )


# Rating priority for "best" rating calculation (A is best, X is worst)
RATING_PRIORITY = {
    "A": 1, "B": 2, "C": 3, "D": 4,
    "I": 5, "K": 6, "N": 7, "U": 8, "X": 9
}


def _get_best_rating(ratings: List[str]) -> Optional[str]:
    """Get best (least severe) rating from list.

    Rating order: A > B > C > D > I > K > N > U > X
    Returns None if list is empty.
    """
    if not ratings:
        return None

    valid = [r.upper().strip() for r in ratings if r and r.strip()]
    if not valid:
        return None

    # Sort by priority and return best
    known = [r for r in valid if r in RATING_PRIORITY]
    if known:
        return min(known, key=lambda r: RATING_PRIORITY[r])

    # Return first unknown rating if no known ratings
    return valid[0] if valid else None


def _parse_float(value) -> Optional[float]:
    """Safely parse float from database value."""
    if value is None:
        return None
    try:
        return float(value)
    except (ValueError, TypeError):
        return None


def _get_db_params() -> Dict[str, str]:
    """Get database connection parameters from environment or defaults."""
    return {
        "host": os.getenv("POSTGRES_HOST", "localhost"),
        "port": int(os.getenv("POSTGRES_PORT", "5432")),
        "database": os.getenv("POSTGRES_DB", "mira"),
        "user": os.getenv("POSTGRES_USER", "postgres"),
        "password": os.getenv("POSTGRES_PASSWORD", "postgres"),
    }


def _sync_query_maptis_test_data(
    material_code: str,
    include_expired: bool = False,
    conn_params: Optional[Dict] = None,
) -> TestDataStatus:
    """Synchronous database query for flammability test data.

    Internal function - use async wrapper query_maptis_test_data() instead.
    """
    params = conn_params or _get_db_params()
    result = TestDataStatus(material_code=material_code)

    try:
        conn = psycopg2.connect(**params)
        cursor = conn.cursor(cursor_factory=DictCursor)
    except Exception as e:
        LOGGER.error(f"Database connection failed for {material_code}: {e}")
        return result

    try:
        # Query all flammability data for this material
        # We fetch all records and filter by expire_flag in Python
        # to get accurate counts for both current and expired
        cursor.execute(
            """
            SELECT
                normalized_payload->>'materialkey' as material_code,
                normalized_payload->>'flam_rating' as rating,
                normalized_payload->>'flam_dataexpireflag' as expire_flag,
                normalized_payload->>'flam_pressure' as pressure,
                normalized_payload->>'flam_moc_o2_pct' as moc_o2_pct,
                normalized_payload->>'flam_temperature' as temperature,
                normalized_payload->>'flam_sampletemperature' as sample_temp,
                row_uid as report_id
            FROM silver_report_rows
            WHERE contract_id = 'flammability_report'
              AND normalized_payload->>'materialkey' = %s
            """,
            (material_code,),
        )

        rows = cursor.fetchall()
        result.total_records = len(rows)

        if not rows:
            LOGGER.debug(f"No flammability records found for materialkey={material_code}")
            return result

        current_results: List[FlammabilityTestResult] = []
        expired_results: List[FlammabilityTestResult] = []

        for row in rows:
            expire_flag = row["expire_flag"]

            # Determine currency from flag
            if expire_flag == "2":
                currency = TestDataCurrency.CURRENT
            elif expire_flag == "1":
                currency = TestDataCurrency.EXPIRED
            else:
                currency = TestDataCurrency.UNKNOWN

            # Build envelope from test conditions
            envelope = TestEnvelope(
                pressure_psia=_parse_float(row["pressure"]),
                moc_o2_pct=_parse_float(row["moc_o2_pct"]),
                temperature_f=_parse_float(row["temperature"]),
                sample_temperature_f=_parse_float(row["sample_temp"]),
            )

            # Build test result
            test_result = FlammabilityTestResult(
                material_code=material_code,
                rating=row["rating"] or "U",  # Default to Unknown if missing
                envelope=envelope,
                currency=currency,
                report_id=str(row["report_id"]) if row["report_id"] else None,
            )

            # Categorize by currency
            if currency == TestDataCurrency.CURRENT:
                current_results.append(test_result)
            elif currency == TestDataCurrency.EXPIRED:
                if include_expired:
                    expired_results.append(test_result)
            # UNKNOWN currency goes to neither list

        # Populate result
        result.current_results = current_results
        result.expired_results = expired_results
        result.has_current_data = len(current_results) > 0
        result.has_expired_data = len(expired_results) > 0 or any(
            row["expire_flag"] == "1" for row in rows
        )

        # Compute best ratings
        current_ratings = [r.rating for r in current_results if r.rating]
        expired_ratings = [r.rating for r in expired_results if r.rating]
        result.current_rating = _get_best_rating(current_ratings)
        result.expired_rating = _get_best_rating(expired_ratings)

        # Compute most restrictive envelope from current data
        # "Most restrictive" = lowest pressure, lowest O2%, lowest temp
        # (i.e., the safest tested conditions)
        if current_results:
            pressures = [r.envelope.pressure_psia for r in current_results
                        if r.envelope.pressure_psia is not None]
            mocs = [r.envelope.moc_o2_pct for r in current_results
                   if r.envelope.moc_o2_pct is not None]
            temps = [r.envelope.temperature_f for r in current_results
                    if r.envelope.temperature_f is not None]

            result.envelope = TestEnvelope(
                pressure_psia=min(pressures) if pressures else None,
                moc_o2_pct=min(mocs) if mocs else None,
                temperature_f=min(temps) if temps else None,
            )

        LOGGER.debug(
            f"Query for {material_code}: {len(current_results)} current, "
            f"{len(expired_results)} expired, {result.total_records} total"
        )

    except Exception as e:
        LOGGER.error(f"Query failed for materialkey={material_code}: {e}")
        # Return result with defaults (no data found)

    finally:
        cursor.close()
        conn.close()

    return result


async def query_maptis_test_data(
    material_code: str,
    include_expired: bool = False,
    conn_params: Optional[Dict] = None,
) -> TestDataStatus:
    """Query MAPTIS for flammability test data with expiration filtering.

    Args:
        material_code: MAPTIS material code (materialkey in silver_report_rows)
        include_expired: If True, also include expired data in results
        conn_params: Optional database connection parameters override

    Returns:
        TestDataStatus with current/expired test results and envelope.
        Check has_current_data to see if any current data exists.

    SWE-013: Results traceable to silver_report_rows:flammability_report.

    Note:
        Only data with flam_dataexpireflag='2' is considered current.
        Approximately 95% of MAPTIS flammability data is expired (flag='1').

    Example:
        >>> status = await query_maptis_test_data("20494")
        >>> if status.has_current_data:
        ...     print(f"Current rating: {status.current_rating}")
        ...     print(f"Envelope: {status.envelope}")
        >>> else:
        ...     print("No current test data - may need new testing")
    """
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        _executor,
        _sync_query_maptis_test_data,
        material_code,
        include_expired,
        conn_params,
    )


async def query_maptis_test_data_bulk(
    material_codes: List[str],
    include_expired: bool = False,
    conn_params: Optional[Dict] = None,
) -> Dict[str, TestDataStatus]:
    """Query MAPTIS for multiple materials in parallel.

    Args:
        material_codes: List of MAPTIS material codes
        include_expired: If True, also include expired data in results
        conn_params: Optional database connection parameters override

    Returns:
        Dict mapping material_code to TestDataStatus.

    Example:
        >>> results = await query_maptis_test_data_bulk(["20494", "20495"])
        >>> for code, status in results.items():
        ...     print(f"{code}: current={status.has_current_data}")
    """
    if not material_codes:
        return {}

    # Dedupe and clean
    codes = list(set(str(c).strip() for c in material_codes if c))
    if not codes:
        return {}

    # Query all in parallel
    tasks = [
        query_maptis_test_data(code, include_expired, conn_params)
        for code in codes
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    # Build result dict, handling any exceptions
    return {
        code: (
            result if isinstance(result, TestDataStatus)
            else TestDataStatus(material_code=code)  # Default on error
        )
        for code, result in zip(codes, results)
    }
