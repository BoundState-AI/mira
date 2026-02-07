#!/usr/bin/env python3
"""
Stage 9: Decide — Make material suitability decisions.

Delegates to the existing MaterialDecider but fixes Rule 5.4:
environment field derived from MUA env_class, not hardcoded.

BoundState AI 2026
Version: 3.0.0

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI
"""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING

from ..stage import PipelineStage

if TYPE_CHECKING:
    from ..context import QueryContext

logger = logging.getLogger(__name__)


class DecideStage(PipelineStage):
    """
    Stage 9: Generate material decisions based on accumulated evidence.

    Uses the existing MaterialDecider from MIRA_V2.
    """

    @property
    def name(self) -> str:
        return "decide"

    def should_skip(self, ctx: QueryContext) -> bool:
        if ctx.boundary_short_circuited:
            return True
        if not ctx.has_sufficient_evidence:
            return True
        return ctx.pipeline_name not in ("compatibility",)

    def execute(self, ctx: QueryContext) -> QueryContext:
        from mira.MIRA_V2.src.material_decider import MaterialDecider

        decider = MaterialDecider()
        decisions = []
        constraints_dict = ctx.constraints.to_dict() if ctx.constraints else {}

        # Fetch requirements if not already loaded
        if not ctx.requirements:
            ctx.requirements = self._fetch_requirements()

        # Process test results as candidates
        for test in ctx.test_results:
            material_name = test.get("material_name", "")
            relevant_muas = [
                m for m in ctx.mua_precedents
                if (m.get("material_name") or "").lower() in material_name.lower()
                or material_name.lower() in (m.get("material_name") or "").lower()
            ]
            decision = decider.decide_material_suitability(
                candidate=test,
                constraints=constraints_dict,
                mua_precedents=relevant_muas,
                test_evidence=[],
                requirements=ctx.requirements,
            )
            decisions.append(decision.to_dict())

        # Rule 5.4 FIX: If no test results, use MUA precedents as candidates
        # with environment derived from MUA env_class (NOT hardcoded 'oxygen')
        if not ctx.test_results and ctx.mua_precedents:
            logger.info(
                f"[DECIDE] No test results — using {len(ctx.mua_precedents)} "
                f"MUA precedent(s) as candidates"
            )
            for mua in ctx.mua_precedents:
                pressure_psi = mua.get("pressure_psi_max")
                pressure_pa = float(pressure_psi) * 6894.76 if pressure_psi else None
                temp_c = mua.get("temp_c_max")
                temp_c = float(temp_c) if temp_c else None

                # Rule 5.4: environment from MUA, not hardcoded
                mua_env = mua.get("env_class", mua.get("inferred_environment", "unknown"))

                candidate = {
                    "material_id": mua.get("mua_id"),
                    "material_name": mua.get("material_name", "Unknown"),
                    "environment": mua_env,
                    "temp_max_tested_c": temp_c,
                    "pressure_max_tested_pa": pressure_pa,
                    "highest_rating": mua.get("determination"),
                    "test_count": 1,
                    "source": "MUA_PRECEDENT",
                }

                decision = decider.decide_material_suitability(
                    candidate=candidate,
                    constraints=constraints_dict,
                    mua_precedents=[mua],
                    test_evidence=[],
                    requirements=ctx.requirements,
                )
                decisions.append(decision.to_dict())

        ctx.decisions = decisions
        logger.info(f"[DECIDE] Generated {len(decisions)} decisions")

        return ctx

    @staticmethod
    def _fetch_requirements():
        """Load BOK requirements from database."""
        import psycopg2
        import psycopg2.extras

        db_url = os.environ.get("MIRA_DB_URL")
        if not db_url:
            return []

        try:
            conn = psycopg2.connect(db_url)
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cur.execute("""
                SELECT r.req_id, r.section_id, r.action, r.description, r.predicate,
                       s.spec_id, s.section_number, s.heading
                FROM bok.requirements r
                JOIN bok.sections s ON r.section_id = s.section_id
                WHERE s.is_normative = true
                ORDER BY s.spec_id, s.section_number
            """)
            rows = [dict(r) for r in cur.fetchall()]
            cur.close()
            conn.close()
            return rows
        except Exception as exc:
            logger.warning(f"[DECIDE] Requirements fetch failed: {exc}")
            return []
