#!/usr/bin/env python3
"""
Module: Alto Parser
Purpose: alto_parser

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

import logging
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path
from typing import Iterator

from athena.models.ocr import ALTOPage, ALTOWord

__all__ = ["ALTOParser"]

logger = logging.getLogger(__name__)


class ALTOParser:
    """Parse ABBYY ALTO XML output into structured page/word data.

    ALTO XML contains word-level OCR with coordinates and confidence.
    Evidence bounding boxes come FREE from ALTO - no LLM cost.
    """

    # ALTO namespace - version 3 is most common
    ALTO_NS = {
        "alto": "http://www.loc.gov/standards/alto/ns-v3#",
        "alto2": "http://www.loc.gov/standards/alto/ns-v2#",
        "alto4": "http://www.loc.gov/standards/alto/ns-v4#",
    }

    def __init__(self, confidence_threshold: float = 0.7):
        """Initialize ALTO parser.

        Args:
            confidence_threshold: Threshold below which words are flagged
        """
        self.confidence_threshold = confidence_threshold
        self._detected_namespace: str | None = None

    def parse_file(self, alto_path: Path | str) -> list[ALTOPage]:
        """Parse ALTO XML file into structured pages.

        Args:
            alto_path: Path to ALTO XML file

        Returns:
            List of ALTOPage objects with word-level data

        Raises:
            FileNotFoundError: If file doesn't exist
            ET.ParseError: If XML is malformed
        """
        alto_path = Path(alto_path)
        if not alto_path.exists():
            raise FileNotFoundError(f"ALTO file not found: {alto_path}")

        tree = ET.parse(alto_path)
        root = tree.getroot()

        # Detect namespace
        self._detect_namespace(root)

        pages = []
        for page_idx, page_elem in enumerate(self._find_pages(root)):
            pages.append(self._parse_page(page_elem, page_idx + 1))

        logger.info(f"Parsed {len(pages)} pages from {alto_path.name}")
        return pages

    def parse_string(self, alto_xml: str) -> list[ALTOPage]:
        """Parse ALTO XML from string.

        Args:
            alto_xml: ALTO XML content as string

        Returns:
            List of ALTOPage objects
        """
        root = ET.fromstring(alto_xml)
        self._detect_namespace(root)

        pages = []
        for page_idx, page_elem in enumerate(self._find_pages(root)):
            pages.append(self._parse_page(page_elem, page_idx + 1))

        return pages

    def _detect_namespace(self, root: ET.Element) -> None:
        """Auto-detect ALTO namespace version.

        Args:
            root: Root XML element
        """
        # Check tag for namespace
        tag = root.tag
        if "{" in tag:
            ns = tag.split("}")[0].strip("{")
            for prefix, uri in self.ALTO_NS.items():
                if uri == ns:
                    self._detected_namespace = prefix
                    return

        # Try each namespace to find Page elements
        for prefix, ns in self.ALTO_NS.items():
            if root.findall(f".//{{{ns}}}Page"):
                self._detected_namespace = prefix
                return

        # Fallback to no namespace (some ALTO files)
        self._detected_namespace = None
        logger.warning("Could not detect ALTO namespace, using unqualified names")

    def _find_pages(self, root: ET.Element) -> Iterator[ET.Element]:
        """Find all Page elements handling namespace.

        Args:
            root: Root XML element

        Yields:
            Page elements
        """
        if self._detected_namespace:
            ns = self.ALTO_NS[self._detected_namespace]
            yield from root.findall(f".//{{{ns}}}Page")
        else:
            # Try without namespace
            yield from root.findall(".//Page")

    def _parse_page(self, page_elem: ET.Element, page_num: int) -> ALTOPage:
        """Parse single ALTO Page element.

        Args:
            page_elem: Page XML element
            page_num: 1-indexed page number

        Returns:
            ALTOPage with word data
        """
        width = int(page_elem.get("WIDTH", 0))
        height = int(page_elem.get("HEIGHT", 0))

        words = []
        for string_elem in self._find_strings(page_elem):
            word = self._parse_string_element(string_elem, page_num)
            if word:
                words.append(word)

        return ALTOPage(
            page_number=page_num,
            width=width,
            height=height,
            words=words,
        )

    def _find_strings(self, page_elem: ET.Element) -> Iterator[ET.Element]:
        """Find all String elements in page.

        Args:
            page_elem: Page XML element

        Yields:
            String elements (individual words)
        """
        if self._detected_namespace:
            ns = self.ALTO_NS[self._detected_namespace]
            yield from page_elem.findall(f".//{{{ns}}}String")
        else:
            yield from page_elem.findall(".//String")

    def _parse_string_element(
        self,
        string_elem: ET.Element,
        page_num: int
    ) -> ALTOWord | None:
        """Parse single String element into ALTOWord.

        Args:
            string_elem: String XML element
            page_num: Page number

        Returns:
            ALTOWord or None if invalid
        """
        content = string_elem.get("CONTENT", "")
        if not content:
            return None

        try:
            word = ALTOWord(
                content=content,
                x=int(float(string_elem.get("HPOS", 0))),
                y=int(float(string_elem.get("VPOS", 0))),
                width=int(float(string_elem.get("WIDTH", 0))),
                height=int(float(string_elem.get("HEIGHT", 0))),
                confidence=float(string_elem.get("WC", 0.0)),
                page=page_num,
            )
            return word
        except (ValueError, TypeError) as e:
            logger.warning(f"Failed to parse String element: {e}")
            return None

    def extract_vocabulary(self, pages: list[ALTOPage]) -> dict[str, int]:
        """Extract word frequency for discovery phase.

        Args:
            pages: List of parsed ALTO pages

        Returns:
            Dictionary of normalized word -> count
        """
        all_words: list[str] = []
        for page in pages:
            for word in page.words:
                # Normalize: lowercase, strip punctuation
                normalized = word.content.lower().strip(".,;:!?\"'()-")
                if len(normalized) > 2:  # Skip very short words
                    all_words.append(normalized)

        return dict(Counter(all_words).most_common())

    def get_low_confidence_regions(
        self,
        page: ALTOPage,
        threshold: float | None = None
    ) -> list[dict]:
        """Get regions with low OCR confidence for vision review.

        Args:
            page: ALTOPage to analyze
            threshold: Confidence threshold (uses self.confidence_threshold if None)

        Returns:
            List of bounding boxes with low-confidence words
        """
        threshold = threshold or self.confidence_threshold
        regions = []

        for word in page.words:
            if word.confidence < threshold:
                regions.append({
                    "word": word.content,
                    "confidence": word.confidence,
                    "bbox": word.to_normalized_bbox(page.width, page.height),
                    "page": word.page,
                })

        return regions
