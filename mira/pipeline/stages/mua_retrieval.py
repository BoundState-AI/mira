#!/usr/bin/env python3
"""
Stage 5: MUA Retrieval — Query MUA precedents FIRST.

Rule 1.1: MUA precedents ALWAYS queried before any decision.
Uses V6 FAISS retriever (preferred), falls back to SQL.

BoundState AI 2026
Version: 3.0.0

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Dict, List, Optional

from ..context import EnvironmentClass
from ..stage import PipelineStage

if TYPE_CHECKING:
    from ..context import QueryContext

logger = logging.getLogger(__name__)


class MUARetrievalStage(PipelineStage):
    """
    Stage 5: Query MUA precedents from V6 FAISS + SQL fallback.

    Populates ctx.mua_precedents with matched records.
    """

    def __init__(self, db_url: Optional[str] = None):
        self._db_url = db_url
        self._v6_retriever = None
        self._v6_loaded = False

    def _get_v6_retriever(self):
        """Lazy-load V6 FAISS retriever."""
        if not self._v6_loaded:
            self._v6_loaded = True
            try:
                from mira.mua.v6.retriever import V6PrecedentRetriever
                retriever = V6PrecedentRetriever()
                if retriever.is_loaded():
                    self._v6_retriever = retriever
                    logger.info(
                        f"[MUA] V6 retriever loaded: "
                        f"{retriever._index_builder._index.ntotal} precedents"
                    )
            except Exception as exc:
                logger.warning(f"[MUA] V6 retriever unavailable: {exc}")
        return self._v6_retriever

    @property
    def name(self) -> str:
        return "mua_retrieval"

    def should_skip(self, ctx: QueryContext) -> bool:
        if ctx.boundary_short_circuited:
            return True
        return ctx.pipeline_name not in ("compatibility",)

    def execute(self, ctx: QueryContext) -> QueryContext:
        constraints = ctx.constraints
        env_class = constraints.environment_class if constraints else None

        # Try V6 FAISS first
        v6 = self._get_v6_retriever()
        if v6:
            results = self._query_v6(v6, constraints, env_class)
            if results:
                ctx.mua_precedents = results
                logger.info(f"[MUA] V6 returned {len(results)} precedents")
                return ctx
            logger.info("[MUA] V6 returned 0 results, falling back to SQL")

        # SQL fallback
        results = self._query_sql(constraints, env_class)
        ctx.mua_precedents = results
        logger.info(f"[MUA] SQL returned {len(results)} precedents")

        return ctx

    def _query_v6(
        self, v6, constraints, requested_env: Optional[EnvironmentClass]
    ) -> List[Dict]:
        """Query V6 FAISS retriever with hybrid BM25 + FAISS search."""
        query_parts = []
        if constraints and constraints.material:
            query_parts.extend([constraints.material, constraints.material])  # 2x boost
        if requested_env == EnvironmentClass.OXYGEN:
            query_parts.append("oxygen compatibility")
        elif requested_env == EnvironmentClass.HYDROGEN:
            query_parts.append("hydrogen compatibility")
        elif constraints and constraints.environment:
            query_parts.append(constraints.environment)

        if not query_parts:
            query_parts.append("material compatibility")

        search_query = " ".join(query_parts)

        try:
            if hasattr(v6, "search_hybrid") and v6._bm25 is not None:
                raw = v6.search_hybrid(search_query, top_k=20, bm25_candidates=50, faiss_candidates=50)
                raw_results = [(rec, score) for rec, score, _, _ in raw]
            else:
                raw_results = v6.search_raw(search_query, top_k=15)
        except Exception as exc:
            logger.warning(f"[MUA] V6 search failed: {exc}")
            return []

        results = []
        for record, score in raw_results:
            v6_env = record.environment.type.value if record.environment else "unknown"
            env_class = self._map_v6_env(v6_env)

            determination = (record.determination or "UNKNOWN").upper()
            if determination not in ("APPROVED", "CONDITIONAL", "UNKNOWN"):
                continue

            is_primary = (requested_env is not None and env_class == requested_env)

            results.append({
                "mua_number": record.mua_number,
                "material_name": record.material_designation,
                "material_specification": record.specification,
                "determination": determination,
                "rationale": record.rationale,
                "rationale_summary": record.application,
                "pressure_psi_max": record.environment.pressure_psia if record.environment else None,
                "temp_c_max": record.environment.temperature_f if record.environment else None,
                "o2_concentration_pct": record.environment.o2_percent if record.environment else None,
                "env_class": env_class.value,
                "is_primary_for_env": is_primary,
                "inferred_environment": v6_env,
                "hazards": [
                    (i.value if hasattr(i, "value") else str(i))
                    for i in (record.issues or [])
                ],
                "v6_score": score,
                "source": "v6_faiss",
            })

        # Re-rank: material name matches first, then primary environment
        if constraints and constraints.material:
            mat_lower = constraints.material.lower()
            results.sort(
                key=lambda r: (
                    mat_lower in (r.get("material_name") or "").lower(),
                    r.get("is_primary_for_env", False),
                ),
                reverse=True,
            )

        return results

    def _query_sql(
        self, constraints, requested_env: Optional[EnvironmentClass]
    ) -> List[Dict]:
        """Fallback: Query bok.mua_precedents via SQL."""
        import os
        import psycopg2
        import psycopg2.extras

        db_url = self._db_url or os.environ.get("MIRA_DB_URL")
        if not db_url:
            logger.warning("[MUA] No database URL — cannot query SQL")
            return []

        try:
            conn = psycopg2.connect(db_url)
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

            query = """
                SELECT mua_number, material_name, material_specification,
                       determination, rationale, rationale_summary, mitigations,
                       pressure_psi_max, temp_c_min, temp_c_max, o2_concentration_pct,
                       parser_confidence, is_reviewed, parsed_date
                FROM bok.mua_precedents
                WHERE determination IN ('APPROVED', 'CONDITIONAL')
            """
            params = []

            if constraints and constraints.material:
                query += " AND LOWER(material_name) LIKE LOWER(%s)"
                params.append(f"%{constraints.material}%")

            if constraints and constraints.pressure_psi:
                query += " AND pressure_psi_max >= %s"
                params.append(constraints.pressure_psi)

            query += " ORDER BY is_reviewed DESC, parser_confidence DESC LIMIT 10"

            cur.execute(query, params)
            rows = [dict(r) for r in cur.fetchall()]
            cur.close()
            conn.close()

            return rows

        except Exception as exc:
            logger.warning(f"[MUA] SQL query failed: {exc}")
            return []

    @staticmethod
    def _map_v6_env(v6_env: str) -> EnvironmentClass:
        """Map V6 EnvironmentType string to EnvironmentClass."""
        if v6_env in ("lox_gox", "enriched_o2", "pure_o2"):
            return EnvironmentClass.OXYGEN
        if v6_env in ("hydrogen",):
            return EnvironmentClass.HYDROGEN
        if v6_env in ("vacuum", "cabin_air", "ambient"):
            return EnvironmentClass.AIR_VACUUM
        return EnvironmentClass.OTHER
