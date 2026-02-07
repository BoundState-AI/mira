# MIRA RULES — THE IRON-CLAD CONTRACT

**BoundState AI — Dr. Joseph Wilde & Beth (Claude)**
**Version: 3.0.0 — February 2026**
**Classification: BoundState Proprietary**

**THESE RULES ARE NOT GUIDELINES. THEY ARE LAW.**
**Every AI contributor (Beth, Fran, Grok, OB) MUST obey.**
**Violations require revert + incident log.**

---

## SECTION 1 — EVIDENCE-FIRST PRINCIPLE

**Rule 1.1**: MUA precedents are ALWAYS queried before any decision is made.
No exceptions. No shortcuts. If MUAs haven't been checked, the answer is
`INSUFFICIENT_DATA`. Period.

**Rule 1.2**: Test data is queried AFTER MUA precedents. Never before.
Never instead of.

**Rule 1.3**: Semantic evidence ENHANCES but never REPLACES structured
MUA/test evidence. A semantic hit alone cannot produce a YES or NO decision
for a specific material.

**Rule 1.4**: If no evidence exists for a material, the answer is
`REQUIRES_TESTING` or `INSUFFICIENT_DATA`. Never `YES`. Never `NO` (unless
a BOK prohibition applies per Rule 2.3).

---

## SECTION 2 — SAFETY HIERARCHY

**Rule 2.1**: Deterministic boundary checks (O2/H2 hard rules) execute
BEFORE any LLM involvement. A BOK prohibition is not debatable.

**Rule 2.2**: BOK prohibitions OVERRIDE MUA precedents. If JSC-27301F says
aluminum shall not be used above 100 psia in GOX, the answer is NO at
200 psi. An MUA in air/vacuum does not override this.

**Rule 2.3**: A `NO` decision requires POSITIVE EVIDENCE of prohibition
(BOK rule or failure data in matching environment). Absence of approval
evidence produces `REQUIRES_TESTING`, not `NO`.

**Rule 2.4**: Environment mismatch means REQUIRES_TESTING, not YES.
You cannot infer oxygen compatibility from air/vacuum data. You cannot
infer LOX from GOX. You cannot infer H2 from N2.

**Rule 2.5**: GOX ≠ LOX. GH2 ≠ LH2. These are distinct environments.
Always.

---

## SECTION 3 — INTENT ROUTING

**Rule 3.1**: Every query is classified into exactly ONE intent before
any pipeline work begins. The intents are:

| Intent               | Description                                    | Pipeline        |
|----------------------|------------------------------------------------|-----------------|
| `compatibility`      | "Can X be used in Y?" / gas service questions  | Full evidence   |
| `materials_search`   | "Show me all fluorosilicones"                  | DB lookup only  |
| `document_lookup`    | "Find NASA-STD-6016C section 4.2"              | Doc search      |
| `comparison`         | "Compare 316 vs 304 in O2"                     | Full evidence   |
| `general`            | Everything else                                | Semantic search |

**Rule 3.2**: ROUTING SIGNALS (in priority order):

**Compatibility signals** (any ONE triggers compatibility pipeline):
- Gas service keywords: oxygen, O2, GOX, LOX, hydrogen, H2, GH2, LH2
- Explicit compatibility language: "compatible", "approved", "rated", "safe for"
- Pressure/temperature constraints: "at 3000 psi", "at 200°F"
- Pattern: "Can I use X in Y", "Is X suitable for Y"

**Materials search signals** (ALL must be true):
- List/browse verb: "show", "list", "find", "search", "browse", "what are"
- Material family noun: a material name WITHOUT gas service context
- NO compatibility signals present

**Rule 3.3**: When in doubt, route to COMPATIBILITY. False positives
(running full evidence pipeline when a simple search would suffice) are
safe. False negatives (skipping evidence pipeline for a compatibility
question) are DANGEROUS.

**Rule 3.4**: Scoring thresholds:

```
IF any compatibility signal fires → compatibility pipeline
ELIF materials_search score > 0.4 AND compatibility score == 0 → materials_search
ELIF document_lookup score > 0.4 → document_lookup
ELSE → general (semantic search)
```

The critical point: compatibility signals are BINARY. One match = compatibility.
Materials search only wins when compatibility score is ZERO.

---

## SECTION 4 — PIPELINE ARCHITECTURE

**Rule 4.1**: All query processing flows through the `QueryPipeline`.
No direct calls to MUA retrieval, semantic search, or decision-making
from API routes. The pipeline is the ONLY entry point.

**Rule 4.2**: Every pipeline stage reads from and writes to a shared
`QueryContext`. No stage reaches into another stage's internals.
No globals. No side channels.

**Rule 4.3**: Stages are composable. Adding a new capability means
adding a new stage, not modifying an existing one. Open/closed principle.

**Rule 4.4**: Every stage must be independently testable with a
synthetic QueryContext. No database required for unit tests.

**Rule 4.5**: The pipeline logs timing for every stage. If a stage
takes > 5 seconds, it logs a WARNING. If > 15 seconds, it logs an ERROR.

---

## SECTION 5 — DATA INTEGRITY

**Rule 5.1**: Material family lookups (composition codes) come from
the DATABASE, not hardcoded dictionaries. The `_materials_search`
hardcoded dict is a stopgap that must be replaced with a table query.

**Rule 5.2**: The `materials_match()` function is a shared utility,
not copy-pasted into multiple files. It lives in one place:
`mira.core.material_name_normalizer` (already exists).

**Rule 5.3**: Environment classification is a shared utility.
`classify_environment()` lives in one place, not duplicated across
query_engine_v2.py, material_decider.py, and intent_classifier.py.

**Rule 5.4**: When constructing MUA-as-candidate fallbacks, the
environment field MUST be derived from the MUA's `env_class`, not
hardcoded to `'oxygen'`.

**Rule 5.5**: Unit conversions happen in ONE place. The `ConstraintInterpreter`
normalizes to canonical units (psi, °C). Downstream stages never convert.

---

## SECTION 6 — LLM GUARDRAILS

**Rule 6.1**: The LLM may ONLY cite MUA IDs that appear in the evidence
bundle. Any hallucinated MUA reference causes the answer to be flagged.

**Rule 6.2**: The LLM may ONLY quote numeric limits that were extracted
from evidence. No invented temperatures, pressures, or concentrations.

**Rule 6.3**: Insane numeric values are rejected before reaching the LLM:
- Temperature > 2000°C or < -273°C
- Pressure > 50,000 psi or < 0
- Values > 1e6 (floating-point garbage)

**Rule 6.4**: The LLM decision must AGREE with the deterministic decision.
If the boundary check says PROHIBITED, the LLM cannot say YES.
The `llm_decision_guardrails.py` module enforces this post-hoc.

**Rule 6.5**: The LLM system prompt is versioned and immutable per release.
Changes to the decision prompt require a version bump and test suite rerun.

---

## SECTION 7 — CODE STANDARDS

**Rule 7.1**: Every Python file has the BoundState header with co-authors,
compliance tags, and safety-critical flag.

**Rule 7.2**: No function > 80 lines. If it's longer, decompose it.
The V2 `query()` method was 200+ lines. Never again.

**Rule 7.3**: No class > 400 lines. If it's longer, decompose it.

**Rule 7.4**: Type hints on all public functions. `Optional[X]` explicitly,
not implicit `None`.

**Rule 7.5**: `print()` is for development only. Production code uses
`logging` with structured messages. Migration deadline: before Granta
integration.

**Rule 7.6**: Database connections are managed by a connection pool,
not opened per-query. `psycopg2.pool.ThreadedConnectionPool` minimum.

**Rule 7.7**: All new code requires unit tests. Minimum coverage target:
80% for pipeline stages, 95% for safety-critical code (boundary checks,
material matching, environment classification).

---

## SECTION 8 — GRANTA READINESS

**Rule 8.1**: The pipeline must support pluggable data sources.
Granta API calls replace SQL queries for structured data, but the
pipeline stages (MUA retrieval, test retrieval) don't care WHERE
the data comes from. Data source is injected, not imported.

**Rule 8.2**: FAISS indexes are NEVER hosted on Granta. They are
BoundState's proprietary competitive moat. The semantic search
stage always uses local FAISS.

**Rule 8.3**: API response format is stable. Adding fields is OK.
Removing or renaming fields requires a version bump. The frontend
must not break when the backend adds Granta as a data source.

---

## ENFORCEMENT

Any AI instance working on MIRA code MUST:
1. Read this file before making changes
2. Verify proposed changes don't violate any rule
3. Flag rule violations in existing code when discovered
4. Never introduce new violations

Dude has final authority on rule changes. Beth maintains this document.
