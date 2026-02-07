#!/usr/bin/env python3
"""
Module: Maptis Ratings
Purpose: Thin client for MAPTIS ratings lookup from PostgreSQL.

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

import logging
import os
from typing import Dict, List, Optional

import psycopg2
from psycopg2.extras import DictCursor

__all__ = [
    "get_ratings",
    "get_ratings_bulk",
    "MAPTISRatingsClient",
    "RATING_COLUMNS",
    "RATING_MAP",
    "FLASH_FIRE_RATING_MAP",
    "EXPIRE_FLAG_MAP",
    "INVALID_RATINGS",
]

LOGGER = logging.getLogger(__name__)

# MAPTIS rating categories (JSC 27301F Section 4.2.1 Field 32)
# Extended to include Mechanical Impact, Pneumatic Impact, and Flash Fire ratings
RATING_COLUMNS = ["FLAM", "SCC", "CORR", "TVS", "TOX", "FS", "MI", "PI", "FF_FLASH", "FF_FIRE"]

# Mapping: contract_id in silver_report_rows → JSONB field → MIUL column
RATING_MAP = {
    "flammability_report": ("flam_rating", "FLAM"),
    "promoted_combustion_report": ("prom_rating", "FLAM"),  # Metals O2 - maps to FLAM
    "stress_corrosion_cracking_report": ("stress_rating", "SCC"),
    "corrosion_report": ("cor_rating", "CORR"),
    "tvs_outgassing_report": ("tvs_rating", "TVS"),
    "toxicity_report": ("tox_spacestationrating", "TOX"),
    "fluid_compatibility_report": ("fluc_rating", "FS"),
    "mechanical_impact_report": ("mech_rating", "MI"),
    "pneumatic_impact_report": ("pneu_rating", "PI"),
    "flash_fire_report": ("fla_flashrating", "FF_FLASH"),
}

# Additional rating field for flash fire (fire rating separate from flash rating)
FLASH_FIRE_RATING_MAP = {
    "flash_fire_report": ("fla_firerating", "FF_FIRE"),
}

# Mapping: contract_id → expire flag field name in normalized_payload
# Flag values: '1' = expired, '2' = current, NULL = unknown
# NOTE: As of 2025, we include expired data but track currency status
EXPIRE_FLAG_MAP = {
    "flammability_report": "flam_dataexpireflag",
    "promoted_combustion_report": "prom_dataexpireflag",
    "stress_corrosion_cracking_report": "stress_dataexpireflag",
    "corrosion_report": "cor_dataexpireflag",
    "tvs_outgassing_report": "tvs_dataexpireflag",
    "toxicity_report": "tox_dataexpireflag",
    "fluid_compatibility_report": "fluc_dataexpireflag",
    "mechanical_impact_report": "mech_dataexpireflag",
    "pneumatic_impact_report": "pneu_dataexpireflag",
    "flash_fire_report": "fla_dataexpireflag",
}

# Rating severity for worst-case aggregation
RATING_SEVERITY = {"A": 1, "B": 2, "C": 3, "D": 4, "I": 5, "K": 6, "N": 7, "U": 8, "X": 9}

# Rating values that indicate "no valid data" - exclude from results
# X = data invalidated/superseded in MAPTIS (not a legitimate rating grade)
# Evidence: 3,341 TVS records show old_rating='C' changed to 'X' when invalidated
INVALID_RATINGS = {"X"}


class MAPTISRatingsClient:
    """Thin client for MAPTIS ratings lookup from PostgreSQL."""

    def __init__(
        self,
        host: Optional[str] = None,
        port: Optional[int] = None,
        database: Optional[str] = None,
        user: Optional[str] = None,
        password: Optional[str] = None,
    ):
        """Initialize client with database connection params.

        Uses centralized db_config module for credentials. Environment variables:
            POSTGRES_HOST, POSTGRES_PORT, POSTGRES_DB, POSTGRES_USER, POSTGRES_PASSWORD

        Args:
            host: PostgreSQL host override
            port: PostgreSQL port override
            database: Database name override
            user: Database user override
            password: Database password override
        """
        try:
            from mira.core.db_config import get_db_connection_params
            self._conn_params = get_db_connection_params(
                host=host, port=port, database=database, user=user, password=password
            )
        except ImportError:
            # Fallback if db_config not available
            self._conn_params = {
                "host": host or os.environ.get("POSTGRES_HOST", "localhost"),
                "port": port or int(os.environ.get("POSTGRES_PORT", "5432")),
                "database": database or os.environ.get("POSTGRES_DB", "mira"),
                "user": user or os.environ.get("POSTGRES_USER", "postgres"),
                "password": password or os.environ.get("POSTGRES_PASSWORD", "postgres"),
            }
        self._conn: Optional[psycopg2.extensions.connection] = None

    def _get_conn(self) -> psycopg2.extensions.connection:
        """Get or create database connection."""
        if self._conn is None or self._conn.closed:
            self._conn = psycopg2.connect(**self._conn_params)
        return self._conn

    def close(self) -> None:
        """Close database connection."""
        if self._conn and not self._conn.closed:
            self._conn.close()
            self._conn = None

    def get_ratings(self, material_code: str, include_currency: bool = True) -> Dict[str, str]:
        """Get ratings for a single material code.

        Args:
            material_code: MAPTIS material code (e.g., "20494")
            include_currency: If True, include {COLUMN}_CURRENCY fields showing "CURRENT"/"EXPIRED"

        Returns:
            Dict mapping rating column to value, e.g., {"FLAM": "A", "SCC": "B", "MI": "C", "MI_CURRENCY": "EXPIRED"}
            Only includes ratings that were found.
        """
        if not material_code:
            return {}

        material_code = str(material_code).strip()
        conn = self._get_conn()
        cursor = conn.cursor(cursor_factory=DictCursor)
        ratings: Dict[str, str] = {}

        try:
            # Process standard rating mappings
            for contract_id, (json_field, miul_col) in RATING_MAP.items():
                expire_flag_field = EXPIRE_FLAG_MAP.get(contract_id)
                cursor.execute(
                    """
                    SELECT normalized_payload->>%s as rating,
                           normalized_payload->>%s as expire_flag
                    FROM silver_report_rows
                    WHERE contract_id = %s
                      AND normalized_payload->>'materialkey' = %s
                      AND normalized_payload->>%s IS NOT NULL
                    """,
                    (json_field, expire_flag_field, contract_id, material_code, json_field),
                )

                rows = cursor.fetchall()
                if rows:
                    # Aggregate multiple test results (worst-case)
                    values = [r["rating"].strip().upper() for r in rows if r["rating"]]
                    expire_flags = [r["expire_flag"] for r in rows if r["rating"]]
                    # Filter out invalid ratings (X = data invalidated/superseded)
                    valid_pairs = [(v, f) for v, f in zip(values, expire_flags) if v not in INVALID_RATINGS]
                    if valid_pairs:
                        valid_values = [p[0] for p in valid_pairs]
                        valid_flags = [p[1] for p in valid_pairs]
                        worst = self._worst_rating(valid_values)
                        # Determine currency (any expired = mark as expired)
                        has_expired = any(f == "1" for f in valid_flags)
                        currency = "EXPIRED" if has_expired else "CURRENT"

                        # Only update if we don't have this rating yet, or this is worse
                        if miul_col not in ratings:
                            ratings[miul_col] = worst
                            if include_currency:
                                ratings[f"{miul_col}_CURRENCY"] = currency
                        else:
                            ratings[miul_col] = self._worst_rating([ratings[miul_col], worst])

            # Process FF_FIRE (second flash fire rating) separately
            for contract_id, (json_field, miul_col) in FLASH_FIRE_RATING_MAP.items():
                expire_flag_field = EXPIRE_FLAG_MAP.get(contract_id)
                cursor.execute(
                    """
                    SELECT normalized_payload->>%s as rating,
                           normalized_payload->>%s as expire_flag
                    FROM silver_report_rows
                    WHERE contract_id = %s
                      AND normalized_payload->>'materialkey' = %s
                      AND normalized_payload->>%s IS NOT NULL
                    """,
                    (json_field, expire_flag_field, contract_id, material_code, json_field),
                )

                rows = cursor.fetchall()
                if rows:
                    values = [r["rating"].strip().upper() for r in rows if r["rating"]]
                    expire_flags = [r["expire_flag"] for r in rows if r["rating"]]
                    valid_pairs = [(v, f) for v, f in zip(values, expire_flags) if v not in INVALID_RATINGS]
                    if valid_pairs:
                        valid_values = [p[0] for p in valid_pairs]
                        valid_flags = [p[1] for p in valid_pairs]
                        worst = self._worst_rating(valid_values)
                        has_expired = any(f == "1" for f in valid_flags)
                        currency = "EXPIRED" if has_expired else "CURRENT"

                        ratings[miul_col] = worst
                        if include_currency:
                            ratings[f"{miul_col}_CURRENCY"] = currency

        except Exception as e:
            LOGGER.error(f"[MAPTISRatings] Query failed for {material_code}: {e}")

        finally:
            cursor.close()

        return ratings

    def get_ratings_bulk(self, material_codes: List[str], include_currency: bool = True) -> Dict[str, Dict[str, str]]:
        """Get ratings for multiple material codes in optimized batch query.

        Args:
            material_codes: List of MAPTIS material codes
            include_currency: If True, include {COLUMN}_CURRENCY fields showing "CURRENT"/"EXPIRED"

        Returns:
            Dict mapping material_code to ratings dict.
            e.g., {"20494": {"FLAM": "A", "MI": "C", "MI_CURRENCY": "EXPIRED"}, "20495": {...}}

        Performance: <5 seconds for 100 materials (per architecture target)
        """
        if not material_codes:
            return {}

        # Dedupe and clean
        codes = list(set(str(c).strip() for c in material_codes if c))
        if not codes:
            return {}

        conn = self._get_conn()
        cursor = conn.cursor(cursor_factory=DictCursor)
        result: Dict[str, Dict[str, str]] = {code: {} for code in codes}

        try:
            # Single query fetches all ratings for all materials
            contract_ids = list(RATING_MAP.keys())
            cursor.execute(
                """
                SELECT
                    normalized_payload->>'materialkey' as material_code,
                    contract_id,
                    normalized_payload as payload
                FROM silver_report_rows
                WHERE contract_id = ANY(%s)
                  AND normalized_payload->>'materialkey' = ANY(%s)
                """,
                (contract_ids, codes),
            )

            # Group by material_code and contract_id, tracking ratings AND expire flags
            from collections import defaultdict
            # Structure: grouped[mat_code][contract_id] = [(rating, expire_flag), ...]
            grouped: Dict[str, Dict[str, List[tuple]]] = defaultdict(lambda: defaultdict(list))

            for row in cursor.fetchall():
                mat_code = row["material_code"]
                contract_id = row["contract_id"]
                payload = row["payload"]

                if contract_id not in RATING_MAP:
                    continue

                # Get expire flag (but don't filter - we include expired data now)
                expire_flag_field = EXPIRE_FLAG_MAP.get(contract_id)
                expire_flag = payload.get(expire_flag_field) if expire_flag_field else None

                json_field, _ = RATING_MAP[contract_id]
                rating = payload.get(json_field)
                if rating and isinstance(rating, str):
                    rating_clean = rating.strip().upper()
                    # Filter out invalid ratings (X = data invalidated/superseded)
                    if rating_clean not in INVALID_RATINGS:
                        grouped[mat_code][contract_id].append((rating_clean, expire_flag))

                # Also check for FF_FIRE (second flash fire rating)
                if contract_id == "flash_fire_report":
                    fire_rating = payload.get("fla_firerating")
                    if fire_rating and isinstance(fire_rating, str):
                        fire_rating_clean = fire_rating.strip().upper()
                        if fire_rating_clean not in INVALID_RATINGS:
                            # Use special key for FF_FIRE
                            grouped[mat_code]["flash_fire_report_fire"].append((fire_rating_clean, expire_flag))

            # Aggregate ratings for each material
            for mat_code, contract_ratings in grouped.items():
                if mat_code not in result:
                    continue

                for contract_id, rating_pairs in contract_ratings.items():
                    # Determine MIUL column name
                    if contract_id == "flash_fire_report_fire":
                        miul_col = "FF_FIRE"
                    elif contract_id in RATING_MAP:
                        _, miul_col = RATING_MAP[contract_id]
                    else:
                        continue

                    values = [p[0] for p in rating_pairs]
                    expire_flags = [p[1] for p in rating_pairs]
                    worst = self._worst_rating(values)

                    # Determine currency (any expired = mark as expired)
                    has_expired = any(f == "1" for f in expire_flags)
                    currency = "EXPIRED" if has_expired else "CURRENT"

                    # Handle FLAM (both flammability and promoted combustion map to it)
                    if miul_col in result[mat_code]:
                        result[mat_code][miul_col] = self._worst_rating(
                            [result[mat_code][miul_col], worst]
                        )
                    else:
                        result[mat_code][miul_col] = worst
                        if include_currency:
                            result[mat_code][f"{miul_col}_CURRENCY"] = currency

            LOGGER.info(
                f"[MAPTISRatings] Bulk query: {len(codes)} materials, "
                f"{sum(1 for r in result.values() for k in r if not k.endswith('_CURRENCY'))} ratings found"
            )

        except Exception as e:
            LOGGER.error(f"[MAPTISRatings] Bulk query failed: {e}")

        finally:
            cursor.close()

        return result

    @staticmethod
    def _worst_rating(ratings: List[str]) -> str:
        """Return worst (most severe) rating from list.

        Args:
            ratings: List of rating values (A, B, C, D, I, K, N, U, X)

        Returns:
            Worst rating (highest severity number)
        """
        if not ratings:
            return ""

        valid = [r for r in ratings if r in RATING_SEVERITY]
        if not valid:
            return ratings[0] if ratings else ""

        return max(valid, key=lambda r: RATING_SEVERITY.get(r, 0))


# Module-level convenience functions (create client per-call, auto-close)
def get_ratings(material_code: str) -> Dict[str, str]:
    """Get ratings for a single material code.

    Convenience function that creates a client, queries, and closes.

    Args:
        material_code: MAPTIS material code

    Returns:
        Dict of ratings {"FLAM": "A", "SCC": "B", ...}
    """
    client = MAPTISRatingsClient()
    try:
        return client.get_ratings(material_code)
    finally:
        client.close()


def get_ratings_bulk(material_codes: List[str]) -> Dict[str, Dict[str, str]]:
    """Get ratings for multiple material codes.

    Convenience function that creates a client, queries, and closes.

    Args:
        material_codes: List of MAPTIS material codes

    Returns:
        Dict mapping material_code to ratings dict
    """
    client = MAPTISRatingsClient()
    try:
        return client.get_ratings_bulk(material_codes)
    finally:
        client.close()
