#!/usr/bin/env python3
"""
Module:   Init  
Purpose: ATHENA LLM Prompts Package.

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

from athena.prompts.triage import TRIAGE_SYSTEM_PROMPT, TRIAGE_USER_PROMPT_TEMPLATE
from athena.prompts.extract import EXTRACTION_SYSTEM_PROMPT, EXTRACTION_USER_PROMPT_TEMPLATE
from athena.prompts.boundary import (
    BOUNDARY_CONFIRMATION_PROMPT,
    PAGE_NUMBER_DETECTION_PROMPT,
)

__all__ = [
    "TRIAGE_SYSTEM_PROMPT",
    "TRIAGE_USER_PROMPT_TEMPLATE",
    "EXTRACTION_SYSTEM_PROMPT",
    "EXTRACTION_USER_PROMPT_TEMPLATE",
    "BOUNDARY_CONFIRMATION_PROMPT",
    "PAGE_NUMBER_DETECTION_PROMPT",
]
