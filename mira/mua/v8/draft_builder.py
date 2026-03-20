#!/usr/bin/env python3
"""
Module: MUA V8 Draft Builder
Purpose: Orchestrates the 80/20 MUA draft generation pipeline.

Pipeline:
  1. Accept session data (material, environment, application)
  2. Retrieve precedent MUAs from Postgres
  3. Build each section with precedent attribution
  4. Mark sections that need engineer input
  5. Return MUADraftWorkflow for review

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
import os
from typing import List, Optional

from .models import (
    MUAGap,
    MUAPrecedent,
    MUARenderedDocument,
    MUASessionData,
)
from .precedent_retriever import PrecedentRetriever
from .renderer import MUADocumentRenderer
from .workflow import (
    MUADraftSection,
    MUADraftWorkflow,
    PrecedentAttribution,
    SectionStatus,
)

logger = logging.getLogger(__name__)

__all__ = ["MUADraftBuilder"]

USE_BEDROCK = os.getenv("USE_BEDROCK", "1").lower() in ("1", "true", "yes")
BEDROCK_REGION = os.getenv("BEDROCK_REGION", "us-gov-west-1")


class MUADraftBuilder:
    """
    Builds an MUA draft workflow from session data.

    This is the main entry point for the 80/20 MUA system.
    """

    def __init__(
        self,
        db_url: Optional[str] = None,
        use_llm: bool = True,
        use_bedrock: Optional[bool] = None,
    ):
        self._retriever = PrecedentRetriever(db_url=db_url)
        self._use_llm = use_llm
        self._renderer = MUADocumentRenderer(
            use_bedrock=use_bedrock if use_bedrock is not None else USE_BEDROCK,
        )

    def build_draft(
        self,
        session: MUASessionData,
        precedent_limit: int = 5,
    ) -> MUADraftWorkflow:
        """
        Build a complete MUA draft with precedent attribution.

        Args:
            session: MUA session data (material, env, gaps, etc.)
            precedent_limit: Max precedents to retrieve

        Returns:
            MUADraftWorkflow ready for engineer review
        """
        # Step 1: Use pre-loaded precedents or retrieve from Postgres
        if session.precedents:
            precedents = session.precedents
        else:
            precedents = self._retrieve_precedents(session, precedent_limit)
            session.precedents = precedents

        # Step 2: Build each section
        sections = self._build_all_sections(session, precedents)

        # Step 3: Assemble workflow
        workflow = MUADraftWorkflow(
            session=session,
            sections=sections,
            precedents_found=precedents,
        )

        logger.info(
            f"[DraftBuilder] Built draft for {session.material_name}: "
            f"{len(sections)} sections, {len(precedents)} precedents, "
            f"review progress: {workflow.review_progress}"
        )

        return workflow

    def _retrieve_precedents(
        self, session: MUASessionData, limit: int
    ) -> List[MUAPrecedent]:
        """Retrieve precedent MUAs from Postgres."""
        try:
            return self._retriever.retrieve(session, limit=limit)
        except Exception as exc:
            logger.warning(f"[DraftBuilder] Precedent retrieval failed: {exc}")
            return []

    def _build_all_sections(
        self,
        session: MUASessionData,
        precedents: List[MUAPrecedent],
    ) -> List[MUADraftSection]:
        """Build all 7 MUA sections with provenance."""
        sections = [
            self._build_purpose(session),
            self._build_test_data(session),
            self._build_deficiencies(session),
            self._build_rationale(session, precedents),
            self._build_mitigations(session, precedents),
            self._build_verification(session),
            self._build_references(session, precedents),
        ]
        return sections

    # -------------------------------------------------------------------------
    # Section builders (80% automated)
    # -------------------------------------------------------------------------

    def _build_purpose(self, s: MUASessionData) -> MUADraftSection:
        """Section 1: PURPOSE AND SCOPE - fully automated."""
        env = s.environment
        cat = {"1": "I", "2": "II", "3": "III"}.get(str(s.category), s.category)

        content = (
            f"    1. PURPOSE AND SCOPE\n"
            f"\n"
            f"    This Material Usage Agreement documents the engineering\n"
            f"    evaluation of {s.material_name}"
        )
        if s.maptis_code:
            content += f" (MAPTIS: {s.maptis_code})"
        content += (
            f" for use in a\n"
            f"    {env.location} environment per {s.applied_standard}.\n"
            f"    The material is classified as Category {cat} based on\n"
            f"    the operating environment and identified deficiencies.\n"
        )
        if env.application:
            content += f"\n    Application: {env.application}\n"

        return MUADraftSection(
            section_number=1,
            section_title="PURPOSE AND SCOPE",
            content=content,
            status=SectionStatus.AI_DRAFTED,  # Auto but reviewable
        )

    def _build_test_data(self, s: MUASessionData) -> MUADraftSection:
        """Section 2: TEST DATA SUMMARY - automated from MAPTIS."""
        lines = ["    2. TEST DATA SUMMARY\n"]

        if s.ratings:
            rated = [r for r in s.ratings if r.rating]
            unrated = [r for r in s.ratings if not r.rating]
            if rated:
                lines.append("    The following test data is on record:\n")
                for r in rated:
                    line = f"      {r.test_class}: Rating {r.rating}"
                    if r.report_number:
                        line += f" (Report {r.report_number})"
                    if r.test_date:
                        line += f", tested {r.test_date}"
                    lines.append(line)
                lines.append("")
            if unrated:
                classes = ", ".join(r.test_class for r in unrated)
                lines.append(
                    f"    No current test data is available for: {classes}.\n"
                )
        else:
            lines.append(
                "    No MAPTIS test data records were found for this material\n"
                "    in the queried environment. All required test classes lack\n"
                "    current data.\n"
            )

        return MUADraftSection(
            section_number=2,
            section_title="TEST DATA SUMMARY",
            content="\n".join(lines),
            status=SectionStatus.AI_DRAFTED,
        )

    def _build_deficiencies(self, s: MUASessionData) -> MUADraftSection:
        """Section 3: DEFICIENCIES - automated from gap analysis."""
        lines = ["    3. IDENTIFIED DEFICIENCIES AND DISPOSITIONS\n"]

        if s.gaps:
            for i, g in enumerate(s.gaps, 1):
                lines.append(
                    f"    3.{i}  {g.dimension.title()} [{g.severity.upper()}]"
                )
                lines.append(f"         {g.description}")
                if g.disposition:
                    lines.append(f"         Disposition: {g.disposition}")
                if g.rationale:
                    lines.append(f"         Rationale: \"{g.rationale}\"")
                lines.append("")
        else:
            lines.append(
                "    No deficiencies were identified. All required test\n"
                "    classes have acceptable ratings.\n"
            )

        return MUADraftSection(
            section_number=3,
            section_title="IDENTIFIED DEFICIENCIES AND DISPOSITIONS",
            content="\n".join(lines),
            status=SectionStatus.AI_DRAFTED,
        )

    def _build_rationale(
        self,
        s: MUASessionData,
        precedents: List[MUAPrecedent],
    ) -> MUADraftSection:
        """
        Section 4: ENGINEERING RATIONALE - the key 20% section.

        AI pre-fills from precedent MUA rationale, but this section
        is marked NEEDS_INPUT so the engineer MUST review it.
        """
        lines = ["    4. ENGINEERING RATIONALE\n"]
        attributions: List[PrecedentAttribution] = []

        if precedents:
            # Use best precedent's rationale as basis
            best = precedents[0]
            lines.append(
                f"    Based on review of {len(precedents)} precedent MUA(s) for\n"
                f"    similar materials, the following rationale is proposed:\n"
            )

            if best.rationale:
                # Clean up and present the precedent rationale
                rat_text = best.rationale.strip()
                # Wrap long lines
                words = rat_text.split()
                current_line = "    "
                wrapped_lines = []
                for word in words:
                    if len(current_line) + len(word) + 1 > 75:
                        wrapped_lines.append(current_line)
                        current_line = "    " + word
                    else:
                        current_line += " " + word if current_line.strip() else "    " + word
                if current_line.strip():
                    wrapped_lines.append(current_line)
                lines.extend(wrapped_lines)
                lines.append("")

                attributions.append(PrecedentAttribution(
                    precedent_mua_number=best.mua_number,
                    precedent_material=best.material_name or "unknown",
                    relevance_score=best.relevance_score or 0.0,
                    rationale_excerpt=rat_text[:200],
                    used_for="rationale basis",
                ))

            lines.append(
                f"    [SOURCE: Precedent MUA {best.mua_number}"
                f" ({best.material_name or 'N/A'},"
                f" {best.determination or 'N/A'})]\n"
            )

            # Show additional precedents as supporting evidence
            if len(precedents) > 1:
                lines.append("    Supporting precedents:")
                for p in precedents[1:]:
                    lines.append(
                        f"      - {p.mua_number}: {p.material_name or 'N/A'}"
                        f" ({p.determination or 'N/A'})"
                    )
                    attributions.append(PrecedentAttribution(
                        precedent_mua_number=p.mua_number,
                        precedent_material=p.material_name or "unknown",
                        relevance_score=p.relevance_score or 0.0,
                        rationale_excerpt=(p.rationale or "")[:200],
                        used_for="supporting evidence",
                    ))
                lines.append("")
        else:
            lines.append(
                "    No precedent MUAs were found for this material in the\n"
                "    queried environment. Engineer must provide rationale based\n"
                "    on engineering judgment, testing, or analysis.\n"
            )

        # Evidence strength
        if s.evidence_strength:
            es = s.evidence_strength
            lines.append(
                f"    Evidence Strength: {es.band} ({es.score:.3f})\n"
            )

        lines.append(
            "    >>> ENGINEER: Review and edit this rationale as needed. <<<\n"
        )

        # This section requires engineer review
        return MUADraftSection(
            section_number=4,
            section_title="ENGINEERING RATIONALE",
            content="\n".join(lines),
            status=SectionStatus.NEEDS_INPUT,  # THE 20%
            attributions=attributions,
        )

    def _build_mitigations(
        self,
        s: MUASessionData,
        precedents: List[MUAPrecedent],
    ) -> MUADraftSection:
        """Section 5: MITIGATIONS - automated with engineer review."""
        lines = ["    5. MITIGATIONS AND OPERATIONAL CONTROLS\n"]

        accepted = [g for g in s.gaps if g.disposition and "Accept" in g.disposition]
        if accepted:
            for g in accepted:
                lines.append(
                    f"    {g.dimension.title()}: Operational use of this material\n"
                    f"    must remain within the bounds of the stated rationale.\n"
                    f"    Any deviation from the stated conditions invalidates\n"
                    f"    this acceptance and requires re-evaluation.\n"
                )
                if g.rationale and g.rationale != "test":
                    lines.append(f"    Basis: {g.rationale}\n")
                lines.append("")
        else:
            lines.append("    No mitigations required.\n")

        return MUADraftSection(
            section_number=5,
            section_title="MITIGATIONS AND OPERATIONAL CONTROLS",
            content="\n".join(lines),
            status=SectionStatus.AI_DRAFTED,
        )

    def _build_verification(self, s: MUASessionData) -> MUADraftSection:
        """Section 6: VERIFICATION - automated from gaps."""
        lines = ["    6. VERIFICATION REQUIREMENTS\n"]

        open_gaps = [
            g for g in s.gaps
            if not g.disposition or "Accept" not in g.disposition
        ]
        if open_gaps:
            lines.append(
                "    The following verification testing is required prior to\n"
                "    material use:\n"
            )
            for g in open_gaps:
                lines.append(f"      - {g.dimension.title()}: {g.description}")
            lines.append("")
        else:
            lines.append(
                "    No additional verification testing is required. All\n"
                "    identified deficiencies have been dispositioned with\n"
                "    engineering rationale.\n"
            )

        return MUADraftSection(
            section_number=6,
            section_title="VERIFICATION REQUIREMENTS",
            content="\n".join(lines),
            status=SectionStatus.AI_DRAFTED,
        )

    def _build_references(
        self,
        s: MUASessionData,
        precedents: List[MUAPrecedent],
    ) -> MUADraftSection:
        """Section 7: REFERENCES - fully automated."""
        lines = ["    7. REFERENCES AND TRACEABILITY\n"]

        lines.append(f"    Governing Standard: {s.applied_standard}\n")

        if precedents:
            lines.append("    Precedent MUAs cited:")
            for p in precedents:
                line = f"      - {p.mua_number}"
                if p.material_name:
                    line += f" ({p.material_name}"
                    if p.determination:
                        line += f", {p.determination}"
                    line += ")"
                lines.append(line)
            lines.append("")

        if s.cited_evidence:
            lines.append("    Additional evidence:")
            for e in s.cited_evidence:
                lines.append(f"      - {e.get('source', 'Unknown')}")
            lines.append("")

        return MUADraftSection(
            section_number=7,
            section_title="REFERENCES AND TRACEABILITY",
            content="\n".join(lines),
            status=SectionStatus.AI_DRAFTED,
        )

    def close(self):
        """Clean up resources."""
        self._retriever.close()
