# Copyright 2025 BoundStateAI
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
GPTL Exception Hierarchy
========================

Structured exception types for proper error handling and recovery.

Philosophy:
    "Errors should be specific, actionable, and recoverable where possible"

Categories:
- TransientError: Safe to retry with backoff
- ConfigurationError: Fatal - fail fast
- ValidationError: Log and continue with fallback
- ClientError: API communication issues

Compliance: SWE-032, SWE-033
Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI
"""

from __future__ import annotations

__safety_critical__: bool = True


# =============================================================================
# BASE EXCEPTION
# =============================================================================

class GPTLError(Exception):
    """Base exception for all GPTL errors.

    All GPTL exceptions inherit from this class for unified catching.
    """

    def __init__(self, message: str, *, details: dict | None = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}


# =============================================================================
# TRANSIENT ERRORS (Retry-able)
# =============================================================================

class TransientError(GPTLError):
    """Transient error - safe to retry with backoff.

    These errors are expected to resolve on retry:
    - Network glitches
    - Rate limits
    - Temporary service unavailability
    """
    pass


class RateLimitError(TransientError):
    """Rate limit hit - retry with exponential backoff.

    Attributes:
        retry_after_ms: Suggested wait time before retry (if provided by API)
    """

    def __init__(
        self,
        message: str,
        *,
        retry_after_ms: int | None = None,
        details: dict | None = None,
    ):
        super().__init__(message, details=details)
        self.retry_after_ms = retry_after_ms


class ConnectionError(TransientError):
    """Network connection error - safe to retry.

    Covers:
    - DNS resolution failures
    - Connection refused
    - Connection reset
    """
    pass


class TimeoutError(TransientError):
    """Request timed out - may be safe to retry.

    Note: Be cautious with retrying timeouts as the request
    may have been processed by the server.
    """

    def __init__(
        self,
        message: str,
        *,
        timeout_ms: int | None = None,
        details: dict | None = None,
    ):
        super().__init__(message, details=details)
        self.timeout_ms = timeout_ms


# =============================================================================
# CONFIGURATION ERRORS (Fatal)
# =============================================================================

class ConfigurationError(GPTLError):
    """Configuration error - fatal, do not retry.

    Indicates misconfiguration that cannot be fixed at runtime:
    - Invalid API keys
    - Missing required configuration
    - Invalid model specification
    """
    pass


class DomainPackError(ConfigurationError):
    """Error in domain pack configuration.

    Covers:
    - Invalid intent frames
    - Malformed constraint rules
    - Missing required fields
    """
    pass


# =============================================================================
# VALIDATION ERRORS (Log and Continue)
# =============================================================================

class ValidationError(GPTLError):
    """Validation failed - log and use fallback.

    These errors indicate data quality issues:
    - Malformed LLM responses
    - Schema validation failures
    - Missing expected fields
    """
    pass


class ResponseParseError(ValidationError):
    """Failed to parse LLM response.

    Attributes:
        raw_response: The unparseable response text
        expected_format: What format was expected (e.g., "json")
    """

    def __init__(
        self,
        message: str,
        *,
        raw_response: str | None = None,
        expected_format: str | None = None,
        details: dict | None = None,
    ):
        super().__init__(message, details=details)
        self.raw_response = raw_response
        self.expected_format = expected_format


class SchemaValidationError(ValidationError):
    """Response doesn't match expected schema.

    Attributes:
        field: The field that failed validation
        expected: Expected value/type
        actual: Actual value received
    """

    def __init__(
        self,
        message: str,
        *,
        field: str | None = None,
        expected: str | None = None,
        actual: str | None = None,
        details: dict | None = None,
    ):
        super().__init__(message, details=details)
        self.field = field
        self.expected = expected
        self.actual = actual


# =============================================================================
# CLIENT ERRORS (API Issues)
# =============================================================================

class ClientError(GPTLError):
    """API client error - check service status.

    Covers HTTP 4xx/5xx errors from the API.
    """

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        details: dict | None = None,
    ):
        super().__init__(message, details=details)
        self.status_code = status_code


class AuthenticationError(ClientError):
    """Authentication failed - check API key.

    HTTP 401/403 errors.
    """
    pass


class ServiceUnavailableError(ClientError):
    """Service temporarily unavailable.

    HTTP 503 or circuit breaker open.
    """
    pass


# =============================================================================
# PIPELINE ERRORS
# =============================================================================

class PipelineError(GPTLError):
    """Error in pipeline execution."""

    def __init__(
        self,
        message: str,
        *,
        stage: str | None = None,
        details: dict | None = None,
    ):
        super().__init__(message, details=details)
        self.stage = stage


class InsufficientEvidenceError(PipelineError):
    """Not enough evidence to synthesize answer.

    This is a normal outcome when evidence is lacking,
    not necessarily an error condition.
    """

    def __init__(
        self,
        message: str,
        *,
        evidence_count: int = 0,
        min_required: int = 2,
        details: dict | None = None,
    ):
        super().__init__(message, stage="L5_synthesis", details=details)
        self.evidence_count = evidence_count
        self.min_required = min_required


class StageFailedError(PipelineError):
    """A pipeline stage failed after retries.

    Attributes:
        attempts: Number of retry attempts made
        last_error: The final error that caused failure
    """

    def __init__(
        self,
        message: str,
        *,
        stage: str | None = None,
        attempts: int = 1,
        last_error: Exception | None = None,
        details: dict | None = None,
    ):
        super().__init__(message, stage=stage, details=details)
        self.attempts = attempts
        self.last_error = last_error


# =============================================================================
# EXPORTS
# =============================================================================

__all__ = [
    # Base
    "GPTLError",
    # Transient (retry-able)
    "TransientError",
    "RateLimitError",
    "ConnectionError",
    "TimeoutError",
    # Configuration (fatal)
    "ConfigurationError",
    "DomainPackError",
    # Validation (log and continue)
    "ValidationError",
    "ResponseParseError",
    "SchemaValidationError",
    # Client (API issues)
    "ClientError",
    "AuthenticationError",
    "ServiceUnavailableError",
    # Pipeline
    "PipelineError",
    "InsufficientEvidenceError",
    "StageFailedError",
]
