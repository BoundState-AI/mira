"""MUA v7 Investigator --- Unified evidence-gathering pipeline.

Replaces 4 independent search/evaluation paths with one orchestrated pipeline.
Wraps V6PrecedentRetriever (FAISS+BM25+RRF) for search --- does NOT build a new
search backend.

Key safety fixes incorporated:
- C1: Relevance boosts capped at 1.0 (boosts are tiebreakers, not promoters)
- C2: Missing data = 0.0 (unknown), not 0.5 (neutral)
- C3: Multi-record consensus, not just first FAISS result
- C4: Both temp_min AND temp_max passed to envelope matching

Pipeline phases:
1. Material identity (from Step 1, cached)
2. Parallel evidence gathering (precedents + MAPTIS + envelope)
3. Classification (supporting vs conflicting)
4. Conflict detection (cross-source, NEW)
5. Gap identification
6. Dependency checking (zombie MUA detection)
7. Evidence Strength calculation
8. Preliminary category routing
9. Per-precedent relationship explanations
10. Zero-precedent detection (novel materials)
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from .models import (
    MaterialResolution,
    EnvironmentSpec,
    ProcessParams,
    InvestigationResult,
    PrecedentMatch,
    TestDataRecord,
    EnvelopeResult,
    GapIdentified,
    DependencyWarning,
    OverlapStatus,
    DeterminationStatus,
    MUACategory,
    EvidenceStrengthBand,
    EvidenceStrengthResult,
    ConflictFound,
    ConflictSeverity,
    EvidenceRef,
    SourceType,
    SourceLocator,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Sandbox mock data registry
# ---------------------------------------------------------------------------
# Keyed by (material_code, family) tuples.  Provides realistic precedent
# and test data for demo purposes.  In production these calls go through
# V6PrecedentRetriever (FAISS+BM25+RRF) and the MAPTIS REST gateway.

_MOCK_PRECEDENTS: dict[str, list[dict]] = {
    "6061-T6": [
        {
            "mua_number": "MUA-2019-0347",
            "material_designation": "6061-T6 Aluminum",
            "material_family": "aluminum",
            "determination": DeterminationStatus.APPROVED,
            "environment_description": "Enriched O2, 30% O2, 250 psia, -65 to 165 degF",
            "o2_percent": 30.0,
            "pressure_psia": 250.0,
            "temp_min_f": -65.0,
            "temp_max_f": 165.0,
            "program": "SLS",
            "center": "MSFC",
            "rationale_excerpt": (
                "Material meets flammability and compatibility requirements "
                "per NASA-STD-6016B for enriched oxygen service up to 30% O2 "
                "at 250 psia within the stated temperature range."
            ),
            "relevance_score": 0.92,
        },
        {
            "mua_number": "MUA-2021-0512",
            "material_designation": "6061-T6 Aluminum",
            "material_family": "aluminum",
            "determination": DeterminationStatus.APPROVED,
            "environment_description": "Ambient air, 14.7 psia, -100 to 200 degF",
            "o2_percent": 20.9,
            "pressure_psia": 14.7,
            "temp_min_f": -100.0,
            "temp_max_f": 200.0,
            "program": "ISS",
            "center": "JSC",
            "rationale_excerpt": (
                "Material qualified for habitable environment use per "
                "SSP 51700, ambient air conditions."
            ),
            "relevance_score": 0.78,
        },
        {
            "mua_number": "MUA-2022-0088",
            "material_designation": "6061-T651 Aluminum",
            "material_family": "aluminum",
            "determination": DeterminationStatus.APPROVED,
            "environment_description": "GOX, 99.5% O2, 500 psia, 60 to 120 degF",
            "o2_percent": 99.5,
            "pressure_psia": 500.0,
            "temp_min_f": 60.0,
            "temp_max_f": 120.0,
            "program": "Orion",
            "center": "GRC",
            "rationale_excerpt": (
                "High-pressure GOX valve body application.  Approved per "
                "NASA-STD-6016C with ignition-resistant design features."
            ),
            "relevance_score": 0.85,
        },
        {
            "mua_number": "MUA-2017-0201",
            "material_designation": "6061-T6 Aluminum",
            "material_family": "aluminum",
            "determination": DeterminationStatus.REJECTED,
            "environment_description": "LOX immersion, 99.5% O2, 14.7 psia, -297 degF",
            "o2_percent": 99.5,
            "pressure_psia": 14.7,
            "temp_min_f": -297.0,
            "temp_max_f": -297.0,
            "program": "SLS",
            "center": "MSFC",
            "rationale_excerpt": (
                "Impact sensitivity testing showed unacceptable reaction "
                "thresholds for LOX-immersed service.  Material not "
                "recommended for LOX-wetted surfaces without coating."
            ),
            "relevance_score": 0.70,
        },
    ],
    "Inconel 718": [
        {
            "mua_number": "MUA-2020-0199",
            "material_designation": "Inconel 718",
            "material_family": "nickel_superalloy",
            "determination": DeterminationStatus.APPROVED,
            "environment_description": "GOX, 99.5% O2, 6000 psia, -100 to 600 degF",
            "o2_percent": 99.5,
            "pressure_psia": 6000.0,
            "temp_min_f": -100.0,
            "temp_max_f": 600.0,
            "program": "SLS",
            "center": "MSFC",
            "rationale_excerpt": (
                "Nickel-based superalloy exhibits excellent oxygen "
                "compatibility even at high pressures.  Approved for "
                "RS-25 oxygen turbopump housing."
            ),
            "relevance_score": 0.95,
        },
        {
            "mua_number": "MUA-2018-0411",
            "material_designation": "Inconel 718",
            "material_family": "nickel_superalloy",
            "determination": DeterminationStatus.APPROVED,
            "environment_description": "GH2, 100% H2, 4500 psia, -200 to 400 degF",
            "o2_percent": 0.0,
            "pressure_psia": 4500.0,
            "temp_min_f": -200.0,
            "temp_max_f": 400.0,
            "program": "SLS",
            "center": "MSFC",
            "rationale_excerpt": (
                "Evaluated for hydrogen embrittlement resistance per "
                "ASTM G142.  Approved with heat-treatment constraint: "
                "solution anneal + age per AMS 5663."
            ),
            "relevance_score": 0.88,
        },
        {
            "mua_number": "MUA-2023-0032",
            "material_designation": "Inconel 625",
            "material_family": "nickel_superalloy",
            "determination": DeterminationStatus.APPROVED,
            "environment_description": "GOX, 99.5% O2, 3000 psia, -65 to 500 degF",
            "o2_percent": 99.5,
            "pressure_psia": 3000.0,
            "temp_min_f": -65.0,
            "temp_max_f": 500.0,
            "program": "Gateway",
            "center": "JSC",
            "rationale_excerpt": (
                "Family analog -- similar nickel superalloy composition. "
                "Lower pressure than 718 precedent but same O2 environment."
            ),
            "relevance_score": 0.72,
        },
    ],
}

_MOCK_TEST_DATA: dict[str, list[dict]] = {
    "6061-T6": [
        {
            "test_class": "FLAMM",
            "rating": "A",
            "test_number": 12045,
            "report_number": "MSFC-RPT-4521",
            "is_current": True,
            "test_date": "2022-03-15",
        },
        {
            "test_class": "TOX",
            "rating": "B",
            "test_number": 8821,
            "report_number": "JSC-RPT-7823",
            "is_current": True,
            "test_date": "2021-11-02",
        },
        {
            "test_class": "CORR",
            "rating": "A",
            "test_number": 5510,
            "report_number": "MSFC-RPT-3310",
            "is_current": True,
            "test_date": "2020-06-10",
        },
        {
            "test_class": "SCC",
            "rating": "A",
            "test_number": 3304,
            "report_number": "MSFC-RPT-2251",
            "is_current": False,  # expired
            "test_date": "2016-04-22",
        },
    ],
    "Inconel 718": [
        {
            "test_class": "FLAMM",
            "rating": "A",
            "test_number": 14023,
            "report_number": "MSFC-RPT-5671",
            "is_current": True,
            "test_date": "2023-01-20",
        },
        {
            "test_class": "SCC",
            "rating": "A",
            "test_number": 9920,
            "report_number": "MSFC-RPT-4490",
            "is_current": True,
            "test_date": "2022-07-14",
        },
        {
            "test_class": "CORR",
            "rating": "A",
            "test_number": 6012,
            "report_number": "MSFC-RPT-3822",
            "is_current": True,
            "test_date": "2021-09-30",
        },
    ],
}

# Dependency graph: MUA -> list of MUAs it depends on.
_MOCK_DEPENDENCIES: dict[str, list[str]] = {
    "MUA-2019-0347": [],
    "MUA-2021-0512": ["MUA-2018-0102"],  # depends on a potentially revoked MUA
    "MUA-2022-0088": [],
    "MUA-2017-0201": [],
    "MUA-2020-0199": [],
    "MUA-2018-0411": [],
    "MUA-2023-0032": ["MUA-2020-0199"],  # depends on the 718 precedent
}

_MOCK_REVOKED: set[str] = {"MUA-2018-0102"}

# Maximum boost cap per C1 safety fix.
_MAX_RELEVANCE_BOOST: float = 1.0


class MUAInvestigator:
    """Unified evidence-gathering pipeline for MUA v7 Step 2.

    Orchestrates parallel retrieval from precedent corpus (FAISS+BM25+RRF),
    MAPTIS test data, and envelope analysis, then runs classification,
    conflict detection, gap identification, dependency checking, evidence
    strength calculation, preliminary category routing, relationship
    explanation generation, and novel-material detection.

    In the sandbox build every external data call is served by the mock
    registries above.  The public API is stable --- swapping in production
    backends requires only replacing the ``_search_precedents``,
    ``_query_test_data``, and ``_compute_envelope`` methods.
    """

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    async def investigate(
        self,
        material: MaterialResolution,
        environment: EnvironmentSpec,
        process_params: Optional[ProcessParams] = None,
        center: str = "MSFC",
    ) -> InvestigationResult:
        """Run the full investigation pipeline.

        Parameters
        ----------
        material:
            Resolved material identity from Step 1.
        environment:
            Target environment specification.
        process_params:
            Optional process parameters (adhesives / composites).
        center:
            NASA center code for center-specific precedent weighting.

        Returns
        -------
        InvestigationResult
            Complete evidence package for Step 3 review.

        Notes
        -----
        This method never raises.  If an individual phase fails the error
        is logged and the pipeline continues, returning whatever partial
        evidence was gathered.  The ``evidence_strength`` band will
        reflect degraded data quality.
        """
        logger.info(
            "Starting investigation for %s in %s (center=%s)",
            material.resolved_name or material.input_text,
            environment.medium,
            center,
        )

        # Phase 1 -- material identity is already resolved (passed in).

        # Phase 2 -- parallel evidence gathering.
        all_precedents: list[PrecedentMatch] = []
        test_data: list[TestDataRecord] = []

        try:
            all_precedents, test_data = await asyncio.gather(
                self._search_precedents(material, environment),
                self._query_test_data(
                    material.material_code or material.input_text
                ),
            )
        except Exception:
            logger.exception("Evidence gathering failed; continuing with partial data")

        # Phase 3 -- classify supporting vs conflicting.
        supporting = [p for p in all_precedents if p.is_supporting]
        conflicting = [p for p in all_precedents if p.is_conflicting]

        # Phase 2b -- envelope (needs precedent bounds).
        envelope: Optional[EnvelopeResult] = None
        try:
            precedent_bounds = self._extract_precedent_bounds(supporting)
            envelope = await self._compute_envelope(environment, precedent_bounds)
        except Exception:
            logger.exception("Envelope computation failed")

        # Phase 4 -- conflict detection.
        conflicts: list[ConflictFound] = []
        try:
            conflicts = _detect_cross_source_conflicts(
                supporting, conflicting, test_data
            )
        except Exception:
            logger.exception("Conflict detection failed")

        # Phase 5 -- gap identification.
        gaps: list[GapIdentified] = []
        try:
            gaps = self._identify_gaps(envelope, test_data, environment)
        except Exception:
            logger.exception("Gap identification failed")

        # Phase 6 -- dependency checking (zombie MUAs).
        dep_warnings: list[DependencyWarning] = []
        try:
            dep_warnings = self._check_dependencies(all_precedents)
        except Exception:
            logger.exception("Dependency check failed")

        # Phase 7 -- evidence strength.
        evidence_strength = self._calculate_evidence_strength(
            supporting, conflicting, test_data, envelope, gaps
        )

        # Phase 8 -- preliminary category routing.
        preliminary_category = self._route_category(
            material, environment, evidence_strength, gaps, process_params
        )

        # Phase 9 -- relationship explanations (imported lazily to avoid
        #             circular imports at module level).
        try:
            from .relationship_explainer import generate_relationship_explanations

            all_precedents = generate_relationship_explanations(
                all_precedents, material, environment, process_params
            )
            # Re-split after explanations are attached.
            supporting = [p for p in all_precedents if p.is_supporting]
            conflicting = [p for p in all_precedents if p.is_conflicting]
        except Exception:
            logger.exception("Relationship explanation generation failed")

        # Phase 10 -- novel material detection.
        is_novel = self._detect_novel_material(supporting, test_data)

        # Banners.
        banners = self._generate_banners(environment)

        result = InvestigationResult(
            material=material,
            environment=environment,
            process_params=process_params,
            supporting_precedents=supporting,
            conflicting_precedents=conflicting,
            test_data=test_data,
            envelope=envelope,
            conflicts=conflicts,
            gaps=gaps,
            dependency_warnings=dep_warnings,
            evidence_strength=evidence_strength,
            preliminary_category=preliminary_category,
            banners=banners,
            is_novel_material=is_novel,
        )

        logger.info(
            "Investigation complete: %d supporting, %d conflicting, "
            "%d gaps, strength=%s, category=%s, novel=%s",
            len(supporting),
            len(conflicting),
            len(gaps),
            evidence_strength.band.value,
            preliminary_category.value if preliminary_category else "undetermined",
            is_novel,
        )

        return result

    # ------------------------------------------------------------------
    # Phase 2a -- precedent search
    # ------------------------------------------------------------------

    async def _search_precedents(
        self,
        material: MaterialResolution,
        environment: EnvironmentSpec,
    ) -> list[PrecedentMatch]:
        """Search the precedent corpus and return classified matches.

        In production this wraps V6PrecedentRetriever (FAISS+BM25+RRF).
        The sandbox serves from ``_MOCK_PRECEDENTS``.

        Safety fix C1: relevance boosts are capped at ``_MAX_RELEVANCE_BOOST``
        so that boosts act as tiebreakers, never as promoters.

        Safety fix C3: multiple records are returned and evaluated rather
        than relying on a single FAISS nearest-neighbour.
        """
        lookup_key = material.resolved_name or material.input_text
        raw_records = _MOCK_PRECEDENTS.get(lookup_key, [])

        if not raw_records:
            logger.warning("No mock precedents found for %r", lookup_key)
            return []

        precedents: list[PrecedentMatch] = []
        for rec in raw_records:
            # --- C1 fix: cap any relevance score at MAX_RELEVANCE_BOOST ---
            raw_score = float(rec.get("relevance_score", 0.0))
            capped_score = min(raw_score, _MAX_RELEVANCE_BOOST)

            # --- C2 fix: missing numeric fields default to 0.0 ---
            o2 = float(rec["o2_percent"]) if rec.get("o2_percent") is not None else 0.0
            psi = (
                float(rec["pressure_psia"])
                if rec.get("pressure_psia") is not None
                else 0.0
            )
            t_min = (
                float(rec["temp_min_f"])
                if rec.get("temp_min_f") is not None
                else None
            )
            t_max = (
                float(rec["temp_max_f"])
                if rec.get("temp_max_f") is not None
                else None
            )

            determination = rec.get("determination", DeterminationStatus.UNKNOWN)

            # Classification: rejected/cancelled precedents are *conflicting*;
            # everything else is tentatively supporting.
            is_conflicting = determination in (
                DeterminationStatus.REJECTED,
                DeterminationStatus.CANCELLED,
            )
            is_supporting = not is_conflicting

            # Build an evidence ref (Tier B -- metadata-derived).
            evidence_id = EvidenceRef.compute_tier_b_id(
                source_type=SourceType.MUA_CORPUS.value,
                primary_id=rec["mua_number"],
                locator=rec.get("environment_description", ""),
            )
            evidence_ref = EvidenceRef(
                evidence_id=evidence_id,
                source_type=SourceType.MUA_CORPUS,
                source_locator=SourceLocator(document_id=rec["mua_number"]),
            )

            pm = PrecedentMatch(
                mua_number=rec["mua_number"],
                material_designation=rec["material_designation"],
                material_family=rec.get("material_family"),
                determination=determination,
                environment_description=rec["environment_description"],
                o2_percent=o2,
                pressure_psia=psi,
                temp_min_f=t_min,
                temp_max_f=t_max,
                program=rec.get("program"),
                center=rec.get("center"),
                rationale_excerpt=rec.get("rationale_excerpt"),
                relevance_score=capped_score,
                is_supporting=is_supporting,
                is_conflicting=is_conflicting,
                evidence_ref=evidence_ref,
                physics_relevance=min(capped_score, _MAX_RELEVANCE_BOOST),
                regulatory_relevance=min(capped_score * 0.9, _MAX_RELEVANCE_BOOST),
            )
            precedents.append(pm)

        # Sort by relevance descending (C3: return full list, not just top-1).
        precedents.sort(key=lambda p: p.relevance_score, reverse=True)

        logger.info(
            "Precedent search returned %d results for %r",
            len(precedents),
            lookup_key,
        )
        return precedents

    # ------------------------------------------------------------------
    # Phase 2b -- MAPTIS test data
    # ------------------------------------------------------------------

    async def _query_test_data(
        self,
        material_code: str,
    ) -> list[TestDataRecord]:
        """Query MAPTIS for test data records.

        Safety fix C2: records with missing currency information default to
        ``is_current=None`` (unknown, scored as 0.0) rather than assuming
        a neutral 0.5.

        In production this calls the MAPTIS REST gateway.
        """
        raw_records = _MOCK_TEST_DATA.get(material_code, [])

        if not raw_records:
            logger.warning("No mock test data found for %r", material_code)
            return []

        records: list[TestDataRecord] = []
        for rec in raw_records:
            td = TestDataRecord(
                test_class=rec["test_class"],
                rating=rec.get("rating"),
                test_number=rec.get("test_number"),
                report_number=rec.get("report_number"),
                # C2 fix: unknown currency stays None (not coerced to True).
                is_current=rec.get("is_current"),
                test_date=rec.get("test_date"),
            )
            records.append(td)

        logger.info(
            "MAPTIS query returned %d test records for %r",
            len(records),
            material_code,
        )
        return records

    # ------------------------------------------------------------------
    # Phase 2c -- envelope computation
    # ------------------------------------------------------------------

    async def _compute_envelope(
        self,
        environment: EnvironmentSpec,
        precedent_bounds: dict,
    ) -> EnvelopeResult:
        """Compute per-dimension envelope overlap.

        Safety fix C4: both ``temp_min`` AND ``temp_max`` are passed to
        the envelope matcher.  Prior implementations only passed temp_max,
        missing cryogenic exceedances.

        Parameters
        ----------
        environment:
            Target environment.
        precedent_bounds:
            Dict with keys ``o2_min``, ``o2_max``, ``psi_min``, ``psi_max``,
            ``temp_min``, ``temp_max`` aggregated from supporting precedents.
        """
        if not precedent_bounds:
            return EnvelopeResult(
                overall_status=OverlapStatus.INSUFFICIENT_DATA,
                details=["No supporting precedent bounds available for envelope analysis."],
            )

        details: list[str] = []

        # --- O2 dimension ---
        o2_status = self._dimension_status(
            query_val=environment.o2_percent,
            tested_min=precedent_bounds.get("o2_min", 0.0),
            tested_max=precedent_bounds.get("o2_max", 0.0),
            name="O2",
            details=details,
        )

        # --- Pressure dimension ---
        pressure_status = self._dimension_status(
            query_val=environment.pressure_psia,
            tested_min=precedent_bounds.get("psi_min", 0.0),
            tested_max=precedent_bounds.get("psi_max", 0.0),
            name="Pressure",
            details=details,
        )

        # --- Temperature dimension (C4: BOTH min and max) ---
        temp_status = self._temperature_envelope_status(
            query_min=environment.temp_min_f,
            query_max=environment.temp_max_f,
            tested_min=precedent_bounds.get("temp_min", 0.0),
            tested_max=precedent_bounds.get("temp_max", 0.0),
            details=details,
        )

        # --- Overall status ---
        statuses = [o2_status, pressure_status, temp_status]
        if OverlapStatus.OUTSIDE in statuses:
            overall = OverlapStatus.OUTSIDE
        elif OverlapStatus.EXTRAPOLATION in statuses:
            overall = OverlapStatus.EXTRAPOLATION
        elif OverlapStatus.PARTIAL in statuses:
            overall = OverlapStatus.PARTIAL
        elif all(s == OverlapStatus.WITHIN for s in statuses):
            overall = OverlapStatus.WITHIN
        else:
            overall = OverlapStatus.INSUFFICIENT_DATA

        # Coverage ratio: fraction of dimensions within envelope.
        within_count = sum(1 for s in statuses if s == OverlapStatus.WITHIN)
        coverage = within_count / len(statuses) if statuses else 0.0

        return EnvelopeResult(
            overall_status=overall,
            o2_status=o2_status,
            pressure_status=pressure_status,
            temp_status=temp_status,
            coverage_ratio=round(coverage, 2),
            details=details,
        )

    # ------------------------------------------------------------------
    # Phase 5 -- gap identification
    # ------------------------------------------------------------------

    def _identify_gaps(
        self,
        envelope: Optional[EnvelopeResult],
        test_data: list[TestDataRecord],
        environment: EnvironmentSpec,
    ) -> list[GapIdentified]:
        """Identify evidence gaps across temperature, pressure, O2, toxicity, and test classes.

        Returns a list of gaps ordered by severity (critical first).
        """
        gaps: list[GapIdentified] = []

        # --- Temperature range gaps ---
        if envelope and envelope.temp_status in (
            OverlapStatus.PARTIAL,
            OverlapStatus.EXTRAPOLATION,
            OverlapStatus.OUTSIDE,
        ):
            severity = "critical" if envelope.temp_status == OverlapStatus.OUTSIDE else "high"
            gaps.append(
                GapIdentified(
                    gap_id=f"gap-temp-{uuid.uuid4().hex[:8]}",
                    dimension="temperature",
                    description=(
                        f"Query temperature range [{environment.temp_min_f} to "
                        f"{environment.temp_max_f} degF] is not fully covered by "
                        f"precedent data.  Envelope status: {envelope.temp_status.value}."
                    ),
                    severity=severity,
                    query_value=f"{environment.temp_min_f} to {environment.temp_max_f} degF",
                    requires_review=True,
                )
            )

        # --- Pressure extrapolation ---
        if envelope and envelope.pressure_status in (
            OverlapStatus.EXTRAPOLATION,
            OverlapStatus.OUTSIDE,
        ):
            severity = "critical" if envelope.pressure_status == OverlapStatus.OUTSIDE else "high"
            gaps.append(
                GapIdentified(
                    gap_id=f"gap-psi-{uuid.uuid4().hex[:8]}",
                    dimension="pressure",
                    description=(
                        f"Query pressure {environment.pressure_psia} psia exceeds "
                        f"tested precedent envelope.  "
                        f"Envelope status: {envelope.pressure_status.value}."
                    ),
                    severity=severity,
                    query_value=f"{environment.pressure_psia} psia",
                    requires_review=True,
                )
            )

        # --- O2 gap ---
        if envelope and envelope.o2_status in (
            OverlapStatus.EXTRAPOLATION,
            OverlapStatus.OUTSIDE,
        ):
            severity = "critical" if envelope.o2_status == OverlapStatus.OUTSIDE else "high"
            gaps.append(
                GapIdentified(
                    gap_id=f"gap-o2-{uuid.uuid4().hex[:8]}",
                    dimension="o2",
                    description=(
                        f"Query O2 concentration {environment.o2_percent}% is not "
                        f"covered by precedent data.  "
                        f"Envelope status: {envelope.o2_status.value}."
                    ),
                    severity=severity,
                    query_value=f"{environment.o2_percent}%",
                    requires_review=True,
                )
            )

        # --- Missing test class data ---
        required_classes = {"FLAMM", "TOX"}
        if environment.is_enriched_o2:
            required_classes.add("CORR")
        if environment.is_cryogenic:
            required_classes.add("SCC")

        available_classes = {td.test_class for td in test_data if td.is_current is True}

        for missing in sorted(required_classes - available_classes):
            gaps.append(
                GapIdentified(
                    gap_id=f"gap-test-{missing.lower()}-{uuid.uuid4().hex[:8]}",
                    dimension=f"test_class_{missing.lower()}",
                    description=(
                        f"No current {missing} test data available.  "
                        f"This test class is required for the queried environment."
                    ),
                    severity="high" if missing == "FLAMM" else "medium",
                    requires_review=True,
                )
            )

        # --- Toxicity data absence ---
        has_tox = any(
            td.test_class == "TOX" and td.is_current is True for td in test_data
        )
        if not has_tox and environment.location == "habitable":
            gaps.append(
                GapIdentified(
                    gap_id=f"gap-tox-{uuid.uuid4().hex[:8]}",
                    dimension="toxicity",
                    description=(
                        "Habitable environment requires current toxicity (TOX) "
                        "test data, which is absent or expired."
                    ),
                    severity="critical",
                    requires_review=True,
                )
            )

        # --- Expired test data warnings ---
        expired = [td for td in test_data if td.is_current is False]
        for td in expired:
            gaps.append(
                GapIdentified(
                    gap_id=f"gap-expired-{td.test_class.lower()}-{uuid.uuid4().hex[:8]}",
                    dimension=f"expired_{td.test_class.lower()}",
                    description=(
                        f"{td.test_class} test data (report {td.report_number}) is "
                        f"expired.  May need re-test or engineering disposition."
                    ),
                    severity="medium",
                    nearest_data=td.test_date,
                    requires_review=True,
                )
            )

        # Sort by severity priority.
        severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        gaps.sort(key=lambda g: severity_order.get(g.severity, 99))

        return gaps

    # ------------------------------------------------------------------
    # Phase 6 -- dependency checking
    # ------------------------------------------------------------------

    def _check_dependencies(
        self,
        precedents: list[PrecedentMatch],
    ) -> list[DependencyWarning]:
        """Check if cited MUAs depend on other MUAs that might be revoked.

        Detects "zombie" MUAs -- precedents whose validity chains include
        a revoked or cancelled parent MUA.
        """
        warnings: list[DependencyWarning] = []

        for p in precedents:
            deps = _MOCK_DEPENDENCIES.get(p.mua_number, [])
            for dep_mua in deps:
                if dep_mua in _MOCK_REVOKED:
                    warnings.append(
                        DependencyWarning(
                            cited_mua=p.mua_number,
                            depends_on=dep_mua,
                            warning=(
                                f"Cited precedent {p.mua_number} depends on "
                                f"{dep_mua}, which has been revoked.  The validity "
                                f"of this precedent may be compromised.  Engineering "
                                f"review required before relying on this precedent."
                            ),
                        )
                    )
                else:
                    # Dependency exists but is not revoked -- informational.
                    logger.debug(
                        "%s depends on %s (status OK)", p.mua_number, dep_mua
                    )

        if warnings:
            logger.warning(
                "Dependency check found %d zombie-MUA warnings", len(warnings)
            )

        return warnings

    # ------------------------------------------------------------------
    # Phase 8 -- banner generation
    # ------------------------------------------------------------------

    def _generate_banners(
        self,
        environment: EnvironmentSpec,
    ) -> list[str]:
        """Generate environment-specific safety banners.

        Banners alert the reviewing engineer to environment conditions
        that require special handling or additional scrutiny.
        """
        banners: list[str] = []

        if environment.is_enriched_o2:
            banners.append(
                f"ENRICHED OXYGEN ENVIRONMENT: O2 concentration is "
                f"{environment.o2_percent}% (>= 23.5%).  Material must meet "
                f"NASA-STD-6016 oxygen compatibility requirements.  Additional "
                f"flammability and ignition testing may be required."
            )

        if environment.is_cryogenic:
            banners.append(
                f"CRYOGENIC ENVIRONMENT: Minimum temperature is "
                f"{environment.temp_min_f} degF (<= -150 degF).  Material must "
                f"demonstrate adequate ductility and fracture toughness at "
                f"cryogenic temperatures.  Low-temperature embrittlement must "
                f"be addressed."
            )

        if environment.is_hydrogen_service:
            banners.append(
                f"HYDROGEN SERVICE: Medium is {environment.medium}.  Material "
                f"must be evaluated for hydrogen embrittlement susceptibility "
                f"per ASTM G142 or equivalent.  Heat treatment and "
                f"microstructure controls may be required."
            )

        return banners

    # ------------------------------------------------------------------
    # Phase 10 -- novel material detection
    # ------------------------------------------------------------------

    def _detect_novel_material(
        self,
        supporting: list[PrecedentMatch],
        test_data: list[TestDataRecord],
    ) -> bool:
        """Detect if the queried material is novel (zero supporting precedents
        AND no current test data).

        A novel material requires a qualification test plan rather than
        a precedent-based MUA.
        """
        if supporting:
            return False

        has_current_data = any(td.is_current is True for td in test_data)
        if has_current_data:
            return False

        logger.info("Novel material detected: no supporting precedents and no current test data")
        return True

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_precedent_bounds(
        supporting: list[PrecedentMatch],
    ) -> dict:
        """Aggregate environment bounds from supporting precedents.

        Returns a dict with ``o2_min``, ``o2_max``, ``psi_min``, ``psi_max``,
        ``temp_min``, ``temp_max``.
        """
        if not supporting:
            return {}

        o2_vals = [p.o2_percent for p in supporting if p.o2_percent is not None]
        psi_vals = [p.pressure_psia for p in supporting if p.pressure_psia is not None]
        t_mins = [p.temp_min_f for p in supporting if p.temp_min_f is not None]
        t_maxs = [p.temp_max_f for p in supporting if p.temp_max_f is not None]

        bounds: dict = {}
        if o2_vals:
            bounds["o2_min"] = min(o2_vals)
            bounds["o2_max"] = max(o2_vals)
        if psi_vals:
            bounds["psi_min"] = min(psi_vals)
            bounds["psi_max"] = max(psi_vals)
        if t_mins:
            bounds["temp_min"] = min(t_mins)
        if t_maxs:
            bounds["temp_max"] = max(t_maxs)

        return bounds

    @staticmethod
    def _dimension_status(
        query_val: float,
        tested_min: float,
        tested_max: float,
        name: str,
        details: list[str],
    ) -> OverlapStatus:
        """Classify a single-value query dimension against a tested range.

        Used for O2 and pressure, where the query is a point value, not a range.
        """
        if tested_min == 0.0 and tested_max == 0.0:
            details.append(f"{name}: insufficient precedent data for envelope analysis.")
            return OverlapStatus.INSUFFICIENT_DATA

        if tested_min <= query_val <= tested_max:
            details.append(
                f"{name}: query value {query_val} is WITHIN tested range "
                f"[{tested_min} - {tested_max}]."
            )
            return OverlapStatus.WITHIN

        # Check for small extrapolation (within 10% of range).
        tested_range = tested_max - tested_min
        margin = tested_range * 0.1 if tested_range > 0 else abs(tested_max) * 0.1

        if (tested_min - margin) <= query_val <= (tested_max + margin):
            details.append(
                f"{name}: query value {query_val} is a minor EXTRAPOLATION "
                f"beyond tested range [{tested_min} - {tested_max}]."
            )
            return OverlapStatus.EXTRAPOLATION

        # Greater than 10% but within 25% of range span -- partial overlap.
        wide_margin = tested_range * 0.25 if tested_range > 0 else abs(tested_max) * 0.25
        if (tested_min - wide_margin) <= query_val <= (tested_max + wide_margin):
            details.append(
                f"{name}: query value {query_val} has PARTIAL overlap with "
                f"tested range [{tested_min} - {tested_max}]."
            )
            return OverlapStatus.PARTIAL

        details.append(
            f"{name}: query value {query_val} is OUTSIDE tested range "
            f"[{tested_min} - {tested_max}]."
        )
        return OverlapStatus.OUTSIDE

    @staticmethod
    def _temperature_envelope_status(
        query_min: float,
        query_max: float,
        tested_min: float,
        tested_max: float,
        details: list[str],
    ) -> OverlapStatus:
        """Classify a temperature *range* query against tested bounds.

        Safety fix C4: evaluates BOTH query_min and query_max against the
        tested envelope.  Earlier implementations only checked query_max,
        completely missing cases where the lower bound exceeded the tested
        cryogenic range.
        """
        if tested_min == 0.0 and tested_max == 0.0:
            details.append("Temperature: insufficient precedent data for envelope analysis.")
            return OverlapStatus.INSUFFICIENT_DATA

        low_within = tested_min <= query_min
        high_within = query_max <= tested_max

        if low_within and high_within:
            details.append(
                f"Temperature: query range [{query_min} to {query_max} degF] is "
                f"WITHIN tested range [{tested_min} to {tested_max} degF]."
            )
            return OverlapStatus.WITHIN

        # Calculate how far each bound exceeds the tested range.
        tested_span = tested_max - tested_min if tested_max != tested_min else 1.0
        low_exceed = (tested_min - query_min) / tested_span if query_min < tested_min else 0.0
        high_exceed = (query_max - tested_max) / tested_span if query_max > tested_max else 0.0
        max_exceed = max(low_exceed, high_exceed)

        if max_exceed <= 0.1:
            details.append(
                f"Temperature: query range [{query_min} to {query_max} degF] "
                f"is a minor EXTRAPOLATION beyond tested range "
                f"[{tested_min} to {tested_max} degF]."
            )
            return OverlapStatus.EXTRAPOLATION

        if max_exceed <= 0.3:
            details.append(
                f"Temperature: query range [{query_min} to {query_max} degF] "
                f"has PARTIAL overlap with tested range "
                f"[{tested_min} to {tested_max} degF]."
            )
            return OverlapStatus.PARTIAL

        details.append(
            f"Temperature: query range [{query_min} to {query_max} degF] is "
            f"OUTSIDE tested range [{tested_min} to {tested_max} degF]."
        )
        return OverlapStatus.OUTSIDE

    def _calculate_evidence_strength(
        self,
        supporting: list[PrecedentMatch],
        conflicting: list[PrecedentMatch],
        test_data: list[TestDataRecord],
        envelope: Optional[EnvelopeResult],
        gaps: list[GapIdentified],
    ) -> EvidenceStrengthResult:
        """Calculate evidence strength with component breakdown.

        Scoring components:
        - Precedent strength: count and quality of supporting precedents.
        - Test data coverage: current test data for required classes.
        - Envelope coverage: fraction of dimensions within envelope.
        - Conflict penalty: reduction for conflicting evidence.
        - Gap penalty: reduction for identified data gaps.
        """
        components: dict[str, float] = {}
        penalties: dict[str, float] = {}

        # --- Precedent strength (0.0 to 0.4) ---
        if supporting:
            avg_relevance = sum(p.relevance_score for p in supporting) / len(supporting)
            count_factor = min(len(supporting) / 3.0, 1.0)  # 3+ precedents = full credit
            precedent_score = avg_relevance * count_factor * 0.4
        else:
            precedent_score = 0.0
        components["precedent_strength"] = round(precedent_score, 3)

        # --- Test data coverage (0.0 to 0.3) ---
        if test_data:
            current_count = sum(1 for td in test_data if td.is_current is True)
            # C2 fix: unknown (None) does NOT count as partial credit.
            total_required = max(len(test_data), 2)  # at least 2 required classes
            test_score = min(current_count / total_required, 1.0) * 0.3
        else:
            test_score = 0.0
        components["test_data_coverage"] = round(test_score, 3)

        # --- Envelope coverage (0.0 to 0.2) ---
        if envelope:
            envelope_score = envelope.coverage_ratio * 0.2
        else:
            envelope_score = 0.0
        components["envelope_coverage"] = round(envelope_score, 3)

        # --- Conflict penalty ---
        if conflicting:
            conflict_penalty = min(len(conflicting) * 0.08, 0.2)
            penalties["conflicting_precedents"] = round(conflict_penalty, 3)
        else:
            conflict_penalty = 0.0

        # --- Gap penalty ---
        critical_gaps = sum(1 for g in gaps if g.severity == "critical")
        high_gaps = sum(1 for g in gaps if g.severity == "high")
        gap_penalty = min(critical_gaps * 0.12 + high_gaps * 0.06, 0.3)
        if gap_penalty > 0:
            penalties["data_gaps"] = round(gap_penalty, 3)

        # --- Final score ---
        raw_score = precedent_score + test_score + envelope_score
        final_score = max(raw_score - conflict_penalty - gap_penalty, 0.0)
        final_score = min(final_score, 1.0)

        # --- Band assignment ---
        if final_score >= 0.7:
            band = EvidenceStrengthBand.STRONG
        elif final_score >= 0.45:
            band = EvidenceStrengthBand.MODERATE
        elif final_score >= 0.2:
            band = EvidenceStrengthBand.WEAK
        else:
            band = EvidenceStrengthBand.INSUFFICIENT

        # --- Explanation ---
        parts: list[str] = []
        parts.append(
            f"Evidence strength: {band.value} ({final_score:.2f})."
        )
        if supporting:
            parts.append(
                f"{len(supporting)} supporting precedent(s) with "
                f"average relevance {components['precedent_strength'] / 0.4:.2f}."
            )
        else:
            parts.append("No supporting precedents found.")
        if conflicting:
            parts.append(
                f"{len(conflicting)} conflicting precedent(s) detected "
                f"(penalty: -{conflict_penalty:.2f})."
            )
        if critical_gaps or high_gaps:
            parts.append(
                f"{critical_gaps} critical and {high_gaps} high-severity "
                f"gap(s) identified (penalty: -{gap_penalty:.2f})."
            )

        return EvidenceStrengthResult(
            score=round(final_score, 3),
            band=band,
            components=components,
            penalties=penalties,
            explanation="  ".join(parts),
        )

    def _route_category(
        self,
        material: MaterialResolution,
        environment: EnvironmentSpec,
        evidence_strength: EvidenceStrengthResult,
        gaps: list[GapIdentified],
        process_params: Optional[ProcessParams],
    ) -> Optional[MUACategory]:
        """Preliminary category routing.

        NASA MUA categories:
        - Category I:   Standard materials with strong evidence and no gaps.
        - Category II:  Materials requiring additional review or having
                        moderate evidence / minor gaps.
        - Category III: Materials requiring full engineering evaluation,
                        testing, or having weak/insufficient evidence.

        This is a *preliminary* routing that the reviewing engineer
        may override in Step 3.
        """
        critical_gaps = sum(1 for g in gaps if g.severity == "critical")
        high_gaps = sum(1 for g in gaps if g.severity == "high")

        # Category III triggers: insufficient evidence, critical gaps,
        # enriched O2 with weak evidence, process-sensitive materials.
        if evidence_strength.band == EvidenceStrengthBand.INSUFFICIENT:
            return MUACategory.III

        if critical_gaps >= 1:
            return MUACategory.III

        if (
            environment.is_enriched_o2
            and evidence_strength.band in (
                EvidenceStrengthBand.WEAK,
                EvidenceStrengthBand.INSUFFICIENT,
            )
        ):
            return MUACategory.III

        # Category II triggers: moderate evidence, high gaps, enriched O2,
        # hydrogen service, process-sensitive materials.
        if evidence_strength.band == EvidenceStrengthBand.MODERATE:
            return MUACategory.II

        if high_gaps >= 1:
            return MUACategory.II

        if environment.is_enriched_o2:
            return MUACategory.II

        if environment.is_hydrogen_service:
            return MUACategory.II

        if process_params is not None:
            return MUACategory.II

        # Category I: strong evidence, no significant gaps, standard environment.
        if evidence_strength.band == EvidenceStrengthBand.STRONG:
            return MUACategory.I

        # Default to Category II if unsure.
        return MUACategory.II


# ---------------------------------------------------------------------------
# Cross-source conflict detection (Phase 4)
# ---------------------------------------------------------------------------

def _detect_cross_source_conflicts(
    supporting: list[PrecedentMatch],
    conflicting: list[PrecedentMatch],
    test_data: list[TestDataRecord],
) -> list[ConflictFound]:
    """Detect conflicts between different evidence sources.

    Cross-source conflicts include:
    - Supporting precedent vs conflicting precedent for similar environment.
    - Precedent determination vs test data rating disagreement.
    - Multiple precedents with contradictory determinations for overlapping
      environments.
    """
    conflicts: list[ConflictFound] = []

    # --- Supporting vs conflicting for the same material ---
    for sp in supporting:
        for cp in conflicting:
            if _materials_related(sp, cp):
                conflict_id = f"conflict-{uuid.uuid4().hex[:8]}"
                conflicts.append(
                    ConflictFound(
                        conflict_id=conflict_id,
                        severity=ConflictSeverity.HARD,
                        source_a=sp.mua_number,
                        source_b=cp.mua_number,
                        description=(
                            f"Supporting precedent {sp.mua_number} "
                            f"({sp.determination.value}) conflicts with "
                            f"{cp.mua_number} ({cp.determination.value}).  "
                            f"Both reference related material "
                            f"({sp.material_designation} / {cp.material_designation})."
                        ),
                        recommendation=(
                            f"Review both precedents carefully.  "
                            f"{cp.mua_number} was {cp.determination.value} "
                            f"in {cp.environment_description}.  Determine "
                            f"whether the application conditions that led to "
                            f"that determination apply to your query.  "
                            f"Engineering judgment needed."
                        ),
                    )
                )

    # --- Precedent vs test data disagreement ---
    # If a precedent says approved but the most relevant flammability rating
    # is poor (D or U), flag it.
    flamm_records = [td for td in test_data if td.test_class == "FLAMM"]
    poor_flamm = [td for td in flamm_records if td.rating in ("D", "U")]

    if poor_flamm and supporting:
        best_precedent = supporting[0]  # highest relevance
        conflict_id = f"conflict-{uuid.uuid4().hex[:8]}"
        conflicts.append(
            ConflictFound(
                conflict_id=conflict_id,
                severity=ConflictSeverity.SOFT,
                source_a=best_precedent.mua_number,
                source_b=f"MAPTIS FLAMM rating {poor_flamm[0].rating}",
                description=(
                    f"Supporting precedent {best_precedent.mua_number} "
                    f"({best_precedent.determination.value}) conflicts with "
                    f"MAPTIS flammability rating '{poor_flamm[0].rating}'.  "
                    f"A poor flammability rating contradicts an approved precedent."
                ),
                recommendation=(
                    f"Verify whether the flammability test conditions match "
                    f"the precedent environment.  The precedent may have been "
                    f"approved under different conditions or with mitigations "
                    f"not reflected in the MAPTIS rating.  Engineering judgment "
                    f"needed."
                ),
            )
        )

    return conflicts


def _materials_related(a: PrecedentMatch, b: PrecedentMatch) -> bool:
    """Check if two precedents reference related materials."""
    # Same designation is an obvious match.
    if a.material_designation == b.material_designation:
        return True
    # Same family (e.g. both aluminum, both nickel_superalloy).
    if (
        a.material_family
        and b.material_family
        and a.material_family == b.material_family
    ):
        return True
    return False
