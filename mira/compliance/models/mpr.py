#!/usr/bin/env python3
"""
Module: MPR Models
Purpose: Material and Process Requirement index from NASA-STD-6016C

BoundState AI 2025
Version: 2.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Fran OpenAI 5 <noreply@openai.com>
Co-Authored-By: Grok 4.0 <noreply@x.ai>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: NASA-STD-8739.8B, SWE-013, SWE-033
Safety Critical: True
"""

# Copyright © 2025 BoundState AI. All Rights Reserved.
# Classification: BoundState Proprietary
# License: Evaluation Use Only - Authorized Pilot Program
"""
NASA-STD-6016C Compliance Module - MPR Models

MPRRecord: Individual Material and Process Requirement from NASA-STD-6016C.
MPRIndex: Index of all MPRs with lookup and filtering capabilities.

Fran Fix #8: Added priority field for deterministic selection when
multiple MPRs match the same failure mode. Uses get_mprs_for_signal()
instead of hardcoded mapping tables.

Compliance: NASA-STD-8739.8B, SWE-013, SWE-033

Author: BoundState Team
Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Fran OpenAI <noreply@openai.com>
Co-Authored-By: Grok <noreply@x.ai>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI
"""

__version__ = "2.0.0"
__safety_critical__ = True

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel

from mira.compliance.models.enums import FailureMode
from mira.compliance.models.evidence import EvidenceRef
from mira.compliance.models.gaps import GapSignal


class MPRRecord(BaseModel):
    """
    MPR definition from NASA-STD-6016C index.

    Fran Fix #8: Added priority field for deterministic selection
    when multiple MPRs match the same failure mode.
    """

    # Identity
    mpr_number: int
    """MPR number from NASA-STD-6016C (e.g., 1, 2, 3...)."""

    mpr_id: str
    """Full MPR identifier (e.g., 'MPR-001')."""

    # Content
    section: str
    """Section reference in NASA-STD-6016C (e.g., '4.2.1')."""

    title: str
    """MPR title/name."""

    shall_text: str
    """The 'shall' requirement text."""

    verification_method: str
    """How compliance is verified."""

    # Applicability
    applicability_triggers: list[str] = []
    """Environment/condition triggers that make this MPR applicable."""

    exception_refs: list[str] = []
    """References to exception conditions."""

    # Failure mode linkage (Fran Fix #8)
    related_failure_modes: list[FailureMode] = []
    """Failure modes this MPR addresses. Used for signal → MPR mapping."""

    priority: int = 100
    """Priority for selection when multiple MPRs match. Lower = higher priority."""

    # Source evidence
    source_evidence: EvidenceRef
    """Evidence for this MPR (link to standard)."""

    model_config = {"extra": "forbid"}

    def matches_failure_mode(self, fm: FailureMode) -> bool:
        """Check if this MPR is related to a failure mode."""
        return fm in self.related_failure_modes

    def is_applicable_to_context(self, env_context: dict) -> bool:
        """
        Check if MPR is applicable to environment context.

        Args:
            env_context: Dictionary with environment parameters

        Returns:
            True if any applicability trigger matches
        """
        if not self.applicability_triggers:
            return True  # No triggers means always applicable

        for trigger in self.applicability_triggers:
            # Simple trigger matching - can be extended
            if trigger == "oxygen_service":
                if env_context.get("is_oxygen_enriched") or env_context.get("oxygen_pct", 21) > 23.5:
                    return True
            elif trigger == "hydrogen_service":
                if env_context.get("is_hydrogen_service"):
                    return True
            elif trigger == "habitable":
                if env_context.get("is_habitable"):
                    return True
            elif trigger == "cryogenic":
                if env_context.get("is_cryogenic"):
                    return True
            elif trigger == "high_pressure":
                if env_context.get("pressure_is_high"):
                    return True
            elif trigger == "always":
                return True

        return False


class MPRIndex(BaseModel):
    """
    Index of all MPRs from NASA-STD-6016C.

    The ONLY source of MPR data. No hardcoded MPR numbers anywhere else.

    Fran Fix #8: Uses get_mprs_for_signal() for signal → MPR mapping,
    not hardcoded mapping tables.
    """

    # Metadata
    standard_version: str
    """Version of NASA-STD-6016C (e.g., 'C')."""

    parse_date: datetime
    """When the index was parsed/generated."""

    source_document_hash: str
    """SHA-256 hash of source document for reproducibility."""

    # MPR records
    records: dict[int, MPRRecord]
    """Map of MPR number to MPRRecord."""

    model_config = {"extra": "forbid"}

    def get_by_number(self, n: int) -> Optional[MPRRecord]:
        """Get MPR by number."""
        return self.records.get(n)

    def get_by_id(self, mpr_id: str) -> Optional[MPRRecord]:
        """Get MPR by ID string (e.g., 'MPR-001')."""
        for record in self.records.values():
            if record.mpr_id == mpr_id:
                return record
        return None

    def get_all(self) -> list[MPRRecord]:
        """Get all MPR records."""
        return list(self.records.values())

    def get_by_failure_mode(self, fm: FailureMode) -> list[MPRRecord]:
        """
        Get all MPRs related to a failure mode, sorted by priority.

        Fran Fix #8: Deterministic ordering via priority field.

        Args:
            fm: Failure mode to filter by

        Returns:
            List of matching MPRs sorted by priority (ascending)
        """
        matches = [r for r in self.records.values() if fm in r.related_failure_modes]
        return sorted(matches, key=lambda r: r.priority)

    def get_applicable(self, env_context: dict) -> list[MPRRecord]:
        """
        Get MPRs applicable to environment context.

        Args:
            env_context: Dictionary with environment parameters

        Returns:
            List of applicable MPRs
        """
        return [r for r in self.records.values() if r.is_applicable_to_context(env_context)]

    def get_mprs_for_signal(
        self,
        signal: GapSignal,
        env_context: dict,
    ) -> list[MPRRecord]:
        """
        Get MPRs that should receive this signal.

        Fran Fix #8: Deterministic mapping via failure_mode + applicability.
        Returns ALL matching MPRs (no [0] selection).

        Args:
            signal: Gap signal to map
            env_context: Environment context for applicability filtering

        Returns:
            List of matching MPRs (all of them, not just first)
        """
        # Get by failure mode
        fm_matches = self.get_by_failure_mode(signal.gap_type)

        # Filter by applicability
        applicable = self.get_applicable(env_context)
        applicable_numbers = {m.mpr_number for m in applicable}

        # Intersection - MPRs that match failure mode AND are applicable
        return [m for m in fm_matches if m.mpr_number in applicable_numbers]

    def get_by_section(self, section_prefix: str) -> list[MPRRecord]:
        """Get MPRs in a section (e.g., '4.2' matches '4.2.1', '4.2.2')."""
        return [r for r in self.records.values() if r.section.startswith(section_prefix)]

    @property
    def total_mprs(self) -> int:
        """Total number of MPRs in index."""
        return len(self.records)

    def validate_completeness(self) -> list[str]:
        """
        Validate that index covers all expected failure modes.

        Returns:
            List of warnings about missing coverage
        """
        warnings = []

        # Check each failure mode has at least one MPR
        for fm in FailureMode:
            if not self.get_by_failure_mode(fm):
                warnings.append(f"No MPR covers failure mode: {fm.value}")

        return warnings


def create_mpr_index_from_yaml(yaml_path: str) -> MPRIndex:
    """
    Create MPR index from YAML file.

    Args:
        yaml_path: Path to MPR index YAML file

    Returns:
        MPRIndex instance
    """
    import yaml
    from pathlib import Path

    with open(yaml_path, "r") as f:
        data = yaml.safe_load(f)

    records = {}
    for mpr_data in data.get("mprs", []):
        # Convert failure_modes from strings to enums
        failure_modes = [
            FailureMode(fm) for fm in mpr_data.get("related_failure_modes", [])
        ]

        # Create evidence ref for source
        source_evidence = EvidenceRef(
            source_type="standard",
            source_id="NASA-STD-6016C",
            source_version=data.get("standard_version", "C"),
            locator=mpr_data.get("section"),
            confidence=1.0,
            confidence_basis="Direct standard citation",
            retrieved_at=datetime.now(),
            retrieval_method="yaml_index",
        )

        record = MPRRecord(
            mpr_number=mpr_data["mpr_number"],
            mpr_id=mpr_data.get("mpr_id", f"MPR-{mpr_data['mpr_number']:03d}"),
            section=mpr_data["section"],
            title=mpr_data["title"],
            shall_text=mpr_data["shall_text"],
            verification_method=mpr_data.get("verification_method", "Analysis/Test"),
            applicability_triggers=mpr_data.get("applicability_triggers", []),
            exception_refs=mpr_data.get("exception_refs", []),
            related_failure_modes=failure_modes,
            priority=mpr_data.get("priority", 100),
            source_evidence=source_evidence,
        )
        records[record.mpr_number] = record

    return MPRIndex(
        standard_version=data.get("standard_version", "C"),
        parse_date=datetime.now(),
        source_document_hash=data.get("source_document_hash", ""),
        records=records,
    )
