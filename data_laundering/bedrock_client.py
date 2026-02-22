#!/usr/bin/env python3
"""
Module: LLM Client Wrapper
Purpose: Async LLM client supporting local API and AWS Bedrock (GovCloud).

BoundState AI 2026
Version: 1.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Claude "CC" <noreply@anthropic.com>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: NASA-STD-8739.8B, SWE-013, SWE-033
Safety Critical: True

Current mode: LOCAL API — hits a local LLM endpoint for Layer 1 testing.
GovCloud Bedrock integration is stubbed for deployment.

When we deploy to GovCloud, uncomment the Bedrock sections and pipe in
the fat models:
  - Layer 1 (Sanitize): meta.llama3-70b-instruct-v1:0
  - Layer 2 (Reason):   anthropic.claude-sonnet-4-5-20250929-v1:0
  - Layer 3 (Validate): N/A (database, not LLM)
  - Layer 4 (Present):  anthropic.claude-3-haiku-20240307-v1:0

Spec Reference: BS-DL-ARCH-001
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional

import httpx

logger = logging.getLogger(__name__)


# =============================================================================
# Response Model
# =============================================================================


@dataclass
class LLMResponse:
    """Wrapper for LLM API response with metadata."""
    text: str
    model: str
    input_tokens: int
    output_tokens: int
    latency_ms: float
    raw_response: Optional[Dict[str, Any]] = None


# =============================================================================
# LLM Client
# =============================================================================


class LLMClient:
    """Async LLM client with local API and Bedrock support.

    Current mode: LOCAL API for Layer 1 testing.
    GovCloud Bedrock is stubbed for future deployment.

    Usage::

        client = LLMClient(base_url="http://localhost:11434")
        response = await client.invoke_local(
            prompt="Parse this query...",
            system="You are a query parser.",
            model="llama3",
        )
    """

    # GovCloud Bedrock model IDs (for future deployment)
    BEDROCK_LLAMA = "meta.llama3-70b-instruct-v1:0"
    BEDROCK_SONNET = "anthropic.claude-sonnet-4-5-20250929-v1:0"
    BEDROCK_HAIKU = "anthropic.claude-3-haiku-20240307-v1:0"
    BEDROCK_REGION = "us-gov-west-1"

    def __init__(
        self,
        base_url: str = "http://localhost:11434",
        api_format: str = "ollama",
        timeout: float = 120.0,
    ) -> None:
        """Initialize LLM client.

        Args:
            base_url: Local LLM API endpoint.
            api_format: API format — "ollama" or "openai" compatible.
            timeout: Request timeout in seconds.
        """
        self.base_url = base_url.rstrip("/")
        self.api_format = api_format
        self.timeout = timeout
        self._client = httpx.AsyncClient(timeout=timeout)

        logger.info(
            "LLMClient initialized: base_url=%s, format=%s, timeout=%.0fs",
            self.base_url, self.api_format, self.timeout,
        )

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        await self._client.aclose()

    # =========================================================================
    # Local LLM API
    # =========================================================================

    async def invoke_local(
        self,
        prompt: str,
        system: str,
        model: str = "llama3",
        max_tokens: int = 2048,
        temperature: float = 0.0,
    ) -> LLMResponse:
        """Call a local LLM API (Ollama or OpenAI-compatible).

        Args:
            prompt: User prompt text.
            system: System prompt text.
            model: Model name for the local API.
            max_tokens: Maximum output tokens.
            temperature: Sampling temperature.

        Returns:
            LLMResponse with the generated text and metadata.

        Raises:
            LLMError: If the API call fails.
        """
        start_time = time.perf_counter()

        if self.api_format == "ollama":
            response = await self._call_ollama(
                prompt, system, model, max_tokens, temperature
            )
        elif self.api_format == "openai":
            response = await self._call_openai_compatible(
                prompt, system, model, max_tokens, temperature
            )
        else:
            raise LLMError(f"Unknown API format: {self.api_format}")

        elapsed_ms = (time.perf_counter() - start_time) * 1000
        response.latency_ms = elapsed_ms

        logger.info(
            "LLM call completed: model=%s, tokens=%d/%d, latency=%.0fms",
            response.model, response.input_tokens,
            response.output_tokens, elapsed_ms,
        )

        return response

    async def _call_ollama(
        self,
        prompt: str,
        system: str,
        model: str,
        max_tokens: int,
        temperature: float,
    ) -> LLMResponse:
        """Call Ollama API at /api/chat."""
        url = f"{self.base_url}/api/chat"
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            "stream": False,
            "options": {
                "num_predict": max_tokens,
                "temperature": temperature,
            },
        }

        try:
            resp = await self._client.post(url, json=payload)
            resp.raise_for_status()
            data = resp.json()
        except httpx.HTTPStatusError as exc:
            raise LLMError(
                f"Ollama API error {exc.response.status_code}: "
                f"{exc.response.text}"
            ) from exc
        except httpx.RequestError as exc:
            raise LLMError(
                f"Ollama connection error: {exc}"
            ) from exc

        message = data.get("message", {})
        text = message.get("content", "")

        # Ollama provides token counts in eval_count / prompt_eval_count
        return LLMResponse(
            text=text,
            model=model,
            input_tokens=data.get("prompt_eval_count", 0),
            output_tokens=data.get("eval_count", 0),
            latency_ms=0.0,
            raw_response=data,
        )

    async def _call_openai_compatible(
        self,
        prompt: str,
        system: str,
        model: str,
        max_tokens: int,
        temperature: float,
    ) -> LLMResponse:
        """Call OpenAI-compatible API at /v1/chat/completions."""
        url = f"{self.base_url}/v1/chat/completions"
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            "max_tokens": max_tokens,
            "temperature": temperature,
        }

        try:
            resp = await self._client.post(url, json=payload)
            resp.raise_for_status()
            data = resp.json()
        except httpx.HTTPStatusError as exc:
            raise LLMError(
                f"OpenAI-compatible API error {exc.response.status_code}: "
                f"{exc.response.text}"
            ) from exc
        except httpx.RequestError as exc:
            raise LLMError(
                f"OpenAI-compatible connection error: {exc}"
            ) from exc

        choices = data.get("choices", [])
        text = choices[0]["message"]["content"] if choices else ""
        usage = data.get("usage", {})

        return LLMResponse(
            text=text,
            model=model,
            input_tokens=usage.get("prompt_tokens", 0),
            output_tokens=usage.get("completion_tokens", 0),
            latency_ms=0.0,
            raw_response=data,
        )

    # =========================================================================
    # Convenience Methods (Layer-Specific)
    # =========================================================================

    async def invoke_sanitizer(
        self,
        prompt: str,
        system: str,
        model: str = "llama3",
        max_tokens: int = 2048,
    ) -> LLMResponse:
        """Layer 1: Sanitize raw input via local LLM.

        Temperature is ALWAYS 0.0 for deterministic parsing.
        """
        return await self.invoke_local(
            prompt=prompt, system=system, model=model,
            max_tokens=max_tokens, temperature=0.0,
        )

    async def invoke_reasoner(
        self,
        prompt: str,
        system: str,
        model: str = "llama3",
        max_tokens: int = 4096,
        temperature: float = 0.3,
    ) -> LLMResponse:
        """Layer 2: Reason about candidates.

        In production, this uses Sonnet on Bedrock.
        For local testing, uses the local LLM.
        """
        return await self.invoke_local(
            prompt=prompt, system=system, model=model,
            max_tokens=max_tokens, temperature=temperature,
        )

    async def invoke_presenter(
        self,
        prompt: str,
        system: str,
        model: str = "llama3",
        max_tokens: int = 2048,
    ) -> LLMResponse:
        """Layer 4: Present validated results.

        In production, this uses Haiku on Bedrock.
        For local testing, uses the local LLM.
        """
        return await self.invoke_local(
            prompt=prompt, system=system, model=model,
            max_tokens=max_tokens, temperature=0.1,
        )

    # =========================================================================
    # Bedrock (STUBBED — uncomment for GovCloud deployment)
    # =========================================================================

    # async def invoke_bedrock_llama(
    #     self,
    #     prompt: str,
    #     system: str,
    #     max_tokens: int = 2048,
    # ) -> LLMResponse:
    #     """Call Llama 70B on Bedrock for Layer 1 sanitization.
    #
    #     Model: meta.llama3-70b-instruct-v1:0
    #     Region: us-gov-west-1
    #     """
    #     import aioboto3
    #     session = aioboto3.Session()
    #     async with session.client(
    #         "bedrock-runtime", region_name=self.BEDROCK_REGION
    #     ) as client:
    #         body = json.dumps({
    #             "prompt": f"<|begin_of_text|><|start_header_id|>system<|end_header_id|>\n\n{system}<|eot_id|><|start_header_id|>user<|end_header_id|>\n\n{prompt}<|eot_id|><|start_header_id|>assistant<|end_header_id|>\n\n",
    #             "max_gen_len": max_tokens,
    #             "temperature": 0.0,
    #         })
    #         start = time.perf_counter()
    #         resp = await client.invoke_model(
    #             modelId=self.BEDROCK_LLAMA,
    #             body=body,
    #             contentType="application/json",
    #             accept="application/json",
    #         )
    #         raw = json.loads(await resp["body"].read())
    #         elapsed = (time.perf_counter() - start) * 1000
    #         return LLMResponse(
    #             text=raw.get("generation", ""),
    #             model=self.BEDROCK_LLAMA,
    #             input_tokens=raw.get("prompt_token_count", 0),
    #             output_tokens=raw.get("generation_token_count", 0),
    #             latency_ms=elapsed,
    #             raw_response=raw,
    #         )

    # async def invoke_bedrock_sonnet(
    #     self,
    #     prompt: str,
    #     system: str,
    #     max_tokens: int = 4096,
    #     temperature: float = 0.3,
    # ) -> LLMResponse:
    #     """Call Sonnet on Bedrock for Layer 2 reasoning.
    #
    #     Model: anthropic.claude-sonnet-4-5-20250929-v1:0
    #     Region: us-gov-west-1
    #     """
    #     import aioboto3
    #     session = aioboto3.Session()
    #     async with session.client(
    #         "bedrock-runtime", region_name=self.BEDROCK_REGION
    #     ) as client:
    #         body = json.dumps({
    #             "anthropic_version": "bedrock-2023-05-31",
    #             "max_tokens": max_tokens,
    #             "temperature": temperature,
    #             "system": system,
    #             "messages": [{"role": "user", "content": prompt}],
    #         })
    #         start = time.perf_counter()
    #         resp = await client.invoke_model(
    #             modelId=self.BEDROCK_SONNET,
    #             body=body,
    #             contentType="application/json",
    #             accept="application/json",
    #         )
    #         raw = json.loads(await resp["body"].read())
    #         elapsed = (time.perf_counter() - start) * 1000
    #         text = raw.get("content", [{}])[0].get("text", "")
    #         usage = raw.get("usage", {})
    #         return LLMResponse(
    #             text=text,
    #             model=self.BEDROCK_SONNET,
    #             input_tokens=usage.get("input_tokens", 0),
    #             output_tokens=usage.get("output_tokens", 0),
    #             latency_ms=elapsed,
    #             raw_response=raw,
    #         )

    # async def invoke_bedrock_haiku(
    #     self,
    #     prompt: str,
    #     system: str,
    #     max_tokens: int = 2048,
    # ) -> LLMResponse:
    #     """Call Haiku on Bedrock for Layer 4 presentation.
    #
    #     Model: anthropic.claude-3-haiku-20240307-v1:0
    #     Region: us-gov-west-1
    #     """
    #     import aioboto3
    #     session = aioboto3.Session()
    #     async with session.client(
    #         "bedrock-runtime", region_name=self.BEDROCK_REGION
    #     ) as client:
    #         body = json.dumps({
    #             "anthropic_version": "bedrock-2023-05-31",
    #             "max_tokens": max_tokens,
    #             "temperature": 0.1,
    #             "system": system,
    #             "messages": [{"role": "user", "content": prompt}],
    #         })
    #         start = time.perf_counter()
    #         resp = await client.invoke_model(
    #             modelId=self.BEDROCK_HAIKU,
    #             body=body,
    #             contentType="application/json",
    #             accept="application/json",
    #         )
    #         raw = json.loads(await resp["body"].read())
    #         elapsed = (time.perf_counter() - start) * 1000
    #         text = raw.get("content", [{}])[0].get("text", "")
    #         usage = raw.get("usage", {})
    #         return LLMResponse(
    #             text=text,
    #             model=self.BEDROCK_HAIKU,
    #             input_tokens=usage.get("input_tokens", 0),
    #             output_tokens=usage.get("output_tokens", 0),
    #             latency_ms=elapsed,
    #             raw_response=raw,
    #         )


# =============================================================================
# Exceptions
# =============================================================================


class LLMError(Exception):
    """Raised when an LLM API call fails."""
    pass
