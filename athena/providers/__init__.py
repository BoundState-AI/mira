#!/usr/bin/env python3
"""
Module:   Init  
Purpose: ATHENA LLM Providers Package.

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

from athena.providers.base import LLMProvider, LLMResponse
from athena.providers.anthropic import AnthropicProvider

# Optional Bedrock import (for GovCloud deployments)
try:
    from athena.providers.bedrock import BedrockProvider
except ImportError:
    BedrockProvider = None

__all__ = [
    "LLMProvider",
    "LLMResponse",
    "AnthropicProvider",
    "BedrockProvider",
]
