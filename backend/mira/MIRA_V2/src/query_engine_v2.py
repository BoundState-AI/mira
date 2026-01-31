#!/usr/bin/env python3
"""
Module: Query Engine V2 (Railway Deployment)
Purpose: Evidence-First Query Engine - MIRA V2 (Simplified for Railway)

BoundState AI 2025
Version: 1.0.0 (Railway)

This is a simplified version for Railway deployment that:
- Works with PostgreSQL (required)
- Gracefully degrades without V6 FAISS retriever
- Gracefully degrades without semantic evidence
- Gracefully degrades without O2 engine
"""

from typing import List, Dict, Optional
from dataclasses import dataclass, asdict
from enum import Enum
import os

# PostgreSQL driver
try:
    import psycopg2
    import psycopg2.extras
    PSYCOPG2_AVAILABLE = True
except ImportError:
    PSYCOPG2_AVAILABLE = False
    psycopg2 = None

# V6 MUA Retriever - optional
V6_AVAILABLE = False
V6PrecedentRetriever = None

# Semantic evidence - optional
SEMANTIC_AVAILABLE = False


class EnvironmentClass(str, Enum):
    """Coarse environment classification for safety decisions."""
    OXYGEN = "oxygen"
    HYDROGEN = "hydrogen"
    AIR_VACUUM = "air_vacuum"
    OTHER = "other"


def classify_environment(env_str: Optional[str], phase: Optional[str] = None) -> EnvironmentClass:
    """Classify a free-text environment string into a coarse class."""
    if not env_str:
        return EnvironmentClass.OTHER

    env = env_str.lower()

    if "oxygen" in env or "gox" in env or "lox" in env or "o2" in env or "o₂" in env:
        return EnvironmentClass.OXYGEN

    if "hydrogen" in env or "gh2" in env or "lh2" in env or "h2" in env or "h₂" in env:
        return EnvironmentClass.HYDROGEN

    if "air" in env or "vacuum" in env:
        return EnvironmentClass.AIR_VACUUM

    return EnvironmentClass.OTHER


def infer_test_types(rationale: Optional[str]) -> set:
    """Infer test types from MUA rationale text."""
    if not rationale:
        return set()

    text = rationale.lower()
    test_types = set()

    if any(kw in text for kw in ["flammability", "flammable", "ignition", "combustion"]):
        test_types.add("flammability")

    if any(kw in text for kw in ["mechanical impact", "impact test"]):
        test_types.add("mechanical_impact")

    if any(kw in text for kw in ["particle impact", "promoted ignition"]):
        test_types.add("particle_impact")

    if any(kw in text for kw in ["corrosion", "corrode", "scc"]):
        test_types.add("corrosion")

    if any(kw in text for kw in ["toxicity", "toxic", "outgas"]):
        test_types.add("toxicity")

    return test_types


def extract_hazards_from_mitigations(mitigations: Optional[list]) -> set:
    """Extract hazard tags from MUA mitigations JSONB field."""
    if not mitigations:
        return set()

    hazards = set()
    for mitigation in mitigations:
        if isinstance(mitigation, dict) and mitigation.get("hazard"):
            hazards.add(mitigation["hazard"].upper())

    return hazards


def is_relevant_for_oxygen_query(test_types: set, env_class: EnvironmentClass, hazards: Optional[set] = None) -> bool:
    """Determine if MUA is relevant for oxygen compatibility query."""
    if env_class == EnvironmentClass.OXYGEN:
        return True

    if hazards:
        o2_relevant_hazards = {"FLAMM", "O2_COMPAT", "MECH_IMPACT"}
        if hazards & o2_relevant_hazards:
            return True
        non_o2_hazards = {"CORR", "SCC", "TOX", "OUTGAS"}
        if hazards and hazards.issubset(non_o2_hazards):
            return False

    o2_relevant_tests = {"flammability", "mechanical_impact", "particle_impact"}
    if test_types & o2_relevant_tests:
        return True

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

    Railway deployment version - works with PostgreSQL only.
    Semantic search and V6 retriever are optional enhancements.
    """

    def __init__(self, db_url: Optional[str] = None, enable_semantic: bool = False, llm_provider: str = "haiku"):
        """
        Initialize evidence-first query engine.

        Args:
            db_url: Database connection URL (uses DATABASE_URL env var if not provided)
            enable_semantic: Enable semantic search (disabled by default on Railway)
            llm_provider: LLM provider - "haiku" (default) or "ollama"
        """
        if not PSYCOPG2_AVAILABLE:
            raise ImportError("psycopg2-binary is required. Install with: pip install psycopg2-binary")

        self.llm_provider = llm_provider
        self.db_url = db_url or os.environ.get('DATABASE_URL') or os.environ.get('MIRA_DB_URL')

        if not self.db_url:
            # Try building from individual env vars
            self.db_url = self._build_db_url()

        if not self.db_url:
            raise ValueError("DATABASE_URL not configured. Set DATABASE_URL environment variable.")

        self.conn = psycopg2.connect(self.db_url)
        psycopg2.extras.register_uuid()
        print(f"[QueryEngine] Connected to PostgreSQL")

        # Semantic search disabled on Railway (no FAISS indexes)
        self.enable_semantic = False
        self.semantic_retriever = None

        # V6 retriever disabled on Railway
        self.v6_retriever = None

    def _build_db_url(self) -> Optional[str]:
        """Build database URL from environment or defaults."""
        host = os.getenv('POSTGRES_HOST')
        if not host:
            return None

        port = os.getenv('POSTGRES_PORT', '5432')
        db = os.getenv('POSTGRES_DB', 'mira')
        user = os.getenv('POSTGRES_USER', 'postgres')
        password = os.getenv('POSTGRES_PASSWORD', '')

        return f"postgresql://{user}:{password}@{host}:{port}/{db}"

    def query_mua_precedents(self, constraints: MaterialConstraints) -> List[Dict]:
        """
        STEP 1: Query MUA precedents FIRST (CRITICAL!)

        Queries the bok.mua_precedents table for historic NASA decisions.
        """
        requested_env = (constraints.environment or "").lower()
        requested_env_class: Optional[EnvironmentClass] = None

        if "oxygen" in requested_env or "gox" in requested_env or "lox" in requested_env or "o2" in requested_env:
            requested_env_class = EnvironmentClass.OXYGEN
        elif "hydrogen" in requested_env or "h2" in requested_env:
            requested_env_class = EnvironmentClass.HYDROGEN

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

        if constraints.temp_c_max:
            query += " AND temp_c_max >= %s"
            params.append(constraints.temp_c_max)

        # Prioritize APPROVED and CONDITIONAL
        query += " AND determination IN ('APPROVED', 'CONDITIONAL')"
        query += " ORDER BY is_reviewed DESC, parser_confidence DESC, parsed_date DESC LIMIT 10"

        try:
            cur.execute(query, params)
            rows = cur.fetchall()
        except Exception as e:
            print(f"[WARNING] MUA query failed: {e}")
            self.conn.rollback()
            cur.close()
            return []

        cur.close()

        # Process results
        results = []
        for row in rows:
            row_dict = dict(row)

            rationale_text = (row_dict.get("rationale") or "") + " " + (row_dict.get("material_specification") or "")
            env_class = classify_environment(rationale_text)
            hazards = extract_hazards_from_mitigations(row_dict.get("mitigations"))
            test_types = infer_test_types(row_dict.get("rationale"))

            if requested_env_class == EnvironmentClass.OXYGEN:
                if not is_relevant_for_oxygen_query(test_types, env_class, hazards):
                    continue

            is_primary = (env_class == requested_env_class) if requested_env_class else False

            row_dict["env_class"] = env_class.value
            row_dict["is_primary_for_env"] = is_primary
            row_dict["inferred_environment"] = env_class.value
            row_dict["test_types"] = list(test_types)
            row_dict["hazards"] = list(hazards)

            results.append(row_dict)

        return results

    def query_test_data(self, constraints: MaterialConstraints) -> List[Dict]:
        """STEP 2: Query test data SECOND."""
        cur = self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        try:
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

            if constraints.environment:
                query += " AND tr.environment = %s"
                params.append(constraints.environment)

            if constraints.pressure_psi_max:
                query += " AND tr.pressure_max_pa >= %s"
                params.append(constraints.pressure_psi_max * 6894.76)

            query += " ORDER BY tr.test_date DESC LIMIT 20"

            cur.execute(query, params)
            results = cur.fetchall()
            cur.close()

            return [dict(row) for row in results]

        except Exception as e:
            print(f"[WARNING] Test data query failed: {e}")
            self.conn.rollback()
            cur.close()
            return []

    def evaluate_requirements(self, constraints: MaterialConstraints) -> List[Dict]:
        """Query bok.requirements and evaluate against constraints."""
        cur = self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        try:
            cur.execute("""
                SELECT
                    r.req_id, r.section_id, r.action, r.description, r.predicate,
                    s.spec_id, s.section_number, s.heading
                FROM bok.requirements r
                JOIN bok.sections s ON r.section_id = s.section_id
                WHERE s.is_normative = true
                ORDER BY s.spec_id, s.section_number
                LIMIT 100
            """)

            results = cur.fetchall()
            cur.close()
            return [dict(row) for row in results]

        except Exception as e:
            print(f"[WARNING] Requirements query failed: {e}")
            self.conn.rollback()
            cur.close()
            return []

    def query(self, raw_query: str, parsed_constraints: Optional[MaterialConstraints] = None) -> Dict:
        """
        Main query method - EVIDENCE-FIRST IMPLEMENTATION.
        """
        from .constraint_interpreter import ConstraintInterpreter

        # Step 1: Parse query
        if parsed_constraints is None:
            interpreter = ConstraintInterpreter()
            constraints = interpreter.parse_query(raw_query)
        else:
            constraints = parsed_constraints

        # Step 2: Query MUA precedents FIRST
        print(f"[1/5] Querying MUA precedents for: {constraints.material or 'any material'}")
        mua_precedents = self.query_mua_precedents(constraints)
        print(f"      Found {len(mua_precedents)} MUA precedents")

        # Step 3: Query test data
        print(f"[2/5] Querying test data...")
        test_results = self.query_test_data(constraints)
        print(f"      Found {len(test_results)} test results")

        # Step 4: Check for insufficient data
        has_evidence = bool(mua_precedents or test_results)

        if not has_evidence:
            print("[INSUFFICIENT DATA] No evidence found")
            return {
                'status': 'INSUFFICIENT_DATA',
                'message': 'No MUA precedents or test data found for these constraints',
                'recommendation': 'Testing required per NASA-STD-6001B',
                'constraints': constraints.to_dict(),
                'evidence': [],
                'query': raw_query,
                'mua_precedents_found': 0,
                'test_results_found': 0,
                'requirements_evaluated': 0,
            }

        # Step 5: Evaluate requirements
        print(f"[3/5] Evaluating requirements...")
        requirements = self.evaluate_requirements(constraints)
        print(f"      Found {len(requirements)} applicable requirements")

        # Step 6: Make decisions
        print(f"[4/5] Making decisions...")
        from .material_decider import MaterialDecider

        decider = MaterialDecider()
        decisions = []

        # Process MUA precedents as candidates
        for mua in mua_precedents[:5]:
            pressure_psi = mua.get('pressure_psi_max')
            pressure_pa = float(pressure_psi) * 6894.76 if pressure_psi else None
            temp_c = float(mua.get('temp_c_max')) if mua.get('temp_c_max') else None

            candidate = {
                'material_id': mua.get('mua_number'),
                'material_name': mua['material_name'],
                'environment': mua.get('env_class', 'unknown'),
                'temp_max_tested_c': temp_c,
                'pressure_max_tested_pa': pressure_pa,
                'highest_rating': mua.get('determination'),
                'source': 'MUA_PRECEDENT'
            }

            decision = decider.decide_material_suitability(
                candidate=candidate,
                constraints=constraints.to_dict(),
                mua_precedents=[mua],
                test_evidence=[],
                requirements=requirements
            )

            decisions.append(decision.to_dict())

        print(f"[5/5] Generated {len(decisions)} decision(s)")

        # Step 7: Generate LLM answer
        llm_answer = None
        try:
            print(f"[LLM] Generating answer with {self.llm_provider}...")
            from .llm_answer_generator import LLMAnswerGenerator

            llm_generator = LLMAnswerGenerator(provider=self.llm_provider)
            llm_answer = llm_generator.generate_answer(
                query=raw_query,
                mua_precedents=mua_precedents[:5],
                semantic_evidence=None,
                decisions=decisions,
                requirements=requirements
            )
            print(f"[LLM] Answer generated ({len(llm_answer)} chars)")

        except Exception as e:
            print(f"[LLM] Warning: Could not generate LLM answer: {e}")
            import traceback
            traceback.print_exc()
            llm_answer = f"LLM answer generation unavailable: {str(e)}"

        # Return results
        return {
            'status': 'SUCCESS',
            'query': raw_query,
            'constraints': constraints.to_dict(),
            'mua_precedents_found': len(mua_precedents),
            'mua_precedents': mua_precedents[:5],
            'test_results_found': len(test_results),
            'requirements_evaluated': len(requirements),
            'decisions': decisions,
            'evidence_first_verified': True,
            'semantic_evidence': None,
            'llm_answer': llm_answer
        }

    def close(self):
        """Close database connection."""
        if self.conn:
            self.conn.close()


if __name__ == "__main__":
    # Example usage
    engine = EvidenceFirstQueryEngine()
    result = engine.query("Stainless steel 316 for oxygen service at 3000 psi")

    import json
    print(json.dumps(result, indent=2, default=str))

    engine.close()
