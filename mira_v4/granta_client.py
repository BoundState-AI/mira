#!/usr/bin/env python3
"""
Module: Dirty Data Threshold and Filter Relaxation
Purpose: Classifies dirty data tiers and suggests filter relaxations for MIRA v4.

BoundState AI 2026
Version: 4.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: SWE-013, SWE-032, NASA-STD-8739.8B
Safety Critical: True

Implements BuildSpec REV1 Item 2: Dirty Data Threshold and Escalation (P0).

DirtyDataClassifier:
    Classifies record sets by dirty data fraction into CLEAN / DEGRADED / REFUSE
    tiers per BuildSpec Section 3.2. Dirty records are NEVER removed -- they
    remain visible with dirty_flag=True and original values preserved in
    raw_values for audit trail.

FilterRelaxer:
    When Granta returns zero clean results, suggests minimal filter relaxations
    returned to the user as OPTIONS (never applied automatically) per
    BuildSpec Section 3.4.

Spec Reference: BS-MIRA-V4-BUILDSPEC-001-REV1, Sections 3.2, 3.4
"""

from __future__ import annotations

import copy
import logging
from typing import Any, Dict, List, Optional, Tuple

from .models import (
    DirtyDataResult,
    DirtyDataTier,
    EvidenceRow,
    RelaxationProposal,
)

logger = logging.getLogger(__name__)


# =============================================================================
# DirtyDataClassifier
# =============================================================================


class DirtyDataClassifier:
    """Classifies record sets by dirty data fraction per BuildSpec Section 3.2.

    Thresholds:
        CLEAN:    0-10%   dirty records -> proceed normally
        DEGRADED: 11-30%  dirty records -> proceed with warning
        REFUSE:   >30%    dirty records -> refuse for affected property

    WARNING: Dirty records MUST remain visible. They are never removed from
    result sets. The annotate_dirty_records method preserves all records
    and stores original values in raw_values for the audit trail.

    Compliance: SWE-032, NASA-STD-8739.8B
    """

    CLEAN_THRESHOLD: float = 0.10
    """Maximum dirty fraction for CLEAN tier (0-10%)."""

    DEGRADED_THRESHOLD: float = 0.30
    """Maximum dirty fraction for DEGRADED tier (11-30%)."""

    def classify(self, dirty_fraction: float) -> DirtyDataTier:
        """Classify a dirty data fraction into a tier.

        Args:
            dirty_fraction: Fraction of dirty records (0.0 to 1.0).

        Returns:
            DirtyDataTier: CLEAN, DEGRADED, or REFUSE.

        Raises:
            ValueError: If dirty_fraction is outside [0.0, 1.0].
        """
        if dirty_fraction < 0.0 or dirty_fraction > 1.0:
            raise ValueError(
                f"dirty_fraction must be in [0.0, 1.0], got {dirty_fraction}"
            )

        if dirty_fraction <= self.CLEAN_THRESHOLD:
            logger.debug(
                f"Dirty fraction {dirty_fraction:.2%} -> CLEAN "
                f"(threshold {self.CLEAN_THRESHOLD:.0%})"
            )
            return DirtyDataTier.CLEAN

        if dirty_fraction <= self.DEGRADED_THRESHOLD:
            logger.info(
                f"Dirty fraction {dirty_fraction:.2%} -> DEGRADED "
                f"(threshold {self.DEGRADED_THRESHOLD:.0%})"
            )
            return DirtyDataTier.DEGRADED

        logger.warning(
            f"Dirty fraction {dirty_fraction:.2%} -> REFUSE "
            f"(exceeds {self.DEGRADED_THRESHOLD:.0%})"
        )
        return DirtyDataTier.REFUSE

    def compute_dirty_fraction(self, records: List[EvidenceRow]) -> float:
        """Compute the fraction of dirty records in a record set.

        Args:
            records: List of evidence rows to analyze.

        Returns:
            Fraction of records with dirty_flag=True.
            Returns 0.0 if the list is empty.
        """
        if not records:
            logger.debug("No records provided, returning dirty_fraction=0.0")
            return 0.0

        dirty_count = sum(1 for r in records if r.dirty_flag)
        fraction = dirty_count / len(records)

        logger.debug(
            f"Dirty fraction: {dirty_count}/{len(records)} = {fraction:.4f}"
        )
        return fraction

    def classify_records(
        self,
        records: List[EvidenceRow],
        property_name: Optional[str] = None,
    ) -> DirtyDataResult:
        """Classify a record set and generate user-facing messages.

        Combines compute_dirty_fraction and classify into a single
        DirtyDataResult with appropriate user messages for DEGRADED
        and REFUSE tiers.

        Args:
            records: List of evidence rows to classify.
            property_name: Optional property name for REFUSE message.
                Defaults to "this property" if not provided.

        Returns:
            DirtyDataResult with tier, fraction, counts, and user_message.
        """
        total = len(records)
        dirty_count = sum(1 for r in records if r.dirty_flag)
        fraction = self.compute_dirty_fraction(records)
        tier = self.classify(fraction)

        # Generate user-facing messages for non-CLEAN tiers
        user_message: Optional[str] = None

        if tier == DirtyDataTier.DEGRADED:
            user_message = (
                f"{dirty_count} of {total} matched records contain "
                f"non-typed data and were excluded from typed comparisons. "
                f"Results may be incomplete."
            )
            logger.info(f"DEGRADED tier message: {user_message}")

        elif tier == DirtyDataTier.REFUSE:
            prop = property_name if property_name else "this property"
            pct = dirty_count / total * 100 if total > 0 else 0.0
            user_message = (
                f"Insufficient clean data for {prop}. "
                f"{dirty_count} of {total} records ({pct:.0f}%) "
                f"contain non-typed data. "
                f"Manual review of source records recommended."
            )
            logger.warning(f"REFUSE tier message: {user_message}")

        result = DirtyDataResult(
            tier=tier,
            dirty_fraction=fraction,
            total_records=total,
            dirty_records=dirty_count,
            user_message=user_message,
        )

        logger.info(
            f"DirtyDataResult: tier={tier.value}, "
            f"dirty={dirty_count}/{total} ({fraction:.2%})"
        )

        return result

    def annotate_dirty_records(
        self, records: List[EvidenceRow]
    ) -> List[EvidenceRow]:
        """Annotate dirty records with original values preserved.

        WARNING: Dirty records MUST remain visible. This method returns ALL
        records (clean + dirty). For each dirty record, original values from
        dirty_fields are stored in the raw_values dict for audit trail.

        This method does NOT remove or filter dirty records. It only
        ensures that dirty records have their raw_values populated.

        Args:
            records: List of evidence rows to annotate.

        Returns:
            List of ALL records (clean + dirty) with dirty records
            annotated. Returns a shallow copy -- original list is not
            modified, but EvidenceRow objects may be replaced with
            new instances for dirty records.
        """
        annotated: List[EvidenceRow] = []

        for record in records:
            if record.dirty_flag:
                # Deep-copy to avoid mutating the original
                record_data = record.model_dump()

                # Ensure raw_values preserves the original values
                # for any dirty fields that don't already have entries
                raw = dict(record_data.get("raw_values", {}))
                for field_name in record.dirty_fields:
                    if field_name not in raw:
                        # Store current value as the raw original
                        raw[field_name] = record_data.get(field_name)

                record_data["raw_values"] = raw
                annotated_record = EvidenceRow(**record_data)
                annotated.append(annotated_record)

                logger.debug(
                    f"Annotated dirty record {record.record_id}: "
                    f"dirty_fields={record.dirty_fields}, "
                    f"raw_values={raw}"
                )
            else:
                # Clean records pass through unchanged
                annotated.append(record)

        logger.info(
            f"Annotated {len(records)} records: "
            f"{sum(1 for r in annotated if r.dirty_flag)} dirty, "
            f"{sum(1 for r in annotated if not r.dirty_flag)} clean"
        )

        return annotated


# =============================================================================
# FilterRelaxer
# =============================================================================


class FilterRelaxer:
    """Suggests minimal filter relaxations when Granta returns zero results.

    Per BuildSpec Section 3.4, when a query returns zero clean results,
    MIRA suggests filter relaxations to the user as OPTIONS. Relaxations
    are NEVER applied automatically.

    Relaxation rules define per-field widening percentages for numeric
    filter fields.

    Compliance: SWE-032
    """

    RELAXATION_RULES: List[Tuple[str, float]] = [
        ("temperature_c", 0.10),   # 10% widening
        ("pressure_kpa", 0.10),    # 10% widening
        ("o2_pct", 0.15),          # 15% widening
    ]
    """Relaxation rules: list of (field_name, relaxation_pct) tuples."""

    def suggest_relaxations(
        self,
        filters: Dict[str, Any],
        zero_result_field: str,
    ) -> List[RelaxationProposal]:
        """Suggest filter relaxations for a zero-result query.

        When Granta returns zero clean results, this method generates
        relaxation proposals for applicable numeric filter fields.
        Proposals are returned to the user as OPTIONS and are NOT
        applied automatically.

        Args:
            filters: Current query filters as {field_name: value}.
            zero_result_field: The field that produced zero results,
                used for logging context.

        Returns:
            List of RelaxationProposal objects, one per applicable
            relaxation rule where the field exists in filters.
        """
        proposals: List[RelaxationProposal] = []

        logger.info(
            f"Suggesting relaxations for zero-result field: "
            f"{zero_result_field}"
        )

        for field_name, relax_pct in self.RELAXATION_RULES:
            if field_name not in filters:
                logger.debug(
                    f"Skipping relaxation for '{field_name}': "
                    f"not in filters"
                )
                continue

            value = filters[field_name]
            if value is None:
                logger.debug(
                    f"Skipping relaxation for '{field_name}': value is None"
                )
                continue

            original, relaxed = self._relax_numeric_field(
                field_name, value, relax_pct
            )

            proposal = RelaxationProposal(
                field=field_name,
                original_value=original,
                relaxed_value=relaxed,
                relaxation_pct=relax_pct,
                estimated_results=0,  # Actual count requires index query
            )

            proposals.append(proposal)

            logger.info(
                f"Relaxation proposal: {field_name} "
                f"{original} -> {relaxed} "
                f"({relax_pct:.0%} widening)"
            )

        logger.info(
            f"Generated {len(proposals)} relaxation proposals "
            f"for zero_result_field='{zero_result_field}'"
        )

        return proposals

    def _relax_numeric_field(
        self,
        field: str,
        value: Any,
        pct: float,
    ) -> Tuple[Any, Any]:
        """Compute original and relaxed values for a numeric field.

        For range values (tuple or list of [low, high]): widen both
        ends by pct.
        For single numeric values: create a range of
        value * (1 - pct) to value * (1 + pct).

        Args:
            field: Field name (for logging).
            value: Current filter value (numeric or range).
            pct: Relaxation percentage (e.g., 0.10 for 10%).

        Returns:
            Tuple of (original_value, relaxed_value).
            For single values, relaxed_value is a dict with "min" and "max".
            For ranges, relaxed_value is a dict with widened "min" and "max".
        """
        if isinstance(value, (list, tuple)) and len(value) == 2:
            # Range value: widen both ends
            low, high = float(value[0]), float(value[1])
            span = high - low
            widening = span * pct

            original = {"min": low, "max": high}
            relaxed = {
                "min": round(low - widening, 6),
                "max": round(high + widening, 6),
            }

            logger.debug(
                f"Range relaxation for '{field}': "
                f"[{low}, {high}] -> [{relaxed['min']}, {relaxed['max']}] "
                f"(span={span}, widening={widening})"
            )

            return original, relaxed

        # Single numeric value: create range
        numeric_value = float(value)
        delta = abs(numeric_value) * pct

        original = numeric_value
        relaxed = {
            "min": round(numeric_value - delta, 6),
            "max": round(numeric_value + delta, 6),
        }

        logger.debug(
            f"Single-value relaxation for '{field}': "
            f"{numeric_value} -> [{relaxed['min']}, {relaxed['max']}] "
            f"(delta={delta})"
        )

        return original, relaxed
