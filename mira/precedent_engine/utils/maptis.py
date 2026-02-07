#!/usr/bin/env python3
"""
Module: Maptis
Purpose: [Automatically migrated - needs manual review]

BoundState AI 2025
Version: 1.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Fran OpenAI 5 <noreply@openai.com>
Co-Authored-By: Grok 4.0 <noreply@x.ai>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: SWE-013, NASA-STD-6016
Safety Critical: True
"""

from __future__ import annotations

import asyncio
import logging
import os
from concurrent.futures import ThreadPoolExecutor
from typing import Optional, Protocol
import uuid

logger = logging.getLogger(__name__)


class MAPTISLookupProtocol(Protocol):
    """Protocol for MAPTIS lookup functions."""

    async def __call__(
        self, material_name: str, specification: str | None
    ) -> tuple[str | None, float]:
        """
        Look up material in MAPTIS.

        Args:
            material_name: Material designation
            specification: Material specification (AMS, ASTM, etc.)

        Returns:
            Tuple of (material_key, confidence_score)
            material_key is None if not found
            confidence_score is 0.0-1.0
        """
        ...


class MAPTISClient:
    """
    Client for MAPTIS database lookups.

    This client connects to the MAPTIS PostgreSQL database to resolve material
    designations to canonical keys using the silver layer materials table.
    """

    def __init__(
        self,
        connection_string: str | None = None,
        max_workers: int = 4,
    ) -> None:
        """
        Initialize the MAPTIS client.

        Args:
            connection_string: Database connection string (optional, uses env vars)
            max_workers: Thread pool size for async operations
        """
        self.connection_string = connection_string
        self._executor = ThreadPoolExecutor(max_workers=max_workers)
        self._connection = None
        self._conn_params = None

    def _get_conn_params(self) -> dict:
        """Get database connection parameters."""
        if self._conn_params is None:
            # KNOWN RISK: Development defaults - see db_config.py security note
            try:
                from mira.core.db_config import get_db_connection_params
                self._conn_params = get_db_connection_params()
            except ImportError:
                self._conn_params = {
                    "host": os.environ.get("POSTGRES_HOST", "localhost"),
                    "port": int(os.environ.get("POSTGRES_PORT", "5432")),
                    "database": os.environ.get("POSTGRES_DB", "mira"),
                    "user": os.environ.get("POSTGRES_USER", "postgres"),
                    # KNOWN RISK: Hardcoded default password for development
                    "password": os.environ.get("POSTGRES_PASSWORD", "postgres"),
                }
        return self._conn_params

    def _get_connection(self):
        """Get or create database connection."""
        if self._connection is None or self._connection.closed:
            try:
                import psycopg2
                self._connection = psycopg2.connect(**self._get_conn_params())
            except ImportError:
                logger.warning("[MAPTIS] psycopg2 not available - returning None for lookups")
                return None
            except Exception as e:
                logger.error(f"[MAPTIS] Database connection failed: {e}")
                return None
        return self._connection

    def _lookup_sync(
        self, material_name: str, specification: str | None
    ) -> tuple[str | None, float]:
        """
        Synchronous MAPTIS lookup against silver layer materials table.

        Searches by designation pattern match with ranking by relevance.
        Returns material_code (as string) and confidence score.
        """
        if not material_name:
            return None, 0.0

        conn = self._get_connection()
        if conn is None:
            return None, 0.0

        try:
            from psycopg2.extras import RealDictCursor
            cursor = conn.cursor(cursor_factory=RealDictCursor)

            # Search by designation with pattern matching
            # Priority: exact match > starts with > contains
            normalized = material_name.strip().upper()

            # Try exact match first
            cursor.execute(
                """
                SELECT material_code, designation, composition
                FROM materials
                WHERE UPPER(designation) = %s
                LIMIT 1
                """,
                (normalized,)
            )
            row = cursor.fetchone()
            if row:
                cursor.close()
                return str(row["material_code"]), 1.0

            # Try starts-with match
            cursor.execute(
                """
                SELECT material_code, designation, composition
                FROM materials
                WHERE UPPER(designation) LIKE %s
                ORDER BY LENGTH(designation) ASC
                LIMIT 1
                """,
                (f"{normalized}%",)
            )
            row = cursor.fetchone()
            if row:
                cursor.close()
                return str(row["material_code"]), 0.9

            # Try contains match
            cursor.execute(
                """
                SELECT material_code, designation, composition
                FROM materials
                WHERE UPPER(designation) LIKE %s
                ORDER BY LENGTH(designation) ASC
                LIMIT 5
                """,
                (f"%{normalized}%",)
            )
            rows = cursor.fetchall()
            cursor.close()

            if rows:
                # Return best match (shortest designation containing the search term)
                return str(rows[0]["material_code"]), 0.7

            # If spec provided, try searching by spec
            if specification:
                cursor = conn.cursor(cursor_factory=RealDictCursor)
                cursor.execute(
                    """
                    SELECT material_code, designation, composition
                    FROM materials
                    WHERE UPPER(composition) LIKE %s
                    LIMIT 1
                    """,
                    (f"%{specification.upper()}%",)
                )
                row = cursor.fetchone()
                cursor.close()
                if row:
                    return str(row["material_code"]), 0.6

            return None, 0.0

        except Exception as e:
            logger.error(f"[MAPTIS] Lookup failed for '{material_name}': {e}")
            return None, 0.0

    async def lookup(
        self, material_name: str, specification: str | None
    ) -> tuple[str | None, float]:
        """
        Asynchronously look up material in MAPTIS.

        Args:
            material_name: Material designation
            specification: Material specification

        Returns:
            Tuple of (material_key, confidence_score)
        """
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            self._executor, self._lookup_sync, material_name, specification
        )

    def close(self) -> None:
        """Cleanup resources."""
        self._executor.shutdown(wait=True)
        if self._connection and not self._connection.closed:
            self._connection.close()
            self._connection = None


class MockMAPTISClient:
    """
    Mock MAPTIS client for testing.

    Returns known mappings for common materials.
    """

    # Known material mappings
    KNOWN_MATERIALS: dict[str, str] = {
        "316L": "SS316L",
        "CRES 316L": "SS316L",
        "316L CRES": "SS316L",
        "SS 316L": "SS316L",
        "304": "SS304",
        "CRES 304": "SS304",
        "304L": "SS304L",
        "INCONEL 718": "INC718",
        "INCONEL718": "INC718",
        "INC 718": "INC718",
        "HASTELLOY X": "HASTX",
        "HASTELLOY-X": "HASTX",
        "AL 6061": "AL6061",
        "6061 AL": "AL6061",
        "ALUMINUM 6061": "AL6061",
        "TI-6AL-4V": "TI64",
        "TI6AL4V": "TI64",
        "TITANIUM 6-4": "TI64",
        "MONEL 400": "MON400",
        "MONEL K-500": "MONK500",
    }

    async def lookup(
        self, material_name: str, specification: str | None
    ) -> tuple[str | None, float]:
        """
        Mock MAPTIS lookup.

        Args:
            material_name: Material designation
            specification: Material specification (unused in mock)

        Returns:
            Tuple of (material_key, confidence_score)
        """
        # Normalize material name for lookup
        normalized = material_name.upper().replace(" ", "").replace("-", "")

        # Check exact matches first
        if material_name.upper() in self.KNOWN_MATERIALS:
            return self.KNOWN_MATERIALS[material_name.upper()], 1.0

        # Check normalized matches
        for key, value in self.KNOWN_MATERIALS.items():
            key_normalized = key.replace(" ", "").replace("-", "")
            if key_normalized == normalized:
                return value, 0.95

        # Check partial matches
        for key, value in self.KNOWN_MATERIALS.items():
            if key.replace(" ", "") in normalized or normalized in key.replace(" ", ""):
                return value, 0.8

        return None, 0.0

    def close(self) -> None:
        """No-op for mock."""
        pass
