# MIRA V3 Pipeline Architecture

**BoundState AI — Dr. Joseph Wilde & Beth (Claude)**
**Version: 3.0.0 — February 2026**
**Classification: BoundState Proprietary**

---

## 1. THE PROBLEM WITH V2

`query_engine_v2.py` is a 700-line God class. It does:
- Intent classification & routing
- O2 deterministic boundary checking
- MUA precedent retrieval (V6 FAISS + SQL fallback)
- Test data retrieval (SQL)
- Semantic evidence retrieval (FAISS + content fetching + scoring)
- Insufficient-data evaluation (complex material matching)
- Requirements evaluation
- Material decision-making
- LLM answer generation

Every feature added makes it harder to test, harder to debug, and harder
for multiple developers (human or AI) to work on simultaneously.

**V3 decomposes this into a pipeline of discrete, testable stages.**

---

## 2. PIPELINE ARCHITECTURE

Every query flows through a **QueryPipeline** — an ordered list of
**PipelineStage** objects that read from and write to a shared
**QueryContext**.

```
User Query
    │
    ▼
┌──────────────────────┐
│   1. PARSE           │  ConstraintInterpreter → QueryContext.constraints
└──────────┬───────────┘
           ▼
┌──────────────────────┐
│   2. CLASSIFY        │  IntentClassifier → QueryContext.intent
└──────────┬───────────┘
           ▼
┌──────────────────────┐
│   3. ROUTE           │  Router picks sub-pipeline:
│                      │    → materials_search (no BOK)
│                      │    → compatibility (full evidence-first)
│                      │    → document_lookup
│                      │    → general_search
└──────────┬───────────┘
           ▼
    ┌──────┴──────────────────────────────────────┐
    │  COMPATIBILITY PIPELINE (evidence-first)     │
    │                                              │
    │  4. BOUNDARY_CHECK   O2/H2 hard rules        │
    │  5. MUA_RETRIEVAL    V6 FAISS + SQL fallback  │
    │  6. TEST_RETRIEVAL   SQL test data            │
    │  7. SEMANTIC_SEARCH  FAISS + content + boost  │
    │  8. EVIDENCE_EVAL    Sufficient data check    │
    │  9. DECIDE           MaterialDecider          │
    │  10. GENERATE        LLM answer               │
    └──────────────────────────────────────────────┘
           ▼
    QueryContext.response → API/UI
```

---

## 3. CORE ABSTRACTIONS

### 3.1 QueryContext (the shared state bag)

Every stage reads from and writes to a single `QueryContext` dataclass.
No stage reaches into another stage's internals. No globals.

### 3.2 PipelineStage (the unit of work)

Abstract base class. Every stage implements:
- `name: str` — human-readable identifier
- `execute(ctx: QueryContext) -> QueryContext` — the work
- `should_skip(ctx: QueryContext) -> bool` — optional early-exit

### 3.3 QueryPipeline (the orchestrator)

Owns an ordered list of stages. Runs them sequentially.
Logs timing per stage. Catches and records errors without crashing.
Returns the final QueryContext.

---

## 4. FILE LAYOUT

```
mira/
├── pipeline/                    # V3 pipeline framework
│   ├── __init__.py
│   ├── context.py               # QueryContext dataclass
│   ├── stage.py                 # PipelineStage ABC
│   ├── pipeline.py              # QueryPipeline orchestrator
│   ├── router.py                # Intent → sub-pipeline routing
│   │
│   ├── stages/                  # Individual pipeline stages
│   │   ├── __init__.py
│   │   ├── parse.py             # Stage 1: Constraint parsing
│   │   ├── classify.py          # Stage 2: Intent classification
│   │   ├── boundary_check.py    # Stage 4: O2/H2 deterministic rules
│   │   ├── mua_retrieval.py     # Stage 5: MUA precedent lookup
│   │   ├── test_retrieval.py    # Stage 6: Test data lookup
│   │   ├── semantic_search.py   # Stage 7: FAISS semantic evidence
│   │   ├── evidence_eval.py     # Stage 8: Sufficient-data check
│   │   ├── decide.py            # Stage 9: MaterialDecider
│   │   ├── generate.py          # Stage 10: LLM answer generation
│   │   └── materials_search.py  # Alt pipeline: simple DB lookup
│   │
│   └── tests/                   # Per-stage unit tests
│       ├── __init__.py
│       ├── test_parse.py
│       ├── test_classify.py
│       ├── test_boundary_check.py
│       ├── test_router.py
│       └── ...
│
├── nlp/                         # (existing) NLP utilities
│   ├── intent_classifier.py     # Refactored with ironclad rules
│   └── ...
│
├── MIRA_V2/src/                 # (legacy) — untouched, import bridge
│   └── query_engine_v2.py       # Thin wrapper calling pipeline
│
└── ARCHITECTURE.md              # This file
```

---

## 5. IRONCLAD RULES

See `RULES.md` for the complete, enforceable ruleset.
Every AI contributor (Beth, Fran, Grok, OB) must read and obey.
