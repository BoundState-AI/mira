#!/usr/bin/env python3
"""
Stage 6: Test Retrieval — Query MAPTIS test data.

Rule 1.2: Test data queried AFTER MUA precedents. Never before.

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


class TestRetrievalStage(PipelineStage):
    """Stage 6: Query MAPTIS test data from map.test_results."""

    def __init__(self, db_url: Optional[str] = None):
        self._db_url = db_url

    @property
    def name(self) -> str:
        return "test_retrieval"

    def should_skip(self, ctx: QueryContext) -> bool:
        if ctx.boundary_short_circuited:
            return True
        return ctx.pipeline_name not in ("compatibility",)

    def execute(self, ctx: QueryContext) -> QueryContext:
        import psycopg2
        import psycopg2.extras

        db_url = self._db_url or os.environ.get("MIRA_DB_URL")
        if not db_url:
            logger.warning("[TEST] No database URL")
            return ctx

        constraints = ctx.constraints

        try:
            conn = psycopg2.connect(db_url)
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

            query = """
                SELECT tr.result_id as material_id,
                       tr.material_id::text as material_name,
                       tr.environment,
                       tr.temp_max_c as temp_max_tested_c,
                       tr.pressure_max_pa as pressure_max_tested_pa,
                       tr.rating as highest_rating,
                       1 as test_count, tr.test_date
                FROM map.test_results tr WHERE 1=1
            """
            params = []

            if constraints and constraints.environment:
                query += " AND tr.environment = %s"
                params.append(constraints.environment)
            if constraints and constraints.pressure_psi:
                query += " AND tr.pressure_max_pa >= %s"
                params.append(constraints.pressure_psi * 6894.76)
            if constraints and constraints.temp_c_max:
                query += " AND tr.temp_max_c >= %s"
                params.append(constraints.temp_c_max)

            query += " ORDER BY tr.test_date DESC LIMIT 20"

            cur.execute(query, params)
            ctx.test_results = [dict(r) for r in cur.fetchall()]
            cur.close()
            conn.close()

            logger.info(f"[TEST] Found {len(ctx.test_results)} test results")

        except Exception as exc:
            logger.warning(f"[TEST] Query failed (will rely on semantic): {exc}")

        return ctx
