#!/usr/bin/env python3
"""
Module: Vision Extractor (v4)
Purpose: Sonnet Vision-based MIUL material extraction with banked 3-phase pipeline.

Architecture: OCR Bank -> Sonnet Bank -> Compare
  Phase 1 (OCR Bank):    All PDFs -> local OCR + image render -> banked results (free, instant)
  Phase 2 (Sonnet Bank): All banked pages -> Sonnet Vision in parallel -> banked results
  Phase 3 (Compare):     OCR bank vs Sonnet bank -> flag gaps -> HITL review

This prevents proxy timeouts by doing all heavy I/O upfront in parallel
instead of sequential page-by-page Sonnet calls that take 10+ minutes.

BoundState AI 2025
Version: 4.1.0
Classification: BoundState Proprietary

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: SWE-013, NASA-STD-8739.8B
Safety Critical: False (extraction only - safety gates applied downstream)
"""

from __future__ import annotations

import json
import logging
import os
import re
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Reuse existing v3 infrastructure - no need to rebuild
from .v3.extract import VisionClient, pdf_to_images
from .v3.text_extract import extract_drawing as extract_ocr_text, has_text_layer

LOGGER = logging.getLogger(__name__)

# Confidence threshold: items below this go to HITL review
REVIEW_THRESHOLD = 0.7

# Field classification for smart HITL:
#   REQUIRED - flag if missing or low confidence (designation only)
#   EXPECTED - flag only if confidence < 0.5 AND in gaps (material_spec, material_form, process_spec)
#   OPTIONAL - never flag as a gap (uns_code -- looked up from designation during build)
# Rationale: material_spec (e.g. "SAE AMS 4027") is rarely printed on drawings.
# It's looked up from designation during MIUL build via alloy_normalizer + material_code_lookup.
REQUIRED_FIELDS = {"designation"}
EXPECTED_FIELDS = {"material_spec", "material_form", "process_spec"}
OPTIONAL_FIELDS = {"uns_code"}
EXPECTED_THRESHOLD = 0.5  # lower bar for "expected" fields

# Max pages to process per PDF (safety limit)
MAX_PAGES_PER_PDF = 50

# Max concurrent Sonnet API calls (Anthropic rate limit friendly)
MAX_SONNET_WORKERS = 4


# =============================================================================
# Data Models
# =============================================================================

@dataclass(frozen=True)
class ExtractionEvidence:
    """Immutable record of where a piece of data came from."""
    source_page: int
    source_location: str   # "title_block", "notes", "epl_row", "flag_note", "detail_view"
    source_text: str
    confidence: float


@dataclass
class ExtractedMaterial:
    """Single material row extracted by Sonnet Vision."""
    part_number: str
    part_description: str
    designation: Optional[str] = None
    material_spec: Optional[str] = None
    process_spec: Optional[str] = None
    uns_code: Optional[str] = None
    material_form: Optional[str] = None
    quantity: int = 1
    nha: Optional[str] = None
    source_file: str = ""
    source_page: int = 0
    confidence: Dict[str, float] = field(default_factory=dict)
    gaps: List[str] = field(default_factory=list)
    gap_reasons: List[str] = field(default_factory=list)
    evidence: List[ExtractionEvidence] = field(default_factory=list)

    @property
    def worst_confidence(self) -> float:
        """Lowest confidence across all fields."""
        if not self.confidence:
            return 0.0
        return min(self.confidence.values())

    @property
    def needs_review(self) -> bool:
        """Smart HITL: only flag when it actually matters.

        - REQUIRED (designation): flag if < 0.7 or in gaps
        - EXPECTED (material_spec, material_form, process_spec): flag only
          if 0 < conf < 0.5 (Sonnet saw something but wasn't confident)
        - OPTIONAL (uns_code): never flag -- looked up later from designation
        """
        # Check required fields
        for f in REQUIRED_FIELDS:
            if f in self.gaps:
                return True
            if self.confidence.get(f, 0.0) < REVIEW_THRESHOLD:
                return True

        # Check expected fields (lower bar)
        # Only flag if Sonnet SAW something but wasn't confident (0 < conf < 0.5).
        # Confidence 0.0 means "not on this page at all" -- that's normal, not a flag.
        for f in EXPECTED_FIELDS:
            conf = self.confidence.get(f, 0.0)
            if 0.0 < conf < EXPECTED_THRESHOLD:
                return True

        return False


@dataclass
class ExtractionResult:
    """Complete extraction result for a drawing set."""
    extraction_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    materials: List[ExtractedMaterial] = field(default_factory=list)
    dt_context: Optional[Dict[str, Any]] = None
    summary: Dict[str, Any] = field(default_factory=dict)
    audit_trail: List[Dict[str, Any]] = field(default_factory=list)

    def compute_summary(self) -> Dict[str, Any]:
        """Compute summary stats from materials list."""
        total = len(self.materials)
        needs_review = sum(1 for m in self.materials if m.needs_review)
        self.summary = {
            "total_materials": total,
            "needs_review": needs_review,
            "auto_approved": total - needs_review,
        }
        return self.summary

    def to_dict(self) -> Dict[str, Any]:
        """Serialize for JSON storage/API response."""
        return {
            "extraction_id": self.extraction_id,
            "timestamp": self.timestamp,
            "materials": [_material_to_dict(m) for m in self.materials],
            "dt_context": self.dt_context,
            "summary": self.summary,
            "audit_trail": self.audit_trail,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ExtractionResult":
        """Deserialize from stored JSON."""
        result = cls(
            extraction_id=data["extraction_id"],
            timestamp=data["timestamp"],
            dt_context=data.get("dt_context"),
            summary=data.get("summary", {}),
            audit_trail=data.get("audit_trail", []),
        )
        for m in data.get("materials", []):
            result.materials.append(_material_from_dict(m))
        return result


def _material_to_dict(m: ExtractedMaterial) -> Dict[str, Any]:
    return {
        "part_number": m.part_number,
        "part_description": m.part_description,
        "designation": m.designation,
        "material_spec": m.material_spec,
        "process_spec": m.process_spec,
        "uns_code": m.uns_code,
        "material_form": m.material_form,
        "quantity": m.quantity,
        "nha": m.nha,
        "source_file": m.source_file,
        "source_page": m.source_page,
        "confidence": m.confidence,
        "gaps": m.gaps,
        "gap_reasons": m.gap_reasons,
        "evidence": [
            {
                "source_page": e.source_page,
                "source_location": e.source_location,
                "source_text": e.source_text,
                "confidence": e.confidence,
            }
            for e in m.evidence
        ],
    }


def _material_from_dict(d: Dict[str, Any]) -> ExtractedMaterial:
    return ExtractedMaterial(
        part_number=d["part_number"],
        part_description=d.get("part_description", ""),
        designation=d.get("designation"),
        material_spec=d.get("material_spec"),
        process_spec=d.get("process_spec"),
        uns_code=d.get("uns_code"),
        material_form=d.get("material_form"),
        quantity=d.get("quantity", 1),
        nha=d.get("nha"),
        source_file=d.get("source_file", ""),
        source_page=d.get("source_page", 0),
        confidence=d.get("confidence", {}),
        gaps=d.get("gaps", []),
        gap_reasons=d.get("gap_reasons", []),
        evidence=[
            ExtractionEvidence(**e) for e in d.get("evidence", [])
        ],
    )


# =============================================================================
# Banked Page Data -- intermediate structure between phases
# =============================================================================

@dataclass
class BankedPage:
    """One page's worth of OCR + image data, ready for Sonnet."""
    pdf_name: str
    page_number: int
    drawing_number: str
    image_b64: str
    ocr_json: str              # serialized OCR result
    dt_context: Optional[Dict[str, Any]]
    ocr_result: Dict[str, Any]  # raw OCR dict for comparison


# =============================================================================
# Prompts
# =============================================================================

SYSTEM_PROMPT = """\
You are a PRECISION engineering drawing parser for NASA/MSFC aerospace drawings.
You extract material data for MIUL (Material Identification and Usage List) generation.
You receive both the drawing IMAGE and OCR-extracted text (which may contain errors).

GOLDEN RULES:
1. Extract ONLY what you can CLEARLY SEE in the image. Never guess or infer.
2. When OCR text disagrees with the image, TRUST THE IMAGE.
3. Skip any part you cannot read with high confidence.
4. Report gaps honestly - say what's missing and where the user should look.\
"""

PASS1_PROMPT_TEMPLATE = """\
You are verifying and completing material data extracted by OCR from an engineering drawing.
The OCR system already extracted structured data (below). Your job:
1. VERIFY the OCR output against what you SEE in the drawing image
2. CORRECT any OCR errors (the image is ground truth)
3. FLAG any holes where OCR missed data that IS visible on the drawing
4. REPORT gaps where data genuinely isn't on this page

## OCR EXTRACTED DATA (machine-extracted, may contain errors)
```
{ocr_text}
```

## DRAWING TREE CONTEXT (parts expected on this drawing)
{dt_context}

## WHAT TO VERIFY AND EXTRACT
For EACH part visible on this drawing, verify or extract:
1. Part Number (exact, from EPL or title block)
2. Part Description / Document Title
3. Material Designation (e.g., "INCONEL 718", "AL 6061-T6", "A286 CRES")
4. Material Specification (e.g., "SAE AMS 5664", "ASTM B209")
5. Process Specification (e.g., "ANODIZE PER MIL-A-8625, TYPE II")
6. UNS Code (e.g., "N07718", "S66286")
7. Material Form (SHEET, PLATE, BAR, ROD, TUBE, FORGING, CASTING, WIRE)
8. Quantity

## WHERE TO LOOK (check ALL locations)
- Title block MATERIAL field (lower right)
- Numbered NOTES section ("3. MATERIAL: ...")
- EPL (Engineering Parts List) MATERIAL column
- Flag notes (balloons with note numbers pointing to features)
- Detail view callouts

## HANDLING OCR vs IMAGE DISAGREEMENTS
The OCR text may contain errors. Common ones:
- 3O4 should be 304 (zero vs letter O)
- INCONE1 should be INCONEL (one vs letter L)
- 6O61 should be 6061
- Si3N4 misread as S3H4, S3N4, S2N4
When you see a discrepancy, use what the IMAGE shows.

## CHARACTER ACCURACY (read twice)
- 5 vs 8: curved top = 5, two loops = 8
- 0 vs O vs D: zero often has slash/dot
- H vs N: H has horizontal bar, N has diagonal
- W vs M: W points down, M points up
- S vs 5: S has no straight segments

## CONFIDENCE SCORING
For each field, assign confidence (0.0-1.0):
- 1.0: Clearly visible in image AND matches OCR
- 0.8: Clearly visible in image, OCR had error you corrected
- 0.6: Partially visible, inferred from context
- 0.3: Not directly visible, inferred from part type or related notes
- 0.0: Not found anywhere on this page

## GAP IDENTIFICATION
If you CANNOT find a field, explicitly say so with an actionable reason.
Example: "Material spec not found for MER07588-001 - check sheet 2 notes section"

## OUTPUT FORMAT
Return ONLY valid JSON (no markdown fences, no explanation):
{{
  "drawing_type": "ASSEMBLY" or "DETAIL",
  "drawing_number": "from title block",
  "materials": [
    {{
      "part_number": "exact part number",
      "part_description": "name/title",
      "designation": "material name or null",
      "material_spec": "spec reference or null",
      "process_spec": "process spec or null",
      "uns_code": "UNS code or null",
      "material_form": "form or null",
      "quantity": 1,
      "confidence": {{
        "part_number": 1.0,
        "designation": 0.8,
        "material_spec": 0.6,
        "process_spec": 0.0,
        "material_form": 0.6
      }},
      "evidence": [
        {{
          "source_location": "notes",
          "source_text": "3. MATERIAL: A286 CRES, UNS S66286, PER SAE AMS 5737",
          "confidence": 0.9
        }}
      ],
      "gaps": ["process_spec"],
      "gap_reasons": ["No process specification found - check notes section for surface treatment callouts"]
    }}
  ]
}}\
"""

PASS2_PROMPT_TEMPLATE = """\
This is a TARGETED second pass. On the first pass, some fields had gaps or low confidence.

## FIRST PASS RESULTS (what was already extracted)
```json
{pass1_results}
```

## OCR TEXT
```
{ocr_text}
```

## SPECIFIC GAPS TO RESOLVE
{gap_list}

## INSTRUCTIONS
Look SPECIFICALLY at these locations on the drawing to fill the gaps above:
- Notes section: Read every numbered note carefully
- EPL table: Check MATERIAL/REMARKS column for each flagged part
- Title block: Check MATERIAL field
- Flag notes: Follow balloon numbers to their corresponding notes
- Detail views: Look for local material callouts near specific features

Return the SAME JSON format as before, but ONLY include the parts that had gaps.
Update their confidence scores and fill in any fields you can now see.
If you still cannot find a field after this focused look, keep the gap - it will go to the user.

Return ONLY valid JSON.\
"""


# =============================================================================
# Main Extractor -- 3-Phase Banked Architecture
# =============================================================================

class MIULVisionExtractor:
    """
    Sonnet Vision-based MIUL material extractor.

    3-Phase Banked Pipeline:
      Phase 1 (OCR Bank):    All PDFs -> OCR + render -> list[BankedPage]  (instant)
      Phase 2 (Sonnet Bank): BankedPages -> Sonnet Vision in parallel     (fast)
      Phase 3 (Compare):     Merge Sonnet results + flag gaps -> HITL

    This replaces the old sequential page-by-page approach that caused
    proxy timeouts on large drawing sets.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        max_workers: int = MAX_SONNET_WORKERS,
    ):
        self._vision = VisionClient(api_key=api_key)
        if model:
            self._vision.model = model
        self._max_workers = max_workers

    # =====================================================================
    # Phase 1: OCR Bank -- local OCR + image render for every page
    # =====================================================================

    def _phase1_ocr_bank(
        self,
        pdf_paths: List[Path],
        dt_json: Dict[str, Any],
        result: ExtractionResult,
    ) -> List[BankedPage]:
        """
        Phase 1: Run local OCR + render images for ALL pages across ALL PDFs.

        Free. Instant. No API calls. Builds the bank of pages ready for Sonnet.
        """
        bank: List[BankedPage] = []

        for pdf_path in pdf_paths:
            if self._is_dt_pdf(pdf_path):
                LOGGER.info(f"[Phase1] Skipping DT PDF: {pdf_path.name}")
                continue

            drawing_number = _extract_drawing_number(pdf_path)
            dt_context = _get_dt_context(dt_json, drawing_number)

            # --- OCR ---
            ocr_result: Dict[str, Any] = {}
            if has_text_layer(pdf_path):
                try:
                    ocr_result = extract_ocr_text(pdf_path)
                    LOGGER.info(
                        f"[Phase1] OCR: {pdf_path.name} -> "
                        f"type={ocr_result.get('drawing_type', '?')}, "
                        f"epl={ocr_result.get('has_epl', False)}, "
                        f"material={ocr_result.get('title_block', {}).get('material', 'none')}"
                    )
                except Exception as e:
                    LOGGER.warning(f"[Phase1] OCR failed: {pdf_path.name}: {e}")

            ocr_json = json.dumps(ocr_result, indent=2) if ocr_result else ""

            result.audit_trail.append({
                "event": "phase1_ocr",
                "file": pdf_path.name,
                "has_text_layer": bool(ocr_result),
                "drawing_type": ocr_result.get("drawing_type", "unknown"),
                "timestamp": _now(),
            })

            # --- Render pages to images ---
            try:
                page_images = pdf_to_images(pdf_path)
            except Exception as e:
                LOGGER.error(f"[Phase1] Render failed: {pdf_path.name}: {e}")
                result.audit_trail.append({
                    "event": "phase1_render_failed",
                    "file": pdf_path.name,
                    "error": str(e),
                    "timestamp": _now(),
                })
                continue

            if len(page_images) > MAX_PAGES_PER_PDF:
                page_images = page_images[:MAX_PAGES_PER_PDF]

            # --- Bank each page ---
            for page_num, img_b64 in enumerate(page_images, 1):
                bank.append(BankedPage(
                    pdf_name=pdf_path.name,
                    page_number=page_num,
                    drawing_number=drawing_number,
                    image_b64=img_b64,
                    ocr_json=ocr_json,
                    dt_context=dt_context,
                    ocr_result=ocr_result,
                ))

        LOGGER.info(f"[Phase1] OCR Bank complete: {len(bank)} pages from {len(pdf_paths)} PDFs")
        result.audit_trail.append({
            "event": "phase1_complete",
            "total_pages_banked": len(bank),
            "timestamp": _now(),
        })

        return bank

    # =====================================================================
    # Phase 2: Sonnet Bank -- parallel vision calls for all banked pages
    # =====================================================================

    def _phase2_sonnet_bank(
        self,
        bank: List[BankedPage],
        result: ExtractionResult,
    ) -> Dict[int, List[ExtractedMaterial]]:
        """
        Phase 2: Send ALL banked pages to Sonnet Vision in parallel.

        Uses ThreadPoolExecutor with MAX_SONNET_WORKERS concurrent calls.
        Returns dict mapping bank index -> extracted materials.
        """
        if not bank:
            return {}

        LOGGER.info(
            f"[Phase2] Sending {len(bank)} pages to Sonnet "
            f"({self._max_workers} workers)"
        )

        results_by_idx: Dict[int, List[ExtractedMaterial]] = {}

        def _process_one(idx: int, page: BankedPage) -> Tuple[int, List[ExtractedMaterial]]:
            """Single Sonnet call for one banked page (runs in thread)."""
            materials = self._extract_single_page(
                page_image_b64=page.image_b64,
                ocr_text=page.ocr_json,
                dt_context=page.dt_context,
                source_file=page.pdf_name,
                page_number=page.page_number,
            )
            return idx, materials

        with ThreadPoolExecutor(max_workers=self._max_workers) as executor:
            futures = {
                executor.submit(_process_one, idx, page): (idx, page)
                for idx, page in enumerate(bank)
            }

            for future in as_completed(futures):
                idx, page = futures[future]
                try:
                    _, materials = future.result()
                    results_by_idx[idx] = materials

                    result.audit_trail.append({
                        "event": "phase2_vision_complete",
                        "file": page.pdf_name,
                        "page": page.page_number,
                        "materials_found": len(materials),
                        "timestamp": _now(),
                    })

                    LOGGER.info(
                        f"[Phase2] Done: {page.pdf_name} p{page.page_number} "
                        f"-> {len(materials)} materials"
                    )

                except Exception as e:
                    LOGGER.error(
                        f"[Phase2] Failed: {page.pdf_name} p{page.page_number}: {e}"
                    )
                    results_by_idx[idx] = []
                    result.audit_trail.append({
                        "event": "phase2_vision_failed",
                        "file": page.pdf_name,
                        "page": page.page_number,
                        "error": str(e),
                        "timestamp": _now(),
                    })

        total_materials = sum(len(mats) for mats in results_by_idx.values())
        LOGGER.info(f"[Phase2] Sonnet Bank complete: {total_materials} materials from {len(bank)} pages")
        result.audit_trail.append({
            "event": "phase2_complete",
            "total_materials": total_materials,
            "timestamp": _now(),
        })

        return results_by_idx

    # =====================================================================
    # Phase 3: Compare -- merge results, assign NHA, flag gaps
    # =====================================================================

    def _phase3_compare(
        self,
        bank: List[BankedPage],
        sonnet_results: Dict[int, List[ExtractedMaterial]],
        result: ExtractionResult,
    ) -> None:
        """
        Phase 3: Merge Sonnet bank results into final ExtractionResult.

        For each page:
        - Take Sonnet's extraction as primary (image is ground truth)
        - Assign NHA from DT context
        - Append to result.materials

        Remaining gaps go to HITL review via identify_review_items().
        """
        for idx, page in enumerate(bank):
            materials = sonnet_results.get(idx, [])

            # Assign NHA from DT context if not already set
            for mat in materials:
                if mat.nha is None and page.dt_context:
                    mat.nha = page.dt_context.get("parent")

            result.materials.extend(materials)

        result.compute_summary()

        LOGGER.info(
            f"[Phase3] Compare complete: "
            f"{result.summary.get('total_materials', 0)} materials, "
            f"{result.summary.get('needs_review', 0)} need review, "
            f"{result.summary.get('auto_approved', 0)} auto-approved"
        )
        result.audit_trail.append({
            "event": "phase3_complete",
            "summary": result.summary,
            "timestamp": _now(),
        })

    # =====================================================================
    # Single-page Sonnet extraction (Pass 1 + Pass 2 gap-fill)
    # =====================================================================

    def _extract_single_page(
        self,
        page_image_b64: str,
        ocr_text: str,
        dt_context: Optional[Dict[str, Any]] = None,
        source_file: str = "",
        page_number: int = 1,
    ) -> List[ExtractedMaterial]:
        """
        Extract materials from a single drawing page using 2-pass vision.

        Pass 1: Full extraction prompt.
        Pass 2: Targeted gap-filling for any low-confidence or missing fields.
        """
        dt_str = json.dumps(dt_context, indent=2) if dt_context else "No DT context provided."

        # === PASS 1: Full extraction ===
        prompt1 = PASS1_PROMPT_TEMPLATE.format(
            ocr_text=ocr_text[:8000] if ocr_text else "(no OCR text available)",
            dt_context=dt_str[:3000],
        )
        LOGGER.info(f"[Sonnet] Pass 1: {source_file} page {page_number}")
        raw = self._vision.call_vision(page_image_b64, prompt1)

        if not raw or "materials" not in raw:
            LOGGER.warning(f"[Sonnet] Pass 1 returned no materials for {source_file} p{page_number}")
            return []

        materials = self._parse_materials(raw["materials"], source_file, page_number)

        # === PASS 2: Targeted gap-filling ===
        items_with_gaps = [m for m in materials if m.gaps or m.worst_confidence < REVIEW_THRESHOLD]

        if items_with_gaps:
            gap_list = self._build_gap_list(items_with_gaps)
            prompt2 = PASS2_PROMPT_TEMPLATE.format(
                pass1_results=json.dumps(
                    [_material_to_dict(m) for m in items_with_gaps], indent=2
                )[:6000],
                ocr_text=ocr_text[:6000] if ocr_text else "(no OCR text)",
                gap_list=gap_list,
            )
            LOGGER.info(
                f"[Sonnet] Pass 2: {len(items_with_gaps)} items with gaps, "
                f"{source_file} page {page_number}"
            )
            raw2 = self._vision.call_vision(page_image_b64, prompt2)

            if raw2 and "materials" in raw2:
                self._merge_pass2(materials, raw2["materials"])

        return materials

    # =====================================================================
    # Public API -- drop-in replacement for old sequential methods
    # =====================================================================

    def extract_from_files(
        self,
        pdf_paths: List[Path],
        dt_json: Dict[str, Any],
    ) -> ExtractionResult:
        """
        Extract materials from a list of PDF files (for API upload use case).

        3-Phase banked pipeline:
          Phase 1: OCR + render all pages -> bank
          Phase 2: Send bank to Sonnet in parallel
          Phase 3: Compare + merge -> ExtractionResult
        """
        result = ExtractionResult(dt_context=dt_json)

        # Phase 1: OCR Bank (free, instant)
        bank = self._phase1_ocr_bank(pdf_paths, dt_json, result)

        if not bank:
            result.compute_summary()
            return result

        # Phase 2: Sonnet Bank (parallel API calls)
        sonnet_results = self._phase2_sonnet_bank(bank, result)

        # Phase 3: Compare + merge
        self._phase3_compare(bank, sonnet_results, result)

        return result

    def extract_drawing_set(
        self,
        pdf_dir: Path,
        dt_json: Dict[str, Any],
    ) -> ExtractionResult:
        """
        Extract materials from an entire drawing set directory.

        Delegates to extract_from_files with directory glob.
        """
        pdf_files = sorted(pdf_dir.glob("*.pdf"))
        if not pdf_files:
            LOGGER.warning(f"[VisionExtractor] No PDFs found in {pdf_dir}")
            return ExtractionResult(dt_context=dt_json)

        LOGGER.info(f"[VisionExtractor] Processing {len(pdf_files)} PDFs from {pdf_dir}")
        return self.extract_from_files(pdf_files, dt_json)

    # Keep old per-page method for backward compatibility (used by tests/scripts)
    def extract_drawing_page(
        self,
        page_image_b64: str,
        ocr_text: str,
        dt_context: Optional[Dict[str, Any]] = None,
        source_file: str = "",
        page_number: int = 1,
    ) -> List[ExtractedMaterial]:
        """Backward-compatible single-page extraction."""
        return self._extract_single_page(
            page_image_b64=page_image_b64,
            ocr_text=ocr_text,
            dt_context=dt_context,
            source_file=source_file,
            page_number=page_number,
        )

    # =====================================================================
    # Internal helpers
    # =====================================================================

    def _parse_materials(
        self,
        raw_materials: List[Dict],
        source_file: str,
        page_number: int,
    ) -> List[ExtractedMaterial]:
        """Convert raw JSON materials into ExtractedMaterial objects."""
        results = []
        for item in raw_materials:
            pn = item.get("part_number", "").strip()
            if not pn:
                continue

            evidence = []
            for e in item.get("evidence", []):
                evidence.append(ExtractionEvidence(
                    source_page=page_number,
                    source_location=e.get("source_location", "unknown"),
                    source_text=e.get("source_text", ""),
                    confidence=e.get("confidence", 0.5),
                ))

            mat = ExtractedMaterial(
                part_number=pn,
                part_description=item.get("part_description", ""),
                designation=item.get("designation"),
                material_spec=item.get("material_spec"),
                process_spec=item.get("process_spec"),
                uns_code=item.get("uns_code"),
                material_form=item.get("material_form"),
                quantity=item.get("quantity", 1),
                source_file=source_file,
                source_page=page_number,
                confidence=item.get("confidence", {}),
                gaps=item.get("gaps", []),
                gap_reasons=item.get("gap_reasons", []),
                evidence=evidence,
            )
            results.append(mat)
        return results

    def _build_gap_list(self, items: List[ExtractedMaterial]) -> str:
        """Build human-readable gap list for pass 2 prompt."""
        lines = []
        for m in items:
            lines.append(f"Part {m.part_number} ({m.part_description}):")
            for gap in m.gaps:
                lines.append(f"  - MISSING: {gap}")
            for field_name, conf in m.confidence.items():
                if conf < REVIEW_THRESHOLD:
                    lines.append(f"  - LOW CONFIDENCE ({conf:.1f}): {field_name}")
            if m.gap_reasons:
                for reason in m.gap_reasons:
                    lines.append(f"  - Hint: {reason}")
        return "\n".join(lines)

    def _merge_pass2(
        self,
        materials: List[ExtractedMaterial],
        pass2_raw: List[Dict],
    ) -> None:
        """Merge pass 2 results into existing materials (in-place update)."""
        p2_by_pn = {}
        for item in pass2_raw:
            pn = item.get("part_number", "").strip()
            if pn:
                p2_by_pn[pn] = item

        for mat in materials:
            p2 = p2_by_pn.get(mat.part_number)
            if not p2:
                continue

            p2_conf = p2.get("confidence", {})
            for field_name in ["designation", "material_spec", "process_spec",
                               "uns_code", "material_form"]:
                old_conf = mat.confidence.get(field_name, 0.0)
                new_conf = p2_conf.get(field_name, 0.0)
                new_val = p2.get(field_name)

                if new_val and new_conf > old_conf:
                    setattr(mat, field_name, new_val)
                    mat.confidence[field_name] = new_conf
                    LOGGER.debug(
                        f"[Pass2] {mat.part_number}.{field_name}: "
                        f"upgraded {old_conf:.1f} -> {new_conf:.1f}"
                    )

            # Update gaps: remove any that pass 2 resolved
            remaining_gaps = []
            remaining_reasons = []
            for gap, reason in zip(mat.gaps, mat.gap_reasons):
                new_conf = p2_conf.get(gap, 0.0)
                if new_conf < REVIEW_THRESHOLD:
                    remaining_gaps.append(gap)
                    remaining_reasons.append(reason)
            mat.gaps = remaining_gaps
            mat.gap_reasons = remaining_reasons

            # Append pass 2 evidence
            for e in p2.get("evidence", []):
                mat.evidence.append(ExtractionEvidence(
                    source_page=mat.source_page,
                    source_location=e.get("source_location", "pass2"),
                    source_text=e.get("source_text", ""),
                    confidence=e.get("confidence", 0.5),
                ))

    @staticmethod
    def _is_dt_pdf(pdf_path: Path) -> bool:
        """Check if a PDF is a Drawing Tree (skip it - already processed by DT Editor)."""
        name_upper = pdf_path.stem.upper()
        return (
            "_DT_" in name_upper
            or name_upper.endswith("_DT")
            or "DRAWING_TREE" in name_upper
            or "DRAWINGTREE" in name_upper
        )


# =============================================================================
# HITL Review Item Builder
# =============================================================================

def _merge_material_into_item(
    item: Dict[str, Any],
    mat: "ExtractedMaterial",
) -> None:
    """Merge a duplicate material sighting into an existing review item.

    Takes the higher-confidence value for each field and stacks evidence.
    """
    field_map = {
        "designation": mat.designation,
        "material_spec": mat.material_spec,
        "process_spec": mat.process_spec,
        "uns_code": mat.uns_code,
        "material_form": mat.material_form,
    }
    for field_name, new_val in field_map.items():
        old = item["fields"].get(field_name, {})
        old_conf = old.get("confidence", 0.0)
        new_conf = mat.confidence.get(field_name, 0.0)

        if new_val and new_conf > old_conf:
            item["fields"][field_name] = {
                "value": new_val,
                "confidence": new_conf,
            }

    # Stack evidence from additional pages
    for e in mat.evidence:
        item["evidence"].append({
            "source_location": f"{mat.source_file} p{mat.source_page}: {e.source_location}",
            "source_text": e.source_text,
            "confidence": e.confidence,
        })

    # Track all source pages
    src = f"{mat.source_file} p{mat.source_page}"
    if src not in item.get("source_pages", []):
        item.setdefault("source_pages", []).append(src)

    # Recalculate worst confidence from REQUIRED fields only
    req_confs = [
        item["fields"][f].get("confidence", 0.0)
        for f in REQUIRED_FIELDS
        if f in item["fields"]
    ]
    item["worst_confidence"] = min(req_confs) if req_confs else 0.0

    # Merge gaps: remove any that the new sighting resolved
    remaining_gaps = []
    remaining_reasons = []
    resolved_fields = {
        f for f, v in field_map.items()
        if v and mat.confidence.get(f, 0.0) >= REVIEW_THRESHOLD
    }
    for gap, reason in zip(item.get("gaps", []), item.get("gap_reasons", [])):
        if gap not in resolved_fields:
            remaining_gaps.append(gap)
            remaining_reasons.append(reason)
    item["gaps"] = remaining_gaps
    item["gap_reasons"] = remaining_reasons


def identify_review_items(result: ExtractionResult) -> Dict[str, Any]:
    """
    Convert extraction result into HITL review structure.

    Deduplicates materials: same part_number from multiple pages gets merged
    into one review item with stacked evidence and best-of-breed field values.
    Uses smart thresholds: only required fields trigger HITL.
    """
    # Phase 1: Group materials by part_number
    by_pn: Dict[str, List["ExtractedMaterial"]] = {}
    for mat in result.materials:
        by_pn.setdefault(mat.part_number, []).append(mat)

    review_items = []
    auto_approved_parts = []

    for pn, mats in by_pn.items():
        # Start with the highest-confidence sighting as the base
        mats_sorted = sorted(mats, key=lambda m: m.worst_confidence, reverse=True)
        primary = mats_sorted[0]

        # Check if ANY sighting needs review
        any_needs_review = any(m.needs_review for m in mats)

        if not any_needs_review:
            auto_approved_parts.append(pn)
            continue

        # Build the review item from the primary sighting
        item = {
            "item_id": pn,  # part_number is now unique after dedup
            "part_number": pn,
            "part_description": primary.part_description,
            "nha": primary.nha,
            "source_file": primary.source_file,
            "source_page": primary.source_page,
            "source_pages": [f"{primary.source_file} p{primary.source_page}"],
            "fields": {
                "designation": {
                    "value": primary.designation,
                    "confidence": primary.confidence.get("designation", 0.0),
                },
                "material_spec": {
                    "value": primary.material_spec,
                    "confidence": primary.confidence.get("material_spec", 0.0),
                },
                "process_spec": {
                    "value": primary.process_spec,
                    "confidence": primary.confidence.get("process_spec", 0.0),
                },
                "uns_code": {
                    "value": primary.uns_code,
                    "confidence": primary.confidence.get("uns_code", 0.0),
                },
                "material_form": {
                    "value": primary.material_form,
                    "confidence": primary.confidence.get("material_form", 0.0),
                },
            },
            # Only include gaps for REQUIRED and EXPECTED fields
            "gaps": [g for g in primary.gaps if g not in OPTIONAL_FIELDS],
            "gap_reasons": [
                r for g, r in zip(primary.gaps, primary.gap_reasons)
                if g not in OPTIONAL_FIELDS
            ],
            "evidence": [
                {
                    "source_location": f"{primary.source_file} p{primary.source_page}: {e.source_location}",
                    "source_text": e.source_text,
                    "confidence": e.confidence,
                }
                for e in primary.evidence
            ],
            "worst_confidence": primary.worst_confidence,
            "status": "open",
        }

        # Merge additional sightings (pages 2, 3, etc.)
        for extra in mats_sorted[1:]:
            _merge_material_into_item(item, extra)

        # After merging all sightings, re-check if review is still needed
        # (merging may have resolved gaps via higher-confidence data from other pages)
        still_needs = False
        for f in REQUIRED_FIELDS:
            if f in item["gaps"]:
                still_needs = True
                break
            if item["fields"].get(f, {}).get("confidence", 0.0) < REVIEW_THRESHOLD:
                still_needs = True
                break
        if not still_needs:
            for f in EXPECTED_FIELDS:
                conf = item["fields"].get(f, {}).get("confidence", 0.0)
                # Only flag if Sonnet SAW something but wasn't confident.
                # conf=0.0 means "not on this page" -- that's normal.
                if 0.0 < conf < EXPECTED_THRESHOLD:
                    still_needs = True
                    break

        if still_needs:
            review_items.append(item)
        else:
            auto_approved_parts.append(pn)

    # Unique parts count (after dedup)
    unique_parts = len(by_pn)

    return {
        "version": "1.1",
        "extraction_id": result.extraction_id,
        "summary": {
            "total_materials": unique_parts,
            "total_extractions": len(result.materials),  # raw count before dedup
            "needs_review": len(review_items),
            "auto_approved": len(auto_approved_parts),
        },
        "review_items": review_items,
        "auto_approved_parts": auto_approved_parts,
    }


# =============================================================================
# DT Context Helpers
# =============================================================================

def _extract_drawing_number(pdf_path: Path) -> str:
    """
    Extract drawing number from filename.

    NASA convention: MER07545-001_DRW_-_12_RELEASED.pdf
    Drawing number: MER07545-001
    """
    stem = pdf_path.stem
    # Take everything before _DRW or _drw
    for sep in ["_DRW", "_drw", "_Drw"]:
        if sep in stem:
            return stem.split(sep)[0]
    # Fallback: take up to first underscore after dash pattern
    return stem.split("_")[0] if "_" in stem else stem


def _get_dt_context(
    dt_json: Dict[str, Any],
    drawing_number: str,
) -> Optional[Dict[str, Any]]:
    """
    Find DT context for a specific drawing number.

    The DT JSON (from DT Editor) has a tree structure. We find the node
    matching this drawing number and return its parent and children info
    so Sonnet knows which parts to expect.
    """
    if not dt_json:
        return None

    tree = dt_json.get("tree", [])
    if not tree:
        return None

    # Find node matching this drawing number
    for node in tree:
        if node.get("drawing_number", "").upper() == drawing_number.upper():
            return {
                "drawing_number": node.get("drawing_number"),
                "title": node.get("title", ""),
                "type": node.get("type", ""),
                "parent": node.get("parent"),
                "expected_parts": _get_child_parts(tree, drawing_number),
            }

    return None


def _get_child_parts(tree: List[Dict], parent_drawing: str) -> List[Dict]:
    """Get all parts that list this drawing as their parent."""
    children = []
    for node in tree:
        if node.get("parent", "").upper() == parent_drawing.upper():
            children.append({
                "drawing_number": node.get("drawing_number"),
                "title": node.get("title", ""),
                "type": node.get("type", ""),
            })
    return children


# =============================================================================
# Utilities
# =============================================================================

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
