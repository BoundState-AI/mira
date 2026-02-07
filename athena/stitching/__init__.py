#!/usr/bin/env python3
"""
Module:   Init  
Purpose: ATHENA Stitching Layer.

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

from athena.stitching.models import LogicalTable, StitchSignal
from athena.stitching.stitcher import TableStitcher

__all__ = ["LogicalTable", "StitchSignal", "TableStitcher"]
__safety_critical__ = True
