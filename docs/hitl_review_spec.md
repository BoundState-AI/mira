# MIUL Human-in-the-Loop Review System
## Task Spec for VSClaude

### The Why

MIRA automates MIUL generation. But automation that removes humans from the loop
creates two problems:

1. **Quality**: Some extractions are ambiguous. Temper callouts, multi-spec notes,
   non-standard materials. A human reviewing flagged items produces a better MIUL
   than either human-only or MIRA-only.

2. **Politics**: If MIRA automates everything, every contractor in the room
   mentally calculates their severance. If MIRA flags items for expert review,
   the contractor becomes the domain expert MIRA consults. Their job gets more
   interesting, not eliminated. This is critical for adoption.

The system must feel like MIRA is an eager junior engineer bringing work to a
senior for review — not a replacement system demanding sign-off.

### Architecture Overview

```
MIUL Build Pipeline (existing)
        │
        ▼
┌─────────────────────┐
│  Confidence Tagger  │  ← NEW: scores every row/field
│  (in builder.py)    │
└────────┬────────────┘
         │
         ▼
┌─────────────────────┐
│  Review JSON        │  ← NEW: structured output with flags
│  (per-build)        │
└────────┬────────────┘
         │
         ▼
┌─────────────────────┐
│  Review UI          │  ← NEW: React component in MIRA frontend
│  (human reviews)    │
└────────┬────────────┘
         │
         ▼
┌─────────────────────┐
│  Corrections API    │  ← NEW: accepts human edits
│  (FastAPI endpoint) │
└────────┬────────────┘
         │
         ▼
┌─────────────────────┐
│  Final MIUL Export  │  ← EXISTING: export_to_excel with corrections applied
└─────────────────────┘
```

### Phase 1: Confidence Tagger (builder.py)

Every MIUL row already has all the data. We need to add per-field confidence
metadata so the UI knows what to flag.

#### 1.1 Row-Level Confidence

Add a `_review` metadata dict to each row in `build_miul()`. This does NOT
go into the Excel export — it's for the review UI only.

```python
# Confidence levels
CONFIDENCE_HIGH = "high"       # ≥ 90% sure, green in UI
CONFIDENCE_MEDIUM = "medium"   # 60-89% sure, yellow in UI, reviewable
CONFIDENCE_LOW = "low"         # < 60% sure, red in UI, MUST review
CONFIDENCE_MISSING = "missing" # no data found, red in UI, MUST review
```

#### 1.2 Field-Level Confidence Rules

For each row, score these fields independently:

**Part Number** — `HIGH` if verbatim from text layer EPL. `MEDIUM` if from Vision.
`LOW` if corrected by `correct_part_number()` (means it was mangled).

**Designation** — `HIGH` if from text layer MATERIAL note (verbatim from drawing).
`HIGH` if from EPL column 9 text layer extraction. `MEDIUM` if from standard
parts DB lookup. `LOW` if from Vision extraction. `MISSING` if empty.

**Material Specification** — `HIGH` if from text layer note parsing (our Phase 2).
`MEDIUM` if from standard parts DB. `LOW` if from Vision. `MISSING` if empty.

**Process Specification** — `HIGH` if from text layer note parsing.
`MISSING` if empty (most EPL parts won't have this — that's OK, not an error).

**NHA** — `HIGH` if from manual override JSON. `HIGH` if from DT tree with HIGH
confidence. `MEDIUM` if from DT tree with MEDIUM confidence or EPL inference.
`LOW` if from DT tree with LOW confidence. `MISSING` if empty.

**Material Form** — `MEDIUM` always (it's inferred, never explicit on drawings).

#### 1.3 Implementation in builder.py

Add a `_tag_confidence()` method to MIULBuilder that takes a row dict and its
source metadata, returns a review dict:

```python
def _tag_confidence(
    self,
    row: Dict[str, Any],
    source: str,          # "epl_text", "epl_vision", "detail_text", "detail_vision", "std_parts"
    material_source: str, # "text_note", "epl_column", "child_drawing", "std_parts_db", "vision", "none"
    spec_source: str,     # "text_note", "std_parts_db", "vision", "none"
    nha_source: str,      # "override", "dt_high", "dt_medium", "dt_low", "epl_infer", "none"
) -> Dict[str, Any]:
    """Generate per-field confidence metadata for a MIUL row."""

    review = {
        "part_number": row["Part Number"],
        "fields": {},
        "row_confidence": CONFIDENCE_HIGH,  # will be downgraded
        "needs_review": False,
        "review_reasons": [],
    }

    # Part Number confidence
    if source.startswith("epl_text") or source.startswith("detail_text"):
        review["fields"]["Part Number"] = {"confidence": CONFIDENCE_HIGH}
    elif "correct_part_number" in str(row.get("_corrections", "")):
        review["fields"]["Part Number"] = {
            "confidence": CONFIDENCE_LOW,
            "reason": "Part number was auto-corrected — verify against drawing",
            "original": row.get("_original_pn", ""),
        }
    else:
        review["fields"]["Part Number"] = {"confidence": CONFIDENCE_MEDIUM}

    # Designation confidence
    desig = str(row.get("Designation", "")).strip()
    if not desig:
        review["fields"]["Designation"] = {
            "confidence": CONFIDENCE_MISSING,
            "reason": "No material designation found — check drawing notes",
        }
    elif material_source == "text_note":
        review["fields"]["Designation"] = {"confidence": CONFIDENCE_HIGH}
    elif material_source == "epl_column":
        review["fields"]["Designation"] = {"confidence": CONFIDENCE_HIGH}
    elif material_source == "std_parts_db":
        review["fields"]["Designation"] = {
            "confidence": CONFIDENCE_MEDIUM,
            "reason": f"From standard parts database — verify for this application",
        }
    elif material_source == "child_drawing":
        review["fields"]["Designation"] = {
            "confidence": CONFIDENCE_MEDIUM,
            "reason": "From child drawing title block — verify temper/condition",
        }
    else:
        review["fields"]["Designation"] = {
            "confidence": CONFIDENCE_LOW,
            "reason": "Vision-extracted — verify against drawing",
        }

    # Material Specification confidence
    spec = str(row.get("Material Specification", "")).strip()
    if not spec:
        # Missing spec isn't always an error — standard parts often have no spec on drawing
        if material_source == "std_parts_db":
            review["fields"]["Material Specification"] = {
                "confidence": CONFIDENCE_MEDIUM,
                "reason": "Standard part — spec from database, not drawing",
            }
        elif desig:
            # Has material but no spec — flag for review
            review["fields"]["Material Specification"] = {
                "confidence": CONFIDENCE_MISSING,
                "reason": f"Material '{desig}' found but no specification — check drawing",
            }
        else:
            review["fields"]["Material Specification"] = {
                "confidence": CONFIDENCE_MISSING,
            }
    elif spec_source == "text_note":
        review["fields"]["Material Specification"] = {"confidence": CONFIDENCE_HIGH}
    elif spec_source == "std_parts_db":
        review["fields"]["Material Specification"] = {
            "confidence": CONFIDENCE_MEDIUM,
            "reason": "From standard parts database",
        }
    else:
        review["fields"]["Material Specification"] = {"confidence": CONFIDENCE_LOW}

    # NHA confidence
    nha = str(row.get("NHA", "")).strip()
    if not nha:
        review["fields"]["NHA"] = {
            "confidence": CONFIDENCE_MISSING,
            "reason": "No NHA assignment — orphan part",
        }
    elif nha_source == "override":
        review["fields"]["NHA"] = {"confidence": CONFIDENCE_HIGH}
    elif nha_source in ("dt_high",):
        review["fields"]["NHA"] = {"confidence": CONFIDENCE_HIGH}
    elif nha_source in ("dt_medium", "epl_infer"):
        review["fields"]["NHA"] = {
            "confidence": CONFIDENCE_MEDIUM,
            "reason": "NHA inferred from drawing tree — verify hierarchy",
        }
    else:
        review["fields"]["NHA"] = {
            "confidence": CONFIDENCE_LOW,
            "reason": "NHA assignment uncertain — verify against drawing tree",
        }

    # Roll up: row confidence = worst field confidence
    confidence_rank = {CONFIDENCE_HIGH: 3, CONFIDENCE_MEDIUM: 2, CONFIDENCE_LOW: 1, CONFIDENCE_MISSING: 0}
    worst = min(
        confidence_rank.get(f.get("confidence", CONFIDENCE_HIGH), 0)
        for f in review["fields"].values()
    )
    review["row_confidence"] = {3: CONFIDENCE_HIGH, 2: CONFIDENCE_MEDIUM, 1: CONFIDENCE_LOW, 0: CONFIDENCE_MISSING}[worst]

    # Needs review if any field is LOW or MISSING
    review["needs_review"] = worst <= 1

    # Collect review reasons
    review["review_reasons"] = [
        f"{field}: {meta['reason']}"
        for field, meta in review["fields"].items()
        if meta.get("reason")
    ]

    return review
```

#### 1.4 Where to Call It

In `_process_assembly()` after building each row (around line 1429-1440):

```python
rows.append(row_dict)

# Tag confidence for review
review_meta = self._tag_confidence(
    row_dict,
    source="epl_text" if drawing.extraction_method == "text_layer" else "epl_vision",
    material_source=material_source,  # track this through the fallback chain
    spec_source=spec_source,          # track this through the fallback chain
    nha_source="epl_direct",
)
self._review_items.append(review_meta)
```

In `_create_detail_row()` after building the row (around line 1334-1347):

```python
review_meta = self._tag_confidence(
    row_dict,
    source="detail_text" if drawing.extraction_method == "text_layer" else "detail_vision",
    material_source="text_note" if drawing.material_spec else "none",
    spec_source="text_note" if drawing.material_spec else "none",
    nha_source=nha_source,
)
self._review_items.append(review_meta)
```

Add `self._review_items: List[Dict] = []` to `__init__`.

### Phase 2: Review JSON Export

Add `export_review()` to MIULBuilder:

```python
def export_review(self, output_path: Path) -> Dict[str, Any]:
    """Export review metadata as JSON for the review UI."""
    import json

    total = len(self._review_items)
    needs_review = sum(1 for r in self._review_items if r["needs_review"])
    high = sum(1 for r in self._review_items if r["row_confidence"] == CONFIDENCE_HIGH)
    medium = sum(1 for r in self._review_items if r["row_confidence"] == CONFIDENCE_MEDIUM)
    low = sum(1 for r in self._review_items if r["row_confidence"] == CONFIDENCE_LOW)
    missing = sum(1 for r in self._review_items if r["row_confidence"] == CONFIDENCE_MISSING)

    review_data = {
        "version": "1.0",
        "summary": {
            "total_rows": total,
            "needs_review": needs_review,
            "auto_approved": total - needs_review,
            "confidence_breakdown": {
                "high": high,
                "medium": medium,
                "low": low,
                "missing": missing,
            },
            "review_pct": round(needs_review / total * 100, 1) if total else 0,
        },
        "items": self._review_items,
    }

    with open(output_path, "w") as f:
        json.dump(review_data, f, indent=2)

    LOGGER.info(
        f"[MIULBuilder] Review export: {needs_review}/{total} rows need review "
        f"({review_data['summary']['review_pct']}%)"
    )
    return review_data
```

### Phase 3: Review API Endpoints (FastAPI)

Add to the MIUL API router:

```python
@router.get("/miul/{build_id}/review")
async def get_review(build_id: str):
    """Get review items for a MIUL build."""
    # Returns the review JSON with summary stats
    # UI renders: "MIRA extracted 104 rows. 87 look good. 17 need your eyes."

@router.get("/miul/{build_id}/review/items")
async def get_review_items(
    build_id: str,
    confidence: str = None,  # filter: "low", "missing", "medium"
    field: str = None,       # filter: "Designation", "NHA", etc.
):
    """Get filterable review items."""
    # UI can show: "Show me just the rows with missing MatSpec"

@router.post("/miul/{build_id}/review/items/{part_number}")
async def submit_correction(
    build_id: str,
    part_number: str,
    corrections: Dict[str, str],  # {"Designation": "A286 CRES", "Material Specification": "AMS 5737"}
):
    """Submit human corrections for a flagged row."""
    # Stores correction, marks item as reviewed
    # Returns updated row with correction applied

@router.post("/miul/{build_id}/review/approve")
async def approve_build(build_id: str, reviewer: str):
    """Approve the MIUL build after review."""
    # Checks all LOW/MISSING items have been reviewed
    # If not: returns list of unreviewed items
    # If yes: marks build as approved, exports final Excel
    # Stores reviewer name and timestamp for audit trail

@router.post("/miul/{build_id}/review/items/{part_number}/accept")
async def accept_as_is(build_id: str, part_number: str, reason: str = ""):
    """Accept a flagged item without changes (engineer says it's fine)."""
    # For when MIRA flags something but the human knows it's correct
    # Stores the acceptance with optional reason
```

### Phase 4: Review UI (React Component)

The review screen should feel like a checklist, not a spreadsheet editor.

#### 4.1 Summary Banner

```
┌──────────────────────────────────────────────────────────────────┐
│  MIUL Build: DMLLV — 104 rows extracted                         │
│                                                                  │
│  ██████████████████████░░░░░  87 auto-approved  │  17 need review│
│                                                                  │
│  [View All]  [Review Flagged Items ▸]                           │
└──────────────────────────────────────────────────────────────────┘
```

#### 4.2 Review Queue

Show only flagged items, grouped by reason:

```
┌──────────────────────────────────────────────────────────────────┐
│  ⚠ Missing Material Specification (8 items)                      │
├──────────────────────────────────────────────────────────────────┤
│                                                                  │
│  MER07543-001 │ Shaft Sub-Assembly, 10 Inch Valve               │
│  Designation: (empty)  │  MatSpec: (empty)  │  NHA: MER07540-001│
│  🔴 Assembly — no material expected                              │
│  [Accept As-Is ✓]  [Edit ✏]                                     │
│                                                                  │
│  WSM-137-C86  │ Retaining Ring, Exterior                        │
│  Designation: A286  │  MatSpec: (empty)  │  NHA: MER07540-001   │
│  🟡 Has material but no spec — check drawing or vendor data      │
│  [Accept As-Is ✓]  [Edit ✏]  [Lookup ↗]                        │
│                                                                  │
├──────────────────────────────────────────────────────────────────┤
│  ⚠ NHA Assignment Uncertain (4 items)                            │
├──────────────────────────────────────────────────────────────────┤
│                                                                  │
│  MER07588-001 │ Poppet, 10 Inch Valve                           │
│  NHA: MER07563-001 (from DT — medium confidence)                │
│  🟡 Verify this part belongs in Shaft Sub-Assembly               │
│  [Confirm ✓]  [Change NHA ✏]                                    │
│                                                                  │
├──────────────────────────────────────────────────────────────────┤
│  ⚠ Material From Standard Parts DB (5 items)                     │
├──────────────────────────────────────────────────────────────────┤
│                                                                  │
│  NAS509-6C  │ Nut, Jam, Drilled                                 │
│  Designation: A286 (150 KSI)  │  MatSpec: AMS 5525/5732/5737   │
│  🟢 From standard parts database — verify for this application   │
│  [Accept ✓]  [Edit ✏]                                           │
│                                                                  │
└──────────────────────────────────────────────────────────────────┘

Progress: ██████░░░░░░░░  5/17 reviewed  │  [Approve Build ▸]
```

#### 4.3 Edit Modal

When user clicks [Edit]:

```
┌──────────────────────────────────────────────────────────────────┐
│  Edit: MER07588-001 — Poppet, 10 Inch Valve                     │
│                                                                  │
│  Designation       [INCONEL 718____________]  ← prefilled        │
│  Material Spec     [UNS N07718, SAE AMS 5664]  ← prefilled      │
│  Process Spec      [SOLUTION TREAT AT 1900°F...]  ← prefilled   │
│  NHA               [MER07563-001__________]  ← dropdown          │
│                                                                  │
│  MIRA extracted:   INCONEL 718 (from drawing note 3)             │
│  Drawing source:   MER07588-001_DRW_-_08_RELEASED.pdf  [View ↗] │
│                                                                  │
│  [Cancel]  [Save Correction ✓]                                   │
└──────────────────────────────────────────────────────────────────┘
```

Key UX principle: **always show what MIRA extracted and where it came from.**
The human isn't filling in blanks — they're confirming or correcting MIRA's work.
This is faster and less error-prone than starting from scratch.

#### 4.4 Approval Gate

The [Approve Build] button is disabled until all LOW/MISSING items are either
corrected or explicitly accepted. When clicked:

- Generates final MIUL Excel with corrections applied
- Stamps reviewer name and timestamp
- Stores the review audit trail (what was flagged, what was changed, by whom)
- This audit trail is NASA-grade evidence for SWE-013 compliance

### Phase 5: Learning Loop (Future)

NOT for initial implementation but spec it so the architecture supports it:

When a human corrects a field, store the correction as a training pair:
- Input: what MIRA extracted + source context
- Output: what the human said it should be

Over time, these corrections feed back into:
- Standard parts DB (if a standard part's spec was wrong, fix it globally)
- Normalization rules (if James always writes "7075-T651 ALUMINUM" instead of
  "ALUMINUM ALLOY 7075-T651", learn that format preference)
- Confidence calibration (if MIRA flags something as LOW but humans always
  accept it, maybe it's actually MEDIUM)

### Integration Points

#### builder.py Changes

1. Add `_review_items: List[Dict] = []` to `MIULBuilder.__init__`
2. Add `extraction_method: str = ""` to `DrawingData` dataclass
3. Track `material_source` and `spec_source` through fallback chains in
   `_process_assembly()` and `_create_detail_row()`
4. Call `_tag_confidence()` after each row is built
5. Add `export_review()` method
6. Add confidence constants at module level

#### API Changes

1. New router: `/api/v1/miul/{build_id}/review/...`
2. Review state stored per build (JSON file or DB, TBD)
3. Corrections endpoint applies edits to in-memory DataFrame
4. Approve endpoint triggers final Excel export with corrections

#### Frontend Changes

1. New ReviewQueue component
2. Summary banner with progress bar
3. Inline edit modal with source citation
4. Approval gate with audit trail

### Tone and Language

This is critical. The UI language must feel collaborative, not adversarial.

**YES:**
- "MIRA found 87 rows it's confident about. 17 could use your expertise."
- "This material spec came from the standard parts database — does it look right for this application?"
- "MIRA couldn't find a material spec for this part. Can you check the drawing?"

**NO:**
- "17 ERRORS FOUND — REVIEW REQUIRED"
- "WARNING: Low confidence extraction"
- "Unverified data — do not use without review"

The engineer using this should feel like MIRA is their smart assistant, not
a system they have to babysit.

### Priority

1. Confidence tagger in builder.py (can demo tomorrow as JSON output)
2. Review JSON export (enables any UI to consume it)
3. Review API endpoints
4. Review UI component
5. Learning loop (Phase 5, future)

Steps 1-2 are backend only and can be done today. Steps 3-4 need frontend
work. Step 5 is post-demo.

### File Locations

- `builder.py` — confidence tagger, review export
- `text_extract.py` — already tags `source: "text_layer"`
- API router — new file, `miul_review.py` or add to existing MIUL router
- Frontend — new component in MIRA React app
