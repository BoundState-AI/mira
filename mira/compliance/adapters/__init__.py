#!/usr/bin/env python3
"""
Module: Adapters Package
Purpose: Knowledge twin adapters (O2, H2) and MUA generator

BoundState AI 2025
Version: 2.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Fran OpenAI 5 <noreply@openai.com>
Co-Authored-By: Grok 4.0 <noreply@x.ai>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: NASA-STD-8739.8B, SWE-013, SWE-033
Safety Critical: True
"""

# Copyright © 2025 BoundState AI. All Rights Reserved.
# Classification: BoundState Proprietary
# License: Evaluation Use Only - Authorized Pilot Program
"""
NASA-STD-6016C Compliance Module - Adapters Package

Adapters for interfacing with knowledge twins (O2, H2) and MUA generator.

IMPORTANT: Adapters emit signals only, NOT MPRDetermination.
That's the conductor's job.

Compliance: NASA-STD-8739.8B, SWE-013, SWE-033

Author: BoundState Team
Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Fran OpenAI <noreply@openai.com>
Co-Authored-By: Grok <noreply@x.ai>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI
"""

__version__ = "2.0.0"
__safety_critical__ = True

from mira.compliance.adapters.base import BaseAdapter
from mira.compliance.adapters.o2_adapter import O2Adapter
from mira.compliance.adapters.h2_adapter import H2Adapter
from mira.compliance.adapters.mua_adapter import MUAAdapter

__all__ = [
    "BaseAdapter",
    "O2Adapter",
    "H2Adapter",
    "MUAAdapter",
]
