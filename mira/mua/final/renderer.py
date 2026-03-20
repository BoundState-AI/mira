"""
MUA Final - LLM Document Renderer

Two-layer architecture:
  1. Deterministic shell: header, IDs, dates, classification, signatures
     (no LLM hallucination risk)
  2. LLM semantic layer: Claude renders rationale, gap assessments,
     engineering justification, and assessment summary using real MUA
     precedents from Postgres as style/content reference

The template fallback always produces a valid document if the LLM fails.

BoundState AI 2026
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

# ---------------------------------------------------------------------------
# LLM configuration -- direct API calls (no Bedrock for now)
# ---------------------------------------------------------------------------

DEFAULT_MODEL = "claude-sonnet-4-5-20250929"

# Bedrock support (uncomment when deploying to GovCloud):
# DEFAULT_MODEL_BEDROCK = "us-gov.anthropic.claude-sonnet-4-5-20250929-v1:0"
# USE_BEDROCK = os.getenv("USE_BEDROCK", "1").lower() in ("1", "true", "yes")
# BEDROCK_REGION = os.getenv("BEDROCK_REGION", "us-gov-west-1")


class MUADocumentRenderer:
    """
    Renders structured MUA session data into a professional NASA document.

    Two modes:
      - render()            -- LLM writes prose body, deterministic shell
      - render_without_llm() -- template fallback, no API call
    """

    def __init__(self, model_id: Optional[str] = None):
        self._model_id = model_id or DEFAULT_MODEL
        self._client = None

        # Bedrock init (uncomment when deploying to GovCloud):
        # if use_bedrock:
        #     from anthropic import AnthropicBedrock
        #     self._client = AnthropicBedrock(aws_region=BEDROCK_REGION)
        #     self._model_id = DEFAULT_MODEL_BEDROCK

    def _get_client(self):
        """Lazy-load Anthropic client (direct API)."""
        if self._client is None:
            from anthropic import Anthropic
            self._client = Anthropic()
        return self._client

    def render(self, session: MUASessionData) -> MUARenderedDocument:
        """
        Render a complete MUA document.  LLM writes the prose body;
        header and footer are deterministic.

        Falls back to template if LLM call fails.
        """
        header = self._render_header(session)
        footer = self._render_footer(session)

        try:
            data_context = self._build_data_context(session)
            precedent_context = self._build_precedent_context(session.precedents)
            prose = self._generate_prose(session, data_context, precedent_context)
        except Exception:
            logger.warning(
                "LLM render failed for %s -- falling back to template.",
                session.mua_id,
                exc_info=True,
            )
            prose = self._render_template_body(session)

        document_text = f"{header}\n{prose}\n{footer}"

        return MUARenderedDocument(
            mua_id=session.mua_id,
            document_text=document_text,
            model_used=self._model_id,
            precedents_used=len(session.precedents),
        )

    def render_without_llm(self, session: MUASessionData) -> MUARenderedDocument:
        """Template-only fallback.  No API call."""
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

    # -----------------------------------------------------------------------
    # Deterministic sections (no LLM)
    # -----------------------------------------------------------------------

    def _render_header(self, s: MUASessionData) -> str:
        env = s.environment
        temp_range = ""
        if env.temp_min_f is not None and env.temp_max_f is not None:
            temp_range = f"{env.temp_min_f} to {env.temp_max_f} degF"
        elif env.temp_max_f is not None:
            temp_range = f"up to {env.temp_max_f} degF"

        finalized = s.finalized_at or datetime.utcnow().strftime("%Y-%m-%d")
        cat = _to_roman(s.category)

        lines = [
            "",
            "    NATIONAL AERONAUTICS AND SPACE ADMINISTRATION",
            "    MATERIAL USAGE AGREEMENT (MUA)",
            "",
            f"    MUA No.:     {s.mua_id}",
            f"    Date:        {finalized}",
            f"    Center:      {s.center or 'N/A'}",
            f"    Standard:    {s.applied_standard}",
            f"    Category:    {cat}",
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
        lines = [
            "",
            "    APPROVALS",
            "",
            "    Prepared by:   ___________________________    Date: __________",
            "                   Materials Engineer",
            "",
            "    Reviewed by:   ___________________________    Date: __________",
            f"                   {s.reviewer or 'Reviewer'}",
            "",
            "    Approved by:   ___________________________    Date: __________",
            "                   M&P Branch Chief",
            "",
            f"    Governing Standard: {s.applied_standard}",
            f"    MUA ID: {s.mua_id}",
            "",
        ]
        return "\n".join(lines)

    # -----------------------------------------------------------------------
    # LLM prose generation
    # -----------------------------------------------------------------------

    def _build_data_context(self, s: MUASessionData) -> str:
        """Build structured summary of session data for the LLM."""
        lines = []

        # Ratings
        lines.append("TEST DATA SUMMARY:")
        if s.ratings:
            for r in s.ratings:
                status = r.rating or "no data"
                src = f" (Report: {r.report_number})" if r.report_number else ""
                current = ""
                if r.is_current is True:
                    current = " [current]"
                elif r.is_current is False:
                    current = " [expired]"
                lines.append(f"  {r.test_class}: {status}{src}{current}")
        else:
            lines.append("  No MAPTIS test data records found.")

        # Gaps with engineer dispositions
        lines.append("\nIDENTIFIED DEFICIENCIES:")
        if s.gaps:
            for g in s.gaps:
                lines.append(f"  [{g.severity.upper()}] {g.dimension}: {g.description}")
                if g.disposition:
                    lines.append(f"    Disposition: {g.disposition}")
                if g.rationale:
                    lines.append(f'    Engineer rationale: "{g.rationale}"')
        else:
            lines.append("  No deficiencies identified.")

        # Conflicts
        if s.conflicts:
            lines.append("\nCROSS-SOURCE CONFLICTS:")
            for c in s.conflicts:
                lines.append(f"  [{c.severity.upper()}] {c.description}")
                lines.append(f"    Sources: {c.source_a} vs {c.source_b}")
                if c.disposition:
                    lines.append(f"    Disposition: {c.disposition}")
                if c.rationale:
                    lines.append(f'    Rationale: "{c.rationale}"')

        # Envelope coverage
        if s.envelope:
            env = s.envelope
            lines.append(f"\nENVELOPE COVERAGE: {env.overall_status}")
            lines.append(f"  O2: {env.o2_status}, Pressure: {env.pressure_status}, "
                         f"Temperature: {env.temp_status}")
            lines.append(f"  Coverage ratio: {env.coverage_ratio:.0%}")
            for d in env.details:
                lines.append(f"  {d}")

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

        # Dependency warnings
        if s.dependency_warnings:
            lines.append("\nDEPENDENCY WARNINGS:")
            for w in s.dependency_warnings:
                lines.append(f"  - {w}")

        return "\n".join(lines)

    def _build_precedent_context(self, precedents: List[MUAPrecedent]) -> str:
        if not precedents:
            return "No precedent MUAs were found for this material/environment combination."

        supporting = [p for p in precedents if p.is_supporting]
        conflicting = [p for p in precedents if p.is_conflicting]

        lines = [
            f"PRECEDENT MUA EXAMPLES ({len(precedents)} found in corpus,"
            f" {len(supporting)} supporting, {len(conflicting)} conflicting):",
            "Use these as reference for tone, structure, and technical language.",
            "",
        ]
        for i, p in enumerate(precedents, 1):
            tag = "SUPPORTING" if p.is_supporting else "CONFLICTING"
            lines.append(f"Precedent {i}: {p.mua_number} [{tag}]")
            lines.append(f"  Material: {p.material_name or 'N/A'}")
            lines.append(f"  Determination: {p.determination or 'N/A'}")
            if p.environment:
                lines.append(f"  Environment: {p.environment}")
            if p.relevance_score is not None:
                lines.append(f"  Relevance: {p.relevance_score:.0%}")
            if p.relationship_explanation:
                lines.append(f"  Relationship: {p.relationship_explanation}")
            if p.rationale:
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
        """Call Claude to generate the prose body of the MUA."""
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
1. Write in formal NASA engineering document style - concise, precise, authoritative.
2. NEVER invent test data, report numbers, ratings, or material properties.
3. Only state facts provided in the session data - if data is missing, say so.
4. Reference the governing standard (NASA-STD-6016C) and specific clause numbers where applicable.
5. Use professional third-person engineering prose, not bullet points or key-value dumps.
6. Where gaps have been accepted with rationale, QUOTE the engineer's rationale verbatim and present the engineering basis clearly.
7. If precedent MUA examples are provided, match their tone and technical depth.

SAFETY-CRITICAL LANGUAGE RULES:
8. Use "Evidence Strength" everywhere, NEVER "confidence" or "confidence score".
9. Use hedged language: "may be acceptable", "the evidence suggests", "may be applicable".
   NEVER say "is approved", "is safe", or "is acceptable" without qualification.
10. Tag engineering judgment claims explicitly: "(Engineering assessment)".
11. When conflicts exist between sources, present both sides and state the disposition.
12. Missing data scores 0.0 (unknown), not 0.5 (neutral) -- present accordingly.

STRUCTURE:
Output these numbered sections:
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
- Do NOT include the header or footer (those are rendered separately)
- Do NOT include "========" borders or ASCII art"""

    def _build_user_prompt(
        self,
        session: MUASessionData,
        data_context: str,
        precedent_context: str,
    ) -> str:
        env = session.environment
        cat = _to_roman(session.category)

        novel_note = ""
        if session.is_novel_material:
            novel_note = "\nNOTE: This is a NOVEL material with no prior MUA precedents. A Qualification Test Plan may be required."

        process_note = ""
        if session.is_process_sensitive:
            process_note = "\nNOTE: This material is PROCESS-SENSITIVE. Cure conditions and processing parameters affect material properties."

        return f"""Write the body sections of a Material Usage Agreement for:

Material: {session.material_name} ({session.maptis_code or 'no MAPTIS code'})
Category: {cat}
Environment: {env.medium}, {env.o2_percent}% O2, {env.pressure_psia} psia, {env.location}
Application: {env.application or 'Not specified'}
Standard: {session.applied_standard}
{novel_note}{process_note}

{data_context}

---

{precedent_context}

---

Write sections 1-7 of the MUA body now. Present the data professionally.
Where evidence is insufficient, state that clearly and recommend appropriate action.
Where gaps have engineer-provided rationale, incorporate that rationale into a
proper engineering justification paragraph using their exact words.
Where conflicts exist, present both sides and the engineer's disposition."""

    # -----------------------------------------------------------------------
    # Template-only fallback (no LLM)
    # -----------------------------------------------------------------------

    def _render_template_body(self, s: MUASessionData) -> str:
        """Render body using templates when LLM is unavailable."""
        env = s.environment
        cat = _to_roman(s.category)
        lines = []

        # Section 1
        lines.append("    1. PURPOSE AND SCOPE")
        lines.append("")
        lines.append(
            f"    This Material Usage Agreement documents the engineering evaluation"
            f" of {s.material_name} for use in a {env.location} environment"
            f" per {s.applied_standard}. The material is classified as Category"
            f" {cat} based on the operating environment and identified"
            f" deficiencies."
        )
        if env.application:
            lines.append(f"    The intended application is: {env.application}.")
        if s.is_novel_material:
            lines.append(
                "    This material is flagged as novel for this application."
                " A Qualification Test Plan may be required."
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
                    line = f"      - {r.test_class}: Rating {r.rating}"
                    if r.report_number:
                        line += f" (Report {r.report_number})"
                    if r.is_current is False:
                        line += " [EXPIRED]"
                    lines.append(line)
            if unrated:
                missing = ", ".join(r.test_class for r in unrated)
                lines.append(f"    No current test data is available for: {missing}.")
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
                lines.append(f"    {g.dimension.title()} ({g.severity.upper()}): {g.description}")
                if g.disposition:
                    lines.append(f"    Disposition: {g.disposition}")
                if g.rationale:
                    lines.append(f'    Rationale: "{g.rationale}"')
                lines.append("")
        else:
            lines.append("    No deficiencies were identified.")
            lines.append("")

        if s.conflicts:
            lines.append("    Cross-Source Conflicts:")
            lines.append("")
            for c in s.conflicts:
                lines.append(
                    f"    {c.severity.upper()} CONFLICT: {c.source_a}"
                    f" vs {c.source_b} — {c.description}"
                )
                if c.disposition:
                    lines.append(f"    Disposition: {c.disposition}")
                if c.rationale:
                    lines.append(f'    Rationale: "{c.rationale}"')
                lines.append("")

        # Section 4
        lines.append("    4. ENGINEERING RATIONALE")
        lines.append("")
        if s.evidence_strength:
            es = s.evidence_strength
            lines.append(
                f"    Evidence Strength: {es.band} ({es.score:.2f})"
            )
        if s.precedents:
            supporting = [p for p in s.precedents if p.is_supporting]
            lines.append(
                f"    {len(supporting)} supporting precedent MUA(s) were"
                f" identified for similar materials in similar environments."
            )
            for p in supporting[:3]:
                det = p.determination or "N/A"
                lines.append(
                    f"    - {p.mua_number} ({p.material_name or 'N/A'},"
                    f" {det})"
                )
        else:
            lines.append(
                "    No precedent MUAs were found for this material."
                " (Engineering assessment)"
            )
        lines.append("")

        # Section 5
        lines.append("    5. MITIGATIONS AND OPERATIONAL CONTROLS")
        lines.append("")
        accepted = [g for g in s.gaps if g.disposition and "Accept" in str(g.disposition)]
        if accepted:
            for g in accepted:
                lines.append(
                    f"    {g.dimension.title()}: Operational use must remain within"
                    f" the bounds of the stated rationale. Any deviation"
                    f" invalidates this acceptance."
                )
                if g.rationale:
                    lines.append(f'    Basis: "{g.rationale}"')
                lines.append("")
        if s.is_process_sensitive and s.process_params:
            lines.append(
                "    Process-sensitive material: adherence to specified cure"
                " parameters is required."
            )
            lines.append("")
        if not accepted and not s.is_process_sensitive:
            lines.append("    No mitigations required.")
            lines.append("")

        # Section 6
        lines.append("    6. VERIFICATION REQUIREMENTS")
        lines.append("")
        open_gaps = [
            g for g in s.gaps
            if not g.disposition or "Accept" not in str(g.disposition)
        ]
        if open_gaps:
            lines.append(
                "    The following verification testing is required prior to"
                " material use:"
            )
            for g in open_gaps:
                lines.append(f"      - {g.dimension.title()}: {g.description}")
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
        if s.precedents:
            for p in s.precedents:
                tag = "supporting" if p.is_supporting else "conflicting"
                lines.append(f"    - Precedent MUA: {p.mua_number} ({tag})")
        if s.dependency_warnings:
            lines.append("")
            lines.append("    Dependency warnings:")
            for w in s.dependency_warnings:
                lines.append(f"      [!] {w}")
        lines.append("")

        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _to_roman(category: str) -> str:
    """Convert category to Roman numeral."""
    return {"1": "I", "2": "II", "3": "III"}.get(str(category), str(category))
