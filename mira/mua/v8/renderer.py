#!/usr/bin/env python3
"""
Module: MUA Document Renderer V8
Purpose: LLM-powered renderer that transforms structured MUA session data
         into professional NASA Material Usage Agreement documents.

Architecture:
  - Deterministic shell: header, IDs, dates, classification, signatures
    are rendered via string templates (no LLM hallucination risk)
  - LLM semantic layer: rationale narrative, gap assessments, engineering
    justification, and assessment summary are written by Claude using
    real MUA precedents from Postgres as style/content reference

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
from datetime import datetime
from typing import List, Optional

from .models import (
    MUAGap,
    MUAPrecedent,
    MUARenderedDocument,
    MUASessionData,
)

logger = logging.getLogger(__name__)

__all__ = ["MUADocumentRenderer"]

# LLM configuration
DEFAULT_MODEL_BEDROCK = "us-gov.anthropic.claude-sonnet-4-5-20250929-v1:0"
DEFAULT_MODEL_DIRECT = "claude-sonnet-4-5-20250929"
USE_BEDROCK = os.getenv("USE_BEDROCK", "1").lower() in ("1", "true", "yes")
BEDROCK_REGION = os.getenv("BEDROCK_REGION", "us-gov-west-1")


class MUADocumentRenderer:
    """
    Renders structured MUA session data into a professional NASA MUA document.

    The renderer uses a two-layer approach:
      1. Deterministic template for header/classification/structure
      2. LLM call for prose sections (rationale, assessment, justification)

    The LLM receives:
      - The structured session data (material, environment, gaps, ratings)
      - Real MUA precedent rationale from Postgres as writing examples
      - Strict instructions to never invent data, only present what's given
    """

    def __init__(
        self,
        use_bedrock: Optional[bool] = None,
        bedrock_region: Optional[str] = None,
        model_id: Optional[str] = None,
    ):
        self._use_bedrock = use_bedrock if use_bedrock is not None else USE_BEDROCK
        self._bedrock_region = bedrock_region or BEDROCK_REGION
        self._model_id = model_id
        self._client = None

    def _get_client(self):
        """Lazy-load Anthropic client."""
        if self._client is None:
            if self._use_bedrock:
                from anthropic import AnthropicBedrock
                self._client = AnthropicBedrock(aws_region=self._bedrock_region)
                if not self._model_id:
                    self._model_id = DEFAULT_MODEL_BEDROCK
            else:
                from anthropic import Anthropic
                self._client = Anthropic()
                if not self._model_id:
                    self._model_id = DEFAULT_MODEL_DIRECT
        return self._client

    def render(self, session: MUASessionData) -> MUARenderedDocument:
        """
        Render a complete MUA document from session data.

        Args:
            session: Complete MUA session data

        Returns:
            MUARenderedDocument with professional document text
        """
        # Build deterministic header
        header = self._render_header(session)

        # Build the structured data summary for the LLM
        data_context = self._build_data_context(session)

        # Build precedent context
        precedent_context = self._build_precedent_context(session.precedents)

        # Call LLM for prose sections
        prose = self._generate_prose(session, data_context, precedent_context)

        # Build deterministic footer
        footer = self._render_footer(session)

        # Assemble final document
        document_text = f"{header}\n{prose}\n{footer}"

        return MUARenderedDocument(
            mua_id=session.mua_id,
            document_text=document_text,
            model_used=self._model_id or "",
            precedents_used=len(session.precedents),
        )

    def render_without_llm(self, session: MUASessionData) -> MUARenderedDocument:
        """
        Render using templates only (no LLM call). Useful for testing
        or when LLM is unavailable.
        """
        header = self._render_header(session)
        body = self._render_template_body(session)
        footer = self._render_footer(session)
        document_text = f"{header}\n{body}\n{footer}"

        return MUARenderedDocument(
            mua_id=session.mua_id,
            document_text=document_text,
            model_used="template-only",
            precedents_used=len(session.precedents),
        )

    # -------------------------------------------------------------------------
    # Deterministic sections (no LLM)
    # -------------------------------------------------------------------------

    def _render_header(self, s: MUASessionData) -> str:
        """Render document header - purely deterministic."""
        env = s.environment
        temp_range = ""
        if env.temp_min_f is not None and env.temp_max_f is not None:
            temp_range = f"{env.temp_min_f} to {env.temp_max_f} degF"
        elif env.temp_max_f is not None:
            temp_range = f"up to {env.temp_max_f} degF"

        finalized = s.finalized_at or datetime.utcnow().strftime("%Y-%m-%d")
        cat_roman = {"1": "I", "2": "II", "3": "III"}.get(str(s.category), s.category)

        lines = [
            "",
            "    NATIONAL AERONAUTICS AND SPACE ADMINISTRATION",
            "    MATERIAL USAGE AGREEMENT (MUA)",
            "",
            f"    MUA No.:     {s.mua_id}",
            f"    Date:        {finalized}",
            f"    Center:      {s.center or 'N/A'}",
            f"    Standard:    {s.applied_standard}",
            f"    Category:    {cat_roman}",
            f"    Reviewer:    {s.reviewer or 'N/A'}",
            "",
            "    MATERIAL IDENTIFICATION",
            f"    Material:      {s.material_name}",
            f"    MAPTIS Code:   {s.maptis_code or 'N/A'}",
            f"    Material Class: {s.material_class or 'N/A'}",
            "",
            "    OPERATING ENVIRONMENT",
            f"    Medium:        {env.medium}",
            f"    O2:            {env.o2_percent}%",
            f"    Pressure:      {env.pressure_psia} psia",
            f"    Temperature:   {temp_range or 'N/A'}",
            f"    Location:      {env.location}",
            f"    Application:   {env.application or 'N/A'}",
            "",
        ]
        return "\n".join(lines)

    def _render_footer(self, s: MUASessionData) -> str:
        """Render document footer - deterministic."""
        lines = [
            "",
            "    APPROVALS",
            "",
            f"    Prepared by:   ___________________________    Date: __________",
            f"                   Materials Engineer",
            "",
            f"    Reviewed by:   ___________________________    Date: __________",
            f"                   {s.reviewer or 'Reviewer'}",
            "",
            f"    Approved by:   ___________________________    Date: __________",
            f"                   M&P Branch Chief",
            "",
            f"    Governing Standard: {s.applied_standard}",
            f"    MUA ID: {s.mua_id}",
            "",
        ]
        return "\n".join(lines)

    # -------------------------------------------------------------------------
    # LLM prose generation
    # -------------------------------------------------------------------------

    def _build_data_context(self, s: MUASessionData) -> str:
        """Build a structured summary of session data for the LLM."""
        lines = []

        # Ratings
        lines.append("TEST DATA SUMMARY:")
        if s.ratings:
            for r in s.ratings:
                status = r.rating or "no data"
                src = f" (Report: {r.report_number})" if r.report_number else ""
                lines.append(f"  {r.test_class}: {status}{src}")
        else:
            lines.append("  No MAPTIS test data records found.")

        # Gaps
        lines.append("\nIDENTIFIED DEFICIENCIES:")
        if s.gaps:
            for g in s.gaps:
                lines.append(f"  [{g.severity.upper()}] {g.dimension}: {g.description}")
                if g.disposition:
                    lines.append(f"    Disposition: {g.disposition}")
                if g.rationale:
                    lines.append(f"    Engineer rationale: {g.rationale}")
        else:
            lines.append("  No deficiencies identified.")

        # Evidence strength
        if s.evidence_strength:
            es = s.evidence_strength
            lines.append(f"\nEVIDENCE STRENGTH: {es.band} ({es.score:.2f})")
            if es.components:
                for k, v in es.components.items():
                    lines.append(f"  {k}: {v}")

        # Banners/warnings
        if s.banners:
            lines.append("\nNOTICES:")
            for b in s.banners:
                lines.append(f"  - {b}")

        # Constraints
        if s.constraints:
            lines.append("\nCONSTRAINTS FROM ACCEPTED GAPS:")
            for c in s.constraints:
                lines.append(f"  - {c}")

        return "\n".join(lines)

    def _build_precedent_context(self, precedents: List[MUAPrecedent]) -> str:
        """Build precedent examples for the LLM."""
        if not precedents:
            return "No precedent MUAs were found for this material/environment combination."

        lines = [
            f"PRECEDENT MUA EXAMPLES ({len(precedents)} found in corpus):",
            "Use these as reference for tone, structure, and technical language.",
            "",
        ]
        for i, p in enumerate(precedents, 1):
            lines.append(f"Precedent {i}: {p.mua_number}")
            lines.append(f"  Material: {p.material_name or 'N/A'}")
            lines.append(f"  Determination: {p.determination or 'N/A'}")
            if p.environment:
                lines.append(f"  Environment: {p.environment}")
            if p.rationale:
                # Truncate very long rationale but keep enough for style reference
                rat = p.rationale[:800]
                if len(p.rationale) > 800:
                    rat += "..."
                lines.append(f"  Rationale: {rat}")
            lines.append("")

        return "\n".join(lines)

    def _generate_prose(
        self,
        session: MUASessionData,
        data_context: str,
        precedent_context: str,
    ) -> str:
        """Call the LLM to generate the prose body of the MUA."""
        client = self._get_client()

        system_prompt = self._build_system_prompt()
        user_prompt = self._build_user_prompt(session, data_context, precedent_context)

        response = client.messages.create(
            model=self._model_id,
            max_tokens=4096,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )

        return response.content[0].text

    def _build_system_prompt(self) -> str:
        return """You are a NASA Materials and Processes (M&P) engineer writing a Material Usage Agreement (MUA) document per NASA-STD-6016C.

RULES:
1. Write in formal NASA engineering document style - concise, precise, authoritative
2. NEVER invent test data, report numbers, ratings, or material properties
3. Only state facts provided in the session data - if data is missing, say so
4. Reference the governing standard (NASA-STD-6016C) and specific clause numbers where applicable
5. Use professional third-person engineering prose, not bullet points or key-value dumps
6. Where gaps have been accepted with rationale, present the engineering basis clearly
7. If precedent MUA examples are provided, match their tone and technical depth
8. Structure the output with these numbered sections:
   1. PURPOSE AND SCOPE
   2. TEST DATA SUMMARY
   3. IDENTIFIED DEFICIENCIES AND DISPOSITIONS
   4. ENGINEERING RATIONALE
   5. MITIGATIONS AND OPERATIONAL CONTROLS
   6. VERIFICATION REQUIREMENTS
   7. REFERENCES AND TRACEABILITY

FORMAT RULES:
- Indent section content with 4 spaces
- Use section numbers (1., 2., etc.)
- Within sections, use paragraphs of prose, not key-value pairs
- Keep the total document body concise but complete (aim for 40-80 lines)
- Do NOT include the header or footer (those are already rendered separately)
- Do NOT include "========" borders or ASCII art"""

    def _build_user_prompt(
        self,
        session: MUASessionData,
        data_context: str,
        precedent_context: str,
    ) -> str:
        env = session.environment
        cat_roman = {"1": "I", "2": "II", "3": "III"}.get(
            str(session.category), session.category
        )

        return f"""Write the body sections of a Material Usage Agreement for:

Material: {session.material_name} ({session.maptis_code or 'no MAPTIS code'})
Category: {cat_roman}
Environment: {env.medium}, {env.o2_percent}% O2, {env.pressure_psia} psia, {env.location}
Application: {env.application or 'Not specified'}
Standard: {session.applied_standard}

{data_context}

---

{precedent_context}

---

Write sections 1-7 of the MUA body now. Present the data professionally.
Where evidence is insufficient, state that clearly and recommend appropriate action.
Where gaps have engineer-provided rationale, incorporate that rationale into a
proper engineering justification paragraph."""

    # -------------------------------------------------------------------------
    # Template-only fallback (no LLM)
    # -------------------------------------------------------------------------

    def _render_template_body(self, s: MUASessionData) -> str:
        """Render body using templates when LLM is unavailable."""
        env = s.environment
        cat_roman = {"1": "I", "2": "II", "3": "III"}.get(
            str(s.category), s.category
        )
        lines = []

        # Section 1
        lines.append("    1. PURPOSE AND SCOPE")
        lines.append("")
        lines.append(
            f"    This Material Usage Agreement documents the engineering evaluation"
            f" of {s.material_name} for use in a {env.location} environment"
            f" per {s.applied_standard}. The material is classified as Category"
            f" {cat_roman} based on the operating environment and identified"
            f" deficiencies."
        )
        if env.application:
            lines.append(
                f"    The intended application is: {env.application}."
            )
        lines.append("")

        # Section 2
        lines.append("    2. TEST DATA SUMMARY")
        lines.append("")
        if s.ratings:
            rated = [r for r in s.ratings if r.rating]
            unrated = [r for r in s.ratings if not r.rating]
            if rated:
                lines.append("    The following test data is available:")
                for r in rated:
                    lines.append(
                        f"      - {r.test_class}: Rating {r.rating}"
                        + (f" (Report {r.report_number})" if r.report_number else "")
                    )
            if unrated:
                missing = ", ".join(r.test_class for r in unrated)
                lines.append(
                    f"    No current test data is available for: {missing}."
                )
        else:
            lines.append(
                "    No MAPTIS test data records were found for this material"
                " in the queried environment."
            )
        lines.append("")

        # Section 3
        lines.append("    3. IDENTIFIED DEFICIENCIES AND DISPOSITIONS")
        lines.append("")
        if s.gaps:
            for g in s.gaps:
                sev = g.severity.upper()
                lines.append(
                    f"    {g.dimension} ({sev}): {g.description}"
                )
                if g.disposition:
                    lines.append(f"    Disposition: {g.disposition}")
                if g.rationale:
                    lines.append(f"    Rationale: {g.rationale}")
                lines.append("")
        else:
            lines.append("    No deficiencies were identified.")
            lines.append("")

        # Section 4
        lines.append("    4. ENGINEERING RATIONALE")
        lines.append("")
        if s.evidence_strength:
            es = s.evidence_strength
            lines.append(
                f"    The overall evidence strength is assessed as {es.band}"
                f" (score: {es.score:.3f})."
            )
        if s.precedents:
            lines.append(
                f"    {len(s.precedents)} precedent MUA(s) were identified"
                f" for similar materials."
            )
        elif not s.precedents:
            lines.append("    No precedent MUAs were found for this material.")
        lines.append("")

        # Section 5
        lines.append("    5. MITIGATIONS AND OPERATIONAL CONTROLS")
        lines.append("")
        accepted = [g for g in s.gaps if g.disposition and "Accept" in g.disposition]
        if accepted:
            for g in accepted:
                lines.append(
                    f"    For the {g.dimension} deficiency: operational use must"
                    f" remain within the bounds of the stated rationale."
                )
                if g.rationale:
                    lines.append(f"    Basis: {g.rationale}")
                lines.append("")
        else:
            lines.append("    No mitigations required.")
            lines.append("")

        # Section 6
        lines.append("    6. VERIFICATION REQUIREMENTS")
        lines.append("")
        open_gaps = [g for g in s.gaps if not g.disposition or "Accept" not in g.disposition]
        if open_gaps:
            lines.append(
                "    The following verification testing is required prior"
                " to material use:"
            )
            for g in open_gaps:
                lines.append(f"      - {g.dimension}: {g.description}")
        else:
            lines.append(
                "    No additional verification testing is required. All"
                " deficiencies have been dispositioned."
            )
        lines.append("")

        # Section 7
        lines.append("    7. REFERENCES AND TRACEABILITY")
        lines.append("")
        lines.append(f"    - {s.applied_standard}")
        if s.cited_evidence:
            for e in s.cited_evidence:
                lines.append(f"    - {e.get('source', 'Unknown source')}")
        if s.precedents:
            for p in s.precedents:
                lines.append(f"    - Precedent MUA: {p.mua_number}")
        lines.append("")

        return "\n".join(lines)
