#!/usr/bin/env python3
"""
Module: Base Adapter
Purpose: Base class for all compliance adapters

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
NASA-STD-6016C Compliance Module - Base Adapter

Base class for all adapters in the compliance module.

IMPORTANT: Adapters emit signals only, NOT MPRDetermination.
That's the conductor's job.

Compliance: NASA-STD-8739.8B, SWE-013, SWE-033

Author: BoundState Team
Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Fran OpenAI <noreply@openai.com>
Co-Authored-By: Grok <noreply@x.ai>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI
"""

__version__ = "2.0.0"
__safety_critical__ = True

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Optional

from mira.compliance.models.enums import SourceType
from mira.compliance.models.evidence import EvidenceRef
from mira.compliance.models.policy import EnvironmentDefinition
from mira.compliance.models.resolution import MaterialResolutionResult


class BaseAdapter(ABC):
    """
    Base class for compliance adapters.

    All adapters:
    - Take MaterialResolutionResult and EnvironmentDefinition as input
    - Emit signals (gaps, constraints, evidence)
    - Do NOT select MPRs (that's the conductor's job)
    """

    def __init__(self, version: str = "1.0.0"):
        """
        Initialize adapter.

        Args:
            version: Adapter version for audit trail
        """
        self.version = version

    @abstractmethod
    def evaluate(
        self,
        material: MaterialResolutionResult,
        environment: EnvironmentDefinition,
    ):
        """
        Evaluate material in environment.

        Args:
            material: Resolved material information
            environment: Environment definition

        Returns:
            Adapter-specific output (O2AdapterOutput, H2AdapterOutput, etc.)
        """
        pass

    def _infer_source_type(self, source_id: str) -> SourceType:
        """
        Infer source type from source_id string.

        Fran Fix #2: Enable source typing without string parsing in business logic.

        Args:
            source_id: Source identifier string

        Returns:
            SourceType enum value
        """
        source_id_lower = source_id.lower()

        if "maptis" in source_id_lower:
            return SourceType.MAPTIS
        elif "test" in source_id_lower or "report" in source_id_lower:
            return SourceType.TEST_REPORT
        elif any(std in source_id_lower for std in ["nasa-std", "jsc-", "ksc-", "msfc-"]):
            return SourceType.STANDARD
        elif "mua" in source_id_lower:
            return SourceType.MUA_PRECEDENT
        elif "analysis" in source_id_lower:
            return SourceType.ANALYSIS_REPORT
        else:
            return SourceType.BOK

    def _extract_version(self, source_id: str) -> Optional[str]:
        """
        Extract version from source_id if present.

        Args:
            source_id: Source identifier string

        Returns:
            Version string if found, None otherwise
        """
        import re

        # Look for version patterns like "v1.0", "Rev A", "6016C"
        patterns = [
            r'[vV](\d+(?:\.\d+)*)',  # v1.0, V2.3.1
            r'[Rr]ev\s*([A-Z])',     # Rev A, rev B
            r'(\d{4}[A-Z])',          # 6016C
        ]

        for pattern in patterns:
            match = re.search(pattern, source_id)
            if match:
                return match.group(1)

        return None

    def _create_evidence_ref(
        self,
        source_id: str,
        locator: Optional[str] = None,
        quote: Optional[str] = None,
        confidence: float = 0.9,
        confidence_basis: str = "Adapter evaluation",
        retrieval_method: str = "twin_engine",
    ) -> EvidenceRef:
        """
        Create an EvidenceRef with inferred source type.

        Args:
            source_id: Source identifier
            locator: Location within source
            quote: Direct quote from source
            confidence: Confidence score
            confidence_basis: How confidence was determined
            retrieval_method: How evidence was retrieved

        Returns:
            EvidenceRef instance
        """
        return EvidenceRef(
            source_type=self._infer_source_type(source_id),
            source_id=source_id,
            source_version=self._extract_version(source_id),
            locator=locator,
            quote=quote[:500] if quote else None,
            confidence=confidence,
            confidence_basis=confidence_basis,
            retrieved_at=datetime.now(),
            retrieval_method=retrieval_method,
        )
