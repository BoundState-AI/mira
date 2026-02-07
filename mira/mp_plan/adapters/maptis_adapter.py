#!/usr/bin/env python3
"""
Module: MAPTIS Resolution Adapter
Purpose: Wraps MIULEnrichmentService for material resolution

BoundState AI 2026
Version: 2.0.0
Classification: BoundState Proprietary

This adapter transforms between V2 session models and the
existing MIUL enrichment service interface.

Compliance: NASA-STD-8739.8B, SWE-013, SWE-033
Safety Critical: False
"""

from __future__ import annotations

import logging
import os
from datetime import datetime
from typing import Optional

from mira.compliance.models.enums import SourceType
from mira.compliance.models.evidence import EvidenceRef

from ..models import MaterialEntry, MaterialResolutionResult

LOGGER = logging.getLogger(__name__)

__version__ = "2.0.0"
__safety_critical__ = False


class MaptisResolutionAdapter:
    """
    Adapts MIULEnrichmentService to V2 session model.

    This adapter:
    - Accepts MaterialEntry objects from the V2 session
    - Calls the existing enrichment service for MAPTIS lookups
    - Returns MaterialResolutionResult objects for the session
    """

    def __init__(
        self,
        host: Optional[str] = None,
        port: Optional[int] = None,
        database: Optional[str] = None,
        user: Optional[str] = None,
        password: Optional[str] = None,
    ):
        """
        Initialize the adapter.

        Credentials are loaded from centralized db_config module, which reads
        from environment variables:
        - POSTGRES_HOST (default: localhost)
        - POSTGRES_PORT (default: 5432)
        - POSTGRES_DB (default: mira)
        - POSTGRES_USER (REQUIRED in production)
        - POSTGRES_PASSWORD (REQUIRED in production)

        Args:
            host: PostgreSQL host override
            port: PostgreSQL port override
            database: Database name override
            user: Database user override
            password: Database password override
        """
        # Use centralized config from db_config module
        try:
            from mira.core.db_config import get_db_connection_params
            self._conn_params = get_db_connection_params(
                host=host,
                port=port,
                database=database,
                user=user,
                password=password,
            )
        except ImportError:
            # Fallback if db_config not available
            self._conn_params = {
                "host": host or os.environ.get("POSTGRES_HOST", "localhost"),
                "port": port or int(os.environ.get("POSTGRES_PORT", "5432")),
                "database": database or os.environ.get("POSTGRES_DB", "mira"),
                "user": user or os.environ.get("POSTGRES_USER", "postgres"),
                "password": password or os.environ.get("POSTGRES_PASSWORD", "postgres"),
            }
            LOGGER.warning("[MaptisAdapter] Using fallback config - set env vars for production")
        self._enrichment_service = None

    def _get_enrichment_service(self):
        """Lazy-load the enrichment service."""
        if self._enrichment_service is None:
            from mira.miul.enrichment import MIULEnrichmentService

            self._enrichment_service = MIULEnrichmentService(**self._conn_params)
        return self._enrichment_service

    def resolve_material(
        self,
        material: MaterialEntry,
    ) -> Optional[MaterialResolutionResult]:
        """
        Resolve a single material to MAPTIS data.

        Args:
            material: MaterialEntry from V2 session.

        Returns:
            MaterialResolutionResult if resolved, None otherwise.
        """
        if not material.maptis_code:
            LOGGER.warning(f"Material {material.id} has no MAPTIS code")
            return None

        service = self._get_enrichment_service()

        try:
            # Query MAPTIS for ratings
            ratings = service.get_ratings_for_material_code(material.maptis_code)

            if not ratings:
                LOGGER.warning(
                    f"No MAPTIS data found for code {material.maptis_code}"
                )
                return None

            # Extract ratings with conservative aggregation
            flam_rating = ratings.get("FLAM", "U")
            tvs_rating = ratings.get("TVS", "U")
            tox_rating = ratings.get("TOX", "U")

            # Get test conditions if available
            test_o2_pct = ratings.get("test_o2_pct", 21.0)
            test_pressure = ratings.get("test_pressure_psia")
            test_temp = ratings.get("test_temp_c")

            return MaterialResolutionResult(
                material_id=material.id,
                maptis_code=material.maptis_code,
                flam_rating=flam_rating,
                tvs_rating=tvs_rating,
                tox_rating=tox_rating,
                test_o2_pct=test_o2_pct,
                test_pressure_psia=test_pressure,
                test_temp_c=test_temp,
                source="maptis_adapter",
            )

        except Exception as e:
            LOGGER.error(f"Error resolving material {material.id}: {e}")
            return None

    def resolve_materials(
        self,
        materials: list[MaterialEntry],
    ) -> list[MaterialResolutionResult]:
        """
        Resolve multiple materials to MAPTIS data.

        Args:
            materials: List of MaterialEntry objects.

        Returns:
            List of MaterialResolutionResult for resolved materials.
        """
        results = []
        for material in materials:
            result = self.resolve_material(material)
            if result:
                results.append(result)
        return results

    def create_evidence_ref(
        self,
        maptis_code: str,
        record_id: Optional[str] = None,
    ) -> EvidenceRef:
        """
        Create an evidence reference for MAPTIS data.

        Args:
            maptis_code: MAPTIS material code.
            record_id: Optional specific record ID.

        Returns:
            EvidenceRef for the MAPTIS data.
        """
        return EvidenceRef(
            source_type=SourceType.MAPTIS,
            source_id=f"MAPTIS:{maptis_code}",
            maptis_record_id=record_id,
            confidence=0.95,
            confidence_basis="Direct MAPTIS database lookup",
            retrieved_at=datetime.now(),
            retrieval_method="maptis_adapter",
        )

    def close(self) -> None:
        """Close database connections."""
        if self._enrichment_service:
            self._enrichment_service.close()
