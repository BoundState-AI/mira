"""
MUA Final - Draft Builder

Orchestrates the 80/20 MUA draft generation:
  1. Accept v7 investigation results + review decisions (the bridge)
  2. Retrieve style-example precedents from Postgres
  3. Build each section with precedent attribution
  4. Mark sections that need engineer input
  5. Return MUADraftWorkflow for section-level review

The bridge: converts v7's typed investigation output into MUASessionData,
which the LLM renderer transforms into a professional NASA document.

BoundState AI 2026
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from .models import (
    MUAConflict,
    MUAEnvelopeResult,
    MUAEvidenceStrength,
    MUAGap,
    MUAPrecedent,
    MUARating,
    MUARenderedDocument,
    MUASessionData,
    MUAEnvironment,
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

__all__ = ["MUADraftBuilder", "build_session_from_v7"]


class MUADraftBuilder:
    """
    Builds an MUA draft workflow from session data.

    Main entry point for the unified MUA system.  Accepts either:
      - MUASessionData directly (v8-style)
      - v7 investigation output via build_session_from_v7() bridge
    """

    def __init__(
        self,
        db_url: Optional[str] = None,
        use_llm: bool = True,
        model_id: Optional[str] = None,
    ):
        self._retriever = PrecedentRetriever(db_url=db_url)
        self._use_llm = use_llm
        self._renderer = MUADocumentRenderer(model_id=model_id)

    def build_draft(
        self,
        session: MUASessionData,
        precedent_limit: int = 5,
    ) -> MUADraftWorkflow:
        """
        Build a complete MUA draft with precedent attribution.

        Returns MUADraftWorkflow ready for engineer section-level review.
        """
        # Use pre-loaded precedents or retrieve from Postgres
        if session.precedents:
            precedents = session.precedents
        else:
            precedents = self._retrieve_precedents(session, precedent_limit)
            session.precedents = precedents

        # Build each section
        sections = self._build_all_sections(session, precedents)

        workflow = MUADraftWorkflow(
            session=session,
            sections=sections,
            precedents_found=precedents,
        )

        logger.info(
            "[DraftBuilder] Built draft for %s: %d sections, %d precedents, "
            "review progress: %s",
            session.material_name,
            len(sections),
            len(precedents),
            workflow.review_progress,
        )

        return workflow

    def _retrieve_precedents(
        self, session: MUASessionData, limit: int
    ) -> List[MUAPrecedent]:
        try:
            return self._retriever.retrieve(session, limit=limit)
        except Exception as exc:
            logger.warning("[DraftBuilder] Precedent retrieval failed: %s", exc)
            return []

    def _build_all_sections(
        self,
        session: MUASessionData,
        precedents: List[MUAPrecedent],
    ) -> List[MUADraftSection]:
        """Build all 7 MUA sections with provenance."""
        return [
            self._build_purpose(session),
            self._build_test_data(session),
            self._build_deficiencies(session),
            self._build_rationale(session, precedents),
            self._build_mitigations(session, precedents),
            self._build_verification(session),
            self._build_references(session, precedents),
        ]

    # -----------------------------------------------------------------------
    # Section builders (80% automated)
    # -----------------------------------------------------------------------

    def _build_purpose(self, s: MUASessionData) -> MUADraftSection:
        """Section 1: PURPOSE AND SCOPE - fully automated."""
        env = s.environment
        cat = _to_roman(s.category)

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
        if s.is_novel_material:
            content += (
                "\n    This material is flagged as novel for this application.\n"
                "    A Qualification Test Plan may be required.\n"
            )

        return MUADraftSection(
            section_number=1,
            section_title="PURPOSE AND SCOPE",
            content=content,
            status=SectionStatus.AI_DRAFTED,
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
                    if r.is_current is False:
                        line += " [EXPIRED]"
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
                    lines.append(f'         Rationale: "{g.rationale}"')
                lines.append("")
        else:
            lines.append(
                "    No deficiencies were identified. All required test\n"
                "    classes have acceptable ratings.\n"
            )

        # Conflicts (from v7 conflict detector)
        if s.conflicts:
            lines.append("    Cross-Source Conflicts:\n")
            for c in s.conflicts:
                lines.append(
                    f"    [{c.severity.upper()}] {c.description}"
                )
                lines.append(
                    f"    Sources: {c.source_a} vs {c.source_b}"
                )
                if c.disposition:
                    lines.append(f"    Disposition: {c.disposition}")
                if c.rationale:
                    lines.append(f'    Rationale: "{c.rationale}"')
                lines.append("")

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

        supporting = [p for p in precedents if p.is_supporting]

        if supporting:
            best = supporting[0]
            lines.append(
                f"    Based on review of {len(supporting)} supporting precedent"
                f" MUA(s) for similar materials, the following rationale is"
                f" proposed:\n"
            )

            if best.rationale:
                rat_text = best.rationale.strip()
                wrapped = _wrap_text(rat_text, indent=4, width=75)
                lines.extend(wrapped)
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

            if len(supporting) > 1:
                lines.append("    Supporting precedents:")
                for p in supporting[1:]:
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
                f"    Evidence Strength: {es.band} ({es.score:.2f})\n"
            )

        # Envelope coverage
        if s.envelope:
            env = s.envelope
            lines.append(
                f"    Envelope coverage: {env.coverage_ratio:.0%}"
                f" (O2: {env.o2_status}, Pressure: {env.pressure_status},"
                f" Temp: {env.temp_status})\n"
            )

        lines.append(
            "    >>> ENGINEER: Review and edit this rationale as needed. <<<\n"
        )

        return MUADraftSection(
            section_number=4,
            section_title="ENGINEERING RATIONALE",
            content="\n".join(lines),
            status=SectionStatus.NEEDS_INPUT,
            attributions=attributions,
        )

    def _build_mitigations(
        self,
        s: MUASessionData,
        precedents: List[MUAPrecedent],
    ) -> MUADraftSection:
        """Section 5: MITIGATIONS - automated with engineer review."""
        lines = ["    5. MITIGATIONS AND OPERATIONAL CONTROLS\n"]

        accepted = [g for g in s.gaps if g.disposition and "Accept" in str(g.disposition)]
        if accepted:
            for g in accepted:
                lines.append(
                    f"    {g.dimension.title()}: Operational use of this material\n"
                    f"    must remain within the bounds of the stated rationale.\n"
                    f"    Any deviation from the stated conditions invalidates\n"
                    f"    this acceptance and requires re-evaluation.\n"
                )
                if g.rationale:
                    lines.append(f'    Basis: "{g.rationale}"\n')
                lines.append("")

        if s.is_process_sensitive and s.process_params:
            lines.append(
                "    Process-sensitive material: cure conditions and processing\n"
                "    parameters affect material properties. Adherence to the\n"
                "    following process parameters is required:\n"
            )
            for k, v in s.process_params.items():
                if v is not None:
                    label = k.replace("_", " ").title()
                    lines.append(f"      {label}: {v}")
            lines.append("")

        if not accepted and not (s.is_process_sensitive and s.process_params):
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
            if not g.disposition or "Accept" not in str(g.disposition)
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
                tag = "supporting" if p.is_supporting else "conflicting"
                line = f"      - {p.mua_number} ({tag})"
                if p.material_name:
                    line += f": {p.material_name}"
                    if p.determination:
                        line += f", {p.determination}"
                lines.append(line)
            lines.append("")

        if s.cited_evidence:
            lines.append("    Additional evidence:")
            for e in s.cited_evidence:
                lines.append(f"      - {e.get('source', 'Unknown')}")
            lines.append("")

        if s.dependency_warnings:
            lines.append("    Dependency warnings:")
            for w in s.dependency_warnings:
                lines.append(f"      [!] {w}")
            lines.append("")

        return MUADraftSection(
            section_number=7,
            section_title="REFERENCES AND TRACEABILITY",
            content="\n".join(lines),
            status=SectionStatus.AI_DRAFTED,
        )

    def close(self):
        self._retriever.close()


# ---------------------------------------------------------------------------
# V7 Bridge: convert v7 investigation output → MUASessionData
# ---------------------------------------------------------------------------

def build_session_from_v7(
    *,
    mua_id: str,
    session_id: str,
    investigation,       # v7 InvestigationResult
    review_decisions,    # v7 ReviewDecisions
    category_routing,    # v7 CategoryRoutingResult
    center: str = "MSFC",
    reviewer: Optional[str] = None,
) -> MUASessionData:
    """
    Bridge: convert v7's typed investigation output into MUASessionData.

    This is the glue between the v7 evidence pipeline (Steps 1-3) and
    the final LLM renderer (Steps 4-5).
    """
    mat = investigation.material
    env = investigation.environment

    # Map material
    material_name = mat.resolved_name or mat.input_text
    maptis_code = mat.material_code
    material_class = mat.material_class.value if mat.material_class else None
    material_family = mat.family

    # Map environment
    mua_env = MUAEnvironment(
        medium=env.medium,
        o2_percent=env.o2_percent,
        pressure_psia=env.pressure_psia,
        temp_min_f=env.temp_min_f,
        temp_max_f=env.temp_max_f,
        location=env.location,
        application=env.application or "",
    )

    # Map test data → ratings
    ratings = []
    for t in investigation.test_data:
        ratings.append(MUARating(
            test_class=t.test_class,
            rating=t.rating,
            report_number=str(t.report_number) if t.report_number else None,
            test_date=t.test_date,
            is_current=t.is_current,
        ))

    # Map gaps + engineer dispositions from review decisions
    gap_decision_map = {
        gd.gap_id: gd for gd in review_decisions.gap_decisions
    }
    gaps = []
    for g in investigation.gaps:
        gd = gap_decision_map.get(g.gap_id)
        disposition = None
        rationale = None
        if gd:
            decision_val = gd.decision.value if hasattr(gd.decision, "value") else str(gd.decision)
            disposition = decision_val.replace("_", " ").title()
            rationale = gd.rationale
        gaps.append(MUAGap(
            gap_id=g.gap_id,
            dimension=g.dimension,
            severity=_map_severity(g.severity),
            description=g.description,
            disposition=disposition,
            rationale=rationale,
        ))

    # Map conflicts + engineer dispositions
    conflict_decision_map = {
        cd.conflict_id: cd for cd in review_decisions.conflict_decisions
    }
    conflicts = []
    for c in investigation.conflicts:
        cd = conflict_decision_map.get(c.conflict_id)
        disposition = None
        rationale = None
        if cd:
            decision_val = cd.decision.value if hasattr(cd.decision, "value") else str(cd.decision)
            disposition = decision_val.replace("_", " ").title()
            rationale = cd.rationale
        severity_val = c.severity.value if hasattr(c.severity, "value") else str(c.severity)
        conflicts.append(MUAConflict(
            conflict_id=c.conflict_id,
            severity=severity_val,
            source_a=c.source_a,
            source_b=c.source_b,
            description=c.description,
            recommendation=c.recommendation,
            disposition=disposition,
            rationale=rationale,
        ))

    # Map precedents (filtered by review decisions)
    precedent_decision_map = {
        pd.mua_number: pd for pd in review_decisions.precedent_decisions
    }
    precedents = []
    for p in investigation.supporting_precedents + investigation.conflicting_precedents:
        pd = precedent_decision_map.get(p.mua_number)
        # Skip excluded precedents
        if pd:
            decision_val = pd.decision.value if hasattr(pd.decision, "value") else str(pd.decision)
            if decision_val == "exclude":
                continue

        det_val = p.determination.value if hasattr(p.determination, "value") else str(p.determination)
        precedents.append(MUAPrecedent(
            mua_number=p.mua_number,
            material_name=p.material_designation,
            material_specification=None,
            determination=det_val,
            rationale=p.rationale_excerpt,
            environment=p.environment_description,
            o2_concentration_pct=p.o2_percent,
            pressure_psi_max=p.pressure_psia,
            relevance_score=p.relevance_score,
            is_supporting=p.is_supporting,
            is_conflicting=p.is_conflicting,
            relationship_explanation=p.relationship_explanation,
        ))

    # Map evidence strength
    es = investigation.evidence_strength
    band_val = es.band.value if hasattr(es.band, "value") else str(es.band)
    evidence_strength = MUAEvidenceStrength(
        band=band_val.upper(),
        score=es.score,
        components=es.components,
        penalties=es.penalties,
        explanation=es.explanation,
    )

    # Map envelope
    envelope = None
    if investigation.envelope:
        e = investigation.envelope
        envelope = MUAEnvelopeResult(
            overall_status=_enum_val(e.overall_status),
            o2_status=_enum_val(e.o2_status),
            pressure_status=_enum_val(e.pressure_status),
            temp_status=_enum_val(e.temp_status),
            coverage_ratio=e.coverage_ratio,
            details=e.details,
        )

    # Map category
    cat_val = _enum_val(category_routing.category)

    # Map routing basis
    routing_basis = []
    if hasattr(category_routing, "routing_basis") and category_routing.routing_basis:
        routing_basis = category_routing.routing_basis

    # Map banners
    banners = list(investigation.banners) if investigation.banners else []

    # Map dependency warnings
    dep_warnings = []
    for dw in investigation.dependency_warnings:
        dep_warnings.append(
            f"{dw.cited_mua} depends on {dw.depends_on}: {dw.warning}"
        )

    # Map constraints from process params
    constraints = []
    process_params = None
    if investigation.process_params:
        pp = investigation.process_params
        process_params = {}
        if pp.cure_temp_f is not None:
            process_params["cure_temp_f"] = pp.cure_temp_f
        if pp.cure_time_min is not None:
            process_params["cure_time_min"] = pp.cure_time_min
        if pp.cure_pressure_psi is not None:
            process_params["cure_pressure_psi"] = pp.cure_pressure_psi
        if pp.mix_ratio:
            process_params["mix_ratio"] = pp.mix_ratio
        if pp.layup_orientation:
            process_params["layup_orientation"] = pp.layup_orientation

    return MUASessionData(
        mua_id=mua_id,
        session_id=session_id,
        material_name=material_name,
        maptis_code=maptis_code,
        material_class=material_class,
        material_family=material_family,
        is_novel_material=investigation.is_novel_material,
        is_process_sensitive=mat.is_process_sensitive,
        category=cat_val,
        center=center,
        reviewer=reviewer,
        environment=mua_env,
        ratings=ratings,
        gaps=gaps,
        conflicts=conflicts,
        evidence_strength=evidence_strength,
        envelope=envelope,
        precedents=precedents,
        routing_basis=routing_basis,
        banners=banners,
        constraints=constraints,
        dependency_warnings=dep_warnings,
        process_params=process_params,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _to_roman(category: str) -> str:
    return {"1": "I", "2": "II", "3": "III"}.get(str(category), str(category))


def _enum_val(v) -> str:
    """Safely extract .value from an enum, or str() for plain values."""
    return v.value if hasattr(v, "value") else str(v)


def _map_severity(severity) -> str:
    """Map v7 gap severity to final severity literal."""
    val = _enum_val(severity).lower()
    if val in ("critical", "high", "medium", "low"):
        return val
    return "medium"


def _wrap_text(text: str, indent: int = 4, width: int = 75) -> List[str]:
    """Wrap long text into indented lines."""
    prefix = " " * indent
    words = text.split()
    lines = []
    current_line = prefix
    for word in words:
        if len(current_line) + len(word) + 1 > width:
            lines.append(current_line)
            current_line = prefix + word
        else:
            current_line += " " + word if current_line.strip() else prefix + word
    if current_line.strip():
        lines.append(current_line)
    return lines
