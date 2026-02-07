# CC Marching Orders: EM32 Triage → Extraction Pipeline

**Date:** 2025-01-04  
**Goal:** Make triage trustworthy, then extract EM32 corpus with evidence contracts  
**Discipline:** Do NOT scale until pilot gates pass

---

## Strategic Frame (Fran's Architecture)

```
TRIAGE → ROUTING → DISCOVERY → PILOT → SCALE → ANALYSIS
   ↓         ↓          ↓         ↓        ↓         ↓
 Phase 1   Phase 1   Phase 2   Phase 4  Phase 5   Phase 7
   NOW      NOW      NEXT      GATE     AFTER     LATER
```

**The Rule:** Each phase has acceptance criteria. You don't advance until they pass.

---

## Phase 0: Lock Constraints (30 min)

### Definition of Done for V3 Extractor

Before writing any code, confirm these constraints:

| Constraint | Meaning |
|------------|---------|
| Vision-first | No fitz, no pypdf, no pdfplumber. Render to images. |
| Tool-use only | No JSON parsing from text. Force `tool_choice`. |
| Evidence required | Every record needs `verbatim_snippet` + `page` + `bbox` |
| Family-specific schemas | O2 schema ≠ ITAR schema ≠ EM32 spec schema |
| Pilot before scale | 100 docs per family, gates must pass |

### Success Metrics (Post-Triage Rerun)

| Metric | Target | Current |
|--------|--------|---------|
| `manual_review` routing | < 15% | ? |
| Undifferentiated `other` | < 5% | ? |
| `extract_full` + `extract_light` | > 65% | ? |

---

## Phase 1: Fix Triage (2-4 hours)

### Files to Modify
- `sandbox/scripts/triage_em32.py`
- `sandbox/scripts/triage_em32_full.py`

### Fix 1.1: Remove fitz Dependency

**Kill all `import fitz` and `fitz.open()` calls.**

Replace with system rendering:

```python
import subprocess
import hashlib
from pathlib import Path

RENDER_CACHE_DIR = Path(r"C:\BoundState\sandbox\cache\pdf_renders")

def render_pdf_page(pdf_path: Path, page: int = 0, dpi: int = 150) -> Path:
    """Render PDF page to PNG using pdftoppm (poppler).
    
    Returns path to cached PNG. Caches by file hash so reruns are instant.
    """
    RENDER_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    
    # Cache key = file hash + page + dpi
    file_hash = hashlib.md5(pdf_path.read_bytes()).hexdigest()[:12]
    cache_key = f"{file_hash}_p{page}_d{dpi}"
    cached_png = RENDER_CACHE_DIR / f"{cache_key}.png"
    
    if cached_png.exists():
        return cached_png
    
    # pdftoppm comes with poppler
    # -png = PNG output, -f/-l = first/last page (1-indexed)
    # -r = DPI, -singlefile = don't add page suffix
    subprocess.run([
        "pdftoppm",
        "-png",
        "-f", str(page + 1),
        "-l", str(page + 1),
        "-r", str(dpi),
        "-singlefile",
        str(pdf_path),
        str(cached_png.with_suffix(""))  # pdftoppm adds .png
    ], check=True, capture_output=True)
    
    return cached_png
```

**Install poppler first:**
```bash
conda install -c conda-forge poppler
# or
choco install poppler

# Verify
pdftoppm -v
```

---

### Fix 1.2: Convert to Tool-Use

**Kill all JSON parsing from model text.** No more fence-stripping, no regex on responses.

```python
from anthropic import Anthropic
import base64

# The triage tool schema
TRIAGE_TOOL = {
    "name": "classify_document",
    "description": "Classify a document based on its first page",
    "input_schema": {
        "type": "object",
        "properties": {
            "doc_family": {
                "type": "string",
                "enum": [
                    # EM32-specific families
                    "spec_sheet",
                    "work_order",
                    "test_report",
                    "drawing",
                    "procedure",
                    "form",
                    "correspondence",
                    "data_table",
                    "certificate",
                    "manual",
                    "standard",
                    # Other subtypes (from breakdown)
                    "other_report",
                    "other_memo",
                    "other_scanned",
                    "other_handwritten",
                    "other_image_only",
                    "other_table_heavy",
                    "other_form_like",
                    "other_mixed"
                ],
                "description": "Document family/type"
            },
            "routing": {
                "type": "string",
                "enum": ["extract_full", "extract_light", "manual_review", "skip"],
                "description": "Processing route"
            },
            "confidence": {
                "type": "number",
                "minimum": 0.0,
                "maximum": 1.0,
                "description": "Classification confidence"
            },
            "entities_spotted": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Key entities visible: part_number, revision, date, signature, torque_spec, material, etc."
            },
            "page_summary": {
                "type": "string",
                "description": "Brief description of what's on the page"
            }
        },
        "required": ["doc_family", "routing", "confidence", "page_summary"]
    }
}


def triage_document(image_path: Path, client: Anthropic) -> dict:
    """Triage document using forced tool_use. No JSON parsing needed."""
    
    image_data = base64.standard_b64encode(image_path.read_bytes()).decode()
    
    response = client.messages.create(
        model="claude-3-5-haiku-20241022",
        max_tokens=1024,
        tools=[TRIAGE_TOOL],
        tool_choice={"type": "tool", "name": "classify_document"},  # FORCE IT
        messages=[{
            "role": "user",
            "content": [
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": "image/png",
                        "data": image_data
                    }
                },
                {
                    "type": "text",
                    "text": """Classify this document's first page for the EM32 corpus.

ROUTING RULES:
- extract_full: Structured docs with clear fields (specs, forms, data tables, test reports, drawings)
- extract_light: Semi-structured or text-heavy (memos, correspondence, general reports)
- manual_review: ONLY if genuinely unreadable, corrupted, or requires human judgment
- skip: Blank pages, cover sheets with no data content

Be aggressive about routing to extract_light over manual_review.
If you can read it, we can extract from it.

ENTITY SPOTTING:
Look for: part_number, revision, date, signature, torque_spec, material, 
test_result, drawing_number, work_order_number, approval, specification_ref"""
                }
            ]
        }]
    )
    
    # Extract tool result - already a dict, guaranteed by schema
    tool_block = next(b for b in response.content if b.type == "tool_use")
    return tool_block.input
```

**Key:** `tool_choice={"type": "tool", "name": "classify_document"}` forces structured output.

---

### Fix 1.3: Break Down "other"

Add second-pass classification when first pass returns `other*` or `manual_review`:

```python
OTHER_BREAKDOWN_TOOL = {
    "name": "classify_other_document",
    "description": "Further classify documents that didn't fit main categories",
    "input_schema": {
        "type": "object",
        "properties": {
            "other_subtype": {
                "type": "string",
                "enum": [
                    "other_report",
                    "other_memo",
                    "other_scanned",
                    "other_handwritten",
                    "other_image_only",
                    "other_table_heavy",
                    "other_form_like",
                    "other_spec_like",
                    "other_mixed",
                    "other_corrupted"
                ]
            },
            "readable": {
                "type": "boolean",
                "description": "Can meaningful text be extracted?"
            },
            "suggested_routing": {
                "type": "string",
                "enum": ["extract_light", "manual_review", "skip"]
            },
            "reason": {
                "type": "string",
                "description": "Why this classification"
            }
        },
        "required": ["other_subtype", "readable", "suggested_routing", "reason"]
    }
}

# Default routing for subtypes - most go to extract_light
OTHER_ROUTING = {
    "other_report": "extract_light",
    "other_memo": "extract_light",
    "other_scanned": "extract_light",
    "other_table_heavy": "extract_light",
    "other_form_like": "extract_light",
    "other_spec_like": "extract_light",
    "other_mixed": "extract_light",
    "other_handwritten": "manual_review",  # Actually needs human
    "other_image_only": "skip",
    "other_corrupted": "manual_review"
}


def triage_with_breakdown(pdf_path: Path, client: Anthropic) -> dict:
    """Full triage with other-breakdown second pass."""
    
    # Render first page
    image_path = render_pdf_page(pdf_path)
    
    # First pass
    result = triage_document(image_path, client)
    result["file_path"] = str(pdf_path)
    result["file_hash"] = hashlib.md5(pdf_path.read_bytes()).hexdigest()[:12]
    
    # Second pass if needed
    if result["doc_family"].startswith("other") or result["routing"] == "manual_review":
        image_data = base64.standard_b64encode(image_path.read_bytes()).decode()
        
        breakdown_response = client.messages.create(
            model="claude-3-5-haiku-20241022",
            max_tokens=512,
            tools=[OTHER_BREAKDOWN_TOOL],
            tool_choice={"type": "tool", "name": "classify_other_document"},
            messages=[{
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {"type": "base64", "media_type": "image/png", "data": image_data}
                    },
                    {
                        "type": "text",
                        "text": """This document wasn't clearly classified in first pass.
Look closer. Is it readable? What subtype is it?
Be aggressive - if there's ANY extractable text, mark readable=true."""
                    }
                ]
            }]
        )
        
        breakdown = next(b for b in breakdown_response.content if b.type == "tool_use").input
        
        # Update result
        result["doc_family"] = breakdown["other_subtype"]
        result["routing"] = breakdown["suggested_routing"]
        result["breakdown_reason"] = breakdown["reason"]
        result["readable"] = breakdown["readable"]
    
    return result
```

---

### Fix 1.4: SQLite Checkpoint

**Kill the JSON file scanning.** Use SQLite for resume:

```python
import sqlite3
from datetime import datetime
import json

CHECKPOINT_DB = Path(r"C:\BoundState\sandbox\output\em32_triage\checkpoint.db")


def init_db() -> sqlite3.Connection:
    """Initialize checkpoint database."""
    conn = sqlite3.connect(CHECKPOINT_DB)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS triage_results (
            file_hash TEXT PRIMARY KEY,
            file_path TEXT NOT NULL,
            doc_family TEXT,
            routing TEXT,
            confidence REAL,
            entities TEXT,
            page_summary TEXT,
            breakdown_reason TEXT,
            input_tokens INTEGER,
            output_tokens INTEGER,
            cost_usd REAL,
            timestamp TEXT,
            result_json TEXT
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_path ON triage_results(file_path)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_family ON triage_results(doc_family)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_routing ON triage_results(routing)")
    conn.commit()
    return conn


def is_processed(conn: sqlite3.Connection, file_path: str) -> bool:
    """Check if file already triaged."""
    cur = conn.execute("SELECT 1 FROM triage_results WHERE file_path = ?", (file_path,))
    return cur.fetchone() is not None


def save_result(conn: sqlite3.Connection, result: dict, usage: dict):
    """Save triage result."""
    conn.execute("""
        INSERT OR REPLACE INTO triage_results 
        (file_hash, file_path, doc_family, routing, confidence, entities, 
         page_summary, breakdown_reason, input_tokens, output_tokens, cost_usd, timestamp, result_json)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        result["file_hash"],
        result["file_path"],
        result["doc_family"],
        result["routing"],
        result["confidence"],
        json.dumps(result.get("entities_spotted", [])),
        result.get("page_summary", ""),
        result.get("breakdown_reason"),
        usage.get("input_tokens", 0),
        usage.get("output_tokens", 0),
        usage.get("cost_usd", 0),
        datetime.now().isoformat(),
        json.dumps(result)
    ))
    conn.commit()


def get_stats(conn: sqlite3.Connection) -> dict:
    """Get triage statistics for acceptance criteria."""
    stats = {}
    
    # Total
    cur = conn.execute("SELECT COUNT(*) FROM triage_results")
    stats["total"] = cur.fetchone()[0]
    
    # By routing
    cur = conn.execute("""
        SELECT routing, COUNT(*), ROUND(COUNT(*) * 100.0 / (SELECT COUNT(*) FROM triage_results), 1)
        FROM triage_results GROUP BY routing
    """)
    stats["by_routing"] = {row[0]: {"count": row[1], "pct": row[2]} for row in cur.fetchall()}
    
    # By family
    cur = conn.execute("""
        SELECT doc_family, COUNT(*), ROUND(COUNT(*) * 100.0 / (SELECT COUNT(*) FROM triage_results), 1)
        FROM triage_results GROUP BY doc_family ORDER BY COUNT(*) DESC
    """)
    stats["by_family"] = {row[0]: {"count": row[1], "pct": row[2]} for row in cur.fetchall()}
    
    # Undifferentiated "other" (not other_*)
    cur = conn.execute("""
        SELECT COUNT(*) FROM triage_results 
        WHERE doc_family = 'other' OR doc_family IS NULL
    """)
    stats["undifferentiated_other"] = cur.fetchone()[0]
    
    # Cost
    cur = conn.execute("SELECT SUM(cost_usd) FROM triage_results")
    stats["total_cost_usd"] = cur.fetchone()[0] or 0
    
    return stats


def print_acceptance_check(conn: sqlite3.Connection):
    """Print acceptance criteria check."""
    stats = get_stats(conn)
    
    print("\n" + "="*60)
    print("TRIAGE ACCEPTANCE CRITERIA CHECK")
    print("="*60)
    
    total = stats["total"]
    if total == 0:
        print("No results yet.")
        return
    
    # manual_review < 15%
    mr = stats["by_routing"].get("manual_review", {"pct": 0})["pct"]
    mr_pass = "✓" if mr < 15 else "✗"
    print(f"\n{mr_pass} manual_review: {mr}% (target: < 15%)")
    
    # undifferentiated other < 5%
    other_pct = (stats["undifferentiated_other"] / total) * 100
    other_pass = "✓" if other_pct < 5 else "✗"
    print(f"{other_pass} undifferentiated 'other': {other_pct:.1f}% (target: < 5%)")
    
    # extract_full + extract_light > 65%
    ef = stats["by_routing"].get("extract_full", {"pct": 0})["pct"]
    el = stats["by_routing"].get("extract_light", {"pct": 0})["pct"]
    extract_total = ef + el
    extract_pass = "✓" if extract_total > 65 else "✗"
    print(f"{extract_pass} extractable (full+light): {extract_total}% (target: > 65%)")
    
    print(f"\nTotal processed: {total}")
    print(f"Total cost: ${stats['total_cost_usd']:.2f}")
    
    print("\nTop families:")
    for family, data in list(stats["by_family"].items())[:10]:
        print(f"  {family}: {data['count']} ({data['pct']}%)")
    
    print("="*60)
```

---

## Phase 1 Acceptance Criteria

Before moving to Phase 2, these must pass:

```bash
# Run on 50-doc test batch
python triage_em32_full.py --run --limit 50

# Check acceptance
python triage_em32_full.py --status
```

| Criterion | Target | Pass? |
|-----------|--------|-------|
| No crashes on diverse formats | 0 errors | |
| `manual_review` | < 15% | |
| Undifferentiated `other` | < 5% | |
| `extract_full` + `extract_light` | > 65% | |
| Every result has `file_hash` | 100% | |

**If any fail:** Fix before proceeding. Do not scale broken triage.

---

## Phase 2: Discovery Per Family (After Triage Passes)

### Goal
For each doc_family with > 100 docs, discover what fields repeat.

### Stratified Sampler

```python
def sample_family(conn: sqlite3.Connection, family: str, n: int = 20) -> list[Path]:
    """Get stratified sample from a family for schema discovery."""
    cur = conn.execute("""
        SELECT file_path FROM triage_results 
        WHERE doc_family = ? AND routing IN ('extract_full', 'extract_light')
        ORDER BY RANDOM() LIMIT ?
    """, (family, n))
    return [Path(row[0]) for row in cur.fetchall()]
```

### Discovery Tool Schema

```python
DISCOVERY_TOOL = {
    "name": "discover_schema",
    "description": "Discover what record types and fields exist in this document",
    "input_schema": {
        "type": "object",
        "properties": {
            "record_types": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "description": {"type": "string"},
                        "fields": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "name": {"type": "string"},
                                    "type": {"type": "string", "enum": ["string", "number", "date", "boolean", "list"]},
                                    "description": {"type": "string"},
                                    "example": {"type": "string"}
                                },
                                "required": ["name", "type"]
                            }
                        }
                    },
                    "required": ["name", "fields"]
                }
            },
            "evidence": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "record_type": {"type": "string"},
                        "field": {"type": "string"},
                        "verbatim_snippet": {"type": "string"},
                        "page": {"type": "integer"}
                    },
                    "required": ["record_type", "field", "verbatim_snippet", "page"]
                }
            }
        },
        "required": ["record_types", "evidence"]
    }
}
```

### Aggregation Rules

After running discovery on 20 docs per family:

1. **Keep record types** that appear in ≥ 40% of docs
2. **Keep fields** that appear in ≥ 50% of docs *within that record type*
3. **Drop boilerplate** fields unless they form coherent records
4. **Add `extras` bucket** for low-frequency fields

### Acceptance Criteria

| Criterion | Target |
|-----------|--------|
| Schemas look like "questions" not "metadata" | Subjective human review |
| Evidence snippets present | 100% |
| Evidence snippets plausible (not garbage) | > 90% |

---

## Phase 3: Page Chunking (After Discovery)

**One approach. Commit to it:**

```python
def render_all_pages(pdf_path: Path, dpi: int = 150) -> list[Path]:
    """Render all pages of PDF to cached images."""
    file_hash = hashlib.md5(pdf_path.read_bytes()).hexdigest()[:12]
    cache_dir = RENDER_CACHE_DIR / file_hash
    
    if cache_dir.exists() and list(cache_dir.glob("*.png")):
        return sorted(cache_dir.glob("*.png"))
    
    cache_dir.mkdir(parents=True, exist_ok=True)
    
    # Render all pages
    subprocess.run([
        "pdftoppm",
        "-png",
        "-r", str(dpi),
        str(pdf_path),
        str(cache_dir / "page")
    ], check=True, capture_output=True)
    
    return sorted(cache_dir.glob("*.png"))


def chunk_pages(pages: list[Path], batch_size: int = 5, overlap: int = 1) -> list[list[Path]]:
    """Chunk pages into batches with overlap."""
    if len(pages) <= batch_size:
        return [pages]
    
    chunks = []
    i = 0
    while i < len(pages):
        chunk = pages[i:i + batch_size]
        chunks.append(chunk)
        i += batch_size - overlap
    
    return chunks
```

### Acceptance Criteria

| Criterion | Target |
|-----------|--------|
| 200-page PDF chunks reliably | No crashes |
| Same PDF doesn't re-render | Cache hit |
| Extraction doesn't truncate | Full content captured |

---

## Phase 4: Pilot Extraction Gate (CRITICAL)

**DO NOT SKIP THIS PHASE.**

### Pilot Parameters
- 100 docs per top 2-3 families
- Full evidence contract enforced

### Evidence Contract (Required Per Record)

```python
EXTRACTION_TOOL = {
    "name": "extract_records",
    "input_schema": {
        "type": "object",
        "properties": {
            "records": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "record_type": {"type": "string"},
                        "fields": {"type": "object"},
                        # REQUIRED EVIDENCE
                        "verbatim_snippet": {
                            "type": "string",
                            "description": "Exact quote from document supporting this record"
                        },
                        "page": {"type": "integer"},
                        "bbox": {
                            "type": "object",
                            "properties": {
                                "x": {"type": "number"},
                                "y": {"type": "number"},
                                "width": {"type": "number"},
                                "height": {"type": "number"}
                            }
                        },
                        "evidence_type": {
                            "type": "string",
                            "enum": ["direct_quote", "inferred", "computed"]
                        },
                        "confidence": {"type": "number", "minimum": 0, "maximum": 1}
                    },
                    "required": ["record_type", "fields", "verbatim_snippet", "page", "evidence_type", "confidence"]
                }
            },
            "extras": {
                "type": "object",
                "description": "Low-frequency fields that don't fit schema"
            }
        },
        "required": ["records"]
    }
}
```

### Hard Gates (Must Pass Before Phase 5)

| Metric | Target | Fail Action |
|--------|--------|-------------|
| `evidence_present_rate` | 99-100% | Fix extraction prompt |
| `non_empty_snippet_rate` | ≥ 95% | Fix evidence contract |
| `record_yield` | Sane (not 0, not 10K junk) | Adjust schema |
| `error_rate` | < 5% | Fix chunking/timeout |

```python
def check_pilot_gates(results: list[dict]) -> bool:
    """Check if pilot gates pass."""
    total_records = sum(len(r.get("records", [])) for r in results)
    
    if total_records == 0:
        print("FAIL: No records extracted")
        return False
    
    evidence_present = sum(
        1 for r in results 
        for rec in r.get("records", []) 
        if rec.get("verbatim_snippet")
    )
    evidence_rate = evidence_present / total_records
    
    non_empty = sum(
        1 for r in results
        for rec in r.get("records", [])
        if rec.get("verbatim_snippet", "").strip()
    )
    non_empty_rate = non_empty / total_records
    
    error_count = sum(1 for r in results if r.get("error"))
    error_rate = error_count / len(results)
    
    print(f"Evidence present: {evidence_rate:.1%} (target: ≥99%)")
    print(f"Non-empty snippets: {non_empty_rate:.1%} (target: ≥95%)")
    print(f"Error rate: {error_rate:.1%} (target: <5%)")
    print(f"Total records: {total_records}")
    
    return (
        evidence_rate >= 0.99 and
        non_empty_rate >= 0.95 and
        error_rate < 0.05 and
        total_records > 0
    )
```

---

## Phase 5: Scale Extraction (Only After Gates Pass)

- Full run per family
- Checkpoint/resume with SQLite
- Output: `doc_id`, `family_id`, `schema_version`, `records`, `evidence`, `extras`, `usage`

---

## Phase 6: Drift Detection (Quick Win)

Monitor per-family:
- % docs routed to "unknown"
- Extraction success rate
- Core-field coverage (rolling window)

Triggers:
- Unknown grows > X%
- Core-field coverage drops < Y%
- Success rate drops < Z%

---

## Phase 7: Pattern Analysis (Later)

- Embeddings / FFT / fingerprints / HDBSCAN on extracted records
- Typology reports
- Cross-domain resonance

**This is downstream. Don't touch until Phase 5 complete.**

---

## Task Execution Order

```
Week 1:
├── Day 1-2: Phase 1 (triage fixes)
│   ├── Remove fitz → pdftoppm
│   ├── Convert to tool_use
│   ├── Add other breakdown
│   └── SQLite checkpoint
├── Day 2-3: Rerun triage on 11,317 PDFs
│   └── Check acceptance criteria
├── Day 3-4: Phase 2 (discovery)
│   └── Sample → discover → aggregate → lock schemas

Week 2:
├── Day 1: Phase 3 (chunking)
├── Day 2-3: Phase 4 (pilot extraction)
│   └── MUST PASS GATES
├── Day 3-5: Phase 5 (scale)
│   └── Full extraction with checkpoint/resume
```

---

## Questions for Dude Before Starting

1. Current EM32 family labels from existing triage? (So I can tailor sampler)
2. Which 2-3 families have highest doc count? (Priority for pilot)
3. Existing schema definitions to compare against? (Baseline for discovery)

---

## The Moat Reminder

**Competitors:** PDF → regex/OCR → garbage

**BoundState:** PDF → vision triage → family routing → schema induction → tool-use extraction → evidence-grounded JSON → rules.json → Authority Packs

Nobody else is doing systematic, evidence-first corpus translation with tool-use guarantees.

**That's the company.**
