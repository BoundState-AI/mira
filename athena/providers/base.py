#!/usr/bin/env python3
"""
Module: Base
Purpose: ATHENA LLM Provider Base Interface.

BoundState AI 2025
Version: 1.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Fran OpenAI 5 <noreply@openai.com>
Co-Authored-By: Grok 4.0 <noreply@x.ai>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: SWE-013, NASA-STD-8739.8B
Safety Critical: False
"""

from typing import Protocol

from pydantic import BaseModel


class LLMResponse(BaseModel):
    """Response from LLM provider."""

    content: str
    tokens_in: int
    tokens_out: int
    model: str
    latency_ms: int
    cost_usd: float


class LLMProvider(Protocol):
    """Abstract interface for LLM providers.

    Implementations:
    - BedrockProvider: AWS Bedrock (GovCloud)
    - AnthropicProvider: Commercial Anthropic API
    - LocalProvider: On-prem model server
    """

    async def complete_vision(
        self,
        images: list[str],  # Base64 PNGs
        system_prompt: str,
        user_prompt: str,
        max_tokens: int = 4096,
        model_key: str = "extract",
    ) -> LLMResponse:
        """Complete a vision request.

        Args:
            images: List of base64-encoded PNG images
            system_prompt: System prompt for the model
            user_prompt: User prompt for the model
            max_tokens: Maximum tokens in response
            model_key: Which model to use ("triage" or "extract")

        Returns:
            LLMResponse with content and metadata
        """
        ...

    async def complete_text(
        self,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int = 4096,
        model_key: str = "extract",
    ) -> LLMResponse:
        """Complete a text-only request.

        Args:
            system_prompt: System prompt for the model
            user_prompt: User prompt for the model
            max_tokens: Maximum tokens in response
            model_key: Which model to use

        Returns:
            LLMResponse with content and metadata
        """
        ...
