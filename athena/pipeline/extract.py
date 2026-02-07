#!/usr/bin/env python3
"""
Module: Extract
Purpose: [Automatically migrated - needs manual review]

BoundState AI 2025
Version: 4.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Fran OpenAI 5 <noreply@openai.com>
Co-Authored-By: Grok 4.0 <noreply@x.ai>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: SWE-032, NASA-STD-8739.8B
Safety Critical: True
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from datetime import datetime
from typing import TYPE_CHECKING, Any, Callable, Awaitable

from athena.models.document import (
    Annotation,
    Document,
    DocumentSection,
    ExtractedTable,
    ExtractionResult,
    FieldSpec,
    ProcessingEvent,
)
from athena.models.discovery import CorpusProfile
from athena.models.enums import DocumentStatus, RoutingDecision
from athena.models.evidence import BoundingBox, Evidence, ExtractedValue
from athena.models.ocr import ALTOPage, ALTOWord, OCRResult
from athena.prompts.extract import (
    EXTRACTION_SYSTEM_PROMPT,
    EXTRACTION_LIGHT_SYSTEM_PROMPT,
    EXTRACTION_DRAWING_SYSTEM_PROMPT,
    EXTRACTION_USER_PROMPT_TEMPLATE,
)
from athena.utils.parsing import parse_confidence, safe_parse_enum

if TYPE_CHECKING:
    import fitz
    from athena.config import AthenaConfig
    from athena.providers.base import LLMProvider, LLMResponse
    from athena.services.cost import CostTracker
    from athena.services.storage import FileStore

logger = logging.getLogger(__name__)


class ExtractionStage:
    """Full extraction with mandatory evidence."""

    def __init__(
        self,
        config: AthenaConfig,
        llm: LLMProvider,
        cost_tracker: CostTracker | None = None,
        storage: FileStore | None = None,
    ):
        """Initialize extraction stage.

        Args:
            config: ATHENA configuration
            llm: LLM provider
            cost_tracker: Optional cost tracker
            storage: Optional file storage for evidence snippets
        """
        self.config = config
        self.llm = llm
        self.cost_tracker = cost_tracker
        self.storage = storage

    async def extract_document(
        self,
        doc: Document,
        pdf: "fitz.Document",
    ) -> ExtractionResult:
        """Extract structured data from document with evidence.

        Args:
            doc: Document record
            pdf: PyMuPDF document

        Returns:
            ExtractionResult with fields, tables, and evidence
        """
        start_time = datetime.utcnow()

        # Determine model and prompt based on routing
        if doc.routing == RoutingDecision.EXTRACT_FULL:
            model_key = "extract"
            system_prompt = EXTRACTION_SYSTEM_PROMPT
        elif doc.routing == RoutingDecision.EXTRACT_DRAWING:
            model_key = "triage"  # Use Haiku for drawings (cheaper)
            system_prompt = EXTRACTION_DRAWING_SYSTEM_PROMPT
        else:
            model_key = "triage"
            system_prompt = EXTRACTION_LIGHT_SYSTEM_PROMPT

        # Get DPI from triage or use default
        dpi = (
            doc.triage_result.recommended_dpi
            if doc.triage_result
            else self.config.default_dpi
        )

        # Process in chunks
        all_results: list[dict] = []
        total_tokens_in = 0
        total_tokens_out = 0
        total_cost = 0.0

        start_idx = doc.page_range[0] - 1  # 0-indexed
        end_idx = doc.page_range[1]

        for chunk_start in range(start_idx, end_idx, self.config.pages_per_extraction):
            chunk_end = min(chunk_start + self.config.pages_per_extraction, end_idx)

            # Render pages
            images = pages_to_images(pdf, chunk_start, chunk_end, dpi=dpi)

            # Build prompt with context
            schema_json = "[]"
            doc_type = "unknown"
            if doc.triage_result:
                doc_type = doc.triage_result.document_type
                schema_json = json.dumps(
                    [f.model_dump() for f in doc.triage_result.suggested_schema]
                )

            prompt = system_prompt.format(
                document_type=doc_type,
                schema=schema_json,
            )

            user_prompt = EXTRACTION_USER_PROMPT_TEMPLATE.format(
                start_page=chunk_start + 1,
                end_page=chunk_end,
            )

            response = await self.llm.complete_vision(
                images=images,
                system_prompt=prompt,
                user_prompt=user_prompt,
                max_tokens=4096,
                model_key=model_key,
            )

            # Parse chunk result
            chunk_data = self._parse_extraction(response, chunk_start + 1)
            all_results.append(chunk_data)

            total_tokens_in += response.tokens_in
            total_tokens_out += response.tokens_out
            total_cost += response.cost_usd

            # Record cost
            if self.cost_tracker:
                await self.cost_tracker.record(
                    batch_id=doc.batch_id,
                    document_id=doc.document_id,
                    stage="extraction",
                    cost=response.cost_usd,
                    tokens_in=response.tokens_in,
                    tokens_out=response.tokens_out,
                    model=response.model,
                )

        # Merge chunks
        result = await self._merge_results(
            all_results, dpi, pdf, doc
        )

        # Add metrics
        result.tokens_in = total_tokens_in
        result.tokens_out = total_tokens_out
        result.cost_usd = total_cost
        result.dpi_used = dpi
        result.pages_processed = list(range(doc.page_range[0], doc.page_range[1] + 1))

        # Create processing event
        duration_ms = int((datetime.utcnow() - start_time).total_seconds() * 1000)
        event = ProcessingEvent(
            stage="extraction",
            status="completed",
            duration_ms=duration_ms,
            tokens_used=total_tokens_in + total_tokens_out,
            cost_usd=total_cost,
            details={
                "pages_processed": result.pages_processed,
                "fields_extracted": len(result.fields),
                "tables_extracted": len(result.tables),
                "evidence_coverage": result.evidence_coverage,
            },
        )
        doc.processing_log.append(event)

        return result

    def _parse_extraction(
        self,
        response: LLMResponse,
        page_offset: int,
    ) -> dict:
        """Parse extraction JSON from model response.

        Args:
            response: LLM response
            page_offset: Page offset for this chunk

        Returns:
            Parsed extraction data
        """
        text = response.content

        # Strip markdown fences
        if "```" in text:
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]

        try:
            data = json.loads(text.strip())
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse extraction response: {e}")
            return {"fields": {}, "tables": [], "annotations": [], "sections": []}

        return data

    async def _merge_results(
        self,
        results: list[dict],
        dpi: int,
        pdf: "fitz.Document",
        doc: Document,
    ) -> ExtractionResult:
        """Merge chunk results into final extraction.

        Args:
            results: List of chunk results
            dpi: DPI used for extraction
            pdf: PyMuPDF document
            doc: Document record

        Returns:
            Merged ExtractionResult
        """
        merged_fields: dict[str, ExtractedValue] = {}
        merged_tables: list[ExtractedTable] = []
        merged_annotations: list[Annotation] = []
        merged_sections: list[DocumentSection] = []
        merged_schema: list[FieldSpec] = []

        for result in results:
            # Merge fields
            for field_name, field_data in result.get("fields", {}).items():
                if not isinstance(field_data, dict):
                    continue

                evidence_data = field_data.get("evidence", {})
                if not evidence_data:
                    continue

                # Create evidence with snippet hash
                bbox = BoundingBox(
                    x_min=evidence_data.get("bbox", {}).get("x_min", 0),
                    y_min=evidence_data.get("bbox", {}).get("y_min", 0),
                    x_max=evidence_data.get("bbox", {}).get("x_max", 1),
                    y_max=evidence_data.get("bbox", {}).get("y_max", 1),
                )

                page = evidence_data.get("page", 1)

                # Generate snippet hash
                snippet_hash = await self._compute_snippet_hash(
                    pdf, page - 1, bbox
                )

                evidence = Evidence(
                    page=page,
                    bbox=bbox,
                    snippet_hash=snippet_hash,
                    raw_text=evidence_data.get("raw_text"),
                    confidence=parse_confidence(field_data.get("confidence", 0.5)),
                )

                # Store evidence snippet if storage available
                if self.storage and bbox.area > 0.001:
                    snippet_path, _ = await self._store_evidence_snippet(
                        pdf, page - 1, bbox, doc
                    )
                    evidence.snippet_path = snippet_path

                value = field_data.get("value")
                value_type = field_data.get("value_type", type(value).__name__)

                merged_fields[field_name] = ExtractedValue(
                    value=value,
                    value_type=value_type,
                    evidence=evidence,
                    confidence=parse_confidence(field_data.get("confidence", 0.5)),
                )

            # Merge schema (use latest)
            schema_data = result.get("schema_used", [])
            if schema_data:
                merged_schema = [
                    FieldSpec(
                        field=s.get("field", ""),
                        type=s.get("type", "string"),
                        description=s.get("description", ""),
                        required=s.get("required", False),
                    )
                    for s in schema_data
                    if isinstance(s, dict)
                ]

        # Calculate evidence coverage
        fields_with_bbox = sum(
            1 for f in merged_fields.values()
            if f.evidence and f.evidence.bbox.area > 0
        )
        coverage = fields_with_bbox / len(merged_fields) if merged_fields else 1.0

        # Calculate overall confidence
        confidences = [f.confidence for f in merged_fields.values()]
        overall_confidence = sum(confidences) / len(confidences) if confidences else 0.0

        return ExtractionResult(
            schema_used=merged_schema,
            schema_extended=False,
            fields=merged_fields,
            tables=merged_tables,
            sections=merged_sections,
            annotations=merged_annotations,
            overall_confidence=overall_confidence,
            field_confidences={k: v.confidence for k, v in merged_fields.items()},
            evidence_coverage=coverage,
            model_used="",
            tokens_in=0,
            tokens_out=0,
            latency_ms=0,
            cost_usd=0.0,
            pages_processed=[],
            dpi_used=dpi,
        )

    async def _compute_snippet_hash(
        self,
        pdf: "fitz.Document",
        page_idx: int,
        bbox: BoundingBox,
    ) -> str:
        """Compute hash for evidence snippet.

        Args:
            pdf: PyMuPDF document
            page_idx: Page index (0-indexed)
            bbox: Bounding box

        Returns:
            SHA256 hash of snippet
        """
        if page_idx >= len(pdf):
            return ""

        try:
            snippet_b64 = extract_page_region(
                pdf, page_idx,
                bbox.x_min, bbox.y_min, bbox.x_max, bbox.y_max,
                dpi=100,
            )
            return hashlib.sha256(snippet_b64.encode()).hexdigest()[:32]
        except Exception:
            return ""

    async def _store_evidence_snippet(
        self,
        pdf: "fitz.Document",
        page_idx: int,
        bbox: BoundingBox,
        doc: Document,
    ) -> tuple[str, str]:
        """Store evidence snippet and return path and hash.

        Args:
            pdf: PyMuPDF document
            page_idx: Page index
            bbox: Bounding box
            doc: Document record

        Returns:
            Tuple of (storage_path, content_hash)
        """
        if not self.storage or page_idx >= len(pdf):
            return ("", "")

        try:
            snippet_b64 = extract_page_region(
                pdf, page_idx,
                bbox.x_min, bbox.y_min, bbox.x_max, bbox.y_max,
                dpi=200,
            )
            snippet_bytes = snippet_b64.encode()

            return await self.storage.upload_evidence_snippet(
                doc.batch_id,
                str(doc.document_id),
                snippet_bytes,
            )
        except Exception as e:
            logger.warning(f"Failed to store evidence snippet: {e}")
            return ("", "")

    async def update_document_status(
        self,
        doc: Document,
        result: ExtractionResult,
        db,
    ) -> Document:
        """Update document with extraction results.

        Args:
            doc: Document to update
            result: Extraction result
            db: Database client

        Returns:
            Updated document
        """
        doc.extraction_result = result
        doc.status = DocumentStatus.EXTRACTED
        doc.total_cost_usd += result.cost_usd
        doc.updated_at = datetime.utcnow()

        await db.update_document(doc)
        return doc


# ==============================================================================
# V2: Text-Only Extraction with ALTO Evidence (60% COST SAVINGS)
# ==============================================================================

V2_EXTRACTION_SYSTEM_PROMPT = """You are a document data extraction system.
Extract structured data from the OCR text below.

DOCUMENT TYPE: {document_type}

CORPUS VOCABULARY (known terms from this archive):
{vocabulary}

SCHEMA (fields to extract):
{schema}

OUTPUT (strict JSON, no markdown):
{{
    "fields": {{
        "field_name": {{
            "value": "extracted value",
            "value_type": "string|number|date|boolean",
            "confidence": 0.0-1.0,
            "evidence": {{
                "raw_text": "exact text from document",
                "word_positions": [0, 5, 12]  // word indices for bbox lookup
            }}
        }}
    }},
    "tables": [
        {{
            "headers": ["col1", "col2"],
            "rows": [["val1", "val2"]],
            "confidence": 0.9
        }}
    ],
    "annotations": [
        {{
            "type": "note|handwriting|stamp|signature",
            "content": "annotation text if readable"
        }}
    ]
}}

RULES:
1. ONLY extract what is explicitly present in the text
2. For evidence, provide EXACT text snippets and word positions
3. If a field is not found, do not include it
4. Confidence reflects certainty of interpretation
5. Tables should preserve structure where detectable
"""


class TextOnlyExtractionStage:
    """V2 Text-only extraction using OCR text with ALTO evidence.

    CRITICAL: Evidence bounding boxes come FREE from ALTO XML.
    No LLM cost for evidence - just look up word positions.

    Cost: ~$0.003/page vs ~$0.01/page for vision extraction
    When to use: OCR confidence > 0.7, no complex visual elements
    """

    def __init__(
        self,
        llm: "LLMProvider",
        corpus_profile: CorpusProfile | None = None,
        cost_tracker: "CostTracker | None" = None,
        storage: "FileStore | None" = None,
        max_text_length: int = 12000,
    ):
        """Initialize text-only extraction stage.

        Args:
            llm: LLM provider (uses text-only calls to Haiku)
            corpus_profile: Corpus profile from discovery phase
            cost_tracker: Optional cost tracker
            storage: Optional file storage for evidence snippets
            max_text_length: Max characters to send per page
        """
        self.llm = llm
        self.corpus_profile = corpus_profile
        self.cost_tracker = cost_tracker
        self.storage = storage
        self.max_text_length = max_text_length

    def set_corpus_profile(self, profile: CorpusProfile) -> None:
        """Set corpus profile (can be loaded after initialization).

        Args:
            profile: CorpusProfile from discovery phase
        """
        self.corpus_profile = profile

    async def extract_page(
        self,
        ocr_result: OCRResult,
        alto_page: ALTOPage | None,
        schema: list[FieldSpec],
        document_type: str = "unknown",
    ) -> dict:
        """Extract data from single page using text-only (cheap).

        CRITICAL: Evidence bounding boxes from ALTO are FREE.

        Args:
            ocr_result: OCR result with full text
            alto_page: Optional ALTO page for word-level bbox lookup
            schema: Fields to extract
            document_type: Document classification

        Returns:
            Extraction result dict with fields, tables, annotations
        """
        start_time = datetime.utcnow()

        # Build corpus-informed prompt
        prompt = self._build_prompt(schema, document_type)

        # Truncate text if too long
        text = ocr_result.full_text[:self.max_text_length]

        response = await self.llm.complete_text(
            system_prompt=prompt,
            user_prompt=f"Extract data from this document:\n\n{text}",
            max_tokens=2000,
        )

        # Parse response
        result = self._parse_response(response, alto_page, ocr_result)

        # Add latency
        result["latency_ms"] = int(
            (datetime.utcnow() - start_time).total_seconds() * 1000
        )
        result["model_used"] = response.model
        result["tokens_in"] = response.tokens_in
        result["tokens_out"] = response.tokens_out
        result["cost_usd"] = response.cost_usd

        return result

    async def extract_document(
        self,
        doc: Document,
        ocr_results: list[OCRResult],
        alto_pages: list[ALTOPage] | None = None,
        save_callback: Callable[[ExtractionResult], Awaitable[None]] | None = None,
    ) -> ExtractionResult:
        """Extract data from full document using text-only.

        CRITICAL: Saves progress INCREMENTALLY via save_callback.

        Args:
            doc: Document record
            ocr_results: OCR results for document pages
            alto_pages: Optional ALTO pages for bbox lookup
            save_callback: Called after each page with current results

        Returns:
            Merged ExtractionResult
        """
        start_time = datetime.utcnow()

        # Get schema from triage result
        schema = doc.triage_result.suggested_schema if doc.triage_result else []
        doc_type = doc.triage_result.document_type if doc.triage_result else "unknown"

        all_page_results: list[dict] = []
        total_tokens_in = 0
        total_tokens_out = 0
        total_cost = 0.0

        # Process each page
        for idx, ocr_result in enumerate(ocr_results):
            alto_page = alto_pages[idx] if alto_pages and idx < len(alto_pages) else None

            page_result = await self.extract_page(
                ocr_result=ocr_result,
                alto_page=alto_page,
                schema=schema,
                document_type=doc_type,
            )

            all_page_results.append(page_result)

            total_tokens_in += page_result.get("tokens_in", 0)
            total_tokens_out += page_result.get("tokens_out", 0)
            total_cost += page_result.get("cost_usd", 0.0)

            # Record cost
            if self.cost_tracker:
                await self.cost_tracker.record(
                    batch_id=doc.batch_id,
                    document_id=doc.document_id,
                    stage="extraction",
                    cost=page_result.get("cost_usd", 0.0),
                    tokens_in=page_result.get("tokens_in", 0),
                    tokens_out=page_result.get("tokens_out", 0),
                    model=page_result.get("model_used", ""),
                )

            # INCREMENTAL SAVE after each page
            if save_callback:
                interim_result = self._merge_page_results(
                    all_page_results, schema, total_tokens_in, total_tokens_out, total_cost
                )
                await save_callback(interim_result)

        # Final merge
        result = self._merge_page_results(
            all_page_results, schema, total_tokens_in, total_tokens_out, total_cost
        )
        result.pages_processed = [r.page for r in ocr_results]
        result.dpi_used = 0  # N/A for text-only

        # Create processing event
        duration_ms = int((datetime.utcnow() - start_time).total_seconds() * 1000)
        event = ProcessingEvent(
            stage="extraction",
            status="completed",
            duration_ms=duration_ms,
            tokens_used=total_tokens_in + total_tokens_out,
            cost_usd=total_cost,
            details={
                "pages_processed": result.pages_processed,
                "fields_extracted": len(result.fields),
                "tables_extracted": len(result.tables),
                "evidence_coverage": result.evidence_coverage,
                "extraction_mode": "text_only",
            },
        )
        doc.processing_log.append(event)

        return result

    def _build_prompt(
        self,
        schema: list[FieldSpec],
        document_type: str,
    ) -> str:
        """Build corpus-informed extraction prompt.

        Args:
            schema: Fields to extract
            document_type: Document classification

        Returns:
            System prompt with schema and corpus context
        """
        schema_json = json.dumps(
            [{"field": s.field, "type": s.type, "description": s.description}
             for s in schema]
        ) if schema else "[]"

        vocabulary = []
        if self.corpus_profile:
            vocabulary = list(self.corpus_profile.vocabulary.keys())[:50]

        return V2_EXTRACTION_SYSTEM_PROMPT.format(
            document_type=document_type,
            vocabulary=json.dumps(vocabulary),
            schema=schema_json,
        )

    def _parse_response(
        self,
        response: "LLMResponse",
        alto_page: ALTOPage | None,
        ocr_result: OCRResult,
    ) -> dict:
        """Parse extraction JSON and resolve evidence bounding boxes.

        CRITICAL: Bounding boxes from ALTO are FREE - no LLM cost.

        Args:
            response: LLM response
            alto_page: ALTO page for word-level bbox lookup
            ocr_result: OCR result for fallback

        Returns:
            Parsed extraction data with resolved evidence
        """
        text = response.content

        # Strip markdown fences if present
        if "```" in text:
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]

        try:
            data = json.loads(text.strip())
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse extraction response: {e}")
            return {
                "fields": {},
                "tables": [],
                "annotations": [],
            }

        # Resolve evidence bounding boxes from ALTO (FREE)
        if alto_page and "fields" in data:
            data["fields"] = self._resolve_evidence_bboxes(
                data["fields"], alto_page, ocr_result
            )

        return data

    def _resolve_evidence_bboxes(
        self,
        fields: dict,
        alto_page: ALTOPage,
        ocr_result: OCRResult,
    ) -> dict:
        """Resolve evidence bounding boxes from ALTO word positions.

        CRITICAL: This is FREE - bounding boxes from ALTO, not LLM.

        Args:
            fields: Extracted fields with word_positions
            alto_page: ALTO page with word-level bboxes
            ocr_result: OCR result for page dimensions

        Returns:
            Fields with resolved bounding boxes
        """
        for field_name, field_data in fields.items():
            if not isinstance(field_data, dict):
                continue

            evidence = field_data.get("evidence", {})
            raw_text = evidence.get("raw_text", "")
            word_positions = evidence.get("word_positions", [])

            # Try to find bounding box from word positions
            bbox = None
            if word_positions and alto_page.words:
                bbox = self._compute_bbox_from_positions(
                    word_positions, alto_page
                )

            # Fallback: fuzzy match raw_text in ALTO words
            if not bbox and raw_text and alto_page.words:
                bbox = self._fuzzy_match_text(raw_text, alto_page)

            if bbox:
                field_data["evidence"]["bbox"] = bbox
                field_data["evidence"]["page"] = ocr_result.page

        return fields

    def _compute_bbox_from_positions(
        self,
        positions: list[int],
        alto_page: ALTOPage,
    ) -> dict | None:
        """Compute bounding box from word positions.

        Args:
            positions: Word indices in ALTO word list
            alto_page: ALTO page with words

        Returns:
            Normalized bounding box dict or None
        """
        if not positions:
            return None

        words = []
        for pos in positions:
            if 0 <= pos < len(alto_page.words):
                words.append(alto_page.words[pos])

        if not words:
            return None

        # Compute union of word bboxes
        x_min = min(w.x for w in words)
        y_min = min(w.y for w in words)
        x_max = max(w.x + w.width for w in words)
        y_max = max(w.y + w.height for w in words)

        # Normalize to 0.0-1.0
        return {
            "x_min": x_min / alto_page.width if alto_page.width > 0 else 0.0,
            "y_min": y_min / alto_page.height if alto_page.height > 0 else 0.0,
            "x_max": x_max / alto_page.width if alto_page.width > 0 else 1.0,
            "y_max": y_max / alto_page.height if alto_page.height > 0 else 1.0,
        }

    def _fuzzy_match_text(
        self,
        target_text: str,
        alto_page: ALTOPage,
    ) -> dict | None:
        """Find bounding box by fuzzy matching text in ALTO words.

        Args:
            target_text: Text to find
            alto_page: ALTO page with words

        Returns:
            Normalized bounding box dict or None
        """
        target_words = target_text.lower().split()
        if not target_words:
            return None

        # Sliding window search
        words = alto_page.words
        window_size = len(target_words)

        best_match_score = 0.0
        best_match_indices: list[int] = []

        for i in range(len(words) - window_size + 1):
            window = words[i:i + window_size]
            window_text = [w.content.lower() for w in window]

            # Simple word match score
            matches = sum(
                1 for t, w in zip(target_words, window_text)
                if t in w or w in t
            )
            score = matches / window_size

            if score > best_match_score and score >= 0.5:
                best_match_score = score
                best_match_indices = list(range(i, i + window_size))

        if best_match_indices:
            return self._compute_bbox_from_positions(best_match_indices, alto_page)

        return None

    def _merge_page_results(
        self,
        page_results: list[dict],
        schema: list[FieldSpec],
        total_tokens_in: int,
        total_tokens_out: int,
        total_cost: float,
    ) -> ExtractionResult:
        """Merge page-level results into document ExtractionResult.

        Args:
            page_results: List of per-page extraction results
            schema: Schema used
            total_tokens_in: Total input tokens
            total_tokens_out: Total output tokens
            total_cost: Total cost

        Returns:
            Merged ExtractionResult
        """
        merged_fields: dict[str, ExtractedValue] = {}
        merged_tables: list[ExtractedTable] = []
        merged_annotations: list[Annotation] = []

        for result in page_results:
            # Merge fields (later pages override)
            for field_name, field_data in result.get("fields", {}).items():
                if not isinstance(field_data, dict):
                    continue

                evidence_data = field_data.get("evidence", {})
                bbox_data = evidence_data.get("bbox", {})

                bbox = BoundingBox(
                    x_min=bbox_data.get("x_min", 0.0),
                    y_min=bbox_data.get("y_min", 0.0),
                    x_max=bbox_data.get("x_max", 1.0),
                    y_max=bbox_data.get("y_max", 1.0),
                )

                evidence = Evidence(
                    page=evidence_data.get("page", 1),
                    bbox=bbox,
                    raw_text=evidence_data.get("raw_text"),
                    confidence=parse_confidence(field_data.get("confidence", 0.5)),
                    source="alto",  # FREE evidence from ALTO
                )

                merged_fields[field_name] = ExtractedValue(
                    value=field_data.get("value"),
                    value_type=field_data.get("value_type", "string"),
                    evidence=evidence,
                    confidence=parse_confidence(field_data.get("confidence", 0.5)),
                )

            # Merge tables
            for table_data in result.get("tables", []):
                if isinstance(table_data, dict):
                    merged_tables.append(ExtractedTable(
                        headers=table_data.get("headers", []),
                        rows=table_data.get("rows", []),
                        confidence=parse_confidence(table_data.get("confidence", 0.5)),
                        page=result.get("page", 1),
                    ))

            # Merge annotations
            for ann_data in result.get("annotations", []):
                if isinstance(ann_data, dict):
                    merged_annotations.append(Annotation(
                        type=ann_data.get("type", "note"),
                        content=ann_data.get("content", ""),
                    ))

        # Calculate coverage
        fields_with_bbox = sum(
            1 for f in merged_fields.values()
            if f.evidence and f.evidence.bbox.area > 0
        )
        coverage = fields_with_bbox / len(merged_fields) if merged_fields else 1.0

        # Calculate overall confidence
        confidences = [f.confidence for f in merged_fields.values()]
        overall_confidence = sum(confidences) / len(confidences) if confidences else 0.0

        return ExtractionResult(
            schema_used=[
                FieldSpec(field=s.field, type=s.type, description=s.description)
                for s in schema
            ],
            schema_extended=False,
            fields=merged_fields,
            tables=merged_tables,
            sections=[],
            annotations=merged_annotations,
            overall_confidence=overall_confidence,
            field_confidences={k: v.confidence for k, v in merged_fields.items()},
            evidence_coverage=coverage,
            model_used="",
            tokens_in=total_tokens_in,
            tokens_out=total_tokens_out,
            latency_ms=0,
            cost_usd=total_cost,
            pages_processed=[],
            dpi_used=0,
        )
