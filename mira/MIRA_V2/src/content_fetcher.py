#!/usr/bin/env python3
"""
Module: Content Fetcher
Purpose: Content Fetcher for Semantic Search Results

BoundState AI 2025
Version: 1.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Fran OpenAI 5 <noreply@openai.com>
Co-Authored-By: Grok 4.0 <noreply@x.ai>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: SWE-013, NASA-STD-8739.8B
Safety Critical: False
"""

from typing import Optional, Dict, Any
import psycopg2
from psycopg2.extras import RealDictCursor
import logging
import os

logger = logging.getLogger(__name__)


class ContentFetcher:
    """
    Fetches full content from database for semantic search results.

    Given a result from FAISS (with doc_id), fetch the actual content
    from the appropriate database table.
    """

    def __init__(self, db_url: Optional[str] = None):
        """
        Initialize content fetcher.

        Args:
            db_url: Database connection URL. If None, uses MIRA_DB_URL env var.
        """
        self.db_url = db_url or os.environ.get('MIRA_DB_URL')
        if not self.db_url:
            # Fallback to individual params
            self.db_url = self._build_db_url()

        self.conn = None
        self._connect()

    def _build_db_url(self) -> str:
        """Build database URL from environment or defaults."""
        host = os.getenv('POSTGRES_HOST', 'localhost')
        port = os.getenv('POSTGRES_PORT', '5432')
        db = os.getenv('POSTGRES_DB', 'mira')
        user = os.getenv('POSTGRES_USER', 'postgres')
        password = os.getenv('POSTGRES_PASSWORD', 'postgres')

        return f"postgresql://{user}:{password}@{host}:{port}/{db}"

    def _connect(self):
        """Establish database connection."""
        try:
            self.conn = psycopg2.connect(self.db_url)
            logger.info("ContentFetcher connected to database")
        except Exception as e:
            logger.error(f"Failed to connect to database: {e}")
            raise

    def fetch_bok_content(self, section_id: str) -> Optional[Dict[str, Any]]:
        """
        Fetch BOK standard section content.

        Args:
            section_id: UUID of the section

        Returns:
            Dict with section content and metadata, or None if not found
        """
        if not self.conn:
            self._connect()

        cur = self.conn.cursor(cursor_factory=RealDictCursor)

        try:
            cur.execute("""
                SELECT
                    section_id,
                    spec_id,
                    section_number,
                    heading,
                    content,
                    requirement_type,
                    doc_type
                FROM bok.sections
                WHERE section_id = %s
            """, (section_id,))

            result = cur.fetchone()
            if result:
                return dict(result)
            return None

        except Exception as e:
            logger.error(f"Error fetching BOK content for {section_id}: {e}")
            return None
        finally:
            cur.close()

    def fetch_mua_content(self, mua_id: str) -> Optional[Dict[str, Any]]:
        """
        Fetch MUA precedent content.

        Args:
            mua_id: ID of the MUA (can be UUID from mua_precedents or integer from mua_normalized)

        Returns:
            Dict with MUA content and metadata, or None if not found
        """
        if not self.conn:
            self._connect()

        cur = self.conn.cursor(cursor_factory=RealDictCursor)

        try:
            # Check if mua_id is an integer (from old mua_normalized table)
            # or a UUID (from new mua_precedents table)
            try:
                int_id = int(mua_id)
                # It's an integer - query mua_normalized table
                cur.execute("""
                    SELECT
                        mua_id,
                        filename as source_pdf,
                        material_designation as material_name,
                        specification as material_specification,
                        determination,
                        rationale,
                        environment,
                        hazards,
                        data_quality
                    FROM bok.mua_normalized
                    WHERE mua_id = %s
                """, (int_id,))
            except ValueError:
                # It's a UUID - query mua_precedents table
                cur.execute("""
                    SELECT
                        mua_id,
                        mua_number,
                        material_name,
                        material_specification,
                        configuration,
                        determination,
                        rationale,
                        rationale_summary,
                        mitigations,
                        pressure_psi_max,
                        temp_c_min,
                        temp_c_max,
                        o2_concentration_pct,
                        clause_numbers,
                        precedent_mua_ids,
                        evidence_ids,
                        source_pdf,
                        parsed_date,
                        parser_confidence,
                        is_reviewed
                    FROM bok.mua_precedents
                    WHERE mua_id = %s
                """, (mua_id,))

            result = cur.fetchone()
            if result:
                return dict(result)
            return None

        except Exception as e:
            logger.error(f"Error fetching MUA content for {mua_id}: {e}")
            return None
        finally:
            cur.close()

    def fetch_maptis_content(self, row_uid: str) -> Optional[Dict[str, Any]]:
        """
        Fetch MAPTIS material/test data content.

        Args:
            row_uid: UUID of the MAPTIS row

        Returns:
            Dict with MAPTIS content and metadata, or None if not found
        """
        if not self.conn:
            self._connect()

        cur = self.conn.cursor(cursor_factory=RealDictCursor)

        try:
            cur.execute("""
                SELECT
                    row_uid,
                    contract_id,
                    normalized_payload
                FROM silver_report_rows
                WHERE row_uid = %s
            """, (row_uid,))

            result = cur.fetchone()
            if result:
                # Extract key fields from JSONB payload
                payload = result['normalized_payload']

                return {
                    'row_uid': result['row_uid'],
                    'contract_id': result['contract_id'],
                    'material_key': payload.get('materialkey'),
                    'test_type': payload.get('testtypecaption'),
                    'specification': payload.get('arc_specification') or payload.get('matl_testspec'),
                    'material_designation': payload.get('matl_designation'),
                    'gas': payload.get('arc_gasname'),
                    'oxygen_pct': payload.get('arc_oxygenpercent') or payload.get('arc_moc_o2_pct'),
                    'pressure': payload.get('arc_pressure'),
                    'temperature': payload.get('temperaturemaximum'),
                    'report_number': payload.get('testreportnumber'),
                    'full_payload': payload
                }
            return None

        except Exception as e:
            logger.error(f"Error fetching MAPTIS content for {row_uid}: {e}")
            return None
        finally:
            cur.close()

    def fetch_content(self, source_index: str, doc_id: str) -> Optional[Dict[str, Any]]:
        """
        Fetch content based on source index and document ID.

        Args:
            source_index: One of 'bok', 'mua', 'maptis'
            doc_id: Document identifier (UUID or other ID)

        Returns:
            Dict with content and metadata, or None if not found
        """
        if source_index == "bok":
            return self.fetch_bok_content(doc_id)
        elif source_index == "mua":
            return self.fetch_mua_content(doc_id)
        elif source_index == "maptis":
            return self.fetch_maptis_content(doc_id)
        else:
            logger.warning(f"Unknown source index: {source_index}")
            return None

    def close(self):
        """Close database connection."""
        if self.conn:
            self.conn.close()
            logger.info("ContentFetcher closed database connection")

    def __enter__(self):
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.close()
