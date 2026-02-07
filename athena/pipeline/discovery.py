#!/usr/bin/env python3
"""
Module: Discovery
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

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Awaitable

from athena.models.discovery import (
    BatchDiscoveryState,
    CorpusProfile,
    DiscoveryAggregator,
    DiscoveryResult,
)
from athena.models.ocr import OCRResult

if TYPE_CHECKING:
    from athena.providers.base import LLMProvider

__all__ = ["DiscoveryStage", "DISCOVERY_SYSTEM_PROMPT"]

logger = logging.getLogger(__name__)


DISCOVERY_SYSTEM_PROMPT = """You are analyzing documents from an unknown archive.
Describe what you observe. Do NOT normalize or interpret - capture exactly what you see.

OUTPUT (strict JSON, no markdown):
{
    "document_type": "your best guess - be specific",
    "era_estimate": "decade if visible (e.g., '1980s', 'unknown')",
    "entities_found": {
        "equipment": ["exact text as written"],
        "people": ["exact text as written"],
        "organizations": ["exact text as written"],
        "reference_numbers": ["exact text as written - part#, serial#, doc#"],
        "dates": ["exact text as written"],
        "other_identifiers": ["anything that looks like an ID or code"]
    },
    "vocabulary_notes": ["unusual terms, abbreviations, jargon - exact as written"],
    "form_number": "if visible (e.g., 'DA-2404', 'SF-368')",
    "condition_notes": ["handwritten", "typed", "faded", "stamp", "carbon copy"],
    "content_summary": "2-3 sentences describing what this document is about"
}
"""


class DiscoveryStage:
    """Run discovery on corpus to build vocabulary and taxonomy.

    CRITICAL: Uses TEXT-ONLY Haiku calls (3.8x cheaper than vision).
    OCR text from ABBYY is sufficient for discovery.

    CRITICAL: Saves progress INCREMENTALLY after each page.
    The Wasted Run of 2025-12-22: Never lose progress on interrupt.
    """

    def __init__(
        self,
        llm: "LLMProvider",
        max_text_length: int = 8000,
    ):
        """Initialize discovery stage.

        Args:
            llm: LLM provider (uses text-only calls)
            max_text_length: Max characters to send per page
        """
        self.llm = llm
        self.max_text_length = max_text_length
        self.aggregator = DiscoveryAggregator()

    async def discover_page(
        self,
        ocr_result: OCRResult,
        page_number: int | None = None,
    ) -> DiscoveryResult:
        """Run discovery on single page (text-only, cheap).

        Args:
            ocr_result: OCR result with full text
            page_number: Override page number if needed

        Returns:
            DiscoveryResult with observations
        """
        page_num = page_number or ocr_result.page

        # Truncate text if too long
        text = ocr_result.full_text[:self.max_text_length]

        response = await self.llm.complete_text(
            system_prompt=DISCOVERY_SYSTEM_PROMPT,
            user_prompt=f"Analyze this document page:\n\n{text}",
            max_tokens=1000,
        )

        try:
            # Parse JSON response
            content = response.content
            if "```" in content:
                content = content.split("```")[1]
                if content.startswith("json"):
                    content = content[4:]

            data = json.loads(content.strip())

            result = DiscoveryResult(
                page=page_num,
                document_type=data.get("document_type", "unknown"),
                era_estimate=data.get("era_estimate"),
                entities_found=data.get("entities_found", {}),
                vocabulary_notes=data.get("vocabulary_notes", []),
                form_number=data.get("form_number"),
                condition_notes=data.get("condition_notes", []),
                content_summary=data.get("content_summary"),
            )

            # Add to aggregator
            self.aggregator.add_discovery_result(result)

            return result

        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse discovery response for page {page_num}: {e}")
            return DiscoveryResult(
                page=page_num,
                document_type="parse_error",
            )

    async def discover_batch(
        self,
        ocr_results: list[OCRResult],
        batch_id: str,
        save_callback: Callable[[BatchDiscoveryState], Awaitable[None]] | None = None,
        sample_ratio: float = 1.0,
    ) -> BatchDiscoveryState:
        """Run discovery on batch with incremental saving.

        CRITICAL: Saves after EACH page via save_callback.

        Args:
            ocr_results: List of OCR results
            batch_id: Batch identifier
            save_callback: Called after each page with current state
            sample_ratio: Fraction of pages to sample (1.0 = all)

        Returns:
            BatchDiscoveryState with all results and profile
        """
        # Optionally sample for large corpora
        if sample_ratio < 1.0:
            import random
            sample_size = max(1, int(len(ocr_results) * sample_ratio))
            sample = random.sample(ocr_results, sample_size)
        else:
            sample = ocr_results

        # Initialize state
        state = BatchDiscoveryState(
            batch_id=batch_id,
            total_pages=len(sample),
            started_at=datetime.utcnow(),
        )

        # Process each page with incremental save
        for i, ocr_result in enumerate(sample):
            try:
                result = await self.discover_page(ocr_result)
                state.add_result(result)

                logger.info(
                    f"Discovery progress: {state.pages_discovered}/{state.total_pages} "
                    f"(type: {result.document_type})"
                )

                # CRITICAL: Save after each page
                if save_callback:
                    await save_callback(state)

            except Exception as e:
                logger.error(f"Discovery failed for page {ocr_result.page}: {e}")
                # Continue with next page - don't lose progress

        # Build final profile
        state.profile = self.aggregator.build_profile()
        state.completed_at = datetime.utcnow()
        state.processing_complete = True

        # Final save
        if save_callback:
            await save_callback(state)

        return state

    def build_profile(self) -> CorpusProfile:
        """Build corpus profile from aggregated results.

        Returns:
            CorpusProfile with document types, vocabulary, patterns
        """
        return self.aggregator.build_profile()

    def reset(self) -> None:
        """Reset aggregator for new discovery run."""
        self.aggregator = DiscoveryAggregator()


async def save_discovery_state(
    state: BatchDiscoveryState,
    output_path: Path,
) -> None:
    """Default save callback for discovery state.

    Saves state as JSON after each page.

    Args:
        state: Current discovery state
        output_path: Path to save JSON
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Convert to JSON-serializable dict
    data = {
        "batch_id": state.batch_id,
        "total_pages": state.total_pages,
        "pages_discovered": state.pages_discovered,
        "results": [r.model_dump() for r in state.results],
        "started_at": state.started_at.isoformat() if state.started_at else None,
        "completed_at": state.completed_at.isoformat() if state.completed_at else None,
        "processing_complete": state.processing_complete,
    }

    # Include profile if built
    if state.profile:
        data["profile"] = {
            "document_types": state.profile.document_types,
            "entity_patterns": state.profile.entity_patterns,
            "vocabulary": state.profile.vocabulary,
            "form_numbers": state.profile.form_numbers,
            "total_pages": state.profile.total_pages,
        }

    with open(output_path, "w") as f:
        json.dump(data, f, indent=2)

    logger.debug(f"Saved discovery state: {state.pages_discovered} pages to {output_path}")
