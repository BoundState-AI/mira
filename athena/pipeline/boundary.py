#!/usr/bin/env python3
"""
Module: Boundary
Purpose: ATHENA Boundary Detection Pipeline.

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
from typing import TYPE_CHECKING

from athena.models.enums import BoundarySignal
from athena.models.review import BoundaryCandidate
from athena.models.separator import FolderSegment, SeparatorResult
from athena.utils.barcode import scan_barcode, extract_separator_id, SEPARATOR_BARCODE_PREFIX

if TYPE_CHECKING:
    import fitz
    from athena.config import AthenaConfig
    from athena.providers.base import LLMProvider
    from athena.services.storage import FileStore

logger = logging.getLogger(__name__)


# Signal weights for probabilistic combination
SIGNAL_WEIGHTS = {
    BoundarySignal.BLANK_OR_SEPARATOR_LIKELY: 0.4,  # Weak alone
    BoundarySignal.BARCODE_DIVIDER: 0.9,
    BoundarySignal.PAGE_NUMBERING_RESET: 0.7,
    BoundarySignal.LETTERHEAD_CHANGE: 0.6,
    BoundarySignal.DATE_DISCONTINUITY: 0.5,
    BoundarySignal.FORM_NUMBER_CHANGE: 0.6,
    BoundarySignal.ORIENTATION_CHANGE: 0.4,
    BoundarySignal.CLASSIFICATION_CHANGE: 0.5,
}


def combine_signal_confidences(signals: list[BoundarySignal]) -> float:
    """Probabilistic combination: 1 - Π(1 - w_i).

    Naturally bounded [0, 1].

    Args:
        signals: List of detected signals

    Returns:
        Combined confidence score
    """
    if not signals:
        return 0.0

    weights = [SIGNAL_WEIGHTS.get(s, 0.3) for s in signals]
    prob_all_wrong = 1.0
    for w in weights:
        prob_all_wrong *= 1.0 - w

    return 1.0 - prob_all_wrong


def should_create_boundary(signals: list[BoundarySignal], confidence: float) -> bool:
    """Determine if signals warrant split.

    Blank alone is NOT enough - requires corroboration.

    Args:
        signals: Detected signals
        confidence: Combined confidence

    Returns:
        True if boundary should be created
    """
    # Single blank = weak, need more
    if signals == [BoundarySignal.BLANK_OR_SEPARATOR_LIKELY]:
        return False

    # Barcode divider = strong
    if BoundarySignal.BARCODE_DIVIDER in signals:
        return confidence >= 0.7

    # Blank + page reset = strong
    if (
        BoundarySignal.BLANK_OR_SEPARATOR_LIKELY in signals
        and BoundarySignal.PAGE_NUMBERING_RESET in signals
    ):
        return confidence >= 0.6

    # Multiple non-blank signals
    non_blank = [s for s in signals if s != BoundarySignal.BLANK_OR_SEPARATOR_LIKELY]
    if len(non_blank) >= 2:
        return confidence >= 0.65

    return confidence >= 0.8


async def detect_page_number_in_footer(
    page: "fitz.Page",
    llm: LLMProvider,
) -> tuple[bool, int | None]:
    """Use VISION to detect page number.

    get_text() does NOT work on scanned images.

    Args:
        page: PyMuPDF page
        llm: LLM provider

    Returns:
        Tuple of (has_page_number, page_number)
    """
    footer_b64 = get_page_footer_region(page, footer_height_pct=0.12, dpi=200)

    response = await llm.complete_vision(
        images=[footer_b64],
        system_prompt=PAGE_NUMBER_DETECTION_PROMPT,
        user_prompt="Analyze this footer region.",
        max_tokens=100,
        model_key="triage",
    )

    try:
        # Strip markdown if present
        text = response.content
        if "```" in text:
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]

        result = json.loads(text.strip())
        return (result.get("has_page_number", False), result.get("page_number"))
    except (json.JSONDecodeError, KeyError):
        logger.warning(f"Failed to parse page number response: {response.content}")
        return (False, None)


class BoundaryDetector:
    """Full boundary detection with heuristics and vision confirmation."""

    def __init__(
        self,
        config: AthenaConfig,
        llm: LLMProvider,
        storage: FileStore | None = None,
    ):
        """Initialize boundary detector.

        Args:
            config: ATHENA configuration
            llm: LLM provider for vision analysis
            storage: File storage for page images
        """
        self.config = config
        self.llm = llm
        self.storage = storage
        self.blank_detector = BlankPageDetector()

    async def detect_boundaries(
        self,
        doc: "fitz.Document",
        source_file: str,
        batch_id: str,
    ) -> list[tuple[int, int]]:
        """Detect document boundaries in a multi-page PDF.

        Args:
            doc: PyMuPDF document
            source_file: Source file name
            batch_id: Batch ID for storage

        Returns:
            List of (start_page, end_page) ranges (1-indexed)
        """
        # Calibrate blank detector on this document
        self.blank_detector.calibrate(list(doc))

        # Heuristic detection
        candidates = await self._heuristic_detection(doc)
        logger.info(f"Found {len(candidates)} boundary candidates via heuristics")

        # Vision confirmation for candidates
        confirmed = await self._confirm_with_vision(doc, candidates)
        logger.info(f"Confirmed {len(confirmed)} boundaries via vision")

        # Resolve to page ranges
        return self._resolve_boundaries(confirmed, len(doc))

    async def _heuristic_detection(
        self, doc: "fitz.Document"
    ) -> list[BoundaryCandidate]:
        """Detect potential boundaries using heuristics.

        Args:
            doc: PyMuPDF document

        Returns:
            List of boundary candidates
        """
        candidates = []

        for i in range(len(doc) - 1):
            signals: list[BoundarySignal] = []

            # Check for blank page
            is_blank, blank_conf = self.blank_detector.is_likely_blank(doc[i])
            if is_blank:
                signals.append(BoundarySignal.BLANK_OR_SEPARATOR_LIKELY)

            # Check page number reset on next page
            has_num, num = await detect_page_number_in_footer(doc[i + 1], self.llm)
            if has_num and num == 1:
                signals.append(BoundarySignal.PAGE_NUMBERING_RESET)

            # Check orientation change
            if self._orientation_changed(doc[i], doc[i + 1]):
                signals.append(BoundarySignal.ORIENTATION_CHANGE)

            if signals:
                candidates.append(
                    BoundaryCandidate(
                        after_page=i + 1,  # 1-indexed
                        signals=signals,
                        confidence=combine_signal_confidences(signals),
                    )
                )

        return candidates

    async def _confirm_with_vision(
        self,
        doc: "fitz.Document",
        candidates: list[BoundaryCandidate],
    ) -> list[BoundaryCandidate]:
        """Confirm candidates using vision analysis.

        Args:
            doc: PyMuPDF document
            candidates: Boundary candidates to confirm

        Returns:
            Confirmed candidates
        """
        confirmed = []

        for candidate in candidates:
            before_idx = candidate.after_page - 1  # 0-indexed
            after_idx = candidate.after_page  # 0-indexed

            if after_idx >= len(doc):
                continue

            # Get images of both pages
            images = pages_to_images(doc, before_idx, after_idx + 1, dpi=150)

            response = await self.llm.complete_vision(
                images=images,
                system_prompt=BOUNDARY_CONFIRMATION_PROMPT,
                user_prompt=f"Signals detected: {[s.value for s in candidate.signals]}",
                max_tokens=500,
                model_key="triage",
            )

            try:
                text = response.content
                if "```" in text:
                    text = text.split("```")[1]
                    if text.startswith("json"):
                        text = text[4:]

                result = json.loads(text.strip())
            except (json.JSONDecodeError, KeyError):
                logger.warning(f"Failed to parse boundary response: {response.content}")
                # Reduce confidence for failed parse
                candidate.confidence *= 0.5
                confirmed.append(candidate)
                continue

            # HONOR is_boundary response from model
            if not result.get("is_boundary", True):
                logger.debug(f"Model rejected boundary at page {candidate.after_page}")
                continue  # Drop candidate

            # Update confidence from model
            model_confidence = parse_confidence(result.get("confidence", 0.5))
            candidate.confidence = (candidate.confidence + model_confidence) / 2

            # Add additional signals from model
            for sig_str in result.get("additional_signals", []):
                parsed = safe_parse_enum(BoundarySignal, sig_str)
                if parsed and parsed not in candidate.signals:
                    candidate.signals.append(parsed)

            confirmed.append(candidate)

        return confirmed

    def _resolve_boundaries(
        self,
        candidates: list[BoundaryCandidate],
        total_pages: int,
    ) -> list[tuple[int, int]]:
        """Convert candidates to (start, end) page ranges.

        Args:
            candidates: Confirmed boundary candidates
            total_pages: Total pages in document

        Returns:
            List of (start, end) 1-indexed page ranges
        """
        ranges = []
        start = 1  # 1-indexed

        # Sort by page number
        sorted_candidates = sorted(candidates, key=lambda c: c.after_page)

        for cand in sorted_candidates:
            if should_create_boundary(cand.signals, cand.confidence):
                # Skip blank pages at boundaries
                end = cand.after_page
                if BoundarySignal.BLANK_OR_SEPARATOR_LIKELY in cand.signals:
                    # Don't include the blank page in either document
                    if end > start:
                        ranges.append((start, end - 1))
                    start = cand.after_page + 1
                else:
                    ranges.append((start, end))
                    start = cand.after_page + 1

        # Add final range
        if start <= total_pages:
            ranges.append((start, total_pages))

        return ranges

    def _orientation_changed(
        self, page1: "fitz.Page", page2: "fitz.Page"
    ) -> bool:
        """Check if page orientation changed.

        Args:
            page1: First page
            page2: Second page

        Returns:
            True if orientation changed
        """
        r1, r2 = page1.rect, page2.rect
        p1_portrait = r1.height > r1.width
        p2_portrait = r2.height > r2.width
        return p1_portrait != p2_portrait

    async def create_review_items(
        self,
        candidates: list[BoundaryCandidate],
        doc: "fitz.Document",
        source_file: str,
        batch_id: str,
    ) -> list[dict]:
        """Create review items for uncertain boundaries.

        Args:
            candidates: Boundary candidates
            doc: PyMuPDF document
            source_file: Source file name
            batch_id: Batch ID

        Returns:
            List of review item dictionaries
        """
        from athena.models.review import BoundaryReviewItem

        review_items = []

        for candidate in candidates:
            # Only review if confidence is in uncertain range
            if 0.4 <= candidate.confidence <= 0.8:
                before_idx = candidate.after_page - 1
                after_idx = candidate.after_page

                page_paths = []
                page_numbers = []

                # Store page images if storage available
                if self.storage:
                    for idx in [before_idx, after_idx]:
                        if idx < len(doc):
                            images = pages_to_images(doc, idx, idx + 1, dpi=200)
                            path = await self.storage.upload_page_image(
                                batch_id, source_file, idx + 1, images[0].encode()
                            )
                            page_paths.append(path)
                            page_numbers.append(idx + 1)

                item = BoundaryReviewItem(
                    batch_id=batch_id,
                    source_file=source_file,
                    candidate=candidate,
                    page_image_paths=page_paths,
                    page_numbers=page_numbers,
                )
                review_items.append(item.model_dump())

        return review_items


# ==============================================================================
# V2: Separator-Based Boundary Detection (PRIMARY METHOD)
# ==============================================================================

class SeparatorDetector:
    """V2 Separator-based boundary detection.

    Uses barcode scanning for DETERMINISTIC boundary detection.
    Confidence is always 1.0 - barcodes don't have false positives.

    This eliminates the probabilistic guessing of V1 boundary detection.
    """

    def __init__(
        self,
        barcode_prefix: str = SEPARATOR_BARCODE_PREFIX,
        dpi: int = 150,
    ):
        """Initialize separator detector.

        Args:
            barcode_prefix: Expected barcode prefix
            dpi: Resolution for barcode scanning
        """
        self.barcode_prefix = barcode_prefix
        self.dpi = dpi

    def detect_separators(
        self,
        doc: "fitz.Document",
    ) -> list[tuple[int, SeparatorResult]]:
        """Detect all separator sheets in document.

        Args:
            doc: PyMuPDF document

        Returns:
            List of (page_number, SeparatorResult) tuples, 1-indexed
        """
        separators = []

        for page_idx in range(len(doc)):
            page = doc[page_idx]
            barcode_data = scan_barcode(page, self.dpi, self.barcode_prefix)

            if barcode_data:
                sep_id = extract_separator_id(barcode_data)
                if sep_id:
                    separator = SeparatorResult(
                        separator_id=sep_id,
                        confidence=1.0,  # Barcode = deterministic
                    )
                    separators.append((page_idx + 1, separator))  # 1-indexed
                    logger.info(f"Found separator at page {page_idx + 1}: {sep_id[:8]}...")

        return separators

    def create_folder_segments(
        self,
        doc: "fitz.Document",
        batch_id: str,
    ) -> list[FolderSegment]:
        """Create folder segments from separator sheets.

        Each segment contains pages between consecutive separators.
        Separator pages themselves are excluded from segments.

        Args:
            doc: PyMuPDF document
            batch_id: Batch identifier

        Returns:
            List of FolderSegment objects
        """
        separators = self.detect_separators(doc)

        if not separators:
            logger.warning("No separators found - treating entire PDF as one segment")
            # Create single segment for entire document
            return [
                FolderSegment(
                    batch_id=batch_id,
                    separator=SeparatorResult(
                        separator_id="no-separator",
                        confidence=0.0,
                    ),
                    page_range=(1, len(doc)),
                    page_count=len(doc),
                )
            ]

        segments = []
        total_pages = len(doc)

        for i, (sep_page, separator) in enumerate(separators):
            # Segment starts after this separator
            start_page = sep_page + 1

            # Segment ends at next separator or end of document
            if i + 1 < len(separators):
                next_sep_page = separators[i + 1][0]
                end_page = next_sep_page - 1
            else:
                end_page = total_pages

            # Skip if segment is empty
            if start_page > end_page:
                continue

            segment = FolderSegment(
                batch_id=batch_id,
                separator=separator,
                page_range=(start_page, end_page),
                page_count=end_page - start_page + 1,
            )
            segments.append(segment)
            logger.info(
                f"Created segment: pages {start_page}-{end_page} "
                f"({segment.page_count} pages, folder: {separator.folder_name or 'unnamed'})"
            )

        return segments

    def get_boundary_pages(self, doc: "fitz.Document") -> list[int]:
        """Get list of page numbers that are separator sheets.

        Useful for excluding separator pages from processing.

        Args:
            doc: PyMuPDF document

        Returns:
            List of 1-indexed page numbers that are separators
        """
        separators = self.detect_separators(doc)
        return [page_num for page_num, _ in separators]


class HybridBoundaryDetector:
    """V2 Hybrid boundary detection.

    Combines:
    1. Separator detection (PRIMARY) - deterministic, confidence=1.0
    2. Heuristic detection (FALLBACK) - for documents without separators

    Use separator detection when possible. Fall back to heuristics
    only for legacy documents that weren't scanned with separators.
    """

    def __init__(
        self,
        config: "AthenaConfig",
        llm: "LLMProvider | None" = None,
        storage: "FileStore | None" = None,
        barcode_prefix: str = SEPARATOR_BARCODE_PREFIX,
    ):
        """Initialize hybrid detector.

        Args:
            config: ATHENA configuration
            llm: LLM provider for heuristic fallback
            storage: File storage for page images
            barcode_prefix: Expected barcode prefix
        """
        self.config = config
        self.separator_detector = SeparatorDetector(barcode_prefix)

        # Heuristic detector only if LLM provided
        if llm:
            self.heuristic_detector = BoundaryDetector(config, llm, storage)
        else:
            self.heuristic_detector = None

    async def detect_boundaries(
        self,
        doc: "fitz.Document",
        source_file: str,
        batch_id: str,
        prefer_separators: bool = True,
    ) -> list[tuple[int, int]]:
        """Detect document boundaries using hybrid approach.

        Args:
            doc: PyMuPDF document
            source_file: Source file name
            batch_id: Batch ID
            prefer_separators: If True, use separators when found

        Returns:
            List of (start_page, end_page) ranges (1-indexed)
        """
        if prefer_separators:
            # Try separator detection first
            separators = self.separator_detector.detect_separators(doc)

            if separators:
                logger.info(f"Using separator-based detection: {len(separators)} separators found")
                segments = self.separator_detector.create_folder_segments(doc, batch_id)
                return [(s.page_range[0], s.page_range[1]) for s in segments]

            logger.info("No separators found - falling back to heuristic detection")

        # Fall back to heuristic detection
        if self.heuristic_detector:
            return await self.heuristic_detector.detect_boundaries(doc, source_file, batch_id)

        # No heuristic detector available - treat as single document
        logger.warning("No heuristic detector available - treating as single document")
        return [(1, len(doc))]

    def create_folder_segments(
        self,
        doc: "fitz.Document",
        batch_id: str,
    ) -> list[FolderSegment]:
        """Create folder segments (separator-based only).

        Args:
            doc: PyMuPDF document
            batch_id: Batch identifier

        Returns:
            List of FolderSegment objects
        """
        return self.separator_detector.create_folder_segments(doc, batch_id)
