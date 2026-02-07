#!/usr/bin/env python3
"""
Module: Query Engine V2
Purpose: Evidence-First Query Engine - MIRA V2

BoundState AI 2025
Version: 1.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Fran OpenAI 5 <noreply@openai.com>
Co-Authored-By: Grok 4.0 <noreply@x.ai>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: SWE-013, NASA-STD-8739.8B
Safety Critical: False
"""

from typing import List, Dict, Optional
from dataclasses import dataclass, asdict
from enum import Enum
import psycopg2
import psycopg2.extras
import os

# Intent classifier for routing
try:
    from mira.nlp.intent_classifier import IntentClassifier
    INTENT_CLASSIFIER_AVAILABLE = True
except ImportError:
    INTENT_CLASSIFIER_AVAILABLE = False
    IntentClassifier = None

# V6 MUA Retriever - preferred source for MUA precedents
try:
    from mira.mua.v6.retriever import V6PrecedentRetriever
    from mira.mua.v6.precedent_models import NormalizedEnvironment, EnvironmentType
    V6_AVAILABLE = True
except ImportError:
    V6_AVAILABLE = False
    V6PrecedentRetriever = None


class EnvironmentClass(str, Enum):
    """Coarse environment classification for safety decisions."""
    OXYGEN = "oxygen"
    HYDROGEN = "hydrogen"
    AIR_VACUUM = "air_vacuum"
    OTHER = "other"


def classify_environment(env_str: Optional[str], phase: Optional[str] = None) -> EnvironmentClass:
    """
    Classify a free-text environment string into a coarse class.

    This is intentionally conservative: we only say OXYGEN or HYDROGEN
    when the text is unambiguously pointing there.
    """
    if not env_str:
        return EnvironmentClass.OTHER

    env = env_str.lower()
    phase = (phase or "").lower()

    # Canonical oxygen signals
    if "oxygen" in env or "gox" in env or "lox" in env or "o2" in env or "o₂" in env:
        return EnvironmentClass.OXYGEN

    # Canonical hydrogen signals
    if "hydrogen" in env or "gh2" in env or "lh2" in env or "h2" in env or "h₂" in env:
        return EnvironmentClass.HYDROGEN

    # Typical air / vacuum language
    if "air" in env or "vacuum" in env or "air-vacuum" in env or "air – vacuum" in env:
        return EnvironmentClass.AIR_VACUUM

    return EnvironmentClass.OTHER


def infer_test_types(rationale: Optional[str]) -> set:
    """
    Infer test types from MUA rationale text.

    O2 compatibility is NOT a single test - it's a composite of:
    - Flammability tests
    - Mechanical impact tests
    - Particle impact / promoted combustion tests

    Returns:
        Set of test types found in rationale
    """
    if not rationale:
        return set()

    text = rationale.lower()
    test_types = set()

    # Flammability tests (relevant to O2 compatibility)
    if any(kw in text for kw in ["flammability", "flammable", "ignition", "combustion", "fire", "burn", "flame"]):
        test_types.add("flammability")

    # Mechanical impact tests (relevant to O2 compatibility)
    if any(kw in text for kw in ["mechanical impact", "impact test", "drop test", "shock"]):
        test_types.add("mechanical_impact")

    # Particle impact / promoted combustion (relevant to O2 compatibility)
    if any(kw in text for kw in ["particle impact", "promoted ignition", "promoted combustion", "particle combustion"]):
        test_types.add("particle_impact")

    # Corrosion tests (NOT relevant to O2 compatibility unless in O2 environment)
    if any(kw in text for kw in ["corrosion", "corrode", "rust", "pitting", "stress corrosion", "scc"]):
        test_types.add("corrosion")

    # Toxicity tests (NOT relevant to O2 compatibility)
    if any(kw in text for kw in ["toxicity", "toxic", "offgas", "outgas"]):
        test_types.add("toxicity")

    return test_types


def extract_hazards_from_mitigations(mitigations: Optional[list]) -> set:
    """
    Extract hazard tags from MUA mitigations JSONB field.

    Example mitigations format:
    [{"hazard": "FLAMM", "standards": ["ASTM E595"], ...}]

    Returns:
        Set of hazard codes (e.g., {"FLAMM", "CORR"})
    """
    if not mitigations:
        return set()

    hazards = set()
    for mitigation in mitigations:
        if isinstance(mitigation, dict) and mitigation.get("hazard"):
            hazards.add(mitigation["hazard"].upper())

    return hazards


def is_relevant_for_oxygen_query(test_types: set, env_class: EnvironmentClass, hazards: Optional[set] = None) -> bool:
    """
    Determine if MUA is relevant for oxygen compatibility query.

    O2 compatibility is a composite of:
    - Flammability (FLAMM)
    - Mechanical impact
    - Particle impact / promoted combustion

    NOT relevant: Corrosion (CORR), SCC, Toxicity (TOX) unless in O2 environment.

    Args:
        test_types: Inferred test types from rationale keywords
        env_class: Environment classification
        hazards: Hazard tags from mitigations JSONB (if available)

    Returns:
        True if MUA is relevant to oxygen compatibility
    """
    # If oxygen environment, all test types are relevant
    if env_class == EnvironmentClass.OXYGEN:
        return True

    # PREFERRED: Use structured hazard tags from mitigations JSONB
    if hazards:
        o2_relevant_hazards = {"FLAMM", "O2_COMPAT", "MECH_IMPACT", "PARTICLE_IMPACT", "PROMOTED_COMBUSTION"}

        # If has O2-relevant hazards, include it
        if hazards & o2_relevant_hazards:
            return True

        # If only has corrosion/toxicity hazards in non-O2 environment, exclude
        non_o2_hazards = {"CORR", "SCC", "TOX", "OUTGAS"}
        if hazards and hazards.issubset(non_o2_hazards):
            return False  # Only irrelevant hazards

    # FALLBACK: Use keyword-based test type inference
    o2_relevant_tests = {"flammability", "mechanical_impact", "particle_impact"}

    # If has O2-relevant tests, include it
    if test_types & o2_relevant_tests:
        return True

    # If only has corrosion/toxicity tests in non-O2 environment, exclude
    return False


@dataclass
class MaterialConstraints:
    """Parsed query constraints."""
    material: Optional[str] = None
    configuration: Optional[str] = None
    pressure_psi_max: Optional[float] = None
    temp_c_min: Optional[float] = None
    temp_c_max: Optional[float] = None
    o2_pct: Optional[float] = None
    environment: Optional[str] = None

    def to_dict(self) -> Dict:
        return asdict(self)


class EvidenceFirstQueryEngine:
    """
    Query engine enforcing evidence-first principles.

    Architecture:
    1. Parse query -> MaterialConstraints
    2. Query MUA precedents FIRST (required!)
    3. Query test data SECOND
    4. Fetch evidence rows for citations
    5. Evaluate requirements
    6. Return INSUFFICIENT DATA if no evidence
    7. Make decisions with MaterialDecider
    """

    def __init__(self, db_url: Optional[str] = None, enable_semantic: bool = True, llm_provider: str = "ollama"):
        """
        Initialize evidence-first query engine.

        Args:
            db_url: Database connection URL
            enable_semantic: Enable semantic search enhancement (default: True)
            llm_provider: LLM provider for answer generation - "ollama" or "haiku" (default: ollama)
        """
        self.llm_provider = llm_provider
        self.db_url = db_url or os.environ.get('MIRA_DB_URL')
        if not self.db_url:
            # Fallback to building from individual env vars or defaults
            self.db_url = self._build_db_url()

        self.conn = psycopg2.connect(self.db_url)
        psycopg2.extras.register_uuid()

        # Phase 3: Semantic evidence enhancement
        self.enable_semantic = enable_semantic
        self.semantic_retriever = None

        if self.enable_semantic:
            try:
                from .semantic_evidence import SemanticEvidenceRetriever
                from .relevance_scorer import RelevanceBand

                # Determine FAISS index directory
                index_dir = os.getenv('MIRA_INDEX_DIR')
                if not index_dir:
                    # Default to MIRA_V2/data/faiss_indexes relative to this file
                    current_dir = os.path.dirname(os.path.abspath(__file__))
                    index_dir = os.path.join(current_dir, "..", "data", "faiss_indexes")

                self.semantic_retriever = SemanticEvidenceRetriever(
                    db_url=self.db_url,
                    index_dir=index_dir
                )
                self.RelevanceBand = RelevanceBand
                print("[SEMANTIC] Semantic evidence retriever initialized")
            except Exception as e:
                print(f"[WARNING] Semantic search disabled: {e}")
                self.enable_semantic = False

        # V6 MUA Retriever - preferred source for MUA precedents
        self.v6_retriever = None
        if V6_AVAILABLE:
            try:
                self.v6_retriever = V6PrecedentRetriever()
                if self.v6_retriever.is_loaded():
                    print(f"[V6] MUA retriever loaded: {self.v6_retriever._index_builder._index.ntotal} precedents")
                else:
                    self.v6_retriever = None
            except Exception as e:
                print(f"[WARNING] V6 MUA retriever disabled: {e}")
                self.v6_retriever = None

        # Intent classifier for routing
        self.intent_classifier = None
        if INTENT_CLASSIFIER_AVAILABLE:
            self.intent_classifier = IntentClassifier()
            print("[INTENT] Intent classifier loaded for query routing")

    def _build_db_url(self) -> str:
        """Build database URL from environment or defaults."""
        host = os.getenv('POSTGRES_HOST', 'localhost')
        port = os.getenv('POSTGRES_PORT', '5432')
        db = os.getenv('POSTGRES_DB', 'mira')
        user = os.getenv('POSTGRES_USER', 'postgres')
        password = os.getenv('POSTGRES_PASSWORD', 'postgres')

        return f"postgresql://{user}:{password}@{host}:{port}/{db}"

    def _check_o2_deterministic_boundaries(self, constraints, raw_query: str) -> Optional[Dict]:
        """
        Check deterministic O2 compatibility boundaries BEFORE LLM involvement.

        This catches hard prohibitions like aluminum-in-GOX that should return
        consistent "NO" decisions regardless of what evidence is found.

        DETERMINISM FIX (2025-01-27): Ensures same query always gets same answer
        for safety-critical rules.

        Returns:
            Dict with deterministic decision if a hard rule applies, None otherwise
        """
        try:
            from mira.o2.engine import evaluate_o2_compatibility
            from mira.o2.models import O2CompatibilityRequest, OxygenPhase
            from core.models.answer import AnswerSeverity
        except ImportError:
            # O2 engine not available - skip deterministic check
            return None

        # Check if this is an O2-related query
        query_lower = raw_query.lower()
        is_o2_query = any(kw in query_lower for kw in [
            'oxygen', 'o2', 'o₂', 'gox', 'lox', 'lox service', 'oxygen service'
        ])

        if not is_o2_query:
            return None

        # Check if we have a material
        material = constraints.material if hasattr(constraints, 'material') else None
        if not material:
            return None

        # Extract pressure from constraints or query
        pressure_psia = None
        if hasattr(constraints, 'pressure_psi') and constraints.pressure_psi:
            pressure_psia = float(constraints.pressure_psi)
        elif hasattr(constraints, 'pressure_pa') and constraints.pressure_pa:
            pressure_psia = float(constraints.pressure_pa) / 6894.76

        # Try to extract pressure from query text if not in constraints
        if not pressure_psia:
            import re
            # Match patterns like "700 psi", "3000 psia", "200 psi"
            pressure_match = re.search(r'(\d+(?:\.\d+)?)\s*psi[a]?', query_lower)
            if pressure_match:
                pressure_psia = float(pressure_match.group(1))

        # Default to conservative pressure if not specified
        if not pressure_psia:
            pressure_psia = 1000.0  # Conservative default

        # Determine phase (GOX vs LOX)
        phase = OxygenPhase.GAS  # Default to GOX
        if 'lox' in query_lower or 'liquid oxygen' in query_lower or 'cryogenic' in query_lower:
            phase = OxygenPhase.LIQUID

        # Extract temperature (default to room temp)
        temperature_k = 294.26  # 70°F in Kelvin
        if hasattr(constraints, 'temperature_c') and constraints.temperature_c:
            temperature_k = float(constraints.temperature_c) + 273.15
        elif hasattr(constraints, 'temperature_f') and constraints.temperature_f:
            temperature_k = (float(constraints.temperature_f) - 32) * 5/9 + 273.15

        # Call deterministic O2 engine
        try:
            o2_request = O2CompatibilityRequest(
                question=raw_query,
                material_key=material,
                pressure_psia=pressure_psia,
                temperature_k=temperature_k,
                phase=phase,
            )

            result = evaluate_o2_compatibility(o2_request)

            # Only return for PROHIBITED (hard NO) decisions
            if result.classification == AnswerSeverity.PROHIBITED:
                print(f"[O2 BOUNDARY] PROHIBITED: {material} in {phase.value} at {pressure_psia} psia")
                return {
                    'status': 'success',
                    'query': raw_query,
                    'deterministic_decision': 'NO',
                    'decision_source': 'O2_BOUNDARY_CHECK',
                    'decision_rationale': result.rationale,
                    'boundary_check_results': [{
                        'verdict': 'PROHIBITED',
                        'rationale': result.rationale,
                        'margin': None,
                        'evidence_sources': [e.source_id for e in result.evidence]
                    }],
                    'mua_precedents_found': 0,
                    'test_results_found': 0,
                    'requirements_evaluated': 0,
                    'llm_answer': f"**NO** - {result.rationale}",
                    'explanation': f"**NO** - {result.rationale}",
                    'constraints': constraints.to_dict() if hasattr(constraints, 'to_dict') else {},
                    'insufficient_data': False,
                    'deterministic_decision_verified': True,
                    'mua_precedents': [],
                    'test_results': [],
                    'semantic_evidence': {
                        'total_results': 0,
                        'stats': {'high_confidence': 0, 'medium_confidence': 0}
                    },
                    'decisions': [{
                        'material_name': material,
                        'verdict': 'NO',
                        'reason': result.rationale,
                        'source': 'O2_DETERMINISTIC_BOUNDARY',
                        'evidence': [e.source_id for e in result.evidence]
                    }]
                }

            # For CAUTION, add a note but don't override LLM
            # Let the normal flow continue to gather evidence

        except Exception as e:
            print(f"[O2 BOUNDARY] Check failed (continuing to LLM): {e}")

        return None

    def query_semantic_evidence(self, raw_query: str, constraints: MaterialConstraints) -> Optional[Dict]:
        """
        STEP 2.5: Semantic evidence search (ENHANCEMENT - Phase 3)

        This enhances SQL queries with semantic similarity search across:
        - BOK Standards (1,868 sections)
        - MUA Precedents (9,734 vectors)
        - MAPTIS Data (130,661 test results)

        Returns semantically similar evidence that SQL might miss due to:
        - Different terminology (e.g., "CRES" vs "Stainless Steel")
        - Conceptual similarity (e.g., "flammability" finds "ignition" tests)
        - Related precedents (e.g., similar materials/environments)

        NOW INCLUDES MATERIAL FILTERING (per llm_fix.md) to prevent:
        - Aluminum queries returning silicone rubber evidence
        - PTFE queries returning wrong materials

        Args:
            raw_query: Natural language query
            constraints: Material constraints (used for material filtering)

        Returns:
            Dict with semantic evidence organized by confidence band, or None if disabled
        """
        if not self.enable_semantic or not self.semantic_retriever:
            return None

        try:
            # NOTE: Material filtering moved to post-search via materials_match() function
            # The FAISS vector search returns results based on semantic similarity,
            # and the materials_match() function handles naming variations like:
            # "aluminum 6061" -> "AL 6061-O SHAPES"
            # "stainless steel 316" -> "SS 316L" or "CRES 316"
            if constraints.material:
                print(f"[Semantic] Searching for material: {constraints.material}")

            evidence = self.semantic_retriever.get_evidence(
                query=raw_query,
                top_k_per_index=10,  # Top 10 from each index (increased for BOK recall)
                min_relevance=self.RelevanceBand.LOW,  # Low confidence minimum (safety boost will elevate critical results)
                fetch_content=True  # Get full content from database
            )

            return {
                'total_results': evidence.total_results,
                'stats': evidence.stats,
                'bok_standards': evidence.bok_standards,
                'mua_precedents': evidence.mua_precedents,
                'maptis_data': evidence.maptis_data,
                'top_results': evidence.top_results[:10]  # Top 10 overall
            }
        except Exception as e:
            print(f"[WARNING] Semantic search failed: {e}")
            return None

    def _query_v6_mua_precedents(self, constraints: MaterialConstraints, requested_env_class: Optional[EnvironmentClass]) -> List[Dict]:
        """Query MUA precedents from V6 FAISS index with proper environment matching.

        V6 has 6,370+ records with structured environment types (lox_gox, enriched_o2, etc.)
        vs the bok.mua_precedents table which lacks proper O2 classification.
        """
        if not self.v6_retriever:
            return []

        # Build search query - prioritize material name for relevance
        query_parts = []
        if constraints.material:
            # Repeat material 2x to boost relevance
            query_parts.append(constraints.material)
            query_parts.append(constraints.material)

        # Add environment terms (but don't overwhelm material)
        if requested_env_class == EnvironmentClass.OXYGEN:
            query_parts.append("oxygen compatibility")
        elif requested_env_class == EnvironmentClass.HYDROGEN:
            query_parts.append("hydrogen compatibility")
        elif constraints.environment:
            query_parts.append(constraints.environment)

        if not query_parts:
            query_parts.append("material compatibility")

        search_query = " ".join(query_parts)

        # Query V6 retriever using hybrid BM25 + FAISS search if available
        try:
            # Try hybrid search first (BM25 + FAISS with RRF fusion)
            if hasattr(self.v6_retriever, 'search_hybrid') and self.v6_retriever._bm25 is not None:
                hybrid_results = self.v6_retriever.search_hybrid(
                    search_query,
                    top_k=20,
                    bm25_candidates=50,
                    faiss_candidates=50,
                )
                # Convert to (record, score) format
                raw_results = [(rec, rrf_score) for rec, rrf_score, bm25_rank, faiss_rank in hybrid_results]
                print(f"[V6] Hybrid BM25+FAISS search: {len(raw_results)} results")
            else:
                # Fallback to semantic-only search
                raw_results = self.v6_retriever.search_raw(search_query, top_k=15)
                print(f"[V6] FAISS-only search: {len(raw_results)} results")
        except Exception as e:
            print(f"[V6] Search failed: {e}")
            return []

        # Convert V6 results to expected format
        results = []
        num_primary = 0
        num_secondary = 0

        for record, score in raw_results:
            # Map V6 EnvironmentType to EnvironmentClass
            v6_env = record.environment.type.value if record.environment else "unknown"

            if v6_env in ("lox_gox", "enriched_o2", "pure_o2"):
                env_class = EnvironmentClass.OXYGEN
            elif v6_env in ("hydrogen",):
                env_class = EnvironmentClass.HYDROGEN
            elif v6_env in ("vacuum", "cabin_air", "ambient"):
                env_class = EnvironmentClass.AIR_VACUUM
            else:
                env_class = EnvironmentClass.OTHER

            # Determine if primary match for environment
            is_primary = False
            if requested_env_class == EnvironmentClass.OXYGEN:
                is_primary = env_class == EnvironmentClass.OXYGEN
            elif requested_env_class == EnvironmentClass.HYDROGEN:
                is_primary = env_class == EnvironmentClass.HYDROGEN

            # Skip non-approved for safety
            determination = record.determination.upper() if record.determination else "UNKNOWN"
            if determination not in ("APPROVED", "CONDITIONAL", "UNKNOWN"):
                continue

            # Extract hazard/issue categories
            hazards = set()
            for issue in (record.issues or []):
                issue_val = issue.value if hasattr(issue, 'value') else str(issue)
                if issue_val in ("flammability", "o2_compat"):
                    hazards.add("FLAMM")
                elif issue_val == "toxicity":
                    hazards.add("TOX")
                elif issue_val in ("tvs", "offgassing"):
                    hazards.add("TVS")
                elif issue_val == "scc":
                    hazards.add("SCC")
                elif issue_val == "corrosion":
                    hazards.add("CORR")

            # Build result dict matching expected format
            result_dict = {
                "mua_number": record.mua_number,
                "material_name": record.material_designation,
                "material_specification": record.specification,
                "determination": determination,
                "rationale": record.rationale,
                "rationale_summary": record.application,
                "mitigations": None,  # V6 doesn't have this in same format
                "pressure_psi_max": record.environment.pressure_psia if record.environment else None,
                "temp_c_min": None,
                "temp_c_max": record.environment.temperature_f if record.environment else None,
                "o2_concentration_pct": record.environment.o2_percent if record.environment else None,
                "clause_numbers": None,
                "precedent_mua_ids": None,
                "parser_confidence": record.confidence,
                "is_reviewed": False,
                "parsed_date": None,
                "env_class": env_class.value,
                "is_primary_for_env": is_primary,
                "inferred_environment": v6_env,
                "test_types": [],
                "hazards": list(hazards),
                "v6_score": score,  # Semantic similarity score
                "source": "v6_faiss",  # Track source
            }

            results.append(result_dict)

            if is_primary:
                num_primary += 1
            else:
                num_secondary += 1

        if requested_env_class and results:
            print(f"[V6 MUA] Requested: {requested_env_class.value}, Primary: {num_primary}, Secondary: {num_secondary}")

        # Re-rank: Boost results where material name matches constraint
        if constraints.material and results:
            material_lower = constraints.material.lower()
            material_parts = material_lower.split()

            def material_match_score(r):
                """Score how well result matches material constraint."""
                mat_name = (r.get('material_name') or '').lower()
                score = 0

                # Exact substring match (highest priority)
                if material_lower in mat_name:
                    score += 100

                # All parts match (e.g., "6061" and "aluminum" both found)
                parts_found = sum(1 for p in material_parts if p in mat_name)
                score += parts_found * 20

                # Primary environment match bonus
                if r.get('is_primary_for_env'):
                    score += 50

                return score

            results.sort(key=lambda r: material_match_score(r), reverse=True)

        return results

    def query_mua_precedents(self, constraints: MaterialConstraints) -> List[Dict]:
        """
        STEP 1: Query MUA precedents FIRST (6,370+ records via V6 FAISS)
        Per .claude-code-rules.md line 47-54

        This is the CRITICAL first step - we MUST check historic NASA decisions
        before doing anything else.

        Uses V6 FAISS retriever (preferred) with structured environment types,
        falls back to bok.mua_precedents table if V6 unavailable.
        """
        # Determine requested environment class
        requested_env = (constraints.environment or "").lower()
        requested_env_class: Optional[EnvironmentClass] = None
        if "oxygen" in requested_env or "gox" in requested_env or "lox" in requested_env or "o2" in requested_env or "o₂" in requested_env:
            requested_env_class = EnvironmentClass.OXYGEN
        elif "hydrogen" in requested_env or "h2" in requested_env or "h₂" in requested_env:
            requested_env_class = EnvironmentClass.HYDROGEN

        # Try V6 FAISS retriever first (preferred - has structured environment types)
        if self.v6_retriever:
            v6_results = self._query_v6_mua_precedents(constraints, requested_env_class)
            if v6_results:
                return v6_results
            print("[V6] No results, falling back to bok.mua_precedents")

        # Fallback to bok.mua_precedents table
        cur = self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        query = """
            SELECT
                mua_number, material_name, material_specification,
                determination, rationale, rationale_summary, mitigations,
                pressure_psi_max, temp_c_min, temp_c_max, o2_concentration_pct,
                clause_numbers, precedent_mua_ids, parser_confidence,
                is_reviewed, parsed_date
            FROM bok.mua_precedents
            WHERE 1=1
        """
        params = []

        if constraints.material:
            query += " AND LOWER(material_name) LIKE LOWER(%s)"
            params.append(f"%{constraints.material}%")

        if constraints.pressure_psi_max:
            query += " AND pressure_psi_max >= %s"
            params.append(constraints.pressure_psi_max)

        if constraints.temp_c_min:
            query += " AND temp_c_min <= %s"
            params.append(constraints.temp_c_min)

        if constraints.temp_c_max:
            query += " AND temp_c_max >= %s"
            params.append(constraints.temp_c_max)

        if constraints.o2_pct:
            query += " AND o2_concentration_pct >= %s"
            params.append(constraints.o2_pct)

        # Prioritize APPROVED and CONDITIONAL
        query += " AND determination IN ('APPROVED', 'CONDITIONAL')"

        # Order by quality: reviewed first, then confidence, then date
        query += " ORDER BY is_reviewed DESC, parser_confidence DESC, parsed_date DESC LIMIT 10"

        cur.execute(query, params)
        rows = cur.fetchall()
        cur.close()

        # Process each MUA to classify environment and mark primary matches
        results = []
        num_primary = 0
        num_secondary = 0

        for row in rows:
            row_dict = dict(row)

            # Infer environment from rationale and specification text
            rationale_text = (row_dict.get("rationale") or "") + " " + (row_dict.get("material_specification") or "")
            env_class = classify_environment(rationale_text)

            # Extract hazard tags from mitigations JSONB (preferred method)
            hazards = extract_hazards_from_mitigations(row_dict.get("mitigations"))

            # Fallback: Infer test types from rationale keywords if no hazard tags
            test_types = infer_test_types(row_dict.get("rationale"))

            # For oxygen queries, filter out irrelevant MUAs
            # (e.g., corrosion-only tests in air/vacuum)
            if requested_env_class == EnvironmentClass.OXYGEN:
                if not is_relevant_for_oxygen_query(test_types, env_class, hazards):
                    # Skip this MUA - not relevant to oxygen compatibility
                    print(f"[MUA FILTER] Skipping {row_dict.get('mua_number')}: hazards={hazards}, test_types={test_types}, env={env_class.value}")
                    continue

            is_primary = False

            if requested_env_class is not None:
                # Only MUAs with matching environment are "primary"
                is_primary = (env_class == requested_env_class)

            row_dict["env_class"] = env_class.value
            row_dict["is_primary_for_env"] = is_primary
            row_dict["inferred_environment"] = env_class.value  # For debugging
            row_dict["test_types"] = list(test_types)  # For debugging
            row_dict["hazards"] = list(hazards)  # For debugging

            results.append(row_dict)

            if is_primary:
                num_primary += 1
            else:
                num_secondary += 1

        # Log environment breakdown for debugging
        if requested_env_class is not None and results:
            print(f"[MUA ENV] Requested: {requested_env_class.value}, Primary: {num_primary}, Secondary: {num_secondary}")

        return results

    def query_test_data(self, constraints: MaterialConstraints) -> List[Dict]:
        """
        STEP 2: Query test data SECOND (30,462+ records)
        Per .claude-code-rules.md line 56-62

        Only called AFTER MUA precedents have been queried.

        NOTE: Gracefully handles missing view/table by returning empty list.
        Semantic evidence will provide additional context when SQL data is limited.
        """
        cur = self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        try:
            # Try querying map.test_results (actual MAPTIS data)
            # Note: material_id is UUID in test_results, material_key is integer in materials
            # We'll fetch material name separately if needed
            query = """
                SELECT
                    tr.result_id as material_id,
                    tr.material_id::text as material_name,
                    tr.environment,
                    tr.temp_max_c as temp_max_tested_c,
                    tr.pressure_max_pa as pressure_max_tested_pa,
                    tr.rating as highest_rating,
                    1 as test_count,
                    tr.test_date
                FROM map.test_results tr
                WHERE 1=1
            """
            params = []

            # Note: Can't filter by material name without JOIN
            # Semantic evidence will handle material-specific queries
            if constraints.material:
                # Skip material name filter (table uses UUIDs, not names)
                pass

            if constraints.environment:
                query += " AND tr.environment = %s"
                params.append(constraints.environment)

            if constraints.pressure_psi_max:
                # Convert psi to Pa
                query += " AND tr.pressure_max_pa >= %s"
                params.append(constraints.pressure_psi_max * 6894.76)

            if constraints.temp_c_max:
                query += " AND tr.temp_max_c >= %s"
                params.append(constraints.temp_c_max)

            query += " ORDER BY tr.test_date DESC LIMIT 20"

            cur.execute(query, params)
            results = cur.fetchall()
            cur.close()

            return [dict(row) for row in results]

        except Exception as e:
            # Gracefully handle missing table/view or empty results
            print(f"[WARNING] Test data query failed (will rely on semantic evidence): {e}")
            cur.close()
            # CRITICAL: Rollback transaction so subsequent queries can proceed
            self.conn.rollback()
            return []

    def fetch_evidence_rows(self, material_id: str) -> List[Dict]:
        """
        Fetch evidence rows per evidence-schema skill.
        Returns structured evidence with citations.
        """
        cur = self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        cur.execute("""
            SELECT
                property, value, source, test_method, date,
                confidence, units, test_conditions, authority_tier,
                lab, accreditation, n_samples, notes
            FROM map.evidence
            WHERE material_id = %s
            ORDER BY authority_tier ASC, date DESC
        """, (material_id,))

        results = cur.fetchall()
        cur.close()

        return [dict(row) for row in results]

    def evaluate_requirements(self, constraints: MaterialConstraints) -> List[Dict]:
        """
        Query bok.requirements and evaluate against constraints.
        Per Phase 4 requirement to wire evaluator.
        """
        cur = self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        # Fetch relevant requirements based on environment
        cur.execute("""
            SELECT
                r.req_id, r.section_id, r.action, r.description, r.predicate,
                s.spec_id, s.section_number, s.heading
            FROM bok.requirements r
            JOIN bok.sections s ON r.section_id = s.section_id
            WHERE s.is_normative = true
            ORDER BY s.spec_id, s.section_number
        """)

        results = cur.fetchall()
        cur.close()

        return [dict(row) for row in results]

    def _materials_search(self, raw_query: str, constraints: MaterialConstraints) -> Dict:
        """
        Simple materials search - NO compatibility logic applied.

        This is for queries like "show me fluorosilicone materials" where the user
        just wants a list of materials, NOT a compatibility assessment.

        Returns materials matching the query without:
        - O2/H2 BOK rules
        - Pressure/temperature envelope filtering
        - Compatibility decisions

        Args:
            raw_query: Natural language query
            constraints: Parsed material constraints

        Returns:
            Dict with status, materials list, and metadata
        """
        print(f"[MATERIALS SEARCH] Simple database lookup (no BOK rules)")

        cur = self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        # Extract material family keywords for search
        query_lower = raw_query.lower()

        # Try to identify material family
        material_families = {
            'fluorosilicone': 833,
            'silicone': 832,
            'ptfe': 700,
            'teflon': 700,
            'aluminum': 100,
            'stainless': 200,
            'inconel': 300,
            'titanium': 400,
        }

        composition_key = None
        for family, comp_key in material_families.items():
            if family in query_lower:
                composition_key = comp_key
                break

        results = []

        try:
            # Search by composition if we identified a family
            if composition_key:
                print(f"[MATERIALS SEARCH] Searching by composition key: {composition_key}")
                cur.execute("""
                    SELECT DISTINCT
                        m.material_key,
                        m.designation,
                        m.material_code,
                        m.composition
                    FROM materials m
                    WHERE m.composition = %s
                    ORDER BY m.designation
                    LIMIT 100
                """, (composition_key,))
                results = [dict(row) for row in cur.fetchall()]

            # Fallback: Search by name if no composition match or no results
            if not results and constraints.material:
                print(f"[MATERIALS SEARCH] Searching by name: {constraints.material}")
                cur.execute("""
                    SELECT DISTINCT
                        m.material_key,
                        m.designation,
                        m.material_code,
                        m.composition
                    FROM materials m
                    WHERE LOWER(m.designation) LIKE LOWER(%s)
                    ORDER BY m.designation
                    LIMIT 100
                """, (f"%{constraints.material}%",))
                results = [dict(row) for row in cur.fetchall()]

            # Final fallback: Search silver_report_rows payloads
            if not results:
                search_term = constraints.material or query_lower.split()[0]
                print(f"[MATERIALS SEARCH] Searching silver_report_rows for: {search_term}")
                cur.execute("""
                    SELECT DISTINCT
                        normalized_payload->>'materialkey' as material_key,
                        normalized_payload->>'matl_designation' as designation,
                        normalized_payload->>'matl_materialcode' as material_code,
                        contract_id
                    FROM silver_report_rows
                    WHERE LOWER(normalized_payload->>'matl_designation') LIKE LOWER(%s)
                       OR LOWER(normalized_payload::text) LIKE LOWER(%s)
                    ORDER BY normalized_payload->>'matl_designation'
                    LIMIT 100
                """, (f"%{search_term}%", f"%{search_term}%"))
                results = [dict(row) for row in cur.fetchall()]

        except Exception as e:
            print(f"[MATERIALS SEARCH] Query error: {e}")
            self.conn.rollback()

        cur.close()

        print(f"[MATERIALS SEARCH] Found {len(results)} materials")

        return {
            'status': 'SUCCESS',
            'query': raw_query,
            'query_type': 'materials_search',
            'constraints': constraints.to_dict(),
            'materials_found': len(results),
            'materials': results,
            'evidence_first_verified': False,  # Materials search doesn't use evidence-first
            'note': 'Simple materials lookup - no compatibility rules applied. '
                    'For compatibility assessment, ask "Is X compatible with O2?"'
        }

    def query(self, raw_query: str, parsed_constraints: Optional[MaterialConstraints] = None) -> Dict:
        """
        Main query method - EVIDENCE-FIRST IMPLEMENTATION

        Flow (enforces .claude-code-rules.md):
        1. Parse query -> MaterialConstraints
        2. Query MUA precedents FIRST (CRITICAL!)
        3. Query test data SECOND
        4. Fetch evidence rows for citations
        5. Evaluate requirements
        6. Return INSUFFICIENT DATA if no evidence
        7. Make decisions with MaterialDecider

        Args:
            raw_query: Natural language query
            parsed_constraints: Pre-parsed constraints (optional)

        Returns:
            Dict with status, decisions, evidence, citations
        """
        # Import here to avoid circular dependency
        from .constraint_interpreter import ConstraintInterpreter

        # Step 1: Parse query (if not already parsed)
        if parsed_constraints is None:
            interpreter = ConstraintInterpreter()
            constraints = interpreter.parse_query(raw_query)
        else:
            constraints = parsed_constraints

        # =========================================================================
        # STEP 1.1: INTENT CLASSIFICATION & ROUTING (2025-02-04)
        # Route between:
        # - compatibility_query → Full O2/H2 Knowledge Twin (BOK rules, evidence, decisions)
        # - materials_query → Simple database lookup (composition filter, no intelligence)
        # =========================================================================
        if self.intent_classifier:
            intent_result = self.intent_classifier.classify(raw_query)
            best_intent, intent_score = intent_result.best()
            print(f"[INTENT] Classified as '{best_intent}' (score: {intent_score:.2f})")

            # Check for competing intents
            compat_score = intent_result.scores.get('compatibility_query', 0.0)
            materials_score = intent_result.scores.get('materials_query', 0.0)

            # Route to simple materials search if:
            # 1. materials_query is the winner OR
            # 2. materials_query scores high AND compatibility_query scores low
            if best_intent == 'materials_query' or (
                materials_score > 0.4 and compat_score < 0.3
            ):
                print(f"[ROUTING] → Materials Search (no BOK rules)")
                return self._materials_search(raw_query, constraints)
            elif best_intent == 'compatibility_query' or compat_score > 0.3:
                print(f"[ROUTING] → Compatibility Engine (full BOK rules)")
                # Continue to full evidence-first pipeline below
            else:
                # Ambiguous - check for gas service keywords as tiebreaker
                query_lower = raw_query.lower()
                has_gas_service = any(kw in query_lower for kw in [
                    'oxygen', 'o2', 'gox', 'lox', 'hydrogen', 'h2', 'gh2', 'lh2',
                    'compatible', 'compatibility', 'service', 'psi', 'pressure'
                ])
                if not has_gas_service and materials_score > 0:
                    print(f"[ROUTING] → Materials Search (no gas service context)")
                    return self._materials_search(raw_query, constraints)
                # Default: proceed to full pipeline

        # =========================================================================
        # STEP 1.5: DETERMINISTIC O2 BOUNDARY CHECK (2025-01-27)
        # Check for hard prohibitions (e.g., aluminum in GOX) BEFORE LLM involvement
        # This ensures consistent, deterministic decisions for safety-critical rules
        # =========================================================================
        o2_boundary_result = self._check_o2_deterministic_boundaries(constraints, raw_query)
        if o2_boundary_result:
            print(f"[O2 BOUNDARY] Deterministic decision: {o2_boundary_result['deterministic_decision']}")
            return o2_boundary_result

        # Step 2: Query MUA precedents FIRST (CRITICAL!)
        print(f"[1/6] Querying MUA precedents for: {constraints.material or 'any material'}")
        mua_precedents = self.query_mua_precedents(constraints)
        print(f"      Found {len(mua_precedents)} MUA precedents")

        # Step 3: Query test data SECOND
        print(f"[2/6] Querying test data...")
        test_results = self.query_test_data(constraints)
        print(f"      Found {len(test_results)} test results")

        # Step 3.5: Query semantic evidence (ENHANCEMENT - Phase 3)
        print(f"[3/6] Semantic evidence search...")
        semantic_evidence = self.query_semantic_evidence(raw_query, constraints)
        if semantic_evidence:
            print(f"      Found {semantic_evidence['total_results']} semantic matches")
            print(f"      High confidence: {semantic_evidence['stats'].get('high_confidence', 0)}")
            print(f"      Medium confidence: {semantic_evidence['stats'].get('medium_confidence', 0)}")
        else:
            print(f"      Semantic search disabled or unavailable")

        # Step 4: Check for insufficient data (CRITICAL!)
        # SAFETY FIX (2025-11-24): If material is specified but no MUA/test data exists,
        # semantic evidence alone is NOT sufficient - it may be generic BOK standards
        # that don't apply to the specific material (e.g., "unobtainium-42").
        has_material_specific_evidence = bool(mua_precedents or test_results)
        has_semantic_evidence = bool(semantic_evidence and semantic_evidence['total_results'] > 0)

        # If material was specified in query, require material-specific evidence
        if constraints.material:
            if not has_material_specific_evidence:
                # Check if semantic evidence actually mentions the material
                material_mentioned_in_semantic = False
                if semantic_evidence:
                    material_lower = constraints.material.lower()

                    def get_content_field(hit, field):
                        """Safely get content field from dict or dataclass."""
                        if hasattr(hit, 'content'):
                            content = hit.content or {}
                        elif isinstance(hit, dict):
                            content = hit.get('content', {})
                        else:
                            return ''
                        if isinstance(content, dict):
                            return content.get(field, '') or ''
                        elif hasattr(content, field):
                            return getattr(content, field, '') or ''
                        return ''

                    def materials_match(query_material: str, db_material: str) -> bool:
                        """Flexible material name matching.

                        Handles common variations:
                        - 'aluminum 6061' matches 'AL 6061-O SHAPES'
                        - 'stainless steel 316' matches 'SS 316L' or 'CRES 316'
                        - 'inconel 718' matches 'INCONEL 718'
                        - 'titanium 6al-4v' matches 'TI 6AL-4V'
                        """
                        if not query_material or not db_material:
                            return False

                        q = query_material.lower().strip()
                        d = db_material.lower().strip()

                        # Direct match
                        if q in d or d in q:
                            return True

                        import re

                        # Extract alloy numbers (e.g., 6061, 316, 718, 2024)
                        # Strip trailing letters for comparison (316L -> 316)
                        q_numbers_raw = re.findall(r'\b(\d{3,4})[A-Za-z]?\b', q)
                        d_numbers_raw = re.findall(r'\b(\d{3,4})[A-Za-z]?\b', d)
                        q_numbers = set(q_numbers_raw)
                        d_numbers = set(d_numbers_raw)

                        # Also extract titanium-style designations (6al-4v, 6-4, etc.)
                        q_ti_alloys = set(re.findall(r'\b(\d+al-\d+v)\b', q))
                        d_ti_alloys = set(re.findall(r'\b(\d+al-\d+v)\b', d))

                        # Material family aliases
                        family_aliases = {
                            'aluminum': ['al', 'aluminium'],
                            'stainless': ['ss', 'cres', 'stainless steel'],
                            'inconel': ['in', 'inconel'],
                            'hastelloy': ['ha', 'hastelloy'],
                            'monel': ['monel'],
                            'titanium': ['ti', 'titanium'],
                            'copper': ['cu', 'copper'],
                            'nickel': ['ni', 'nickel'],
                            'steel': ['steel'],
                        }

                        # Check titanium alloy match (6al-4v style)
                        if q_ti_alloys and d_ti_alloys and q_ti_alloys & d_ti_alloys:
                            return True

                        # Check if alloy numbers match
                        if q_numbers and d_numbers and q_numbers & d_numbers:
                            # Same alloy number - check if material families are compatible
                            for family, aliases in family_aliases.items():
                                q_has_family = family in q or any(alias in q for alias in aliases)
                                d_has_family = family in d or any(alias in d for alias in aliases)
                                if q_has_family and d_has_family:
                                    return True
                                # If query has family and db has alloy number match, likely same material
                                if q_has_family and q_numbers & d_numbers:
                                    return True

                        return False

                    # Check MAPTIS hits (high AND medium confidence)
                    maptis_data = semantic_evidence.get('maptis_data', {})
                    maptis_hits = []
                    if isinstance(maptis_data, dict):
                        maptis_hits = maptis_data.get('high', []) + maptis_data.get('medium', [])
                    for hit in maptis_hits:
                        material_name = (get_content_field(hit, 'material_designation') or
                                        get_content_field(hit, 'material_name')).lower()
                        if material_name and materials_match(material_lower, material_name):
                            material_mentioned_in_semantic = True
                            print(f"[MATCH] Found material match: '{material_name}' for query '{material_lower}'")
                            break

                    # Check MUA semantic hits (high AND medium confidence)
                    if not material_mentioned_in_semantic:
                        mua_data = semantic_evidence.get('mua_precedents', {})
                        mua_hits = []
                        if isinstance(mua_data, dict):
                            mua_hits = mua_data.get('high', []) + mua_data.get('medium', [])
                        for hit in mua_hits:
                            material_name = get_content_field(hit, 'material_name').lower()
                            if material_name and materials_match(material_lower, material_name):
                                material_mentioned_in_semantic = True
                                print(f"[MATCH] Found MUA match: '{material_name}' for query '{material_lower}'")
                                break

                if not material_mentioned_in_semantic:
                    print(f"[INSUFFICIENT DATA] Material '{constraints.material}' not found in any database")
                    return {
                        'status': 'INSUFFICIENT_DATA',
                        'message': f"Material '{constraints.material}' not found in MAPTIS, MUA precedents, or BOK. "
                                   f"This may be an unknown material or require different search terms.",
                        'recommendation': 'Testing required per NASA-STD-6001B before use',
                        'constraints': constraints.to_dict(),
                        'evidence': [],
                        'query': raw_query
                    }
        else:
            # No specific material - general query, allow semantic evidence
            pass

        has_evidence = bool(has_material_specific_evidence or has_semantic_evidence)

        if not has_evidence:
            print("[INSUFFICIENT DATA] No evidence found")
            return {
                'status': 'INSUFFICIENT_DATA',
                'message': 'No MUA precedents, test data, or semantic matches found for these constraints',
                'recommendation': 'Testing required per NASA-STD-6001B',
                'constraints': constraints.to_dict(),
                'evidence': [],
                'query': raw_query
            }

        # Step 5: Evaluate requirements
        print(f"[4/6] Evaluating requirements...")
        requirements = self.evaluate_requirements(constraints)
        print(f"      Found {len(requirements)} applicable requirements")

        # Step 6: Collect evidence and make decisions
        print(f"[5/6] Making decisions with MaterialDecider...")
        from .material_decider import MaterialDecider

        decider = MaterialDecider()
        decisions = []

        # Process test results as candidates (if any)
        for test_result in test_results:
            # Fetch evidence for this material
            material_id = test_result.get('material_id')
            evidence_rows = self.fetch_evidence_rows(material_id) if material_id else []

            # Find relevant MUA precedents for this material
            material_name = test_result['material_name']
            relevant_muas = [
                mua for mua in mua_precedents
                if mua['material_name'].lower() in material_name.lower() or
                   material_name.lower() in mua['material_name'].lower()
            ]

            # Make decision
            decision = decider.decide_material_suitability(
                candidate=test_result,
                constraints=constraints.to_dict(),
                mua_precedents=relevant_muas,
                test_evidence=evidence_rows,
                requirements=requirements
            )

            decisions.append(decision.to_dict())

        # CRITICAL: If no test results, use MUA precedents as candidates!
        # This ensures we make decisions even when test data is missing
        if not test_results and mua_precedents:
            print(f"      No test results - using {len(mua_precedents)} MUA precedent(s) as candidate(s)")
            for mua in mua_precedents:
                # Convert MUA precedent to candidate format
                pressure_psi = mua.get('pressure_psi_max')
                pressure_pa = float(pressure_psi) * 6894.76 if pressure_psi else None

                temp_c = mua.get('temp_c_max')
                temp_c = float(temp_c) if temp_c else None

                candidate = {
                    'material_id': mua.get('mua_id'),
                    'material_name': mua['material_name'],
                    'environment': 'oxygen',  # MUAs are oxygen-specific
                    'temp_max_tested_c': temp_c,
                    'pressure_max_tested_pa': pressure_pa,
                    'highest_rating': mua.get('determination'),
                    'test_count': 1,  # MUA represents at least 1 decision
                    'source': 'MUA_PRECEDENT'
                }

                # Make decision based on MUA precedent
                decision = decider.decide_material_suitability(
                    candidate=candidate,
                    constraints=constraints.to_dict(),
                    mua_precedents=[mua],  # Include self
                    test_evidence=[],  # MUAs don't have separate test evidence
                    requirements=requirements
                )

                decisions.append(decision.to_dict())

        print(f"[6/6] Generated {len(decisions)} material decision(s)")

        # Step 7: Generate natural language answer with LLM
        llm_answer = None
        try:
            print(f"[LLM] Generating natural language answer...")
            from .llm_answer_generator import LLMAnswerGenerator

            llm_generator = LLMAnswerGenerator(provider=self.llm_provider)
            llm_answer = llm_generator.generate_answer(
                query=raw_query,
                mua_precedents=mua_precedents[:5],  # Top 5 MUAs
                semantic_evidence=semantic_evidence,
                decisions=decisions,
                requirements=requirements
            )
            print(f"[LLM] Answer generated ({len(llm_answer)} chars)")

        except Exception as e:
            print(f"[LLM] Warning: Could not generate LLM answer: {e}")
            llm_answer = f"LLM answer generation unavailable: {str(e)}"

        # Return comprehensive results (SQL + Semantic evidence + LLM answer)
        result = {
            'status': 'SUCCESS',
            'query': raw_query,
            'constraints': constraints.to_dict(),
            'mua_precedents_found': len(mua_precedents),
            'mua_precedents': mua_precedents[:5],  # Top 5 for UI
            'test_results_found': len(test_results),
            'requirements_evaluated': len(requirements),
            'decisions': decisions,
            'material_decisions': decisions,  # Alias for test script compatibility
            'evidence_first_verified': True,  # Confirms we queried MUAs first!
            'semantic_evidence': semantic_evidence,  # Phase 3: Semantic enhancement
            'llm_answer': llm_answer  # Phase 3+: Natural language answer
        }

        return result

    def close(self):
        """Close database connection and semantic retriever."""
        if self.conn:
            self.conn.close()
        if self.semantic_retriever:
            self.semantic_retriever.close()


if __name__ == "__main__":
    # Example usage
    engine = EvidenceFirstQueryEngine()

    # Test query
    result = engine.query(
        "Stainless steel 316 for oxygen service at 3000 psi and 200 F"
    )

    import json
    print("\n" + "="*80)
    print("QUERY RESULT")
    print("="*80)
    print(json.dumps(result, indent=2, default=str))

    engine.close()
