#!/usr/bin/env python3
"""
Module: Bedrock
Purpose: ATHENA AWS Bedrock LLM Provider.

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

from datetime import datetime

from athena.models.cost import BEDROCK_PRICING
from athena.providers.base import LLMResponse


class BedrockProvider:
    """AWS Bedrock provider for GovCloud deployments.

    Supports:
    - Claude 3.5 Haiku for triage (fast, cheap)
    - Claude Sonnet 4.5 for extraction (capable, accurate)
    """

    def __init__(self, region: str = "us-gov-west-1"):
        """Initialize Bedrock provider.

        Args:
            region: AWS region (default: us-gov-west-1 for GovCloud)
        """
        import anthropic

        self.client = anthropic.AnthropicBedrock(aws_region=region)
        self.region = region

        # Model IDs based on region
        if region.startswith("us-gov"):
            self.models = {
                "triage": "us-gov.anthropic.claude-3-5-haiku-20241022-v1:0",
                "extract": "us-gov.anthropic.claude-sonnet-4-5-20250929-v1:0",
            }
        else:
            self.models = {
                "triage": "us.anthropic.claude-3-5-haiku-20241022-v1:0",
                "extract": "us.anthropic.claude-sonnet-4-5-20250929-v1:0",
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
            messages=[{"role": "user", "content": user_prompt}],
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

    def _calculate_cost(self, model: str, tokens_in: int, tokens_out: int) -> float:
        """Calculate cost for a request.

        Args:
            model: Model ID
            tokens_in: Input tokens
            tokens_out: Output tokens

        Returns:
            Cost in USD
        """
        pricing = BEDROCK_PRICING.get(model, (0.003, 0.015))
        cost = (tokens_in * pricing[0] + tokens_out * pricing[1]) / 1000
        return round(cost, 6)


class AnthropicProvider:
    """Commercial Anthropic API provider.

    For non-GovCloud deployments where FedRAMP is not required.
    """

    def __init__(self, api_key: str | None = None):
        """Initialize Anthropic provider.

        Args:
            api_key: API key (or uses ANTHROPIC_API_KEY env var)
        """
        import anthropic

        self.client = anthropic.Anthropic(api_key=api_key)
        self.models = {
            "triage": "claude-3-5-haiku-20241022",
            "extract": "claude-sonnet-4-5-20250929",
        }

    async def complete_vision(
        self,
        images: list[str],
        system_prompt: str,
        user_prompt: str,
        max_tokens: int = 4096,
        model_key: str = "extract",
    ) -> LLMResponse:
        """Complete a vision request with images."""
        start = datetime.utcnow()

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
        )

        latency_ms = int((datetime.utcnow() - start).total_seconds() * 1000)

        # Anthropic pricing (slightly different from Bedrock)
        if "haiku" in model:
            pricing = (0.00025, 0.00125)
        else:
            pricing = (0.003, 0.015)

        cost = (response.usage.input_tokens * pricing[0] + response.usage.output_tokens * pricing[1]) / 1000

        return LLMResponse(
            content=response.content[0].text,
            tokens_in=response.usage.input_tokens,
            tokens_out=response.usage.output_tokens,
            model=model,
            latency_ms=latency_ms,
            cost_usd=round(cost, 6),
        )

    async def complete_text(
        self,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int = 4096,
        model_key: str = "extract",
    ) -> LLMResponse:
        """Complete a text-only request."""
        start = datetime.utcnow()

        model = self.models.get(model_key, self.models["extract"])

        response = self.client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )

        latency_ms = int((datetime.utcnow() - start).total_seconds() * 1000)

        if "haiku" in model:
            pricing = (0.00025, 0.00125)
        else:
            pricing = (0.003, 0.015)

        cost = (response.usage.input_tokens * pricing[0] + response.usage.output_tokens * pricing[1]) / 1000

        return LLMResponse(
            content=response.content[0].text,
            tokens_in=response.usage.input_tokens,
            tokens_out=response.usage.output_tokens,
            model=model,
            latency_ms=latency_ms,
            cost_usd=round(cost, 6),
        )
