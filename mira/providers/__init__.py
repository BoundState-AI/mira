"""MIRA LLM provider abstraction layer.

Usage::

    from mira.providers import get_provider, resolve_model

    provider = get_provider()                     # uses LLM_PROVIDER env var
    resp = provider.complete(
        system="You are a materials scientist.",
        messages=[{"role": "user", "content": "What is Inconel 718?"}],
    )
    print(resp.text, resp.input_tokens, resp.output_tokens)
"""

from mira.providers.llm_provider import (
    LLMResponse,
    LLMProvider,
    BedrockConverseProvider,
    AnthropicProvider,
    OpenAICompatProvider,
    get_provider,
    resolve_model,
)

__all__ = [
    "LLMResponse",
    "LLMProvider",
    "BedrockConverseProvider",
    "AnthropicProvider",
    "OpenAICompatProvider",
    "get_provider",
    "resolve_model",
]
