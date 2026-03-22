#!/usr/bin/env python3
"""
Module: Heritage Failures Database
Purpose: PostgreSQL storage for heritage failure records used by MIRA v4 veto engine.

BoundState AI 2026
Version: 4.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: SWE-013, SWE-032, NASA-STD-8739.8B
Safety Critical: True

Uses raw psycopg2 following the established BoundState pattern
(see mira/api/routers/test_classes.py, mira/core/db_config.py).

Table: heritage_failures
    failure_id        TEXT PRIMARY KEY
    material_key      TEXT NOT NULL (indexed)
    failure_environment JSONB NOT NULL
    failure_description TEXT
    created_at        TIMESTAMPTZ DEFAULT NOW()
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, List, Optional

from psycopg2.extras import RealDictCursor

from mira.core.db_config import open_db_connection

logger = logging.getLogger(__name__)


def _heritage_db_disabled() -> bool:
    """Check whether heritage DB integration is disabled via environment."""
    return os.getenv("MIRA_DISABLE_HERITAGE_DB", "").strip().lower() in {"1", "true", "yes"}

# SQL for table creation (idempotent)
CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS heritage_failures (
    failure_id          TEXT PRIMARY KEY,
    material_key        TEXT NOT NULL,
    failure_environment JSONB NOT NULL DEFAULT '{}',
    failure_description TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_heritage_failures_material_key
    ON heritage_failures (material_key);
"""


def _get_connection():
    """Get a psycopg2 connection using centralised config."""
    if _heritage_db_disabled():
        raise RuntimeError("heritage DB disabled via MIRA_DISABLE_HERITAGE_DB")

    try:
        return open_db_connection()
    except Exception:
        logger.warning(
            "[HERITAGE_DB] Could not load db_config; falling back to defaults"
        )
        import psycopg2
        return psycopg2.connect(
            host="localhost",
            port=5432,
            database="mira",
            user="postgres",
            password="postgres",
        )


def ensure_table() -> None:
    """Create the heritage_failures table if it does not exist."""
    if _heritage_db_disabled():
        logger.info("[HERITAGE_DB] Skipping table ensure (MIRA_DISABLE_HERITAGE_DB enabled)")
        return

    conn = _get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(CREATE_TABLE_SQL)
        conn.commit()
        logger.info("[HERITAGE_DB] heritage_failures table ensured")
    except Exception as exc:
        conn.rollback()
        logger.error("[HERITAGE_DB] Failed to create table: %s", exc)
        raise
    finally:
        conn.close()


def get_heritage_records(material_key: str) -> List[Dict[str, Any]]:
    """Query heritage failure records for a specific material.

    Args:
        material_key: Material identifier to look up.

    Returns:
        List of heritage failure dicts compatible with
        HeritageVetoEngine.check_heritage() format:
        [{"failure_id": str, "material_key": str,
          "failure_environment": dict, "failure_description": str}, ...]
    """
    if _heritage_db_disabled():
        return []

    conn = _get_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT failure_id, material_key, failure_environment,
                       failure_description
                FROM heritage_failures
                WHERE material_key = %s
                ORDER BY created_at DESC
                """,
                (material_key,),
            )
            rows = cur.fetchall()

        results = []
        for row in rows:
            env = row["failure_environment"]
            if isinstance(env, str):
                env = json.loads(env)
            results.append({
                "failure_id": row["failure_id"],
                "material_key": row["material_key"],
                "failure_environment": env,
                "failure_description": row["failure_description"] or "",
            })

        logger.debug(
            "[HERITAGE_DB] Found %d heritage records for material '%s'",
            len(results),
            material_key,
        )
        return results

    except Exception as exc:
        logger.error(
            "[HERITAGE_DB] Query failed for material '%s': %s",
            material_key,
            exc,
        )
        return []
    finally:
        conn.close()


def insert_heritage_record(
    failure_id: str,
    material_key: str,
    failure_environment: Dict[str, Any],
    failure_description: str = "",
) -> bool:
    """Insert a new heritage failure record.

    Args:
        failure_id: Unique failure identifier.
        material_key: Material that failed.
        failure_environment: Environment conditions as dict (stored as JSONB).
        failure_description: Human-readable description of the failure.

    Returns:
        True if inserted, False on error.
    """
    if _heritage_db_disabled():
        logger.info("[HERITAGE_DB] Insert skipped (MIRA_DISABLE_HERITAGE_DB enabled)")
        return False

    conn = _get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO heritage_failures
                    (failure_id, material_key, failure_environment, failure_description)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (failure_id) DO NOTHING
                """,
                (
                    failure_id,
                    material_key,
                    json.dumps(failure_environment),
                    failure_description,
                ),
            )
        conn.commit()
        logger.info(
            "[HERITAGE_DB] Inserted heritage record: failure_id='%s' material='%s'",
            failure_id,
            material_key,
        )
        return True
    except Exception as exc:
        conn.rollback()
        logger.error("[HERITAGE_DB] Insert failed: %s", exc)
        return False
    finally:
        conn.close()
