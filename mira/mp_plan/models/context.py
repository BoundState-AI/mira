#!/usr/bin/env python3
"""
Module: Computation Context Models
Purpose: Cache key and version tracking for M&P Plan Generator V2

BoundState AI 2026
Version: 2.0.0
Classification: BoundState Proprietary

Implements Fran Fix #10: Complete cache keys

Fran: "Your computation_hash should include MPRIndex hash,
PolicyPack hash, MAPTIS dataset version hash, code version."

Compliance: NASA-STD-8739.8B, SWE-013, SWE-033
Safety Critical: False
"""

from __future__ import annotations

import hashlib
from datetime import datetime

from pydantic import BaseModel, Field

__version__ = "2.0.0"
__safety_critical__ = False


class ComputationContext(BaseModel):
    """
    All version information needed for cache validation.

    This ensures reproducibility by capturing all inputs that
    could affect computation results.

    Fran Fix #10: "Incomplete cache keys" -> include all hashes.

    Compliance: SWE-013 (reproducibility).
    """

    # MPR Index versions
    mpr_index_hash: str
    """SHA-256 hash of the MPR index content."""

    mpr_index_version: str
    """Version string of the MPR index."""

    mpr_count: int
    """Number of MPRs in the index (derived, not hardcoded)."""

    # Policy versions
    policy_pack_hash: str
    """SHA-256 hash of the policy pack content."""

    policy_pack_version: str
    """Version string of the policy pack."""

    # MAPTIS data versions
    maptis_dataset_version: str
    """Version of the MAPTIS dataset."""

    maptis_dataset_hash: str
    """SHA-256 hash of MAPTIS dataset metadata."""

    # Code version
    code_version: str
    """Git SHA or version tag of the code."""

    code_branch: str
    """Git branch name."""

    # Timestamp
    computed_at: datetime = Field(default_factory=datetime.now)
    """When this context was captured."""

    model_config = {"extra": "forbid", "populate_by_name": True}

    def compute_cache_key(self) -> str:
        """
        Compute cache key from all components.

        Returns:
            SHA-256 hash combining all version components.
        """
        components = [
            self.mpr_index_hash,
            self.policy_pack_hash,
            self.maptis_dataset_hash,
            self.code_version,
        ]
        return hashlib.sha256("|".join(components).encode()).hexdigest()

    def is_compatible_with(self, other: ComputationContext) -> bool:
        """
        Check if this context is compatible with another.

        Contexts are compatible if all hashes match.

        Args:
            other: Another computation context.

        Returns:
            True if contexts are compatible.
        """
        return (
            self.mpr_index_hash == other.mpr_index_hash
            and self.policy_pack_hash == other.policy_pack_hash
            and self.maptis_dataset_hash == other.maptis_dataset_hash
            and self.code_version == other.code_version
        )


class RunManifest(BaseModel):
    """
    Complete run manifest with all version info.

    Records everything needed to reproduce or audit a plan generation run.
    """

    run_id: str
    """Unique identifier for this run."""

    session_id: str
    """Session this run belongs to."""

    # Context (V2: includes all hashes)
    computation_context: ComputationContext
    """Version context for this run."""

    # Inputs
    input_fingerprints: dict[str, str]
    """SHA-256 hashes of all input files/data."""

    # Policy pack
    policy_pack_id: str
    """ID of policy pack used."""

    policy_pack_hash: str
    """Hash of policy pack content."""

    # Timing
    started_at: datetime = Field(default_factory=datetime.now)
    """When run started."""

    completed_at: datetime | None = None
    """When run completed (None if still running)."""

    # Outputs
    output_artifacts: list[str] = Field(default_factory=list)
    """List of artifact IDs produced."""

    model_config = {"extra": "forbid", "populate_by_name": True}
