#!/usr/bin/env python3
"""
Module: Batch Mode Safety-Critical REFUSE Gate
Purpose: Enforce required fields for safety-critical batch queries.

BoundState AI 2026
Version: 4.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: SWE-013, SWE-033, NASA-STD-6016 S4.2.1, S5.1.4
Safety Critical: True

Implements BuildSpec REV1 Item 3: Batch Mode Safety-Critical REFUSE Gate (P0).

WARNING: Batch mode MUST NOT become a mechanism for circumventing
safety-critical validation. The cost of a false negative in O2/H2
service is catastrophic.

Safety-critical queries (O2/H2/cryo/high-pressure) get a HARD REFUSE
if required fields are missing. General queries get penalty-only
(fed to the confidence calculator).

Spec Reference: BS-MIRA-V4-BUILDSPEC-001-REV1, Section 4
"""

from __future__ import annotations

import logging
import re
from typing import Dict, List

from .models import (
    BatchGateAction,
    BatchGateResult,
    EnvironmentSpec,
    ParsedQuery,
    SafetyContext,
)

logger = logging.getLogger(__name__)


# =============================================================================
# Required Fields Per Safety Context (BuildSpec Table 6)
# =============================================================================

SAFETY_REQUIRED_FIELDS: Dict[SafetyContext, List[str]] = {
    SafetyContext.OXYGEN: [
        "o2_pct", "pressure_kpa", "fluid_medium", "temperature_c",
    ],
    SafetyContext.HYDROGEN: [
        "fluid_medium", "pressure_kpa", "temperature_c",
    ],
    SafetyContext.CRYOGENIC: [
        "temperature_c", "pressure_kpa",
    ],
    SafetyContext.HIGH_PRESSURE: [
        "pressure_kpa", "temperature_c", "fluid_medium",
    ],
    # GENERAL has no required fields -- penalty-based only.
}

#: Default confidence penalty for general batch queries.
BATCH_GENERAL_PENALTY: float = 0.10

# =============================================================================
# Safety Context Detection Keywords
# =============================================================================

#: Oxygen-enriched keywords (O2 >= 23.5% threshold implied).
OXYGEN_KEYWORDS = {
    "LOX", "GOX", "LIQUID OXYGEN", "GASEOUS OXYGEN",
    "O2", "OXYGEN", "OXYGEN SERVICE", "OXYGEN ENRICHED",
}

#: Hydrogen service keywords.
HYDROGEN_KEYWORDS = {
    "LH2", "GH2", "LIQUID HYDROGEN", "GASEOUS HYDROGEN",
    "HYDROGEN", "H2", "HYDROGEN SERVICE",
}

#: Cryogenic temperature threshold in Celsius (-100F = -73.3C).
#: BuildSpec says < -100F; converting to Celsius for v4 canonical units.
CRYOGENIC_THRESHOLD_C: float = -73.3

#: High-pressure threshold in kPa (3000 psi = 20684 kPa).
HIGH_PRESSURE_THRESHOLD_KPA: float = 20684.0


class BatchSafetyGate:
    """Safety-critical batch mode gate per BuildSpec Section 4.

    For safety-critical contexts (O2/H2/cryo/high-pressure):
        Missing required fields -> REFUSE (hard gate).

    For GENERAL context:
        Missing fields -> PROCEED with confidence penalty.

    Compliance: SWE-013, NASA-STD-6016 S4.2.1, S5.1.4
    """

    def check(self, query: ParsedQuery) -> BatchGateResult:
        """Check batch safety gate for a query.

        Args:
            query: Parsed query with environment and intent.

        Returns:
            BatchGateResult with PROCEED or REFUSE.
        """
        # Detect safety context
        context = self.detect_safety_context(query)

        # General queries: penalty-only, always PROCEED
        if context == SafetyContext.GENERAL:
            logger.debug(
                f"Batch gate: GENERAL context, PROCEED with penalty "
                f"{BATCH_GENERAL_PENALTY}"
            )
            return BatchGateResult(
                action=BatchGateAction.PROCEED,
                penalty=BATCH_GENERAL_PENALTY,
                missing_fields=[],
                safety_context=context,
                reason="General context: penalty-based only.",
            )

        # Safety-critical: check required fields
        required = SAFETY_REQUIRED_FIELDS.get(context, [])
        missing = self._get_missing_fields(query.environment, required)

        if missing:
            reason = (
                f"Safety-critical context {context.value} requires: "
                f"{', '.join(missing)}. These fields are missing."
            )
            logger.warning(
                f"Batch gate REFUSE: {reason}"
            )
            return BatchGateResult(
                action=BatchGateAction.REFUSE,
                penalty=0.0,
                missing_fields=missing,
                safety_context=context,
                reason=reason,
            )

        # All required fields present: PROCEED
        logger.debug(
            f"Batch gate: {context.value} context, all required fields present, PROCEED"
        )
        return BatchGateResult(
            action=BatchGateAction.PROCEED,
            penalty=0.0,
            missing_fields=[],
            safety_context=context,
            reason=f"Safety-critical context {context.value}: all required fields present.",
        )

    def detect_safety_context(self, query: ParsedQuery) -> SafetyContext:
        """Detect safety context from query content.

        Detection priority:
        1. Explicit safety_context on ParsedQuery (if not GENERAL).
        2. Fluid medium keywords.
        3. O2 percentage threshold (>= 23.5%).
        4. Temperature threshold (< -73.3C / -100F).
        5. Pressure threshold (> 20684 kPa / 3000 psi).
        6. Query text keyword scan.
        7. Default: GENERAL.

        Args:
            query: Parsed query with environment and intent.

        Returns:
            SafetyContext enum value.
        """
        env = query.environment

        # 1. Check if already classified as non-GENERAL
        if query.safety_context != SafetyContext.GENERAL:
            return query.safety_context

        # 2. Check fluid medium
        if env.fluid_medium:
            fluid_upper = env.fluid_medium.upper().strip()
            if fluid_upper in OXYGEN_KEYWORDS or "OXYGEN" in fluid_upper:
                return SafetyContext.OXYGEN
            if fluid_upper in HYDROGEN_KEYWORDS or "HYDROGEN" in fluid_upper or fluid_upper == "H2":
                return SafetyContext.HYDROGEN

        # 3. Check O2 percentage
        if env.o2_pct is not None and env.o2_pct >= 23.5:
            return SafetyContext.OXYGEN

        # 4. Check cryogenic temperature
        if env.temperature_c is not None and env.temperature_c < CRYOGENIC_THRESHOLD_C:
            return SafetyContext.CRYOGENIC

        # 5. Check high pressure
        if env.pressure_kpa is not None and env.pressure_kpa > HIGH_PRESSURE_THRESHOLD_KPA:
            return SafetyContext.HIGH_PRESSURE

        # 6. Scan raw query for safety keywords
        query_upper = query.raw_query.upper()

        # Oxygen keywords in query text
        oxygen_patterns = [
            r"\bLOX\b", r"\bGOX\b", r"\bOXYGEN\b", r"\bO2\b",
            r"\bOXYGEN[\s-]*SERVICE\b", r"\bOXYGEN[\s-]*ENRICHED\b",
        ]
        for pattern in oxygen_patterns:
            if re.search(pattern, query_upper):
                return SafetyContext.OXYGEN

        # Hydrogen keywords in query text
        hydrogen_patterns = [
            r"\bLH2\b", r"\bGH2\b", r"\bHYDROGEN\b", r"\bH2\b",
            r"\bHYDROGEN[\s-]*SERVICE\b",
        ]
        for pattern in hydrogen_patterns:
            if re.search(pattern, query_upper):
                return SafetyContext.HYDROGEN

        # Cryogenic keywords
        if re.search(r"\bCRYO(?:GENIC)?\b", query_upper):
            return SafetyContext.CRYOGENIC

        # 7. Default: GENERAL
        return SafetyContext.GENERAL

    def _get_missing_fields(
        self,
        environment: EnvironmentSpec,
        required: List[str],
    ) -> List[str]:
        """Check which required fields are missing from environment.

        Args:
            environment: Query environment specification.
            required: List of required field names.

        Returns:
            List of field names that are None.
        """
        missing = []
        for field_name in required:
            value = getattr(environment, field_name, None)
            if value is None:
                missing.append(field_name)
        return missing
