"""
Module: AM Knowledge Twin -- engines package (Rev 5 §6)
Purpose: Sub-engines of the AM Qualification Package. Every output is
         rule-derived (cites a frozen pack clause) or evidence-derived
         (cites a corpus source). No assertion without one or the other.

BoundState AI 2026
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: SWE-013, SWE-032, SWE-033, NASA-STD-8739.8B
Safety Critical: True
"""

from __future__ import annotations

__version__ = "0.1.0"
__safety_critical__ = True

from mira.knowledge_twins.am.engines.applicability import (
    ApplicabilityResult,
    evaluate_applicability,
)
from mira.knowledge_twins.am.engines.classification import (
    ClassificationResult,
    evaluate_classification,
)
from mira.knowledge_twins.am.engines.crosswalk import (
    CrosswalkResult,
    build_crosswalk,
)

__all__ = [
    "ApplicabilityResult",
    "ClassificationResult",
    "CrosswalkResult",
    "build_crosswalk",
    "evaluate_applicability",
    "evaluate_classification",
]
