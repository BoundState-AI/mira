#!/usr/bin/env python3
"""
Module:   Init  
Purpose: ATHENA Validation Gates.

BoundState AI 2025
Version: 1.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Fran OpenAI 5 <noreply@openai.com>
Co-Authored-By: Grok 4.0 <noreply@x.ai>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: SWE-032, SWE-033
Safety Critical: True
"""

from athena.validation.gates.extraction import ExtractionGate
from athena.validation.gates.h2 import H2ValidationGate
from athena.validation.gates.o2 import O2ValidationGate

__all__ = ["ExtractionGate", "H2ValidationGate", "O2ValidationGate"]
__safety_critical__ = True
