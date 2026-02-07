#!/usr/bin/env python3
"""
Module: Heritage Veto Engine
Purpose: Tiered heritage veto policy with envelope matching and rank-sink.

BoundState AI 2026
Version: 4.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: SWE-032, SWE-033
Safety Critical: True
Spec Reference: BS-MIRA-V4-BUILDSPEC-001-REV1, Section 7

Heritage veto prevents materials with known heritage failures from being
recommended in similar environments WITHOUT removing them from results.

Tiered behaviour:
  - SAFETY_CRITICAL context: requires_acknowledgment=True, material is
    gated behind an engineer acknowledgment before use.
  - NON_SAFETY context: rank_penalty=0.30 applied via rank-sink. Material
    drops below non-vetoed results but remains visible.

Envelope matching (temperature / pressure / media) determines whether a
heritage failure record's environment overlaps the current query. All three
dimensions must overlap for a veto to apply (BuildSpec Section 7.4).

Override records are immutable and linked to the Decision Lineage via
lineage_hash.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from .models import (
    EnvironmentSpec,
    HeritageOverride,
    HeritageVetoResult,
    HeritageVetoType,
    SafetyContext,
)

logger = logging.getLogger(__name__)


# =============================================================================
# Constants
# =============================================================================

# Temperature margin: 10% relative overlap for envelope matching.
TEMPERATURE_MARGIN: float = 0.10

# Pressure overlap factor: query >= 0.80 * failure_pressure triggers overlap.
PRESSURE_OVERLAP_FACTOR: float = 0.80

# Rank-sink penalty for non-safety vetoed materials.
RANK_SINK_PENALTY: float = 0.30


# =============================================================================
# EnvelopeMatcher
# =============================================================================


class EnvelopeMatcher:
    """Three-dimensional envelope matcher for heritage veto evaluation.

    Compares a query environment against a heritage failure environment
    across temperature, pressure, and fluid medium. All three dimensions
    must overlap for a match (AND logic, per BuildSpec Section 7.4).

    Compliance: SWE-032, SWE-033
    Safety Critical: True
    """

    TEMPERATURE_MARGIN: float = TEMPERATURE_MARGIN
    PRESSURE_OVERLAP_FACTOR: float = PRESSURE_OVERLAP_FACTOR

    def match_envelope(
        self,
        query_env: EnvironmentSpec,
        failure_env: EnvironmentSpec,
    ) -> Tuple[bool, Dict[str, Any]]:
        """Determine whether a query environment overlaps a failure environment.

        All three dimensions (temperature, pressure, media) must overlap
        for the overall match to be True.

        Args:
            query_env:   The current query's environment specification.
            failure_env: The heritage failure record's environment.

        Returns:
            A 2-tuple of:
              - match (bool): True if ALL three dimensions overlap.
              - details (dict): Per-dimension match results and scores.

        Compliance: SWE-032, SWE-033, BuildSpec Section 7.4
        """
        temp_match, temp_detail = self._match_temperature(
            query_env.temperature_c, failure_env.temperature_c
        )
        press_match, press_detail = self._match_pressure(
            query_env.pressure_kpa, failure_env.pressure_kpa
        )
        media_match, media_detail = self._match_media(
            query_env.fluid_medium, failure_env.fluid_medium
        )

        all_match = temp_match and press_match and media_match

        details: Dict[str, Any] = {
            "temperature": {
                "match": temp_match,
                **temp_detail,
            },
            "pressure": {
                "match": press_match,
                **press_detail,
            },
            "media": {
                "match": media_match,
                **media_detail,
            },
            "all_match": all_match,
        }

        logger.debug(
            "Envelope match result: all_match=%s | temp=%s press=%s media=%s",
            all_match,
            temp_match,
            press_match,
            media_match,
        )

        return all_match, details

    # --------------------------------------------------------------------- #
    # Dimension matchers
    # --------------------------------------------------------------------- #

    def _match_temperature(
        self,
        query_temp: Optional[float],
        failure_temp: Optional[float],
    ) -> Tuple[bool, Dict[str, Any]]:
        """Check temperature overlap within the configured margin.

        Temperature match criterion:
            abs(query_temp - failure_temp) / max(abs(failure_temp), 1.0)
            <= TEMPERATURE_MARGIN

        If either temperature is None, the dimension does NOT match
        (null-safety: no guessing, per BuildSpec Section 7.4).

        Args:
            query_temp:   Query temperature in Celsius.
            failure_temp: Failure record temperature in Celsius.

        Returns:
            Tuple of (match: bool, detail: dict).
        """
        detail: Dict[str, Any] = {
            "query_temp_c": query_temp,
            "failure_temp_c": failure_temp,
            "margin": self.TEMPERATURE_MARGIN,
        }

        if query_temp is None or failure_temp is None:
            detail["reason"] = "missing_temperature"
            detail["relative_diff"] = None
            return False, detail

        denominator = max(abs(failure_temp), 1.0)
        relative_diff = abs(query_temp - failure_temp) / denominator
        detail["relative_diff"] = round(relative_diff, 6)

        match = relative_diff <= self.TEMPERATURE_MARGIN
        if not match:
            detail["reason"] = (
                f"relative_diff {relative_diff:.4f} > margin "
                f"{self.TEMPERATURE_MARGIN}"
            )
        else:
            detail["reason"] = "within_margin"

        return match, detail

    def _match_pressure(
        self,
        query_pressure: Optional[float],
        failure_pressure: Optional[float],
    ) -> Tuple[bool, Dict[str, Any]]:
        """Check pressure overlap using the configured factor.

        Pressure match criterion:
            query_pressure >= PRESSURE_OVERLAP_FACTOR * failure_pressure

        If either pressure is None, the dimension does NOT match
        (null-safety: no guessing).

        Args:
            query_pressure:   Query pressure in kPa.
            failure_pressure: Failure record pressure in kPa.

        Returns:
            Tuple of (match: bool, detail: dict).
        """
        detail: Dict[str, Any] = {
            "query_pressure_kpa": query_pressure,
            "failure_pressure_kpa": failure_pressure,
            "factor": self.PRESSURE_OVERLAP_FACTOR,
        }

        if query_pressure is None or failure_pressure is None:
            detail["reason"] = "missing_pressure"
            detail["threshold"] = None
            return False, detail

        threshold = self.PRESSURE_OVERLAP_FACTOR * failure_pressure
        detail["threshold"] = round(threshold, 6)

        match = query_pressure >= threshold
        if not match:
            detail["reason"] = (
                f"query_pressure {query_pressure:.2f} kPa < threshold "
                f"{threshold:.2f} kPa"
            )
        else:
            detail["reason"] = "at_or_above_threshold"

        return match, detail

    def _match_media(
        self,
        query_media: Optional[str],
        failure_media: Optional[str],
    ) -> Tuple[bool, Dict[str, Any]]:
        """Check fluid medium exact match (case-insensitive, stripped).

        Both media values are uppercased and stripped before comparison.
        If either is None, the dimension does NOT match.

        Args:
            query_media:   Query fluid medium string.
            failure_media: Failure record fluid medium string.

        Returns:
            Tuple of (match: bool, detail: dict).
        """
        detail: Dict[str, Any] = {
            "query_media": query_media,
            "failure_media": failure_media,
        }

        if query_media is None or failure_media is None:
            detail["reason"] = "missing_media"
            return False, detail

        q_norm = query_media.strip().upper()
        f_norm = failure_media.strip().upper()
        detail["query_media_normalised"] = q_norm
        detail["failure_media_normalised"] = f_norm

        match = q_norm == f_norm
        if not match:
            detail["reason"] = f"media mismatch: '{q_norm}' != '{f_norm}'"
        else:
            detail["reason"] = "exact_match"

        return match, detail


# =============================================================================
# HeritageVetoEngine
# =============================================================================


class HeritageVetoEngine:
    """Tiered heritage veto engine per BuildSpec Section 7.

    Checks a material against known heritage failure records. When the
    query environment overlaps a failure environment (all three dimensions),
    a veto is raised.

    Behaviour depends on safety context:
      - SAFETY_CRITICAL contexts (oxygen, hydrogen, cryogenic, high_pressure):
        requires_acknowledgment=True, veto_type=SAFETY_CRITICAL.
      - NON_SAFETY (general): rank_penalty=RANK_SINK_PENALTY,
        veto_type=NON_SAFETY.

    Compliance: SWE-032, SWE-033, NASA-STD-6016 S4.2.1
    Safety Critical: True
    """

    RANK_SINK_PENALTY: float = RANK_SINK_PENALTY

    def __init__(self) -> None:
        """Initialise the engine with a fresh EnvelopeMatcher."""
        self._matcher = EnvelopeMatcher()
        logger.info("HeritageVetoEngine initialised")

    # --------------------------------------------------------------------- #
    # Core veto check
    # --------------------------------------------------------------------- #

    def check_heritage(
        self,
        material_key: str,
        query_env: EnvironmentSpec,
        heritage_records: List[Dict[str, Any]],
        safety_context: SafetyContext,
    ) -> HeritageVetoResult:
        """Check a material against heritage failure records.

        Heritage records format::

            [
                {
                    "failure_id": str,
                    "material_key": str,
                    "failure_environment": dict,   # EnvironmentSpec-compatible
                    "failure_description": str,
                },
                ...
            ]

        Args:
            material_key:     The material identifier to check.
            query_env:        The current query's environment specification.
            heritage_records: List of heritage failure record dicts.
            safety_context:   The safety context of the current query.

        Returns:
            HeritageVetoResult with match details and veto decision.

        Compliance: SWE-032, SWE-033, BuildSpec Section 7.2
        """
        matching_failure_ids: List[str] = []
        all_envelope_details: Dict[str, Any] = {}

        for record in heritage_records:
            failure_id = record.get("failure_id", "UNKNOWN")
            record_material = record.get("material_key", "")

            # Only check records that match the target material
            if record_material != material_key:
                logger.debug(
                    "Skipping heritage record '%s': material_key '%s' "
                    "does not match target '%s'",
                    failure_id,
                    record_material,
                    material_key,
                )
                continue

            # Parse the failure environment into an EnvironmentSpec
            failure_env_data = record.get("failure_environment", {})
            try:
                failure_env = EnvironmentSpec(**failure_env_data)
            except Exception as exc:
                logger.warning(
                    "Could not parse failure_environment for record '%s': %s. "
                    "Skipping this record.",
                    failure_id,
                    exc,
                )
                continue

            # Run envelope matching
            matched, details = self._matcher.match_envelope(query_env, failure_env)

            if matched:
                matching_failure_ids.append(failure_id)
                all_envelope_details[failure_id] = details
                logger.info(
                    "Heritage veto MATCH: material='%s' failure_id='%s' "
                    "description='%s'",
                    material_key,
                    failure_id,
                    record.get("failure_description", "N/A"),
                )
            else:
                logger.debug(
                    "Heritage record '%s' did not match query envelope.",
                    failure_id,
                )

        # Determine veto outcome
        vetoed = len(matching_failure_ids) > 0

        if not vetoed:
            logger.debug(
                "No heritage veto for material '%s' (%d records checked).",
                material_key,
                len(heritage_records),
            )
            return HeritageVetoResult(
                vetoed=False,
                veto_type=None,
                heritage_failure_ids=[],
                requires_acknowledgment=False,
                rank_penalty=0.0,
                envelope_match_details={},
            )

        # Determine tier based on safety context
        is_safety_critical = safety_context != SafetyContext.GENERAL

        if is_safety_critical:
            veto_type = HeritageVetoType.SAFETY_CRITICAL
            requires_acknowledgment = True
            rank_penalty = 0.0  # Safety-critical uses acknowledgment gate, not rank sink
            logger.warning(
                "SAFETY-CRITICAL heritage veto for material '%s': "
                "%d matching failures [%s]. Requires engineer acknowledgment.",
                material_key,
                len(matching_failure_ids),
                ", ".join(matching_failure_ids),
            )
        else:
            veto_type = HeritageVetoType.NON_SAFETY
            requires_acknowledgment = False
            rank_penalty = self.RANK_SINK_PENALTY
            logger.info(
                "NON-SAFETY heritage veto for material '%s': "
                "%d matching failures [%s]. Rank penalty=%.2f.",
                material_key,
                len(matching_failure_ids),
                ", ".join(matching_failure_ids),
                rank_penalty,
            )

        return HeritageVetoResult(
            vetoed=True,
            veto_type=veto_type,
            heritage_failure_ids=matching_failure_ids,
            requires_acknowledgment=requires_acknowledgment,
            rank_penalty=rank_penalty,
            envelope_match_details=all_envelope_details,
        )

    # --------------------------------------------------------------------- #
    # Override creation
    # --------------------------------------------------------------------- #

    def create_override(
        self,
        material_key: str,
        heritage_failure_id: str,
        failure_env: EnvironmentSpec,
        query_env: EnvironmentSpec,
        engineer_name: str,
        engineer_rationale: str,
        lineage_hash: str,
    ) -> HeritageOverride:
        """Create an immutable heritage veto override record.

        An override records an engineer's acknowledgment that they have
        reviewed a heritage failure and accept the risk for the current
        query context.

        Args:
            material_key:         Material identifier.
            heritage_failure_id:  The heritage failure record being overridden.
            failure_env:          Environment of the heritage failure.
            query_env:            Environment of the current query.
            engineer_name:        Name of the acknowledging engineer.
            engineer_rationale:   Free-text rationale for the override.
            lineage_hash:         Links to the parent Decision Lineage query_hash.

        Returns:
            An immutable HeritageOverride record with UUID and timestamp.

        Compliance: SWE-013, SWE-033, NASA-STD-6016 S4.2.1
        """
        override = HeritageOverride(
            override_id=str(uuid.uuid4()),
            material_key=material_key,
            heritage_failure_id=heritage_failure_id,
            failure_environment=failure_env,
            query_environment=query_env,
            engineer_name=engineer_name,
            engineer_rationale=engineer_rationale,
            timestamp=datetime.now(timezone.utc).isoformat(),
            lineage_hash=lineage_hash,
            acknowledged=True,
        )

        logger.info(
            "Heritage override created: override_id='%s' material='%s' "
            "failure_id='%s' engineer='%s' lineage='%s'",
            override.override_id,
            material_key,
            heritage_failure_id,
            engineer_name,
            lineage_hash,
        )

        return override

    # --------------------------------------------------------------------- #
    # Rank-sink application
    # --------------------------------------------------------------------- #

    @staticmethod
    def apply_rank_sink(
        results: List[Dict[str, Any]],
        vetoed_keys: set,
    ) -> List[Dict[str, Any]]:
        """Re-order results so vetoed materials sink below non-vetoed ones.

        Vetoed materials are NOT removed -- they remain visible but are
        placed after all non-vetoed materials. Relative ordering within
        each group (non-vetoed and vetoed) is preserved.

        Args:
            results:     List of result dicts. Each must have a
                         ``material_key`` field.
            vetoed_keys: Set of material_key strings that are vetoed.

        Returns:
            Re-ordered list: non-vetoed results first, then vetoed results.

        Compliance: BuildSpec Section 7.3
        """
        non_vetoed: List[Dict[str, Any]] = []
        vetoed: List[Dict[str, Any]] = []

        for result in results:
            key = result.get("material_key", "")
            if key in vetoed_keys:
                vetoed.append(result)
            else:
                non_vetoed.append(result)

        logger.debug(
            "Rank sink applied: %d non-vetoed, %d vetoed (total %d)",
            len(non_vetoed),
            len(vetoed),
            len(results),
        )

        return non_vetoed + vetoed
