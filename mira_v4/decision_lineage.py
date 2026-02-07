#!/usr/bin/env python3
"""
Module: Decision Lineage Builder
Purpose: Assembles the immutable Decision Lineage artifact.

BoundState AI 2026
Version: 4.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: SWE-013, SWE-033, NASA-STD-8739.8B
Safety Critical: True

Orchestrates all MIRA v4 modules to produce a single, immutable
DecisionLineage artifact per query. This artifact is the audit trail
for IV&V review.

Assembly steps:
    1. Compute provenance hashes (deterministic + snapshot)
    2. Classify dirty data tier
    3. Run batch safety gate (if batch mode)
    4. Run intent guardrail (Sonnet vs heuristic)
    5. Check heritage veto (envelope matching)
    6. Calculate confidence score (all penalties)
    7. Assemble immutable DecisionLineage

Spec Reference: BS-MIRA-V4-BUILDSPEC-001-REV1
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from .batch_safety import BatchSafetyGate
from .confidence import ConfidenceCalculator
from .models import (
    BatchGateAction,
    DecisionLineage,
    DirtyDataTier,
    EvidenceRow,
    HeritageOverride,
    HeritageVetoResult,
    IntentDisagreement,
    ParsedQuery,
    SafetyContext,
)
from .provenance import ProvenanceCalculator

logger = logging.getLogger(__name__)


class DecisionLineageBuilder:
    """Assembles the immutable DecisionLineage artifact.

    This builder orchestrates calls to each v4 module, collects
    results, and produces the final Decision Lineage record.

    WARNING: DecisionLineage is IMMUTABLE once created (frozen=True).
    It must be stored as-is for NASA-STD-8739.8B compliance.

    Compliance: SWE-013, SWE-033, NASA-STD-8739.8B
    """

    def __init__(
        self,
        provenance_calc: Optional[ProvenanceCalculator] = None,
        confidence_calc: Optional[ConfidenceCalculator] = None,
        batch_gate: Optional[BatchSafetyGate] = None,
    ):
        """Initialize with v4 module instances.

        Args:
            provenance_calc: Provenance hash calculator. Created if None.
            confidence_calc: Confidence score calculator. Created if None.
            batch_gate: Batch safety gate. Created if None.
        """
        self._provenance = provenance_calc or ProvenanceCalculator()
        self._confidence = confidence_calc or ConfidenceCalculator()
        self._batch_gate = batch_gate or BatchSafetyGate()

    def build(
        self,
        parsed_query: ParsedQuery,
        evidence_rows: List[EvidenceRow],
        schema_version: str,
        dirty_fraction: float = 0.0,
        dirty_data_tier: Optional[DirtyDataTier] = None,
        heritage_veto_result: Optional[HeritageVetoResult] = None,
        heritage_overrides: Optional[List[HeritageOverride]] = None,
        intent_disagreement: Optional[IntentDisagreement] = None,
        record_ids: Optional[List[str]] = None,
    ) -> DecisionLineage:
        """Full decision lineage assembly.

        This method runs the complete v4 pipeline and produces
        the immutable DecisionLineage artifact.

        Args:
            parsed_query: Parsed and validated query.
            evidence_rows: Evidence records for confidence calculation.
            schema_version: Schema Dictionary version string.
            dirty_fraction: Proportion of dirty records (0.0-1.0).
            dirty_data_tier: Pre-computed dirty data tier (optional).
            heritage_veto_result: Pre-computed heritage veto (optional).
            heritage_overrides: Engineer override records (optional).
            intent_disagreement: Pre-computed intent disagreement (optional).
            record_ids: Record IDs for provenance. Defaults to evidence record_ids.

        Returns:
            Immutable DecisionLineage artifact.
        """
        # --- Step 1: Compute provenance hashes ---
        if record_ids is None:
            record_ids = [e.record_id for e in evidence_rows]

        provenance = self._provenance.create_provenance(
            filters=parsed_query.filters,
            record_ids=record_ids,
            schema_version=schema_version,
        )

        logger.debug(
            f"Lineage step 1: provenance computed. "
            f"query_hash={provenance.query_hash[:16]}..."
        )

        # --- Step 2: Batch safety gate (if batch mode) ---
        batch_gate_result = None
        if parsed_query.batch_mode:
            batch_gate_result = self._batch_gate.check(parsed_query)
            logger.debug(
                f"Lineage step 2: batch gate = {batch_gate_result.action.value}"
            )

            # If batch gate REFUSES, we still compute confidence for the lineage
            # record, but the query is blocked.
            if batch_gate_result.action == BatchGateAction.REFUSE:
                logger.warning(
                    f"Batch safety gate REFUSE: {batch_gate_result.reason}"
                )

        # --- Step 3: Determine safety-critical status ---
        safety_context = parsed_query.safety_context
        if safety_context == SafetyContext.GENERAL and batch_gate_result:
            # Batch gate may have detected a safety context
            safety_context = batch_gate_result.safety_context

        is_safety_critical = safety_context != SafetyContext.GENERAL

        # --- Step 4: Heritage veto penalty ---
        heritage_active = (
            heritage_veto_result is not None and heritage_veto_result.vetoed
        )

        # --- Step 5: Intent disagreement penalty ---
        intent_penalty = 0.0
        if intent_disagreement is not None:
            intent_penalty = intent_disagreement.penalty_applied

        # --- Step 6: Calculate confidence ---
        confidence = self._confidence.calculate(
            environment=parsed_query.environment,
            evidence_rows=evidence_rows,
            dirty_fraction=dirty_fraction,
            heritage_veto_active=heritage_active,
            safety_critical=is_safety_critical,
        )

        # Apply intent disagreement penalty if present
        if intent_penalty > 0:
            adjusted_score = max(0.0, confidence.score - intent_penalty)
            # Recompute gate action with adjusted score
            adjusted_gate = self._confidence._determine_gate(
                adjusted_score, is_safety_critical
            )
            # Update penalties dict
            updated_penalties = dict(confidence.penalties)
            updated_penalties["intent_disagreement"] = intent_penalty

            confidence = confidence.model_copy(update={
                "score": round(adjusted_score, 6),
                "penalties": updated_penalties,
                "gate_action": adjusted_gate,
                "explanation": (
                    confidence.explanation +
                    f" Intent disagreement penalty: -{intent_penalty:.2f}."
                ),
            })

        logger.debug(
            f"Lineage step 6: confidence = {confidence.score:.3f} "
            f"({confidence.gate_action.value})"
        )

        # --- Step 7: Assemble immutable lineage ---
        lineage = DecisionLineage(
            query_hash=provenance.query_hash,
            snapshot_hash=provenance.snapshot_hash,
            parsed_query=parsed_query,
            confidence=confidence,
            batch_gate=batch_gate_result,
            dirty_data_tier=dirty_data_tier,
            heritage_veto=heritage_veto_result,
            intent_disagreement=intent_disagreement,
            heritage_overrides=heritage_overrides or [],
            schema_version=schema_version,
        )

        logger.info(
            f"DecisionLineage assembled: lineage_id={lineage.lineage_id}, "
            f"query_hash={lineage.query_hash[:16]}..., "
            f"confidence={confidence.score:.3f} ({confidence.gate_action.value})"
        )

        return lineage
