# CLAUDE.md — boundstate_mira

## What This Repo Is

The primary BoundState production codebase. Contains:

- **MIRA platform** (`mira/`, `mira_v4/`, `frontend/`) — 14-engine aerospace M&P compliance platform. 431 files, 151K+ lines. React/TypeScript frontend, FastAPI/Python backend.
- **GPTL/SENTINEL** (`sentinel-main/gptl/`) — Grounded Precision Translation Layer. 6-layer negative selection intelligence engine. The core IP.
- **Data Laundering Pipeline** (`data_laundering/`) — 4-layer query pipeline: sanitize → reason → validate → present. Domain-agnostic via DomainPack.
- **Athena** (`athena/`) — 123 files, 30K+ lines. Document extraction engine (PDF/DOCX/image → structured content).
- **Intelligence Compiler** (`unified/`) — NEW. Unifies FORGE + GPTL into single entry point. See `unified/CLAUDE.md` for IC-specific instructions.

## Architecture Invariants

- **No MAPTIS data in production.** PostgreSQL on E: drive is validation oracle only.
- **All engines run on public standards** — NASA-STD-6001B, 6016C, MMPDS, CMH-17, ASTM.
- **Pydantic models with `extra="forbid"`** on all API contracts and pipeline models.
- **`__safety_critical__: bool = True`** header on modules that touch compliance decisions.
- **Four-level fallback ladder** — frontend declares competence, backend enforces.

## Key Directories

```
boundstate_mira/
├── mira/                    # MIRA engines (H2, galvanic, flammability, MUA, etc.)
│   ├── api/                 # FastAPI app + routers
│   ├── bsmh/                # Bounded Smart Materials Helper (chat layer)
│   ├── h2/                  # Hydrogen compatibility engine
│   ├── mua/                 # MUA writer (classifier, synthesis, precedent)
│   ├── providers/           # Bedrock, local LLM providers
│   └── utils/               # Config, JSON extraction
├── mira_v4/                 # v4 models and schemas
├── frontend/                # React/TypeScript/Tailwind frontend
├── athena/                  # Document extraction pipeline
│   ├── extraction/          # Vision, OCR, standards extractors
│   ├── chunking/            # Content chunking
│   ├── indexing/             # FAISS indexing
│   └── parsers/             # Format-specific parsers
├── sentinel-main/           # GPTL standalone
│   └── gptl/                # Core GPTL engine (see sentinel-main CLAUDE.md)
├── data_laundering/         # 4-layer query pipeline
├── unified/                 # Intelligence Compiler (IC) — NEW
├── core/                    # Shared core (evidence, infra, models, query, RAG)
├── scripts/                 # One-off scripts, importers, evaluators
├── tests/                   # Test suite
├── services/                # Service layer
└── docs/                    # Documentation
```

## Database Connections

| Database | Port | Purpose |
|----------|------|---------|
| MIRA Materials | 55433 | Materials properties, test data, heritage |
| IC Canonical Store | 55434 | Intelligence Compiler provenance graph |
| PostgreSQL (system) | 5432 | General PostgreSQL |

## Running Locally

```bash
# Python
PYTHON=/c/Users/Jnwil/.conda/envs/boundstate-intent/python.exe

# API server
$PYTHON -m uvicorn mira.api.app:app --reload --port 8000

# Tests
$PYTHON -m pytest tests/ -v --tb=short

# Specific test
$PYTHON -m pytest tests/mira/test_h2_engine.py -v
```

## Import Rules

- `mira/` may import from `core/`, `data_laundering/`, `athena/`
- `unified/` may import from `sentinel-main/gptl/` and `boundstate_forge/` (cross-repo, via direct import for now)
- `unified/` MUST NOT import from `mira/` application logic — strict decoupling for future extraction
- `sentinel-main/gptl/` is self-contained — no imports from `mira/`
- `data_laundering/` is self-contained — no imports from `mira/` application logic

## Before You Build

1. Read `REPO_BOUNDARIES.md` — canonical ownership rules
2. Check which directory owns the feature you're building
3. If touching `unified/`, read `unified/CLAUDE.md` for IC-specific rules
4. If touching `sentinel-main/gptl/`, read the GPTL schema carefully — 59 Pydantic models with `extra="forbid"`
5. Run the relevant test suite before and after changes

## MUA Writer Authority Boundary

If you are working on MUA-related code, this is non-negotiable:

> The system SHALL NOT infer new engineering allowables, approve alternative design-value methods, or convert precedent into acceptance authority. All outputs are draft artifacts pending responsible NASA M&P review, Program/Project approval, or any approval path defined by the governing M&P Plan and NASA-STD-6016C.

This must appear in: bouncer rules, system prompt, response footer. Hardcoded, not configurable.
