"""MUA v7 Investigator --- Unified evidence-gathering pipeline.

Replaces 4 independent search/evaluation paths with one orchestrated pipeline.
Queries mua_precedents_v7 via PostgreSQL for search --- does NOT build a new
search backend.

Key safety fixes incorporated:
- C1: Relevance boosts capped at 1.0 (boosts are tiebreakers, not promoters)
- C2: Missing data = 0.0 (unknown), not 0.5 (neutral)
- C3: Multi-record consensus via tiered PG search (not single-result)
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

Co-Authored-By: Atlas (OpenAI GPT-5) <noreply@openai.com>
"""

from __future__ import annotations

import asyncio
import logging
import re
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
    ConflictFound,
    ConflictSeverity,
    EvidenceRef,
    SourceType,
    SourceLocator,
)

logger = logging.getLogger(__name__)

_ALLOWED_ISSUE_CODES: set[str] = {
    "FLAM",
    "TVS",
    "FS",
    "TOX",
    "OFFGAS",
    "O2_COMPAT",
    "HEE",
    "SCC",
    "CORR",
    "FRACTURE",
}

_ISSUE_CODE_ALIASES: dict[str, str] = {
    "FLAMM": "FLAM",
    "THERMAL_VAC_STABILITY": "TVS",
    "FLUID_SUSCEPTIBILITY": "FS",
    "O2": "O2_COMPAT",
    "O2COMPAT": "O2_COMPAT",
    "FRACTURE_CONTROL": "FRACTURE",
}


# Canonical family values in mua_precedents_v7.
_PG_CANONICAL_FAMILIES = {
    "STAINLESS_STEEL",
    "NICKEL_ALLOY",
    "ALUMINUM",
    "TITANIUM",
    "COPPER_ALLOY",
    "CARBON_STEEL",
    "ADHESIVE",
    "POLYMER",
    "ELASTOMER",
    "COATING",
    "CERAMIC",
    "SEALANT",
    "LUBRICANT",
    "COMPOSITE",
}

# MaterialResolver returns broad labels like "stainless"/"nickel".
# Map those onto canonical PG family values so tier 0/1/3 queries hit.
_PG_FAMILY_ALIAS_MAP = {
    "STAINLESS": "STAINLESS_STEEL",
    "CRES": "STAINLESS_STEEL",
    "SS": "STAINLESS_STEEL",
    "NICKEL": "NICKEL_ALLOY",
    "NICKEL_ALLOY": "NICKEL_ALLOY",
    "INCONEL": "NICKEL_ALLOY",
    "HASTELLOY": "NICKEL_ALLOY",
    "MONEL": "NICKEL_ALLOY",
    "ALUMINUM": "ALUMINUM",
    "ALUMINIUM": "ALUMINUM",
    "AL": "ALUMINUM",
    "TITANIUM": "TITANIUM",
    "TI": "TITANIUM",
    "COPPER": "COPPER_ALLOY",
    "COPPER_ALLOY": "COPPER_ALLOY",
    "STEEL": "CARBON_STEEL",
    "CARBON_STEEL": "CARBON_STEEL",
    "ADHESIVE": "ADHESIVE",
    "POLYMER": "POLYMER",
    "ELASTOMER": "ELASTOMER",
    "COATING": "COATING",
    "CERAMIC": "CERAMIC",
    "SEALANT": "SEALANT",
    "LUBRICANT": "LUBRICANT",
    "COMPOSITE": "COMPOSITE",
}


# ---------------------------------------------------------------------------
# Dependency stubs (no real dependency service yet)
# ---------------------------------------------------------------------------
# In production, dependency and revocation data will come from a dedicated
# service.  For now, these are empty so _check_dependencies is a no-op.

_MOCK_DEPENDENCIES: dict[str, list[str]] = {}
_MOCK_REVOKED: set[str] = set()


# MOCK DATA REMOVED -- _search_precedents() now queries mua_precedents_v7 via PG,
# _query_test_data() now calls query_maptis_test_data().
# See git history for the original sandbox mock data.

# S-2 safety fix: boosted relevance scores must NEVER exceed the base
# relevance score from the retriever.  Previously capped at 1.0, which
# allowed boosts to inflate beyond the base evidence level.


class MUAInvestigator:
    """Unified evidence-gathering pipeline for MUA v7 Step 2.

    Orchestrates parallel retrieval from precedent corpus (PostgreSQL tiered search),
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

    @staticmethod
    def _normalize_pg_family(
        family: Optional[str],
        designation: Optional[str] = None,
    ) -> Optional[str]:
        """Normalize resolver family labels into mua_precedents_v7 values."""
        raw = (family or "").strip()
        if raw:
            key = re.sub(r"[^A-Z0-9]+", "_", raw.upper()).strip("_")

            if key in _PG_CANONICAL_FAMILIES:
                return key
            if key in _PG_FAMILY_ALIAS_MAP:
                return _PG_FAMILY_ALIAS_MAP[key]

            if key.startswith("SS_") or key.startswith("STAINLESS"):
                return "STAINLESS_STEEL"
            if key.startswith("NI_") or key.startswith("NICKEL"):
                return "NICKEL_ALLOY"
            if key.startswith("AL_"):
                return "ALUMINUM"
            if key.startswith("TI_"):
                return "TITANIUM"
            if key.startswith("CU_"):
                return "COPPER_ALLOY"
            if key.startswith("ADHESIVE_"):
                return "ADHESIVE"
            if key.startswith("POLYMER_"):
                return "POLYMER"
            if key.startswith("ELASTOMER_"):
                return "ELASTOMER"
            if key.startswith("SEALANT_"):
                return "SEALANT"
            if key.startswith("COMPOSITE_"):
                return "COMPOSITE"
            if key.startswith("COATING_"):
                return "COATING"

        text = (designation or "").upper()
        if re.search(r"\b(STAINLESS|CRES|AISI\s*3\d{2})\b", text):
            return "STAINLESS_STEEL"
        if re.search(r"\b(INCONEL|HASTELLOY|MONEL|NICKEL|WASPALOY|RENE)\b", text):
            return "NICKEL_ALLOY"
        if re.search(r"\b(ALUMINUM|ALUMINIUM|AL\s*\d{3,4})\b", text):
            return "ALUMINUM"
        if re.search(r"\b(TITANIUM|TI\s*6AL|TI-)\b", text):
            return "TITANIUM"
        if re.search(r"\b(COPPER|BRONZE|BERYLLIUM COPPER|BECU)\b", text):
            return "COPPER_ALLOY"
        if re.search(r"\b(ADHESIVE|EPOXY|RTV|SEALANT|POTTING)\b", text):
            return "ADHESIVE"
        if re.search(r"\b(PEEK|PTFE|TEFLON|POLYIMIDE|VITON|NITRILE)\b", text):
            return "POLYMER"
        if re.search(r"\b(STEEL|AISI)\b", text):
            return "CARBON_STEEL"

        return None

    async def investigate(
        self,
        material: MaterialResolution,
        environment: EnvironmentSpec,
        process_params: Optional[ProcessParams] = None,
        center: str = "MSFC",
        issue_codes: Optional[list[str]] = None,
        approved_cat3_codes: Optional[list[str]] = None,
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
        issue_codes:
            Engineer-selected MAPTIS issue codes.  If provided, these
            define explicit investigation scope.  If ``None``, issue
            scope is auto-detected from environment.

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
            "Starting investigation for %s in %s (center=%s, issue_codes=%s)",
            material.resolved_name or material.input_text,
            environment.medium,
            center,
            issue_codes,
        )

        # Caller-selected issue codes override auto-detected issue scope.
        self._effective_issue_codes = self._resolve_issue_codes(environment, issue_codes)
        scope_adjust_notes: list[str] = []
        try:
            guarded_scope, guard_notes = await asyncio.to_thread(
                self._apply_fs_medium_scope_guard,
                material,
                environment,
                self._effective_issue_codes,
            )
            self._effective_issue_codes = guarded_scope
            scope_adjust_notes.extend(guard_notes)
        except Exception:
            logger.exception("FS scope guard failed; continuing with original issue scope")
        logger.info("Effective issue scope for investigation: %s", self._effective_issue_codes)

        # Phase 1 -- material identity is already resolved (passed in).

        # Phase 2 -- parallel evidence gathering.
        all_precedents: list[PrecedentMatch] = []
        test_data: list[TestDataRecord] = []

        try:
            all_precedents, test_data = await asyncio.gather(
                self._search_precedents(material, environment),
                self._query_test_data(material, environment),
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
            gaps = self._identify_gaps(
                envelope,
                test_data,
                environment,
                issue_scope=set(self._effective_issue_codes),
            )
        except Exception:
            logger.exception("Gap identification failed")

        # Phase 6 -- dependency checking (zombie MUAs).
        dep_warnings: list[DependencyWarning] = []
        try:
            dep_warnings = self._check_dependencies(all_precedents)
        except Exception:
            logger.exception("Dependency check failed")

        # Phase 7 -- evidence strength (S-3: use Fran's canonical formula).
        from .confidence import calculate_evidence_strength
        evidence_strength = calculate_evidence_strength(
            supporting_precedents=supporting,
            conflicting_precedents=conflicting,
            test_data=test_data,
            envelope=envelope,
            conflicts=conflicts,
            gaps=gaps,
            material=material,
            environment=environment,
            issue_codes=self._effective_issue_codes,
        )

        # Phase 8 -- preliminary category routing.
        preliminary_category = self._route_category(
            material=material,
            environment=environment,
            test_data=test_data,
            gaps=gaps,
            process_params=process_params,
            approved_cat3_codes=approved_cat3_codes,
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
        banners.extend(scope_adjust_notes)

        # S-4 safety fix: novel material must surface qualification plan offer.
        if is_novel:
            banners.append(
                "Novel material with limited precedent data. "
                "A Qualification Test Plan can be generated after MUA finalization."
            )

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
        """Search the precedent corpus via PostgreSQL (mua_precedents_v7).

        REPLACED Feb 2026: V6PrecedentRetriever (FAISS+BM25+RRF) replaced
        with direct PostgreSQL search. 10x faster, deterministic, auditable.

        S-2: relevance scores are capped at 1.0.
        C3: multiple records are returned and evaluated (top-k, not top-1).
        """
        from .pg_precedent_search import (
            pg_results_to_v7_matches,
            search_precedents_pg,
        )

        lookup_key = material.resolved_name or material.input_text
        family = self._normalize_pg_family(material.family, lookup_key)
        if material.family and family and material.family.upper() != family:
            logger.debug(
                "Normalized material family for PG search: %s -> %s",
                material.family,
                family,
            )

        # Derive issue codes from environment characteristics, then merge
        # with caller-selected overrides.
        issues = list(getattr(self, "_effective_issue_codes", None) or [])
        if not issues:
            issues = self._derive_issues_from_env(environment)

        # Derive canonical env_type from environment.
        env_type = self._derive_env_type(environment)

        try:
            pg_results = search_precedents_pg(
                material_designation=lookup_key,
                material_family=family,
                issues=issues,
                env_type=env_type,
                o2_percent=environment.o2_percent,
                pressure_psia=environment.pressure_psia,
                temp_max_f=environment.temp_max_f,
                temp_min_f=environment.temp_min_f,
                is_habitable=(environment.location == "habitable"),
                include_rejected=True,
            )
            if pg_results:
                precedents = pg_results_to_v7_matches(pg_results)
                logger.info(
                    "PG precedent search returned %d results for %r (env=%s, issues=%s)",
                    len(precedents),
                    lookup_key,
                    env_type,
                    issues,
                )
                return precedents
            logger.warning(
                "PG precedent search returned no results for %r (family=%s, env=%s, issues=%s). "
                "PG-only mode is enabled; returning no precedents.",
                lookup_key,
                family,
                env_type,
                issues,
            )
            return []
        except Exception:
            logger.exception(
                "PG precedent search failed for %r; PG-only mode is enabled so no fallback will run.",
                lookup_key,
            )
            return []

    @staticmethod
    def _derive_issues_from_env(env: EnvironmentSpec) -> list[str]:
        """Derive issue codes from environment characteristics.

        These codes match the canonical issue enum in mua_precedents_v7.
        Multiple codes can apply simultaneously.
        """
        issues: list[str] = []

        # Flammability is always relevant
        issues.append("FLAM")

        # O2 compatibility
        if env.is_enriched_o2 or (env.medium or "").upper() in (
            "GOX", "LOX", "OXYGEN", "O2", "ENRICHED_AIR", "ENRICHED_O2",
        ):
            issues.append("O2_COMPAT")

        # Hydrogen embrittlement
        if env.is_hydrogen_service:
            issues.append("HEE")

        # Stress corrosion cracking (salt spray, marine, humid)
        medium_lower = (env.medium or "").lower()
        if any(kw in medium_lower for kw in ["salt", "marine", "seawater", "humid"]):
            issues.append("SCC")
            issues.append("CORR")

        # Offgassing / toxicity (habitable)
        if env.location == "habitable":
            issues.append("OFFGAS")
            issues.append("TOX")

        # Cryogenic fracture
        if env.temp_min_f is not None and env.temp_min_f <= -150.0:
            issues.append("FRACTURE")

        return issues

    @staticmethod
    def _normalize_issue_codes(issue_codes: Optional[list[str]]) -> list[str]:
        """Normalize caller-provided issue codes to canonical values."""
        if not issue_codes:
            return []

        normalized: list[str] = []
        for raw in issue_codes:
            code = str(raw or "").strip().upper()
            if not code:
                continue
            code = _ISSUE_CODE_ALIASES.get(code, code)
            if code in _ALLOWED_ISSUE_CODES and code not in normalized:
                normalized.append(code)
        return normalized

    @classmethod
    def _resolve_issue_codes(
        cls,
        environment: EnvironmentSpec,
        issue_codes: Optional[list[str]],
    ) -> list[str]:
        """Resolve effective issue scope for this investigation run.

        If the caller selected issue codes, those are treated as explicit scope.
        Otherwise, issue codes are auto-derived from the environment.
        """
        caller_scope = cls._normalize_issue_codes(issue_codes)
        if caller_scope:
            return caller_scope
        return cls._derive_issues_from_env(environment)

    @staticmethod
    def _required_test_classes_for_issues(
        issue_codes: set[str],
        environment: EnvironmentSpec,
    ) -> set[str]:
        """Map issue scope to required MAPTIS test classes."""
        required_classes: set[str] = set()

        if "FLAM" in issue_codes or "O2_COMPAT" in issue_codes:
            required_classes.add("FLAMM")
        if "SCC" in issue_codes or "HEE" in issue_codes:
            required_classes.add("SCC")
        if "CORR" in issue_codes:
            required_classes.add("CORR")
        if "TVS" in issue_codes:
            required_classes.add("TVS")
        if "FS" in issue_codes:
            required_classes.add("FS")
        if environment.location == "habitable" and (
            "TOX" in issue_codes or "OFFGAS" in issue_codes
        ):
            required_classes.add("TOX")

        return required_classes

    @staticmethod
    def _derive_env_type(env: EnvironmentSpec) -> str:
        """Map EnvironmentSpec to canonical env_type for PG search.

        Returns one of the canonical env_type values stored in
        mua_precedents_v7.
        """
        medium_upper = (env.medium or "").upper()

        # Explicit O2 service
        if medium_upper in ("LOX", "GOX", "OXYGEN", "O2"):
            return "LOX_GOX"
        if medium_upper in ("ENRICHED_AIR", "ENRICHED_O2"):
            return "ENRICHED_O2"
        if env.is_enriched_o2:
            return "ENRICHED_O2"

        # Hydrogen
        if env.is_hydrogen_service or medium_upper in ("GH2", "LH2", "HYDROGEN", "H2"):
            return "HYDROGEN"

        # Habitable vs non-habitable air
        if env.location == "habitable":
            return "CABIN_AIR"

        if medium_upper in ("AIR", "AMBIENT", "STANDARD_AIR", ""):
            return "STANDARD_AIR"

        # Vacuum / space
        if medium_upper in ("VACUUM", "SPACE"):
            return "VACUUM"

        # Fluid service
        if any(kw in medium_upper for kw in ["NTO", "MMH", "N2O4", "HYDRAZINE"]):
            return "PROPELLANT"

        return "UNKNOWN"

    # ------------------------------------------------------------------
    # Phase 2b -- MAPTIS test data
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_uns(designation: str) -> Optional[str]:
        """Extract UNS code (e.g., S31600) from a designation string."""
        if not designation:
            return None
        match = re.search(r"\b([SNCGKJTAR]\d{5})\b", designation.upper())
        return match.group(1) if match else None

    @staticmethod
    def _extract_base_alloy(designation: str) -> Optional[str]:
        """Extract a base alloy token for related-code expansion."""
        if not designation:
            return None

        text = designation.upper()

        # Common explicit families first
        if "A-286" in text or "A286" in text:
            return "A-286"

        for family in ("INCONEL", "HASTELLOY", "MONEL"):
            match = re.search(rf"{family}\s*([A-Z]?-?\d{{2,4}})", text)
            if match:
                return f"{family} {match.group(1)}"

        # 4-digit alloys (e.g., 6061, 4340, 440C stem 440)
        match = re.search(r"\b(\d{3,4}[A-Z]?)\b", text)
        if match:
            return match.group(1)

        return None

    @staticmethod
    def _family_pattern(family_hint: Optional[str]) -> Optional[str]:
        """Return a SQL regex that keeps related-code expansion in-family."""
        hint = (family_hint or "").lower()
        if "stainless" in hint:
            return r"\y(STAINLESS|CRES|SST|SS)\y"
        if "aluminum" in hint:
            return r"\y(AL|ALUMINUM|ALUMINIUM)\y"
        if "nickel" in hint:
            return r"\y(INCONEL|HASTELLOY|MONEL|NICKEL)\y"
        if "titanium" in hint:
            return r"\y(TI|TITANIUM)\y"
        return None

    def _find_related_maptis_codes(
        self,
        material: MaterialResolution,
        *,
        max_related: int = 10,
    ) -> list[str]:
        """Find related MAPTIS material codes for the same alloy family.

        Uses UNS/base-alloy expansion so generic inputs (e.g., 316, 6061)
        can still retrieve evidence from sibling product forms/specs.
        """
        primary_code = str(material.material_code or "").strip()
        if not primary_code:
            return []

        try:
            import psycopg2
            from psycopg2.extras import DictCursor
            from mira.core.db_config import get_db_connection_params
        except Exception:
            logger.exception("Related-code lookup imports failed")
            return []

        designation = material.resolved_name or material.input_text or ""

        try:
            with psycopg2.connect(
                **get_db_connection_params(options="-c search_path=maptis,public")
            ) as conn:
                with conn.cursor(cursor_factory=DictCursor) as cursor:
                    # Prefer DB designation for the selected material code.
                    cursor.execute(
                        """
                        SELECT designation
                        FROM materials
                        WHERE material_code = %s
                        LIMIT 1
                        """,
                        (primary_code,),
                    )
                    row = cursor.fetchone()
                    if row and row.get("designation"):
                        designation = str(row["designation"])

                    uns_code = self._extract_uns(designation)
                    base_alloy = self._extract_base_alloy(designation)
                    family_regex = self._family_pattern(material.family)

                    conditions: list[str] = []
                    params: list[str] = []

                    if uns_code:
                        conditions.append("designation ILIKE %s")
                        params.append(f"%{uns_code}%")

                    if base_alloy:
                        conditions.append("designation ~* %s")
                        params.append(rf"\y{re.escape(base_alloy)}\y")

                    if not conditions:
                        return []

                    family_clause = ""
                    if family_regex:
                        family_clause = "AND designation ~* %s"
                        params.append(family_regex)

                    query = f"""
                        SELECT material_code
                        FROM materials
                        WHERE material_code IS NOT NULL
                          AND material_code != %s
                          AND ({" OR ".join(conditions)})
                          {family_clause}
                        ORDER BY designation
                        LIMIT %s
                    """

                    exec_params = [primary_code] + params + [max_related]
                    cursor.execute(query, exec_params)
                    return [str(r["material_code"]) for r in cursor.fetchall() if r.get("material_code")]
        except Exception:
            logger.exception("Related-code lookup failed for %s", primary_code)
            return []

    @staticmethod
    def _classify_medium_text(value: Optional[str]) -> str:
        text = (value or "").strip().upper()
        if not text:
            return "UNKNOWN"
        if any(
            k in text
            for k in (
                "HYDRAZINE",
                "N2H4",
                "MMH",
                "UDMH",
                "NTO",
                "N2O4",
                "DINITROGEN TETROXIDE",
            )
        ):
            return "HYDRAZINE"
        if re.search(r"\b(GH2|LH2|HYDROGEN|H2)\b", text):
            return "HYDROGEN"
        if any(k in text for k in ("GOX", "LOX", "OXYGEN", " O2")):
            return "OXYGEN"
        if "AIR" in text:
            return "AIR"
        return "UNKNOWN"

    @classmethod
    def _is_fs_medium_match(
        cls,
        environment: EnvironmentSpec,
        test_medium: Optional[str],
    ) -> Optional[bool]:
        env_cls = cls._classify_medium_text(environment.medium)
        if env_cls not in {"HYDROGEN", "HYDRAZINE", "OXYGEN"}:
            return None
        test_cls = cls._classify_medium_text(test_medium)
        if test_cls == "UNKNOWN":
            return None
        return env_cls == test_cls

    @staticmethod
    def _clean_null_text(value: Optional[str]) -> str:
        text = str(value or "").strip()
        if not text or text.upper() == "NULL":
            return ""
        return text

    def _sync_lookup_fs_media_context(self, material_codes: list[str]) -> dict:
        """Summarize FS media classes/examples for scope guarding."""
        rows = self._sync_query_fs_rows(material_codes)
        classes: set[str] = set()
        examples: list[str] = []
        source_count = 0

        for row in rows:
            media_text = self._clean_null_text(row.get("media_text"))
            if not media_text:
                media_text = self._clean_null_text(row.get("fluc_changes"))
            if not media_text:
                continue
            source_count += 1
            cls = self._classify_medium_text(media_text)
            if cls != "UNKNOWN":
                classes.add(cls)
            if len(examples) < 8:
                examples.append(media_text[:220])

        return {
            "classes": sorted(classes),
            "examples": examples,
            "source_count": source_count,
        }

    def _apply_fs_medium_scope_guard(
        self,
        material: MaterialResolution,
        environment: EnvironmentSpec,
        issue_codes: list[str],
    ) -> tuple[list[str], list[str]]:
        """Filter FS issue scope when DB media context conflicts with usage medium."""
        if "FS" not in issue_codes:
            return issue_codes, []

        usage_cls = self._classify_medium_text(environment.medium)
        if usage_cls != "HYDROGEN":
            return issue_codes, []

        primary_code = str(material.material_code or "").strip()
        if not primary_code:
            return issue_codes, []

        material_codes = [primary_code]
        for code in self._find_related_maptis_codes(material):
            if code not in material_codes:
                material_codes.append(code)

        ctx = self._sync_lookup_fs_media_context(material_codes)
        ctx_classes = set(ctx.get("classes") or [])
        reasons: list[str] = []

        if ctx_classes and "HYDROGEN" not in ctx_classes and "HYDRAZINE" in ctx_classes:
            filtered = [i for i in issue_codes if i != "FS"]
            reasons.append(
                "FS evidence appears tied to hydrazine/non-H2 media in DB; "
                "FS was removed from investigation scope for H2 usage."
            )
            return filtered, reasons

        if not ctx_classes:
            reasons.append(
                "No FS media mapping found in DB for this material. If your FS dataset is available, "
                "load it so FS can be medium-filtered (H2 vs hydrazine)."
            )

        return issue_codes, reasons

    @staticmethod
    def _sync_query_fs_rows(material_codes: list[str]) -> list[dict]:
        """Return raw FS rows from curated FC table plus silver report rows."""
        try:
            import psycopg2
            from psycopg2.extras import RealDictCursor
            from mira.core.db_config import get_db_connection_params
        except Exception:
            return []

        codes = sorted({str(c).strip() for c in material_codes if str(c).strip()})
        if not codes:
            return []
        codes_int = [int(c) for c in codes if c.isdigit()]

        rows_out: list[dict] = []
        seen: set[tuple[str, str, str, str, str, str]] = set()

        def _clean(value: object) -> str:
            text = str(value or "").strip()
            if not text or text.upper() == "NULL":
                return ""
            return text

        def _append_row(row: dict) -> None:
            key = (
                _clean(row.get("material_code")),
                _clean(row.get("testreportnumber")),
                _clean(row.get("testreportkey")),
                _clean(row.get("rating")),
                _clean(row.get("expire_flag")),
                _clean(row.get("media_text")),
            )
            if key in seen:
                return
            seen.add(key)
            rows_out.append(
                {
                    "material_code": key[0],
                    "rating": key[3],
                    "expire_flag": key[4],
                    "testreportkey": _clean(row.get("testreportkey")),
                    "testreportnumber": key[1],
                    "fluc_reference": _clean(row.get("fluc_reference")),
                    "updt_dte": _clean(row.get("updt_dte")),
                    "fluc_changes": _clean(row.get("fluc_changes")),
                    "media_text": key[5],
                }
            )

        try:
            cfg = get_db_connection_params(options="-c search_path=maptis,public")
            with psycopg2.connect(**cfg) as conn:
                with conn.cursor(cursor_factory=RealDictCursor) as cur:
                    # 1) Curated/ingested FC table by material_code (best source).
                    if codes_int:
                        cur.execute(
                            """
                            SELECT
                                material_code::text AS material_code,
                                rating::text AS rating,
                                ''::text AS expire_flag,
                                ''::text AS testreportkey,
                                COALESCE(test_report_no, '')::text AS testreportnumber,
                                ''::text AS fluc_reference,
                                COALESCE(date_tested::text, '')::text AS updt_dte,
                                COALESCE(material_fluid_changes, '')::text AS fluc_changes,
                                CONCAT_WS(
                                    ' | ',
                                    NULLIF(TRIM(COALESCE(media, '')), ''),
                                    NULLIF(TRIM(COALESCE(media_spec, '')), ''),
                                    NULLIF(TRIM(COALESCE(material_fluid_changes, '')), '')
                                )::text AS media_text
                            FROM maptis.fluid_compatibility_tests
                            WHERE material_code = ANY(%s)
                            """,
                            (codes_int,),
                        )
                        for row in cur.fetchall():
                            _append_row(dict(row))

                    # 2) Legacy silver rows (contains MAPTIS expire flag for some rows).
                    cur.execute(
                        """
                        SELECT
                            normalized_payload->>'materialkey' AS material_code,
                            normalized_payload->>'fluc_rating' AS rating,
                            normalized_payload->>'fluc_dataexpireflag' AS expire_flag,
                            normalized_payload->>'testreportkey' AS testreportkey,
                            normalized_payload->>'testreportnumber' AS testreportnumber,
                            normalized_payload->>'fluc_reference' AS fluc_reference,
                            normalized_payload->>'fluc_updt_dte' AS updt_dte,
                            normalized_payload->>'fluc_materialfluidchanges' AS fluc_changes
                        FROM silver_report_rows
                        WHERE contract_id = 'fluid_compatibility_report'
                          AND normalized_payload->>'materialkey' = ANY(%s)
                        """,
                        (codes,),
                    )
                    silver_rows = list(cur.fetchall())

                    report_numbers = sorted(
                        {
                            _clean(r.get("testreportnumber"))
                            for r in silver_rows
                            if _clean(r.get("testreportnumber"))
                        }
                    )

                    media_by_report: dict[str, str] = {}
                    if report_numbers:
                        cur.execute(
                            """
                            SELECT test_report_no, media, media_spec, material_fluid_changes
                            FROM maptis.fluid_compatibility_tests
                            WHERE test_report_no = ANY(%s)
                            """,
                            (report_numbers,),
                        )
                        for row in cur.fetchall():
                            report_no = _clean(row.get("test_report_no"))
                            if not report_no:
                                continue
                            parts = [
                                _clean(row.get("media")),
                                _clean(row.get("media_spec")),
                                _clean(row.get("material_fluid_changes")),
                            ]
                            text = " | ".join(p for p in parts if p)
                            if text and report_no not in media_by_report:
                                media_by_report[report_no] = text

                    for row in silver_rows:
                        report_no = _clean(row.get("testreportnumber"))
                        media_text = media_by_report.get(report_no, "")
                        payload = dict(row)
                        payload["testreportnumber"] = report_no
                        payload["media_text"] = media_text
                        _append_row(payload)
        except Exception:
            logger.exception("FS query failed for material codes: %s", codes)
            return []

        return rows_out

    async def _query_fs_test_data(
        self,
        material_codes: list[str],
        environment: EnvironmentSpec,
    ) -> list[TestDataRecord]:
        rows = await asyncio.to_thread(self._sync_query_fs_rows, material_codes)
        records: list[TestDataRecord] = []
        seen: set[tuple] = set()

        for row in rows:
            material_code = str(row.get("material_code") or "").strip()
            rating_raw = self._clean_null_text(row.get("rating"))
            rating = rating_raw.upper() if rating_raw else None

            expire_flag = self._clean_null_text(row.get("expire_flag"))
            if expire_flag == "2":
                is_current: Optional[bool] = True
            elif expire_flag == "1":
                is_current = False
            else:
                is_current = None

            test_key = self._clean_null_text(row.get("testreportkey"))
            report_no = self._clean_null_text(row.get("testreportnumber"))
            fluc_ref = self._clean_null_text(row.get("fluc_reference"))
            media_text = self._clean_null_text(row.get("media_text"))
            if not media_text:
                media_text = self._clean_null_text(row.get("fluc_changes"))

            report_parts = []
            if material_code:
                report_parts.append(material_code)
            if report_no:
                report_parts.append(report_no)
            elif test_key:
                report_parts.append(f"key:{test_key}")
            if fluc_ref:
                report_parts.append(f"ref:{fluc_ref}")
            report_number = ":".join(report_parts) if report_parts else None

            test_number = int(test_key) if test_key.isdigit() else None
            test_date = self._clean_null_text(row.get("updt_dte"))[:10] or None
            medium_match = self._is_fs_medium_match(environment, media_text or None)

            td = TestDataRecord(
                test_class="FS",
                rating=rating,
                test_number=test_number,
                report_number=report_number,
                is_current=is_current,
                test_date=test_date,
                test_medium=media_text or None,
                medium_match=medium_match,
            )
            key = (
                td.test_class,
                td.rating,
                td.test_number,
                td.report_number,
                td.is_current,
                td.test_date,
                td.test_medium,
                td.medium_match,
            )
            if key in seen:
                continue
            seen.add(key)
            records.append(td)

        return records

    async def _query_test_data(
        self,
        material: MaterialResolution,
        environment: EnvironmentSpec,
    ) -> list[TestDataRecord]:
        """Query MAPTIS test data for the selected code + related sibling codes.

        C2: records with missing currency default to is_current=None (scored 0.0).
        """
        primary_code = str(material.material_code or "").strip()
        if not primary_code:
            logger.warning("No material code for MAPTIS query")
            return []

        material_codes = [primary_code]
        for code in self._find_related_maptis_codes(material):
            if code not in material_codes:
                material_codes.append(code)

        try:
            from mira.mua.v6.maptis_test_data import query_maptis_test_data

            statuses = await asyncio.gather(
                *[
                    query_maptis_test_data(
                        material_code=code,
                        include_expired=True,
                    )
                    for code in material_codes
                ],
                return_exceptions=True,
            )
        except Exception:
            logger.exception("MAPTIS query failed for %r", material_codes)
            return []

        records: list[TestDataRecord] = []
        seen: set[tuple] = set()

        for code, status in zip(material_codes, statuses):
            if isinstance(status, Exception):
                logger.warning("MAPTIS query failed for %r: %s", code, status)
                continue

            for result in status.current_results:
                report = getattr(result, "report_number", None) or getattr(result, "report_id", None)
                td = TestDataRecord(
                    test_class=getattr(result, "test_class", "FLAMM"),
                    rating=getattr(result, "rating", None),
                    test_number=getattr(result, "test_number", None),
                    report_number=f"{code}:{report}" if report else code,
                    is_current=True,
                    test_date=getattr(result, "test_date", None),
                )
                key = (td.test_class, td.rating, td.report_number, td.is_current, td.test_date)
                if key not in seen:
                    seen.add(key)
                    records.append(td)

            for result in status.expired_results:
                report = getattr(result, "report_number", None) or getattr(result, "report_id", None)
                td = TestDataRecord(
                    test_class=getattr(result, "test_class", "FLAMM"),
                    rating=getattr(result, "rating", None),
                    test_number=getattr(result, "test_number", None),
                    report_number=f"{code}:{report}" if report else code,
                    is_current=False,
                    test_date=getattr(result, "test_date", None),
                )
                key = (td.test_class, td.rating, td.report_number, td.is_current, td.test_date)
                if key not in seen:
                    seen.add(key)
                    records.append(td)

        try:
            fs_records = await self._query_fs_test_data(material_codes, environment)
            if fs_records:
                for td in fs_records:
                    key = (
                        td.test_class,
                        td.rating,
                        td.report_number,
                        td.is_current,
                        td.test_date,
                        td.test_medium,
                        td.medium_match,
                    )
                    if key not in seen:
                        seen.add(key)
                        records.append(td)
        except Exception:
            logger.exception("FS media-aware query failed for %r", material_codes)

        logger.info(
            "MAPTIS query returned %d test records across %d code(s) (primary=%r)",
            len(records),
            len(material_codes),
            primary_code,
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
        issue_scope: Optional[set[str]] = None,
    ) -> list[GapIdentified]:
        """Identify evidence gaps across temperature, pressure, O2, toxicity, and test classes.

        Returns a list of gaps ordered by severity (critical first).
        """
        gaps: list[GapIdentified] = []
        normalized_scope = {c.upper() for c in (issue_scope or set()) if c}
        if not normalized_scope:
            normalized_scope = set(self._derive_issues_from_env(environment))

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
        if "O2_COMPAT" in normalized_scope and envelope and envelope.o2_status in (
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
        required_classes = self._required_test_classes_for_issues(
            normalized_scope, environment
        )

        available_classes = {
            (td.test_class or "").upper()
            for td in test_data
            if td.is_current is True
            and not (
                (td.test_class or "").upper() == "FS"
                and td.medium_match is False
            )
        }

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
            (td.test_class or "").upper() == "TOX" and td.is_current is True
            for td in test_data
        )
        tox_required = environment.location == "habitable" and (
            "TOX" in normalized_scope or "OFFGAS" in normalized_scope
        )
        if tox_required and not has_tox:
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
        expired_by_class: dict[str, list[TestDataRecord]] = {}
        for td in test_data:
            cls = (td.test_class or "").upper()
            if cls == "FS" and td.medium_match is False:
                # Skip non-applicable FS records for this environment medium.
                continue
            if td.is_current is not False:
                continue
            if cls not in required_classes:
                continue
            expired_by_class.setdefault(cls, []).append(td)

        for test_class, records in sorted(expired_by_class.items()):
            unique_reports: list[str] = []
            seen_reports: set[str] = set()
            for rec in records:
                report = rec.report_number
                if report and report not in seen_reports:
                    seen_reports.add(report)
                    unique_reports.append(report)

            report_preview = ", ".join(unique_reports[:3])
            more_suffix = ""
            if len(unique_reports) > 3:
                more_suffix = f" (+{len(unique_reports) - 3} more)"

            dated = [r.test_date for r in records if r.test_date]
            latest_date = max(dated) if dated else None

            gaps.append(
                GapIdentified(
                    gap_id=f"gap-expired-{test_class.lower()}-{uuid.uuid4().hex[:8]}",
                    dimension=f"expired_{test_class.lower()}",
                    description=(
                        f"{len(records)} expired {test_class} test record(s) found"
                        + (f" ({report_preview}{more_suffix})" if report_preview else "")
                        + ". May need re-test or engineering disposition."
                    ),
                    severity="medium",
                    nearest_data=latest_date,
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

    # S-3 SAFETY FIX: _calculate_evidence_strength DELETED.
    # All evidence strength calculations now route through
    # confidence.calculate_evidence_strength() which implements Fran's
    # saturation formula: 1 - exp(-k * sum(relevance_i * authority_i))
    # with weights wP=0.30, wT=0.25, wE=0.20, wC=0.10, wK=0.15.
    # The deleted method used a simpler linear formula with different
    # weights and band thresholds that could disagree with the canonical
    # implementation.

    def _route_category(
        self,
        material: MaterialResolution,
        environment: EnvironmentSpec,
        test_data: list[TestDataRecord],
        gaps: list[GapIdentified],
        process_params: Optional[ProcessParams],
        approved_cat3_codes: Optional[list[str]] = None,
    ) -> Optional[MUACategory]:
        """Preliminary category routing aligned to final standards logic.

        Step 2 must not invert category semantics. We reuse the v7
        ``CategoryRouter`` so preliminary and final category determinations
        follow the same 6016C rule order:
        Cat I safety triggers first, Cat III only when Appendix B criteria
        are satisfied, otherwise Cat II.
        """
        _ = process_params  # Reserved for future Cat III gate inputs.

        try:
            from .category_router import CategoryRouter

            result = CategoryRouter().route(
                environment=environment,
                test_data=test_data,
                gaps=gaps,
                material_resolution=material,
                engineer_notes=environment.application or "",
                approved_appendix_b_codes=approved_cat3_codes,
            )
            return result.category
        except Exception:
            logger.exception(
                "Preliminary category routing failed; defaulting to Category II."
            )
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

    # --- S-1 SAFETY FIX: Precedent vs test data disagreement ---
    # Uses top-k consensus, NOT first-record [0] access.
    # Aggregate across all poor flammability ratings and all supporting
    # precedents to build a consensus before flagging a conflict.
    flamm_records = [td for td in test_data if td.test_class == "FLAMM"]
    poor_flamm = [td for td in flamm_records if td.rating in ("D", "U")]

    if poor_flamm and supporting:
        # Top-k consensus: count positive vs negative determinations
        # across ALL supporting precedents, not just supporting[0].
        positive_count = sum(
            1 for p in supporting
            if p.determination in (DeterminationStatus.APPROVED, DeterminationStatus.CONDITIONAL)
        )
        total_supporting = len(supporting)
        # Aggregate poor flammability ratings
        poor_ratings = sorted(set(td.rating for td in poor_flamm))
        poor_rating_str = "/".join(poor_ratings)
        flamm_count = len(poor_flamm)

        conflict_id = f"conflict-{uuid.uuid4().hex[:8]}"
        conflicts.append(
            ConflictFound(
                conflict_id=conflict_id,
                severity=ConflictSeverity.SOFT,
                source_a=f"{positive_count}/{total_supporting} supporting precedents",
                source_b=f"MAPTIS FLAMM rating(s) {poor_rating_str} ({flamm_count} record(s))",
                description=(
                    f"{positive_count} of {total_supporting} supporting precedent(s) "
                    f"have positive determinations, but {flamm_count} MAPTIS "
                    f"flammability record(s) show poor rating(s) ({poor_rating_str}).  "
                    f"Poor flammability data may contradict precedent approvals."
                ),
                recommendation=(
                    f"Verify whether the flammability test conditions match "
                    f"the precedent environments.  Precedents may have been "
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
