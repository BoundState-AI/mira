#!/usr/bin/env python3
"""
Module: Material Resolver
Purpose: Deterministic material identifier resolution with AND-first, OR-fallback logic.

BoundState AI 2025
Version: 1.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Fran OpenAI 5 <noreply@openai.com>
Co-Authored-By: Grok 4.0 <noreply@x.ai>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: NASA-STD-8739.8B:
Safety Critical: True
"""

from __future__ import annotations

import logging
from typing import Literal, Optional, List, Dict, Any
from dataclasses import dataclass, field
from uuid import uuid4
from datetime import datetime

import psycopg2
import psycopg2.extras
from pydantic import BaseModel, Field, ConfigDict

from src.utils.exceptions import (
    SafetyCriticalError,
    DataIntegrityError,
    ErrorSeverity,
    ErrorCategory,
)
from src.monitoring.material_metrics import (
    resolution_total,
    conflict_total,
    resolution_duration,
    match_strength_distribution,
    fallback_used_total,
)

__all__ = [
    'MaterialResolution',
    'MaterialResolver',
    'ResolutionStatus',
    'normalize_code',
    'normalize_key',
]

__safety_critical__ = True

logger = logging.getLogger(__name__)
safety_logger = logging.getLogger('safety')
metrics_logger = logging.getLogger('metrics')

ResolutionStatus = Literal['and_match', 'or_fallback', 'conflict', 'no_match']


class MaterialResolution(BaseModel):
    """Resolution result with full audit trail.

    This model captures the complete outcome of a material identifier
    resolution attempt, including status, matched material ID, confidence
    level (match strength), all candidates considered, and a full decision
    trace for audit purposes.

    Attributes:
        status: Resolution outcome (and_match, or_fallback, conflict, no_match)
        material_id: Resolved material ID if successful
        match_strength: Confidence level (2=AND, 1=OR, 0=none)
        candidates: List of all candidate materials considered
        decision_trace: Full audit trail with inputs, normalization, hits
        conflict_details: Details if conflict detected (key→A, code→B)

    Compliance:
        SWE-032: Data validation
        SWE-033: Configuration management
    """

    model_config = ConfigDict(extra='forbid', populate_by_name=True)

    status: ResolutionStatus
    material_id: Optional[str] = None
    match_strength: int = Field(0, ge=0, le=2)
    candidates: List[Dict[str, Any]] = Field(default_factory=list)
    decision_trace: Dict[str, Any] = Field(default_factory=dict)
    conflict_details: Optional[Dict[str, Any]] = None


class MaterialResolver:
    """Deterministic material resolution with AND-first, OR-fallback logic.

    This resolver implements a two-phase strategy:
    1. AND-first: Try to match where BOTH key AND code point to same material
    2. OR-fallback: If AND fails, accept single-identifier matches
    3. Conflict detection: Fail closed if identifiers point to different materials

    The resolver maintains full audit trails and integrates with Prometheus
    metrics for observability.

    Args:
        dsn: PostgreSQL connection string

    Example:
        >>> resolver = MaterialResolver("dbname=maptis user=readonly")
        >>> result = resolver.resolve(key="60486", code="10018")
        >>> if result.status == "and_match":
        ...     print(f"High confidence match: {result.material_id}")

    Compliance:
        NASA-STD-8739.8B:
            - SWE-013: Requirements and planning
            - SWE-032: Traceability
            - SWE-033: Configuration management
    """

    __safety_critical__ = True

    def __init__(self, dsn: str):
        """Initialize resolver with database connection string.

        Args:
            dsn: PostgreSQL connection string (e.g., "dbname=maptis user=readonly")
        """
        self._dsn = dsn
        logger.info("MaterialResolver initialized", extra={"dsn_masked": dsn.split('@')[-1] if '@' in dsn else "local"})

    def resolve(
        self,
        key: Optional[str],
        code: Optional[str],
        match_mode: Literal['AND_THEN_OR', 'AND_ONLY', 'OR_ONLY'] = 'AND_THEN_OR',
        policy_on_conflict: Literal['RETURN', 'RAISE'] = 'RETURN',
    ) -> MaterialResolution:
        """Resolve material using key and/or code with deterministic logic.

        Resolution Strategy:
            1. Normalize inputs (preserve leading zeros in codes)
            2. Query database for matches on both identifiers
            3. Score matches: 2=both hit, 1=one hits, 0=no hits
            4. Detect conflicts: key→A and code→B (different materials)
            5. Return best match with full audit trail

        Args:
            key: Legacy material key (numeric string, optional)
            code: Material code (formatted string, optional)
            match_mode: Resolution strategy (AND_THEN_OR, AND_ONLY, OR_ONLY)
            policy_on_conflict: How to handle conflicts (RETURN or RAISE)

        Returns:
            MaterialResolution with status, material_id, strength, audit trail

        Raises:
            SafetyCriticalError: If policy_on_conflict='RAISE' and conflict detected
            DataIntegrityError: If database query fails

        Compliance:
            SWE-013: Requirements traceability
            SWE-032: Data validation
        """
        req_id = str(uuid4())
        t0 = datetime.utcnow()

        # Normalize inputs
        norm_key = self._normalize_key(key) if key else None
        norm_code = self._normalize_code(code) if code else None

        trace = {
            'req_id': req_id,
            'timestamp': t0.isoformat(),
            'inputs': {'key': key, 'code': code, 'match_mode': match_mode},
            'normalized': {'key': norm_key, 'code': norm_code},
        }

        logger.info(
            "Resolving material identifiers",
            extra={'req_id': req_id, 'key': key, 'code': code, 'mode': match_mode}
        )

        # No inputs = no match
        if not (norm_key or norm_code):
            resolution_total.labels(status='no_match', mode=match_mode).inc()
            metrics_logger.info("No identifiers provided", extra={'req_id': req_id})
            return MaterialResolution(status='no_match', decision_trace=trace)

        # Execute query
        try:
            rows = self._query_hits(norm_key, norm_code)
        except psycopg2.Error as e:
            error_msg = "Database error during material resolution"
            logger.error(error_msg, extra={'req_id': req_id, 'error': str(e)})
            safety_logger.error(error_msg, extra={'req_id': req_id, 'error': str(e)})

            dt = (datetime.utcnow() - t0).total_seconds()
            resolution_duration.observe(dt)

            raise DataIntegrityError(
                message=error_msg,
                error_code='MAPTIS-RES-001',
                severity=ErrorSeverity.HIGH,
                category=ErrorCategory.DATA_INTEGRITY,
                details={'req_id': req_id, 'error': str(e)},
                recovery_suggestions=['Verify database connectivity', 'Check materials table schema'],
                nasa_compliance_ref='SWE-032',
            ) from e

        if not rows:
            resolution_total.labels(status='no_match', mode=match_mode).inc()
            logger.info("No matching materials found", extra={'req_id': req_id, 'trace': trace})

            dt = (datetime.utcnow() - t0).total_seconds()
            resolution_duration.observe(dt)

            return MaterialResolution(status='no_match', decision_trace=trace)

        # Detect conflicts
        key_materials = {r['material_id'] for r in rows if r['key_hit'] > 0}
        code_materials = {r['material_id'] for r in rows if r['code_hit'] > 0}

        conflict = (
            match_mode != 'OR_ONLY'
            and key_materials
            and code_materials
            and key_materials.isdisjoint(code_materials)
        )

        if conflict:
            conflict_total.inc()
            trace['conflict'] = {
                'key_resolves_to': list(key_materials),
                'code_resolves_to': list(code_materials),
            }

            logger.warning(
                "Material resolution conflict detected",
                extra={'req_id': req_id, 'trace': trace}
            )
            safety_logger.warning(
                "Material identifier conflict - identifiers point to different materials",
                extra={'req_id': req_id, 'conflict': trace['conflict']}
            )

            resolution_total.labels(status='conflict', mode=match_mode).inc()

            res = MaterialResolution(
                status='conflict',
                candidates=rows[:5],
                decision_trace=trace,
                conflict_details=trace['conflict'],
            )

            if policy_on_conflict == 'RAISE':
                dt = (datetime.utcnow() - t0).total_seconds()
                resolution_duration.observe(dt)

                raise SafetyCriticalError(
                    message="Material identifiers conflict; reconciliation required",
                    error_code='MAPTIS-RES-002',
                    severity=ErrorSeverity.HIGH,
                    category=ErrorCategory.DATA_INTEGRITY,
                    details={'req_id': req_id, 'conflict': trace['conflict']},
                    recovery_suggestions=[
                        'Verify material_key and material_code are for same material',
                        'Consult MAPTIS database administrator',
                        'Use single identifier for lookup',
                    ],
                    nasa_compliance_ref='SWE-032',
                )

            dt = (datetime.utcnow() - t0).total_seconds()
            resolution_duration.observe(dt)

            return res

        # Determine status from best match
        best = rows[0]
        if best['match_strength'] == 2:
            status: ResolutionStatus = 'and_match'
        elif best['match_strength'] == 1:
            status = 'or_fallback'
        else:
            status = 'no_match'

        # Record metrics
        match_strength_distribution.labels(str(best['match_strength'])).set(best['match_strength'])
        resolution_total.labels(status=status, mode=match_mode).inc()

        dt = (datetime.utcnow() - t0).total_seconds()
        resolution_duration.observe(dt)

        trace['hits'] = rows[:5]

        logger.info(
            f"Material resolved: {status}",
            extra={'req_id': req_id, 'material_id': best['material_id'], 'strength': best['match_strength']}
        )

        metrics_logger.info(
            "Resolution completed",
            extra={'req_id': req_id, 'status': status, 'duration_ms': dt * 1000}
        )

        return MaterialResolution(
            status=status,
            material_id=best['material_id'],
            match_strength=best['match_strength'],
            candidates=rows[:5],
            decision_trace=trace,
        )

    def _query_hits(self, key: Optional[str], code: Optional[str]) -> List[Dict[str, Any]]:
        """Query materials table with CASE-based scoring.

        Uses portable SQL with parameter binding and CASE statements for
        scoring. Preserves leading zeros in codes.

        Args:
            key: Normalized key (numeric string)
            code: Normalized code (formatted string)

        Returns:
            List of matching material dicts with match_strength scores

        Compliance:
            SWE-032: Data validation
        """
        sql = """
        WITH hits AS (
            SELECT
                m.material_id,
                m.designation,
                SUM(CASE WHEN %s IS NOT NULL AND m.material_id = %s THEN 1 ELSE 0 END) AS key_hit,
                SUM(CASE WHEN %s IS NOT NULL AND m.material_id = %s THEN 1 ELSE 0 END) AS code_hit
            FROM materials m
            WHERE (%s IS NOT NULL AND m.material_id = %s)
               OR (%s IS NOT NULL AND m.material_id = %s)
            GROUP BY m.material_id, m.designation
        )
        SELECT
            material_id,
            designation,
            CASE
                WHEN key_hit > 0 AND code_hit > 0 THEN 2
                WHEN key_hit > 0 OR code_hit > 0 THEN 1
                ELSE 0
            END AS match_strength,
            key_hit,
            code_hit
        FROM hits
        ORDER BY match_strength DESC, material_id ASC
        LIMIT 10
        """

        params = (key, key, code, code, key, key, code, code)

        with psycopg2.connect(self._dsn) as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(sql, params)
                rows = cur.fetchall()

        return [dict(row) for row in rows]

    @staticmethod
    def _normalize_code(value: str) -> str:
        """Normalize material code: trim whitespace, preserve leading zeros and case.

        Args:
            value: Raw material code string

        Returns:
            Normalized code with leading zeros preserved

        Compliance:
            SWE-033: Configuration management
        """
        return value.strip()

    @staticmethod
    def _normalize_key(value: str) -> str:
        """Normalize material key: validate numeric, keep as string.

        Args:
            value: Raw key string

        Returns:
            Validated numeric string

        Raises:
            ValueError: If value contains non-numeric characters

        Compliance:
            SWE-033: Configuration management
        """
        v = value.strip()
        if not v.isdigit():
            logger.warning(f"Non-numeric key rejected: {value}")
            return ''
        return v  # Keep as string to match database text fields


# Module-level convenience functions
def normalize_code(code: str) -> str:
    """Normalize material code (module-level convenience function)."""
    return MaterialResolver._normalize_code(code)


def normalize_key(key: str) -> str:
    """Normalize material key (module-level convenience function)."""
    return MaterialResolver._normalize_key(key)
