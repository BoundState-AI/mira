#!/usr/bin/env python3
"""
Module: Evidence Model
Purpose: Extended EvidenceRef with source typing for basis selection

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
NASA-STD-6016C Compliance Module - Evidence Model

Extended EvidenceRef with source typing for basis selection.

Fran Fix #2: Added source_type and source_version to enable
TEST vs POLICY basis selection without string parsing.

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
from typing import Optional

from pydantic import BaseModel, Field

from mira.compliance.models.enums import SourceType


class EvidenceRef(BaseModel):
    """
    Evidence reference with source typing for basis selection.

    Fran Fix #2: Added source_type and source_version to enable
    TEST vs POLICY basis selection without string parsing.

    All evidence in the compliance module uses this model for
    full traceability and audit compliance.
    """

    # Source identification
    source_type: SourceType
    """Type of evidence source - enables TEST vs POLICY basis selection."""

    source_id: str
    """Unique identifier for the source (e.g., MAPTIS ID, report number)."""

    source_version: Optional[str] = None
    """Version of the source document (required for policy/standard refs)."""

    # Location within source
    locator: Optional[str] = None
    """Location within source (page, section, table number)."""

    anchor_id: Optional[str] = None
    """Specific anchor within the document (for deep linking)."""

    quote: Optional[str] = Field(default=None, max_length=500)
    """Direct quote from source (max 500 chars for audit trail)."""

    # Reproducibility hashes
    document_fingerprint: Optional[str] = None
    """SHA-256 hash of the full source document."""

    content_hash: Optional[str] = None
    """SHA-256 hash of the extracted snippet/quote."""

    # MAPTIS-specific fields
    maptis_record_id: Optional[str] = None
    """MAPTIS record ID if source is MAPTIS."""

    maptis_query_signature: Optional[str] = None
    """Hash of the query used to retrieve this MAPTIS record."""

    # Confidence assessment
    confidence: float = Field(ge=0.0, le=1.0)
    """Confidence in this evidence (0.0-1.0)."""

    confidence_basis: str
    """Explanation of how confidence was determined."""

    # Retrieval metadata
    retrieved_at: datetime
    """Timestamp when evidence was retrieved."""

    retrieval_method: str
    """Method used to retrieve evidence (e.g., 'faiss_search', 'direct_lookup')."""

    model_config = {"extra": "forbid"}

    def supports_test_basis(self) -> bool:
        """
        Check if this evidence can support ComplianceBasis.TEST.

        Only MAPTIS records and test reports provide direct test evidence.
        Other sources (BOK, standards, precedents) support POLICY basis.

        Returns:
            True if evidence is from MAPTIS or a test report.
        """
        return self.source_type in {SourceType.MAPTIS, SourceType.TEST_REPORT}

    def supports_policy_basis(self) -> bool:
        """
        Check if this evidence can support ComplianceBasis.POLICY.

        All evidence types can support policy basis, but standards and
        BOK are the primary sources.

        Returns:
            True if evidence is from a standard or BOK.
        """
        return self.source_type in {SourceType.STANDARD, SourceType.BOK}

    def is_precedent(self) -> bool:
        """Check if this evidence is from a historical MUA precedent."""
        return self.source_type == SourceType.MUA_PRECEDENT

    def get_citation(self) -> str:
        """
        Generate a citation string for this evidence.

        Returns:
            Formatted citation string for documentation.
        """
        parts = [self.source_id]
        if self.source_version:
            parts.append(f"v{self.source_version}")
        if self.locator:
            parts.append(self.locator)
        return ", ".join(parts)


class EvidenceCollection(BaseModel):
    """
    Collection of evidence references for a determination.

    Provides utilities for analyzing evidence strength and basis.
    """

    evidence_refs: list[EvidenceRef] = []
    """List of evidence references."""

    model_config = {"extra": "forbid"}

    def get_strongest_evidence(self) -> Optional[EvidenceRef]:
        """Get the evidence with highest confidence."""
        if not self.evidence_refs:
            return None
        return max(self.evidence_refs, key=lambda e: e.confidence)

    def has_test_evidence(self) -> bool:
        """Check if any evidence supports TEST basis."""
        return any(e.supports_test_basis() for e in self.evidence_refs)

    def has_precedent_evidence(self) -> bool:
        """Check if any evidence is from precedent."""
        return any(e.is_precedent() for e in self.evidence_refs)

    def filter_by_source_type(self, source_type: SourceType) -> list[EvidenceRef]:
        """Get all evidence of a specific source type."""
        return [e for e in self.evidence_refs if e.source_type == source_type]

    def get_maptis_refs(self) -> list[EvidenceRef]:
        """Get all MAPTIS evidence references."""
        return self.filter_by_source_type(SourceType.MAPTIS)

    def get_average_confidence(self) -> float:
        """Get average confidence across all evidence."""
        if not self.evidence_refs:
            return 0.0
        return sum(e.confidence for e in self.evidence_refs) / len(self.evidence_refs)

    def get_citations(self) -> list[str]:
        """Get all citations as a list of strings."""
        return [e.get_citation() for e in self.evidence_refs]
