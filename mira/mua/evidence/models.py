"""Evidence bundle models for MUA runtime synthesis."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from mira.mua.matchmaker.models import RationalePhrase
from mira.mua.precedent.models import PrecedentExemplar, PrecedentSummary


@dataclass(frozen=True)
class EvidenceBundle:
    """Complete evidence package for one classified flag."""

    issue: str
    rating: str
    mua_type: str
    material_class: str
    media: str

    precedent_summary: Optional[PrecedentSummary]
    precedent_ring: Optional[str]

    exemplars: list[PrecedentExemplar] = field(default_factory=list)
    phrases: list[RationalePhrase] = field(default_factory=list)

    evidence_hash: str = ""
