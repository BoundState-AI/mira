# BoundState ATHENA Table Extraction Architecture

**Version:** 1.5.0  
**Date:** 2025-12-24  
**Authors:** Dr. Joseph Wilde (CEO), Claude Opus 4.5, Grok 4.0, Fran (GPT 5.1), Gemini 2.0  
**Status:** FINAL - IMPLEMENTATION READY  
**Codename:** ATHENA (Automated Table Harvesting & ENtity Analysis)

---

## Changelog

### v1.5.0 (Current)
| Change | Source | Resolution |
|--------|--------|------------|
| Rename `mira/` → `boundstate/` | Dr. Wilde | Correct branding |
| Add `core/coords.py` | Fran | PDF↔pixel transforms centralized |
| Split `core/models.py` → `core/models/` | Fran/Grok | cell.py, grid.py, source.py, result.py |
| Split `extraction/` | Fran | detector.py + transcriber.py separation |
| Split `semantic/rules.py` → `semantic/rules/` | Fran | base.py, h2.py, o2.py, composition.py |
| Add `interpreters/models/` | Grok | Record models separate from interpreter logic |
| Split `validation/gates.py` → `validation/gates/` | Fran | extraction.py, h2.py, o2.py |
| Add `validation/models.py` | Fran | ValidationResult, GateProtocol |
| Add `debug/` module | Fran/Grok | Standard place for --debug artifacts |
| Add `tests/` structure | Grok | Safety-critical code needs tests from day 1 |

### v1.4.0
| Issue | Source | Resolution |
|-------|--------|------------|
| Coordinate system inconsistent | Fran | NEW: `BBox` model with explicit `coord_space`, `origin`, `dpi` |
| Unit detection misfires (K=Kelvin vs Potassium) | Fran | Unit detection is now TAG-AWARE, only runs for applicable tags |
| RANGE_PATTERN regex bug ("to" in char class) | Fran | Fixed: proper alternation `(?:-\|–\|—\|\bto\b)` |
| LogicalTable docstring contradicts code | Fran | Fixed docstring, added `get_all_rows_with_headers()` |
| "149 tables" invalid success metric | Fran | Replaced with ground-truth hash-linked baselines |
| extraction_confidence fails with spans | Fran | Confidence now uses structural coverage, not count match |
| mapping_hash missing unit/signature | Fran | Now includes `tag + detected_unit + header_signature` |
| get_cell is O(n) | Fran | Added `_cell_index` built on init |
| Stitcher needs more signals | Fran | Added bbox position + table number continuity |
| MaterialResolver classification unclear | Fran | Explicit: "canonicalization only, not inference" |

### v1.3.0
| Issue | Source | Resolution |
|-------|--------|------------|
| "Vision-only" but uses pdfplumber | Fran | Renamed: "pdfplumber-assisted detection + vision transcription" |
| Derived fields in ontology | Fran | REMOVED `H2_EMBRITTLEMENT_INDEX`, `NTS_RATIO` from tags |
| Multi-row header flattening | Fran | Added header signature construction |
| String heuristics policy unclear | Fran | Added explicit allowed/forbidden policy |
| Cost numbers inconsistent | Fran | Explicit assumptions documented |
| No "zero tables" hard fail | Fran | Added `ExtractionGate` |
| Cell-level bbox missing | Fran | Added `cell_bbox` to `TableCell` |
| Confidence contract undefined | Fran | Defined computation rules |
| No mapping hash for regression | Fran | Added `mapping_hash` to `SemanticTable` |
| Multi-page tables not handled | Gemini | Added Layer 1.5: Table Stitcher |
| Unit normalization missing | Gemini | Added to Layer 2 |
| Dirty numeric data unhandled | Gemini | Added `NumericValue` model |
| Material resolver too late | Gemini | Moved to Layer 2 |

---

## Executive Summary

ATHENA is BoundState's general-purpose PDF table extraction platform. It transforms
unstructured PDF tables into typed, validated, searchable records for the H2 and O2
Knowledge Twins—and any future domain.

**Core Philosophy:**
```
Extract faithfully → Stitch continuations → Map semantically → 
Normalize units → Interpret deterministically → Fail loudly
```

**Non-Negotiable Principles:**
1. **Lossless extraction** - Grid structure, never dict-by-header
2. **Evidence-first** - Every value traces to source cell, page, document
3. **Deterministic interpretation** - Code calculates ratios, not LLM
4. **Hard fail on missing safety signal** - 0 embrittlement records = RUN FAILURE
5. **No hardcoded material logic** - Properties drive decisions, never names
6. **Unit safety** - All values normalized to SI before calculation
7. **Coordinate clarity** - All bboxes have explicit space, origin, and DPI

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────┐
│                           PDF DOCUMENTS                                 │
│        (Sandia H2 BOK, NASA O2 Standards, Red River Reports)           │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  LAYER 1: EXTRACTION                                                    │
│  ┌───────────────────────────────────────────────────────────────────┐ │
│  │  Detection: pdfplumber.find_tables() [free, fast]                 │ │
│  │  Fallback:  Vision table detection [if pdfplumber returns 0]      │ │
│  │  Transcription: Haiku vision reads cropped regions                │ │
│  │  Output: TableGrid[] (lossless cell array)                        │ │
│  └───────────────────────────────────────────────────────────────────┘ │
│                                                            Cost: $0.24 │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  LAYER 1.5: TABLE STITCHER                                              │
│  ┌───────────────────────────────────────────────────────────────────┐ │
│  │  Detects multi-page table continuations                           │ │
│  │  Merges "Table 3" + "Table 3 (cont.)" into single LogicalTable    │ │
│  │  Uses: context_text, header matching, page sequence, bbox position│ │
│  └───────────────────────────────────────────────────────────────────┘ │
│                                                            Cost: $0.00 │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  LAYER 2: SEMANTIC MAPPING                                              │
│  ┌───────────────────────────────────────────────────────────────────┐ │
│  │  2a. Column Mapping: headers → ontology tags (rules-first)        │ │
│  │  2b. Unit Detection: "MPa", "ksi", "K", "°C" → detected_unit      │ │
│  │  2c. Value Cleaning: "720†" → NumericValue(720.0, footnotes=["†"])│ │
│  │  2d. Material Resolution: "304L" → UNS S30403 (canonical key)     │ │
│  └───────────────────────────────────────────────────────────────────┘ │
│                                                            Cost: $0.01 │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  LAYER 3: DOMAIN INTERPRETERS                                           │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐        │
│  │  H2Interpreter  │  │  O2Interpreter  │  │  Composition    │  ...   │
│  │                 │  │                 │  │  Interpreter    │        │
│  │  Pure code      │  │  Pure code      │  │  Pure code      │        │
│  │  SI units only  │  │  SI units only  │  │                 │        │
│  │  Calculates:    │  │  Extracts:      │  │  Normalizes:    │        │
│  │  • HEE index    │  │  • AIT (K)      │  │  • wt% to       │        │
│  │  • NTS ratio    │  │  • Ratings      │  │    canonical    │        │
│  └─────────────────┘  └─────────────────┘  └─────────────────┘        │
│                                                            Cost: $0.00 │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  LAYER 4: VALIDATION GATES                          NON-NEGOTIABLE     │
│  ┌───────────────────────────────────────────────────────────────────┐ │
│  │  ExtractionGate: tables_extracted == 0 → HARD FAIL                │ │
│  │  H2Gate: embrittlement_index OR nts_ratio required → HARD FAIL    │ │
│  │  O2Gate: ait_kelvin OR flammability_rating required → HARD FAIL   │ │
│  └───────────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  LAYER 5: KNOWLEDGE TWIN INGESTION                    (REUSE EXISTING) │
│  ┌───────────────────────────────────────────────────────────────────┐ │
│  │  TwinIndexBuilder, FAISS indices, CompatibilityRecord model       │ │
│  │  VerdictEngine and scoring profiles                               │ │
│  └───────────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────────┘

TOTAL COST PER DOCUMENT: ~$0.25
```

---

## Policy Statements

### Detection Strategy

> **"pdfplumber-assisted detection + vision transcription"**

```
Detection Pipeline:
1. pdfplumber.find_tables() → bounding boxes in PDF points [FREE, FAST]
2. IF find_tables() returns 0 AND document expected to have tables:
   a. Render full page at 150 DPI
   b. Vision prompt: "Find all tables, return their bboxes"
   c. Parse bboxes (in page pixels), convert to PDF points
3. For each detected region:
   a. Convert bbox to render coordinates
   b. Crop and render at 150 DPI
   c. Vision transcription → TableGrid
```

### String Heuristics Policy

```
STRING MATCHING POLICY:

✅ ALLOWED for:
   - Test environment normalization ("he" → helium, "h2" → hydrogen)
   - Reference parsing ("[15]", "†", "Ref. 3")
   - Unit extraction from headers ("MPa", "%", "(K)", "(°C)")
   - Footnote symbol detection ("†", "‡", "*")
   - Table continuation detection ("(cont.)", "(continued)")
   - Numeric value parsing (ranges, inequalities, scientific notation)
   - Material alias → canonical key (CANONICALIZATION ONLY)

❌ FORBIDDEN for:
   - Material name → compatibility class inference
   - Material substitution/recommendation logic
   - Any domain decision that should derive from properties
   - Hardcoded material boosting/penalizing
```

### Coordinate System Contract

```
ALL BOUNDING BOXES USE THE BBox MODEL.

Never pass raw tuples. Always specify:
- coord_space: "pdf_points" or "page_pixels"
- origin: "bottom_left" (PDF standard) or "top_left" (image standard)
- dpi: Required if coord_space == "page_pixels"

Conversion functions in core/coords.py:
- pdf_points_to_pixels(bbox, page_height, dpi) → pixels, top_left origin
- pixels_to_pdf_points(bbox, page_height, dpi) → points, bottom_left origin
- store_both_bboxes() → keeps original + converted for provenance
```

### Unit Detection Policy

```
UNIT DETECTION IS TAG-AWARE.

Order of operations:
1. Map column to SemanticTag FIRST
2. Check if tag can have units (UNIT_APPLICABLE_TAGS set)
3. Only THEN run unit pattern matching

Tags that CAN have units:
- mechanical.* (MPa, ksi, %)
- test.pressure (MPa, psi, bar)
- test.temperature (K, °C, °F)
- o2.ait (K, °C)
- h2.permeability, h2.diffusivity (various)

Tags that CANNOT have units (prevents K=Potassium bug):
- composition.* (always wt%, no unit detection needed)
- material.* (text only)
- reference.* (text only)

Pattern restrictions:
- Bare "K" or "C" only match if:
  a. Inside parentheses: "(K)", "(C)"
  b. After "Temp" or "Temperature"
  c. Tag is in UNIT_APPLICABLE_TAGS
```

### Confidence Contract

```
EXTRACTION CONFIDENCE uses structural coverage, not count matching.

Computation:
1.0  All cells have valid (r,c) within bounds
     No overlapping spans
     Spans don't exceed grid bounds
     Header row count is sensible (1-3)
     
0.8  Minor issues:
     - Some cells have null text (expected for sparse tables)
     - Row/col counts slightly off (merged cell artifacts)
     
0.5  Structural issues:
     - Missing cells in expected grid positions
     - Span overlaps detected and resolved
     
0.3  Major issues:
     - JSON required fixups (removed markdown, fixed brackets)
     - Significant gaps in coverage
     
0.0  Extraction failed (error field populated)

NOTE: row_count × col_count ≠ len(cells) is EXPECTED with merged cells.
      This is NOT a confidence penalty.
```

### Success Metrics

```
GROUND-TRUTH BASELINES are hash-linked.

For Sandia PDF (SAND2012-7321.pdf):
  pdf_hash: "sha256:abc123..."  # Actual hash of test file
  ground_truth:
    tables_found_pdfplumber: 149
    tables_found_vision: 0  # pdfplumber found all
    table_grids_transcribed: 149
    logical_tables_after_stitch: 142  # 7 multi-page tables merged
    h2_records_produced: 155
    records_with_embrittlement_index: 155

Metrics tracked per run:
- tables_found_pdfplumber
- tables_found_vision_fallback
- table_grids_transcribed
- logical_tables_after_stitch
- domain_records_produced
- validation_gate_passed: bool
```

### Cost Model

```
COST MODEL (Haiku claude-haiku-4-5-20251001):
  Input:  $0.80 / 1M tokens
  Output: $4.00 / 1M tokens

BASELINE DOCUMENT (Sandia H2 reference, 292 pages):
  - Tables detected: ~150
  - Avg image tokens: ~1000/table (150 DPI, ~400×600px crop)
  - Avg output tokens: ~200/table

LAYER 1 (Extraction):
  Input:  150 × 1000 = 150K tokens → $0.12
  Output: 150 × 200 = 30K tokens   → $0.12
  Subtotal: $0.24

LAYER 2 (Semantic Mapping, rules-first):
  ~10% need LLM fallback → 15 calls × 500 tokens = 7.5K input
  Output: 15 × 100 = 1.5K tokens
  Subtotal: $0.01

TOTAL: ~$0.25/document

VISION FALLBACK (if pdfplumber misses all tables):
  Add ~$0.05/page for table detection pass
  Triggered rarely on well-formed PDFs
```

---

## Core Models

### BBox Model

```python
from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, model_validator

__all__ = ["CoordSpace", "Origin", "BBox"]


class CoordSpace(str, Enum):
    """Coordinate space for bounding boxes."""
    PDF_POINTS = "pdf_points"      # 72 points per inch, standard PDF
    PAGE_PIXELS = "page_pixels"    # Rendered image pixels


class Origin(str, Enum):
    """Origin point for coordinate system."""
    BOTTOM_LEFT = "bottom_left"    # PDF standard (y increases upward)
    TOP_LEFT = "top_left"          # Image standard (y increases downward)


class BBox(BaseModel):
    """
    Bounding box with explicit coordinate system.
    
    NEVER pass raw tuples. Always use this model.
    
    Compliance: SWE-033 (traceability)
    """
    model_config = {"extra": "forbid", "frozen": True}

    x0: float
    y0: float
    x1: float
    y1: float
    
    coord_space: CoordSpace
    origin: Origin
    dpi: Optional[int] = None  # Required if coord_space == PAGE_PIXELS

    @model_validator(mode="after")
    def validate_dpi(self) -> "BBox":
        if self.coord_space == CoordSpace.PAGE_PIXELS and self.dpi is None:
            raise ValueError("dpi required for PAGE_PIXELS coordinate space")
        return self

    @property
    def width(self) -> float:
        return abs(self.x1 - self.x0)

    @property
    def height(self) -> float:
        return abs(self.y1 - self.y0)

    @property
    def as_tuple(self) -> tuple[float, float, float, float]:
        """For APIs that need raw tuples."""
        return (self.x0, self.y0, self.x1, self.y1)

    def to_pdf_points(self, page_height: float) -> "BBox":
        """Convert to PDF points with bottom-left origin."""
        if self.coord_space == CoordSpace.PDF_POINTS:
            if self.origin == Origin.BOTTOM_LEFT:
                return self
            # PDF points but top-left origin: flip y
            return BBox(
                x0=self.x0,
                y0=page_height - self.y1,
                x1=self.x1,
                y1=page_height - self.y0,
                coord_space=CoordSpace.PDF_POINTS,
                origin=Origin.BOTTOM_LEFT,
            )
        
        # Page pixels to PDF points
        if self.dpi is None:
            raise ValueError("Cannot convert: dpi not set")
        
        scale = 72.0 / self.dpi  # PDF points per pixel
        
        if self.origin == Origin.TOP_LEFT:
            # Flip y and scale
            return BBox(
                x0=self.x0 * scale,
                y0=page_height - (self.y1 * scale),
                x1=self.x1 * scale,
                y1=page_height - (self.y0 * scale),
                coord_space=CoordSpace.PDF_POINTS,
                origin=Origin.BOTTOM_LEFT,
            )
        else:
            # Just scale
            return BBox(
                x0=self.x0 * scale,
                y0=self.y0 * scale,
                x1=self.x1 * scale,
                y1=self.y1 * scale,
                coord_space=CoordSpace.PDF_POINTS,
                origin=Origin.BOTTOM_LEFT,
            )

    def to_page_pixels(self, page_height_points: float, dpi: int) -> "BBox":
        """Convert to page pixels with top-left origin."""
        if self.coord_space == CoordSpace.PAGE_PIXELS and self.origin == Origin.TOP_LEFT:
            if self.dpi == dpi:
                return self
            # Rescale
            scale = dpi / self.dpi
            return BBox(
                x0=self.x0 * scale,
                y0=self.y0 * scale,
                x1=self.x1 * scale,
                y1=self.y1 * scale,
                coord_space=CoordSpace.PAGE_PIXELS,
                origin=Origin.TOP_LEFT,
                dpi=dpi,
            )
        
        # Convert from PDF points
        pdf_bbox = self.to_pdf_points(page_height_points)
        scale = dpi / 72.0  # Pixels per PDF point
        page_height_pixels = page_height_points * scale
        
        return BBox(
            x0=pdf_bbox.x0 * scale,
            y0=page_height_pixels - (pdf_bbox.y1 * scale),  # Flip y
            x1=pdf_bbox.x1 * scale,
            y1=page_height_pixels - (pdf_bbox.y0 * scale),
            coord_space=CoordSpace.PAGE_PIXELS,
            origin=Origin.TOP_LEFT,
            dpi=dpi,
        )
```

### TableCell

```python
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel

__all__ = ["TableCell"]
__safety_critical__ = True


class TableCell(BaseModel):
    """Single cell in extracted table grid."""
    model_config = {"extra": "forbid"}

    r: int                              # Row index (0-based)
    c: int                              # Column index (0-based)
    text: Optional[str] = None          # Cell content (None if empty)
    rowspan: int = 1
    colspan: int = 1
    
    # Pixel-level provenance (optional, debug mode)
    cell_bbox: Optional[BBox] = None
```

### TableSource

```python
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel

__all__ = ["TableSource"]
__safety_critical__ = True


class TableSource(BaseModel):
    """Provenance for extracted table."""
    model_config = {"extra": "forbid"}

    # Document identity
    pdf_path: str
    pdf_hash: str                       # SHA256
    page_number: int                    # 1-indexed
    page_height_points: float           # For coordinate conversion

    # Table location - ALWAYS in PDF points, bottom-left origin
    bbox: BBox
    table_index: int                    # 0-indexed on page

    # Rendered image provenance
    render_dpi: int = 150
    render_bbox: Optional[BBox] = None  # In page pixels, top-left origin
    rendered_image_hash: str            # SHA256 of PNG
    rendered_image_path: Optional[str] = None  # Debug mode only

    # Extraction metadata
    model_id: str = "claude-haiku-4-5-20251001"
    prompt_version: str = "1.5"
    raw_response_path: Optional[str] = None
```

### TableGrid

```python
from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, PrivateAttr, computed_field

__all__ = ["TableGrid"]
__safety_critical__ = True


class TableGrid(BaseModel):
    """
    Single table extracted as lossless cell grid.
    
    Compliance: SWE-032 (data integrity), SWE-033 (traceability)
    """
    model_config = {"extra": "forbid"}

    table_id: str
    cells: list[TableCell]
    row_count: int
    col_count: int
    header_row_count: int = 1

    context_text: Optional[str] = None
    footnotes_text: Optional[str] = None

    source: TableSource

    # Quality
    extraction_confidence: float = 1.0
    extraction_timestamp: str
    error: Optional[str] = None

    # Internal index for O(1) cell lookup
    _cell_index: dict[tuple[int, int], TableCell] = PrivateAttr(default_factory=dict)

    def model_post_init(self, __context: Any) -> None:
        """Build cell index after initialization."""
        self._build_cell_index()

    def _build_cell_index(self) -> None:
        """Build O(1) lookup index for cells, handling spans."""
        self._cell_index = {}
        for cell in self.cells:
            # Index the cell at its primary position
            self._cell_index[(cell.r, cell.c)] = cell
            # Also index all positions covered by spans
            for dr in range(cell.rowspan):
                for dc in range(cell.colspan):
                    pos = (cell.r + dr, cell.c + dc)
                    if pos not in self._cell_index:
                        self._cell_index[pos] = cell

    def get_cell(self, row: int, col: int) -> Optional[TableCell]:
        """O(1) cell lookup."""
        return self._cell_index.get((row, col))

    def get_row(self, row: int) -> list[Optional[str]]:
        """Get all text values in a row."""
        return [
            cell.text if (cell := self.get_cell(row, c)) else None
            for c in range(self.col_count)
        ]

    def get_column_header_signature(self, col: int) -> str:
        """
        Construct header signature from ALL header rows.
        
        Example: "Mechanical Properties | RA (%)"
        """
        parts = []
        seen = set()
        
        for r in range(self.header_row_count):
            cell = self.get_cell(r, col)
            if cell and cell.text and cell.text.strip():
                text = cell.text.strip()
                if text not in seen:
                    parts.append(text)
                    seen.add(text)
        
        return " | ".join(parts) if parts else ""

    def get_all_header_signatures(self) -> list[str]:
        """Get header signatures for all columns."""
        return [self.get_column_header_signature(c) for c in range(self.col_count)]

    def get_column_headers_flat(self) -> list[str]:
        """Get bottom header row only."""
        if self.header_row_count == 0:
            return []
        return [h or "" for h in self.get_row(self.header_row_count - 1)]

    def get_data_rows(self) -> list[list[Optional[str]]]:
        """Get data rows EXCLUDING headers."""
        return [
            self.get_row(r) 
            for r in range(self.header_row_count, self.row_count)
        ]

    @computed_field
    @property
    def structural_coverage(self) -> float:
        """
        Structural coverage metric for confidence.
        
        1.0 = all expected positions covered
        """
        expected = self.row_count * self.col_count
        if expected == 0:
            return 0.0
        
        covered = len(set(self._cell_index.keys()))
        return min(1.0, covered / expected)
```

### ExtractionResult

```python
from __future__ import annotations

from pydantic import BaseModel, Field, computed_field

__all__ = ["ExtractionResult"]
__safety_critical__ = True


class ExtractionResult(BaseModel):
    """Result of extracting tables from one or more documents."""
    model_config = {"extra": "forbid"}

    extraction_id: str
    extraction_timestamp: str
    extractor_version: str = "1.5.0"

    source_paths: list[str]
    source_hashes: list[str]

    tables: list[TableGrid] = Field(default_factory=list)

    # Stats
    documents_processed: int = 0
    pages_scanned: int = 0
    tables_found_pdfplumber: int = 0
    tables_found_vision_fallback: int = 0
    table_grids_transcribed: int = 0
    tables_failed: int = 0

    # Cost tracking
    api_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0

    @computed_field
    @property
    def estimated_cost_usd(self) -> float:
        """Estimate API cost (Haiku pricing)."""
        input_cost = self.input_tokens * 0.80 / 1_000_000
        output_cost = self.output_tokens * 4.00 / 1_000_000
        return round(input_cost + output_cost, 4)

    failed_documents: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
```

### LogicalTable

```python
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

__all__ = ["LogicalTable"]


class LogicalTable(BaseModel):
    """
    A logical table that may span multiple physical TableGrids.
    
    Created by TableStitcher when continuation patterns detected.
    """
    model_config = {"extra": "forbid"}

    logical_table_id: str
    display_name: Optional[str] = None
    
    grids: list[TableGrid]
    
    merged_row_count: int
    merged_col_count: int
    header_row_count: int
    
    source_pages: list[int]
    stitch_confidence: float = 1.0
    stitch_evidence: list[str] = Field(default_factory=list)

    def get_merged_data_rows(self) -> list[list[Optional[str]]]:
        """
        Get all DATA rows from all grids, EXCLUDING headers.
        
        Headers are taken only from first grid.
        Continuation grids have their header rows skipped.
        """
        rows = []
        for grid in self.grids:
            rows.extend(grid.get_data_rows())
        return rows

    def get_all_rows_with_headers(self) -> list[list[Optional[str]]]:
        """
        Get ALL rows including headers from first grid.
        
        Returns: header rows from first grid + data rows from all grids
        """
        if not self.grids:
            return []
        
        rows = []
        first = self.grids[0]
        
        # Headers from first grid
        for r in range(first.header_row_count):
            rows.append(first.get_row(r))
        
        # Data from all grids
        rows.extend(self.get_merged_data_rows())
        
        return rows

    def get_header_signatures(self) -> list[str]:
        """Get header signatures from first grid."""
        if not self.grids:
            return []
        return self.grids[0].get_all_header_signatures()
```

---

## Layer 1.5: Table Stitcher

```python
from __future__ import annotations

import re
from typing import Optional

__all__ = ["TableStitcher"]


class TableStitcher:
    """
    Detects and merges multi-page table continuations.
    
    Detection signals (multiple signals increase confidence):
    1. Context text contains continuation pattern
    2. Same column count and headers
    3. Sequential pages
    4. Bbox position: prev ends near bottom, curr starts near top
    5. Table number continuity (e.g., "Table 3-1", "Table 3-2")
    """

    CONTINUATION_PATTERNS = [
        r"\(cont\.?\)",
        r"\(continued\)",
        r"continued\s+from",
        r"continuation\s+of",
        r"table\s+\d+\s*\(cont",
    ]
    
    TABLE_NUMBER_PATTERN = re.compile(
        r"table\s+(\d+)(?:[-.](\d+))?",
        re.IGNORECASE
    )

    BOTTOM_MARGIN_THRESHOLD = 0.15
    TOP_MARGIN_THRESHOLD = 0.15

    def stitch(self, grids: list[TableGrid]) -> list[LogicalTable]:
        """Group grids into logical tables."""
        if not grids:
            return []

        sorted_grids = sorted(
            grids, 
            key=lambda g: (g.source.page_number, g.source.table_index)
        )
        
        logical_tables: list[LogicalTable] = []
        current_group: list[TableGrid] = []
        
        for grid in sorted_grids:
            if not current_group:
                current_group.append(grid)
                continue
            
            is_cont, evidence = self._is_continuation(current_group[-1], grid)
            if is_cont:
                current_group.append(grid)
            else:
                logical_tables.append(self._merge_group(current_group))
                current_group = [grid]
        
        if current_group:
            logical_tables.append(self._merge_group(current_group))
        
        return logical_tables

    def _is_continuation(
        self, 
        prev: TableGrid, 
        curr: TableGrid,
    ) -> tuple[bool, list[str]]:
        """Check if curr continues prev."""
        evidence = []
        score = 0.0
        
        page_diff = curr.source.page_number - prev.source.page_number
        if page_diff > 2:
            return False, []
        if page_diff == 1:
            evidence.append("Sequential pages")
            score += 0.2
        
        # Signal 1: Continuation pattern in context
        if curr.context_text:
            for pattern in self.CONTINUATION_PATTERNS:
                if re.search(pattern, curr.context_text, re.IGNORECASE):
                    evidence.append(f"Context matches: {pattern}")
                    score += 0.5
                    break
        
        # Signal 2: Same column structure
        if curr.col_count == prev.col_count:
            prev_headers = prev.get_column_headers_flat()
            curr_headers = curr.get_column_headers_flat()
            
            if prev_headers == curr_headers:
                evidence.append("Identical headers")
                score += 0.4
            else:
                matching = sum(1 for p, c in zip(prev_headers, curr_headers) if p == c)
                if prev_headers and matching / len(prev_headers) > 0.8:
                    evidence.append(f"Similar headers ({matching}/{len(prev_headers)})")
                    score += 0.3
        else:
            return False, []
        
        # Signal 3: Bbox position
        if self._check_margin_positions(prev, curr):
            evidence.append("Margin position match (prev=bottom, curr=top)")
            score += 0.3
        
        # Signal 4: Table number continuity
        table_num_match = self._check_table_number_continuity(prev, curr)
        if table_num_match:
            evidence.append(f"Table number continuity: {table_num_match}")
            score += 0.4
        
        # Signal 5: No new caption
        if not curr.context_text or curr.context_text.strip() == "":
            evidence.append("No new caption (likely continuation)")
            score += 0.2
        
        return score >= 0.5, evidence

    def _check_margin_positions(self, prev: TableGrid, curr: TableGrid) -> bool:
        """Check if prev ends near bottom and curr starts near top."""
        prev_page_height = prev.source.page_height_points
        curr_page_height = curr.source.page_height_points
        
        prev_bbox = prev.source.bbox.to_pdf_points(prev_page_height)
        curr_bbox = curr.source.bbox.to_pdf_points(curr_page_height)
        
        prev_bottom_margin = prev_bbox.y0 / prev_page_height
        curr_top_margin = 1.0 - (curr_bbox.y1 / curr_page_height)
        
        return (
            prev_bottom_margin < self.BOTTOM_MARGIN_THRESHOLD and
            curr_top_margin < self.TOP_MARGIN_THRESHOLD
        )

    def _check_table_number_continuity(
        self, 
        prev: TableGrid, 
        curr: TableGrid,
    ) -> Optional[str]:
        """Check for table number patterns like 'Table 3-1', 'Table 3-2'."""
        prev_match = self.TABLE_NUMBER_PATTERN.search(prev.context_text or "")
        curr_match = self.TABLE_NUMBER_PATTERN.search(curr.context_text or "")
        
        if not prev_match or not curr_match:
            return None
        
        prev_main = prev_match.group(1)
        curr_main = curr_match.group(1)
        
        if prev_main != curr_main:
            return None
        
        prev_sub = prev_match.group(2)
        curr_sub = curr_match.group(2)
        
        if prev_sub and curr_sub:
            if int(curr_sub) == int(prev_sub) + 1:
                return f"Table {prev_main}-{prev_sub} → {curr_main}-{curr_sub}"
        
        return None

    def _merge_group(self, grids: list[TableGrid]) -> LogicalTable:
        """Merge grids into LogicalTable."""
        first = grids[0]
        
        total_data_rows = sum(g.row_count - g.header_row_count for g in grids)
        merged_rows = first.header_row_count + total_data_rows
        
        evidence = []
        if len(grids) > 1:
            pages = [g.source.page_number for g in grids]
            evidence.append(f"Merged {len(grids)} grids from pages {pages}")
        
        display_name = None
        if first.context_text:
            match = re.search(
                r"(table\s+[\d.]+[:\s]*[^(]*)",
                first.context_text,
                re.IGNORECASE
            )
            if match:
                display_name = match.group(1).strip()
        
        return LogicalTable(
            logical_table_id=f"{first.table_id}_logical",
            display_name=display_name,
            grids=grids,
            merged_row_count=merged_rows,
            merged_col_count=first.col_count,
            header_row_count=first.header_row_count,
            source_pages=[g.source.page_number for g in grids],
            stitch_confidence=1.0 if len(grids) == 1 else 0.9,
            stitch_evidence=evidence,
        )
```

---

## Layer 2: Semantic Mapping

### SemanticTag Ontology

```python
from enum import Enum

__all__ = ["SemanticTag"]


class SemanticTag(str, Enum):
    """
    Ontology of column types for materials tables.
    
    IMPORTANT: This contains ONLY observable column types.
    Derived quantities (embrittlement_index, nts_ratio) are NOT here.
    Those are computed by interpreters.
    """

    # MATERIAL IDENTIFICATION
    MATERIAL_IDENTIFIER = "material.identifier"
    MATERIAL_SPECIFICATION = "material.specification"
    MATERIAL_HEAT = "material.heat"
    MATERIAL_FORM = "material.form"
    MATERIAL_CONDITION = "material.condition"
    MATERIAL_CATEGORY = "material.category"

    # CHEMICAL COMPOSITION (weight %)
    COMPOSITION_FE = "composition.fe"
    COMPOSITION_CR = "composition.cr"
    COMPOSITION_NI = "composition.ni"
    COMPOSITION_MO = "composition.mo"
    COMPOSITION_MN = "composition.mn"
    COMPOSITION_SI = "composition.si"
    COMPOSITION_C = "composition.c"
    COMPOSITION_N = "composition.n"
    COMPOSITION_AL = "composition.al"
    COMPOSITION_TI = "composition.ti"
    COMPOSITION_CU = "composition.cu"
    COMPOSITION_V = "composition.v"
    COMPOSITION_W = "composition.w"
    COMPOSITION_CO = "composition.co"
    COMPOSITION_NB = "composition.nb"
    COMPOSITION_OTHER = "composition.other"

    # TEST CONDITIONS
    TEST_ENVIRONMENT = "test.environment"
    TEST_PRESSURE = "test.pressure"
    TEST_TEMPERATURE = "test.temperature"
    TEST_STRAIN_RATE = "test.strain_rate"
    TEST_METHOD = "test.method"

    # MECHANICAL PROPERTIES (observable columns)
    MECHANICAL_YIELD = "mechanical.yield_strength"
    MECHANICAL_ULTIMATE = "mechanical.ultimate_strength"
    MECHANICAL_ELONGATION = "mechanical.elongation"
    MECHANICAL_RA = "mechanical.reduction_of_area"
    MECHANICAL_HARDNESS = "mechanical.hardness"
    MECHANICAL_NTS = "mechanical.notched_tensile_strength"
    MECHANICAL_TOUGHNESS = "mechanical.toughness"

    # HYDROGEN PROPERTIES (observable)
    H2_PERMEABILITY = "h2.permeability"
    H2_DIFFUSIVITY = "h2.diffusivity"
    H2_SOLUBILITY = "h2.solubility"

    # OXYGEN PROPERTIES (observable)
    O2_AIT = "o2.ait"
    O2_FLAMMABILITY_RATING = "o2.flammability_rating"
    O2_MECHANICAL_IMPACT = "o2.mechanical_impact"
    O2_PROMOTED_IGNITION = "o2.promoted_ignition"
    O2_COMPATIBILITY_RATING = "o2.compatibility_rating"
    O2_LOI = "o2.loi"

    # METADATA
    REFERENCE_CITATION = "reference.citation"
    REFERENCE_FOOTNOTE = "reference.footnote"
    NOTES = "meta.notes"

    UNKNOWN = "unknown"
```

### Unit Detection (Tag-Aware)

```python
from __future__ import annotations

import re
from enum import Enum
from typing import Optional

__all__ = ["Unit", "UNIT_APPLICABLE_TAGS", "detect_unit", "convert_to_si"]


class Unit(str, Enum):
    """Standard units with SI conversion factors."""
    
    # Pressure (target: MPa)
    MPA = "MPa"
    KSI = "ksi"
    PSI = "psi"
    BAR = "bar"
    
    # Temperature (target: K)
    KELVIN = "K"
    CELSIUS = "°C"
    FAHRENHEIT = "°F"
    
    # Percentage
    PERCENT = "%"
    
    # Dimensionless
    DIMENSIONLESS = ""


UNIT_APPLICABLE_TAGS: set[SemanticTag] = {
    SemanticTag.MECHANICAL_YIELD,
    SemanticTag.MECHANICAL_ULTIMATE,
    SemanticTag.MECHANICAL_ELONGATION,
    SemanticTag.MECHANICAL_RA,
    SemanticTag.MECHANICAL_NTS,
    SemanticTag.MECHANICAL_HARDNESS,
    SemanticTag.MECHANICAL_TOUGHNESS,
    SemanticTag.TEST_PRESSURE,
    SemanticTag.TEST_TEMPERATURE,
    SemanticTag.O2_AIT,
    SemanticTag.O2_LOI,
    SemanticTag.H2_PERMEABILITY,
    SemanticTag.H2_DIFFUSIVITY,
    SemanticTag.H2_SOLUBILITY,
}


UNIT_PATTERNS: list[tuple[str, Unit, bool]] = [
    # Unambiguous - always safe
    (r"\bmpa\b", Unit.MPA, False),
    (r"\bksi\b", Unit.KSI, False),
    (r"\bpsi\b", Unit.PSI, False),
    (r"\bbar\b", Unit.BAR, False),
    (r"°c\b", Unit.CELSIUS, False),
    (r"°f\b", Unit.FAHRENHEIT, False),
    (r"\bkelvin\b", Unit.KELVIN, False),
    (r"\bfahrenheit\b", Unit.FAHRENHEIT, False),
    (r"\bcelsius\b", Unit.CELSIUS, False),
    (r"%", Unit.PERCENT, False),
    
    # Ambiguous - require tag check
    (r"\(k\)", Unit.KELVIN, True),
    (r"\(c\)", Unit.CELSIUS, True),
    (r"temp.*\bk\b", Unit.KELVIN, True),
    (r"temp.*\bc\b", Unit.CELSIUS, True),
]


def detect_unit(header: str, tag: Optional[SemanticTag] = None) -> Optional[Unit]:
    """
    Detect unit from column header.
    
    IMPORTANT: For ambiguous patterns (K, C), tag must be provided
    and must be in UNIT_APPLICABLE_TAGS.
    """
    header_lower = header.lower()
    
    for pattern, unit, requires_tag in UNIT_PATTERNS:
        if re.search(pattern, header_lower):
            if requires_tag:
                if tag is None or tag not in UNIT_APPLICABLE_TAGS:
                    continue
            return unit
    
    return None


def convert_to_si(value: float, unit: Unit) -> float:
    """Convert value to SI units (MPa for pressure, K for temperature)."""
    conversions = {
        Unit.MPA: lambda x: x,
        Unit.KSI: lambda x: x * 6.89476,
        Unit.PSI: lambda x: x * 0.00689476,
        Unit.BAR: lambda x: x * 0.1,
        Unit.KELVIN: lambda x: x,
        Unit.CELSIUS: lambda x: x + 273.15,
        Unit.FAHRENHEIT: lambda x: (x + 459.67) * 5/9,
        Unit.PERCENT: lambda x: x,
        Unit.DIMENSIONLESS: lambda x: x,
    }
    return conversions[unit](value)
```

### Value Cleaner (Fixed Regex)

```python
from __future__ import annotations

import re
from typing import Optional

from pydantic import BaseModel, Field

__all__ = ["NumericValue", "ValueCleaner"]


class NumericValue(BaseModel):
    """
    Cleaned numeric value with metadata.
    
    Handles: ranges, inequalities, approximations, traces, footnotes,
    scientific notation, commas.
    """
    model_config = {"extra": "forbid", "frozen": True}

    raw: str
    value: Optional[float] = None
    value_high: Optional[float] = None
    original_unit: Optional[Unit] = None
    
    operator: str = "exact"  # exact, approx, gt, lt, gte, lte, range
    is_trace: bool = False
    is_balance: bool = False
    is_missing: bool = False
    
    footnotes: list[str] = Field(default_factory=list)
    parse_warnings: list[str] = Field(default_factory=list)


class ValueCleaner:
    """
    Cleans raw cell values into typed NumericValue objects.
    
    Compliance: SWE-032 (data integrity)
    """

    MISSING_VALUES = {"—", "–", "-", "n/a", "na", "nd", "not determined", ""}
    TRACE_VALUES = {"tr", "tr.", "trace"}
    BALANCE_VALUES = {"bal", "bal.", "balance", "rem", "remainder"}
    
    FOOTNOTE_PATTERN = re.compile(r"[†‡§¶*#]+|\(\d+\)|\[\d+\]")
    
    NUMBER = r"[-+]?\d{1,3}(?:,\d{3})*(?:\.\d+)?(?:[eE][-+]?\d+)?"
    
    # FIXED: proper alternation for "to"
    RANGE_PATTERN = re.compile(
        rf"({NUMBER})\s*(?:-|–|—|\bto\b)\s*({NUMBER})",
        re.IGNORECASE
    )
    
    INEQ_PATTERN = re.compile(rf"([<>≤≥]=?)\s*({NUMBER})")
    PLAIN_NUMBER = re.compile(rf"({NUMBER})")
    UNCERTAINTY_PATTERN = re.compile(rf"({NUMBER})\s*(?:±|\+/-)\s*({NUMBER})")

    @classmethod
    def clean(
        cls,
        raw: Optional[str],
        detected_unit: Optional[Unit] = None,
    ) -> NumericValue:
        """Clean a raw cell value."""
        if raw is None:
            return NumericValue(raw="", is_missing=True)
        
        text = raw.strip()
        text_lower = text.lower()
        
        if text_lower in cls.MISSING_VALUES:
            return NumericValue(raw=raw, is_missing=True)
        
        if text_lower in cls.TRACE_VALUES or text_lower.startswith("<0.0"):
            return NumericValue(raw=raw, is_trace=True)
        
        if text_lower in cls.BALANCE_VALUES:
            return NumericValue(raw=raw, is_balance=True)
        
        footnotes = cls.FOOTNOTE_PATTERN.findall(text)
        text_clean = cls.FOOTNOTE_PATTERN.sub("", text).strip()
        text_clean = re.sub(r"(\d),(\d)", r"\1\2", text_clean)
        
        warnings = []
        
        # Try uncertainty: "500 ± 5"
        unc_match = cls.UNCERTAINTY_PATTERN.search(text_clean)
        if unc_match:
            try:
                val = float(unc_match.group(1))
                unc = float(unc_match.group(2))
                if detected_unit:
                    val = convert_to_si(val, detected_unit)
                    unc = convert_to_si(unc, detected_unit)
                return NumericValue(
                    raw=raw,
                    value=val,
                    value_high=val + unc,
                    original_unit=detected_unit,
                    operator="range",
                    footnotes=footnotes,
                )
            except ValueError:
                warnings.append(f"Failed to parse uncertainty: {text_clean}")
        
        # Try range: "500-600" or "500 to 600"
        range_match = cls.RANGE_PATTERN.search(text_clean)
        if range_match:
            try:
                v1 = float(range_match.group(1))
                v2 = float(range_match.group(2))
                if detected_unit:
                    v1 = convert_to_si(v1, detected_unit)
                    v2 = convert_to_si(v2, detected_unit)
                return NumericValue(
                    raw=raw,
                    value=min(v1, v2),
                    value_high=max(v1, v2),
                    original_unit=detected_unit,
                    operator="range",
                    footnotes=footnotes,
                )
            except ValueError:
                warnings.append(f"Failed to parse range: {text_clean}")
        
        # Try inequality: ">500"
        ineq_match = cls.INEQ_PATTERN.search(text_clean)
        if ineq_match:
            try:
                op_str = ineq_match.group(1)
                val = float(ineq_match.group(2))
                if detected_unit:
                    val = convert_to_si(val, detected_unit)
                op_map = {"<": "lt", ">": "gt", "<=": "lte", ">=": "gte", 
                          "≤": "lte", "≥": "gte"}
                return NumericValue(
                    raw=raw,
                    value=val,
                    original_unit=detected_unit,
                    operator=op_map.get(op_str, "exact"),
                    footnotes=footnotes,
                )
            except ValueError:
                warnings.append(f"Failed to parse inequality: {text_clean}")
        
        # Try approximation: "~500"
        if "~" in text_clean or "≈" in text_clean or "approx" in text_lower:
            num_match = cls.PLAIN_NUMBER.search(text_clean)
            if num_match:
                try:
                    val = float(num_match.group(1))
                    if detected_unit:
                        val = convert_to_si(val, detected_unit)
                    return NumericValue(
                        raw=raw,
                        value=val,
                        original_unit=detected_unit,
                        operator="approx",
                        footnotes=footnotes,
                    )
                except ValueError:
                    pass
        
        # Try plain number
        num_match = cls.PLAIN_NUMBER.search(text_clean)
        if num_match:
            try:
                val = float(num_match.group(1))
                if detected_unit:
                    val = convert_to_si(val, detected_unit)
                return NumericValue(
                    raw=raw,
                    value=val,
                    original_unit=detected_unit,
                    operator="exact",
                    footnotes=footnotes,
                )
            except ValueError:
                warnings.append(f"Failed to parse number: {text_clean}")
        
        return NumericValue(
            raw=raw,
            is_missing=True,
            parse_warnings=warnings or [f"Could not parse: '{raw}'"],
        )
```

### Material Resolver

```python
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, computed_field

__all__ = ["MaterialKey", "MaterialResolver"]


class MaterialKey(BaseModel):
    """Canonical material identifier."""
    model_config = {"extra": "forbid"}

    uns: Optional[str] = None
    common_name: str
    specification: Optional[str] = None

    @computed_field
    @property
    def canonical_key(self) -> str:
        """Primary key for deduplication."""
        if self.uns:
            return self.uns
        return self.common_name.lower().replace(" ", "").replace("-", "")


class MaterialResolver:
    """
    Resolves material names to canonical keys.
    
    IMPORTANT: This is CANONICALIZATION only, not inference.
    
    Alias mapping is permitted for canonical key normalization.
    It must NOT drive compatibility decisions.
    """

    MATERIAL_ALIASES: dict[str, str] = {
        # Austenitic stainless steels
        "304": "S30400",
        "304l": "S30403",
        "type 304l": "S30403",
        "aisi 304l": "S30403",
        "ss304l": "S30403",
        "316": "S31600",
        "316l": "S31603",
        "type 316l": "S31603",
        "321": "S32100",
        "347": "S34700",
        
        # Nickel alloys
        "inconel 718": "N07718",
        "alloy 718": "N07718",
        "in718": "N07718",
        "inconel 625": "N06625",
        "alloy 625": "N06625",
        "in625": "N06625",
        "hastelloy c-276": "N10276",
        "hastelloy c276": "N10276",
        
        # Aluminum alloys
        "6061": "A96061",
        "6061-t6": "A96061",
        "7075": "A97075",
        "7075-t6": "A97075",
    }

    def resolve(self, name: str, spec: Optional[str] = None) -> MaterialKey:
        """Resolve material name to canonical key."""
        normalized = name.strip().lower().replace(" ", "").replace("-", "")
        
        uns = self.MATERIAL_ALIASES.get(normalized)
        
        if not uns:
            uns = self.MATERIAL_ALIASES.get(name.strip().lower())
        
        return MaterialKey(
            uns=uns,
            common_name=name.strip(),
            specification=spec,
        )
```

### SemanticTable

```python
from __future__ import annotations

import hashlib
from typing import Optional

from pydantic import BaseModel, Field, computed_field

__all__ = ["ColumnMapping", "SemanticTable"]


class ColumnMapping(BaseModel):
    """Mapping of a column to semantic tag."""
    model_config = {"extra": "forbid"}

    col_index: int
    raw_header: str
    header_signature: str
    tag: SemanticTag
    confidence: float
    evidence: str
    detected_unit: Optional[Unit] = None


class SemanticTable(BaseModel):
    """Table with semantic column mappings."""
    model_config = {"extra": "forbid"}

    source_table_id: str
    source_grids: list[TableGrid]
    
    column_mappings: list[ColumnMapping]
    unmapped_columns: list[int] = Field(default_factory=list)

    @computed_field
    @property
    def mapping_hash(self) -> str:
        """
        Stable hash for regression tests.
        
        INCLUDES: tag, detected_unit, header_signature (normalized)
        """
        components = []
        for m in sorted(self.column_mappings, key=lambda x: x.col_index):
            sig_normalized = m.header_signature.lower().strip()
            unit_str = m.detected_unit.value if m.detected_unit else "none"
            components.append(f"{m.col_index}:{m.tag.value}:{unit_str}:{sig_normalized}")
        
        sig = "|".join(components)
        return hashlib.md5(sig.encode()).hexdigest()[:16]

    def has_tag(self, tag: SemanticTag) -> bool:
        return any(m.tag == tag for m in self.column_mappings)

    def has_any_tag(self, tags: list[SemanticTag]) -> bool:
        return any(self.has_tag(t) for t in tags)

    def has_all_tags(self, tags: list[SemanticTag]) -> bool:
        return all(self.has_tag(t) for t in tags)

    def get_column_for_tag(self, tag: SemanticTag) -> Optional[int]:
        for m in self.column_mappings:
            if m.tag == tag:
                return m.col_index
        return None

    def get_unit_for_tag(self, tag: SemanticTag) -> Optional[Unit]:
        for m in self.column_mappings:
            if m.tag == tag:
                return m.detected_unit
        return None
```

---

## Layer 4: Validation Gates

### ValidationResult and GateProtocol

```python
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from pydantic import BaseModel, Field

__all__ = ["ValidationResult", "GateProtocol"]


class ValidationResult(BaseModel):
    """Result of a validation gate check."""
    model_config = {"extra": "forbid"}

    passed: bool
    gate_name: str
    checked: int = 0
    passed_count: int = 0
    required_fields: list[str] = Field(default_factory=list)
    diagnostics: list[str] = Field(default_factory=list)


class GateProtocol(ABC):
    """Base protocol for validation gates."""
    
    @property
    @abstractmethod
    def gate_name(self) -> str:
        ...
    
    @abstractmethod
    def validate(self, data: Any) -> ValidationResult:
        ...
```

### ExtractionGate

```python
from __future__ import annotations

__all__ = ["ExtractionGate"]


class ExtractionGate(GateProtocol):
    """
    Fails BEFORE interpretation if extraction produced nothing.
    """
    
    gate_name = "Extraction Gate"

    def validate(
        self,
        result: ExtractionResult,
        expected_tables: bool = True,
    ) -> ValidationResult:
        """Check that extraction produced tables."""
        if expected_tables and result.table_grids_transcribed == 0:
            return ValidationResult(
                passed=False,
                gate_name=self.gate_name,
                checked=result.documents_processed,
                diagnostics=[
                    f"HARD FAIL: Zero tables extracted from {result.documents_processed} document(s)",
                    f"Tables found by pdfplumber: {result.tables_found_pdfplumber}",
                    f"Tables found by vision fallback: {result.tables_found_vision_fallback}",
                    f"Tables failed: {result.tables_failed}",
                    "Possible causes:",
                    "  - PDF is image-only (scan) and detection missed all",
                    "  - PDF genuinely has no tables (verify manually)",
                    "  - Vision API errors (check result.errors)",
                    "Suggested actions:",
                    "  - Enable full-page vision fallback for table detection",
                    "  - Verify PDF content manually",
                    "  - Check error logs for API failures",
                ],
            )
        
        return ValidationResult(
            passed=True,
            gate_name=self.gate_name,
            checked=result.documents_processed,
            passed_count=result.table_grids_transcribed,
        )
```

### H2ValidationGate

```python
from __future__ import annotations

__all__ = ["H2ValidationGate"]


class H2ValidationGate(GateProtocol):
    """
    H2 Knowledge Twin validation gate.
    
    HARD FAIL if no embrittlement data extracted.
    """
    
    gate_name = "H2 Safety Signal Gate"
    required_any_of = ["embrittlement_index_ra", "embrittlement_index_el", "nts_ratio"]

    def validate(self, records: list[EmbrittlementRecord]) -> ValidationResult:
        """Check that extraction produced H2 safety signals."""
        with_signal = [
            r for r in records
            if (r.embrittlement_index_ra is not None or
                r.embrittlement_index_el is not None or
                r.nts_ratio is not None)
        ]
        
        passed = len(with_signal) > 0
        
        diagnostics = []
        if not passed:
            diagnostics = [
                f"HARD FAIL: Extracted {len(records)} records but 0 have safety signal",
                f"Required at least one of: {self.required_any_of}",
                "Possible causes:",
                "  - Table doesn't contain paired He/H2 test data",
                "  - TEST_ENVIRONMENT column not mapped",
                "  - MECHANICAL_RA column not found",
                "  - Paired test pattern not detected",
                "  - Unit mismatch preventing calculation",
            ]
        
        return ValidationResult(
            passed=passed,
            gate_name=self.gate_name,
            checked=len(records),
            passed_count=len(with_signal),
            required_fields=self.required_any_of,
            diagnostics=diagnostics,
        )
```

### O2ValidationGate

```python
from __future__ import annotations

__all__ = ["O2ValidationGate"]


class O2ValidationGate(GateProtocol):
    """
    O2 Knowledge Twin validation gate.
    
    HARD FAIL if no flammability data extracted.
    """
    
    gate_name = "O2 Safety Signal Gate"
    required_any_of = ["ait_kelvin", "flammability_rating", "compatibility_rating"]

    def validate(self, records: list) -> ValidationResult:
        """Check that extraction produced O2 safety signals."""
        with_signal = [
            r for r in records
            if (getattr(r, "ait_kelvin", None) is not None or
                getattr(r, "flammability_rating", None) is not None or
                getattr(r, "compatibility_rating", None) is not None)
        ]
        
        passed = len(with_signal) > 0
        
        diagnostics = []
        if not passed:
            diagnostics = [
                f"HARD FAIL: Extracted {len(records)} records but 0 have safety signal",
                f"Required at least one of: {self.required_any_of}",
            ]
        
        return ValidationResult(
            passed=passed,
            gate_name=self.gate_name,
            checked=len(records),
            passed_count=len(with_signal),
            required_fields=self.required_any_of,
            diagnostics=diagnostics,
        )
```

---

## Vision Prompts

### EXTRACTION_PROMPT

```python
EXTRACTION_PROMPT = """Read this table image. Return the EXACT structure as JSON.

{
  "cells": [
    {"r": 0, "c": 0, "text": "Header1"},
    {"r": 0, "c": 1, "text": "Header2", "colspan": 2},
    {"r": 1, "c": 0, "text": "Value1"},
    {"r": 1, "c": 1, "text": "Value2"},
    {"r": 1, "c": 2, "text": "Value3"}
  ],
  "row_count": 10,
  "col_count": 5,
  "header_row_count": 1,
  "context_text": "Table 3.1: Mechanical properties of austenitic steels",
  "footnotes_text": "† Heat treated at 1050°C for 1 hour"
}

RULES:
- r = row index (0-based), c = column index (0-based)
- Preserve text EXACTLY (spelling, units, symbols, superscripts, subscripts)
- Multi-line cells: include newlines as \\n
- Empty cells: text = null
- Merged cells: include "rowspan" and/or "colspan" fields
- header_row_count: how many top rows are headers (1, 2, or more)
- context_text: visible caption, title, or section header near table
- footnotes_text: footnotes, symbol definitions, notes below table

CRITICAL:
- Do NOT interpret, calculate, summarize, or infer
- Do NOT skip rows, columns, or cells
- Do NOT correct perceived typos or normalize values
- Extract EXACTLY what you see

Return ONLY valid JSON."""
```

### TABLE_DETECTION_PROMPT

```python
TABLE_DETECTION_PROMPT = """Find all tables in this page image.

Return JSON with bounding boxes for each table:
{
  "tables": [
    {"bbox": [x0, y0, x1, y1], "confidence": 0.95},
    {"bbox": [x0, y0, x1, y1], "confidence": 0.88}
  ]
}

Coordinates are in pixels from top-left (0,0).
Include any structured data that looks like a table (rows/columns of aligned data).
Return empty "tables": [] if no tables found."""
```

---

## File Structure

```
boundstate/
├── athena/                          # ATHENA Table Extraction Platform
│   ├── __init__.py
│   │
│   ├── core/                        # Shared models, utilities, primitives
│   │   ├── __init__.py
│   │   ├── bbox.py                 # BBox model with coord_space, origin, dpi
│   │   ├── coords.py               # PDF↔pixel conversions, origin transforms
│   │   │
│   │   └── models/                  # Core data models
│   │       ├── __init__.py         # Re-exports all models
│   │       ├── cell.py             # TableCell
│   │       ├── grid.py             # TableGrid (with O(1) cell index)
│   │       ├── source.py           # TableSource (provenance)
│   │       └── result.py           # ExtractionResult (stats, cost tracking)
│   │
│   ├── extraction/                  # Layer 1: Vision Extraction
│   │   ├── __init__.py
│   │   ├── extractor.py            # Orchestrates detector + transcriber
│   │   ├── detector.py             # pdfplumber + vision bbox detection
│   │   ├── transcriber.py          # crop + vision → TableGrid
│   │   └── prompts.py              # EXTRACTION_PROMPT, TABLE_DETECTION_PROMPT
│   │
│   ├── stitching/                   # Layer 1.5: Table Stitcher
│   │   ├── __init__.py
│   │   ├── models.py               # LogicalTable
│   │   └── stitcher.py             # TableStitcher with multi-signal detection
│   │
│   ├── semantic/                    # Layer 2: Semantic Mapping
│   │   ├── __init__.py
│   │   ├── ontology.py             # SemanticTag enum (no derived fields)
│   │   ├── mapper.py               # SemanticMapper (rules-first, LLM fallback)
│   │   ├── units.py                # Unit enum, tag-aware detection, SI conversion
│   │   ├── cleaner.py              # ValueCleaner, NumericValue (fixed regex)
│   │   ├── materials.py            # MaterialResolver (canonicalization only)
│   │   │
│   │   └── rules/                   # Semantic mapping rules by domain
│   │       ├── __init__.py         # Re-exports all rules
│   │       ├── base.py             # EXACT_RULES, PATTERN_RULES (shared)
│   │       ├── h2.py               # H2-specific header patterns
│   │       ├── o2.py               # O2-specific header patterns
│   │       └── composition.py      # Composition table patterns
│   │
│   ├── interpreters/                # Layer 3: Domain Interpreters
│   │   ├── __init__.py
│   │   ├── protocol.py             # DomainInterpreter ABC
│   │   ├── models/                  # Domain record models
│   │   │   ├── __init__.py
│   │   │   ├── h2.py               # EmbrittlementRecord
│   │   │   └── o2.py               # FlammabilityRecord
│   │   ├── h2.py                   # H2Interpreter
│   │   └── o2.py                   # O2Interpreter
│   │
│   ├── validation/                  # Layer 4: Safety Gates
│   │   ├── __init__.py
│   │   ├── models.py               # ValidationResult, GateProtocol
│   │   └── gates/                   # Domain-specific gates
│   │       ├── __init__.py
│   │       ├── extraction.py       # ExtractionGate (zero tables = FAIL)
│   │       ├── h2.py               # H2ValidationGate
│   │       └── o2.py               # O2ValidationGate
│   │
│   ├── debug/                       # Debug artifacts (--debug mode)
│   │   ├── __init__.py
│   │   ├── artifacts.py            # Save images, raw JSON responses
│   │   └── overlay.py              # Bbox visualization on page renders
│   │
│   └── pipeline.py                  # KnowledgeTwinPipeline orchestration
│
├── tests/                           # Safety-critical = tests from day 1
│   ├── __init__.py
│   ├── conftest.py                 # Pytest fixtures, shared setup
│   ├── unit/
│   │   ├── __init__.py
│   │   ├── test_bbox.py
│   │   ├── test_coords.py
│   │   ├── test_detector.py
│   │   ├── test_transcriber.py
│   │   ├── test_stitcher.py
│   │   ├── test_cleaner.py
│   │   ├── test_units.py
│   │   └── test_materials.py
│   ├── integration/
│   │   ├── __init__.py
│   │   ├── test_sandia_e2e.py      # Full pipeline on Sandia PDF
│   │   └── test_extraction_gate.py
│   └── fixtures/
│       ├── sandia_sample.pdf       # Subset for CI (hash-linked)
│       ├── multi_page_table.pdf    # Stitcher test case
│       └── golden/                  # Known-good outputs for regression
│           ├── sandia_extraction.json
│           └── sandia_h2_records.json
│
└── cli/
    └── athena.py                    # CLI entry point
```

---

## Implementation Phases

### Phase 1: Core + Extraction (Week 1)
- [ ] `BBox` model with coordinate conversion
- [ ] `core/coords.py` transform utilities
- [ ] `TableCell`, `TableGrid` with O(1) cell index
- [ ] `TableSource`, `ExtractionResult`
- [ ] `detector.py` (pdfplumber + vision fallback)
- [ ] `transcriber.py` (crop + Haiku → TableGrid)
- [ ] `extractor.py` (orchestration)
- [ ] `ExtractionGate`
- [ ] CLI: `athena extract`
- [ ] Test: Sandia produces grids with valid bboxes

### Phase 2: Stitching (Week 1)
- [ ] `LogicalTable` with corrected methods
- [ ] `TableStitcher` with multi-signal detection
- [ ] Test: Multi-page tables merge correctly

### Phase 3: Semantic Mapping (Week 2)
- [ ] `SemanticTag` ontology
- [ ] `semantic/rules/base.py` (EXACT_RULES, PATTERN_RULES)
- [ ] Tag-aware unit detection
- [ ] `ValueCleaner` with FIXED regex
- [ ] `MaterialResolver` (canonicalization only)
- [ ] `SemanticMapper`
- [ ] `mapping_hash` with full signature
- [ ] Test: 95%+ columns mapped, no K/Potassium bugs

### Phase 4: Interpreters (Week 2-3)
- [ ] `EmbrittlementRecord` model
- [ ] `H2Interpreter` with SI normalization
- [ ] `H2ValidationGate`
- [ ] Test: 72+ records with embrittlement_index

### Phase 5: Integration (Week 3-4)
- [ ] `KnowledgeTwinPipeline`
- [ ] Full CLI: `athena process`
- [ ] End-to-end test
- [ ] Ground-truth baseline with PDF hashes

---

## Ensemble Sign-Off

| Reviewer | Status | Final Contribution |
|----------|--------|-------------------|
| **Claude Opus 4.5** | ✅ Final | Architecture synthesis, clean spec |
| **Grok 4.0** | ✅ Approved | Determinism enforcement, test structure |
| **Fran (GPT 5.1)** | ✅ Approved | Critical bugs (coord, regex, confidence), file structure |
| **Gemini 2.0** | ✅ Approved | Stitcher, units, value cleaning, business context |
| **Claude Code** | ✅ Approved | Implementation planning |

---

*End of Specification v1.5.0 FINAL*

---

**ATHENA: Automated Table Harvesting & ENtity Analysis**

*"Extract faithfully. Stitch continuations. Map semantically. Normalize units. Interpret deterministically. Fail loudly."*