"""
MUA Final - Section-Level Review Workflow

The 80/20 pattern:
  - 80% AI: header, classification, test data, gaps, precedent retrieval,
    draft rationale, mitigations, verification, references
  - 20% Engineer: rationale review/edit, gap dispositions, final approval

Each section tracks:
  - What the AI generated
  - Which precedent(s) it drew from (PrecedentAttribution)
  - What the engineer decided (accept/edit/override/flag)

BoundState AI 2026
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from .models import MUAPrecedent, MUARenderedDocument, MUASessionData

logger = logging.getLogger(__name__)

__all__ = [
    "MUADraftSection",
    "MUADraftWorkflow",
    "SectionStatus",
    "ReviewAction",
    "PrecedentAttribution",
]


class SectionStatus(str, Enum):
    """Status of a draft section in the review workflow."""
    AI_DRAFTED = "ai_drafted"           # AI generated, awaiting review
    ENGINEER_ACCEPTED = "accepted"       # Engineer accepted as-is
    ENGINEER_MODIFIED = "modified"       # Engineer edited the content
    ENGINEER_OVERRIDE = "override"       # Engineer replaced entirely
    NEEDS_INPUT = "needs_input"          # Requires engineer input (the 20%)


class ReviewAction(str, Enum):
    """Actions an engineer can take on a section."""
    ACCEPT = "accept"
    EDIT = "edit"
    OVERRIDE = "override"
    FLAG_FOR_TESTING = "flag_for_testing"


@dataclass
class PrecedentAttribution:
    """Links a draft section to the precedent MUA that informed it."""
    precedent_mua_number: str
    precedent_material: str
    relevance_score: float
    rationale_excerpt: str
    used_for: str  # "rationale basis", "mitigation template", "gap disposition"


@dataclass
class MUADraftSection:
    """
    A single section of the MUA draft, with provenance and review state.

    Each section tracks:
    - What the AI generated (content)
    - Which precedent(s) it drew from (attributions)
    - What the engineer decided (status, engineer_content)
    """
    section_number: int
    section_title: str
    content: str
    status: SectionStatus = SectionStatus.AI_DRAFTED

    # Provenance: which precedent(s) informed this section
    attributions: List[PrecedentAttribution] = field(default_factory=list)

    # Engineer review
    engineer_content: Optional[str] = None  # If modified/overridden
    engineer_notes: Optional[str] = None
    reviewed_at: Optional[datetime] = None
    reviewed_by: Optional[str] = None

    @property
    def final_content(self) -> str:
        """The content that goes into the final document."""
        if self.status in (SectionStatus.ENGINEER_MODIFIED, SectionStatus.ENGINEER_OVERRIDE):
            return self.engineer_content or self.content
        return self.content

    @property
    def needs_review(self) -> bool:
        return self.status in (SectionStatus.AI_DRAFTED, SectionStatus.NEEDS_INPUT)


@dataclass
class MUADraftWorkflow:
    """
    Complete MUA draft workflow state.

    The engineer sees the full draft with all sections, can review
    each one, and sees exactly which precedent MUAs informed each
    section.
    """
    # Session data
    session: MUASessionData

    # Draft sections
    sections: List[MUADraftSection] = field(default_factory=list)

    # Precedents used
    precedents_found: List[MUAPrecedent] = field(default_factory=list)

    # Workflow state
    created_at: datetime = field(default_factory=datetime.utcnow)
    status: str = "draft"  # draft, in_review, finalized

    @property
    def review_progress(self) -> Dict[str, Any]:
        """How much of the draft has been reviewed."""
        total = len(self.sections)
        reviewed = sum(1 for s in self.sections if not s.needs_review)
        needs_input = sum(
            1 for s in self.sections
            if s.status == SectionStatus.NEEDS_INPUT
        )
        return {
            "total_sections": total,
            "reviewed": reviewed,
            "remaining": total - reviewed,
            "needs_engineer_input": needs_input,
            "percent_complete": round(reviewed / total * 100) if total else 0,
        }

    @property
    def is_ready_to_finalize(self) -> bool:
        """All sections reviewed and no NEEDS_INPUT remaining."""
        return all(not s.needs_review for s in self.sections)

    def review_section(
        self,
        section_number: int,
        action: ReviewAction,
        content: Optional[str] = None,
        notes: Optional[str] = None,
        reviewer: Optional[str] = None,
    ) -> MUADraftSection:
        """Engineer reviews a section."""
        section = next(
            (s for s in self.sections if s.section_number == section_number),
            None,
        )
        if not section:
            raise ValueError(f"Section {section_number} not found")

        section.reviewed_at = datetime.utcnow()
        section.reviewed_by = reviewer
        section.engineer_notes = notes

        if action == ReviewAction.ACCEPT:
            section.status = SectionStatus.ENGINEER_ACCEPTED
        elif action == ReviewAction.EDIT:
            if not content:
                raise ValueError("Content required for EDIT action")
            section.engineer_content = content
            section.status = SectionStatus.ENGINEER_MODIFIED
        elif action == ReviewAction.OVERRIDE:
            if not content:
                raise ValueError("Content required for OVERRIDE action")
            section.engineer_content = content
            section.status = SectionStatus.ENGINEER_OVERRIDE
        elif action == ReviewAction.FLAG_FOR_TESTING:
            section.engineer_notes = notes or "Flagged for testing"
            section.status = SectionStatus.ENGINEER_MODIFIED
            section.engineer_content = (
                section.content
                + f"\n\n    [FLAGGED FOR TESTING: {notes or 'Additional testing required'}]"
            )

        return section

    def render_final(self) -> str:
        """Render the final document from all sections using final_content."""
        lines = []
        for section in sorted(self.sections, key=lambda s: s.section_number):
            lines.append(section.final_content)
            lines.append("")
        return "\n".join(lines)
