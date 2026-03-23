#!/usr/bin/env python3
"""
Module: LLM Provider
Purpose: Provider-agnostic LLM completion interface for MIRA runtime.

Routes calls through AWS Bedrock Converse (first-class), Anthropic direct API,
or any OpenAI-compatible endpoint based on LLM_PROVIDER env var.

BoundState AI 2026
Version: 2.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: SWE-013, NASA-STD-8739.8B
Safety Critical: False
"""

from __future__ import annotations

import json
import logging
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

LOGGER = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Model tier defaults — Bedrock-first runtime defaults
# ---------------------------------------------------------------------------

_BEDROCK_MODEL_DEFAULTS: dict[str, str] = {
    "sonnet": "us.anthropic.claude-sonnet-4-5-20250929-v1:0",
    "haiku": "us.anthropic.claude-haiku-4-5-20251001-v1:0",
}
_BEDROCK_MODEL_DEFAULTS_GOVCLOUD: dict[str, str] = {
    "sonnet": "us-gov.anthropic.claude-sonnet-4-5-20250929-v1:0",
    "haiku": "us-gov.anthropic.claude-haiku-4-5-20251001-v1:0",
}
_ANTHROPIC_MODEL_DEFAULTS: dict[str, str] = {
    "sonnet": "claude-sonnet-4-5-20250929",
    "haiku": "claude-haiku-4-5-20251001",
}
MODEL_DEFAULTS = _BEDROCK_MODEL_DEFAULTS


def resolve_provider_name(name: str | None = None) -> str:
    """Resolve the active provider name, honoring chat-specific overrides."""
    return (
        name
        or os.environ.get("LLM_PROVIDER")
        or os.environ.get("MIRA_CHAT_LLM_PROVIDER")
        or "bedrock-converse"
    ).strip().lower()


def resolve_bedrock_region(
    *,
    model_id: str | None = None,
    region_override: str | None = None,
) -> str:
    """Resolve the AWS Bedrock region with explicit env and model-aware fallbacks."""
    if region_override and region_override.strip():
        return region_override.strip()

    for env_key in (
        "BEDROCK_REGION",
        "MIRA_CHAT_BEDROCK_REGION",
        "AWS_REGION",
        "AWS_DEFAULT_REGION",
    ):
        value = os.environ.get(env_key, "").strip()
        if value:
            return value

    normalized_model = (model_id or "").strip().lower()
    if normalized_model.startswith("us-gov."):
        return "us-gov-west-1"
    if normalized_model.startswith("us."):
        return "us-east-1"
    return "us-east-1"


def resolve_model_for_provider(
    tier: str,
    *,
    provider_name: str | None = None,
    bedrock_region: str | None = None,
) -> str:
    """Resolve a logical tier for a specific provider/region combination."""
    resolved_provider = resolve_provider_name(provider_name)
    resolved_region = resolve_bedrock_region(
        model_id=None,
        region_override=bedrock_region,
    ).lower()

    env_map = {"sonnet": "LLM_SONNET_MODEL", "haiku": "LLM_HAIKU_MODEL"}
    env_var = env_map.get(tier)
    if env_var:
        val = os.environ.get(env_var, "").strip()
        if val:
            if resolved_provider == "bedrock-converse":
                if resolved_region.startswith("us-gov-") and val.startswith("us."):
                    LOGGER.warning(
                        "Ignoring commercial %s=%s for GovCloud Bedrock region %s; using GovCloud default.",
                        env_var,
                        val,
                        resolved_region,
                    )
                elif (
                    resolved_region.startswith("us-")
                    and not resolved_region.startswith("us-gov-")
                    and val.startswith("us-gov.")
                ):
                    LOGGER.warning(
                        "Ignoring GovCloud %s=%s for commercial Bedrock region %s; using commercial default.",
                        env_var,
                        val,
                        resolved_region,
                    )
                else:
                    return val
            else:
                return val
    if tier not in {"sonnet", "haiku"}:
        return tier

    if resolved_provider == "anthropic":
        return _ANTHROPIC_MODEL_DEFAULTS[tier]

    if resolved_provider == "bedrock-converse" and resolved_region.startswith("us-gov-"):
        return _BEDROCK_MODEL_DEFAULTS_GOVCLOUD[tier]
    return _BEDROCK_MODEL_DEFAULTS[tier]


def resolve_model(tier: str) -> str:
    """Map a logical tier name to a concrete model ID."""
    return resolve_model_for_provider(tier)


# ---------------------------------------------------------------------------
# Response dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LLMResponse:
    """Normalized response from any LLM backend."""

    text: str
    input_tokens: int
    output_tokens: int
    model: str
    latency_ms: float


# ---------------------------------------------------------------------------
# Protocol
# ---------------------------------------------------------------------------


@runtime_checkable
class LLMProvider(Protocol):
    """Structural interface for LLM providers.

    Implementations must provide a synchronous ``complete`` method.
    """

    def complete(
        self,
        system: str,
        messages: list[dict],
        *,
        max_tokens: int = 4096,
        temperature: float = 0.0,
        response_format: str | None = None,
        timeout_s: int | float | None = None,
    ) -> LLMResponse: ...


# ---------------------------------------------------------------------------
# Bedrock Converse  (first-class provider)
# ---------------------------------------------------------------------------


class BedrockConverseProvider:
    """AWS Bedrock Converse API provider using boto3 ``bedrock-runtime``.

    No Anthropic SDK dependency — uses the native Converse wire format.
    """

    def __init__(
        self,
        region: str | None = None,
        model_id: str | None = None,
    ) -> None:
        import boto3

        self._region = resolve_bedrock_region(
            model_id=model_id,
            region_override=region,
        )
        self._default_model = model_id or resolve_model("sonnet")
        self._client = boto3.client("bedrock-runtime", region_name=self._region)

    def complete(
        self,
        system: str,
        messages: list[dict],
        *,
        max_tokens: int = 4096,
        temperature: float = 0.0,
        response_format: str | None = None,
        timeout_s: int | float | None = None,
    ) -> LLMResponse:
        model_id = self._default_model

        # Build Converse-format messages:
        #   [{"role": "user", "content": [{"text": "..."}]}, ...]
        converse_msgs = []
        for msg in messages:
            role = msg["role"]
            content = msg.get("content", "")
            if isinstance(content, str):
                converse_msgs.append({"role": role, "content": [{"text": content}]})
            elif isinstance(content, list):
                # Already structured blocks — pass through
                converse_msgs.append({"role": role, "content": content})
            else:
                converse_msgs.append({"role": role, "content": [{"text": str(content)}]})

        # If response_format requests JSON, nudge via system prompt suffix
        sys_text = system
        if response_format and response_format.lower() == "json":
            sys_text = f"{system}\n\nYou MUST respond with valid JSON only."

        t0 = time.monotonic()
        response = self._client.converse(
            modelId=model_id,
            system=[{"text": sys_text}],
            messages=converse_msgs,
            inferenceConfig={
                "maxTokens": max_tokens,
                "temperature": temperature,
            },
        )
        latency_ms = (time.monotonic() - t0) * 1000

        text = _extract_converse_text(response)
        usage = response.get("usage", {})

        return LLMResponse(
            text=text,
            input_tokens=usage.get("inputTokens", 0),
            output_tokens=usage.get("outputTokens", 0),
            model=model_id,
            latency_ms=latency_ms,
        )


def _extract_converse_text(response: dict) -> str:
    """Pull text from a Bedrock Converse response envelope."""
    output = response.get("output", {})
    message = output.get("message", {})
    parts: list[str] = []
    for block in message.get("content", []):
        t = block.get("text")
        if isinstance(t, str) and t.strip():
            parts.append(t.strip())
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Anthropic direct API  (commercial / non-federal fallback)
# ---------------------------------------------------------------------------


class AnthropicProvider:
    """Anthropic Messages API provider using the ``anthropic`` SDK.

    Intended for commercial workloads where Bedrock is not available.
    """

    def __init__(
        self,
        api_key: str | None = None,
        model_id: str | None = None,
    ) -> None:
        import anthropic

        self._api_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "").strip()
        if not self._api_key:
            raise ValueError(
                "AnthropicProvider requires ANTHROPIC_API_KEY env var or explicit api_key"
            )
        self._client = anthropic.Anthropic(api_key=self._api_key)
        self._default_model = model_id or resolve_model("sonnet")

    def complete(
        self,
        system: str,
        messages: list[dict],
        *,
        max_tokens: int = 4096,
        temperature: float = 0.0,
        response_format: str | None = None,
        timeout_s: int | float | None = None,
    ) -> LLMResponse:
        model_id = self._default_model

        # Anthropic SDK accepts messages as [{"role": ..., "content": str|list}]
        t0 = time.monotonic()
        response = self._client.messages.create(
            model=model_id,
            max_tokens=max_tokens,
            temperature=temperature,
            system=system,
            messages=messages,
            timeout=timeout_s,
        )
        latency_ms = (time.monotonic() - t0) * 1000

        text_parts: list[str] = []
        for block in response.content:
            t = getattr(block, "text", None)
            if isinstance(t, str) and t.strip():
                text_parts.append(t.strip())
        text = "\n".join(text_parts)

        return LLMResponse(
            text=text,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            model=response.model,
            latency_ms=latency_ms,
        )


# ---------------------------------------------------------------------------
# OpenAI-compatible endpoint  (vLLM, Ollama /v1, LiteLLM, etc.)
# ---------------------------------------------------------------------------


class OpenAICompatProvider:
    """Generic OpenAI-compatible chat completions provider.

    Uses raw HTTP to avoid adding ``openai`` as a runtime dependency.
    Works with any server exposing ``/v1/chat/completions``.
    """

    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        model_id: str | None = None,
    ) -> None:
        self._base_url = (
            base_url
            or os.environ.get("LLM_BASE_URL", "").strip()
            or "http://localhost:11434/v1"
        ).rstrip("/")
        self._api_key = api_key or os.environ.get("OPENAI_API_KEY", "").strip() or "no-key"
        self._default_model = model_id or resolve_model("sonnet")

    def complete(
        self,
        system: str,
        messages: list[dict],
        *,
        max_tokens: int = 4096,
        temperature: float = 0.0,
        response_format: str | None = None,
        timeout_s: int | float | None = None,
    ) -> LLMResponse:
        model_id = self._default_model

        # Build OpenAI chat messages: system first, then conversation
        chat_messages = [{"role": "system", "content": system}]
        for msg in messages:
            chat_messages.append({"role": msg["role"], "content": msg.get("content", "")})

        body: dict = {
            "model": model_id,
            "messages": chat_messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if response_format and response_format.lower() == "json":
            body["response_format"] = {"type": "json_object"}

        req = urllib.request.Request(
            f"{self._base_url}/chat/completions",
            data=json.dumps(body).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )

        t0 = time.monotonic()
        try:
            with urllib.request.urlopen(req, timeout=timeout_s or 120) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            details = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(
                f"OpenAI-compat endpoint returned HTTP {exc.code}: {details}"
            ) from exc
        latency_ms = (time.monotonic() - t0) * 1000

        # Standard OpenAI response shape
        choices = payload.get("choices", [])
        text = ""
        if choices:
            text = choices[0].get("message", {}).get("content", "").strip()

        usage = payload.get("usage", {})
        return LLMResponse(
            text=text,
            input_tokens=usage.get("prompt_tokens", 0),
            output_tokens=usage.get("completion_tokens", 0),
            model=payload.get("model", model_id),
            latency_ms=latency_ms,
        )


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

_PROVIDER_REGISTRY: dict[str, type] = {
    "bedrock-converse": BedrockConverseProvider,
    "anthropic": AnthropicProvider,
    "openai-compat": OpenAICompatProvider,
}


def validate_provider_configuration(name: str | None = None) -> None:
    """Fail fast on obviously incomplete provider configuration."""
    provider_name = resolve_provider_name(name)

    if provider_name not in _PROVIDER_REGISTRY:
        valid = ", ".join(sorted(_PROVIDER_REGISTRY))
        raise RuntimeError(f"Unknown LLM provider {provider_name!r}. Valid: {valid}")

    if provider_name == "anthropic":
        if not (os.environ.get("ANTHROPIC_API_KEY", "").strip()):
            raise RuntimeError("LLM_PROVIDER=anthropic requires ANTHROPIC_API_KEY.")
        return

    if provider_name == "openai-compat":
        if not (os.environ.get("LLM_BASE_URL", "").strip()):
            raise RuntimeError("LLM_PROVIDER=openai-compat requires LLM_BASE_URL.")
        if not (os.environ.get("OPENAI_API_KEY", "").strip()):
            raise RuntimeError("LLM_PROVIDER=openai-compat requires OPENAI_API_KEY.")
        return


def get_provider(name: str | None = None) -> LLMProvider:
    """Instantiate an LLM provider by name.

    Args:
        name: Provider key.  Falls back to ``LLM_PROVIDER`` env var,
              then defaults to ``"bedrock-converse"``.

    Returns:
        A configured provider instance satisfying the ``LLMProvider`` protocol.

    Raises:
        ValueError: If the provider name is unknown.

    Environment variables consumed (depending on provider):

    =================== ========================================
    Variable             Used by
    =================== ========================================
    ``LLM_PROVIDER``     Factory default (bedrock-converse)
    ``LLM_SONNET_MODEL`` Model resolver — "sonnet" tier override
    ``LLM_HAIKU_MODEL``  Model resolver — "haiku" tier override
    ``AWS_REGION``       BedrockConverseProvider
    ``BEDROCK_REGION``   BedrockConverseProvider (takes priority)
    ``ANTHROPIC_API_KEY`` AnthropicProvider
    ``LLM_BASE_URL``     OpenAICompatProvider endpoint
    ``OPENAI_API_KEY``   OpenAICompatProvider auth
    =================== ========================================
    """
    provider_name = resolve_provider_name(name)

    cls = _PROVIDER_REGISTRY.get(provider_name)
    if cls is None:
        valid = ", ".join(sorted(_PROVIDER_REGISTRY))
        raise ValueError(f"Unknown LLM provider {provider_name!r}. Valid: {valid}")

    return cls()


# ---------------------------------------------------------------------------
# Module-level convenience functions for Stream C callsites
# ---------------------------------------------------------------------------


def complete(
    *,
    system: str,
    user: str,
    model: str,
    max_tokens: int = 1024,
    temperature: float = 0.0,
    timeout_s: int = 45,
    provider: str | None = None,
    bedrock_region: str | None = None,
) -> LLMResponse:
    """Synchronous text completion via the configured provider.

    Convenience wrapper that instantiates a provider via ``get_provider()``
    and calls ``complete()`` with a single user message.  This keeps Stream C
    callsites simple while routing through the class-based provider hierarchy.

    Args:
        system: System prompt.
        user: User message content.
        model: Full model ID (passed to provider as override — caller is
               responsible for choosing the right ID for the active backend).
        max_tokens: Maximum output tokens.
        temperature: Sampling temperature.
        timeout_s: Request timeout (used by providers that support it).
        provider: Override provider name (default: auto-detect via env).
        bedrock_region: Explicit AWS Bedrock region override for Bedrock calls.

    Returns:
        LLMResponse with normalized text and metadata.
    """
    backend_name = resolve_provider_name(provider)

    # Map legacy provider names
    if backend_name == "bedrock-converse":
        prov = BedrockConverseProvider(region=bedrock_region, model_id=model)
    elif backend_name == "anthropic":
        prov = AnthropicProvider(model_id=model)
    elif backend_name in {"openai-compat", "ollama"}:
        prov = OpenAICompatProvider(model_id=model)
    else:
        # Auto-detect: use factory default but override model
        prov = get_provider()
        # Override model for this call
        prov._default_model = model  # type: ignore[attr-defined]

    return prov.complete(
        system=system,
        messages=[{"role": "user", "content": user}],
        max_tokens=max_tokens,
        temperature=temperature,
        timeout_s=timeout_s,
    )


def complete_with_sdk(
    *,
    system: str,
    user: str,
    model: str,
    max_tokens: int = 1024,
    temperature: float = 0.0,
    timeout_s: int = 45,
    use_bedrock: bool = False,
    bedrock_region: str = "us-east-1",
) -> LLMResponse:
    """Complete using the Anthropic SDK (direct or Bedrock).

    Legacy bridge — prefer ``complete()`` for new code.
    """
    if use_bedrock:
        prov = BedrockConverseProvider(region=bedrock_region, model_id=model)
    else:
        prov = AnthropicProvider(model_id=model)

    return prov.complete(
        system=system,
        messages=[{"role": "user", "content": user}],
        max_tokens=max_tokens,
        temperature=temperature,
        timeout_s=timeout_s,
    )
