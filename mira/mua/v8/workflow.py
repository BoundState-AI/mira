#!/usr/bin/env python3
"""
Module: MUA V8 Workflow
Purpose: 80/20 automated MUA generation - AI fills 80%, engineer reviews 20%.

The workflow:
  1. INTAKE: Engineer provides material, environment, application (input form)
  2. AUTO-POPULATE: System queries MAPTIS for ratings + Postgres for precedents
  3. DRAFT: LLM renders a professional MUA using precedent rationale as basis
  4. REVIEW: Engineer sees the draft with precedent citations highlighted
     - Each section shows its source (which precedent MUA, which clause)
     - Engineer can accept, edit, or override any section
     - Rationale section is pre-filled from best-match precedent but EDITABLE
  5. FINALIZE: Engineer signs off, document is rendered final

The 80% automated:
  - Header, classification, environment (deterministic)
  - Test data lookup (MAPTIS query)
  - Gap identification (rule-based)
  - Precedent retrieval and ranking (Postgres + LLM scoring)
  - Draft rationale from precedent corpus (LLM)
  - Mitigations from precedent + standard clauses
  - Verification requirements (rule-based from gaps)
  - References/traceability (automated)

The 20% engineer:
  - Application description (their words)
  - Rationale review/edit (accept or refine the AI draft)
  - Gap dispositions (accept with rationale, or flag for testing)
  - Final approval signature

BoundState AI 2026
Version: 8.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: SWE-013 (Traceability), SWE-032 (Data validation)
Safety Critical: True
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from .models import (
    MUAGap,
    MUAPrecedent,
    MUARenderedDocument,
    MUASessionData,
)

logger = logging.getLogger(__name__)

__all__ = [
    "MUADraftSection",
    "MUADraftWorkflow",
    "SectionStatus",
    "ReviewAction",
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
    used_for: str  # e.g., "rationale basis", "mitigation template", "gap disposition"


@dataclass
class MUADraftSection:
    """
    A single section of the MUA draft, with provenance and review state.

    Each section tracks:
    - What the AI generated
    - Which precedent(s) it drew from
    - What the engineer decided
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

    This is the object that the UI/API exposes to the engineer.
    They see the full draft with all sections, can review each one,
    and see exactly which precedent MUAs informed each section.
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
        needs_input = sum(1 for s in self.sections if s.status == SectionStatus.NEEDS_INPUT)
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
                section.content + f"\n\n[FLAGGED FOR TESTING: {notes or 'Additional testing required'}]"
            )

        return section

    def render_final(self) -> str:
        """Render the final document from all sections using final_content."""
        lines = []
        for section in sorted(self.sections, key=lambda s: s.section_number):
            lines.append(section.final_content)
            lines.append("")
        return "\n".join(lines)
