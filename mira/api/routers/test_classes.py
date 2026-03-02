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

# Reverse mapping: contract_id -> URL slug
CONTRACT_TO_SLUG = {v: k for k, v in SLUG_TO_CONTRACT.items()}

# Display names for test classes (matches frontend TEST_CLASS_FALLBACK)
TEST_CLASS_NAMES = {
    'tvs-outgassing': 'TVS Outgassing',
    'flammability': 'Flammability',
    'mechanical-impact': 'Mechanical Impact',
    'toxicity': 'Toxicity',
    'stress-corrosion-cracking': 'Stress Corrosion Cracking',
    'corrosion': 'Corrosion',
    'fluid-compatibility': 'Fluid Compatibility',
    'odor': 'Odor',
    'flash-fire': 'Flash Fire',
    'tensile-strength': 'Tensile Strength',
    'pneumatic-impact': 'Pneumatic Impact',
    'promoted-combustion': 'Promoted Combustion',
    'particle-impact': 'Particle Impact',
    'electrical-overload': 'Electrical Overload',
    'vcm-optical': 'VCM Optical',
    'electric-wire-insulation': 'Electric Wire Insulation',
    'low-cycle-fatigue': 'Low Cycle Fatigue',
    'fungus': 'Fungus',
    'fracture-mechanics': 'Fracture Mechanics',
    'creep-rupture': 'Creep Rupture',
    'high-cycle-fatigue': 'High Cycle Fatigue',
    'friction-heat': 'Friction Heat',
    'crack-growth': 'Crack Growth',
    'arc-tracking': 'Arc Tracking',
}

# Canonical rating fields per test type — single source of truth.
# Each entry: {'fields': [field_names_in_priority_order], 'context': label_or_None}
# For multi-context types (toxicity, flash-fire), each context gets its own entry.
# For single-rating types, one entry with context=None; fields tried in order.
CANONICAL_RATINGS = {
    'tvs_outgassing_report': [
        {'fields': ['tvs_rating', 'rating'], 'context': None},
    ],
    'flammability_report': [
        {'fields': ['flam_rtg', 'flam_rating', 'rating'], 'context': None},
    ],
    'mechanical_impact_report': [
        {'fields': ['mech_rating', 'rating'], 'context': None},
    ],
    'toxicity_report': [
        {'fields': ['tox_emurating'], 'context': 'EMU'},
        {'fields': ['tox_orionrating'], 'context': 'Orion'},
        {'fields': ['tox_shuttlerating'], 'context': 'Shuttle'},
        {'fields': ['tox_spacestationrating', 'tox_spacestationrtg'], 'context': 'Space Station'},
    ],
    'stress_corrosion_cracking_report': [
        {'fields': ['stress_rating', 'rating'], 'context': None},
    ],
    'corrosion_report': [
        {'fields': ['cor_rating', 'rating'], 'context': None},
    ],
    'fluid_compatibility_report': [
        {'fields': ['fluc_rating', 'fluid_rating', 'rating'], 'context': None},
    ],
    'odor_report': [
        {'fields': ['odor_rating', 'rating'], 'context': None},
    ],
    'flash_fire_report': [
        {'fields': ['fla_firerating'], 'context': 'Fire'},
        {'fields': ['fla_flashrating'], 'context': 'Flash'},
    ],
    'tensile_strength_report': [
        {'fields': ['tens_rating', 'rating'], 'context': None},
    ],
    'pneumatic_impact_report': [
        {'fields': ['pneu_rating', 'rating'], 'context': None},
    ],
    'promoted_combustion_report': [
        {'fields': ['prom_rating', 'rating'], 'context': None},
    ],
    'particle_impact_report': [
        {'fields': ['partimp_rating', 'rating'], 'context': None},
    ],
    'electrical_overload_report': [
        {'fields': ['elo_rating', 'rating'], 'context': None},
    ],
    'vcm_optical_report': [
        {'fields': ['vcm_rating', 'rating'], 'context': None},
    ],
    'electric_wire_insulation_report': [
        {'fields': ['ewi_rating', 'rating'], 'context': None},
    ],
    'low_cycle_fatigue_report': [
        {'fields': ['lowcyc_rating', 'rating'], 'context': None},
    ],
    'fungus_report': [
        {'fields': ['fung_rating', 'rating'], 'context': None},
    ],
    'fracture_mechanics_report': [
        {'fields': ['frac_rating', 'rating'], 'context': None},
    ],
    'creep_rupture_report': [
        {'fields': ['crp_rating', 'rating'], 'context': None},
    ],
    'high_cycle_fatigue_report': [
        {'fields': ['highcyc_rating', 'rating'], 'context': None},
    ],
    'friction_heat_report': [
        {'fields': ['fri_rating', 'rating'], 'context': None},
    ],
    'crack_growth_report': [
        {'fields': ['crk_rating', 'rating'], 'context': None},
    ],
    'arc_tracking_report': [
        {'fields': ['arc_rating', 'rating'], 'context': None},
    ],
}


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


def extract_canonical_ratings(contract_id: str, payload: dict) -> list:
    """Extract ratings with context labels using the canonical mapping.

    Returns list of {'value': str, 'context': str|None} dicts.
    For multi-context types (toxicity → EMU/Orion/Shuttle/ISS,
    flash-fire → Fire/Flash), returns one entry per populated context.
    For single-rating types, returns one entry with context=None.
    """
    entries = CANONICAL_RATINGS.get(contract_id, [])
    ratings = []
    for entry in entries:
        value = None
        for field in entry['fields']:
            v = payload.get(field)
            if v and str(v).strip() and str(v).strip().upper() not in ('NULL', 'N/A', 'NONE'):
                value = str(v).strip()
                break
        if value:
            ratings.append({'value': value, 'context': entry.get('context')})
    return ratings


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


@router.get("/api/materials/types")
async def get_material_types():
    """Get list of available material types for filter dropdowns."""
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute("""
            SELECT material_type_name, COUNT(*) as count
            FROM materials
            WHERE material_type_name IS NOT NULL
            GROUP BY material_type_name
            ORDER BY count DESC
        """)
        rows = cursor.fetchall()
        cursor.close()
        conn.close()
        return {"types": [{"name": r["material_type_name"], "count": r["count"]} for r in rows]}
    except Exception as e:
        logger.error(f"Error fetching material types: {e}")
        raise HTTPException(status_code=500, detail=str(e))


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
        # FC class enrichment: include tested fluid from curated FC table when available.
        if contract_id == 'fluid_compatibility_report':
            query = f"""
                SELECT DISTINCT ON (s.normalized_payload->>%s)
                    s.row_uid as id,
                    s.contract_id,
                    s.normalized_payload->>'materialkey' as material_code,
                    s.normalized_payload,
                    COALESCE(
                        m.designation,
                        CONCAT('Material ', s.normalized_payload->>'materialkey')
                    ) as material_designation,
                    fc_lookup.tested_fluid
                FROM silver_report_rows s
                LEFT JOIN materials m ON m.material_code = s.normalized_payload->>'materialkey'
                LEFT JOIN LATERAL (
                    SELECT string_agg(DISTINCT fc.media, '; ' ORDER BY fc.media) AS tested_fluid
                    FROM maptis.fluid_compatibility_tests fc
                    WHERE (s.normalized_payload->>'materialkey') ~ '^[0-9]+$'
                      AND fc.material_code = (s.normalized_payload->>'materialkey')::integer
                      AND NULLIF(BTRIM(s.normalized_payload->>'testreportnumber'), '') IS NOT NULL
                      AND UPPER(BTRIM(fc.test_report_no)) = UPPER(BTRIM(s.normalized_payload->>'testreportnumber'))
                ) fc_lookup ON TRUE
                WHERE {where_clause}
                ORDER BY s.normalized_payload->>%s, s.row_uid DESC
                LIMIT %s OFFSET %s
            """
            cursor.execute(query, [test_key_field, *params, test_key_field, per_page, offset])
        else:
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
                'tested_fluid': row.get('tested_fluid'),
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


@router.get("/api/materials/search")
async def search_materials(
    q: str = Query(..., min_length=2, max_length=100, description="Search query"),
    limit: int = Query(20, ge=1, le=50, description="Max materials to return"),
    material_type: Optional[str] = Query(None, description="Filter by material type (Metal, Polymer, etc.)"),
    test_class: Optional[str] = Query(None, description="Filter by test class slug (flammability, toxicity, etc.)"),
    rating: Optional[str] = Query(None, description="Filter by rating value (A, B, X, etc.)"),
):
    """Search materials across all test classes and return test profile scorecards.

    Queries the materials table by designation, composition, material type,
    and material code, then aggregates all test records across every test class
    for each matching material. Returns ratings extracted via the canonical
    mapping so each test type's rating(s) are normalized and labelled.
    """
    # Sanitize input
    search_sanitized = ''.join(c for c in q[:100] if c.isalnum() or c in ' -_.')
    if not search_sanitized.strip():
        return {"query": q, "results": [], "total_materials": 0}

    like = f"%{search_sanitized}%"

    # Resolve optional test_class slug to contract_id
    filter_contract_id = SLUG_TO_CONTRACT.get(test_class) if test_class else None

    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        # Build material WHERE clause
        mat_conditions = [
            "(designation ILIKE %s OR composition ILIKE %s OR material_type_name ILIKE %s OR material_code ILIKE %s)"
        ]
        mat_params: list = [like, like, like, like]

        if material_type:
            mat_conditions.append("material_type_name = %s")
            mat_params.append(material_type)

        mat_where = " AND ".join(mat_conditions)

        # Count total matching materials
        cursor.execute(f"""
            SELECT COUNT(DISTINCT material_code) as total
            FROM materials
            WHERE {mat_where}
        """, mat_params)
        total_materials = cursor.fetchone()['total']

        if total_materials == 0:
            cursor.close()
            conn.close()
            return {"query": q, "results": [], "total_materials": 0}

        # Build silver_report_rows WHERE clause
        silver_conditions = [
            "s.normalized_payload->>'materialkey' IN (SELECT material_code FROM matching_materials)"
        ]
        silver_params: list = []

        if filter_contract_id:
            silver_conditions.append("s.contract_id = %s")
            silver_params.append(filter_contract_id)

        if rating and filter_contract_id:
            rating_clause, rating_params = build_rating_filter(filter_contract_id, rating)
            # Prefix table alias on the clause (replace normalized_payload with s.normalized_payload)
            rating_clause_aliased = rating_clause.replace("normalized_payload", "s.normalized_payload")
            silver_conditions.append(rating_clause_aliased)
            silver_params.extend(rating_params)

        silver_where = " AND ".join(silver_conditions)

        # Get one representative test record per (material, test_type) with counts.
        cursor.execute(f"""
            WITH matching_materials AS (
                SELECT DISTINCT ON (material_code)
                    material_code, designation, composition, material_type_name
                FROM materials
                WHERE {mat_where}
                ORDER BY material_code
                LIMIT %s
            ),
            grouped AS (
                SELECT
                    s.normalized_payload->>'materialkey' as material_code,
                    s.contract_id,
                    s.row_uid,
                    s.normalized_payload,
                    COUNT(*) OVER (
                        PARTITION BY s.normalized_payload->>'materialkey', s.contract_id
                    ) as record_count,
                    ROW_NUMBER() OVER (
                        PARTITION BY s.normalized_payload->>'materialkey', s.contract_id
                        ORDER BY s.row_uid DESC
                    ) as rn
                FROM silver_report_rows s
                WHERE {silver_where}
            )
            SELECT
                g.material_code,
                mm.designation,
                mm.composition,
                mm.material_type_name,
                g.contract_id,
                g.row_uid,
                g.normalized_payload,
                g.record_count
            FROM grouped g
            JOIN matching_materials mm ON mm.material_code = g.material_code
            WHERE g.rn = 1
            ORDER BY mm.designation, g.contract_id
        """, [*mat_params, limit, *silver_params])

        rows = cursor.fetchall()
        cursor.close()
        conn.close()

        # Assemble material scorecards
        materials: dict = {}
        for row in rows:
            mc = row['material_code']
            if mc not in materials:
                materials[mc] = {
                    'material_code': mc,
                    'designation': row['designation'] or f'Material {mc}',
                    'composition': row['composition'],
                    'material_type': row['material_type_name'],
                    'test_profile': [],
                }

            contract_id = row['contract_id']
            slug = CONTRACT_TO_SLUG.get(contract_id)
            if not slug:
                continue

            payload = row['normalized_payload'] or {}
            ratings = extract_canonical_ratings(contract_id, payload)

            materials[mc]['test_profile'].append({
                'test_class': slug,
                'test_name': TEST_CLASS_NAMES.get(slug, slug),
                'record_count': row['record_count'],
                'record_id': row['row_uid'],
                'ratings': ratings,
            })

        # Attach summary counts
        total_classes = len(SLUG_TO_CONTRACT)
        results = []
        for mat in materials.values():
            mat['tested_classes'] = len(mat['test_profile'])
            mat['total_classes'] = total_classes
            results.append(mat)

        return {
            "query": q,
            "results": results,
            "total_materials": total_materials,
        }

    except Exception as e:
        logger.error(f"Error in material search: {e}")
        import traceback
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(e))


__safety_critical__ = True  # NASA SWE-032 compliance
