#!/usr/bin/env python3
"""
Module: Two-Hash Provenance Scheme
Purpose: Deterministic and audit-trail provenance hashing for MIRA v4.

BoundState AI 2026
Version: 4.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: SWE-013, NASA-STD-8739.8B
Safety Critical: True

Implements BuildSpec REV1 Item 4: Two-Hash Provenance Scheme.

query_hash:    SHA-256 of canonicalized filters. Deterministic --
               same filters always produce same hash regardless of
               field order or whitespace. Used for cache matching
               and IV&V replay testing.

snapshot_hash: SHA-256 of query_hash + timestamp + sorted record IDs
               + schema version. NOT deterministic (includes timestamp).
               Used for provenance audit and tamper detection.

Both hashes appear in the Decision Lineage artifact.

Spec Reference: BS-MIRA-V4-BUILDSPEC-001-REV1, Section 5
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List

from .models import ProvenanceHashes

logger = logging.getLogger(__name__)


class ProvenanceCalculator:
    """Computes deterministic provenance hashes per BuildSpec Section 5.

    Canonicalization rules:
    - Sort all dict keys recursively
    - Normalize floats to 6 decimal places
    - Sort all lists by string representation
    - Strip None values (exclude_none)
    - Stable JSON: sorted keys, no whitespace, ASCII-safe
    - Timestamp is EXCLUDED from query_hash (determinism)
    - Timestamp is INCLUDED in snapshot_hash (audit)
    """

    @staticmethod
    def _normalize_value(value: Any) -> Any:
        """Normalize a value for canonical representation.

        - Floats: round to 6 decimal places
        - Strings: strip whitespace, uppercase
        - Lists: sort by str representation, normalize each element
        - Dicts: recursively normalize
        - None: excluded at the caller level
        """
        if value is None:
            return None
        if isinstance(value, float):
            return round(value, 6)
        if isinstance(value, str):
            return value.strip()
        if isinstance(value, list):
            normalized = [ProvenanceCalculator._normalize_value(v) for v in value]
            return sorted(normalized, key=str)
        if isinstance(value, dict):
            return {
                k: ProvenanceCalculator._normalize_value(v)
                for k, v in sorted(value.items())
                if v is not None
            }
        return value

    @staticmethod
    def canonicalize_filters(filters: Dict[str, Any]) -> str:
        """Produce stable JSON encoding of filters.

        Args:
            filters: Query filter dictionary.

        Returns:
            Canonical JSON string. Same filters in any order produce
            identical output.

        Implementation per BuildSpec Section 5.3:
            - Exclude None values
            - Sort all keys recursively
            - Normalize floats to 6 decimal places
            - Sort lists by string representation
            - Stable JSON: sorted keys, no whitespace, ASCII-safe
        """
        # Deep-normalize the filter dictionary
        normalized = {}
        for key, value in sorted(filters.items()):
            if value is not None:
                normalized[key] = ProvenanceCalculator._normalize_value(value)

        # Stable JSON encoding
        canonical = json.dumps(
            normalized,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        )

        return canonical

    @staticmethod
    def compute_query_hash(canonical_filters: str) -> str:
        """SHA-256 of canonicalized filters string.

        Args:
            canonical_filters: Output of canonicalize_filters().

        Returns:
            64-character hex digest. Deterministic -- same filters
            always produce same hash.
        """
        return hashlib.sha256(
            canonical_filters.encode("utf-8")
        ).hexdigest()

    @staticmethod
    def compute_snapshot_hash(
        query_hash: str,
        timestamp: str,
        record_ids: List[str],
        schema_version: str,
    ) -> str:
        """SHA-256 of query_hash + timestamp + sorted record IDs + schema version.

        NOT deterministic (includes timestamp). Used for provenance
        audit and tamper detection.

        Args:
            query_hash: The deterministic query hash.
            timestamp: ISO 8601 retrieval timestamp.
            record_ids: List of record IDs in the snapshot.
            schema_version: Schema Dictionary version string.

        Returns:
            64-character hex digest.

        Implementation per BuildSpec Section 5.3:
            payload = f'{query_hash}|{timestamp}|{"|".join(sorted(record_ids))}|{schema_version}'
        """
        sorted_ids = sorted(record_ids)
        payload = f'{query_hash}|{timestamp}|{"|".join(sorted_ids)}|{schema_version}'
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def create_provenance(
        self,
        filters: Dict[str, Any],
        record_ids: List[str],
        schema_version: str,
        timestamp: str | None = None,
    ) -> ProvenanceHashes:
        """Full provenance calculation returning ProvenanceHashes.

        Args:
            filters: Query filter dictionary.
            record_ids: List of record IDs in the result set.
            schema_version: Schema Dictionary version string.
            timestamp: Optional ISO 8601 timestamp. If None, uses current UTC time.

        Returns:
            ProvenanceHashes with both hashes and metadata.
        """
        if timestamp is None:
            timestamp = datetime.now(timezone.utc).isoformat()

        canonical = self.canonicalize_filters(filters)
        query_hash = self.compute_query_hash(canonical)
        snapshot_hash = self.compute_snapshot_hash(
            query_hash, timestamp, record_ids, schema_version
        )

        logger.debug(
            f"Provenance computed: query_hash={query_hash[:16]}... "
            f"snapshot_hash={snapshot_hash[:16]}..."
        )

        return ProvenanceHashes(
            query_hash=query_hash,
            snapshot_hash=snapshot_hash,
            canonical_filters=canonical,
            timestamp=timestamp,
            record_ids=sorted(record_ids),
            schema_version=schema_version,
        )
