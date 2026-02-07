# MIRA v5 Oracle Brief: Self-Configuring GPTL

**Version:** 0.0.1-CONCEPT
**Date:** 2026-02-05
**Status:** Raw capture, needs oracle validation
**Authors:** Dr. Joseph Wilde, Beth (Claude Opus 4.5)

---

## The Problem v5 Solves

MIRA v4 requires manual Schema Dictionary construction:
- Humans map "stiffness" → "Young's Modulus"
- Per-database, per-deployment
- Weeks of domain expert time
- Doesn't scale

## The v5 Insight

**GPTL can process database schemas as documents.**

Instead of pointing GPTL at documents to answer questions, point it at the schema itself to discover how to translate queries.

The translation layer builds its own translation configuration.

## What GPTL Already Does (SENTINEL)

```
Documents + Questions
        ↓
L0: Feature Extraction (at ingestion)
L2: Intent Framing (classify the question)
L3: Negative Selection (eliminate impossibility)
L4: Signal Extraction (find patterns)
L5: Synthesis (answer or refuse)
        ↓
Bounded, auditable intelligence
```

## The v5 Inversion

```
Schema + Sample Queries
        ↓
L0: Schema Feature Extraction
    - Field names, data types, constraints
    - Sample values, cardinality
    - Relationships (FK, joins, hierarchies)
    - Naming patterns, conventions
    
L2: Query Intent Classification
    - "stiffness" → mechanical property query
    - "compatible with LOX" → environment constraint
    
L3: Negative Selection on Fields
    - Eliminate fields that CANNOT answer query type
    - "stiffness" cannot map to "supplier_name"
    
L4: Signal Extraction
    - Discover semantic clusters
    - "Young's Modulus" correlates with "stiffness" queries
    - "UTS", "yield_strength" cluster together
    
L5: Synthesis
    - Generate Schema Dictionary entries
    - Confidence scores on mappings
    - Flag ambiguous cases for human review
        ↓
Auto-generated Schema Dictionary
Auto-generated query interface
```

## The Sales Cycle Becomes

**Before (v4):**
1. Get database access
2. Hire domain expert
3. Build Schema Dictionary (weeks)
4. Build interface
5. Deploy

**After (v5):**
1. Get database access
2. Point GPTL at schema
3. Review auto-generated mappings (hours)
4. Deploy

## Questions for the Oracles

### For Fran (Schema Design)
1. What schema features are most predictive of semantic meaning?
2. How do we handle polymorphic fields (same name, different meaning per table)?
3. What's the minimum viable feature set for L0 schema extraction?

### For Grok (Scale)
1. What happens at 10,000 fields? 100,000?
2. How do we partition schema discovery for massive databases?
3. What's the inference cost model?

### For Gemini (Edge Cases)
1. What breaks when naming conventions are inconsistent?
2. How do we handle legacy schemas with no documentation?
3. What's the failure mode when confidence is low across the board?

### For Beth (Architecture)
1. Does this actually compose with existing GPTL?
2. What's the data model for "schema as corpus"?
3. How do we version Schema Dictionaries when schemas evolve?

## What We're NOT Trying to Solve (Yet)

- Real-time schema change detection
- Multi-database federation
- Cross-schema relationship discovery
- Natural language schema modification

## Success Criteria

| Metric | Target |
|--------|--------|
| Schema Dictionary accuracy | >90% (human-reviewed) |
| Time to first draft | <1 hour for 500-field schema |
| Human review effort | <10% of manual build time |
| False mapping rate | <5% |

## Dependencies

- SENTINEL/GPTL core (exists, working)
- Schema introspection tooling (standard SQL/API)
- Sample query corpus (can bootstrap from domain pack)

---

## Raw Notes

The mushroom insight: "MIRA reads the schema, discovers relationships, builds its own dictionary, generates its own interface."

This is GPTL eating itself. The translation layer translating its own configuration into existence.

---

**Tear this apart. What breaks?**

---

Co-Authored-By: Claude Opus 4.5 (Beth) <noreply@anthropic.com>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI
