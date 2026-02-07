## TRIAGE FIX: Phase 0 Checklist

**Goal:** Make triage trustworthy enough to route 11,317 EM32 PDFs, then rerun.

**Files to modify:**
- `sandbox/scripts/triage_em32.py` (core logic)
- `sandbox/scripts/triage_em32_full.py` (corpus runner)

---

### FIX 1: Remove fitz dependency (REQUIRED)

**Current problem:** Using PyMuPDF (fitz) to render PDF first page. It's unreliable and a maintenance headache.

**Replace with:**

```python
import subprocess
import hashlib
from pathlib import Path

RENDER_CACHE_DIR = Path(r"C:\BoundState\sandbox\cache\pdf_renders")

def render_pdf_page(pdf_path: Path, page: int = 0, dpi: int = 150) -> Path:
    """Render PDF page to PNG using pdftoppm (poppler).

    Returns path to cached PNG.
    """
    RENDER_CACHE_DIR.mkdir(parents=True, exist_ok=True)

    # Cache key = file hash + page + dpi
    file_hash = hashlib.md5(pdf_path.read_bytes()).hexdigest()[:12]
    cache_key = f"{file_hash}_p{page}_d{dpi}"
    cached_png = RENDER_CACHE_DIR / f"{cache_key}.png"

    if cached_png.exists():
        return cached_png

    # Render with pdftoppm (comes with poppler)
    # -png = PNG output
    # -f/-l = first/last page (1-indexed)
    # -r = DPI
    # -singlefile = don't add page suffix
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

**Install poppler:**
```bash
# Windows (via conda or chocolatey)
conda install -c conda-forge poppler
# or
choco install poppler

# Verify
pdftoppm -v
```

**Remove all fitz imports and calls.** Search for `import fitz` and `fitz.open`.

---

### FIX 2: Convert triage to tool_use (REQUIRED)

**Current problem:** Parsing JSON from model text with string hacks and fence-stripping.

**Replace with Anthropic tool_use:**

```python
from anthropic import Anthropic
from pydantic import BaseModel
from typing import Literal

# Define the triage tool schema
TRIAGE_TOOL = {
    "name": "classify_document",
    "description": "Classify a document based on its first page",
    "input_schema": {
        "type": "object",
        "properties": {
            "doc_family": {
                "type": "string",
                "enum": [
                    "spec_sheet", "work_order", "test_report", "drawing",
                    "procedure", "form", "correspondence", "data_table",
                    "certificate", "manual", "standard",
                    "other_report", "other_memo", "other_scanned",
                    "other_image_only", "other_table_heavy", "other_handwritten"
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
                "description": "Key entities visible (part_number, revision, date, signature, etc.)"
            },
            "page_summary": {
                "type": "string",
                "description": "Brief description of what's on the page"
            }
        },
        "required": ["doc_family", "routing", "confidence", "page_summary"]
    }
}


async def triage_with_tool_use(
    image_path: Path,
    client: Anthropic,
    model: str = "claude-3-5-haiku-20241022"
) -> dict:
    """Triage document using forced tool_use - no JSON parsing."""

    import base64
    image_data = base64.standard_b64encode(image_path.read_bytes()).decode()

    response = client.messages.create(
        model=model,
        max_tokens=1024,
        tools=[TRIAGE_TOOL],
        tool_choice={"type": "tool", "name": "classify_document"},  # FORCE tool use
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
                    "text": """Classify this document's first page.

ROUTING RULES:
- extract_full: Structured docs with clear fields (specs, forms, data tables, test reports)
- extract_light: Semi-structured or text-heavy (memos, correspondence, general reports)
- manual_review: ONLY if genuinely unreadable, corrupted, or requires human judgment
- skip: Blank pages, cover sheets with no content

Be aggressive about routing to extract_light over manual_review.
If you can read it, we can extract from it."""
                }
            ]
        }]
    )

    # Extract tool use result - no JSON parsing needed
    tool_use_block = next(
        block for block in response.content
        if block.type == "tool_use"
    )

    return tool_use_block.input  # Already a dict, guaranteed by schema
```

**Key change:** `tool_choice={"type": "tool", "name": "classify_document"}` forces structured output. No more string hacks.

---

### FIX 3: Break down "other" (REQUIRED)

**Current problem:** "other" is a dumping ground that triggers manual_review.

**Add second-pass classification:**

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
                    "other_report",        # Generic report format
                    "other_memo",          # Internal memo/correspondence
                    "other_scanned",       # Scanned but readable
                    "other_handwritten",   # Handwritten content
                    "other_image_only",    # Photo/diagram, no text
                    "other_table_heavy",   # Mostly tables
                    "other_form_like",     # Form structure but unknown type
                    "other_spec_like",     # Looks like spec but uncertain
                    "other_mixed",         # Multiple content types
                    "other_corrupted"      # Actually unreadable
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

# Routing defaults for other_* subtypes
OTHER_ROUTING_DEFAULTS = {
    "other_report": "extract_light",
    "other_memo": "extract_light",
    "other_scanned": "extract_light",
    "other_handwritten": "manual_review",  # Actually needs human
    "other_image_only": "skip",
    "other_table_heavy": "extract_light",
    "other_form_like": "extract_light",
    "other_spec_like": "extract_light",
    "other_mixed": "extract_light",
    "other_corrupted": "manual_review"     # Actually needs human
}


async def triage_file(path: Path, client: Anthropic) -> dict:
    """Full triage with other-breakdown."""

    # First pass
    result = await triage_with_tool_use(render_pdf_page(path), client)

    # Second pass if needed
    if result["doc_family"].startswith("other") or result["routing"] == "manual_review":
        breakdown = await client.messages.create(
            model="claude-3-5-haiku-20241022",
            max_tokens=512,
            tools=[OTHER_BREAKDOWN_TOOL],
            tool_choice={"type": "tool", "name": "classify_other_document"},
            messages=[{
                "role": "user",
                "content": [
                    {"type": "image", "source": {...}},  # Same image
                    {"type": "text", "text": "This document wasn't clearly classified. Look closer and categorize it."}
                ]
            }]
        )

        breakdown_result = next(b for b in breakdown.content if b.type == "tool_use").input

        # Update result with breakdown
        result["doc_family"] = breakdown_result["other_subtype"]
        result["routing"] = breakdown_result["suggested_routing"]
        result["breakdown_reason"] = breakdown_result["reason"]

    return result
```

---

### FIX 4: SQLite checkpoint for resume (RECOMMENDED)

**Current problem:** `get_processed_files()` scans thousands of JSON files.

**Use SQLite:**

```python
import sqlite3
from pathlib import Path

CHECKPOINT_DB = Path(r"C:\BoundState\sandbox\output\em32_triage\checkpoint.db")

def init_checkpoint_db():
    """Initialize checkpoint database."""
    conn = sqlite3.connect(CHECKPOINT_DB)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS triage_results (
            file_hash TEXT PRIMARY KEY,
            file_path TEXT NOT NULL,
            doc_family TEXT,
            routing TEXT,
            confidence REAL,
            cost_usd REAL,
            timestamp TEXT,
            result_json TEXT
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_path ON triage_results(file_path)")
    conn.commit()
    return conn


def is_processed(conn: sqlite3.Connection, file_path: str) -> bool:
    """Check if file already processed."""
    cursor = conn.execute(
        "SELECT 1 FROM triage_results WHERE file_path = ?",
        (file_path,)
    )
    return cursor.fetchone() is not None


def save_result(conn: sqlite3.Connection, result: dict):
    """Save triage result to checkpoint DB."""
    conn.execute("""
        INSERT OR REPLACE INTO triage_results
        (file_hash, file_path, doc_family, routing, confidence, cost_usd, timestamp, result_json)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        result["file_hash"],
        result["file_path"],
        result["doc_family"],
        result["routing"],
        result["confidence"],
        result.get("cost_usd", 0),
        datetime.now().isoformat(),
        json.dumps(result)
    ))
    conn.commit()


def get_stats(conn: sqlite3.Connection) -> dict:
    """Get triage statistics."""
    stats = {}

    # By family
    cursor = conn.execute("""
        SELECT doc_family, COUNT(*) FROM triage_results GROUP BY doc_family
    """)
    stats["by_family"] = dict(cursor.fetchall())

    # By routing
    cursor = conn.execute("""
        SELECT routing, COUNT(*) FROM triage_results GROUP BY routing
    """)
    stats["by_routing"] = dict(cursor.fetchall())

    # Total
    cursor = conn.execute("SELECT COUNT(*), SUM(cost_usd) FROM triage_results")
    row = cursor.fetchone()
    stats["total_processed"] = row[0]
    stats["total_cost"] = row[1] or 0

    return stats
```

---

### RERUN SEQUENCE

After fixes are in:

```bash
# 1. Test on small batch
python sandbox/scripts/triage_em32_full.py --run --limit 50

# 2. Check stats
python sandbox/scripts/triage_em32_full.py --status

# 3. Verify "other" breakdown is working
# Should see other_report, other_memo, etc. instead of just "other"

# 4. Full PDF run
python sandbox/scripts/triage_em32_full.py --run --pdf-only

# 5. Check success criteria
#    - "other" (undifferentiated) < 20%
#    - manual_review < 15%
#    - extract_full + extract_light > 65%
```

---

### SUCCESS CRITERIA

| Metric | Target | Why |
|--------|--------|-----|
| `manual_review` | < 15% | Most docs are machine-readable |
| `other` (undifferentiated) | < 5% | Breakdown should categorize |
| `other_*` subtypes | < 20% total | Acceptable unknowns |
| `extract_full` + `extract_light` | > 65% | Ready for extraction |

---

### DON'T DO YET

- Office doc conversion (defer until PDFs done)
- TIFF support (defer)
- Schema induction (Phase 2)
- Extraction (Phase 3)

**Just fix triage. Just rerun PDFs. Get clean routing first.**
