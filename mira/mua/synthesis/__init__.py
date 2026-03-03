"""Rationale synthesis package for MUA runtime."""

from .models import Claim, SynthesisResult
from .synthesizer import synthesize_rationale

__all__ = [
    "Claim",
    "SynthesisResult",
    "synthesize_rationale",
]
