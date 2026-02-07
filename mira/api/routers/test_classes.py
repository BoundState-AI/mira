#!/usr/bin/env python3
"""
Module: Test Classes
Purpose: Copyright (c) 2025 BoundState Inc. All Rights Reserved.

BoundState AI 2025
Version: 1.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Fran OpenAI 5 <noreply@openai.com>
Co-Authored-By: Grok 4.0 <noreply@x.ai>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: NASA-CSET, SWE-013, SWE-032
Safety Critical: True
"""

import csv
import logging
from io import StringIO
from typing import Optional

import psycopg2
from psycopg2.extras import RealDictCursor
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse

logger = logging.getLogger(__name__)

router = APIRouter(tags=["test-classes"])

# Test key fields for deduplication via DISTINCT ON
# Using test-specific keys to match MAPTIS counting method
TEST_KEY_FIELDS = {
    'tvs_outgassing_report': 'tvs_key',
    'flammability_report': 'flam_key',
    'mechanical_impact_report': 'mech_key',
    'toxicity_report': 'tox_key',
    'stress_corrosion_cracking_report': 'stress_key',
    'corrosion_report': 'cor_key',
    'fluid_compatibility_report': 'testreportkey',
    'odor_report': 'odor_key',
    'flash_fire_report': 'fla_key',
    'tensile_strength_report': 'tens_key',
    'pneumatic_impact_report': 'pneu_key',
    'promoted_combustion_report': 'prom_key',
    'particle_impact_report': 'partimp_key',
    'electrical_overload_report': 'elo_key',
    'vcm_optical_report': 'vcm_key',
    'electric_wire_insulation_report': 'ewi_key',
    'low_cycle_fatigue_report': 'lowcyc_key',
    'fungus_report': 'fung_key',
    'fracture_mechanics_report': 'frac_key',
    'creep_rupture_report': 'crp_key',
    'high_cycle_fatigue_report': 'highcyc_key',
    'friction_heat_report': 'fri_key',
    'crack_growth_report': 'crk_key',
    'arc_tracking_report': 'arc_key',
}

# Mapping from URL slugs to database contract_ids
SLUG_TO_CONTRACT = {
    'tvs-outgassing': 'tvs_outgassing_report',
    'flammability': 'flammability_report',
    'mechanical-impact': 'mechanical_impact_report',
    'toxicity': 'toxicity_report',
    'stress-corrosion-cracking': 'stress_corrosion_cracking_report',
    'corrosion': 'corrosion_report',
    'fluid-compatibility': 'fluid_compatibility_report',
    'odor': 'odor_report',
    'flash-fire': 'flash_fire_report',
    'tensile-strength': 'tensile_strength_report',
    'pneumatic-impact': 'pneumatic_impact_report',
    'promoted-combustion': 'promoted_combustion_report',
    'particle-impact': 'particle_impact_report',
    'electrical-overload': 'electrical_overload_report',
    'vcm-optical': 'vcm_optical_report',
    'electric-wire-insulation': 'electric_wire_insulation_report',
    'low-cycle-fatigue': 'low_cycle_fatigue_report',
    'fungus': 'fungus_report',
    'fracture-mechanics': 'fracture_mechanics_report',
    'creep-rupture': 'creep_rupture_report',
    'high-cycle-fatigue': 'high_cycle_fatigue_report',
    'friction-heat': 'friction_heat_report',
    'crack-growth': 'crack_growth_report',
    'arc-tracking': 'arc_tracking_report',
}

# All possible rating field names
RATING_FIELDS = [
    'rating', 'rtg', 'flam_rtg', 'flam_rating',
    'fla_rating', 'fla_firerating', 'fla_flashrating',
    'pneu_rating', 'mech_rating', 'partimp_rating', 'prom_rating',
    'cor_rating', 'elo_rating', 'ewi_rating',
    'fluc_rating', 'fluid_rating',
    'fung_rating', 'odor_rating', 'stress_rating', 'tens_rating',
    'tox_rating', 'tox_shuttlerating', 'tox_rtg',
    'tox_emurating', 'tox_orionrating', 'tox_spacestationrating', 'tox_spacestationrtg',
    'tvs_rating', 'vcm_rating', 'arc_rating', 'lowcyc_rating', 'highcyc_rating',
    'fri_rating', 'crk_rating', 'frac_rating', 'crp_rating'
]


def get_db_connection():
    """Get database connection using centralized config."""
    try:
        from mira.core.db_config import get_db_connection_params
        return psycopg2.connect(**get_db_connection_params())
    except ImportError:
        # Fallback if db_config not available
        import os
        return psycopg2.connect(
            host=os.environ.get('POSTGRES_HOST', 'localhost'),
            port=int(os.environ.get('POSTGRES_PORT', '5432')),
            database=os.environ.get('POSTGRES_DB', 'mira'),
            user=os.environ.get('POSTGRES_USER', 'postgres'),
            password=os.environ.get('POSTGRES_PASSWORD', 'postgres'),
        )


def extract_rating(payload: dict) -> Optional[str]:
    """Extract rating value from payload using all known rating field names."""
    for field in RATING_FIELDS:
        if payload.get(field):
            return payload.get(field)
    return None


def build_rating_filter(contract_id: str, rating: str, rating_type: Optional[str] = None):
    """Build rating filter clause and params for a given contract type."""
    where_clause = ""
    params = []

    if contract_id == 'toxicity_report' and rating_type and rating_type != 'all':
        where_clause = f"(normalized_payload->>'{rating_type}' = %s)"
        params = [rating]
    elif contract_id == 'toxicity_report':
        rating_fields = [
            'tox_emurating', 'tox_orionrating', 'tox_shuttlerating',
            'tox_spacestationrating', 'tox_spacestationrtg', 'tox_rtg'
        ]
        rating_conditions = [f"(normalized_payload->>'{field}' = %s)" for field in rating_fields]
        where_clause = f"({' OR '.join(rating_conditions)})"
        params = [rating] * len(rating_conditions)
    elif contract_id == 'flash_fire_report':
        rating_fields = ['fla_firerating', 'fla_flashrating', 'fla_rating']
        rating_conditions = [f"(normalized_payload->>'{field}' = %s)" for field in rating_fields]
        where_clause = f"({' OR '.join(rating_conditions)})"
        params = [rating] * len(rating_conditions)
    elif contract_id == 'fluid_compatibility_report':
        rating_fields = ['fluc_rating', 'fluid_rating']
        rating_conditions = [f"(normalized_payload->>'{field}' = %s)" for field in rating_fields]
        where_clause = f"({' OR '.join(rating_conditions)})"
        params = [rating] * len(rating_conditions)
    else:
        rating_conditions = [f"(normalized_payload->>'{field}' = %s)" for field in RATING_FIELDS]
        where_clause = f"({' OR '.join(rating_conditions)})"
        params = [rating] * len(rating_conditions)

    return where_clause, params


@router.get("/api/test-classes/counts")
async def get_test_class_counts():
    """Get counts of unique test reports for all test classes."""
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        counts = {}
        for slug, contract_id in SLUG_TO_CONTRACT.items():
            test_key = TEST_KEY_FIELDS.get(contract_id)
            if not test_key:
                counts[slug] = 0
                continue

            cursor.execute("""
                SELECT COUNT(DISTINCT normalized_payload->>%s) as count
                FROM silver_report_rows
                WHERE contract_id = %s
                AND normalized_payload->>%s IS NOT NULL
            """, [test_key, contract_id, test_key])

            result = cursor.fetchone()
            counts[slug] = result['count'] if result else 0

        cursor.close()
        conn.close()
        return counts

    except Exception as e:
        logger.error(f"Error fetching test class counts: {e}")
        import traceback
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/test-records/{test_type}")
async def get_test_records(
    test_type: str,
    page: int = Query(1, ge=1, description="Page number"),
    per_page: int = Query(50, ge=1, le=500, description="Records per page"),
    rating: Optional[str] = Query(None, description="Filter by rating"),
    rating_type: Optional[str] = Query(None, description="Specific rating type field (toxicity only)"),
    std_test_flag: Optional[str] = Query(None, description="Standard test flag filter (toxicity only)"),
    search: Optional[str] = Query(None, description="Search material name/code"),
):
    """Get paginated test records with deduplication via DISTINCT ON."""
    contract_id = SLUG_TO_CONTRACT.get(test_type)
    if not contract_id:
        raise HTTPException(status_code=404, detail=f"Unknown test type: {test_type}")

    test_key_field = TEST_KEY_FIELDS.get(contract_id)
    if not test_key_field:
        raise HTTPException(status_code=500, detail=f"No test key mapping for {contract_id}")

    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        where_clauses = ["contract_id = %s"]
        params = [contract_id]

        # Rating filter
        if rating and rating.lower() != 'all':
            rating_clause, rating_params = build_rating_filter(contract_id, rating, rating_type)
            where_clauses.append(rating_clause)
            params.extend(rating_params)

        # Standard test flag filter (toxicity only)
        if std_test_flag and std_test_flag.lower() != 'all':
            where_clauses.append("(normalized_payload->>'tox_nonstandardflag' = %s)")
            params.append(std_test_flag)

        # Search filter - JOIN to materials table for designation search
        if search:
            search_sanitized = search[:100]
            search_sanitized = ''.join(c for c in search_sanitized if c.isalnum() or c in ' -_.')
            if search_sanitized.strip():
                like = f"%{search_sanitized}%"
                # Join to materials via material_code (materialkey stores material_code, not material_key)
                where_clauses.append("""
                    EXISTS (
                        SELECT 1 FROM materials m
                        WHERE m.material_code = normalized_payload->>'materialkey'
                          AND (
                              m.designation ILIKE %s
                              OR m.composition ILIKE %s
                              OR m.material_type_name ILIKE %s
                          )
                    )
                """)
                params.extend([like, like, like])

        where_clause = " AND ".join(where_clauses)

        # Count query using only %s placeholders
        count_query = f"""
            SELECT COUNT(DISTINCT normalized_payload->>%s) as total
            FROM silver_report_rows
            WHERE {where_clause}
        """
        cursor.execute(count_query, [test_key_field, *params])
        total_records = cursor.fetchone()['total']

        total_pages = (total_records + per_page - 1) // per_page
        offset = (page - 1) * per_page

        # Fetch records - JOIN via material_code (materialkey stores material_code, not material_key)
        query = f"""
            SELECT DISTINCT ON (s.normalized_payload->>%s)
                s.row_uid as id,
                s.contract_id,
                s.normalized_payload->>'materialkey' as material_code,
                s.normalized_payload,
                COALESCE(
                    m.designation,
                    CONCAT('Material ', s.normalized_payload->>'materialkey')
                ) as material_designation
            FROM silver_report_rows s
            LEFT JOIN materials m ON m.material_code = s.normalized_payload->>'materialkey'
            WHERE {where_clause}
            ORDER BY s.normalized_payload->>%s, s.row_uid DESC
            LIMIT %s OFFSET %s
        """
        cursor.execute(query, [test_key_field, *params, test_key_field, per_page, offset])
        rows = cursor.fetchall()

        records = []
        for row in rows:
            payload = row['normalized_payload'] or {}
            records.append({
                'id': row['id'],
                'material_key': row['material_code'],  # Return as material_key for API compatibility
                'material_designation': row['material_designation'],
                'test_results': payload,
                'rating': extract_rating(payload),
                'contract_id': row['contract_id'],
            })

        cursor.close()
        conn.close()

        return {
            'records': records,
            'pagination': {
                'page': page,
                'per_page': per_page,
                'total_records': total_records,
                'total_pages': total_pages,
            }
        }

    except Exception as e:
        logger.error(f"Error fetching test records for {test_type}: {e}")
        import traceback
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/test-records/{test_type}/ratings")
async def get_test_type_ratings(test_type: str):
    """Get list of available ratings for a test type."""
    contract_id = SLUG_TO_CONTRACT.get(test_type)
    if not contract_id:
        raise HTTPException(status_code=404, detail=f"Unknown test type: {test_type}")

    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        # Choose rating fields based on test type
        if contract_id == 'toxicity_report':
            rating_fields = [
                'tox_emurating', 'tox_orionrating', 'tox_shuttlerating',
                'tox_spacestationrating', 'tox_spacestationrtg', 'tox_rtg',
                'tox_nonstandardflag'
            ]
        elif contract_id == 'flash_fire_report':
            rating_fields = ['fla_firerating', 'fla_flashrating', 'fla_rating']
        elif contract_id == 'fluid_compatibility_report':
            rating_fields = ['fluc_rating', 'fluid_rating']
        else:
            rating_fields = RATING_FIELDS[:20]  # Use subset for other types

        union_parts = [
            f"SELECT DISTINCT normalized_payload->>'{field}' as rating FROM silver_report_rows WHERE contract_id = %s"
            for field in rating_fields
        ]
        query = f"""
            WITH ratings_union AS (
                {' UNION '.join(union_parts)}
            )
            SELECT rating FROM ratings_union
            WHERE rating IS NOT NULL AND rating != ''
            ORDER BY rating
        """
        cursor.execute(query, [contract_id] * len(rating_fields))
        rows = cursor.fetchall()
        ratings = [row['rating'] for row in rows]

        cursor.close()
        conn.close()
        return {"ratings": ratings}

    except Exception as e:
        logger.error(f"Error fetching ratings for {test_type}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/test-records/{test_type}/export")
async def export_test_records(
    test_type: str,
    rating: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
):
    """Export test records as CSV."""
    contract_id = SLUG_TO_CONTRACT.get(test_type)
    if not contract_id:
        raise HTTPException(status_code=404, detail=f"Unknown test type: {test_type}")

    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        where_clauses = ["contract_id = %s"]
        params = [contract_id]

        if rating and rating.lower() != 'all':
            rating_clause, rating_params = build_rating_filter(contract_id, rating, None)
            where_clauses.append(rating_clause)
            params.extend(rating_params)

        if search:
            search_sanitized = search[:100]
            search_sanitized = ''.join(c for c in search_sanitized if c.isalnum() or c in ' -_.')
            if search_sanitized.strip():
                like = f"%{search_sanitized}%"
                # Join to materials via material_code (materialkey stores material_code, not material_key)
                where_clauses.append("""
                    EXISTS (
                        SELECT 1 FROM materials m
                        WHERE m.material_code = normalized_payload->>'materialkey'
                          AND (
                              m.designation ILIKE %s
                              OR m.composition ILIKE %s
                              OR m.material_type_name ILIKE %s
                          )
                    )
                """)
                params.extend([like, like, like])

        where_clause = " AND ".join(where_clauses)

        query = f"""
            SELECT
                s.normalized_payload->>'materialkey' as material_code,
                m.designation,
                s.normalized_payload
            FROM silver_report_rows s
            LEFT JOIN materials m ON m.material_code = s.normalized_payload->>'materialkey'
            WHERE {where_clause}
            ORDER BY material_code
        """
        cursor.execute(query, params)
        rows = cursor.fetchall()

        output = StringIO()
        writer = csv.writer(output)
        writer.writerow(['Material Code', 'Designation', 'Rating', 'Contract ID'])

        for row in rows:
            payload = row['normalized_payload'] or {}
            writer.writerow([
                row['material_code'],
                row['designation'] or '',
                extract_rating(payload) or '',
                contract_id
            ])

        cursor.close()
        conn.close()

        output.seek(0)
        return StreamingResponse(
            iter([output.getvalue()]),
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename={test_type}-records.csv"}
        )

    except Exception as e:
        logger.error(f"Error exporting test records for {test_type}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


__safety_critical__ = True  # NASA SWE-032 compliance
