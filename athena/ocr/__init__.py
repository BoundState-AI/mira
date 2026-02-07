#!/usr/bin/env python3
"""
Module:   Init  
Purpose: OCR engine for document processing.

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

from athena.ocr.engine import OCREngine
from athena.ocr.alto_parser import ALTOParser
from athena.ocr.abbyy_client import ABBYYClient, MockABBYYClient

__all__ = ["OCREngine", "ALTOParser", "ABBYYClient", "MockABBYYClient"]
