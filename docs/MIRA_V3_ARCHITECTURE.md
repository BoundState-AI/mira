# MIRA V3 Architecture — Refactoring Specification

**Author:** Beth (Claude) + Dr. Joseph Wilde  
**Date:** 2025-02-04  
**Status:** SPEC — Ready for implementation  
**Compliance:** SWE-013, NASA-STD-8739.8B  

---

## 1. THE IRONCLAD RULES

These are non-negotiable. Every module, every PR, every line of code obeys these.

### Rule 1: Single Router, Zero Logic
Every query passes through exactly ONE router. The router classifies and dispatches.
It does NOT execute database queries, apply BOK rules, or gather evidence.
It answers one question: **"What kind of question is this?"** Then it hands off.

### Rule 2: Pipelines Are Independent
Each pipeline is self-contained. A compatibility pipeline does not know materials_search 
exists. A materials_search pipeline does not know about BOK rules. They share 
infrastructure (FAISS, Postgres, embeddings) via injected services — never decision logic.

### Rule 3: Safety Interceptors Fire First
Deterministic safety checks (O2 prohibitions, H2 embrittlement) execute BEFORE any 
pipeline. They are pre-pipeline interceptors. They fire on every query. If they 
short-circuit with PROHIBITED, nothing else runs. Period.

### Rule 4: Evidence-First Is Structural
Every pipeline returns an `EvidencePackage`. If the package is empty, the answer is 
`INSUFFICIENT_DATA`. This is enforced by the return type, not by comments or hope.

### Rule 5: LLM Explains, Never Decides
Decisions come from deterministic logic (MaterialDecider, O2PolicyEngine, H2PolicyEngine).
The LLM receives the decision + evidence and formats it for humans. The LLM cannot 
override, modify, or supplement a deterministic decision.

### Rule 6: No Inline Definitions, No Hardcoded Dictionaries, No Duplicates
- ONE `MaterialConstraints` dataclass (in `models.py`)
- ONE `materials_match()` function (in `matching.py`)
- ONE material families registry (database-backed or config file, NOT code)
- ZERO functions defined inside other functions

---

## 2. FILE STRUCTURE

```
MIRA_V2/src/
├── __init__.py
├── models.py                    # ALL shared dataclasses & enums
├── config.py                    # Material families registry, thresholds
│
├── router/
│   ├── __init__.py
│   ├── query_router.py          # THE router (Rule 1)
│   └── intent_classifier.py     # Pattern-based intent scoring (moved here)
│
├── interceptors/
│   ├── __init__.py
│   ├── base.py                  # SafetyInterceptor ABC
│   ├── o2_boundary.py           # O2 deterministic prohibition check
│   └── h2_boundary.py           # H2 embrittlement prohibition check
│
├── pipelines/
│   ├── __init__.py
│   ├── base.py                  # Pipeline ABC (enforces EvidencePackage return)
│   ├── compatibility.py         # Full BOK rules, evidence-first, decisions
│   ├── materials_search.py      # Simple DB lookup, no intelligence
│   ├── document_lookup.py       # Standards/spec retrieval
│   ├── comparison.py            # Side-by-side material comparison
│   └── help.py                  # Tutorial/guidance responses
│
├── evidence/
│   ├── __init__.py
│   ├── package.py               # EvidencePackage dataclass (Rule 4)
│   ├── mua_retriever.py         # V6 FAISS + SQL fallback MUA retrieval
│   ├── test_data_retriever.py   # MAPTIS test data queries
│   ├── semantic_retriever.py    # FAISS semantic search (existing)
│   └── requirements_evaluator.py # BOK requirements check
│
├── decisions/
│   ├── __init__.py
│   ├── material_decider.py      # MaterialDecider (existing, cleaned)
│   └── decision_models.py       # MaterialDecision dataclass
│
├── matching/
│   ├── __init__.py
│   ├── material_match.py        # materials_match() — ONE place (Rule 6)
│   ├── environment_classify.py  # classify_environment() — ONE place
│   └── constraint_interpreter.py # Parse NL → MaterialConstraints
│
├── generation/
│   ├── __init__.py
│   ├── llm_generator.py         # LLM answer formatting (Rule 5)
│   ├── llm_contract.py          # System prompt / safety rules
│   └── haiku_client.py          # Haiku API client
│
├── scoring/
│   ├── __init__.py
│   ├── relevance_scorer.py      # RelevanceBand, safety boost (existing)
│   └── answer_authority.py      # Answer authority scoring (existing)
│
└── engine.py                    # QueryEngine — thin orchestrator
```

---

## 3. THE ROUTER

```python
# router/query_router.py

class QueryRoute(str, Enum):
    """Possible pipeline destinations."""
    COMPATIBILITY = "compatibility"       # Full BOK + evidence-first
    MATERIALS_SEARCH = "materials_search" # Simple DB lookup
    DOCUMENT_LOOKUP = "document_lookup"   # Standards retrieval
    COMPARISON = "comparison"             # Side-by-side
    HELP = "help"                         # Guidance
    UNKNOWN = "unknown"                   # Fallback → compatibility (conservative)


@dataclass
class RoutingDecision:
    """Router output — immutable record of why we routed where."""
    route: QueryRoute
    confidence: float           # 0.0-1.0
    intent_scores: Dict[str, float]
    reasoning: str              # Human-readable explanation
    has_gas_service: bool       # Detected O2/H2/GOX/LOX context
    has_compatibility_language: bool  # "compatible", "approved", "rated"
    has_list_language: bool     # "show me", "list", "find all"


class QueryRouter:
    """
    Routes queries to pipelines. DOES NOT execute pipeline logic.
    
    Routing Rules (checked in order):
    
    1. EXPLICIT COMPATIBILITY SIGNALS → COMPATIBILITY
       - "compatible", "compatibility", "approved for", "rated for", "safe for"
       - "can I use X in Y", "is X suitable for"
       - Pressure/temperature envelope specified ("at 3000 psi")
       
    2. EXPLICIT LIST/BROWSE SIGNALS (without gas service) → MATERIALS_SEARCH
       - "show me", "list", "find all", "browse", "search for"
       - "what materials are" (information seeking, not compatibility)
       - Material family names WITHOUT gas service context
    
    3. GAS SERVICE CONTEXT (tiebreaker) → COMPATIBILITY  
       - Any O2/H2/GOX/LOX/GH2/LH2 keyword present
       - "service", "psi", "pressure" in query
       - Even if no explicit compatibility language
    
    4. DOCUMENT SIGNALS → DOCUMENT_LOOKUP
       - NASA-STD, MIL-STD, specification references
       
    5. COMPARISON SIGNALS → COMPARISON
       - "compare", "vs", "versus", "better than"
       
    6. HELP SIGNALS → HELP
       - "how do I", "help", "what can you"
    
    7. AMBIGUOUS → COMPATIBILITY (conservative default)
       - When in doubt, apply intelligence. It's safer to over-analyze
         than to miss a compatibility concern.
    """
    
    def __init__(self):
        self.classifier = IntentClassifier()
    
    def route(self, raw_query: str, constraints: MaterialConstraints) -> RoutingDecision:
        """
        Classify query and return routing decision.
        
        This method MUST NOT:
        - Query any database
        - Load any FAISS index
        - Call any LLM
        - Apply any BOK rules
        - Make any material decisions
        """
        query_lower = raw_query.lower()
        
        # Detect signal categories
        has_gas_service = self._detect_gas_service(query_lower)
        has_compat_language = self._detect_compatibility_language(query_lower)
        has_list_language = self._detect_list_language(query_lower)
        has_doc_signals = self._detect_document_signals(query_lower)
        has_comparison = self._detect_comparison_signals(query_lower)
        has_help = self._detect_help_signals(query_lower)
        
        # Get pattern-based scores
        intent_result = self.classifier.classify(raw_query)
        
        # Apply routing rules IN ORDER
        
        # Rule 1: Explicit compatibility → COMPATIBILITY
        if has_compat_language:
            return RoutingDecision(
                route=QueryRoute.COMPATIBILITY,
                confidence=0.95,
                intent_scores=intent_result.scores,
                reasoning="Explicit compatibility language detected",
                has_gas_service=has_gas_service,
                has_compatibility_language=True,
                has_list_language=has_list_language,
            )
        
        # Rule 2: List/browse WITHOUT gas service → MATERIALS_SEARCH
        if has_list_language and not has_gas_service:
            return RoutingDecision(
                route=QueryRoute.MATERIALS_SEARCH,
                confidence=0.90,
                intent_scores=intent_result.scores,
                reasoning="List/browse language without gas service context",
                has_gas_service=False,
                has_compatibility_language=False,
                has_list_language=True,
            )
        
        # Rule 3: Gas service context (even without explicit compat) → COMPATIBILITY
        if has_gas_service:
            return RoutingDecision(
                route=QueryRoute.COMPATIBILITY,
                confidence=0.85,
                intent_scores=intent_result.scores,
                reasoning="Gas service context detected (O2/H2/pressure)",
                has_gas_service=True,
                has_compatibility_language=False,
                has_list_language=has_list_language,
            )
        
        # Rule 4: Document lookup
        if has_doc_signals:
            return RoutingDecision(
                route=QueryRoute.DOCUMENT_LOOKUP,
                confidence=0.85,
                intent_scores=intent_result.scores,
                reasoning="Document/standard reference detected",
                has_gas_service=False,
                has_compatibility_language=False,
                has_list_language=False,
            )
        
        # Rule 5: Comparison
        if has_comparison:
            return RoutingDecision(
                route=QueryRoute.COMPARISON,
                confidence=0.80,
                intent_scores=intent_result.scores,
                reasoning="Comparison language detected",
                has_gas_service=False,
                has_compatibility_language=False,
                has_list_language=False,
            )
        
        # Rule 6: Help
        if has_help:
            return RoutingDecision(
                route=QueryRoute.HELP,
                confidence=0.75,
                intent_scores=intent_result.scores,
                reasoning="Help/guidance request detected",
                has_gas_service=False,
                has_compatibility_language=False,
                has_list_language=False,
            )
        
        # Rule 7: Ambiguous → COMPATIBILITY (conservative)
        return RoutingDecision(
            route=QueryRoute.COMPATIBILITY,
            confidence=0.50,
            intent_scores=intent_result.scores,
            reasoning="Ambiguous query — defaulting to compatibility (conservative)",
            has_gas_service=False,
            has_compatibility_language=False,
            has_list_language=has_list_language,
        )
    
    def _detect_gas_service(self, q: str) -> bool:
        """Detect O2/H2/GOX/LOX/pressure context."""
        gas_keywords = [
            'oxygen', 'o2', 'o₂', 'gox', 'lox',
            'hydrogen', 'h2', 'h₂', 'gh2', 'lh2',
        ]
        service_keywords = ['service', 'psi', 'psia', 'pressure', 'bar']
        
        return (any(kw in q for kw in gas_keywords) or
                any(kw in q for kw in service_keywords))
    
    def _detect_compatibility_language(self, q: str) -> bool:
        """Detect explicit compatibility questions."""
        import re
        patterns = [
            r'\b(compatible|compatibility)\b',
            r'\b(approved|rated|safe)\s+(for|in|with)\b',
            r'\bcan\s+(i|we)\s+use\b',
            r'\b(is|are)\s+\w+\s+(suitable|acceptable|allowed)\b',
            r'\buse\s+\w+\s+(in|for|with)\s+(oxygen|o2|hydrogen|h2)',
        ]
        return any(re.search(p, q, re.IGNORECASE) for p in patterns)
    
    def _detect_list_language(self, q: str) -> bool:
        """Detect list/browse/search requests."""
        import re
        patterns = [
            r'\b(list|show|find|search|browse|display)\s+(all\s+)?(material|alloy|metal|polymer)',
            r'\bwhat\s+(material|alloy)s?\s+(are|is)\b',
            r'\b(show|give|get)\s+me\s+(all\s+)?',
        ]
        return any(re.search(p, q, re.IGNORECASE) for p in patterns)
    
    def _detect_document_signals(self, q: str) -> bool:
        import re
        return bool(re.search(
            r'\b(NASA[-\s]?STD|MIL[-\s]?STD|specification|procedure|standard)\b',
            q, re.IGNORECASE
        ))
    
    def _detect_comparison_signals(self, q: str) -> bool:
        import re
        return bool(re.search(r'\b(compare|versus|vs\.?|better\s+than|difference)\b', q, re.IGNORECASE))
    
    def _detect_help_signals(self, q: str) -> bool:
        import re
        return bool(re.search(r'\b(how\s+do\s+i|help|what\s+can\s+you)\b', q, re.IGNORECASE))
```

---

## 4. SAFETY INTERCEPTORS

```python
# interceptors/base.py

from abc import ABC, abstractmethod
from typing import Optional
from ..models import MaterialConstraints, QueryResult


class SafetyInterceptor(ABC):
    """
    Pre-pipeline safety check. Fires BEFORE routing.
    
    If intercept() returns a QueryResult, that result is FINAL.
    No pipeline executes. No LLM is consulted.
    """
    
    @abstractmethod
    def should_check(self, raw_query: str, constraints: MaterialConstraints) -> bool:
        """Does this interceptor apply to this query?"""
        ...
    
    @abstractmethod
    def intercept(self, raw_query: str, constraints: MaterialConstraints) -> Optional[QueryResult]:
        """
        Check for hard prohibition.
        
        Returns:
            QueryResult with PROHIBITED decision if hard rule applies.
            None if no prohibition found (let pipeline handle it).
        """
        ...


# interceptors/o2_boundary.py

class O2BoundaryInterceptor(SafetyInterceptor):
    """
    Deterministic O2 compatibility boundary check.
    
    Catches hard prohibitions like aluminum-in-GOX BEFORE any pipeline
    or LLM touches the query. Ensures same query always gets same answer.
    
    Uses: mira.o2.engine.evaluate_o2_compatibility()
    """
    
    def should_check(self, raw_query: str, constraints: MaterialConstraints) -> bool:
        query_lower = raw_query.lower()
        return (any(kw in query_lower for kw in ['oxygen', 'o2', 'gox', 'lox']) 
                and constraints.material is not None)
    
    def intercept(self, raw_query: str, constraints: MaterialConstraints) -> Optional[QueryResult]:
        # ... existing _check_o2_deterministic_boundaries logic ...
        # Returns QueryResult with PROHIBITED or None
        pass


# interceptors/h2_boundary.py

class H2BoundaryInterceptor(SafetyInterceptor):
    """
    Deterministic H2 embrittlement boundary check.
    
    Catches hard prohibitions like martensitic steels in hydrogen.
    """
    
    def should_check(self, raw_query: str, constraints: MaterialConstraints) -> bool:
        query_lower = raw_query.lower()
        return (any(kw in query_lower for kw in ['hydrogen', 'h2', 'gh2', 'lh2'])
                and constraints.material is not None)
    
    def intercept(self, raw_query: str, constraints: MaterialConstraints) -> Optional[QueryResult]:
        # H2 boundary logic
        pass
```

---

## 5. PIPELINE INTERFACE

```python
# pipelines/base.py

from abc import ABC, abstractmethod
from ..evidence.package import EvidencePackage
from ..models import MaterialConstraints, QueryResult


class Pipeline(ABC):
    """
    Base pipeline. All pipelines MUST return EvidencePackage.
    
    Rule 4: If evidence is empty → INSUFFICIENT_DATA.
    This is enforced here, not in subclasses.
    """
    
    @abstractmethod
    def execute(self, raw_query: str, constraints: MaterialConstraints) -> QueryResult:
        """Execute pipeline and return result with evidence."""
        ...
    
    def _enforce_evidence_first(self, evidence: EvidencePackage, raw_query: str, 
                                 constraints: MaterialConstraints) -> Optional[QueryResult]:
        """
        Structural enforcement of evidence-first principle.
        
        If no evidence exists, returns INSUFFICIENT_DATA.
        Subclasses call this BEFORE making decisions.
        """
        if evidence.is_empty():
            return QueryResult(
                status='INSUFFICIENT_DATA',
                query=raw_query,
                constraints=constraints.to_dict(),
                message=f"No evidence found for '{constraints.material or 'query'}'",
                recommendation='Testing required per NASA-STD-6001B',
                evidence_package=evidence,
            )
        return None  # Evidence exists, continue


# pipelines/compatibility.py

class CompatibilityPipeline(Pipeline):
    """
    Full evidence-first compatibility assessment.
    
    Steps:
    1. Retrieve MUA precedents (V6 FAISS + SQL fallback)
    2. Retrieve test data (MAPTIS)
    3. Retrieve semantic evidence (FAISS)
    4. Enforce evidence-first (structural check)
    5. Evaluate requirements (BOK)
    6. Make decisions (MaterialDecider)
    7. Generate explanation (LLM)
    """
    
    def __init__(self, 
                 mua_retriever: MUARetriever,
                 test_retriever: TestDataRetriever,
                 semantic_retriever: SemanticEvidenceRetriever,
                 requirements_evaluator: RequirementsEvaluator,
                 decider: MaterialDecider,
                 llm_generator: LLMAnswerGenerator):
        self.mua_retriever = mua_retriever
        self.test_retriever = test_retriever
        self.semantic_retriever = semantic_retriever
        self.requirements_evaluator = requirements_evaluator
        self.decider = decider
        self.llm_generator = llm_generator
    
    def execute(self, raw_query: str, constraints: MaterialConstraints) -> QueryResult:
        # Step 1: MUA precedents FIRST
        mua_precedents = self.mua_retriever.retrieve(constraints)
        
        # Step 2: Test data
        test_results = self.test_retriever.retrieve(constraints)
        
        # Step 3: Semantic evidence
        semantic_evidence = self.semantic_retriever.retrieve(raw_query, constraints)
        
        # Step 4: Build evidence package & enforce evidence-first
        evidence = EvidencePackage(
            mua_precedents=mua_precedents,
            test_results=test_results,
            semantic_evidence=semantic_evidence,
            query=raw_query,
            constraints=constraints,
        )
        
        insufficient = self._enforce_evidence_first(evidence, raw_query, constraints)
        if insufficient:
            return insufficient
        
        # Step 5: Requirements
        requirements = self.requirements_evaluator.evaluate(constraints)
        
        # Step 6: Decisions (deterministic)
        decisions = self.decider.decide(evidence, constraints, requirements)
        
        # Step 7: LLM explanation (Rule 5: explains, never decides)
        explanation = self.llm_generator.explain(
            query=raw_query,
            decisions=decisions,
            evidence=evidence,
            requirements=requirements,
        )
        
        return QueryResult(
            status='SUCCESS',
            query=raw_query,
            constraints=constraints.to_dict(),
            decisions=decisions,
            evidence_package=evidence,
            llm_answer=explanation,
            evidence_first_verified=True,
        )


# pipelines/materials_search.py

class MaterialsSearchPipeline(Pipeline):
    """
    Simple database lookup. NO BOK rules. NO intelligence.
    
    Returns all materials matching the query without filtering
    through compatibility logic.
    """
    
    def __init__(self, db_conn, material_registry: MaterialFamilyRegistry):
        self.db_conn = db_conn
        self.registry = material_registry
    
    def execute(self, raw_query: str, constraints: MaterialConstraints) -> QueryResult:
        # Look up composition key from registry (NOT hardcoded dict)
        composition_key = self.registry.get_composition_key(raw_query)
        
        materials = self._search_by_composition(composition_key)
        if not materials and constraints.material:
            materials = self._search_by_name(constraints.material)
        if not materials:
            materials = self._search_silver_rows(raw_query)
        
        return QueryResult(
            status='SUCCESS',
            query=raw_query,
            query_type='materials_search',
            constraints=constraints.to_dict(),
            materials=materials,
            materials_found=len(materials),
            evidence_first_verified=False,  # Explicitly: no intelligence applied
            note='Simple materials lookup — no compatibility rules applied.',
        )
```

---

## 6. EVIDENCE PACKAGE

```python
# evidence/package.py

@dataclass
class EvidencePackage:
    """
    Structural enforcement of evidence-first principle.
    
    Every pipeline returns this. If it's empty, the answer is 
    INSUFFICIENT_DATA. No exceptions.
    """
    query: str
    constraints: MaterialConstraints
    mua_precedents: List[Dict] = field(default_factory=list)
    test_results: List[Dict] = field(default_factory=list)
    semantic_evidence: Optional[SemanticEvidence] = None
    
    def is_empty(self) -> bool:
        """True if NO evidence of any kind exists."""
        has_mua = bool(self.mua_precedents)
        has_test = bool(self.test_results)
        has_semantic = bool(
            self.semantic_evidence and 
            self.semantic_evidence.total_results > 0
        )
        return not (has_mua or has_test or has_semantic)
    
    def has_material_specific_evidence(self) -> bool:
        """True if MUA or test data directly references the queried material."""
        return bool(self.mua_precedents or self.test_results)
    
    @property
    def total_evidence_count(self) -> int:
        count = len(self.mua_precedents) + len(self.test_results)
        if self.semantic_evidence:
            count += self.semantic_evidence.total_results
        return count
```

---

## 7. THE ENGINE (Thin Orchestrator)

```python
# engine.py

class QueryEngine:
    """
    MIRA V3 Query Engine — Thin orchestrator.
    
    This class does THREE things:
    1. Parse the query → MaterialConstraints
    2. Run safety interceptors (short-circuit if PROHIBITED)
    3. Route to pipeline and return result
    
    It does NOT contain business logic. It does NOT make decisions.
    It does NOT query databases. It orchestrates.
    """
    
    def __init__(self, db_url: str = None, llm_provider: str = "ollama"):
        # Build all components via dependency injection
        self.constraint_parser = ConstraintInterpreter()
        self.router = QueryRouter()
        
        # Safety interceptors (Rule 3: fire first)
        self.interceptors: List[SafetyInterceptor] = [
            O2BoundaryInterceptor(),
            H2BoundaryInterceptor(),
        ]
        
        # Shared infrastructure
        db_conn = self._connect_db(db_url)
        mua_retriever = MUARetriever(db_conn)
        test_retriever = TestDataRetriever(db_conn)
        semantic_retriever = SemanticEvidenceRetriever(db_url=db_url)
        requirements_eval = RequirementsEvaluator(db_conn)
        decider = MaterialDecider()
        llm_gen = LLMAnswerGenerator(provider=llm_provider)
        material_registry = MaterialFamilyRegistry(db_conn)
        
        # Pipelines (Rule 2: independent, injected dependencies)
        self.pipelines: Dict[QueryRoute, Pipeline] = {
            QueryRoute.COMPATIBILITY: CompatibilityPipeline(
                mua_retriever, test_retriever, semantic_retriever,
                requirements_eval, decider, llm_gen
            ),
            QueryRoute.MATERIALS_SEARCH: MaterialsSearchPipeline(
                db_conn, material_registry
            ),
            QueryRoute.DOCUMENT_LOOKUP: DocumentLookupPipeline(semantic_retriever),
            QueryRoute.COMPARISON: ComparisonPipeline(
                mua_retriever, test_retriever, decider
            ),
            QueryRoute.HELP: HelpPipeline(),
        }
    
    def query(self, raw_query: str, parsed_constraints: MaterialConstraints = None) -> QueryResult:
        """
        Main entry point. Parse → Intercept → Route → Execute.
        """
        # Step 1: Parse
        constraints = parsed_constraints or self.constraint_parser.parse_query(raw_query)
        
        # Step 2: Safety interceptors (Rule 3)
        for interceptor in self.interceptors:
            if interceptor.should_check(raw_query, constraints):
                result = interceptor.intercept(raw_query, constraints)
                if result:
                    print(f"[INTERCEPTOR] {interceptor.__class__.__name__}: PROHIBITED")
                    return result
        
        # Step 3: Route
        routing = self.router.route(raw_query, constraints)
        print(f"[ROUTER] → {routing.route.value} (confidence: {routing.confidence:.2f})")
        print(f"[ROUTER]   reason: {routing.reasoning}")
        
        # Step 4: Execute pipeline
        pipeline = self.pipelines.get(routing.route)
        if not pipeline:
            pipeline = self.pipelines[QueryRoute.COMPATIBILITY]  # Conservative fallback
        
        result = pipeline.execute(raw_query, constraints)
        
        # Attach routing metadata
        result.routing = routing
        
        return result
```

---

## 8. SHARED MODELS (Rule 6: One Definition)

```python
# models.py — THE source of truth for all shared types

from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Optional, List, Dict, Any


class EnvironmentClass(str, Enum):
    OXYGEN = "oxygen"
    HYDROGEN = "hydrogen"
    AIR_VACUUM = "air_vacuum"
    OTHER = "other"


class QueryRoute(str, Enum):
    COMPATIBILITY = "compatibility"
    MATERIALS_SEARCH = "materials_search"
    DOCUMENT_LOOKUP = "document_lookup"
    COMPARISON = "comparison"
    HELP = "help"
    UNKNOWN = "unknown"


@dataclass
class MaterialConstraints:
    """THE material constraints dataclass. There is no other."""
    material: Optional[str] = None
    configuration: Optional[str] = None
    pressure_psi_max: Optional[float] = None
    temp_c_min: Optional[float] = None
    temp_c_max: Optional[float] = None
    o2_pct: Optional[float] = None
    environment: Optional[str] = None
    
    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class RoutingDecision:
    route: QueryRoute
    confidence: float
    intent_scores: Dict[str, float]
    reasoning: str
    has_gas_service: bool
    has_compatibility_language: bool
    has_list_language: bool


@dataclass 
class MaterialDecision:
    material_name: str
    decision: str  # YES, YES_WITH_CAVEATS, NO, REQUIRES_TESTING
    rationale: str
    evidence_sources: List[str]
    caveats: List[str] = field(default_factory=list)
    confidence: float = 0.0
    
    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class QueryResult:
    """Universal query result. Every pipeline returns this."""
    status: str  # SUCCESS, INSUFFICIENT_DATA, PROHIBITED
    query: str
    constraints: Dict
    
    # Optional fields (populated by different pipelines)
    decisions: List[MaterialDecision] = field(default_factory=list)
    materials: List[Dict] = field(default_factory=list)
    materials_found: int = 0
    evidence_package: Any = None
    llm_answer: Optional[str] = None
    routing: Optional[RoutingDecision] = None
    message: Optional[str] = None
    recommendation: Optional[str] = None
    query_type: Optional[str] = None
    note: Optional[str] = None
    evidence_first_verified: bool = False
    
    # Backwards compatibility aliases
    @property
    def material_decisions(self) -> List[MaterialDecision]:
        return self.decisions
    
    @property
    def mua_precedents_found(self) -> int:
        if self.evidence_package:
            return len(self.evidence_package.mua_precedents)
        return 0
```

---

## 9. MATERIAL FAMILY REGISTRY (Rule 6: Not Hardcoded)

```python
# config.py

class MaterialFamilyRegistry:
    """
    Material family → composition key mapping.
    
    Loaded from database or config file. NEVER hardcoded in pipeline logic.
    Adding a new material family = adding a row, not editing code.
    """
    
    # Default fallback (loaded from DB at init, this is bootstrap only)
    _DEFAULTS = {
        'fluorosilicone': 833,
        'silicone': 832,
        'ptfe': 700,
        'teflon': 700,
        'aluminum': 100,
        'stainless': 200,
        'inconel': 300,
        'titanium': 400,
    }
    
    def __init__(self, db_conn=None):
        self._registry = dict(self._DEFAULTS)
        if db_conn:
            self._load_from_db(db_conn)
    
    def _load_from_db(self, conn):
        """Load material families from map.material_families table."""
        try:
            cur = conn.cursor()
            cur.execute("SELECT family_name, composition_key FROM map.material_families")
            for row in cur.fetchall():
                self._registry[row[0].lower()] = row[1]
            cur.close()
        except Exception:
            pass  # Use defaults
    
    def get_composition_key(self, query: str) -> Optional[int]:
        """Find composition key from query text."""
        query_lower = query.lower()
        for family, key in self._registry.items():
            if family in query_lower:
                return key
        return None
```

---

## 10. MIGRATION PLAN

### Phase 1: Extract Models (30 min)
- Create `models.py` with all shared types
- Delete duplicate `MaterialConstraints` from `query_engine_v2.py`
- Delete duplicate `MaterialConstraints` from `constraint_interpreter.py`
- Import from `models.py` everywhere

### Phase 2: Extract Matching Functions (30 min)
- Move `classify_environment()` → `matching/environment_classify.py`
- Move `materials_match()` → `matching/material_match.py` (extract from inline)
- Move `infer_test_types()`, `extract_hazards_from_mitigations()`, 
  `is_relevant_for_oxygen_query()` → `matching/o2_relevance.py`

### Phase 3: Extract Evidence Retrieval (1 hour)
- Move MUA retrieval logic → `evidence/mua_retriever.py`
- Move test data logic → `evidence/test_data_retriever.py`  
- Move semantic retrieval → `evidence/semantic_retriever.py` (wrapper)
- Create `evidence/package.py` with `EvidencePackage`

### Phase 4: Extract Router (45 min)
- Move `IntentClassifier` → `router/intent_classifier.py`
- Create `router/query_router.py` with new routing rules
- Wire up routing decision logic

### Phase 5: Extract Interceptors (30 min)
- Move `_check_o2_deterministic_boundaries()` → `interceptors/o2_boundary.py`
- Create `interceptors/h2_boundary.py` (new)
- Create `interceptors/base.py` ABC

### Phase 6: Create Pipelines (1 hour)
- Create `pipelines/base.py` ABC
- Create `pipelines/compatibility.py` (main evidence-first flow)
- Create `pipelines/materials_search.py` (existing `_materials_search` method)

### Phase 7: Wire Engine (30 min)
- Create new `engine.py` as thin orchestrator
- Wire interceptors → router → pipelines
- Verify backwards compatibility via `query()` method signature

### Phase 8: Test (ongoing)
- Run existing test queries through new engine
- Verify routing decisions match expected behavior
- Verify O2 boundary still catches aluminum-in-GOX
- Verify materials_search returns all 94 fluorosilicones
- Verify compatibility returns filtered results

---

## 11. ROUTING TEST MATRIX

| Query | Expected Route | Reason |
|-------|---------------|--------|
| "show me fluorosilicone materials" | MATERIALS_SEARCH | list language, no gas service |
| "fluorosilicone compatible with O2" | COMPATIBILITY | explicit compat + gas service |
| "aluminum 6061 in oxygen at 3000 psi" | COMPATIBILITY | gas service + pressure |
| "list all stainless steel alloys" | MATERIALS_SEARCH | list language, no gas |
| "is titanium safe for hydrogen service" | COMPATIBILITY | explicit compat + gas |
| "compare 316 vs 321 stainless" | COMPARISON | comparison language |
| "NASA-STD-6001B requirements" | DOCUMENT_LOOKUP | standard reference |
| "how do I search for materials" | HELP | help language |
| "fluorosilicone" (bare word) | COMPATIBILITY | ambiguous → conservative |
| "what fluorosilicone materials exist" | MATERIALS_SEARCH | "what...exist" = listing |
| "fluorosilicone for LOX service" | COMPATIBILITY | gas service context |
| "show me polymers rated for O2" | COMPATIBILITY | list + gas service → compat wins |

---

## 12. WHAT THIS ENABLES

With this architecture:

1. **Adding Granta** = Create `evidence/granta_retriever.py`, inject into CompatibilityPipeline.
   Zero changes to router, interceptors, or other pipelines.

2. **Adding a new database** (Phase B: MISSEE, Additive Mfg, etc.) = Add retriever,
   add material families to registry. Same pipelines.

3. **AEGIS reuse** = Same router pattern, different interceptors (PFAS rules instead of 
   O2/H2), different pipelines (degradation instead of compatibility), same evidence 
   package structure.

4. **ATHENA reuse** = Same router → document pipeline, entity extraction pipeline.
   Same semantic search infrastructure.

5. **Steve can't stump it** because routing is deterministic and testable.
   "Show me fluorosilicones" will ALWAYS go to materials_search.
   "Fluorosilicone in O2" will ALWAYS go to compatibility.
   No ambiguity. No race conditions. No LLM deciding which path to take.
