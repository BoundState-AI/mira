# GPTL - Grounded Precision Translation Layer

**SENTINEL is GPTL deployed as a service.**

A negative selection intelligence engine that:

- Accepts documents + questions
- Eliminates the 80% that CANNOT be relevant
- Produces bounded, auditable intelligence
- Refuses deterministically when evidence is insufficient
- Shows its work completely

## Philosophy

> "We don't retrieve truth. We eliminate impossibility—then show our work."

## Quick Start

```bash
# Install with CPU support
pip install -e ".[cpu]"

# Run the API
uvicorn gptl.api.main:app --reload
```

## API Endpoints

- `POST /api/v1/query` - Execute a SENTINEL query
- `GET /api/v1/audit/{trace_id}` - Retrieve audit trail
- `GET /api/v1/domains` - List available domain packs
- `GET /health` - Liveness check

## Architecture

```
GPTL Pipeline
│
├── L0: Feature Extraction (pre-computed at ingestion)
├── L2: Intent Framing
├── L3: Negative Selection (the core)
├── L4: Signal Extraction
└── L5: Synthesis (or refusal)
```

## License

Apache 2.0

---

**Co-Authored-By:** Claude Opus 4.5 <noreply@anthropic.com>
**Co-Authored-By:** Dr. Joseph Wilde, BoundState AI
