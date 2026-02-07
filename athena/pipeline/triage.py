#!/usr/bin/env python3
"""
Module: Triage
Purpose: ATHENA Document Triage Pipeline.

BoundState AI 2025
Version: 1.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Fran OpenAI 5 <noreply@openai.com>
Co-Authored-By: Grok 4.0 <noreply@x.ai>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: SWE-013, NASA-STD-8739.8B
Safety Critical: False
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import TYPE_CHECKING

from athena.models.document import Document, EntityBag, FieldSpec, ProcessingEvent, TriageResult
from athena.models.enums import DocumentStatus, QualityIssue, RoutingDecision
from athena.models.discovery import CorpusProfile
from athena.models.ocr import OCRResult

if TYPE_CHECKING:
    import fitz
    from athena.config import AthenaConfig
    from athena.providers.base import LLMProvider, LLMResponse
    from athena.services.cost import CostTracker

logger = logging.getLogger(__name__)


class TriageStage:
    """Document triage for classification and routing."""

    def __init__(
        self,
        config: AthenaConfig,
        llm: LLMProvider,
        cost_tracker: CostTracker | None = None,
    ):
        """Initialize triage stage.

        Args:
            config: ATHENA configuration
            llm: LLM provider
            cost_tracker: Optional cost tracker
        """
        self.config = config
        self.llm = llm
        self.cost_tracker = cost_tracker

    async def triage_document(
        self,
        doc: Document,
        pdf: "fitz.Document",
    ) -> TriageResult:
        """Triage a document for classification and routing.

        Args:
            doc: Document record
            pdf: PyMuPDF document

        Returns:
            TriageResult with classification and routing
        """
        start_time = datetime.utcnow()

        # Get first N pages as images
        start_idx = doc.page_range[0] - 1  # Convert to 0-indexed
        end_idx = min(start_idx + self.config.pages_per_triage, doc.page_range[1])
        images = pages_to_images(pdf, start_idx, end_idx, dpi=200)

        # Build page info for prompt
        page_info = ", ".join(
            [f"Page {start_idx + i + 1}" for i in range(len(images))]
        )

        # Make LLM request
        response = await self.llm.complete_vision(
            images=images,
            system_prompt=TRIAGE_SYSTEM_PROMPT,
            user_prompt=TRIAGE_USER_PROMPT_TEMPLATE.format(page_info=page_info),
            max_tokens=1500,
            model_key="triage",
        )

        # Parse response
        result = self._parse_response(response, start_idx + 1, end_idx)

        # Calculate adaptive DPI
        result.recommended_dpi = DPIStrategy.calculate(
            result.routing.value,
            result.quality_issues,
            doc.source_dpi,
            self.config.max_dpi,
            self.config.default_dpi,
        )

        # Record cost if tracker available
        if self.cost_tracker:
            await self.cost_tracker.record(
                batch_id=doc.batch_id,
                document_id=doc.document_id,
                stage="triage",
                cost=response.cost_usd,
                tokens_in=response.tokens_in,
                tokens_out=response.tokens_out,
                model=response.model,
            )

        # Create processing event
        duration_ms = int((datetime.utcnow() - start_time).total_seconds() * 1000)
        event = ProcessingEvent(
            stage="triage",
            status="completed",
            duration_ms=duration_ms,
            tokens_used=response.tokens_in + response.tokens_out,
            cost_usd=response.cost_usd,
            details={
                "pages_analyzed": list(range(start_idx + 1, end_idx + 1)),
                "routing": result.routing.value,
                "quality_score": result.quality_score,
            },
        )
        doc.processing_log.append(event)

        return result

    def _parse_response(
        self,
        response: LLMResponse,
        start_page: int,
        end_page: int,
    ) -> TriageResult:
        """Parse triage JSON from model response.

        Args:
            response: LLM response
            start_page: Start page number
            end_page: End page number

        Returns:
            Parsed TriageResult
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
            logger.error(f"Failed to parse triage response: {e}")
            # Return default manual review result
            return TriageResult(
                document_type="unknown",
                quality_score=0.5,
                confidence=0.0,
                routing=RoutingDecision.MANUAL_REVIEW,
                routing_reason="Failed to parse triage response",
                model_used=response.model,
                tokens_in=response.tokens_in,
                tokens_out=response.tokens_out,
                latency_ms=response.latency_ms,
                cost_usd=response.cost_usd,
                pages_analyzed=list(range(start_page, end_page + 1)),
            )

        # Parse entities
        entities_data = data.get("entities", {})
        entities = EntityBag(
            equipment=entities_data.get("equipment", []),
            people=entities_data.get("people", []),
            locations=entities_data.get("locations", []),
            organizations=entities_data.get("organizations", []),
            references=entities_data.get("references", []),
            dates=entities_data.get("dates", []),
            materials=entities_data.get("materials", []),
        )

        # Parse quality issues
        quality_issues = safe_parse_enum_list(
            QualityIssue, data.get("quality_issues", [])
        )

        # Parse routing
        routing = safe_parse_enum(
            RoutingDecision,
            data.get("routing"),
            RoutingDecision.MANUAL_REVIEW,
        )

        # Parse suggested schema
        schema = []
        for field_data in data.get("suggested_schema", []):
            if isinstance(field_data, dict):
                schema.append(
                    FieldSpec(
                        field=field_data.get("field", ""),
                        type=field_data.get("type", "string"),
                        description=field_data.get("description", ""),
                        required=field_data.get("required", False),
                    )
                )

        return TriageResult(
            document_type=data.get("document_type", "other"),
            document_subtype=data.get("document_subtype"),
            date_detected=data.get("date_detected"),
            language=data.get("language", "en"),
            entities=entities,
            quality_score=parse_confidence(data.get("quality_score", 0.5)),
            quality_issues=quality_issues,
            suggested_schema=schema,
            confidence=parse_confidence(data.get("confidence", 0.5)),
            routing=routing,
            routing_reason=data.get("routing_reason", ""),
            model_used=response.model,
            tokens_in=response.tokens_in,
            tokens_out=response.tokens_out,
            latency_ms=response.latency_ms,
            cost_usd=response.cost_usd,
            pages_analyzed=list(range(start_page, end_page + 1)),
        )

    async def update_document_status(
        self,
        doc: Document,
        result: TriageResult,
        db,
    ) -> Document:
        """Update document with triage results.

        Args:
            doc: Document to update
            result: Triage result
            db: Database client

        Returns:
            Updated document
        """
        doc.triage_result = result
        doc.quality_score = result.quality_score
        doc.routing = result.routing
        doc.updated_at = datetime.utcnow()

        # Set status based on routing
        if result.routing == RoutingDecision.RESCAN:
            doc.status = DocumentStatus.RESCAN_REQUESTED
        elif result.routing == RoutingDecision.MANUAL_REVIEW:
            doc.status = DocumentStatus.MANUAL_REVIEW
        elif result.routing == RoutingDecision.SKIP:
            doc.status = DocumentStatus.INDEXED  # Skip extraction
        else:
            doc.status = DocumentStatus.TRIAGED

        await db.update_document(doc)
        return doc


# ==============================================================================
# V2: Text-Only Corpus-Informed Triage (3.8x CHEAPER)
# ==============================================================================

# V2 routing decisions include EXTRACT_TEXT for text-only extraction
V2_TRIAGE_SYSTEM_PROMPT = """You are a document classification system.
Analyze the OCR text and classify this document.

CORPUS VOCABULARY (discovered from this archive):
{vocabulary}

KNOWN DOCUMENT TYPES:
{document_types}

KNOWN ENTITY PATTERNS:
{entity_patterns}

OUTPUT (strict JSON, no markdown):
{{
    "document_type": "type from known list or 'other'",
    "document_subtype": "more specific if identifiable, else null",
    "date_detected": "ISO date or range if visible, else null",
    "entities": {{
        "equipment": ["list of equipment/asset IDs"],
        "people": ["list of person names"],
        "locations": ["list of locations"],
        "organizations": ["list of orgs"],
        "references": ["doc numbers, serial numbers, part numbers"]
    }},
    "confidence": 0.0-1.0,
    "routing": "extract_text|extract_vision|manual_review|skip",
    "routing_reason": "brief explanation"
}}

ROUTING RULES:
- extract_text: Good OCR quality, standard content
- extract_vision: Low OCR confidence OR complex tables/forms/drawings
- manual_review: Uncertain classification
- skip: Blank, duplicate, or separator page
"""


class TextOnlyTriageStage:
    """V2 Text-only triage using OCR text (3.8x cheaper than vision).

    Uses corpus profile from discovery phase for informed classification.
    OCR text from ABBYY is sufficient for most triage decisions.
    """

    def __init__(
        self,
        llm: "LLMProvider",
        corpus_profile: CorpusProfile | None = None,
        cost_tracker: "CostTracker | None" = None,
        max_text_length: int = 8000,
    ):
        """Initialize text-only triage stage.

        Args:
            llm: LLM provider (uses text-only calls)
            corpus_profile: Corpus profile from discovery phase
            cost_tracker: Optional cost tracker
            max_text_length: Max characters to send per page
        """
        self.llm = llm
        self.corpus_profile = corpus_profile
        self.cost_tracker = cost_tracker
        self.max_text_length = max_text_length

    def set_corpus_profile(self, profile: CorpusProfile) -> None:
        """Set corpus profile (can be loaded after initialization).

        Args:
            profile: CorpusProfile from discovery phase
        """
        self.corpus_profile = profile

    async def triage_page(
        self,
        ocr_result: OCRResult,
        page_number: int | None = None,
    ) -> TriageResult:
        """Triage single page using text-only (cheap).

        Args:
            ocr_result: OCR result with full text
            page_number: Override page number if needed

        Returns:
            TriageResult with classification and routing
        """
        from athena.utils.parsing import parse_confidence, safe_parse_enum, safe_parse_enum_list

        start_time = datetime.utcnow()
        page_num = page_number or ocr_result.page

        # Build corpus-informed prompt
        prompt = self._build_prompt()

        # Truncate text if too long
        text = ocr_result.full_text[:self.max_text_length]

        response = await self.llm.complete_text(
            system_prompt=prompt,
            user_prompt=f"Classify this document:\n\n{text}",
            max_tokens=1000,
        )

        # Parse response
        result = self._parse_response(response, page_num, ocr_result)

        # Override routing if OCR flagged vision needed
        if ocr_result.needs_vision_review:
            if result.routing in (RoutingDecision.EXTRACT_FULL, RoutingDecision.EXTRACT_LIGHT):
                # Map to vision extraction
                result.routing = RoutingDecision.EXTRACT_FULL
                result.routing_reason = f"OCR triggered: {[t.value for t in ocr_result.vision_triggers]}"

        # Record cost
        if self.cost_tracker:
            await self.cost_tracker.record(
                batch_id="",  # Set by caller
                document_id=None,
                stage="triage",
                cost=response.cost_usd,
                tokens_in=response.tokens_in,
                tokens_out=response.tokens_out,
                model=response.model,
            )

        return result

    def _build_prompt(self) -> str:
        """Build corpus-informed prompt.

        Returns:
            System prompt with corpus context
        """
        if self.corpus_profile:
            vocabulary = list(self.corpus_profile.vocabulary.keys())[:100]
            document_types = list(self.corpus_profile.document_types.keys())
            entity_patterns = self.corpus_profile.entity_patterns
        else:
            vocabulary = []
            document_types = []
            entity_patterns = {}

        return V2_TRIAGE_SYSTEM_PROMPT.format(
            vocabulary=json.dumps(vocabulary),
            document_types=json.dumps(document_types),
            entity_patterns=json.dumps(entity_patterns),
        )

    def _parse_response(
        self,
        response: "LLMResponse",
        page_num: int,
        ocr_result: OCRResult,
    ) -> TriageResult:
        """Parse triage JSON from model response.

        Args:
            response: LLM response
            page_num: Page number
            ocr_result: OCR result for quality score

        Returns:
            Parsed TriageResult
        """
        from athena.utils.parsing import parse_confidence, safe_parse_enum, safe_parse_enum_list

        text = response.content

        # Strip markdown fences if present
        if "```" in text:
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]

        try:
            data = json.loads(text.strip())
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse triage response: {e}")
            return TriageResult(
                document_type="unknown",
                quality_score=ocr_result.average_confidence,
                confidence=0.0,
                routing=RoutingDecision.MANUAL_REVIEW,
                routing_reason="Failed to parse triage response",
                model_used=response.model,
                tokens_in=response.tokens_in,
                tokens_out=response.tokens_out,
                latency_ms=response.latency_ms,
                cost_usd=response.cost_usd,
                pages_analyzed=[page_num],
            )

        # Parse entities
        entities_data = data.get("entities", {})
        entities = EntityBag(
            equipment=entities_data.get("equipment", []),
            people=entities_data.get("people", []),
            locations=entities_data.get("locations", []),
            organizations=entities_data.get("organizations", []),
            references=entities_data.get("references", []),
            dates=entities_data.get("dates", []),
            materials=entities_data.get("materials", []),
        )

        # Map V2 routing decisions to existing enums
        routing_str = data.get("routing", "manual_review")
        if routing_str == "extract_text":
            routing = RoutingDecision.EXTRACT_LIGHT  # Text-only = light extraction
        elif routing_str == "extract_vision":
            routing = RoutingDecision.EXTRACT_FULL  # Vision = full extraction
        else:
            routing = safe_parse_enum(
                RoutingDecision, routing_str, RoutingDecision.MANUAL_REVIEW
            )

        # Use OCR confidence as quality score
        quality_score = ocr_result.average_confidence

        return TriageResult(
            document_type=data.get("document_type", "other"),
            document_subtype=data.get("document_subtype"),
            date_detected=data.get("date_detected"),
            language=data.get("language", "en"),
            entities=entities,
            quality_score=quality_score,
            quality_issues=[],  # Populated by OCR stage
            suggested_schema=[],  # Can be inferred from document type
            confidence=parse_confidence(data.get("confidence", 0.5)),
            routing=routing,
            routing_reason=data.get("routing_reason", ""),
            model_used=response.model,
            tokens_in=response.tokens_in,
            tokens_out=response.tokens_out,
            latency_ms=response.latency_ms,
            cost_usd=response.cost_usd,
            pages_analyzed=[page_num],
        )
