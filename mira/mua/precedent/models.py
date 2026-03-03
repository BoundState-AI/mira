"""MUA precedent result models."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PrecedentSummary:
    """Precedent lookup result from mua_precedent.precedent_counts."""

    issue: str
    media_category: str
    material_class: str
    alloy_family: str
    total_count: int
    approved_count: int
    rejected_count: int
    distinct_materials: int
    most_common_category: str  # "I", "II", "III", or ""

    @property
    def approval_rate(self) -> float:
        if self.total_count == 0:
            return 0.0
        return self.approved_count / self.total_count

    @property
    def has_strong_precedent(self) -> bool:
        """True if >=5 prior MUAs with >=80% approval rate."""
        return self.total_count >= 5 and self.approval_rate >= 0.80


@dataclass(frozen=True)
class PrecedentExemplar:
    """A single historic MUA exemplar with rationale text."""

    mua_number: str
    material_name: str
    alloy_family: str
    media_category: str
    determination: str  # APPROVED, CONDITIONAL, REJECTED
    category: str       # I, II, III, or ""
    rationale_text: str
    confidence: float
    match_ring: str     # "exact", "family", "broad"
    match_score: float  # composite ranking score
