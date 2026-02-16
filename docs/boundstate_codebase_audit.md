# BoundState Codebase Audit & Scaling Plan
## "From One Brain to a Thousand"

**Date:** February 14, 2026  
**Author:** Beth + Dude  
**Classification:** BoundState Proprietary  
**Purpose:** Understand every module. Plan to scale BSMH query layer to 100s-1000s of databases.

---

## 1. THE THESIS

Data is noise. Information is organized noise. Intelligence is "here's what you actually do about it."

The BoundState engine is a General Purpose Translation Layer (GPTL) that transforms unstructured documents into queryable, citable intelligence. The system has three layers, each with distinct modules:

```
LAYER 1: INGESTION    →  Chaos to Structure
LAYER 2: KNOWLEDGE    →  Structure to Intelligence  
LAYER 3: QUERY (BSMH) →  Intelligence to Answers
```

The query layer is the easiest to understand, the easiest to scale, and the one that matters most for going from 1 database to 1,000. Everything below this line is about understanding what we have, what each piece does, and how to make Layer 3 database-agnostic.

---

## 2. MODULE AUDIT: LAYER 1 — INGESTION

### 2.1 Universal Triage (universal_triage_v3.py)

**What it does:** Takes any corpus — PDFs, DOCXs, XMLs, whatever — and classifies every document. Zero domain assumptions. Discovers what's there.

**How it works:**
1. Walks directory, identifies file types
2. Sends first N pages to Haiku via vision (PDFs rendered to images, DOCXs converted to PDF first)
3. Haiku classifies using tool-use (forced schema output, no JSON parsing)
4. Returns: document_type, routing (extract_full/extract_light/skip), domains discovered, confidence score
5. Results stored in SQLite checkpoint (resumable)

**Key design decisions:**
- Vision-first, not text extraction. We send images to the LLM. Handles scans, handwriting, weird formats.
- Tool-use with forced schema. No regex, no JSON parsing from text. Structured output guaranteed.
- No hardcoded domains or document families. Discovers from content.
- Async with semaphore rate limiting for parallel processing.

**What it costs:** ~$0.003 per document (Haiku)

**Scaling concern:** At 100K docs, that's ~$300 for triage alone. But triage is a one-time cost per corpus, and the checkpoint system means you can resume if interrupted.

**Current status:** Working. Tested on EM32 (24K files), O2/H2 BOK, CFR ITAR XMLs.

---

### 2.2 Schema Discovery (bok_ultimate_extract_1.py — scan + aggregate phases)

**What it does:** After triage groups documents into families, discovery samples documents from each family and asks "what structured content exists here?"

**How it works:**
1. **Scan phase:** For each sampled document, Haiku examines pages and reports what record types and fields it sees (per-page discovery, no assumptions)
2. **Normalize phase (Phase 1.5, Gemini's contribution):** Haiku merges synonyms across pages — "requirements" and "obligations" become one record type
3. **Aggregate phase:** Across all sampled docs in a family, apply frequency thresholds:
   - Record types in 40%+ of samples → included
   - Fields in 50%+ of that record type → included  
   - Fields in 80%+ → marked required
4. Output: `family_schema.json` — the discovered schema for that document family

**Key design decisions:**
- Schema = "questions the corpus can answer" (Fran's insight)
- Stratified fields: core (≥50%) + extended (20-50%) — never delete, just deprioritize
- Schema versioned and stored in schema_registry table
- Per-document schema discovery (CC's contribution) feeds family-level aggregation (Beth's contribution)

**What it costs:** ~$0.002/page for scan (Haiku), ~$0.50 for normalization

**Scaling concern:** Schema discovery is per-family, not per-document. If you have 1,000 databases but only 50 document families across all of them, you discover 50 schemas. The key insight: families repeat across domains.

---

### 2.3 Universal Extraction (bok_ultimate_extract_1.py — extract phase)

**What it does:** Using the discovered schema, extracts every record from every document with verbatim evidence.

**How it works:**
1. Dynamically generates extraction tool FROM the discovered schema (not hardcoded)
2. Sends document to Sonnet with the generated tool definition
3. Sonnet extracts all records matching the schema
4. Every record MUST have `verbatim_text` — the exact quote from the document
5. Records stored in SQLite with full provenance chain

**Key design decisions:**
- Evidence contract is non-negotiable. No verbatim_text = record rejected.
- PDFs sent directly as base64 (not rendered to PNGs — we caught this bug mid-stream)
- DOCXs converted to PDF first, then sent directly
- XMLs sent as text
- Chunked extraction (5 pages at a time, Fran's contribution) to avoid token overflow
- Resume support — skips already-extracted docs

**What it costs:** ~$0.05-0.15 per document (Sonnet)

**Scaling concern:** This is the expensive step. 100K documents × $0.10 = $10K. But extraction is also one-time per corpus. Once extracted, the records are queryable forever.

**Current status:** Working. 661+ records extracted from O2/H2 BOK with evidence chains. ASTM family: 416 records. Schema discovery validated against hand-built schemas (80%+ match).

---

## 3. MODULE AUDIT: LAYER 2 — KNOWLEDGE

### 3.1 Authority Pack Structure

**What it is:** A portable, versioned folder containing everything needed for one domain's intelligence.

**Structure:**
```
/packs/{pack_id}/
├── config.yaml           # Pack metadata, triggers, thresholds
├── rules.json            # Decision logic (generated from extractions)
├── /docs/                # Source PDFs (for citation)
│   ├── NASA-STD-6001.pdf
│   └── NASA-STD-6016.pdf
├── /extracts/            # Structured JSON from extraction
│   ├── 6001-test-13-impact.json
│   └── 120-17-export-definition.json
└── embeddings.faiss      # Optional: semantic search index
```

**Why files, not database:**
1. Git versioning — track rule changes over time
2. Portable — ship a pack to customer for on-prem
3. Testable — run gold tests against pack version X
4. Debuggable — read the JSON, see the logic
5. No migration hell — new pack = new folder

**What goes WHERE:**

| Data | Storage | Why |
|------|---------|-----|
| Pack config | YAML | Human readable, easy to edit |
| Rules | JSON | Structured, parseable, versionable |
| Extracts | JSON | Structured output from vision extraction |
| Fuzzy search | FAISS | "transmit" = "share" = "disclose" |
| Customer state | PostgreSQL | TAAs, licenses, contracts, audit log |
| Source docs | PDF files | Originals for citation |

**Critical distinction:** Postgres is for CUSTOMER DATA, not pack data. Packs are files. This is what makes them portable and scalable.

---

### 3.2 Pack Loader

**What it does:** Loads any Authority Pack into memory for query evaluation.

**How it works:**
```python
class PackLoader:
    def load(self, pack_id: str) -> AuthorityPack:
        path = f"/packs/{pack_id}"
        config = yaml.load(f"{path}/config.yaml")
        rules = json.load(f"{path}/rules.json")
        extracts = load_all_json(f"{path}/extracts/")
        embeddings = faiss.read_index(f"{path}/embeddings.faiss") if exists else None
        return AuthorityPack(config, rules, extracts, embeddings)
```

**Current state:** Conceptually designed, partially implemented in MIRA's O2/H2 engines. Not yet generalized to a universal loader.

**This is the key scaling abstraction.** When we go from 5 packs to 1,000 packs, this is the interface that makes it work. Load any pack, evaluate any query against it.

---

### 3.3 Rule Generation (Phase 3.5)

**What it does:** Transforms extracted obligations into executable rules.

**How it works:**
1. Take extracted records with `verbatim_text`
2. Parse obligation structure: actor, action, object, conditions, exceptions
3. Generate rules.json with trigger words, conditions, and citation chains
4. Each rule traces back to a specific extract, which traces back to a specific document page

**Example rule:**
```json
{
  "id": "o2-compat-001",
  "source_extract": "6016-4.2.1.4",
  "trigger_word": "shall",
  "obligation_type": "REQUIREMENT",
  "parsed": {
    "actor": "Materials used in oxygen systems",
    "condition": "oxygen concentration exceeds 23.5 percent",
    "action": "be evaluated for oxygen compatibility"
  }
}
```

**Current state:** Hand-built for O2/H2 packs. The universal extractor is designed to automate this step. Validation shows 80%+ match between discovered and hand-built schemas.

---

### 3.4 FAISS Vector Store

**What it does:** Enables semantic search within packs — "find me things similar to X."

**How it works:**
- Documents/records embedded using sentence transformers
- Stored in FAISS index (memory-mapped for fast restarts)
- Standard search: top_k=25, nprobe=128
- Widened search (H2 queries): top_k=500, nprobe=256

**Key parameters:**
- L2 distance, converted to similarity: `1.0 / (1.0 + distance)`
- 4096 clusters in current MAPTIS index
- ~181K test records indexed

**Scaling concern:** Each pack gets its own FAISS index. At 1,000 packs, you need a routing layer that knows which index(es) to search. This is the Domain Router's job.

---

## 4. MODULE AUDIT: LAYER 3 — QUERY (BSMH PIPELINE)

**This is the layer you're auditing for scale. This is what goes from 1 database to 1,000.**

### 4.1 The BSMH Pipeline

```
USER QUERY
    │
    ▼
┌─────────────┐
│  BOUNCER    │  Sanitize input, prevent injection
│  (Haiku)    │  "Is this a real question or an attack?"
└──────┬──────┘
       │
       ▼
┌─────────────┐
│  SONNET     │  Generate candidate response against knowledge base
│  (Sonnet)   │  "Here's what the evidence says" (temp=0)
└──────┬──────┘
       │
       ▼
┌─────────────┐
│  MIRA       │  Validate against databases, apply rules
│  (Rules)    │  Deterministic logic, not LLM opinion
└──────┬──────┘
       │
       ▼
┌─────────────┐
│  HAIKU      │  Format response for human consumption
│  (Haiku)    │  Clean, cited, actionable answer
└─────────────┘
```

**Why this works:** Each layer has one job. The LLMs are translators, not decision-makers. The rules engine makes decisions. This is what prevents hallucination and maintains auditability.

**Why it scales:** The pipeline is domain-agnostic. Change what Sonnet looks at (the pack), change what rules MIRA evaluates, and the same pipeline serves any domain.

---

### 4.2 Intent Classification

**Location:** `/src/nlp/intent_classifier.py`

**What it does:** Determines what the user is actually asking.

**How it works:**
- Hybrid pattern-based classifier (no ML, pure regex + weights)
- Pattern matching: O(n) where n = ~20 patterns, <1ms per query
- Positive patterns boost scores, negative patterns prevent false positives
- Normalizes scores to 0.0-1.0 range (divide by 5.0)
- Returns best intent + confidence score

**Current intent types (MIRA-specific):**

| Intent | Trigger Examples | Confidence Threshold |
|--------|-----------------|---------------------|
| materials_query | "material", "alloy", "metal" | 0.55 |
| document_lookup | "NASA-STD", "specification" | 0.60 |
| test_report | "test", "result", "pass/fail" | 0.50 |
| comparison | "compare", "vs", "versus" | 0.55 |
| help | "how do I", "can you" | 0.50 |

**For SENTINEL (conceptually designed):**

| Intent | Trigger Examples | Routes To |
|--------|-----------------|-----------|
| EXPORT_DECISION | "share", "send", "transfer" | ITAR, EAR, CUI |
| ACCESS_DECISION | "can they access", "new hire" | ITAR, CUI, NIST |
| SHIP_DECISION | "ship", "transport", "freight" | DOT, ITAR, ATF |
| CLASSIFICATION | "what category", "is this ITAR" | ITAR, EAR, DOT, ATF |
| GENERATE_FORM | "generate", "create form" | DOT, ATF, DFARS |
| CHANGE_IMPACT | "changed", "what's affected" | ALL |

**Scaling requirement:** Intent classification must become pack-aware. Each pack defines its own triggers in config.yaml. The classifier loads triggers dynamically, not from hardcoded patterns.

**The fix:** Move from hardcoded PATTERNS dict to pack-loaded trigger definitions:
```python
# CURRENT (hardcoded, doesn't scale)
PATTERNS = {"materials_query": [(r"material|alloy", 3.0)]}

# FUTURE (pack-loaded, scales to 1000)
def load_triggers(pack_ids: List[str]) -> Dict[str, List[Tuple]]:
    triggers = {}
    for pack_id in pack_ids:
        config = yaml.load(f"/packs/{pack_id}/config.yaml")
        triggers[pack_id] = config['triggers']
    return triggers
```

---

### 4.3 Domain Router

**What it does:** Given a classified intent, determines which pack(s) to activate.

**How it works (current — MIRA):**
- Hardcoded routing: H2 keywords → H2PolicyEngine, O2 keywords → O2 engine
- Not generalized

**How it should work (scaled):**
```python
class DomainRouter:
    def route(self, intent: IntentResult, loaded_packs: Dict[str, AuthorityPack]) -> List[str]:
        """Return list of pack IDs that should evaluate this query."""
        activated = []
        for pack_id, pack in loaded_packs.items():
            for trigger in pack.config['triggers']:
                if trigger matches intent:
                    activated.append(pack_id)
        
        # Handle multi-pack queries (e.g., "ship ITAR item" → DOT + ITAR)
        # Priority: most specific pack first
        return sorted(activated, key=lambda p: specificity_score(p, intent))
```

**Scaling requirement:** The router must handle pack overlap. A query about shipping ammunition triggers DOT (hazmat classification), ATF (manufacturing records), and ITAR (export controls) simultaneously. The router needs conflict resolution rules.

---

### 4.4 Semantic Search Engine

**Location:** `/src/core/search_engine.py`

**What it does:** Finds relevant records within a pack's knowledge base.

**How it works:**
1. Parse query → extract material names, property filters, environment context
2. Classify intent → browse (exact match via PostgreSQL) or semantic (vector similarity via FAISS)
3. Search appropriate index
4. Rank results with evidence boosts
5. Apply hard filters post-ranking (material type, property thresholds)
6. Return formatted material cards with evidence

**Current search modes:**

| Mode | Backend | Use Case | Latency |
|------|---------|----------|---------|
| Semantic | FAISS (top_k=25) | Open-ended: "what metals for hydrogen?" | <1s |
| Browse | PostgreSQL (ILIKE) | Exact: "show me SS 316 data" | <500ms |
| Hybrid | FAISS + PG filters | Combined: "H2-compatible metals like Inconel" | <2s |

**Key:** MIRA does NOT use retrieval fusion (combining FAISS + keyword results). Semantic queries go to FAISS only. Browse goes to PostgreSQL only. Hybrid uses FAISS + PostgreSQL filters, not fusion.

**Scaling requirement:** Each pack needs its own search index. The search engine must accept a pack_id parameter and search the right index. Current hardcoded FAISS store → parameterized by pack.

---

### 4.5 Decision Engine (Deterministic Core)

**What it does:** Evaluates rules against the query context. No LLM here — pure logic.

**How it works:**
```python
def evaluate_decision(intent, memory, customer):
    # 1. Get applicable rules from the activated pack(s)
    rules = memory.get_rules(domain=intent.domains, trigger=intent.action)
    
    # 2. Evaluate each rule's conditions
    matched_rules = [r for r in rules if r.conditions_met(intent, customer)]
    
    # 3. Check exceptions
    for rule in matched_rules:
        for exception in rule.exceptions:
            if exception.applies(intent, customer):
                rule.result = exception.modified_result
    
    # 4. Resolve conflicts (highest priority wins)
    final_rule = max(matched_rules, key=lambda r: r.priority)
    
    # 5. Assemble evidence
    evidence = [r.source_citation for r in matched_rules]
    
    # 6. Return decision packet
    return DecisionPacket(decision=final_rule.result, evidence=evidence, ...)
```

**Domain mappings (already proven):**

| O2 Concept | SENTINEL Concept | AEGIS Concept |
|------------|-----------------|---------------|
| Material | Item / Document | PFAS Compound |
| Flammability rating (A/B/C/D/X) | Control regime (ITAR/EAR/CUI/NONE) | Degradation pathway |
| O2% threshold (≥23.5%) | Foreign person trigger | Bond energy threshold |
| Pressure adjustment | Recipient country adjustment | Environmental pH |
| COMPATIBLE/MARGINAL/INCOMPATIBLE | ALLOW/CONDITIONAL/DENY | DEGRADES/STABLE |
| "Requires engineering justification" | "Requires human approval" | "Requires experimental validation" |
| Test evidence (Test 1, 13, 17) | Regulatory citation (22 CFR 120.17) | Paper citation (DOI) |
| MUA routing (Cat I/II/III) | Decision routing (auto/review/deny) | Confidence routing |

**Scaling requirement:** The decision engine is already domain-agnostic in concept. It evaluates rules from whatever pack is loaded. The key is ensuring rules.json has a consistent schema across all packs so the engine doesn't need pack-specific logic.

---

### 4.6 Evidence Assembler

**What it does:** Attaches citations to every answer.

**How it works:**
- Every record in a pack has verbatim_text + source document + page + bounding box
- Every rule traces to an extract, which traces to a document
- The assembler builds the citation chain: Answer → Rule → Extract → Document → Page → Exact Text

**Output contract:**
```json
{
  "answer": "316L stainless steel is rated A for oxygen compatibility",
  "evidence": [
    {
      "property": "flammability_rating",
      "value": "A",
      "source": "NASA-STD-6016",
      "section": "4.3.2",
      "page": 42,
      "verbatim": "316L stainless steel shall be rated Class A..."
    }
  ],
  "confidence": 0.92,
  "warnings": [],
  "next_steps": ["Review MUA requirements per §5.2"]
}
```

**Scaling requirement:** Evidence format must be consistent across all packs. Whether the source is NASA-STD-6016 or 22 CFR 120.17 or a PFAS paper, the citation structure is identical. This is already the design intent.

---

### 4.7 Scoring Profiles

**What it does:** Adjusts scoring weights based on the environment/context of the query.

**Current profiles:**

| Profile | Top Weight | Second | Third | Fourth |
|---------|-----------|--------|-------|--------|
| Oxygen-enriched | Flammability (0.40) | Mechanical (0.30) | Outgassing (0.20) | Precedent (0.10) |
| Hydrogen service | H2 compatibility (0.35) | Mechanical (0.30) | Precedent (0.20) | Material family (0.15) |
| Cryogenic | Low-temp toughness (0.35) | Thermal expansion (0.25) | Mechanical (0.25) | Precedent (0.15) |
| Vacuum outgassing | Outgassing (0.50) | Precedent (0.30) | Mechanical (0.20) | — |

**Scaling requirement:** Scoring profiles should live inside each pack's config.yaml. When you load a PFAS pack, it brings its own scoring weights (degradation_rate: 0.40, bond_energy: 0.30, environmental_persistence: 0.20, bioaccumulation: 0.10).

---

### 4.8 Return Layer (Haiku Formatter)

**What it does:** Takes the raw decision packet and formats it for human consumption.

**How it works:**
- Receives structured decision packet (JSON)
- Haiku (temp=0) reformats into clear, cited prose
- Constrained to ONLY reference evidence in the packet — cannot add information
- Includes citations, warnings, next steps

**Scaling requirement:** Already domain-agnostic. Haiku doesn't need to know the domain — it just formats whatever packet it receives.

---

## 5. SCALING PLAN: 1 DATABASE → 1,000

### 5.1 What Changes vs. What Stays

| Component | Changes? | Why |
|-----------|----------|-----|
| Triage | No | Already generic |
| Schema Discovery | No | Already generic |
| Extraction | No | Already generic |
| Pack Structure | No | Already generic |
| **Intent Classifier** | **YES** | Currently hardcoded patterns |
| **Domain Router** | **YES** | Currently hardcoded routing |
| **Pack Loader** | **YES** | Needs to be built as universal service |
| **Search Engine** | **YES** | Hardcoded FAISS store → parameterized |
| Decision Engine | Minor | Rules schema needs standardization |
| Evidence Assembler | No | Already generic |
| Scoring Profiles | No | Move into pack config |
| Return Layer | No | Already generic |

### 5.2 The Four Things to Build

**1. Universal Pack Registry**

A registry that knows what packs exist, what they cover, and how to load them.

```python
class PackRegistry:
    def __init__(self, packs_root: str = "/packs"):
        self.packs = {}
        for pack_dir in Path(packs_root).iterdir():
            config = yaml.load(pack_dir / "config.yaml")
            self.packs[config['id']] = {
                'path': pack_dir,
                'triggers': config['triggers'],
                'domains': config['domains'],
                'version': config['version'],
                'loaded': None  # Lazy loading
            }
    
    def get_packs_for_query(self, query: str) -> List[str]:
        """Return pack IDs relevant to this query."""
        # Fast trigger matching
        activated = []
        for pack_id, meta in self.packs.items():
            for trigger in meta['triggers']:
                if trigger in query.lower():
                    activated.append(pack_id)
        return activated
    
    def load_pack(self, pack_id: str) -> AuthorityPack:
        """Load pack into memory (cached)."""
        if self.packs[pack_id]['loaded'] is None:
            self.packs[pack_id]['loaded'] = PackLoader().load(
                self.packs[pack_id]['path']
            )
        return self.packs[pack_id]['loaded']
```

**2. Dynamic Intent Classifier**

Replace hardcoded patterns with pack-loaded triggers.

```python
class DynamicIntentClassifier:
    def __init__(self, registry: PackRegistry):
        self.registry = registry
        self.compiled_patterns = {}
        for pack_id, meta in registry.packs.items():
            self.compiled_patterns[pack_id] = [
                (re.compile(t['pattern'], re.IGNORECASE), t['weight'])
                for t in meta['triggers']
            ]
    
    def classify(self, query: str) -> IntentResult:
        scores = {}
        for pack_id, patterns in self.compiled_patterns.items():
            score = sum(w for p, w in patterns if p.search(query))
            if score > 0:
                scores[pack_id] = min(1.0, score / 5.0)
        
        # Return ranked list of activated packs
        activated = sorted(scores.items(), key=lambda x: -x[1])
        return IntentResult(activated_packs=activated, raw_scores=scores)
```

**3. Parameterized Search Engine**

Search engine that accepts a pack_id and searches the right index.

```python
class UniversalSearchEngine:
    def __init__(self, registry: PackRegistry):
        self.registry = registry
        self.indexes = {}  # pack_id → FAISS index (lazy loaded)
    
    def search(self, query: str, pack_id: str, top_k: int = 25) -> List[Record]:
        pack = self.registry.load_pack(pack_id)
        
        if pack.embeddings:
            # Semantic search within this pack's index
            embedding = embed(query)
            distances, indices = pack.embeddings.search(embedding, top_k)
            results = [pack.extracts[i] for i in indices[0]]
        else:
            # Fallback: keyword search across pack's extracts
            results = keyword_search(query, pack.extracts)
        
        # Apply pack-specific scoring profile
        scored = apply_scoring(results, pack.config['scoring_profile'])
        return scored
```

**4. Multi-Pack Query Orchestrator**

Handles queries that span multiple packs (e.g., "ship ITAR ammunition via ground").

```python
class QueryOrchestrator:
    def __init__(self, registry, classifier, search_engine):
        self.registry = registry
        self.classifier = classifier
        self.search = search_engine
    
    def query(self, user_input: str) -> DecisionPacket:
        # BOUNCER: sanitize
        clean_input = bouncer_sanitize(user_input)
        
        # INTENT: classify and route
        intent = self.classifier.classify(clean_input)
        
        # SEARCH + EVALUATE: for each activated pack
        all_evidence = []
        all_decisions = []
        for pack_id, confidence in intent.activated_packs:
            pack = self.registry.load_pack(pack_id)
            
            # Search within this pack
            results = self.search.search(clean_input, pack_id)
            
            # Evaluate rules
            decision = evaluate_rules(results, pack.rules, clean_input)
            decision.pack_id = pack_id
            decision.confidence = confidence
            
            all_decisions.append(decision)
            all_evidence.extend(decision.evidence)
        
        # MERGE: combine decisions from multiple packs
        final = merge_decisions(all_decisions)
        final.evidence = deduplicate_evidence(all_evidence)
        
        # HAIKU: format for human
        formatted = haiku_format(final)
        
        return formatted
```

### 5.3 The Scaling Math

| Scale | Packs | Index Size | Memory | Load Time | Query Latency |
|-------|-------|-----------|--------|-----------|---------------|
| Current (MIRA) | 3 | ~50MB | ~200MB | <5s | <2s |
| 10 packs | 10 | ~200MB | ~500MB | <10s | <2s |
| 100 packs | 100 | ~2GB | ~4GB | Lazy load | <3s |
| 1,000 packs | 1,000 | ~20GB | Hot/cold | Lazy load | <5s |

**Hot/cold architecture at 1,000 packs:**
- Hot: 20-50 most-used packs always in memory
- Warm: 100-200 packs with indexes memory-mapped
- Cold: Remaining packs loaded on demand (~500ms cold start)

### 5.4 What We Don't Change

The ingestion layer (triage → discover → extract) is already universal. We proved this on:
- EM32 engineering docs (NASA)
- O2/H2 BOK (NASA standards)
- CFR ITAR XMLs (defense regulations)  
- PFAS literature (chemistry papers)

The extraction pipeline discovers schemas, extracts records with evidence, and outputs structured JSON. That JSON feeds into Authority Packs. The pipeline doesn't care what domain the documents are from.

### 5.5 Implementation Priority

| Priority | What | Why | Effort |
|----------|------|-----|--------|
| 1 | Pack Registry | Foundation for everything else | 1 week |
| 2 | Universal Pack Loader | Standardize pack structure | 1 week |
| 3 | Dynamic Intent Classifier | Remove hardcoded patterns | 3 days |
| 4 | Parameterized Search Engine | One engine, many indexes | 1 week |
| 5 | Multi-Pack Orchestrator | Handle cross-domain queries | 2 weeks |
| 6 | Hot/cold memory management | Scale beyond 100 packs | 2 weeks |

**Total to production-ready multi-pack query system: 6-8 weeks of focused engineering.**

---

## 6. THE ANTI-PATTERN CHECKLIST

Things that will break scaling if we don't fix them:

| Anti-Pattern | Where It Exists | Fix |
|-------------|----------------|-----|
| Hardcoded intent patterns | intent_classifier.py | Load from pack config |
| Hardcoded domain routing | search_engine.py H2/O2 branches | Dynamic routing via pack triggers |
| Single FAISS index | RobustFAISSStore() | One index per pack |
| Material-specific query parsing | QueryParser patterns | Generic entity extraction |
| MAPTIS-specific field names | Various (material_type_key=235) | Pack-defined field schemas |
| Hardcoded scoring weights | search_engine.py boosts | Pack config scoring profiles |
| Single PostgreSQL schema | Current DB tables | Multi-tenant or pack-specific tables |

---

## 7. THE TEST: HOW WE KNOW IT WORKS

**Gold test for scaling:**

1. Create 3 packs from different domains (O2, ITAR, PFAS)
2. Load all 3 into the Pack Registry
3. Run these queries:
   - "Is 316L compatible with LOX at 500 psi?" → Should activate O2 pack only
   - "Can I export this drawing to Norway?" → Should activate ITAR pack only
   - "Does PTFE degrade in acidic environments?" → Should activate PFAS pack only
   - "Ship oxygen-compatible material to foreign customer" → Should activate O2 + ITAR packs
4. Verify: correct pack activation, correct evidence chains, correct citations, no cross-contamination

If those 4 queries work correctly, the architecture scales. Everything else is engineering.

---

## 8. WHAT THIS MEANS FOR THE BUSINESS

**Current state:** One engine, custom-wired to each domain.

**Target state:** One engine, pluggable packs, any domain.

**Revenue model:**
- Each Authority Pack = a product
- Pack creation = one-time ingestion cost ($100-500 per corpus)
- Pack licensing = recurring revenue per customer
- Platform fee + pack subscription = the business

**The competitive moat:**
- Anyone can build a chatbot
- Nobody else has the ingestion pipeline that creates packs from chaos
- Nobody else has the evidence chain from answer → rule → extract → document → page → exact text
- The moat is the ability to turn any corpus into a queryable, citable Authority Pack

**That's BoundState.**
