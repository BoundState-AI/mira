#!/usr/bin/env python3
"""
Module: Models
Purpose: ATHENA Validation Models.

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
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Generic, TypeVar

__all__ = ["ValidationResult", "ValidationStatus", "GateProtocol"]
__safety_critical__ = True

T = TypeVar("T")


class ValidationStatus(str, Enum):
    """Validation gate status."""
    PASS = "pass"
    WARN = "warn"
    FAIL = "fail"


@dataclass
class ValidationResult:
    """Result of a validation gate."""
    gate_name: str
    status: ValidationStatus
    message: str
    details: dict[str, Any] = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        """Check if validation passed."""
        return self.status == ValidationStatus.PASS

    @property
    def failed(self) -> bool:
        """Check if validation failed."""
        return self.status == ValidationStatus.FAIL

    @classmethod
    def pass_result(
        cls,
        gate_name: str,
        message: str = "Validation passed",
        **details: Any,
    ) -> ValidationResult:
        """Create a PASS result."""
        return cls(
            gate_name=gate_name,
            status=ValidationStatus.PASS,
            message=message,
            details=details,
        )

    @classmethod
    def warn_result(
        cls,
        gate_name: str,
        message: str,
        **details: Any,
    ) -> ValidationResult:
        """Create a WARN result."""
        return cls(
            gate_name=gate_name,
            status=ValidationStatus.WARN,
            message=message,
            details=details,
        )

    @classmethod
    def fail_result(
        cls,
        gate_name: str,
        message: str,
        **details: Any,
    ) -> ValidationResult:
        """Create a FAIL result."""
        return cls(
            gate_name=gate_name,
            status=ValidationStatus.FAIL,
            message=message,
            details=details,
        )


class GateProtocol(ABC, Generic[T]):
    """Abstract protocol for validation gates."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Gate name for reporting."""
        ...

    @abstractmethod
    def validate(self, data: T) -> ValidationResult:
        """
        Validate data against gate criteria.

        Args:
            data: Data to validate

        Returns:
            ValidationResult with status and details
        """
        ...
