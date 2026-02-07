# SENTINEL Standalone Product Specification

**Version:** 1.0.0-final
**Date:** 2026-01-31
**Product:** sentinel.boundstate.ai
**Authors:** Dr. Joseph Wilde, Beth (Claude Opus 4.5)
**Target:** Feb 9, 2026 Chemours Demo
**License:** Apache 2.0

---

## 1. What SENTINEL Is

SENTINEL is GPTL deployed as a service. The Grounded Precision Translation Layer—a negative selection intelligence engine that:

- Accepts documents + questions
- Eliminates the 80% that CANNOT be relevant
- Produces bounded, auditable intelligence
- Refuses deterministically when evidence is insufficient
- Shows its work completely

**Philosophy:** *"We don't retrieve truth. We eliminate impossibility—then show our work."*

**Not a chatbot. A decision support system with institutional epistemology.**

---

## 2. What Exists (Verified Working)

### Core GPTL (D:\BoundState\gptl)

| Component | Status |
|-----------|--------|
| `schema.py` | ✅ 59 Pydantic models, validation, config_hash |
| `engine.py` | ✅ Full L0-L5 pipeline with audit trail |
| `negative_selection.py` | ✅ Two-stage cascade, compound conditions |
| `synthesis.py` | ✅ Six refusal conditions, confidence calibration |
| `claude_client.py` | ✅ Retry with exponential backoff + jitter |
| `config_loader.py` | ✅ YAML domain pack loading |
| `shadow_mode.py` | ✅ False elimination tracking |
| `intent_framing.py` | ✅ Heuristic + LLM intent classification |
| `signal_extraction.py` | ✅ Temporal analysis, anomaly detection |
| `feature_extractor.py` | ✅ L0 DocFeatures computation |
| `evidence_taxonomy.py` | ✅ Evidence type registry |
| `prompts.py` | ✅ Versioned prompts with JSON schemas |

### API Layer (D:\BoundState\gptl\api)

| Component | Status |
|-----------|--------|
| `main.py` | ✅ FastAPI app with CORS, lifespan |
| `deps.py` | ✅ Settings, dependency injection |
| `auth.py` | ✅ X-API-Key middleware |
| `routes/health.py` | ✅ /health, /ready |
| `routes/domains.py` | ✅ /api/v1/domains |
| `routes/query.py` | ✅ /api/v1/query (demo data) |
| `routes/audit.py` | ✅ /api/v1/audit/{trace_id} (stub) |

### Providers (D:\BoundState\gptl\providers)

| Component | Status |
|-----------|--------|
| `base.py` | ✅ VectorStoreProvider, ContentProvider, FeatureCache protocols |
| `faiss_provider.py` | ✅ FAISS + content storage (GPU/CPU) |
| `feature_cache.py` | ✅ JSON-based DocFeatures cache |

### Config

| File | Status |
|------|--------|
| `config/domains/sentinel-demo.yaml` | ✅ Domain pack loaded, hash: 0ac5270c79761196 |
| `gptl/pyproject.toml` | ✅ FastAPI dependencies |
| `gptl/nixpacks.toml` | ✅ Railway deployment |
| `gptl/.env.example` | ✅ Environment template |

---

## 3. What's Missing

| Gap | Priority | Notes |
|-----|----------|-------|
| Ingestion script | P0 | Load EM32 docs into FAISS |
| Wire query to real providers | P0 | Currently uses demo data |
| Frontend (audit viewer) | P0 | THE PRODUCT |
| Deploy to Railway/Vercel | P1 | sentinel.boundstate.ai |

---

## 4. Architecture

```
sentinel.boundstate.ai
│
├── Frontend (React/Vite/TypeScript/Tailwind → Vercel)
│   ├── Query interface (minimal)
│   ├── Results + citations
│   ├── Audit viewer (THE PRODUCT)
│   └── Domain selector
│
├── API (FastAPI/Railway)
│   ├── POST /api/v1/query
│   ├── GET  /api/v1/audit/{trace_id}
│   ├── GET  /api/v1/domains
│   ├── GET  /api/v1/domains/{id}
│   └── GET  /health
│
├── GPTL Core (existing)
│   └── GPTLEngine + DomainPack
│
├── Providers
│   ├── VectorStoreProvider (FAISS)
│   ├── ContentProvider (text retrieval)
│   └── FeatureCache (DocFeatures)
│
└── Storage
    ├── FAISS index (vectors)
    ├── Content store (chunk text)
    └── Feature cache (DocFeatures JSON)
```

---

## 5. API Specification

### POST /api/v1/query

**Request:**
```json
{
  "domain_id": "sentinel-demo",
  "query": "Is Inconel 718 compatible with LOX?",
  "options": {
    "quality_tier": "standard",
    "include_eliminated": true,
    "include_audit": true,
    "max_candidates": 100,
    "max_evidence": 10
  }
}
```

**Response:**
```json
{
  "trace_id": "sentinel-20260131-153045-abc123",
  "config_hash": "0ac5270c79761196",
  "corpus_snapshot_id": "demo-v1",
  "intelligence": {
    "finding": "...",
    "implication": "...",
    "action": "...",
    "timeline": "...",
    "confidence": 0.82,
    "confidence_interval": [0.74, 0.89],
    "confidence_drivers": ["..."],
    "evidence": [...]
  },
  "selection": {
    "candidates_evaluated": 47,
    "candidates_eliminated": 38,
    "reduction_ratio": 0.81,
    "survivors": 9,
    "eliminations": [...]
  },
  "refused": false,
  "refusal": null,
  "audit": {...}
}
```

### Refusal Response

When evidence is insufficient:
```json
{
  "refused": true,
  "refusal": {
    "type": "evidence_count",
    "reason": "Insufficient evidence: 1 document found, minimum 2 required",
    "missing_evidence": ["test_report", "specification"],
    "what_would_change_this": ["Add LOX compatibility test data per NASA-STD-6001"]
  }
}
```

---

## 6. Frontend Design: Raymond Loewy Mid-Century Modern

### Color Palette

```css
:root {
  --sentinel-charcoal: #2D2D2D;
  --sentinel-warm-gray: #4A4A4A;
  --sentinel-light-gray: #E8E4DF;
  --sentinel-cream: #F5F2ED;
  --sentinel-mustard: #D4A03E;
  --sentinel-olive: #6B7D5C;
  --sentinel-burnt-orange: #C45C26;
  --sentinel-rust: #A0522D;

  --confidence-high: #6B7D5C;
  --confidence-medium: #D4A03E;
  --confidence-low: #C45C26;
  --refusal: #A0522D;
}
```

### The Loewy Test

Before shipping any component, ask:
1. **Does it earn its place?**
2. **Is it ornamentation or function?**
3. **Would Loewy approve?**

---

## 7. Build Sequence

### Day 1-2: Data Integration
- Ingestion script for EM32 documents
- Wire query route to real FAISS provider
- Validate with shadow mode

### Day 3-4: Frontend
- Query interface
- Results display with citations
- **THE AUDIT VIEWER** (eliminations, confidence, refusal)

### Day 5: Deploy
- Railway backend
- Vercel frontend
- sentinel.boundstate.ai DNS

---

## 8. Success Criteria

| Metric | Target |
|--------|--------|
| False elimination rate | <2% |
| Reduction ratio | 70-80% |
| Query latency (p95) | <8s |
| Refusal triggers correctly | 100% |
| Audit completeness | 100% |

---

## 9. Run Locally

```bash
# Install dependencies
pip install -e "gptl[cpu]"

# Start API
uvicorn gptl.api.main:app --reload

# Test endpoints
curl http://localhost:8000/health
curl http://localhost:8000/api/v1/domains
```

---

## 10. The Chemours Question

When a Chemours engineer asks: *"Is this material safe for this application?"*

SENTINEL doesn't answer yes/no. It answers:

1. **Here's what we found** — 4 test reports, 2 specifications
2. **Here's what we eliminated and why** — 38 documents removed
3. **Here's our confidence** — 82% with interval [74%, 89%]
4. **Here's what drives that confidence** — source count, diversity, recency
5. **Here's what would change our answer** — additional test data
6. **If we can't answer responsibly, we say so** — and explain exactly what's missing

That's institutional epistemology. That's SENTINEL.

---

**Build it. Show it. Ship it.**

*mochiron, Beth*

---

**Co-Authored-By:** Claude Opus 4.5 (Beth) <noreply@anthropic.com>
**Co-Authored-By:** Dr. Joseph Wilde, BoundState AI
