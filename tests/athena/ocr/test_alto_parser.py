#!/usr/bin/env python3
"""
Module: Test Alto Parser
Purpose: Tests for athena.ocr.alto_parser module.

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

import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock
from xml.etree import ElementTree as ET

import pytest

# Mock cv2 before importing athena.ocr to avoid import errors
sys.modules.setdefault('cv2', MagicMock())

# Import directly from the module file to avoid package __init__ imports
import importlib.util
_alto_path = Path(__file__).parent.parent.parent.parent / "athena" / "ocr" / "alto_parser.py"
_spec = importlib.util.spec_from_file_location("alto_parser", _alto_path)
_alto_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_alto_module)
ALTOParser = _alto_module.ALTOParser


class TestALTOParserNamespaceDetection:
    """Tests for ALTO namespace auto-detection."""

    def test_detect_namespace_v3(self, sample_alto_xml_v3):
        """Detect ALTO v3 namespace."""
        parser = ALTOParser()
        pages = parser.parse_string(sample_alto_xml_v3)

        assert parser._detected_namespace == "alto"
        assert len(pages) == 1

    def test_detect_namespace_v2(self, sample_alto_xml_v2):
        """Detect ALTO v2 namespace."""
        parser = ALTOParser()
        pages = parser.parse_string(sample_alto_xml_v2)

        assert parser._detected_namespace == "alto2"
        assert len(pages) == 1

    def test_detect_namespace_fallback(self, sample_alto_xml_no_namespace):
        """Fallback to no namespace for legacy ALTO."""
        parser = ALTOParser()
        pages = parser.parse_string(sample_alto_xml_no_namespace)

        assert parser._detected_namespace is None
        assert len(pages) == 1


class TestALTOParserFileOperations:
    """Tests for file-based parsing."""

    def test_parse_file_success(self, sample_alto_xml_v3):
        """Parse ALTO XML from file."""
        parser = ALTOParser()

        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".xml",
            delete=False,
            encoding="utf-8",
        ) as f:
            f.write(sample_alto_xml_v3)
            temp_path = Path(f.name)

        try:
            pages = parser.parse_file(temp_path)

            assert len(pages) == 1
            assert pages[0].page_number == 1
        finally:
            temp_path.unlink()

    def test_parse_file_missing_file(self):
        """FileNotFoundError raised for missing file."""
        parser = ALTOParser()

        with pytest.raises(FileNotFoundError):
            parser.parse_file(Path("/nonexistent/file.xml"))

    def test_parse_string_malformed_xml(self):
        """ET.ParseError handled for malformed XML."""
        parser = ALTOParser()

        with pytest.raises(ET.ParseError):
            parser.parse_string("<not valid xml>")


class TestALTOParserPageParsing:
    """Tests for page-level parsing."""

    def test_parse_page_dimensions(self, sample_alto_xml_v3):
        """Page dimensions are extracted correctly."""
        parser = ALTOParser()
        pages = parser.parse_string(sample_alto_xml_v3)

        assert pages[0].width == 2480
        assert pages[0].height == 3508

    def test_parse_multipage(self, sample_alto_xml_multipage):
        """Parse multi-page ALTO document."""
        parser = ALTOParser()
        pages = parser.parse_string(sample_alto_xml_multipage)

        assert len(pages) == 2
        assert pages[0].page_number == 1
        assert pages[1].page_number == 2

    def test_parse_words_extraction(self, sample_alto_xml_v3):
        """Words are extracted with correct attributes."""
        parser = ALTOParser()
        pages = parser.parse_string(sample_alto_xml_v3)

        words = pages[0].words
        assert len(words) == 3

        # Check first word
        assert words[0].content == "Hello"
        assert words[0].confidence == 0.95
        assert words[0].x == 100
        assert words[0].y == 200


class TestALTOParserWordParsing:
    """Tests for word-level parsing."""

    def test_word_coordinates(self, sample_alto_xml_v3):
        """Word coordinates are parsed correctly."""
        parser = ALTOParser()
        pages = parser.parse_string(sample_alto_xml_v3)

        word = pages[0].words[0]

        assert word.x == 100       # HPOS
        assert word.y == 200       # VPOS
        assert word.width == 50
        assert word.height == 20

    def test_word_confidence(self, sample_alto_xml_v3):
        """Word confidence values are parsed correctly."""
        parser = ALTOParser()
        pages = parser.parse_string(sample_alto_xml_v3)

        confidences = [w.confidence for w in pages[0].words]

        assert confidences == [0.95, 0.88, 0.65]

    def test_word_page_assignment(self, sample_alto_xml_multipage):
        """Words have correct page numbers assigned."""
        parser = ALTOParser()
        pages = parser.parse_string(sample_alto_xml_multipage)

        # All words on page 1 should have page=1
        for word in pages[0].words:
            assert word.page == 1

        # All words on page 2 should have page=2
        for word in pages[1].words:
            assert word.page == 2

    def test_empty_content_word_skipped(self):
        """Words with empty CONTENT are skipped."""
        xml = '''<?xml version="1.0" encoding="UTF-8"?>
<alto xmlns="http://www.loc.gov/standards/alto/ns-v3#">
  <Layout>
    <Page WIDTH="1000" HEIGHT="1000">
      <PrintSpace>
        <TextBlock>
          <TextLine>
            <String CONTENT="" WC="0.5" HPOS="10" VPOS="10" WIDTH="10" HEIGHT="10"/>
            <String CONTENT="Valid" WC="0.9" HPOS="20" VPOS="10" WIDTH="10" HEIGHT="10"/>
          </TextLine>
        </TextBlock>
      </PrintSpace>
    </Page>
  </Layout>
</alto>'''

        parser = ALTOParser()
        pages = parser.parse_string(xml)

        # Only the "Valid" word should be present
        assert len(pages[0].words) == 1
        assert pages[0].words[0].content == "Valid"


class TestALTOParserVocabularyExtraction:
    """Tests for vocabulary extraction."""

    def test_extract_vocabulary(self, sample_alto_xml_v3):
        """Word frequencies extracted correctly."""
        parser = ALTOParser()
        pages = parser.parse_string(sample_alto_xml_v3)

        vocab = parser.extract_vocabulary(pages)

        assert isinstance(vocab, dict)
        assert "hello" in vocab
        assert "world" in vocab
        assert "test" in vocab

    def test_extract_vocabulary_normalization(self, sample_alto_xml_v3):
        """Vocabulary is normalized to lowercase."""
        parser = ALTOParser()
        pages = parser.parse_string(sample_alto_xml_v3)

        vocab = parser.extract_vocabulary(pages)

        # Should be lowercase
        assert "hello" in vocab
        assert "Hello" not in vocab

    def test_extract_vocabulary_short_words_filtered(self):
        """Words <= 2 characters are filtered."""
        xml = '''<?xml version="1.0" encoding="UTF-8"?>
<alto xmlns="http://www.loc.gov/standards/alto/ns-v3#">
  <Layout>
    <Page WIDTH="1000" HEIGHT="1000">
      <PrintSpace>
        <TextBlock>
          <TextLine>
            <String CONTENT="A" WC="0.9" HPOS="10" VPOS="10" WIDTH="10" HEIGHT="10"/>
            <String CONTENT="to" WC="0.9" HPOS="20" VPOS="10" WIDTH="10" HEIGHT="10"/>
            <String CONTENT="the" WC="0.9" HPOS="30" VPOS="10" WIDTH="10" HEIGHT="10"/>
            <String CONTENT="test" WC="0.9" HPOS="40" VPOS="10" WIDTH="10" HEIGHT="10"/>
          </TextLine>
        </TextBlock>
      </PrintSpace>
    </Page>
  </Layout>
</alto>'''

        parser = ALTOParser()
        pages = parser.parse_string(xml)
        vocab = parser.extract_vocabulary(pages)

        # "A" and "to" should be filtered (len <= 2)
        assert "a" not in vocab
        assert "to" not in vocab
        # "the" and "test" should be present (len > 2)
        assert "the" in vocab
        assert "test" in vocab

    def test_extract_vocabulary_empty_pages(self):
        """Empty pages return empty vocabulary."""
        parser = ALTOParser()
        vocab = parser.extract_vocabulary([])

        assert vocab == {}


class TestALTOParserLowConfidenceRegions:
    """Tests for low confidence region detection."""

    def test_get_low_confidence_regions(self, sample_alto_page):
        """Get regions with low OCR confidence."""
        parser = ALTOParser()

        regions = parser.get_low_confidence_regions(sample_alto_page)

        # Only "Low" word (0.60) should be below 0.7 threshold
        assert len(regions) == 1
        assert regions[0]["word"] == "Low"
        assert regions[0]["confidence"] == 0.60

    def test_get_low_confidence_custom_threshold(self, sample_alto_page):
        """Custom threshold affects region detection."""
        parser = ALTOParser()

        # Higher threshold should catch more words
        regions = parser.get_low_confidence_regions(sample_alto_page, threshold=0.90)

        # "World" (0.88) and "Low" (0.60) should be below 0.90
        assert len(regions) == 2

    def test_get_low_confidence_regions_include_bbox(self, sample_alto_page):
        """Regions include normalized bounding box."""
        parser = ALTOParser()

        regions = parser.get_low_confidence_regions(sample_alto_page)

        assert len(regions) == 1
        bbox = regions[0]["bbox"]

        assert "x_min" in bbox
        assert "y_min" in bbox
        assert "x_max" in bbox
        assert "y_max" in bbox
        assert all(0.0 <= v <= 1.0 for v in bbox.values())

    def test_get_low_confidence_no_regions(self):
        """No regions when all words are high confidence."""
        from athena.models.ocr import ALTOPage, ALTOWord

        page = ALTOPage(
            page_number=1,
            width=1000,
            height=1000,
            words=[
                ALTOWord(content="High", x=0, y=0, width=10, height=10, confidence=0.95, page=1),
                ALTOWord(content="Quality", x=0, y=0, width=10, height=10, confidence=0.98, page=1),
            ],
        )

        parser = ALTOParser()
        regions = parser.get_low_confidence_regions(page)

        assert regions == []


class TestALTOParserConfidenceThreshold:
    """Tests for confidence threshold configuration."""

    def test_default_confidence_threshold(self):
        """Default confidence threshold is 0.7."""
        parser = ALTOParser()

        assert parser.confidence_threshold == 0.7

    def test_custom_confidence_threshold(self):
        """Custom confidence threshold can be set."""
        parser = ALTOParser(confidence_threshold=0.8)

        assert parser.confidence_threshold == 0.8
