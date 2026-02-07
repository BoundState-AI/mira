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
        """
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
            self._render_mitigations(review_decisions, investigation.conflicts),
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
        """Section 1: Header -- identification and classification."""
        mat = investigation.material
        env = investigation.environment

        material_name = mat.resolved_name or mat.input_text
        material_code = mat.material_code or "N/A"
        resolution_label = mat.status.value.upper()

        lines = [
            f"MUA ID:            {mua_id}",
            f"Program:           {program or 'N/A'}",
            f"Material:          {material_name} ({material_code})",
            f"Resolution:        {resolution_label}",
            f"Material Class:    {mat.material_class.value if mat.material_class else 'N/A'}",
            f"",
            f"Environment:",
            f"  Medium:          {env.medium}",
            f"  O2:              {env.o2_percent:.1f}%",
            f"  Pressure:        {env.pressure_psia:.1f} psia",
            f"  Temperature:     {env.temp_min_f:.0f} to {env.temp_max_f:.0f} degF",
            f"  Location:        {env.location}",
            f"  Application:     {env.application}",
            f"",
            f"Category:          {routing.category.value}",
            f"Authority:         {routing.authority_pack}",
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
        """Section 2: Ratings -- per test class with MAPTIS evidence and currency."""
        if not test_data:
            content = (
                "No MAPTIS test data records were found for this material "
                "in the queried environment.  All test classes are unrated."
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

        lines: list[str] = []
        for test_class in sorted(by_class.keys()):
            records = by_class[test_class]
            lines.append(f"--- {test_class} ---")
            for rec in records:
                rating_str = rec.rating or "U"
                currency = _CURRENCY_LABEL.get(rec.is_current, "Unknown")
                test_num = f"Test #{rec.test_number}" if rec.test_number else "No test number"
                report = rec.report_number or "No report"
                date_str = rec.test_date or "No date"
                lines.append(
                    f"  Rating: {rating_str}  |  {test_num}  |  {report}  "
                    f"|  Date: {date_str}  |  Currency: {currency}"
                )
                if rec.is_current is False:
                    lines.append(
                        f"    [WARNING] This test record is EXPIRED. "
                        f"Currency should be confirmed before relying on this rating."
                    )
                elif rec.is_current is None:
                    lines.append(
                        f"    [NOTE] Currency status is UNKNOWN for this record. "
                        f"Verification recommended."
                    )
            lines.append("")

        # Summary counts
        current_count = sum(1 for r in test_data if r.is_current is True)
        expired_count = sum(1 for r in test_data if r.is_current is False)
        unknown_count = sum(1 for r in test_data if r.is_current is None)
        lines.append(
            f"Summary: {len(test_data)} total record(s) -- "
            f"{current_count} current, {expired_count} expired, "
            f"{unknown_count} unknown currency."
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
                rule_name = rule.get("rule", "unknown")
                rule_result = rule.get("result", "")
                lines.append(f"  - {rule_name}: {rule_result}")

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
        """Section 4: Rationale -- synthesized reasoning with precedent citations.

        Key guarantees:
        - Every included precedent decision from Step 3 appears with reasoning.
        - Gap acceptance rationale is QUOTED from engineer's own words.
        - Conflict dispositions are explained.
        - Judgment claims are tagged "(Engineering assessment)".
        - Never claims "APPROVED" -- says "may be acceptable based on reviewed evidence".
        """
        lines: list[str] = []

        # --- Evidence strength summary ---
        strength = investigation.evidence_strength
        band_label = strength.band.value if strength.band else "insufficient"
        lines.append(f"Evidence Strength: {band_label.upper()} ({strength.score:.2f})")
        if strength.explanation:
            lines.append(f"  {strength.explanation}")
        lines.append("")

        # --- Precedent analysis ---
        lines.append("--- Precedent Analysis ---")
        lines.append("")

        precedent_decision_map: dict[str, PrecedentDecision] = {
            pd.mua_number: pd for pd in review_decisions.precedent_decisions
        }

        # Supporting precedents
        included_supporting = self._get_included_precedents(
            investigation.supporting_precedents,
            precedent_decision_map,
            ReviewDecisionType.INCLUDE_SUPPORTING,
        )

        included_context = self._get_included_precedents(
            investigation.supporting_precedents + investigation.conflicting_precedents,
            precedent_decision_map,
            ReviewDecisionType.INCLUDE_CONTEXT,
        )

        approved_count = sum(
            1
            for p in included_supporting
            if p.determination == DeterminationStatus.APPROVED
        )

        if included_supporting:
            lines.append(f"{len(included_supporting)} precedent(s) included as supporting evidence:")
            if approved_count > 0:
                lines.append(
                    f"  {approved_count} approved precedent(s) in the evidence set."
                )
            lines.append("")

            for prec in included_supporting:
                lines.extend(self._format_precedent_citation(prec, precedent_decision_map))
                lines.append("")
        else:
            lines.append("No precedents were included as supporting evidence.")
            lines.append("")

        if included_context:
            lines.append(f"{len(included_context)} precedent(s) included for context:")
            lines.append("")
            for prec in included_context:
                lines.extend(self._format_precedent_citation(prec, precedent_decision_map))
                lines.append("")

        # --- Conflict dispositions ---
        if investigation.conflicts:
            lines.append("--- Conflict Dispositions ---")
            lines.append("")

            conflict_decision_map = {
                cd.conflict_id: cd for cd in review_decisions.conflict_decisions
            }

            for conflict in investigation.conflicts:
                lines.append(f"Conflict: {conflict.conflict_id} ({conflict.severity.value})")
                lines.append(f"  {conflict.description}")
                lines.append(f"  Sources: {conflict.source_a} vs {conflict.source_b}")

                cd = conflict_decision_map.get(conflict.conflict_id)
                if cd:
                    lines.append(f"  Decision: {cd.decision.value.replace('_', ' ').title()}")
                    if cd.rationale:
                        lines.append(f"  Rationale: \"{cd.rationale}\"")
                else:
                    lines.append("  Decision: PENDING")
                lines.append("")

        # --- Gap rationale ---
        gap_decisions_with_acceptance = [
            gd
            for gd in review_decisions.gap_decisions
            if gd.decision == GapDecisionType.ACCEPT_WITH_RATIONALE
        ]

        if gap_decisions_with_acceptance:
            lines.append("--- Gap Acceptance Rationale ---")
            lines.append("")
            for gd in gap_decisions_with_acceptance:
                gap_obj = self._find_gap(investigation.gaps, gd.gap_id)
                dimension_label = gap_obj.dimension if gap_obj else gd.gap_id
                lines.append(f"Gap {gd.gap_id} ({dimension_label}):")
                lines.append(f"  Engineer rationale: \"{gd.rationale}\"")
                lines.append(
                    "  (Engineering judgment -- see Step 3 rationale)"
                )
                lines.append("")

        # --- Envelope analysis ---
        if investigation.envelope:
            env_result = investigation.envelope
            lines.append("--- Envelope Analysis ---")
            lines.append(f"Overall Overlap: {env_result.overall_status.value}")
            lines.append(f"Coverage Ratio:  {env_result.coverage_ratio:.0%}")
            lines.append(f"  O2:          {env_result.o2_status.value}")
            lines.append(f"  Pressure:    {env_result.pressure_status.value}")
            lines.append(f"  Temperature: {env_result.temp_status.value}")
            if env_result.details:
                for detail in env_result.details:
                    lines.append(f"  - {detail}")
            lines.append("")

        # --- Process sensitivity caveat ---
        if self._is_process_sensitive(investigation):
            lines.append(self._render_process_caveat(investigation))
            lines.append("")

        # --- Summary assessment ---
        lines.append("--- Assessment Summary ---")
        lines.append("")
        if band_label in ("strong", "moderate"):
            lines.append(
                f"Based on the reviewed evidence ({len(included_supporting)} supporting "
                f"precedent(s), {approved_count} approved), the material "
                f"may be acceptable for the specified environment and application. "
                f"(Engineering assessment)"
            )
        elif band_label == "weak":
            lines.append(
                "The available evidence is limited. This material may require "
                "additional testing or evaluation before a determination can "
                "be made. (Engineering assessment)"
            )
        else:
            lines.append(
                "The available evidence is insufficient to support an assessment. "
                "Additional investigation and/or testing is recommended. "
                "(Engineering assessment)"
            )

        # --- Divergence note ---
        if review_decisions.divergence_detected:
            lines.append("")
            lines.append("[NOTE] Engineer divergence from AI-suggested rankings was detected.")
            if review_decisions.divergence_rationale:
                lines.append(
                    f"  Divergence rationale: \"{review_decisions.divergence_rationale}\""
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
    ) -> DraftSection:
        """Section 5: Mitigations / Controls -- operational constraints."""
        lines: list[str] = []

        # Mitigations derived from gaps accepted with rationale
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
                    f"  This gap has been accepted per engineering rationale. "
                    f"Operational use must remain within the bounds of the "
                    f"rationale provided:"
                )
                lines.append(f"  \"{gd.rationale}\"")
                lines.append(
                    "  Any deviation from the stated conditions invalidates "
                    "this acceptance and requires re-evaluation."
                )
                lines.append("")

        # Mitigations derived from conflicts
        hard_conflicts = [c for c in conflicts if c.severity.value == "hard"]
        soft_conflicts = [c for c in conflicts if c.severity.value == "soft"]

        if hard_conflicts:
            lines.append("--- Controls from Hard Conflicts ---")
            lines.append("")
            for conflict in hard_conflicts:
                lines.append(f"Conflict {conflict.conflict_id} ({conflict.severity.value}):")
                lines.append(f"  {conflict.description}")
                lines.append(f"  Recommendation: {conflict.recommendation}")
                lines.append(
                    "  [!] This conflict must be resolved or mitigated prior to "
                    "final approval."
                )
                lines.append("")

        if soft_conflicts:
            lines.append("--- Notes from Soft Conflicts ---")
            lines.append("")
            for conflict in soft_conflicts:
                lines.append(f"Conflict {conflict.conflict_id} ({conflict.severity.value}):")
                lines.append(f"  {conflict.description}")
                lines.append(f"  Recommendation: {conflict.recommendation}")
                lines.append("")

        if not accepted_gaps and not hard_conflicts and not soft_conflicts:
            lines.append(
                "No mitigations or operational controls are required based on "
                "the current evidence and review decisions."
            )

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
