# MIUL Builder v2.3 Specification

## Architecture: PDF → Vision (Direct)

Claude Vision API accepts PDFs directly. No image conversion needed.

```
PDF file → Claude Vision (type: document) → Structured JSON → MIUL
                    ↓
           Text extraction (PyMuPDF) → Post-validation filter
```

## Core Principle

**Vision gets the PDF ONLY. Text is for validation, NOT in the prompt.**

The v1 architecture proved this works:
- Vision sees what a human sees
- Text extraction provides ground truth for post-validation
- NO text in the vision prompt - that causes confusion/hallucination

## 3-Phase Pipeline

### Phase 1: Ingest
```
Input: PDF file
Output: PDF bytes per page + page_id + extracted text

Operations:
1. Open PDF with PyMuPDF
2. For each page:
   - Extract single-page PDF bytes
   - Compute page_id = sha256(pdf_bytes)[:16]
   - Extract text (for validation)
```

### Phase 2: Extract (Vision)
```
Input: Single-page PDF bytes
Output: Structured extraction (title block, BOM, occurrences)

Operations:
1. Check cache by (page_id, prompt_version, model_version)
2. If not cached:
   - Send PDF to Claude Vision: {"type": "document", "media_type": "application/pdf"}
   - Prompt asks for structured JSON output
   - NO TEXT IN PROMPT
3. Post-validate against text extraction
4. Cache result
```

### Phase 3: Assemble + Build
```
Input: All page extractions
Output: MIUL Excel

Operations:
1. Bind pages to drawings (zone-weighted scoring)
2. Build drawing hierarchy graph
3. DFS tree walk to collect MIUL rows
4. Generate Excel output
```

## Vision API Call Format

```python
message = anthropic.messages.create(
    model="claude-sonnet-4-20250514",
    max_tokens=4096,
    messages=[{
        "role": "user",
        "content": [
            {
                "type": "document",
                "source": {
                    "type": "base64",
                    "media_type": "application/pdf",
                    "data": pdf_bytes_base64,
                },
            },
            {
                "type": "text",
                "text": EXTRACTION_PROMPT,  # NO extracted text here!
            },
        ],
    }],
)
```

## Extraction Prompt (v1-proven anti-hallucination rules)

The prompt uses battle-tested rules from v1:

```
CRITICAL ANTI-HALLUCINATION RULES:
1. Extract ONLY part numbers that are CLEARLY VISIBLE
2. If you cannot read a part number clearly, SKIP IT - do not guess
3. SKIP rows marked "ITEM NOT SHOWN", "NOT SHOWN", "-", or blank
4. DO NOT invent fasteners - MS20002, MS35206, MS35338 series are commonly hallucinated
5. Copy part numbers EXACTLY as shown - character for character
6. If unsure about a digit or letter, SKIP that part entirely
```

Key fields extracted:
- **title_block**: drawing_number, revision, title, cage_code, nha_part_number, material_designation, material_spec, uns_number
- **drawing_type**: DETAIL or ASSEMBLY
- **parts_list**: find_no, part_number, description, quantity, material_callout, spec_callout, finish_callout
- **hardware_callouts**: raw_text, standard, size, quantity, material

## Post-Validation Filter

Text extraction is used ONLY for validation AFTER vision returns:

```python
def post_validate(vision_result: dict, text_pns: set[str]) -> dict:
    """
    Cross-check vision output against text extraction.

    - If vision found PN not in text: flag as LOW_CONFIDENCE
    - If text has PN not in vision: add as TEXT_ONLY occurrence
    """
    for part in vision_result["parts_list"]:
        if part["part_number"] not in text_pns:
            part["confidence"] = 0.5  # Lower confidence
            part["validation_flag"] = "NOT_IN_TEXT"

    return vision_result
```

## Cache Strategy

Cache key: `sha256(page_id + prompt_version + model_version)[:32]`

Vision calls are expensive. Cache aggressively.
- Cache is invalidated if prompt or model changes
- page_id is content-based, so same drawing = cache hit

## Models

```
PageIngest:
  page_id: str            # sha256(pdf_bytes)[:16]
  pdf_path: Path
  page_number: int
  pdf_bytes: bytes        # Single-page PDF
  text: str               # Extracted text (for validation)

PageExtract:
  page_id: str
  title_block: TitleBlock
  parts_list: list[BOMRow]
  occurrences: list[Occurrence]
  validation_flags: list[str]
```

## Key Differences from v2.2

| v2.2 (broken) | v2.3 (fixed) |
|---------------|--------------|
| PDF → PNG images | PDF → direct to Claude |
| Text IN vision prompt | Text for post-validation only |
| "Anti-hallucination anchoring" | Post-validation filter |
| Complex hybrid approach | Simple: PDF → vision |

## Implementation Files

```
mira/miul/v2/
├── SPEC.md          # This file
├── models.py        # Data models (mostly unchanged)
├── ingest.py        # PDF → page PDF bytes + text
├── extract.py       # Vision API calls (PDF direct)
├── assemble.py      # Page binding
├── graph.py         # Hierarchy graph
├── miul.py          # Tree walk, MIUL generation
└── cli.py           # Pipeline orchestration
```

## What NOT to Do

1. **DO NOT** put extracted text in the vision prompt
2. **DO NOT** convert PDF to images (Claude handles this internally)
3. **DO NOT** use "hybrid" approaches mixing text with vision input
4. **DO NOT** over-engineer - simple PDF → vision → validation works
