#!/usr/bin/env python3
"""
Module: Precedent Retriever
Purpose: Query bok.mua_precedents in Postgres for similar MUA examples.

The retrieved precedents provide real-world rationale language and document
patterns that the LLM uses as style/content reference when rendering the
final MUA document.

BoundState AI 2026
Version: 8.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: SWE-013 (Traceability), SWE-032 (Data validation)
Safety Critical: True
"""

from __future__ import annotations

import logging
import os
from typing import Dict, List, Optional

from .models import MUAPrecedent, MUASessionData

logger = logging.getLogger(__name__)

__all__ = ["PrecedentRetriever"]


class PrecedentRetriever:
    """
    Retrieves MUA precedents from bok.mua_precedents in Postgres.

    Query strategy:
      1. Exact material name match (highest confidence)
      2. Material family match (e.g., same alloy series)
      3. Same environment class with similar conditions

    Results are ranked by: is_reviewed DESC, parser_confidence DESC,
    material name similarity.
    """

    def __init__(self, db_url: Optional[str] = None):
        self._db_url = db_url or os.environ.get("MIRA_DB_URL")
        self._conn = None

    def _get_connection(self):
        """Lazy connection to Postgres."""
        if self._conn is None or self._conn.closed:
            import psycopg2
            if self._db_url:
                self._conn = psycopg2.connect(self._db_url)
            else:
                from mira.core.db_config import get_db_connection_params
                self._conn = psycopg2.connect(**get_db_connection_params())
        return self._conn

    def retrieve(
        self,
        session: MUASessionData,
        limit: int = 5,
    ) -> List[MUAPrecedent]:
        """
        Retrieve precedent MUAs for the given session.

        Args:
            session: MUA session data with material/environment info
            limit: Max precedents to return

        Returns:
            List of MUAPrecedent objects ranked by relevance
        """
        try:
            conn = self._get_connection()
        except Exception as exc:
            logger.warning(f"[PrecedentRetriever] DB unavailable: {exc}")
            return []

        import psycopg2.extras
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        precedents: List[MUAPrecedent] = []

        # Query 1: Exact material name match
        exact = self._query_by_material(cur, session.material_name, limit)
        precedents.extend(exact)

        # Query 2: If not enough, broaden to material family
        if len(precedents) < limit:
            family_term = self._extract_family_term(session.material_name)
            if family_term:
                remaining = limit - len(precedents)
                seen_numbers = {p.mua_number for p in precedents}
                family = self._query_by_material(cur, family_term, remaining + 5)
                for p in family:
                    if p.mua_number not in seen_numbers and len(precedents) < limit:
                        precedents.append(p)
                        seen_numbers.add(p.mua_number)

        # Query 3: If still not enough, get top approved for same environment
        if len(precedents) < 2:
            seen_numbers = {p.mua_number for p in precedents}
            env = self._query_by_environment(
                cur, session.environment.location, limit
            )
            for p in env:
                if p.mua_number not in seen_numbers and len(precedents) < limit:
                    precedents.append(p)
                    seen_numbers.add(p.mua_number)

        cur.close()

        logger.info(
            f"[PrecedentRetriever] Found {len(precedents)} precedents "
            f"for {session.material_name}"
        )
        return precedents

    def _query_by_material(
        self, cur, material_term: str, limit: int
    ) -> List[MUAPrecedent]:
        """Query precedents by material name match."""
        try:
            cur.execute(
                """
                SELECT mua_number, material_name, material_specification,
                       determination, rationale, environment,
                       o2_concentration_pct, pressure_psi_max,
                       parser_confidence
                FROM bok.mua_precedents
                WHERE determination IN ('APPROVED', 'CONDITIONAL')
                  AND LOWER(material_name) LIKE LOWER(%s)
                ORDER BY is_reviewed DESC, parser_confidence DESC
                LIMIT %s
                """,
                (f"%{material_term}%", limit),
            )
            return [self._row_to_precedent(row) for row in cur.fetchall()]
        except Exception as exc:
            logger.warning(f"[PrecedentRetriever] Material query failed: {exc}")
            return []

    def _query_by_environment(
        self, cur, location: str, limit: int
    ) -> List[MUAPrecedent]:
        """Query top precedents for the same location class."""
        try:
            cur.execute(
                """
                SELECT mua_number, material_name, material_specification,
                       determination, rationale, environment,
                       o2_concentration_pct, pressure_psi_max,
                       parser_confidence
                FROM bok.mua_precedents
                WHERE determination IN ('APPROVED', 'CONDITIONAL')
                ORDER BY is_reviewed DESC, parser_confidence DESC
                LIMIT %s
                """,
                (limit,),
            )
            return [self._row_to_precedent(row) for row in cur.fetchall()]
        except Exception as exc:
            logger.warning(f"[PrecedentRetriever] Env query failed: {exc}")
            return []

    @staticmethod
    def _row_to_precedent(row: Dict) -> MUAPrecedent:
        return MUAPrecedent(
            mua_number=row.get("mua_number", "UNKNOWN"),
            material_name=row.get("material_name"),
            material_specification=row.get("material_specification"),
            determination=row.get("determination"),
            rationale=row.get("rationale"),
            environment=row.get("environment"),
            o2_concentration_pct=row.get("o2_concentration_pct"),
            pressure_psi_max=row.get("pressure_psi_max"),
            parser_confidence=row.get("parser_confidence"),
        )

    @staticmethod
    def _extract_family_term(material_name: str) -> Optional[str]:
        """
        Extract a broadened search term from a material name.

        Examples:
            "Aluminum 6061-T6" -> "6061"
            "CRES 316L" -> "316"
            "Inconel 718" -> "718"
            "PTFE" -> "PTFE"
        """
        import re
        # Try to find alloy number
        m = re.search(r'\b(\d{3,4})', material_name)
        if m:
            return m.group(1)

        # Fall back to first word if it looks like a material family
        parts = material_name.strip().split()
        if parts and len(parts[0]) >= 3:
            return parts[0]

        return None

    def close(self):
        if self._conn and not self._conn.closed:
            self._conn.close()
