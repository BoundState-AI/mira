#!/usr/bin/env python3
"""
Module: Review Queue
Purpose: Material Review Queue Module.

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

import json
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

import psycopg2
from psycopg2.extras import DictCursor, Json

LOGGER = logging.getLogger(__name__)
AUDIT_LOGGER = logging.getLogger("miul.material_audit")


# DDL for review queue table
# Requires pgcrypto extension for gen_random_uuid()
# Alternative: Use uuid-ossp extension with uuid_generate_v4()
REVIEW_QUEUE_DDL = """
-- Ensure pgcrypto extension for gen_random_uuid()
CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS miul_material_review_queue (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    miul_item_id uuid NULL,
    miul_id uuid NULL,
    designation text NOT NULL,
    material_spec text NULL,
    context jsonb NULL,
    candidates jsonb NOT NULL DEFAULT '[]'::jsonb,
    suggested_code text NULL,
    confidence text NOT NULL CHECK (confidence IN ('low', 'none')),
    status text NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'resolved', 'rejected')),
    resolved_by text NULL,
    resolved_at timestamp NULL,
    resolved_code text NULL,
    notes text NULL,
    created_at timestamp NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_review_queue_status
    ON miul_material_review_queue (status);
CREATE INDEX IF NOT EXISTS idx_review_queue_miul_item
    ON miul_material_review_queue (miul_item_id);
CREATE INDEX IF NOT EXISTS idx_review_queue_miul
    ON miul_material_review_queue (miul_id);
CREATE INDEX IF NOT EXISTS idx_review_queue_designation
    ON miul_material_review_queue (designation);
"""

# Triage query for prioritizing review queue items
TRIAGE_QUERY = """
WITH candidate_keys AS (
    SELECT q.id, (c->>'material_code')::text AS material_code
    FROM miul_material_review_queue q
    CROSS JOIN LATERAL jsonb_array_elements(q.candidates) AS c
    WHERE q.status = 'open'
),
candidate_with_ratings AS (
    SELECT ck.id, COUNT(*) AS rating_hits
    FROM candidate_keys ck
    JOIN silver_report_rows s
        ON s.normalized_payload->>'materialkey' = ck.material_code
    GROUP BY ck.id
)
SELECT q.*, COALESCE(cwr.rating_hits, 0) AS rating_hits,
    CASE
        WHEN COALESCE(cwr.rating_hits, 0) > 0 THEN 1  -- Has ratings - priority
        WHEN q.confidence = 'none' THEN 2             -- No match at all
        ELSE 3                                        -- Low confidence
    END AS triage_priority
FROM miul_material_review_queue q
LEFT JOIN candidate_with_ratings cwr ON cwr.id = q.id
WHERE q.status = 'open'
ORDER BY triage_priority ASC, q.created_at ASC;
"""


class MaterialReviewQueue:
    """Manages quarantined material lookups for human review."""

    def __init__(
        self,
        host: str = "localhost",
        port: int = 5432,
        database: str = "mira",
        user: str = "postgres",
        password: str = "postgres",
    ):
        """Initialize the review queue service."""
        self._conn_params = {
            "host": host,
            "port": port,
            "database": database,
            "user": user,
            "password": password,
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

    def ensure_table_exists(self) -> bool:
        """Create review queue table if it doesn't exist.

        Returns:
            True if table was created, False if already exists
        """
        conn = self._get_connection()
        cursor = conn.cursor()

        try:
            cursor.execute(REVIEW_QUEUE_DDL)
            conn.commit()
            LOGGER.info("Review queue table ensured")
            return True
        except Exception as e:
            LOGGER.error(f"Error creating review queue table: {e}")
            conn.rollback()
            return False
        finally:
            cursor.close()

    def add_to_queue(
        self,
        designation: str,
        candidates: List[Dict[str, Any]],
        confidence: str = "low",
        miul_item_id: Optional[str] = None,
        miul_id: Optional[str] = None,
        material_spec: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> Optional[str]:
        """Add a quarantined item to the review queue.

        Args:
            designation: Original designation string
            candidates: List of candidate material matches
            confidence: 'low' or 'none'
            miul_item_id: UUID of the MIUL line item (if applicable)
            miul_id: UUID of the MIUL document (if applicable)
            material_spec: Material specification string (if available)
            context: Additional context (source file, row number, etc.)

        Returns:
            Queue item ID if successful, None otherwise
        """
        conn = self._get_connection()
        cursor = conn.cursor()

        try:
            cursor.execute(
                """
                INSERT INTO miul_material_review_queue
                    (designation, candidates, confidence, miul_item_id, miul_id,
                     material_spec, context)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                RETURNING id
                """,
                (
                    designation,
                    Json(candidates),
                    confidence,
                    miul_item_id,
                    miul_id,
                    material_spec,
                    Json(context) if context else None,
                ),
            )
            result = cursor.fetchone()
            conn.commit()

            queue_id = str(result[0]) if result else None
            LOGGER.info(f"Added to review queue: {designation} -> {queue_id}")
            return queue_id

        except Exception as e:
            LOGGER.error(f"Error adding to review queue: {e}")
            conn.rollback()
            return None
        finally:
            cursor.close()

    def get_open_items(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Get open review queue items, prioritized by triage rules.

        Priority order:
        1. Items with rating data available (can be verified)
        2. Items with no candidates at all
        3. Items with low-confidence candidates

        Args:
            limit: Maximum items to return

        Returns:
            List of queue items with triage priority
        """
        conn = self._get_connection()
        cursor = conn.cursor(cursor_factory=DictCursor)

        try:
            cursor.execute(TRIAGE_QUERY + f" LIMIT {limit}")
            items = []
            for row in cursor.fetchall():
                items.append(dict(row))
            return items

        except Exception as e:
            LOGGER.error(f"Error fetching review queue: {e}")
            return []
        finally:
            cursor.close()

    def resolve_item(
        self,
        queue_id: str,
        resolved_code: str,
        resolved_by: str,
        notes: Optional[str] = None,
    ) -> bool:
        """Resolve a review queue item with selected material code.

        Args:
            queue_id: Review queue item ID
            resolved_code: Selected material code
            resolved_by: User who resolved the item
            notes: Optional resolution notes

        Returns:
            True if resolved successfully
        """
        conn = self._get_connection()
        cursor = conn.cursor()

        try:
            cursor.execute(
                """
                UPDATE miul_material_review_queue
                SET status = 'resolved',
                    resolved_code = %s,
                    resolved_by = %s,
                    resolved_at = now(),
                    notes = %s
                WHERE id = %s AND status = 'open'
                RETURNING id
                """,
                (resolved_code, resolved_by, notes, queue_id),
            )
            result = cursor.fetchone()
            conn.commit()

            if result:
                LOGGER.info(f"Resolved queue item {queue_id} -> {resolved_code}")
                return True
            else:
                LOGGER.warning(f"Queue item {queue_id} not found or already resolved")
                return False

        except Exception as e:
            LOGGER.error(f"Error resolving queue item: {e}")
            conn.rollback()
            return False
        finally:
            cursor.close()

    def reject_item(
        self,
        queue_id: str,
        resolved_by: str,
        notes: Optional[str] = None,
    ) -> bool:
        """Reject a review queue item (no valid material code).

        Args:
            queue_id: Review queue item ID
            resolved_by: User who rejected the item
            notes: Reason for rejection

        Returns:
            True if rejected successfully
        """
        conn = self._get_connection()
        cursor = conn.cursor()

        try:
            cursor.execute(
                """
                UPDATE miul_material_review_queue
                SET status = 'rejected',
                    resolved_by = %s,
                    resolved_at = now(),
                    notes = %s
                WHERE id = %s AND status = 'open'
                RETURNING id
                """,
                (resolved_by, notes, queue_id),
            )
            result = cursor.fetchone()
            conn.commit()

            if result:
                LOGGER.info(f"Rejected queue item {queue_id}")
                return True
            else:
                LOGGER.warning(f"Queue item {queue_id} not found or already resolved")
                return False

        except Exception as e:
            LOGGER.error(f"Error rejecting queue item: {e}")
            conn.rollback()
            return False
        finally:
            cursor.close()

    def get_stats(self) -> Dict[str, int]:
        """Get review queue statistics.

        Returns:
            Dict with open, resolved, rejected counts
        """
        conn = self._get_connection()
        cursor = conn.cursor(cursor_factory=DictCursor)

        try:
            cursor.execute(
                """
                SELECT status, COUNT(*) as count
                FROM miul_material_review_queue
                GROUP BY status
                """
            )
            stats = {"open": 0, "resolved": 0, "rejected": 0}
            for row in cursor.fetchall():
                stats[row["status"]] = row["count"]
            return stats

        except Exception as e:
            LOGGER.error(f"Error getting queue stats: {e}")
            return {"open": 0, "resolved": 0, "rejected": 0}
        finally:
            cursor.close()


def log_material_lookup(
    designation: str,
    method: str,
    selected_code: Optional[str],
    score: float,
    candidates: List[Dict[str, Any]],
    action: str,
    normalized_uns: Optional[str] = None,
    llm_info: Optional[Dict[str, Any]] = None,
) -> None:
    """Log every material lookup decision for audit trail.

    Args:
        designation: Original designation string
        method: Lookup method used (uns_normalized, exact_match, family_filtered, etc.)
        selected_code: Material code selected (None if quarantined)
        score: Confidence score (0.0-1.0)
        candidates: List of candidate materials considered
        action: Action taken (auto_applied, applied_with_warning, quarantined)
        normalized_uns: UNS code if normalization was successful
        llm_info: LLM tie-breaker info if used
    """
    audit_record = {
        "event": "material_code_lookup",
        "designation": designation,
        "normalized_uns": normalized_uns,
        "lookup_stage": method,
        "candidates": candidates,
        "selected_code": selected_code,
        "score": score,
        "action": action,
        "llm": llm_info,
        "timestamp": datetime.utcnow().isoformat() + "Z",
    }
    AUDIT_LOGGER.info(json.dumps(audit_record))


# Global service instance
_review_queue: Optional[MaterialReviewQueue] = None


def get_review_queue() -> MaterialReviewQueue:
    """Get singleton review queue instance."""
    global _review_queue
    if _review_queue is None:
        _review_queue = MaterialReviewQueue()
    return _review_queue


def reset_review_queue() -> None:
    """Reset singleton for testing."""
    global _review_queue
    if _review_queue is not None:
        _review_queue.close()
    _review_queue = None


__all__ = [
    "MaterialReviewQueue",
    "get_review_queue",
    "reset_review_queue",
    "log_material_lookup",
    "REVIEW_QUEUE_DDL",
    "TRIAGE_QUERY",
]
