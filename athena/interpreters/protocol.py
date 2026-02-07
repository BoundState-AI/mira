#!/usr/bin/env python3
"""
Module: Protocol
Purpose: ATHENA Interpreter Protocol.

BoundState AI 2025
Version: 1.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Fran OpenAI 5 <noreply@openai.com>
Co-Authored-By: Grok 4.0 <noreply@x.ai>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: SWE-032, SWE-033
Safety Critical: True
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Generic, TypeVar

from athena.stitching.models import LogicalTable

__all__ = ["DomainInterpreter"]
__safety_critical__ = True

T = TypeVar("T")  # Domain record type


class DomainInterpreter(ABC, Generic[T]):
    """
    Abstract base class for domain-specific interpreters.

    Interpreters convert LogicalTables with semantic tags into
    domain-specific records (e.g., EmbrittlementRecord, FlammabilityRecord).
    """

    @property
    @abstractmethod
    def domain(self) -> str:
        """Domain identifier (e.g., 'h2', 'o2')."""
        ...

    @abstractmethod
    def interpret(self, table: LogicalTable) -> list[T]:
        """
        Extract domain records from a logical table.

        Args:
            table: LogicalTable with semantic tags applied

        Returns:
            List of domain-specific records
        """
        ...

    @abstractmethod
    def can_interpret(self, table: LogicalTable) -> bool:
        """
        Check if this interpreter can handle the table.

        Args:
            table: LogicalTable to check

        Returns:
            True if table contains relevant domain data
        """
        ...

    def normalize_to_si(self, value: float, unit: str) -> float:
        """
        Convert value to SI units.

        Override for domain-specific unit handling.
        """
        return value
