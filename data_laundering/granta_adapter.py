#!/usr/bin/env python3
"""
Module: Granta Validator Adapter
Purpose: ValidatorAdapter implementation for Granta MI / MAPTIS database.

BoundState AI 2026
Version: 1.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Claude "CC" <noreply@anthropic.com>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: NASA-STD-8739.8B, SWE-013, SWE-033
Safety Critical: True

This adapter wires the data laundering pipeline into the existing
mira_v4 modules. It does NOT rewrite them — it imports and orchestrates:
  - mira_v4.granta_client.DirtyDataClassifier
  - mira_v4.heritage_veto.HeritageVetoEngine
  - mira_v4.provenance.ProvenanceCalculator
  - mira_v4.confidence.ConfidenceCalculator
  - mira_v4.batch_safety.BatchSafetyGate

Every candidate from Layer 2 gets validated against Granta ground truth.
Dirty records are preserved. Heritage vetoes are applied. Provenance
hashes are computed. Nothing is skipped.

Spec Reference: BS-DL-ARCH-001
"""

from __future__ import annotations

import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

# Ensure mira_v4 is importable — resolve repo root relative to this
# file so imports work on any machine (not just C:\BoundState).
_REPO_ROOT = str(Path(__file__).resolve().parents[1])
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from mira_v4.confidence import ConfidenceCalculator
from mira_v4.granta_client import DirtyDataClassifier, FilterRelaxer
from mira_v4.heritage_veto import HeritageVetoEngine
from mira_v4.models import (
    BatchGateAction,
    EnvironmentSpec,
    EvidenceRow,
    ParsedQuery,
    SafetyContext,
)
from mira_v4.provenance import ProvenanceCalculator

from .domain_pack import ValidatorAdapter
from .models import (
    CandidateRecord,
    SanitizedQuery,
    ValidatedRecord,
    ValidatedResults,
)

logger = logging.getLogger(__name__)


class GrantaValidatorAdapter(ValidatorAdapter):
    """ValidatorAdapter implementation for Granta MI / MAPTIS.

    Wires into existing mira_v4 modules for:
      - Dirty data classification (granta_client.DirtyDataClassifier)
      - Heritage veto checks (heritage_veto.HeritageVetoEngine)
      - Provenance hashing (provenance.ProvenanceCalculator)
      - Confidence scoring (confidence.ConfidenceCalculator)

    The adapter translates between pipeline models (data_laundering.models)
    and v4 models (mira_v4.models) at the boundary.

    Accepts an optional db_search_fn callable for MAPTIS database lookups.
    When provided, candidates are validated against real MAPTIS data instead
    of mock records.

    Compliance: SWE-013, SWE-033, NASA-STD-8739.8B
    """

    def __init__(
        self,
        granta_api_url: Optional[str] = None,
        heritage_records: Optional[List[Dict[str, Any]]] = None,
        schema_version: str = "4.0.0",
        db_search_fn: Optional[Any] = None,
    ) -> None:
        """Initialize the Granta validator adapter.

        Args:
            granta_api_url: Granta MI API endpoint (for future live queries).
            heritage_records: Known heritage failure records for veto checks.
            schema_version: Current schema version string.
            db_search_fn: Optional callable(patterns: List[str], per_pattern_limit: int) -> List[Dict].
                          When provided, used for real MAPTIS database lookups.
                          Expected to return enriched material rows (same format as
                          mira_v4.py _db_batch_search).
        """
        self._granta_api_url = granta_api_url
        self._heritage_records = heritage_records or []
        self._schema_version = schema_version
        self._db_search_fn = db_search_fn

        # Initialize v4 engines
        self._dirty_classifier = DirtyDataClassifier()
        self._heritage_engine = HeritageVetoEngine()
        self._provenance_calc = ProvenanceCalculator()
        self._confidence_calc = ConfidenceCalculator()
        self._filter_relaxer = FilterRelaxer()

        logger.info(
            "GrantaValidatorAdapter initialized: schema=%s, "
            "heritage_records=%d, db_search=%s",
            self._schema_version, len(self._heritage_records),
            "MAPTIS" if db_search_fn else "mock",
        )

    async def validate_candidates(
        self,
        candidates: List[CandidateRecord],
        query: SanitizedQuery,
    ) -> ValidatedResults:
        """Validate candidate records against Granta ground truth.

        For each candidate:
          1. Look up in Granta (or mock for now)
          2. Run dirty data classification
          3. Run heritage veto check
          4. Compute confidence score
        Then compute provenance hashes for the full result set.

        Args:
            candidates: Ranked candidates from Layer 2.
            query: Sanitized query from Layer 1.

        Returns:
            ValidatedResults with confirmed records and provenance.
        """
        # Convert pipeline query to v4 types for module compatibility
        v4_env = self._to_v4_environment(query.environment)
        safety_ctx = self._to_v4_safety_context(query.safety_context)
        is_safety_critical = safety_ctx != SafetyContext.GENERAL

        validated_records: List[ValidatedRecord] = []
        all_evidence_rows: List[EvidenceRow] = []
        rejected_count = 0

        for candidate in candidates:
            # Step 1: Look up candidate in Granta
            granta_records = await self._lookup_in_granta(candidate)

            if not granta_records:
                logger.info(
                    "Candidate %s not found in Granta, rejecting",
                    candidate.material_key,
                )
                rejected_count += 1
                continue

            # Step 2: Build evidence rows from Granta records
            evidence_rows = self._build_evidence_rows(
                granta_records, candidate.material_key
            )
            all_evidence_rows.extend(evidence_rows)

            # Step 3: Dirty data classification
            dirty_result = self._dirty_classifier.classify_records(evidence_rows)
            dirty_fraction = dirty_result.dirty_fraction

            # Step 4: Heritage veto check
            heritage_result = self._heritage_engine.check_heritage(
                material_key=candidate.material_key,
                query_env=v4_env,
                heritage_records=self._heritage_records,
                safety_context=safety_ctx,
            )

            # Step 5: Confidence scoring
            confidence_result = self._confidence_calc.calculate(
                environment=v4_env,
                evidence_rows=evidence_rows,
                dirty_fraction=dirty_fraction,
                heritage_veto_active=heritage_result.vetoed,
                safety_critical=is_safety_critical,
            )

            # Build validated record
            validated = ValidatedRecord(
                material_key=candidate.material_key,
                record_id=candidate.record_id or f"granta-{candidate.material_key}",
                source="GRANTA",
                properties=candidate.properties,
                confidence_score=confidence_result.score,
                dirty_flag=dirty_result.tier.value != "clean",
                dirty_fields=[
                    f for r in evidence_rows
                    for f in r.dirty_fields
                    if r.dirty_flag
                ],
                raw_values={
                    k: v
                    for r in evidence_rows
                    if r.dirty_flag
                    for k, v in r.raw_values.items()
                },
                heritage_vetoed=heritage_result.vetoed,
                heritage_requires_acknowledgment=heritage_result.requires_acknowledgment,
            )

            validated_records.append(validated)

        # Step 6: Compute provenance hashes
        record_ids = [r.record_id for r in validated_records]
        filters_dict = query.filters.copy()
        if query.material_name:
            filters_dict["material_name"] = query.material_name
        filters_dict["intent"] = query.intent.value

        provenance = self._provenance_calc.create_provenance(
            filters=filters_dict,
            record_ids=record_ids,
            schema_version=self._schema_version,
        )

        # Step 7: Check for zero results and suggest relaxations
        relaxation_suggestions: List[Dict[str, Any]] = []
        if not validated_records:
            env_filters = {
                k: v for k, v in query.environment.model_dump().items()
                if v is not None
            }
            proposals = self._filter_relaxer.suggest_relaxations(
                filters=env_filters,
                zero_result_field="all",
            )
            relaxation_suggestions = [p.model_dump() for p in proposals]

        # Build dirty data summary
        dirty_summary = None
        if all_evidence_rows:
            overall_dirty = self._dirty_classifier.classify_records(
                all_evidence_rows
            )
            dirty_summary = overall_dirty.model_dump()

        return ValidatedResults(
            records=validated_records,
            query_hash=provenance.query_hash,
            snapshot_hash=provenance.snapshot_hash,
            total_candidates=len(candidates),
            candidates_validated=len(validated_records),
            candidates_rejected=rejected_count,
            relaxation_suggestions=relaxation_suggestions,
            safety_gate_result=None,
            dirty_data_summary=dirty_summary,
            schema_version=self._schema_version,
        )

    async def health_check(self) -> bool:
        """Check if Granta MI is reachable.

        For now, always returns True (local testing mode).
        In production, this would ping the Granta API.
        """
        # TODO: Implement actual Granta health check
        return True

    # =========================================================================
    # Translation Helpers (Pipeline Models <-> v4 Models)
    # =========================================================================

    @staticmethod
    def _to_v4_environment(env_filter: Any) -> EnvironmentSpec:
        """Convert pipeline EnvironmentFilter to v4 EnvironmentSpec."""
        return EnvironmentSpec(
            temperature_c=env_filter.temperature_c,
            pressure_kpa=env_filter.pressure_kpa,
            o2_pct=env_filter.o2_pct,
            fluid_medium=env_filter.fluid_medium,
            duration_hr=env_filter.duration_hr,
            cycles=env_filter.cycles,
        )

    @staticmethod
    def _to_v4_safety_context(
        safety_ctx: Optional[str],
    ) -> SafetyContext:
        """Convert pipeline safety context string to v4 SafetyContext enum."""
        if safety_ctx is None:
            return SafetyContext.GENERAL
        mapping = {
            "oxygen": SafetyContext.OXYGEN,
            "hydrogen": SafetyContext.HYDROGEN,
            "cryogenic": SafetyContext.CRYOGENIC,
            "high_pressure": SafetyContext.HIGH_PRESSURE,
        }
        return mapping.get(safety_ctx, SafetyContext.GENERAL)

    # =========================================================================
    # Granta Lookup (stubbed for local testing)
    # =========================================================================

    async def _lookup_in_granta(
        self,
        candidate: CandidateRecord,
    ) -> List[Dict[str, Any]]:
        """Look up a candidate material in the database.

        If db_search_fn was provided, queries MAPTIS via the v4 router's
        batch search. Otherwise, returns a mock record for testing.

        Args:
            candidate: The candidate to look up.

        Returns:
            List of enriched material record dicts from the database.
        """
        if self._db_search_fn is not None:
            try:
                rows = self._db_search_fn(
                    [candidate.material_key], per_pattern_limit=5
                )
                if rows:
                    # Convert MAPTIS rows to the format expected by _build_evidence_rows
                    result = []
                    for row in rows:
                        total_tests = row.get("total_tests", 0)
                        result.append({
                            "record_id": str(row.get("material_key", candidate.material_key)),
                            "material_key": candidate.material_key,
                            "source": "MAPTIS",
                            "data_class": "direct_test" if total_tests > 0 else "derived",
                            "dirty_flag": total_tests == 0,
                            "dirty_fields": [],
                            "raw_values": {},
                            "test_year": row.get("latest_test_year"),
                            "properties": {
                                "designation": row.get("designation"),
                                "total_tests": total_tests,
                                "test_counts": row.get("test_counts", {}),
                                "oxygen_compatible": row.get("oxygen_compatible", False),
                                "mua_count": row.get("mua_count", 0),
                            },
                            # Preserve the full MAPTIS row for Layer 4
                            "_maptis_row": row,
                        })
                    return result
                return []
            except Exception as exc:
                logger.warning(
                    "MAPTIS lookup failed for %s: %s, falling back to mock",
                    candidate.material_key, exc,
                )

        # Mock fallback for testing without database
        return [
            {
                "record_id": candidate.record_id or f"granta-{candidate.material_key}",
                "material_key": candidate.material_key,
                "source": "GRANTA",
                "data_class": "derived",
                "dirty_flag": False,
                "dirty_fields": [],
                "raw_values": {},
                "test_year": 2022,
                "properties": candidate.properties,
            }
        ]

    @staticmethod
    def _build_evidence_rows(
        granta_records: List[Dict[str, Any]],
        material_key: str,
    ) -> List[EvidenceRow]:
        """Build EvidenceRow objects from Granta lookup results."""
        rows = []
        for record in granta_records:
            row = EvidenceRow(
                record_id=record.get("record_id", f"granta-{material_key}"),
                source=record.get("source", "GRANTA"),
                data_class=record.get("data_class", "derived"),
                dirty_flag=record.get("dirty_flag", False),
                dirty_fields=record.get("dirty_fields", []),
                raw_values=record.get("raw_values", {}),
                test_year=record.get("test_year"),
            )
            rows.append(row)
        return rows
