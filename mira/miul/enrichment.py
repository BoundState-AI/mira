#!/usr/bin/env python3
"""
Module: Enrichment
Purpose: MIUL Rating Enrichment Service.

This module provides two enrichment workflows:

1. **Two-Step Workflow (Recommended)**:
   Build a MIUL first, then enrich it separately:

   ```python
   from mira.miul.builder import build_miul_from_bom
   from mira.miul.enrichment import enrich_miul_with_maptis_ratings

   # Step 1: Build MIUL
   miul_result = build_miul_from_bom(bom_df, crosswalk_df, specs_df)

   # Step 2: Enrich with MAPTIS ratings
   enriched_result = enrich_miul_with_maptis_ratings(miul_result)

   # Step 3: Export
   enriched_result.to_excel("enriched_miul.xlsx")
   ```

2. **Direct DataFrame Enrichment (Legacy)**:
   Enrich a DataFrame directly:

   ```python
   from mira.miul.enrichment import get_enrichment_service

   service = get_enrichment_service()
   enriched_df, stats = service.enrich_miul_dataframe(miul_df)
   ```

BoundState AI 2025
Version: 1.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Fran OpenAI 5 <noreply@openai.com>
Co-Authored-By: Grok 4.0 <noreply@x.ai>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: SWE-032 (Data validation), SWE-033 (Requirements Traceability)
Safety Critical: True
"""

from __future__ import annotations

import logging
from collections import defaultdict
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
import psycopg2
from psycopg2.extras import DictCursor
import uuid

from mira.miul.maptis_ratings import EXPIRE_FLAG_MAP, INVALID_RATINGS

LOGGER = logging.getLogger(__name__)

# Mapping of test type contract_id to rating field in JSONB
RATING_FIELD_MAP = {
    "flammability_report": "flam_rating",
    "promoted_combustion_report": "prom_rating",
    "corrosion_report": "cor_rating",
    "stress_corrosion_cracking_report": "stress_rating",
    "tvs_outgassing_report": "tvs_rating",
    "fluid_compatibility_report": "fluc_rating",
    "toxicity_report": "tox_spacestationrating",
    "mechanical_impact_report": "mech_rating",
    "pneumatic_impact_report": "pneu_rating",
    "flash_fire_report": "fla_flashrating",
}

# Second flash fire rating field (fire rating separate from flash rating)
FLASH_FIRE_FIELD_MAP = {
    "flash_fire_report": "fla_firerating",
}

# MIUL column names for ratings (per JSC 27301F Section 4.2.1 field 32)
# Extended to include Mechanical Impact, Pneumatic Impact, and Flash Fire ratings
MIUL_RATING_COLUMNS = {
    "flammability_report": "FLAM",
    "promoted_combustion_report": "FLAM",
    "corrosion_report": "CORR",
    "stress_corrosion_cracking_report": "SCC",
    "tvs_outgassing_report": "TVS",
    "fluid_compatibility_report": "FS",
    "toxicity_report": "TOX",
    "mechanical_impact_report": "MI",
    "pneumatic_impact_report": "PI",
    "flash_fire_report": "FF_FLASH",
}

# Second flash fire rating column
FLASH_FIRE_MIUL_COLUMNS = {
    "flash_fire_report": "FF_FIRE",
}

# Rating severity order (for conservative aggregation)
RATING_SEVERITY = {
    "A": 1,
    "B": 2,
    "C": 3,
    "D": 4,
    "I": 5,
    "K": 6,
    "N": 7,
    "U": 8,
    "X": 9,
}


class MIULEnrichmentService:
    """Service for enriching MIULs with MAPTIS test ratings."""

    def __init__(
        self,
        host: Optional[str] = None,
        port: Optional[int] = None,
        database: Optional[str] = None,
        user: Optional[str] = None,
        password: Optional[str] = None,
    ):
        """Initialize the enrichment service.

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
            import os
            self._conn_params = {
                "host": host or os.environ.get("POSTGRES_HOST", "localhost"),
                "port": port or int(os.environ.get("POSTGRES_PORT", "5432")),
                "database": database or os.environ.get("POSTGRES_DB", "mira"),
                "user": user or os.environ.get("POSTGRES_USER", "postgres"),
                "password": password or os.environ.get("POSTGRES_PASSWORD", "postgres"),
            }
        self._conn: Optional[psycopg2.extensions.connection] = None

    def _get_connection(self) -> psycopg2.extensions.connection:
        """Get PostgreSQL database connection."""
        if self._conn is None or self._conn.closed:
            self._conn = psycopg2.connect(**self._conn_params)
        return self._conn

    def close(self) -> None:
        """Close database connection."""
        if self._conn and not self._conn.closed:
            self._conn.close()

    def _translate_miul_code_to_db_code(self, miul_value: str) -> Optional[str]:
        """Translate MIUL 'Material Code' column value to database material_code.

        MIUL files typically store material_keys in their "Material Code" column.
        This translates to actual material_code for database query.

        Args:
            miul_value: Value from MIUL "Material Code" column

        Returns:
            material_code for database query, or None if not found
        """
        if not miul_value:
            return None

        miul_value = str(miul_value).strip()

        try:
            material_key = int(miul_value)

            conn = self._get_connection()
            cursor = conn.cursor(cursor_factory=DictCursor)

            cursor.execute(
                """
                SELECT material_code
                FROM materials
                WHERE material_key = %s
                  AND material_code IS NOT NULL
                  AND material_code != 'UNKNOWN'
                """,
                (material_key,),
            )

            row = cursor.fetchone()
            cursor.close()

            if row and row["material_code"]:
                db_code = row["material_code"]
                LOGGER.debug(f"Translated MIUL key {miul_value} -> material_code {db_code}")
                return db_code
            else:
                LOGGER.warning(f"No material_code found for MIUL key {miul_value}")
                return None

        except ValueError:
            # Non-numeric value - try direct lookup
            LOGGER.debug(f"MIUL value '{miul_value}' is non-numeric, trying direct lookup")
            return miul_value

    def _normalize_designation(self, designation: str) -> List[str]:
        """Generate normalized search variants for a designation.

        Handles common naming variations:
        - A286 -> A-286 (hyphen insertion)
        - 416 SST -> STAINLESS STEEL 416, CRES 416
        - SS 316L -> STAINLESS STEEL 316L, CRES 316L

        Args:
            designation: Raw designation string

        Returns:
            List of search variants to try
        """
        import re

        variants = [designation]
        upper = designation.upper().strip()

        # Handle A286 -> A-286 pattern (alloy numbers without hyphen)
        match = re.match(r"^([A-Z])(\d{3,4})$", upper)
        if match:
            variants.append(f"{match.group(1)}-{match.group(2)}")

        # Handle "416 SST", "316L SST" -> "STAINLESS STEEL 416", "CRES 416"
        sst_match = re.match(r"^(\d{3}[A-Z]?)\s*(SST|STAINLESS|CRES|SS)$", upper)
        if sst_match:
            alloy = sst_match.group(1)
            variants.extend([
                f"STAINLESS STEEL {alloy}",
                f"CRES {alloy}",
                f"STEEL {alloy}",
                alloy,
            ])

        # Handle "SS 316L" -> "STAINLESS STEEL 316L"
        ss_match = re.match(r"^SS\s*(\d{3}[A-Z]?)$", upper)
        if ss_match:
            alloy = ss_match.group(1)
            variants.extend([
                f"STAINLESS STEEL {alloy}",
                f"CRES {alloy}",
                alloy,
            ])

        # Handle "CRES 316L" -> "STAINLESS STEEL 316L"
        cres_match = re.match(r"^CRES\s*(\d{3}[A-Z]?)$", upper)
        if cres_match:
            alloy = cres_match.group(1)
            variants.extend([
                f"STAINLESS STEEL {alloy}",
                alloy,
            ])

        # Handle bare alloy numbers like "316L", "416"
        bare_match = re.match(r"^(\d{3}[A-Z]?)$", upper)
        if bare_match:
            alloy = bare_match.group(1)
            variants.extend([
                f"STAINLESS STEEL {alloy}",
                f"CRES {alloy}",
            ])

        return variants

    def find_material_code_by_designation(
        self,
        designation: str,
        part_description: str = "",
        material_form: str = "",
    ) -> Optional[str]:
        """Look up material_code from MAPTIS by designation/name.

        Delegates to the authoritative MaterialCodeLookupService for consistent
        lookup behavior. Only returns a code if confidence is medium or higher.

        Args:
            designation: Material designation/name from MIUL (e.g., "INCONEL 718")
            part_description: Part description for form inference (e.g., "SKIN, FUSELAGE")
            material_form: Explicit material form if known (e.g., "SHEET", "PLATE")

        Returns:
            material_code if found with sufficient confidence, None otherwise
        """
        if not designation:
            return None

        designation = str(designation).strip()
        if not designation:
            return None

        # Delegate to authoritative lookup service
        try:
            from mira.miul.material_code_lookup import get_lookup_service

            lookup = get_lookup_service()
            match = lookup.lookup_material_code(
                designation,
                part_description=part_description,
                material_form=material_form,
            )

            # Only return code if high/medium confidence
            if match.material_code and match.score >= 0.5:
                LOGGER.debug(
                    f"Authoritative lookup: '{designation}' -> {match.material_code} "
                    f"(method={match.method}, score={match.score:.2f})"
                )
                return match.material_code

            LOGGER.debug(
                f"No confident match for '{designation}' "
                f"(method={match.method}, score={match.score:.2f})"
            )
            return None

        except ImportError:
            LOGGER.warning(
                "MaterialCodeLookupService not available, using legacy lookup"
            )
            return self._legacy_find_material_code(designation)

        except Exception as e:
            LOGGER.error(f"Error looking up material code for '{designation}': {e}")
            return None

    def _legacy_find_material_code(self, designation: str) -> Optional[str]:
        """Legacy lookup method - only used if authoritative service unavailable.

        NOTE: This method uses ILIKE %variant% which can produce false positives
        (e.g., "302 SST" matching "AMS 3302"). Prefer the authoritative lookup.
        """
        conn = self._get_connection()
        cursor = conn.cursor(cursor_factory=DictCursor)

        try:
            # Generate search variants
            variants = self._normalize_designation(designation)

            # Try exact match first for each variant
            for variant in variants:
                cursor.execute(
                    """
                    SELECT material_code
                    FROM materials
                    WHERE designation ILIKE %s
                      AND material_code IS NOT NULL
                      AND material_code != 'UNKNOWN'
                    LIMIT 1
                    """,
                    (variant,),
                )
                row = cursor.fetchone()

                if row and row["material_code"]:
                    LOGGER.debug(f"Legacy exact match: '{designation}' (variant: '{variant}') -> {row['material_code']}")
                    return row["material_code"]

            # Try partial match with wildcards for each variant
            for variant in variants:
                cursor.execute(
                    """
                    SELECT material_code
                    FROM materials
                    WHERE designation ILIKE %s
                      AND material_code IS NOT NULL
                      AND material_code != 'UNKNOWN'
                    ORDER BY LENGTH(designation)
                    LIMIT 1
                    """,
                    (f"%{variant}%",),
                )
                row = cursor.fetchone()

                if row and row["material_code"]:
                    LOGGER.debug(f"Legacy partial match: '{designation}' (variant: '{variant}') -> {row['material_code']}")
                    return row["material_code"]

            LOGGER.debug(f"Legacy: No material_code found for designation: '{designation}'")
            return None

        except Exception as e:
            LOGGER.error(f"Error in legacy lookup for '{designation}': {e}")
            return None

        finally:
            cursor.close()

    def get_ratings_for_material_code(self, material_code: str, include_currency: bool = True) -> Dict[str, str]:
        """Get all available ratings for a specific material code.

        Args:
            material_code: MAPTIS material code
            include_currency: If True, include {COLUMN}_CURRENCY fields showing "CURRENT"/"EXPIRED"

        Returns:
            Dictionary mapping rating type to rating value, with optional currency columns
            e.g., {"FLAM": "A", "MI": "C", "MI_CURRENCY": "EXPIRED"}
        """
        conn = self._get_connection()
        cursor = conn.cursor(cursor_factory=DictCursor)

        ratings: Dict[str, str] = {}

        try:
            # Process standard rating mappings
            for contract_id, rating_field in RATING_FIELD_MAP.items():
                expire_flag_field = EXPIRE_FLAG_MAP.get(contract_id)
                # Include ALL data (no expire flag filter) - we track currency instead
                query = """
                    SELECT normalized_payload->>%s as rating,
                           normalized_payload->>%s as expire_flag
                    FROM silver_report_rows
                    WHERE contract_id = %s
                      AND normalized_payload->>'materialkey' = %s
                      AND normalized_payload->>%s IS NOT NULL
                """

                cursor.execute(query, (rating_field, expire_flag_field, contract_id, material_code, rating_field))
                results = cursor.fetchall()

                if results:
                    rating_values = [row["rating"].strip().upper() for row in results if row["rating"]]
                    expire_flags = [row["expire_flag"] for row in results if row["rating"]]
                    # Filter out invalid ratings (X = data invalidated/superseded)
                    valid_pairs = [(v, f) for v, f in zip(rating_values, expire_flags) if v not in INVALID_RATINGS]

                    if valid_pairs:
                        valid_values = [p[0] for p in valid_pairs]
                        valid_flags = [p[1] for p in valid_pairs]
                        miul_column = MIUL_RATING_COLUMNS[contract_id]
                        aggregated_rating = self._aggregate_ratings(valid_values)

                        if aggregated_rating:
                            ratings[miul_column] = aggregated_rating
                            if include_currency:
                                # Any expired data = mark column as expired
                                has_expired = any(f == "1" for f in valid_flags)
                                ratings[f"{miul_column}_CURRENCY"] = "EXPIRED" if has_expired else "CURRENT"

            # Process FF_FIRE (second flash fire rating) separately
            for contract_id, rating_field in FLASH_FIRE_FIELD_MAP.items():
                expire_flag_field = EXPIRE_FLAG_MAP.get(contract_id)
                query = """
                    SELECT normalized_payload->>%s as rating,
                           normalized_payload->>%s as expire_flag
                    FROM silver_report_rows
                    WHERE contract_id = %s
                      AND normalized_payload->>'materialkey' = %s
                      AND normalized_payload->>%s IS NOT NULL
                """

                cursor.execute(query, (rating_field, expire_flag_field, contract_id, material_code, rating_field))
                results = cursor.fetchall()

                if results:
                    rating_values = [row["rating"].strip().upper() for row in results if row["rating"]]
                    expire_flags = [row["expire_flag"] for row in results if row["rating"]]
                    valid_pairs = [(v, f) for v, f in zip(rating_values, expire_flags) if v not in INVALID_RATINGS]

                    if valid_pairs:
                        valid_values = [p[0] for p in valid_pairs]
                        valid_flags = [p[1] for p in valid_pairs]
                        miul_column = FLASH_FIRE_MIUL_COLUMNS[contract_id]
                        aggregated_rating = self._aggregate_ratings(valid_values)

                        if aggregated_rating:
                            ratings[miul_column] = aggregated_rating
                            if include_currency:
                                has_expired = any(f == "1" for f in valid_flags)
                                ratings[f"{miul_column}_CURRENCY"] = "EXPIRED" if has_expired else "CURRENT"

        except Exception as e:
            LOGGER.error(f"Error fetching ratings for material {material_code}: {e}")

        finally:
            cursor.close()

        return ratings

    def get_ratings_bulk(self, material_codes: List[str], include_currency: bool = True) -> Dict[str, Dict[str, str]]:
        """Get ratings for multiple material codes in one query.

        Args:
            material_codes: List of MAPTIS material codes
            include_currency: If True, include {COLUMN}_CURRENCY fields showing "CURRENT"/"EXPIRED"

        Returns:
            Dictionary mapping material_code to ratings dict with optional currency columns
        """
        if not material_codes:
            return {}

        conn = self._get_connection()
        cursor = conn.cursor(cursor_factory=DictCursor)

        all_ratings = {code: {} for code in material_codes}

        try:
            query = """
                SELECT
                    normalized_payload->>'materialkey' as material_code,
                    contract_id,
                    normalized_payload as payload
                FROM silver_report_rows
                WHERE contract_id = ANY(%s)
                  AND normalized_payload->>'materialkey' = ANY(%s)
            """

            contract_ids = list(RATING_FIELD_MAP.keys())
            cursor.execute(query, (contract_ids, material_codes))

            # Group results by material_code and contract, tracking ratings AND expire flags
            # Structure: grouped_results[material_code][contract_id] = [(rating, expire_flag), ...]
            grouped_results: Dict[str, Dict[str, List[tuple]]] = defaultdict(lambda: defaultdict(list))

            for row in cursor.fetchall():
                material_code = row["material_code"]
                contract_id = row["contract_id"]
                payload = row["payload"]

                # Get expire flag (but don't filter - we include expired data now)
                expire_flag_field = EXPIRE_FLAG_MAP.get(contract_id)
                expire_flag = payload.get(expire_flag_field) if expire_flag_field else None

                rating_field = RATING_FIELD_MAP.get(contract_id)
                if rating_field and rating_field in payload:
                    rating = payload.get(rating_field)
                    if rating and isinstance(rating, str):
                        rating_clean = rating.strip().upper()
                        # Filter out invalid ratings (X = data invalidated/superseded)
                        if rating_clean not in INVALID_RATINGS:
                            grouped_results[material_code][contract_id].append((rating_clean, expire_flag))

                # Also check for FF_FIRE (second flash fire rating)
                if contract_id == "flash_fire_report":
                    fire_rating_field = FLASH_FIRE_FIELD_MAP.get(contract_id)
                    if fire_rating_field and fire_rating_field in payload:
                        fire_rating = payload.get(fire_rating_field)
                        if fire_rating and isinstance(fire_rating, str):
                            fire_rating_clean = fire_rating.strip().upper()
                            if fire_rating_clean not in INVALID_RATINGS:
                                # Use special key for FF_FIRE
                                grouped_results[material_code]["flash_fire_report_fire"].append((fire_rating_clean, expire_flag))

            # Aggregate ratings for each material/test type
            for material_code, contract_ratings in grouped_results.items():
                if material_code not in all_ratings:
                    continue

                for contract_id, rating_pairs in contract_ratings.items():
                    # Determine MIUL column name
                    if contract_id == "flash_fire_report_fire":
                        miul_column = FLASH_FIRE_MIUL_COLUMNS["flash_fire_report"]
                    elif contract_id in MIUL_RATING_COLUMNS:
                        miul_column = MIUL_RATING_COLUMNS[contract_id]
                    else:
                        continue

                    rating_values = [p[0] for p in rating_pairs]
                    expire_flags = [p[1] for p in rating_pairs]
                    aggregated_rating = self._aggregate_ratings(rating_values)

                    if aggregated_rating:
                        all_ratings[material_code][miul_column] = aggregated_rating
                        if include_currency:
                            # Any expired data = mark column as expired
                            has_expired = any(f == "1" for f in expire_flags)
                            all_ratings[material_code][f"{miul_column}_CURRENCY"] = "EXPIRED" if has_expired else "CURRENT"

            LOGGER.info(
                f"Bulk rating fetch: {len(material_codes)} materials, "
                f"{sum(1 for r in all_ratings.values() for k in r if not k.endswith('_CURRENCY'))} ratings retrieved"
            )

        except Exception as e:
            LOGGER.error(f"Error in bulk rating fetch: {e}")

        finally:
            cursor.close()

        return all_ratings

    def _aggregate_ratings(self, ratings: List[str]) -> Optional[str]:
        """Aggregate multiple rating values using conservative worst-case approach.

        Args:
            ratings: List of rating values

        Returns:
            Single aggregated rating (worst-case)
        """
        if not ratings:
            return None

        valid_ratings = [r.upper() for r in ratings if r and isinstance(r, str)]

        if not valid_ratings:
            return None

        # Sort by severity and return worst
        sorted_ratings = sorted(
            valid_ratings,
            key=lambda r: RATING_SEVERITY.get(r, 999),
            reverse=True,
        )

        worst_rating = sorted_ratings[0]

        if len(set(valid_ratings)) > 1:
            LOGGER.warning(f"Multiple ratings found: {valid_ratings} - using worst: {worst_rating}")

        return worst_rating

    def enrich_miul_result(self, miul_result: "MIULBuildResult") -> "MIULBuildResult":
        """Enrich a MIULBuildResult with ratings from MAPTIS.

        Takes a MIULBuildResult, enriches the miul_data DataFrame with ratings,
        and returns a new MIULBuildResult with updated metadata.

        Args:
            miul_result: MIULBuildResult from MIULBuilder

        Returns:
            New MIULBuildResult with enriched data and updated metadata
        """
        from datetime import datetime
        from .models import MIULBuildResult, MIULMetadata

        start_time = datetime.utcnow()

        # Enrich the DataFrame
        enriched_df, stats = self.enrich_miul_dataframe(miul_result.miul_data)

        # Calculate new processing time
        end_time = datetime.utcnow()
        enrichment_time = (end_time - start_time).total_seconds()

        # Create updated metadata
        updated_metadata = MIULMetadata(
            build_id=miul_result.metadata.build_id,
            build_timestamp=miul_result.metadata.build_timestamp,
            processing_time_seconds=miul_result.metadata.processing_time_seconds + enrichment_time,
            source_bom_items=miul_result.metadata.source_bom_items,
            output_miul_rows=miul_result.metadata.output_miul_rows,
            material_coverage_percent=miul_result.metadata.material_coverage_percent,
            spec_coverage_percent=miul_result.metadata.spec_coverage_percent,
            validation_warnings=miul_result.metadata.validation_warnings,
            processing_errors=miul_result.metadata.processing_errors,
            nasa_swe_compliant=miul_result.metadata.nasa_swe_compliant,
            deterministic_hash=miul_result.metadata.deterministic_hash
        )

        # Add enrichment info to warnings for tracking
        enrichment_summary = (
            f"MAPTIS Enrichment: {stats['enriched_count']}/{stats['total_materials']} materials "
            f"({stats['coverage_pct']:.1f}%), {stats['total_ratings_added']} ratings added"
        )
        if stats['codes_looked_up'] > 0:
            enrichment_summary += f", {stats['codes_looked_up']} codes looked up from designation"

        updated_warnings = miul_result.warnings.copy()
        updated_warnings.append(enrichment_summary)

        # Create new result with enriched data
        return MIULBuildResult(
            miul_data=enriched_df,
            metadata=updated_metadata,
            warnings=updated_warnings,
            errors=miul_result.errors.copy(),
            audit_trail=miul_result.audit_trail.copy()
        )

    def enrich_miul_dataframe(
        self, miul_df: pd.DataFrame
    ) -> Tuple[pd.DataFrame, Dict[str, Any]]:
        """Enrich a MIUL DataFrame with ratings from MAPTIS.

        Workflow:
        1. If Material Code is empty, look it up from Designation column
           (JSC 27301F field 7: Material manufacturer's designation)
        2. Fetch ratings (FLAM, SCC, CORR, TVS, TOX, FS) using Material Code

        Args:
            miul_df: MIUL DataFrame with 'Material Code' and/or 'Designation' columns

        Returns:
            Tuple of (enriched_df, stats_dict)
        """
        # Ensure rating columns exist (including new MI, PI, FF_FLASH, FF_FIRE and currency columns)
        all_rating_columns = set(MIUL_RATING_COLUMNS.values()) | set(FLASH_FIRE_MIUL_COLUMNS.values())
        for column in all_rating_columns:
            if column not in miul_df.columns:
                miul_df[column] = pd.Series(dtype="object")
            else:
                miul_df[column] = miul_df[column].astype("object")
            # Also create currency column for each rating
            currency_col = f"{column}_CURRENCY"
            if currency_col not in miul_df.columns:
                miul_df[currency_col] = pd.Series(dtype="object")

        # Ensure Material Code column exists
        if "Material Code" not in miul_df.columns:
            miul_df["Material Code"] = pd.Series(dtype="object")

        # Detect designation column - prefer "Designation" (JSC 27301F field 7)
        designation_col = None
        if "Designation" in miul_df.columns:
            designation_col = "Designation"
        elif "Manufacturer Designation" in miul_df.columns:
            designation_col = "Manufacturer Designation"  # Legacy fallback

        # Step 1: Look up Material Code from designation where missing
        codes_looked_up = 0
        if designation_col:
            LOGGER.info(f"[MIUL] Looking up Material Codes from '{designation_col}' column...")
            for idx, row in miul_df.iterrows():
                material_code = row.get("Material Code")
                # If Material Code is empty/missing, try to look it up from designation
                if pd.isna(material_code) or not str(material_code).strip():
                    designation = row.get(designation_col)
                    if pd.notna(designation) and str(designation).strip():
                        # Extract form context (JSC 27301F fields)
                        # - Document Title (field 23): part description for form inference
                        # - Material Form (field 5): explicit form like BAR, SHEET, PLATE
                        part_description = str(row.get("Document Title", "")).strip()
                        material_form = str(row.get("Material Form", "")).strip()

                        found_code = self.find_material_code_by_designation(
                            str(designation).strip(),
                            part_description=part_description,
                            material_form=material_form,
                        )
                        if found_code:
                            miul_df.at[idx, "Material Code"] = found_code
                            codes_looked_up += 1

            if codes_looked_up > 0:
                LOGGER.info(f"[MIUL] Looked up {codes_looked_up} Material Codes from designations")

        # Step 2: Collect material codes to query for ratings
        material_codes_to_translate: List[Tuple[int, str]] = []
        for idx, row in miul_df.iterrows():
            material_code = row.get("Material Code")
            if pd.notna(material_code) and str(material_code).strip():
                material_codes_to_translate.append((idx, str(material_code).strip()))

        if not material_codes_to_translate:
            LOGGER.warning("No Material Codes available - cannot fetch ratings")
            return miul_df, {
                "total_materials": 0,
                "enriched_count": 0,
                "coverage_pct": 0,
                "codes_looked_up": codes_looked_up,
            }

        # Translate MIUL codes to database codes
        db_codes: Dict[int, str] = {}
        for idx, miul_code in material_codes_to_translate:
            db_code = self._translate_miul_code_to_db_code(miul_code)
            if db_code:
                db_codes[idx] = db_code

        # Bulk fetch ratings
        unique_db_codes = list(set(db_codes.values()))
        all_ratings = self.get_ratings_bulk(unique_db_codes)

        # Stats tracking
        enriched_count = 0
        total_ratings_added = 0

        # Populate DataFrame with ratings
        for idx, db_code in db_codes.items():
            ratings = all_ratings.get(db_code, {})
            if ratings:
                for rating_column, rating_value in ratings.items():
                    miul_df.at[idx, rating_column] = rating_value
                    total_ratings_added += 1
                enriched_count += 1

        total_processed = len(material_codes_to_translate)
        stats = {
            "total_materials": total_processed,
            "enriched_count": enriched_count,
            "coverage_pct": (enriched_count / total_processed * 100) if total_processed > 0 else 0,
            "total_ratings_added": total_ratings_added,
            "codes_looked_up": codes_looked_up,
            "ratings_by_type": {
                col: int(miul_df[col].notna().sum()) for col in set(MIUL_RATING_COLUMNS.values())
            },
        }

        LOGGER.info(
            f"Enrichment complete: {enriched_count}/{total_processed} materials "
            f"({stats['coverage_pct']:.1f}%), {total_ratings_added} ratings added, "
            f"{codes_looked_up} codes looked up from designation"
        )

        return miul_df, stats


# Global service instance
_enrichment_service: Optional[MIULEnrichmentService] = None


def get_enrichment_service() -> MIULEnrichmentService:
    """Get singleton enrichment service instance."""
    global _enrichment_service
    if _enrichment_service is None:
        _enrichment_service = MIULEnrichmentService()
    return _enrichment_service


def reset_enrichment_service() -> None:
    """Reset singleton for testing."""
    global _enrichment_service
    if _enrichment_service is not None:
        _enrichment_service.close()
    _enrichment_service = None


def enrich_miul_with_maptis_ratings(miul_result: "MIULBuildResult") -> "MIULBuildResult":
    """Convenience function to enrich a MIULBuildResult with MAPTIS ratings.

    Args:
        miul_result: MIULBuildResult from MIULBuilder

    Returns:
        New MIULBuildResult with enriched data

    Example:
        >>> from mira.miul.builder import build_miul_from_bom
        >>> from mira.miul.enrichment import enrich_miul_with_maptis_ratings
        >>>
        >>> # Step 1: Build MIUL
        >>> miul_result = build_miul_from_bom(bom_df, crosswalk_df, specs_df)
        >>>
        >>> # Step 2: Enrich with MAPTIS ratings
        >>> enriched_result = enrich_miul_with_maptis_ratings(miul_result)
        >>>
        >>> # Step 3: Export
        >>> enriched_result.to_excel("enriched_miul.xlsx")
    """
    service = get_enrichment_service()
    return service.enrich_miul_result(miul_result)


__all__ = [
    "MIULEnrichmentService",
    "get_enrichment_service",
    "reset_enrichment_service",
    "enrich_miul_with_maptis_ratings",
    "RATING_FIELD_MAP",
    "MIUL_RATING_COLUMNS",
    "FLASH_FIRE_FIELD_MAP",
    "FLASH_FIRE_MIUL_COLUMNS",
]
