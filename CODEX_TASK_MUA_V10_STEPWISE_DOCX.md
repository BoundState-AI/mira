# CODEX TASK: MUA V10 — Stepwise UI + DOCX Generation

**Priority:** High
**Files to modify:** 3 existing + 2 new
**Test against:** The 11 MUAs in `/mnt/user-data/outputs/MUA_*.docx` — output must match format

---

## Context

The MUA V10 classifier pipeline (classifier.py, pipeline.py, rationale.py, models.py, screening.py, domain_facts.py) is **correct and complete**. Do not modify the classifier logic.

Two problems exist in the presentation layer:

1. **Frontend dumps all results at once.** Should walk the user through 5 steps, showing reasoning at each step before proceeding.
2. **No .docx output.** The API returns `Form551Fields` JSON but nothing renders it into an actual MSFC Form 551 .docx document. The user needs a downloadable .docx identical to the reference MUAs.

---

## CHANGE 1: New Backend Endpoint — `/api/mua/v10/generate-docx`

**New file:** `mira/mua/classifier/docx_renderer.py`

This module takes a `Form551Fields` object and returns a .docx buffer using `python-docx`.

### Requirements

The .docx must match the format of the reference MUAs. It is NOT a 7-section report. It is a form with labeled fields and tables.

### Reference Layout (what the .docx must look like)

```
┌──────────────────────────────────────────────────┐
│  NATIONAL AERONAUTICS AND SPACE ADMINISTRATION   │
│       MARSHALL SPACE FLIGHT CENTER               │
│       MATERIAL USAGE AGREEMENT                   │
├──────────────────────────────────────────────────┤
│ MUA No: [mua_number]    │ Category: [category]   │
│ Date:   [date]          │ Standard: NASA-STD-6016C│
│ Project:[project]       │ System:   [system]      │
├──────────────────────────────────────────────────┤
│ MATERIAL IDENTIFICATION                          │
│ Material:      [material_designation]             │
│ MAPTIS Code:   [maptis_code]                     │
│ Specification: [material_specification]           │
│ Material Class:[material_class]                   │
│ Issue:         [issue]                            │
│ Rating:        [rating] + decoded meaning         │
├──────────────────────────────────────────────────┤
│ OPERATING ENVIRONMENT                            │
│ Media: [media]       │ Pressure: [pressure]       │
│ Temperature: [temperature] │ Location: [location]  │
├──────────────────────────────────────────────────┤
│ PART NUMBER(S)                                   │
│ [part_count] part occurrence(s):                  │
│   - [part_numbers[0]]                            │
│   - [part_numbers[1]]                            │
├──────────────────────────────────────────────────┤
│ APPLICATION                                      │
│ [application text]                                │
├──────────────────────────────────────────────────┤
│ RATIONALE                                        │
│ [rationale text - 2-5 sentences]                  │
├──────────────────────────────────────────────────┤
│ DISPOSITION                                      │
│ [disposition text]                                │
├──────────────────────────────────────────────────┤
│ APPROVALS                                        │
│ Prepared by (Materials Engineer): _______ Date:__ │
│ Reviewed by (Hardware Manager):   _______ Date:__ │
│ Approved by (M&P Branch Chief):   _______ Date:__ │
├──────────────────────────────────────────────────┤
│ Governing Standard: NASA-STD-6016C │ MUA ID: ... │
└──────────────────────────────────────────────────┘
```

### Implementation skeleton

Use `python-docx` to create a Document with:
- Page margins: 2cm top/bottom, 2.5cm left/right
- Font: Arial 10pt throughout
- Title block: centered, bold, 11pt/14pt
- Header table: 3 rows x 4 cols with Table Grid style (label cols bold)
- Section headers: bold, 10pt, color #2F5496
- Material ID: 6-row x 2-col table (label | value)
- Environment: 2-row x 4-col table
- Parts: bulleted list with 1cm indent
- Application, Rationale, Disposition: plain paragraphs
- Approvals: 3 signature lines with underscores
- Footer: italic 8pt gray

Return `io.BytesIO` buffer with `.getvalue()` → bytes.

### Add endpoint to router

**Modify:** `mira/api/routers/mua_v10.py`

Add after existing `/classify-row`:

```python
from fastapi.responses import StreamingResponse
from mira.mua.classifier.docx_renderer import render_form551_docx
import io

@router.post("/generate-docx")
async def generate_docx(request: ClassifyRowRequest) -> StreamingResponse:
    pipeline_result = await classify_row(request)
    if not pipeline_result.forms:
        raise HTTPException(status_code=400, detail="No automatable MUAs found.")
    form = pipeline_result.forms[0]
    if not form.date:
        from datetime import date as dt
        form.date = str(dt.today())
    if not form.project and request.project:
        form.project = request.project
    if not form.system and request.system:
        form.system = request.system
    docx_bytes = render_form551_docx(form)
    filename = f"MUA_{form.issue}_{form.maptis_code}.docx"
    return StreamingResponse(
        io.BytesIO(docx_bytes),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
```

### Dependency

Add `python-docx>=1.1.0` to requirements.

---

## CHANGE 2: Stepwise Frontend

**Modify:** `frontend/src/pages/MUAV10.tsx`

Replace single-form-dump UI with 5-step wizard matching Dr. Wilde's five questions.

### Step Flow

```
Step 1: "Who What Where"
  Input: MAPTIS code, material designation, material class, media,
         environment, pressure, temperature, part numbers
  Display: summary of what we're looking at
  Button: "Next →"

Step 2: "Why is MAPTIS bitching?"
  Input: Rating fields (FLAM, FS, TOX, TVS, SCC, CORR)
  Inline: as user types each rating letter, show decoded meaning immediately
  Button: "Classify →" (calls /classify-row API)

Step 3: "Is the bitching even correct?"
  Display per flag:
    - Material-class gate result
    - Hazard check result
  Color: Green = no MUA needed, Yellow = automatable, Red = needs engineer
  Button: "Next →"

Step 4: "Why should there be no bitching?"
  Display per automatable flag: generated rationale (EDITABLE by engineer)
  Display per human flag: "Needs engineering judgment: [reason]"
  Button: "Generate MUA →"

Step 5: "Download MUA"
  Per automatable flag: "Download .docx" button → calls /generate-docx
  Show Form 551 summary
```

### Client-Side Rating Decoder (for Step 2 inline hints)

```typescript
const RATING_HINTS: Record<string, Record<string, string>> = {
  FLAM: {
    A: "Pass — ≥5 samples, burn ≤6.0 inches",
    C: "FAIL — burn >6.0 inches in promoted combustion",
    I: "Incomplete pass — <5 samples, all passing. Administrative gap.",
    S: "Special test — needs manual review of test report",
    U: "No usable test data exists",
  },
  FS: {
    A: "Pass — 48hr screening in hydrazine/MMH/N2O4",
    U: "Untested — no Test 15 data (Test 15 = hydrazine/N2O4 only)",
  },
  TOX: {
    A: "Pass — TML ≤1.0%, CVCM ≤0.1%",
    U: "Untested for offgassing",
    K: "UNKNOWN — not documented. Probable MIUL builder error.",
  },
  TVS: {
    A: "Pass — meets ASTM E595",
    C: "FAIL — exceeds outgassing criteria",
    U: "Untested",
  },
  SCC: {
    A: "Resistant", B: "Conditional — batch/lot verification needed",
    C: "Susceptible under certain conditions", N: "Not applicable", U: "Untested",
  },
  CORR: {
    A: "Resistant", B: "Conditional — batch/lot verification needed", U: "Untested",
  },
};
```

### Key UI Requirements

1. Steps are sequential — don't show Step 3 until Step 2 is submitted
2. Steps 1-2 = input, Steps 3-5 = output/review
3. Step 2 shows inline decoded meanings as user types
4. Step 4 rationale MUST be editable (engineer owns final text)
5. Step 5 download button calls `/api/mua/v10/generate-docx`
6. "Start Over" button always visible

### .docx Download Helper

```typescript
async function downloadDocx(request: ClassifyRowRequest, flag: { issue: string; rating: string }) {
  const singleFlagRequest = { ...request, ratings: { [flag.issue]: flag.rating } };
  const response = await fetch('/api/mua/v10/generate-docx', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(singleFlagRequest),
  });
  if (!response.ok) throw new Error('Failed to generate .docx');
  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `MUA_${flag.issue}_${request.maptis_code}.docx`;
  a.click();
  URL.revokeObjectURL(url);
}
```

---

## CHANGE 3: API Client Update

**Modify:** `frontend/src/lib/mua-v10-api.ts`

Add `generateMuaDocx` function that POSTs to `/api/mua/v10/generate-docx` and returns a Blob. Existing `classifyMuaV10Row` stays as-is.

---

## Testing

Use this input (validated A286 CRES):

```json
{
  "maptis_code": "10392",
  "material_designation": "A286 CRES (UNS K66286)",
  "material_class": "metal",
  "media": "GH2",
  "environment": "non-habitable",
  "ratings": { "FLAM": "A", "FS": "U", "SCC": "A", "CORR": "A", "TOX": "", "TVS": "" },
  "project": "DMLLV",
  "system": "10-Inch H2 Valve (In-Space Refueling)",
  "pressure": "6000 psia",
  "temperature": "-423 to 200 degF"
}
```

Expected: FS=U → THIN_SCREENING → Category II → downloadable .docx with Test 15/hydrazine rationale. TOX/TVS blanks on metal → "Not applicable, skip."

---

## DO NOT MODIFY

- `classifier.py`, `pipeline.py`, `rationale.py`, `models.py`, `screening.py`, `domain_facts.py` — all correct and complete
