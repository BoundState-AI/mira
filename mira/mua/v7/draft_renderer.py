"""MUA v7 Draft Renderer -- Template-first NASA 7-section document generation.

Replaces both the v1 generator (439 lines, full format) and v6 draft generator
(15 lines, too simple) with a two-layer approach:

    Layer 1 -- Template-based structure (deterministic, always valid).
    Layer 2 -- LLM polish (optional enhancement, never a dependency).

Design principle
----------------
The template MUST produce valid output even if the LLM fails entirely.
LLM polish is an enhancement, not a dependency.  Every section has a
deterministic template path that produces compliant NASA-format text from
structured data alone.

Sections
--------
1. Header          -- MUA ID, program, material (resolved), environment, category
2. Ratings         -- Per test class with MAPTIS evidence and currency flags
3. Gap Profile     -- Identified gaps + engineer dispositions + routing implications
4. Rationale       -- Synthesized reasoning chain with precedent citations
5. Mitigations     -- Operational constraints derived from gaps and conflicts
6. Verification    -- Required tests to close gaps flagged for testing
7. Traceability    -- Every evidence item cited, linked to source
"""

from __future__ import annotations

import threading
from datetime import datetime, timezone
from typing import Optional

from mira.mua.v7.models import (
    CategoryRoutingResult,
    ClaimType,
    ConflictFound,
    DeterminationStatus,
    DraftSection,
    EvidenceStrengthBand,
    GapDecision,
    GapDecisionType,
    GapIdentified,
    InvestigationResult,
    MUACategory,
    MUADraft,
    MaterialClass,
    PrecedentDecision,
    PrecedentMatch,
    ProcessParams,
    ReviewDecisionType,
    ReviewDecisions,
    TestDataRecord,
)

# ---------------------------------------------------------------------------
# Module-level sequence counter for MUA ID generation
# ---------------------------------------------------------------------------

_mua_id_lock = threading.Lock()
_mua_id_counter: int = 0


def _next_sequence() -> int:
    """Return the next global MUA sequence number (thread-safe)."""
    global _mua_id_counter
    with _mua_id_lock:
        _mua_id_counter += 1
        return _mua_id_counter


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_PROCESS_SENSITIVE_CLASSES = frozenset(
    {
        MaterialClass.ADHESIVE,
        MaterialClass.COMPOSITE,
        MaterialClass.POTTING,
        MaterialClass.SEALANT,
    }
)

_CURRENCY_LABEL = {
    True: "Current",
    False: "Expired",
    None: "Unknown",
}

_SECTION_TITLES = {
    1: "Header",
    2: "Ratings",
    3: "Gap Profile",
    4: "Rationale",
    5: "Mitigations / Controls",
    6: "Verification Requirements",
    7: "Traceability & Citations",
}


# ---------------------------------------------------------------------------
# DraftRenderer
# ---------------------------------------------------------------------------


class DraftRenderer:
    """Renders full NASA-format MUA documents.

    Two-layer generation:

    1. Template-based structure (deterministic, always valid).
    2. LLM polish (optional enhancement, never a dependency).

    Usage::

        renderer = DraftRenderer()
        draft = renderer.render(investigation, review_decisions, category_routing)
    """

    # ---- public API -------------------------------------------------------

    def render(
        self,
        investigation: InvestigationResult,
        review_decisions: ReviewDecisions,
        category_routing: CategoryRoutingResult,
        *,
        program: Optional[str] = None,
    ) -> MUADraft:
        """Render a complete MUA draft from investigation + review decisions.

        Parameters
        ----------
        investigation:
            The completed Step 2 investigation result.
        review_decisions:
            Engineer decisions from Step 3 review.
        category_routing:
            Category routing result (I / II / III) with audit trail.
        program:
            Optional program name for the header.

        Returns
        -------
        MUADraft
            A fully rendered MUA draft ready for engineer review.

        Notes
        -----
        Category III (Appendix E) produces a MIUL rationale-code report,
        NOT a full 7-section MUA.  Per 6016C, "no MUA form is submitted"
        for Category III items.
        """
        # Check output type: Cat III → MIUL rationale code, not full MUA
        output_type = category_routing.output_type or {}
        if output_type.get("output_format") == "miul_rationale_code":
            return self._render_miul_rationale_code(
                investigation, review_decisions, category_routing, program=program
            )

        return self._render_full_mua(
            investigation, review_decisions, category_routing, program=program
        )

    def _render_full_mua(
        self,
        investigation: InvestigationResult,
        review_decisions: ReviewDecisions,
        category_routing: CategoryRoutingResult,
        *,
        program: Optional[str] = None,
    ) -> MUADraft:
        """Render a full 7-section MUA document (Category I or II)."""
        mua_id = self._generate_mua_id()

        sections = [
            self._render_header(investigation, category_routing, mua_id, program),
            self._render_ratings(investigation.test_data),
            self._render_gap_profile(
                investigation.gaps,
                review_decisions.gap_decisions,
                category_routing,
            ),
            self._render_rationale(investigation, review_decisions),
            self._render_mitigations(
                review_decisions,
                investigation.conflicts,
                category_routing,
            ),
            self._render_verification(review_decisions.gap_decisions),
            self._render_traceability(investigation, review_decisions),
        ]

        full_text = self._assemble_document(sections)

        # Collect cited precedent MUA numbers
        cited = self._collect_cited_precedents(investigation, review_decisions)

        return MUADraft(
            mua_id=mua_id,
            sections=sections,
            category=category_routing.category,
            evidence_strength=investigation.evidence_strength,
            fact_check_results=[],  # populated by FactChecker post-generation
            cited_precedents=cited,
            full_text=full_text,
        )

    # ---- Category III: MIUL Rationale Code Report --------------------------

    def _render_miul_rationale_code(
        self,
        investigation: InvestigationResult,
        review_decisions: ReviewDecisions,
        category_routing: CategoryRoutingResult,
        *,
        program: Optional[str] = None,
    ) -> MUADraft:
        """Render a MIUL rationale-code report for Category III.

        Per JSC 27301F, Category III items have an approved Appendix E
        rationale code and are reported through the MIUL system.
        NO full MUA form is submitted.

        The report contains 4 sections:
            1. Disposition Header — material, environment, code, category
            2. Appendix E Rationale — code template with engineer fill-ins
            3. Ratings Summary — compact MAPTIS data
            4. Traceability — evidence citations
        """
        # Use a disposition ID instead of MUA ID (no MUA form)
        year = datetime.now(timezone.utc).year
        seq = _next_sequence()
        disposition_id = f"MIUL-DISP-{year}-{seq:04d}"

        app_b = category_routing.appendix_b_evaluation or {}
        code = app_b.get("code", "???")
        code_desc = app_b.get("code_description", "")
        rationale_template = app_b.get("rationale_template", "")
        citation = app_b.get("citation", "")

        # ── Section 1: Disposition Header ──
        mat = investigation.material
        env = investigation.environment
        material_name = mat.resolved_name or mat.input_text
        material_code = mat.material_code or "N/A"

        header_lines = [
            f"Disposition ID:    {disposition_id}",
            f"Category:          III (MIUL Rationale Code)",
            f"Output Type:       MIUL Rationale Code — No MUA form submitted",
            f"",
            f"Material:          {material_name} ({material_code})",
            f"Material Class:    {mat.material_class.value if mat.material_class else 'N/A'}",
            f"Program:           {program or 'N/A'}",
            f"",
            f"Environment:",
            f"  Medium:          {env.medium}",
            f"  O2:              {env.o2_percent:.1f}%",
            f"  Pressure:        {env.pressure_psia:.1f} psia",
            f"  Temperature:     {env.temp_min_f:.0f} to {env.temp_max_f:.0f} degF",
            f"  Location:        {env.location}",
            f"  Application:     {env.application}",
            f"",
            f"Appendix E Code:   {code} — {code_desc}",
            f"Citation:          {citation}",
            f"Authority:         {category_routing.authority_pack}",
        ]

        section_header = DraftSection(
            section_number=1,
            title="Disposition Header",
            content="\n".join(header_lines),
            editable=False,
        )

        # ── Section 2: Appendix E Rationale ──
        rationale_lines = [
            f"Appendix E Code {code}: {code_desc}",
            f"",
        ]

        if rationale_template:
            rationale_lines.append("--- Rationale ---")
            rationale_lines.append("")
            rationale_lines.append(rationale_template)
            rationale_lines.append("")
            rationale_lines.append(
                "[ENGINEER: Complete all bracketed items above before approval]"
            )
        else:
            rationale_lines.append(
                "No rationale template available for this code. "
                "Provide rationale manually."
            )

        # Evidence used
        evidence_items = app_b.get("evidence", [])
        if evidence_items:
            rationale_lines.append("")
            rationale_lines.append("--- Supporting Evidence ---")
            for item in evidence_items:
                rationale_lines.append(f"  - {item}")

        section_rationale = DraftSection(
            section_number=2,
            title="Appendix E Rationale",
            content="\n".join(rationale_lines),
            editable=True,
        )

        # ── Section 3: Ratings Summary ──
        test_data = investigation.test_data
        if test_data:
            ratings_lines: list[str] = []
            for rec in test_data:
                rating_str = rec.rating or "U"
                currency = _CURRENCY_LABEL.get(rec.is_current, "Unknown")
                ratings_lines.append(
                    f"  {rec.test_class:12s}  Rating: {rating_str}  "
                    f"Currency: {currency}"
                )
            current_count = sum(1 for r in test_data if r.is_current is True)
            ratings_lines.append("")
            ratings_lines.append(
                f"Summary: {len(test_data)} record(s), "
                f"{current_count} current. All ratings A or B (Cat III requirement met)."
            )
            ratings_content = "\n".join(ratings_lines)
        else:
            ratings_content = (
                "No MAPTIS test data records found. "
                "Cat III disposition based on Appendix E code only."
            )

        section_ratings = DraftSection(
            section_number=3,
            title="Ratings Summary",
            content=ratings_content,
            editable=False,
        )

        # ── Section 4: Traceability ──
        trace_lines: list[str] = []

        # Precedent citations (compact)
        all_precedents = (
            investigation.supporting_precedents
            + investigation.conflicting_precedents
        )
        if all_precedents:
            trace_lines.append("--- Precedent Evidence ---")
            for prec in all_precedents[:10]:  # Cap at 10 for compact report
                trace_lines.append(
                    f"  [{prec.mua_number}] {prec.material_designation} — "
                    f"{prec.determination.value} — "
                    f"Relevance: {prec.relevance_score:.2f}"
                )
            if len(all_precedents) > 10:
                trace_lines.append(
                    f"  ... and {len(all_precedents) - 10} more precedents"
                )
            trace_lines.append("")

        trace_lines.append(f"Governing Standard: NASA-STD-6016C")
        trace_lines.append(f"Disposition Code:   Appendix E, Code {code}")
        trace_lines.append(f"Approval Chain:     Hardware M&P -> NASA M&P (via MIUL acceptance)")

        section_trace = DraftSection(
            section_number=4,
            title="Traceability",
            content="\n".join(trace_lines),
            editable=False,
        )

        sections = [section_header, section_rationale, section_ratings, section_trace]
        full_text = self._assemble_document(sections)
        cited = self._collect_cited_precedents(investigation, review_decisions)

        return MUADraft(
            mua_id=disposition_id,
            sections=sections,
            category=category_routing.category,
            evidence_strength=investigation.evidence_strength,
            fact_check_results=[],
            cited_precedents=cited,
            full_text=full_text,
        )

    # ---- MUA ID generation ------------------------------------------------

    @staticmethod
    def _generate_mua_id() -> str:
        """Generate a unique MUA identifier.

        Format: ``MUA-MIRA-YYYY-NNNN`` where YYYY is the current year and
        NNNN is a zero-padded sequence number.
        """
        year = datetime.now(timezone.utc).year
        seq = _next_sequence()
        return f"MUA-MIRA-{year}-{seq:04d}"

    # ---- section renderers ------------------------------------------------

    def _render_header(
        self,
        investigation: InvestigationResult,
        routing: CategoryRoutingResult,
        mua_id: str,
        program: Optional[str],
    ) -> DraftSection:
        """Section 1: Header -- Appendix D-style identification block."""
        mat = investigation.material
        env = investigation.environment

        material_name = mat.resolved_name or mat.input_text
        material_code = mat.material_code or "N/A"
        resolution_label = mat.status.value.upper()
        hardware_label = env.application or "N/A"
        req_deviated = "NASA-STD-6016C / JSC-27301F M&P screening requirements"
        if routing.routing_basis:
            citations = [
                str(rule.get("citation", "")).strip()
                for rule in routing.routing_basis
                if str(rule.get("citation", "")).strip()
            ]
            if citations:
                req_deviated = "; ".join(citations[:2])

        lines = [
            "JSC MATERIALS USAGE AGREEMENT",
            "Form Basis: JSC 27301F Appendix D (D-2) field layout for Cat I/II",
            "",
            f"MUA NUMBER:                {mua_id}",
            f"USER MUA NUMBER:           {mua_id}",
            "REV:                       DRAFT",
            "PAGE:                      1 OF 2",
            "",
            f"TITLE:                     {hardware_label}",
            f"CATEGORY:                  {routing.category.value}",
            "EFFECTIVITY:               Pending review disposition",
            "TYPE OF DEVIATION:         MATERIAL / PROCESS USAGE DEVIATION",
            f"REQUIREMENT DEVIATED:      {req_deviated}",
            "",
            f"PROGRAM / PROJECT:         {program or 'N/A'}",
            "EQUIPMENT PART NUMBER(S):  N/A",
            "MANUFACTURER:              N/A",
            f"MATERIAL DESIGNATION:      {material_name}",
            f"SPECIFICATION:             MAPTIS code {material_code}",
            f"MATERIAL CODE:             {material_code}",
            f"MATERIAL CLASS:            {mat.material_class.value if mat.material_class else 'N/A'}",
            f"RESOLUTION STATUS:         {resolution_label}",
            f"",
            "ENVIRONMENT / APPLICATION:",
            f"  LOCATION:                {env.location}",
            f"  HABITABILITY:            {'HABITABLE' if env.location.lower().startswith('hab') else 'NONHABITABLE'}",
            f"  PRESSURE (PSIA):         {env.pressure_psia:.1f}",
            f"  TEMPERATURE (DEGF):      {env.temp_min_f:.0f} to {env.temp_max_f:.0f}",
            f"  MEDIA:                   {env.medium}",
            f"  O2 PERCENT:              {env.o2_percent:.1f}%",
            f"  APPLICATION:             {hardware_label}",
            f"",
            f"AUTHORITY PACK:            {routing.authority_pack}",
            "RATIONALE:                 See Section 4 (Me-Too Rationale) and supporting investigation attachment.",
            "NOTE:                      Full MUA form is used for Cat I/II. Cat III uses MIUL rationale code only.",
        ]

        if investigation.banners:
            lines.append("")
            lines.append("Banners:")
            for banner in investigation.banners:
                lines.append(f"  [!] {banner}")

        if self._is_process_sensitive(investigation):
            lines.extend(self._render_process_params_header(investigation.process_params))

        return DraftSection(
            section_number=1,
            title=_SECTION_TITLES[1],
            content="\n".join(lines),
            editable=False,
        )

    def _render_ratings(self, test_data: list[TestDataRecord]) -> DraftSection:
        """Section 2: Ratings -- concise screening summary for the form body."""
        if not test_data:
            content = (
                "SCREENING SUMMARY\n"
                "- No MAPTIS test data records were found for this material in the queried environment.\n"
                "- Engineering disposition required for unrated classes.\n"
                "- Detailed investigation data is recorded in the supporting attachment package."
            )
            return DraftSection(
                section_number=2,
                title=_SECTION_TITLES[2],
                content=content,
                editable=True,
            )

        # Group by test class
        by_class: dict[str, list[TestDataRecord]] = {}
        for rec in test_data:
            by_class.setdefault(rec.test_class, []).append(rec)

        lines: list[str] = ["SCREENING SUMMARY"]
        for test_class in sorted(by_class.keys()):
            records = by_class[test_class]
            ratings = [r.rating or "U" for r in records]
            rating_summary = ", ".join(sorted(set(ratings)))
            lines.append(
                f"- {test_class}: {len(records)} record(s); ratings observed: {rating_summary}"
            )

        # Summary counts
        current_count = sum(1 for r in test_data if r.is_current is True)
        expired_count = sum(1 for r in test_data if r.is_current is False)
        unknown_count = sum(1 for r in test_data if r.is_current is None)
        lines.append("")
        lines.append(
            f"- Data currency: {current_count} current, {expired_count} expired, {unknown_count} unknown."
        )
        lines.append(
            "- Full record-level detail (test numbers, reports, dates) is preserved in the supporting investigation attachment."
        )

        return DraftSection(
            section_number=2,
            title=_SECTION_TITLES[2],
            content="\n".join(lines),
            editable=True,
        )

    def _render_gap_profile(
        self,
        gaps: list[GapIdentified],
        gap_decisions: list[GapDecision],
        routing: CategoryRoutingResult,
    ) -> DraftSection:
        """Section 3: Gap Profile -- gaps, dispositions, and routing implications."""
        if not gaps:
            content = (
                "No gaps were identified in the available evidence for "
                "the queried material and environment combination."
            )
            return DraftSection(
                section_number=3,
                title=_SECTION_TITLES[3],
                content=content,
                editable=True,
            )

        # Build a lookup of gap decisions by gap_id
        decision_map: dict[str, GapDecision] = {
            gd.gap_id: gd for gd in gap_decisions
        }

        lines: list[str] = []
        accepted_count = 0
        testing_count = 0

        for gap in gaps:
            decision = decision_map.get(gap.gap_id)
            lines.append(f"GAP: {gap.gap_id}")
            lines.append(f"  Dimension:    {gap.dimension}")
            lines.append(f"  Severity:     {gap.severity}")
            lines.append(f"  Description:  {gap.description}")
            if gap.query_value:
                lines.append(f"  Query Value:  {gap.query_value}")
            if gap.nearest_data:
                lines.append(f"  Nearest Data: {gap.nearest_data}")

            if decision:
                disposition = decision.decision.value.replace("_", " ").title()
                lines.append(f"  Disposition:  {disposition}")
                lines.append(f"  Rationale:    \"{decision.rationale}\"")
                if decision.decision == GapDecisionType.ACCEPT_WITH_RATIONALE:
                    accepted_count += 1
                elif decision.decision == GapDecisionType.FLAG_FOR_TESTING:
                    testing_count += 1
            else:
                lines.append("  Disposition:  PENDING -- no engineer decision recorded")
            lines.append("")

        # Routing implications
        lines.append("--- Category Routing Implications ---")
        lines.append(f"Current Category: {routing.category.value}")

        if testing_count > 0:
            lines.append(
                f"  {testing_count} gap(s) flagged for testing. "
                f"See Section 6 (Verification Requirements)."
            )

        critical_gaps = [g for g in gaps if g.severity == "critical"]
        if critical_gaps:
            lines.append(
                f"  [!] {len(critical_gaps)} critical gap(s) identified. "
                f"Category routing may require elevation."
            )

        if routing.routing_basis:
            lines.append("")
            lines.append("Routing basis:")
            for rule in routing.routing_basis:
                rule_id = rule.get("rule_id") or rule.get("rule") or "unknown"
                rule_desc = (
                    rule.get("rule_description")
                    or rule.get("result")
                    or ""
                )
                citation = rule.get("citation") or ""
                if citation:
                    lines.append(f"  - {rule_id}: {rule_desc} ({citation})")
                else:
                    lines.append(f"  - {rule_id}: {rule_desc}")

        return DraftSection(
            section_number=3,
            title=_SECTION_TITLES[3],
            content="\n".join(lines),
            editable=True,
        )

    def _render_rationale(
        self,
        investigation: InvestigationResult,
        review_decisions: ReviewDecisions,
    ) -> DraftSection:
        """Section 4: Rationale -- form-ready "me-too" rationale narrative.

        The investigation packet stays in supporting attachments; this section
        captures the signed-review argument:
        1) which historical acceptances are materially similar,
        2) why they were accepted,
        3) which of those conditions the engineer confirms apply now.
        """
        lines: list[str] = []
        strength = investigation.evidence_strength
        band_label = strength.band.value if strength.band else "insufficient"
        material_name = (
            investigation.material.resolved_name
            or investigation.material.input_text
        )

        precedent_decision_map: dict[str, PrecedentDecision] = {
            pd.mua_number: pd for pd in review_decisions.precedent_decisions
        }
        conflict_decision_map = {
            cd.conflict_id: cd for cd in review_decisions.conflict_decisions
        }

        included_supporting = self._get_included_precedents(
            investigation.supporting_precedents,
            precedent_decision_map,
            ReviewDecisionType.INCLUDE_SUPPORTING,
        )
        included_context = self._get_included_precedents(
            investigation.supporting_precedents
            + investigation.conflicting_precedents,
            precedent_decision_map,
            ReviewDecisionType.INCLUDE_CONTEXT,
        )
        approved_count = sum(
            1
            for p in included_supporting
            if p.determination == DeterminationStatus.APPROVED
        )

        env = investigation.environment
        medium_upper = (env.medium or "").upper()
        is_o2_service = env.is_enriched_o2 or medium_upper in (
            "GOX",
            "LOX",
            "OXYGEN",
            "O2",
            "ENRICHED_AIR",
            "ENRICHED_O2",
        )
        lines.append("ME-TOO RATIONALE (PRECEDENT CONSISTENCY)")
        lines.append(
            f"- Material and use case: {material_name} in {env.medium} service "
            f"at {env.pressure_psia:.1f} psia and {env.temp_min_f:.0f} to {env.temp_max_f:.0f} degF."
        )
        if env.is_hydrogen_service:
            lines.append(
                "- Hydrogen assessment focus: whether this material is susceptible to "
                "hydrogen embrittlement in the stated envelope, and how severe that risk is."
            )
        if is_o2_service:
            lines.append(
                "- Oxygen assessment focus: whether this material presents ignition / "
                "combustion hazard in the stated oxygen environment."
            )
        lines.append(
            f"- Evidence strength band: {band_label.upper()} ({strength.score:.2f})."
        )
        lines.append("")

        if included_supporting:
            lines.append(
                f"Supporting precedents selected by review: {len(included_supporting)} "
                f"({approved_count} with approved determinations)."
            )
            lines.append("Applicable acceptance reasons from prior decisions:")
            for idx, prec in enumerate(included_supporting[:6], 1):
                reason = (
                    prec.supporting_rationale
                    or prec.relationship_explanation
                    or prec.rationale_excerpt
                    or "Prior acceptance in a comparable material/environment configuration."
                )
                reason = reason.strip().strip('"')
                relationship = (
                    prec.relationship_type.value.replace("_", " ")
                    if prec.relationship_type
                    else "relationship not classified"
                )
                lines.append(f"{idx}. [{prec.mua_number}] {reason}")
                lines.append(
                    f"   Match: {relationship}; Relevance: {prec.relevance_score:.0%}."
                )
                pd = precedent_decision_map.get(prec.mua_number)
                if pd and pd.rationale:
                    lines.append(f'   Engineer confirmation: "{pd.rationale}"')
        elif investigation.is_novel_material:
            lines.append(
                "No prior supporting precedents were selected for this "
                "material/environment pair; this is treated as a novel "
                "application pending additional qualification."
            )
        else:
            lines.append(
                "No supporting precedents were selected for this case; "
                "the rationale relies on direct MAPTIS evidence and gap dispositions."
            )

        if included_context:
            context_refs = ", ".join(p.mua_number for p in included_context[:6])
            lines.append("")
            lines.append(
                f"Context precedents reviewed (non-primary basis): {context_refs}."
            )

        if investigation.bok_findings:
            lines.append("")
            lines.append("Standards / BoK context considered:")
            for hit in investigation.bok_findings[:4]:
                parts: list[str] = []
                if hit.source:
                    parts.append(hit.source)
                if hit.section:
                    parts.append(hit.section)
                if hit.page:
                    parts.append(f"p.{hit.page}")
                locator = ", ".join(parts) if parts else "BoK reference"
                lines.append(
                    f"- [{hit.domain.upper()}] {locator}: {hit.excerpt}"
                )

        accepted_gaps = [
            gd
            for gd in review_decisions.gap_decisions
            if gd.decision == GapDecisionType.ACCEPT_WITH_RATIONALE
        ]
        if accepted_gaps:
            lines.append("")
            lines.append("Accepted evidence gaps (engineer-owned rationale):")
            for gd in accepted_gaps:
                gap_obj = self._find_gap(investigation.gaps, gd.gap_id)
                gap_label = (
                    gap_obj.dimension.replace("_", " ").title()
                    if gap_obj
                    else gd.gap_id
                )
                lines.append(f'- {gap_label}: "{gd.rationale}"')

        testing_gaps = [
            gd
            for gd in review_decisions.gap_decisions
            if gd.decision == GapDecisionType.FLAG_FOR_TESTING
        ]
        if testing_gaps:
            lines.append("")
            lines.append("Open gaps requiring verification before closeout:")
            for gd in testing_gaps:
                gap_obj = self._find_gap(investigation.gaps, gd.gap_id)
                gap_label = (
                    gap_obj.dimension.replace("_", " ").title()
                    if gap_obj
                    else gd.gap_id
                )
                lines.append(f'- {gap_label}: "{gd.rationale}"')

        if investigation.conflicts:
            lines.append("")
            lines.append("Conflict dispositions:")
            for conflict in investigation.conflicts:
                cd = conflict_decision_map.get(conflict.conflict_id)
                decision_text = (
                    cd.decision.value.replace("_", " ").title()
                    if cd
                    else "Pending Review"
                )
                rationale_text = f' "{cd.rationale}"' if cd and cd.rationale else ""
                lines.append(
                    f"- {conflict.conflict_id} ({conflict.severity.value}): "
                    f"{conflict.description} | Disposition: {decision_text}.{rationale_text}"
                )

        lines.append("")
        lines.append("Assessment Statement:")
        if band_label in ("strong", "moderate"):
            lines.append(
                "This application may be acceptable when operated within the "
                "confirmed bounds above and under the controls in Section 5. "
                "(Engineering assessment)"
            )
        elif band_label == "weak":
            lines.append(
                "Evidence is limited; additional verification is recommended "
                "before final disposition. (Engineering assessment)"
            )
        else:
            lines.append(
                "Evidence is insufficient for disposition without additional "
                "test data. (Engineering assessment)"
            )

        return DraftSection(
            section_number=4,
            title=_SECTION_TITLES[4],
            content="\n".join(lines),
            editable=True,
        )

    def _render_mitigations(
        self,
        review_decisions: ReviewDecisions,
        conflicts: list[ConflictFound],
        routing: CategoryRoutingResult,
    ) -> DraftSection:
        """Section 5: Mitigations / Controls -- operational constraints."""
        lines: list[str] = [
            "CONTROLLED USE CONDITIONS",
            (
                "This MUA is valid only for the material, form, processing, and "
                "environment captured in Section 1 and Section 4."
            ),
            "",
        ]

        accepted_gaps = [
            gd
            for gd in review_decisions.gap_decisions
            if gd.decision == GapDecisionType.ACCEPT_WITH_RATIONALE
        ]

        if accepted_gaps:
            lines.append("--- Constraints from Accepted Gaps ---")
            lines.append("")
            for gd in accepted_gaps:
                lines.append(f"Gap {gd.gap_id}:")
                lines.append(
                    "  Use is bounded by the engineer rationale recorded in review:"
                )
                lines.append(f"  \"{gd.rationale}\"")
                lines.append(
                    "  Any deviation from these conditions requires re-review."
                )
                lines.append("")

        hard_conflicts = [c for c in conflicts if c.severity.value == "hard"]
        soft_conflicts = [c for c in conflicts if c.severity.value == "soft"]

        if hard_conflicts:
            lines.append("--- Controls from Hard Conflicts ---")
            lines.append("")
            for conflict in hard_conflicts:
                lines.append(f"Conflict {conflict.conflict_id} ({conflict.severity.value}):")
                lines.append(f"  {conflict.description}")
                lines.append(f"  Required control: {conflict.recommendation}")
                lines.append(
                    "  [!] This conflict must be resolved or explicitly accepted before finalization."
                )
                lines.append("")

        if soft_conflicts:
            lines.append("--- Notes from Soft Conflicts ---")
            lines.append("")
            for conflict in soft_conflicts:
                lines.append(f"Conflict {conflict.conflict_id} ({conflict.severity.value}):")
                lines.append(f"  {conflict.description}")
                lines.append(f"  Recommended control: {conflict.recommendation}")
                lines.append("")

        if not accepted_gaps and not hard_conflicts and not soft_conflicts:
            lines.append(
                "No mitigations or operational controls are required based on "
                "the current evidence and review decisions."
            )

        lines.append("")
        lines.append("APPROVALS (Appendix D signature block style):")
        lines.append("  ORIGINATOR / ORGANIZATION: _____________________   DATE: __________")
        lines.append("  JSC MATERIALS AND PROCESSES TECHNOLOGY BRANCH: ___ DATE: __________")
        lines.append("  PROJECT MANAGER: ________________________________  DATE: __________")
        if routing.category == MUACategory.I:
            lines.append("  PROGRAM MANAGER / PROGRAM OFFICE: ______________  DATE: __________")
        else:
            lines.append("  PROGRAM MANAGER / PROGRAM OFFICE: N/A for Cat II unless specifically required")

        return DraftSection(
            section_number=5,
            title=_SECTION_TITLES[5],
            content="\n".join(lines),
            editable=True,
        )

    def _render_verification(
        self,
        gap_decisions: list[GapDecision],
    ) -> DraftSection:
        """Section 6: Verification Requirements -- tests to close flagged gaps."""
        flagged = [
            gd
            for gd in gap_decisions
            if gd.decision == GapDecisionType.FLAG_FOR_TESTING
        ]

        if not flagged:
            content = (
                "No verification testing is required.  All gaps have been "
                "accepted with rationale or no gaps were identified."
            )
            return DraftSection(
                section_number=6,
                title=_SECTION_TITLES[6],
                content=content,
                editable=True,
            )

        lines: list[str] = [
            f"{len(flagged)} gap(s) have been flagged for verification testing:",
            "",
        ]

        for idx, gd in enumerate(flagged, 1):
            lines.append(f"VER-{idx}: Gap {gd.gap_id}")
            lines.append(f"  Requirement: Testing is required to close this gap.")
            lines.append(f"  Engineer note: \"{gd.rationale}\"")
            lines.append(
                f"  Status: OPEN -- test must be completed and results "
                f"reviewed before MUA finalization."
            )
            lines.append("")

        lines.append(
            "All verification items must be closed before the MUA may "
            "be finalized.  Partial results should be documented and "
            "referenced in a follow-up assessment."
        )

        return DraftSection(
            section_number=6,
            title=_SECTION_TITLES[6],
            content="\n".join(lines),
            editable=True,
        )

    def _render_traceability(
        self,
        investigation: InvestigationResult,
        review_decisions: ReviewDecisions,
    ) -> DraftSection:
        """Section 7: Traceability & Citations -- every evidence item linked to source."""
        lines: list[str] = []

        # --- Precedent citations ---
        all_precedents = (
            investigation.supporting_precedents
            + investigation.conflicting_precedents
        )

        precedent_decision_map = {
            pd.mua_number: pd for pd in review_decisions.precedent_decisions
        }

        if all_precedents:
            lines.append("--- Precedent Evidence ---")
            lines.append("")
            for prec in all_precedents:
                pd = precedent_decision_map.get(prec.mua_number)
                status_label = pd.decision.value if pd else "no_decision"
                lines.append(f"[{prec.mua_number}]")
                lines.append(f"  Material:       {prec.material_designation}")
                lines.append(
                    f"  Determination:  {prec.determination.value}"
                )
                lines.append(f"  Environment:    {prec.environment_description}")
                lines.append(f"  Relevance:      {prec.relevance_score:.2f}")
                lines.append(f"  Review Status:  {status_label}")
                if prec.evidence_ref:
                    lines.append(f"  Evidence ID:    {prec.evidence_ref.evidence_id[:16]}...")
                    loc = prec.evidence_ref.source_locator
                    if loc.document_id:
                        lines.append(f"  Document:       {loc.document_id}")
                    if loc.url:
                        lines.append(f"  URL:            {loc.url}")
                if prec.program:
                    lines.append(f"  Program:        {prec.program}")
                if prec.center:
                    lines.append(f"  Center:         {prec.center}")
                lines.append("")

        if investigation.bok_findings:
            lines.append("--- BoK / Standards Evidence ---")
            lines.append("")
            for finding in investigation.bok_findings:
                lines.append(f"[{finding.domain.upper()}]")
                lines.append(f"  Source:         {finding.source or 'BoK'}")
                if finding.title:
                    lines.append(f"  Title:          {finding.title}")
                if finding.section:
                    lines.append(f"  Section:        {finding.section}")
                if finding.page:
                    lines.append(f"  Page:           {finding.page}")
                lines.append(f"  Relevance:      {finding.relevance_score:.2f}")
                lines.append(f"  Excerpt:        \"{finding.excerpt}\"")
                lines.append("")

        # --- Test data citations ---
        if investigation.test_data:
            lines.append("--- MAPTIS Test Data ---")
            lines.append("")
            for rec in investigation.test_data:
                report = rec.report_number or "N/A"
                test_num = str(rec.test_number) if rec.test_number else "N/A"
                lines.append(
                    f"[{rec.test_class}] Test #{test_num} -- "
                    f"Report: {report} -- "
                    f"Rating: {rec.rating or 'U'} -- "
                    f"Currency: {_CURRENCY_LABEL.get(rec.is_current, 'Unknown')}"
                )
            lines.append("")

        # --- Envelope data ---
        if investigation.envelope:
            lines.append("--- Envelope Analysis Source ---")
            lines.append(
                f"Overall: {investigation.envelope.overall_status.value}, "
                f"Coverage: {investigation.envelope.coverage_ratio:.0%}"
            )
            lines.append("")

        # --- Dependency warnings ---
        if investigation.dependency_warnings:
            lines.append("--- Dependency Warnings ---")
            lines.append("")
            for dw in investigation.dependency_warnings:
                lines.append(
                    f"[!] {dw.cited_mua} depends on {dw.depends_on}: {dw.warning}"
                )
            lines.append("")

        # --- Evidence strength detail (moved from Section 4 rationale) ---
        strength = investigation.evidence_strength
        if strength.explanation:
            lines.append("--- Evidence Strength Detail ---")
            lines.append(
                f"Band: {strength.band.value.upper()}, "
                f"Score: {strength.score:.3f}"
            )
            lines.append(strength.explanation)
            lines.append("")

        # --- Authority ---
        lines.append(f"Governing Standard: NASA-STD-6016C")

        if not all_precedents and not investigation.test_data:
            lines.insert(
                0,
                "No evidence items were cited for this assessment.\n\n",
            )

        return DraftSection(
            section_number=7,
            title=_SECTION_TITLES[7],
            content="\n".join(lines),
            editable=False,
        )

    # ---- document assembly ------------------------------------------------

    @staticmethod
    def _assemble_document(sections: list[DraftSection]) -> str:
        """Assemble sections into a single document string.

        Format::

            ================================================================
            SECTION N: TITLE
            ================================================================
            <content>

        """
        parts: list[str] = []
        divider = "=" * 64

        for section in sections:
            parts.append(divider)
            parts.append(
                f"SECTION {section.section_number}: {section.title.upper()}"
            )
            parts.append(divider)
            parts.append(section.content)
            parts.append("")  # blank line between sections

        return "\n".join(parts)

    # ---- helper methods ---------------------------------------------------

    @staticmethod
    def _is_process_sensitive(investigation: InvestigationResult) -> bool:
        """Return True if the material is process-sensitive (adhesives, composites, etc.)."""
        mat = investigation.material
        if mat.material_class and mat.material_class in _PROCESS_SENSITIVE_CLASSES:
            return True
        if mat.is_process_sensitive:
            return True
        return False

    @staticmethod
    def _render_process_params_header(
        params: Optional[ProcessParams],
    ) -> list[str]:
        """Render process parameter lines for the header section."""
        lines = ["", "Process Parameters:"]
        if params is None:
            lines.append("  [WARNING] Process parameters not provided for process-sensitive material.")
            return lines

        if params.cure_temp_f is not None:
            lines.append(f"  Cure Temperature: {params.cure_temp_f:.0f} degF")
        if params.cure_time_min is not None:
            lines.append(f"  Cure Time:        {params.cure_time_min:.0f} min")
        if params.cure_pressure_psi is not None:
            lines.append(f"  Cure Pressure:    {params.cure_pressure_psi:.1f} psi")
        if params.mix_ratio:
            lines.append(f"  Mix Ratio:        {params.mix_ratio}")
        if params.layup_orientation:
            lines.append(f"  Layup:            {params.layup_orientation}")

        return lines

    @staticmethod
    def _render_process_caveat(investigation: InvestigationResult) -> str:
        """Render the process-sensitivity caveat for the rationale section."""
        mat = investigation.material
        material_name = mat.resolved_name or mat.input_text
        params = investigation.process_params

        if params and params.cure_temp_f is not None and params.cure_time_min is not None:
            return (
                f"[PROCESS CONSTRAINT] This assessment is limited to "
                f"{material_name} processed at {params.cure_temp_f:.0f} degF "
                f"+/- 10 degF for {params.cure_time_min:.0f} min +/- 5 minutes. "
                f"Alternative process cycles have not been evaluated."
            )
        return (
            f"[PROCESS CONSTRAINT] This material ({material_name}) is "
            f"process-sensitive.  The assessment is limited to the specific "
            f"process parameters documented above.  Alternative process "
            f"cycles have not been evaluated."
        )

    @staticmethod
    def _get_included_precedents(
        precedents: list[PrecedentMatch],
        decision_map: dict[str, PrecedentDecision],
        target_decision: ReviewDecisionType,
    ) -> list[PrecedentMatch]:
        """Filter precedents to those matching a specific review decision type."""
        result: list[PrecedentMatch] = []
        for prec in precedents:
            pd = decision_map.get(prec.mua_number)
            if pd and pd.decision == target_decision:
                result.append(prec)
        return result

    @staticmethod
    def _format_precedent_citation(
        prec: PrecedentMatch,
        decision_map: dict[str, PrecedentDecision],
    ) -> list[str]:
        """Format a single precedent for the rationale section."""
        lines = [
            f"  [{prec.mua_number}] {prec.material_designation}",
            f"    Determination: {prec.determination.value}",
            f"    Environment:   {prec.environment_description}",
            f"    Relevance:     {prec.relevance_score:.2f} "
            f"(physics: {prec.physics_relevance:.2f}, "
            f"regulatory: {prec.regulatory_relevance:.2f})",
        ]

        if prec.rationale_excerpt:
            lines.append(f"    Excerpt:       \"{prec.rationale_excerpt}\"")

        if prec.relationship_explanation:
            lines.append(f"    Relationship:  {prec.relationship_explanation}")

        pd = decision_map.get(prec.mua_number)
        if pd and pd.rationale:
            lines.append(f"    Engineer note: \"{pd.rationale}\"")

        return lines

    @staticmethod
    def _find_gap(
        gaps: list[GapIdentified], gap_id: str
    ) -> Optional[GapIdentified]:
        """Find a gap by its ID."""
        for gap in gaps:
            if gap.gap_id == gap_id:
                return gap
        return None

    @staticmethod
    def _collect_cited_precedents(
        investigation: InvestigationResult,
        review_decisions: ReviewDecisions,
    ) -> list[str]:
        """Collect MUA numbers for all precedents included in the draft."""
        included: set[str] = set()
        for pd in review_decisions.precedent_decisions:
            if pd.decision in (
                ReviewDecisionType.INCLUDE_SUPPORTING,
                ReviewDecisionType.INCLUDE_CONTEXT,
            ):
                included.add(pd.mua_number)
        return sorted(included)
