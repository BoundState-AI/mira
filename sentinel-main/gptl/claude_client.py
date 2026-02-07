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
GPTL Claude Client - Unified Claude API wrapper for all GPTL layers
====================================================================

Provides a consistent interface for calling Claude models across all GPTL layers:
- L0: Haiku for feature extraction and derivation validation
- L2: Sonnet/Opus for intent classification
- L3: Haiku for semantic constraint checks
- L4: Sonnet for anomaly explanation
- L5: Sonnet/Opus for synthesis

Features:
- Model tier abstraction (haiku, sonnet, opus)
- Automatic JSON parsing with retry
- Latency and token tracking
- Escalation support
- Error handling with fallback

Compliance: SWE-032 (Data Validation), SWE-033 (Requirements Traceability)
Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI
"""

from __future__ import annotations

import json
import logging
import os
import random
import re
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Generic, Protocol, TypeVar

T = TypeVar("T")

from gptl.schema import ModelCall, ModelTier
from gptl.exceptions import (
    RateLimitError as GPTLRateLimitError,
    ConnectionError as GPTLConnectionError,
    TimeoutError as GPTLTimeoutError,
    ClientError,
    AuthenticationError,
    ServiceUnavailableError,
    TransientError,
)

__safety_critical__: bool = True

logger = logging.getLogger(__name__)

T = TypeVar("T")


# =============================================================================
# MODEL ID MAPPING
# =============================================================================

MODEL_IDS: dict[ModelTier, str] = {
    ModelTier.HAIKU: "claude-3-5-haiku-20241022",
    ModelTier.SONNET: "claude-sonnet-4-20250514",
    ModelTier.OPUS: "claude-opus-4-0-20250514",
}

# Fallback model IDs if primary not available
MODEL_ID_FALLBACKS: dict[ModelTier, list[str]] = {
    ModelTier.HAIKU: ["claude-3-haiku-20240307"],
    ModelTier.SONNET: ["claude-3-5-sonnet-20241022", "claude-3-sonnet-20240229"],
    ModelTier.OPUS: ["claude-3-opus-20240229"],
}


def get_model_id(tier: ModelTier) -> str:
    """Get the model ID for a tier."""
    return MODEL_IDS.get(tier, MODEL_IDS[ModelTier.SONNET])


# =============================================================================
# RESPONSE TYPES
# =============================================================================

@dataclass
class ClaudeResponse:
    """Response from a Claude API call."""
    content: str
    model_id: str
    tier: ModelTier
    tokens_in: int
    tokens_out: int
    latency_ms: int
    stop_reason: str
    raw_response: Any = None


@dataclass
class ParsedResponse(Generic[T]):
    """Response with parsed JSON content."""
    data: T
    raw: ClaudeResponse
    parse_success: bool = True
    parse_error: str | None = None


# =============================================================================
# RETRY POLICY
# =============================================================================

@dataclass
class RetryPolicy:
    """Configuration for retry behavior on transient errors.

    Uses exponential backoff with jitter:
        delay = min(max_delay_ms, base_delay_ms * (2 ** attempt)) + jitter

    Attributes:
        max_retries: Maximum number of retry attempts (default 3)
        base_delay_ms: Initial delay before first retry (default 1000ms)
        max_delay_ms: Maximum delay cap (default 30000ms)
        jitter: Whether to add random jitter (default True)
        retry_on_timeout: Whether to retry on timeout errors (default False)
    """
    max_retries: int = 3
    base_delay_ms: int = 1000
    max_delay_ms: int = 30000
    jitter: bool = True
    retry_on_timeout: bool = False

    def calculate_delay(self, attempt: int, retry_after_ms: int | None = None) -> int:
        """Calculate delay for a given retry attempt.

        Args:
            attempt: The retry attempt number (0-indexed)
            retry_after_ms: Server-suggested retry delay (takes precedence)

        Returns:
            Delay in milliseconds
        """
        if retry_after_ms is not None:
            delay = retry_after_ms
        else:
            delay = min(
                self.max_delay_ms,
                self.base_delay_ms * (2 ** attempt)
            )

        if self.jitter:
            # Add up to 25% jitter
            jitter_amount = int(delay * 0.25 * random.random())
            delay += jitter_amount

        return delay


# Default retry policy
DEFAULT_RETRY_POLICY = RetryPolicy()


# =============================================================================
# CLAUDE CLIENT PROTOCOL (Interface Segregation)
# =============================================================================

class ClaudeClientProtocol(Protocol):
    """Protocol for Claude API clients."""

    def call(
        self,
        prompt: str,
        tier: ModelTier,
        system: str | None = None,
        temperature: float = 0.0,
        max_tokens: int = 4096,
    ) -> ClaudeResponse:
        """Make a Claude API call."""
        ...

    def call_json(
        self,
        prompt: str,
        tier: ModelTier,
        system: str | None = None,
        temperature: float = 0.0,
        max_tokens: int = 4096,
        retry_on_parse_error: bool = True,
    ) -> ParsedResponse[dict[str, Any]]:
        """Make a Claude API call expecting JSON response."""
        ...


# =============================================================================
# BASE CLIENT (Template Method Pattern)
# =============================================================================

class BaseClaudeClient(ABC):
    """
    Base class for Claude API clients.

    Implements common logic with template method pattern.
    Subclasses implement the actual API call.
    """

    def __init__(self, default_temperature: float = 0.0):
        self.default_temperature = default_temperature
        self._call_count = 0
        self._total_tokens_in = 0
        self._total_tokens_out = 0
        self._total_latency_ms = 0

    @abstractmethod
    def _make_api_call(
        self,
        prompt: str,
        model_id: str,
        system: str | None,
        temperature: float,
        max_tokens: int,
    ) -> ClaudeResponse:
        """Make the actual API call. Implemented by subclasses."""
        pass

    def call(
        self,
        prompt: str,
        tier: ModelTier,
        system: str | None = None,
        temperature: float | None = None,
        max_tokens: int = 4096,
    ) -> ClaudeResponse:
        """
        Make a Claude API call.

        Args:
            prompt: The user prompt
            tier: Model tier (haiku, sonnet, opus)
            system: Optional system prompt
            temperature: Temperature (default 0.0 for determinism)
            max_tokens: Maximum output tokens

        Returns:
            ClaudeResponse with content and metadata
        """
        if temperature is None:
            temperature = self.default_temperature

        model_id = get_model_id(tier)

        start_time = time.perf_counter()
        response = self._make_api_call(prompt, model_id, system, temperature, max_tokens)
        latency_ms = int((time.perf_counter() - start_time) * 1000)

        # Update response with actual latency
        response.latency_ms = latency_ms
        response.tier = tier

        # Track stats
        self._call_count += 1
        self._total_tokens_in += response.tokens_in
        self._total_tokens_out += response.tokens_out
        self._total_latency_ms += latency_ms

        logger.debug(
            f"Claude {tier.value} call: {response.tokens_in}+{response.tokens_out} tokens, "
            f"{latency_ms}ms"
        )

        return response

    def call_json(
        self,
        prompt: str,
        tier: ModelTier,
        system: str | None = None,
        temperature: float | None = None,
        max_tokens: int = 4096,
        retry_on_parse_error: bool = True,
    ) -> ParsedResponse[dict[str, Any]]:
        """
        Make a Claude API call expecting JSON response.

        Automatically extracts and parses JSON from the response.
        Optionally retries with a clarification prompt on parse error.

        Args:
            prompt: The user prompt (should request JSON output)
            tier: Model tier
            system: Optional system prompt
            temperature: Temperature
            max_tokens: Maximum output tokens
            retry_on_parse_error: Whether to retry on JSON parse failure

        Returns:
            ParsedResponse with parsed dict and metadata
        """
        response = self.call(prompt, tier, system, temperature, max_tokens)

        # Try to parse JSON
        data, error = self._extract_json(response.content)

        if data is not None:
            return ParsedResponse(data=data, raw=response)

        # Parse failed
        if retry_on_parse_error:
            logger.warning(f"JSON parse failed, retrying: {error}")
            retry_prompt = (
                f"Your previous response was not valid JSON. Error: {error}\n\n"
                f"Please respond with ONLY valid JSON, no other text.\n\n"
                f"Original request:\n{prompt}"
            )
            response = self.call(retry_prompt, tier, system, temperature, max_tokens)
            data, error = self._extract_json(response.content)

            if data is not None:
                return ParsedResponse(data=data, raw=response)

        # Final failure
        logger.error(f"Failed to parse JSON after retry: {error}")
        return ParsedResponse(
            data={},
            raw=response,
            parse_success=False,
            parse_error=error,
        )

    def _extract_json(self, content: str) -> tuple[dict[str, Any] | None, str | None]:
        """
        Extract JSON from response content.

        Handles various formats:
        - Raw JSON
        - JSON in code blocks
        - JSON with surrounding text
        """
        content = content.strip()

        # Try direct parse
        try:
            return json.loads(content), None
        except json.JSONDecodeError:
            pass

        # Try extracting from code blocks
        code_block_patterns = [
            r"```json\s*([\s\S]*?)\s*```",
            r"```\s*([\s\S]*?)\s*```",
        ]

        for pattern in code_block_patterns:
            match = re.search(pattern, content)
            if match:
                try:
                    return json.loads(match.group(1).strip()), None
                except json.JSONDecodeError:
                    pass

        # Try finding JSON object in content
        brace_start = content.find("{")
        brace_end = content.rfind("}")

        if brace_start != -1 and brace_end != -1 and brace_end > brace_start:
            try:
                return json.loads(content[brace_start:brace_end + 1]), None
            except json.JSONDecodeError as e:
                return None, f"JSON decode error: {e}"

        return None, "No JSON object found in response"

    def create_model_call(
        self,
        response: ClaudeResponse,
        layer: str,
        purpose: str,
        escalated_from: ModelTier | None = None,
    ) -> ModelCall:
        """Create a ModelCall record for audit trail."""
        return ModelCall(
            model=response.tier,
            layer=layer,
            purpose=purpose,
            latency_ms=response.latency_ms,
            tokens_in=response.tokens_in,
            tokens_out=response.tokens_out,
            escalated_from=escalated_from,
        )

    def get_stats(self) -> dict[str, int]:
        """Get accumulated call statistics."""
        return {
            "call_count": self._call_count,
            "total_tokens_in": self._total_tokens_in,
            "total_tokens_out": self._total_tokens_out,
            "total_latency_ms": self._total_latency_ms,
        }

    def reset_stats(self):
        """Reset call statistics."""
        self._call_count = 0
        self._total_tokens_in = 0
        self._total_tokens_out = 0
        self._total_latency_ms = 0


# =============================================================================
# ANTHROPIC SDK CLIENT
# =============================================================================

class AnthropicClaudeClient(BaseClaudeClient):
    """
    Claude client using the Anthropic SDK.

    Includes automatic retry with exponential backoff for transient errors.

    Requires: pip install anthropic
    """

    def __init__(
        self,
        api_key: str | None = None,
        default_temperature: float = 0.0,
        retry_policy: RetryPolicy | None = None,
    ):
        super().__init__(default_temperature)
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        self.retry_policy = retry_policy or DEFAULT_RETRY_POLICY

        if not self.api_key:
            raise ValueError(
                "Anthropic API key required. Set ANTHROPIC_API_KEY env var or pass api_key."
            )

        # Lazy import to avoid hard dependency
        try:
            import anthropic
            self._client = anthropic.Anthropic(api_key=self.api_key)
            self._anthropic = anthropic  # Store module reference for exception types
        except ImportError:
            raise ImportError(
                "anthropic package required. Install with: pip install anthropic"
            )

    def _make_api_call(
        self,
        prompt: str,
        model_id: str,
        system: str | None,
        temperature: float,
        max_tokens: int,
    ) -> ClaudeResponse:
        """Make API call using Anthropic SDK with retry logic."""
        return self._make_api_call_with_retry(
            prompt=prompt,
            model_id=model_id,
            system=system,
            temperature=temperature,
            max_tokens=max_tokens,
        )

    def _make_api_call_with_retry(
        self,
        prompt: str,
        model_id: str,
        system: str | None,
        temperature: float,
        max_tokens: int,
    ) -> ClaudeResponse:
        """Make API call with retry logic for transient errors.

        Handles:
        - Rate limits (429) with exponential backoff
        - Connection errors with retry
        - Timeout errors (no retry by default)
        - Authentication errors (no retry, fail fast)
        """
        messages = [{"role": "user", "content": prompt}]

        kwargs = {
            "model": model_id,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": messages,
        }

        if system:
            kwargs["system"] = system

        last_error: Exception | None = None

        for attempt in range(self.retry_policy.max_retries + 1):
            try:
                response = self._client.messages.create(**kwargs)

                # Extract content
                content = ""
                if response.content:
                    content = response.content[0].text if response.content else ""

                return ClaudeResponse(
                    content=content,
                    model_id=model_id,
                    tier=ModelTier.SONNET,  # Will be overwritten by caller
                    tokens_in=response.usage.input_tokens,
                    tokens_out=response.usage.output_tokens,
                    latency_ms=0,  # Will be set by caller
                    stop_reason=response.stop_reason or "",
                    raw_response=response,
                )

            except self._anthropic.RateLimitError as e:
                last_error = e
                if attempt < self.retry_policy.max_retries:
                    # Extract retry-after header if available
                    retry_after_ms = None
                    if hasattr(e, 'response') and e.response:
                        retry_after = e.response.headers.get('retry-after')
                        if retry_after:
                            try:
                                retry_after_ms = int(float(retry_after) * 1000)
                            except ValueError:
                                pass

                    delay = self.retry_policy.calculate_delay(attempt, retry_after_ms)
                    logger.warning(
                        f"Rate limited, retrying in {delay}ms "
                        f"(attempt {attempt + 1}/{self.retry_policy.max_retries})"
                    )
                    time.sleep(delay / 1000)
                    continue
                else:
                    raise GPTLRateLimitError(
                        f"Rate limit exceeded after {attempt + 1} attempts: {e}",
                        retry_after_ms=retry_after_ms,
                    )

            except self._anthropic.APIConnectionError as e:
                last_error = e
                if attempt < self.retry_policy.max_retries:
                    delay = self.retry_policy.calculate_delay(attempt)
                    logger.warning(
                        f"Connection error, retrying in {delay}ms "
                        f"(attempt {attempt + 1}/{self.retry_policy.max_retries}): {e}"
                    )
                    time.sleep(delay / 1000)
                    continue
                else:
                    raise GPTLConnectionError(
                        f"Connection failed after {attempt + 1} attempts: {e}"
                    )

            except self._anthropic.APITimeoutError as e:
                last_error = e
                if self.retry_policy.retry_on_timeout and attempt < self.retry_policy.max_retries:
                    delay = self.retry_policy.calculate_delay(attempt)
                    logger.warning(
                        f"Request timed out, retrying in {delay}ms "
                        f"(attempt {attempt + 1}/{self.retry_policy.max_retries})"
                    )
                    time.sleep(delay / 1000)
                    continue
                else:
                    raise GPTLTimeoutError(
                        f"Request timed out: {e}",
                        timeout_ms=max_tokens * 10,  # Rough estimate
                    )

            except self._anthropic.AuthenticationError as e:
                # Never retry auth errors
                raise AuthenticationError(
                    f"Authentication failed: {e}",
                    status_code=401,
                )

            except self._anthropic.APIStatusError as e:
                last_error = e
                status_code = e.status_code if hasattr(e, 'status_code') else None

                # 5xx errors may be retryable
                if status_code and 500 <= status_code < 600:
                    if attempt < self.retry_policy.max_retries:
                        delay = self.retry_policy.calculate_delay(attempt)
                        logger.warning(
                            f"Server error ({status_code}), retrying in {delay}ms "
                            f"(attempt {attempt + 1}/{self.retry_policy.max_retries})"
                        )
                        time.sleep(delay / 1000)
                        continue

                if status_code == 503:
                    raise ServiceUnavailableError(
                        f"Service unavailable: {e}",
                        status_code=status_code,
                    )
                else:
                    raise ClientError(
                        f"API error: {e}",
                        status_code=status_code,
                    )

        # Should not reach here, but handle just in case
        if last_error:
            raise ClientError(f"Unexpected error after retries: {last_error}")


# =============================================================================
# MOCK CLIENT FOR TESTING
# =============================================================================

class MockClaudeClient(BaseClaudeClient):
    """
    Mock Claude client for testing.

    Returns predefined responses based on patterns in the prompt.
    """

    def __init__(
        self,
        default_responses: dict[str, str] | None = None,
        default_temperature: float = 0.0,
    ):
        super().__init__(default_temperature)
        self.default_responses = default_responses or {}
        self.call_history: list[dict[str, Any]] = []

    def add_response(self, pattern: str, response: str):
        """Add a pattern-response mapping."""
        self.default_responses[pattern] = response

    def _make_api_call(
        self,
        prompt: str,
        model_id: str,
        system: str | None,
        temperature: float,
        max_tokens: int,
    ) -> ClaudeResponse:
        """Return mock response."""
        # Record call
        self.call_history.append({
            "prompt": prompt,
            "model_id": model_id,
            "system": system,
            "temperature": temperature,
            "max_tokens": max_tokens,
        })

        # Find matching response
        content = '{"error": "no mock response configured"}'

        for pattern, response in self.default_responses.items():
            if pattern.lower() in prompt.lower():
                content = response
                break

        # Simulate token counts
        tokens_in = len(prompt.split()) * 2  # Rough estimate
        tokens_out = len(content.split()) * 2

        return ClaudeResponse(
            content=content,
            model_id=model_id,
            tier=ModelTier.SONNET,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            latency_ms=50,  # Simulated latency
            stop_reason="end_turn",
            raw_response=None,
        )


# =============================================================================
# CLIENT FACTORY
# =============================================================================

_default_client: BaseClaudeClient | None = None


def get_client(
    client_type: str = "anthropic",
    api_key: str | None = None,
    **kwargs,
) -> BaseClaudeClient:
    """
    Get a Claude client instance.

    Args:
        client_type: "anthropic" or "mock"
        api_key: API key for Anthropic client
        **kwargs: Additional client arguments

    Returns:
        Claude client instance
    """
    global _default_client

    if client_type == "anthropic":
        return AnthropicClaudeClient(api_key=api_key, **kwargs)
    elif client_type == "mock":
        return MockClaudeClient(**kwargs)
    else:
        raise ValueError(f"Unknown client type: {client_type}")


def set_default_client(client: BaseClaudeClient):
    """Set the default Claude client."""
    global _default_client
    _default_client = client


def get_default_client() -> BaseClaudeClient:
    """
    Get the default Claude client.

    Creates an Anthropic client if none is set.
    """
    global _default_client

    if _default_client is None:
        try:
            _default_client = AnthropicClaudeClient()
        except (ValueError, ImportError) as e:
            logger.warning(f"Could not create Anthropic client: {e}")
            logger.warning("Using mock client as fallback")
            _default_client = MockClaudeClient()

    return _default_client


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================

def call_haiku(
    prompt: str,
    system: str | None = None,
    client: BaseClaudeClient | None = None,
) -> ClaudeResponse:
    """Convenience function for Haiku calls."""
    client = client or get_default_client()
    return client.call(prompt, ModelTier.HAIKU, system)


def call_sonnet(
    prompt: str,
    system: str | None = None,
    client: BaseClaudeClient | None = None,
) -> ClaudeResponse:
    """Convenience function for Sonnet calls."""
    client = client or get_default_client()
    return client.call(prompt, ModelTier.SONNET, system)


def call_opus(
    prompt: str,
    system: str | None = None,
    client: BaseClaudeClient | None = None,
) -> ClaudeResponse:
    """Convenience function for Opus calls."""
    client = client or get_default_client()
    return client.call(prompt, ModelTier.OPUS, system)


def call_haiku_json(
    prompt: str,
    system: str | None = None,
    client: BaseClaudeClient | None = None,
) -> ParsedResponse[dict[str, Any]]:
    """Convenience function for Haiku JSON calls."""
    client = client or get_default_client()
    return client.call_json(prompt, ModelTier.HAIKU, system)


def call_sonnet_json(
    prompt: str,
    system: str | None = None,
    client: BaseClaudeClient | None = None,
) -> ParsedResponse[dict[str, Any]]:
    """Convenience function for Sonnet JSON calls."""
    client = client or get_default_client()
    return client.call_json(prompt, ModelTier.SONNET, system)


__all__ = [
    # Types
    "ClaudeResponse",
    "ParsedResponse",
    "ClaudeClientProtocol",

    # Retry policy
    "RetryPolicy",
    "DEFAULT_RETRY_POLICY",

    # Clients
    "BaseClaudeClient",
    "AnthropicClaudeClient",
    "MockClaudeClient",

    # Model mapping
    "MODEL_IDS",
    "get_model_id",

    # Factory
    "get_client",
    "set_default_client",
    "get_default_client",

    # Convenience functions
    "call_haiku",
    "call_sonnet",
    "call_opus",
    "call_haiku_json",
    "call_sonnet_json",
]
