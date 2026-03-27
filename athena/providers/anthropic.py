#!/usr/bin/env python3
"""
Module: Anthropic
Purpose: ATHENA Direct Anthropic API Provider.

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

import os
from datetime import datetime

from athena.providers.base import LLMResponse

# Pricing per 1M tokens (as of Dec 2024)
ANTHROPIC_PRICING = {
    "claude-3-5-haiku-20241022": {"input": 1.00, "output": 5.00},
    "claude-3-5-sonnet-20241022": {"input": 3.00, "output": 15.00},
    "claude-sonnet-4-5-20250929": {"input": 3.00, "output": 15.00},
}


class AnthropicProvider:
    """Direct Anthropic API provider.

    Uses the standard Anthropic API with your API key.
    """

    def __init__(self, api_key: str | None = None):
        """Initialize Anthropic provider.

        Args:
            api_key: Anthropic API key (defaults to ANTHROPIC_API_KEY env var)
        """
        import anthropic

        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not self.api_key:
            raise ValueError("ANTHROPIC_API_KEY not set")

        self.client = anthropic.Anthropic(api_key=self.api_key)

        # Model mapping
        self.models = {
            "triage": "claude-3-5-haiku-20241022",
            "extract": "claude-3-5-sonnet-20241022",
        }

    async def complete_vision(
        self,
        images: list[str],
        system_prompt: str,
        user_prompt: str,
        max_tokens: int = 4096,
        model_key: str = "extract",
    ) -> LLMResponse:
        """Complete a vision request with images.

        Args:
            images: List of base64-encoded PNG images
            system_prompt: System prompt
            user_prompt: User prompt
            max_tokens: Maximum response tokens
            model_key: "triage" or "extract"

        Returns:
            LLMResponse with content and metadata
        """
        start = datetime.utcnow()

        # Build content with images
        content = []
        for img in images:
            content.append(
                {
                    "type": "image",
                    "source": {"type": "base64", "media_type": "image/png", "data": img},
                }
            )
        content.append({"type": "text", "text": user_prompt})

        model = self.models.get(model_key, self.models["extract"])

        response = self.client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=system_prompt,
            messages=[{"role": "user", "content": content}],
            timeout=120,
        )

        latency_ms = int((datetime.utcnow() - start).total_seconds() * 1000)
        cost = self._calculate_cost(
            model, response.usage.input_tokens, response.usage.output_tokens
        )

        return LLMResponse(
            content=response.content[0].text,
            tokens_in=response.usage.input_tokens,
            tokens_out=response.usage.output_tokens,
            model=model,
            latency_ms=latency_ms,
            cost_usd=cost,
        )

    async def complete_text(
        self,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int = 4096,
        model_key: str = "extract",
    ) -> LLMResponse:
        """Complete a text-only request.

        Args:
            system_prompt: System prompt
            user_prompt: User prompt
            max_tokens: Maximum response tokens
            model_key: "triage" or "extract"

        Returns:
            LLMResponse with content and metadata
        """
        start = datetime.utcnow()

        model = self.models.get(model_key, self.models["extract"])

        response = self.client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=system_prompt,
            messages=[{"role": "user", "content": [{"type": "text", "text": user_prompt}]}],
            timeout=120,
        )

        latency_ms = int((datetime.utcnow() - start).total_seconds() * 1000)
        cost = self._calculate_cost(
            model, response.usage.input_tokens, response.usage.output_tokens
        )

        return LLMResponse(
            content=response.content[0].text,
            tokens_in=response.usage.input_tokens,
            tokens_out=response.usage.output_tokens,
            model=model,
            latency_ms=latency_ms,
            cost_usd=cost,
        )

    def _calculate_cost(self, model: str, input_tokens: int, output_tokens: int) -> float:
        """Calculate cost based on token usage."""
        pricing = ANTHROPIC_PRICING.get(model, {"input": 3.0, "output": 15.0})
        input_cost = (input_tokens / 1_000_000) * pricing["input"]
        output_cost = (output_tokens / 1_000_000) * pricing["output"]
        return input_cost + output_cost
