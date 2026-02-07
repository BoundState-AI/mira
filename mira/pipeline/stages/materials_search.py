#!/usr/bin/env python3
"""
Alt Pipeline: Materials Search — Simple database lookup, no BOK rules.

For queries like "show me all fluorosilicones" where the user wants
a materials list, not a compatibility assessment.

Rule 5.1: Material family lookups should come from DB, not hardcoded dicts.
(Stopgap dict included with TODO to replace with table query.)

BoundState AI 2026
Version: 3.0.0

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI
"""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING, Optional

from ..stage import PipelineStage

if TYPE_CHECKING:
    from ..context import QueryContext

logger = logging.getLogger(__name__)

# TODO Rule 5.1: Replace with database table query.
# This is a stopgap. When Granta integration lands, these come from
# the materials taxonomy table.
_FAMILY_COMPOSITION_CODES = {
    "fluorosilicone": 833,
    "silicone": 832,
    "ptfe": 700,
    "teflon": 700,
    "aluminum": 100,
    "stainless": 200,
    "inconel": 300,
    "titanium": 400,
}


class MaterialsSearchStage(PipelineStage):
    """Alt pipeline: Simple materials database lookup."""

    def __init__(self, db_url: Optional[str] = None):
        self._db_url = db_url

    @property
    def name(self) -> str:
        return "materials_search"

    def should_skip(self, ctx: QueryContext) -> bool:
        return ctx.pipeline_name != "materials_search"

    def execute(self, ctx: QueryContext) -> QueryContext:
        import psycopg2
        import psycopg2.extras

        db_url = self._db_url or os.environ.get("MIRA_DB_URL")
        if not db_url:
            logger.warning("[MAT_SEARCH] No database URL")
            return ctx

        query_lower = ctx.raw_query.lower()

        # Identify composition code
        composition_key = None
        for family, code in _FAMILY_COMPOSITION_CODES.items():
            if family in query_lower:
                composition_key = code
                break

        results = []

        try:
            conn = psycopg2.connect(db_url)
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

            if composition_key:
                cur.execute("""
                    SELECT DISTINCT m.material_key, m.designation,
                           m.material_code, m.composition
                    FROM materials m WHERE m.composition = %s
                    ORDER BY m.designation LIMIT 100
                """, (composition_key,))
                results = [dict(r) for r in cur.fetchall()]

            if not results and ctx.constraints and ctx.constraints.material:
                cur.execute("""
                    SELECT DISTINCT m.material_key, m.designation,
                           m.material_code, m.composition
                    FROM materials m
                    WHERE LOWER(m.designation) LIKE LOWER(%s)
                    ORDER BY m.designation LIMIT 100
                """, (f"%{ctx.constraints.material}%",))
                results = [dict(r) for r in cur.fetchall()]

            cur.close()
            conn.close()

        except Exception as exc:
            logger.warning(f"[MAT_SEARCH] Query failed: {exc}")

        ctx.materials_found = results
        logger.info(f"[MAT_SEARCH] Found {len(results)} materials")

        return ctx
