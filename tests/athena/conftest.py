#!/usr/bin/env python3
"""
Module: Conftest
Purpose: Shared pytest fixtures for ATHENA V2 tests.

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

from dataclasses import dataclass
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest


# =============================================================================
# ALTO XML Fixtures
# =============================================================================

@pytest.fixture
def sample_alto_xml_v3():
    """Minimal valid ALTO v3 XML with namespace."""
    return '''<?xml version="1.0" encoding="UTF-8"?>
<alto xmlns="http://www.loc.gov/standards/alto/ns-v3#">
  <Layout>
    <Page WIDTH="2480" HEIGHT="3508" PHYSICAL_IMG_NR="1">
      <PrintSpace>
        <TextBlock>
          <TextLine>
            <String CONTENT="Hello" WC="0.95" HPOS="100" VPOS="200" WIDTH="50" HEIGHT="20"/>
            <String CONTENT="World" WC="0.88" HPOS="160" VPOS="200" WIDTH="55" HEIGHT="20"/>
          </TextLine>
          <TextLine>
            <String CONTENT="Test" WC="0.65" HPOS="100" VPOS="250" WIDTH="40" HEIGHT="20"/>
          </TextLine>
        </TextBlock>
      </PrintSpace>
    </Page>
  </Layout>
</alto>'''


@pytest.fixture
def sample_alto_xml_v2():
    """Minimal valid ALTO v2 XML."""
    return '''<?xml version="1.0" encoding="UTF-8"?>
<alto xmlns="http://www.loc.gov/standards/alto/ns-v2#">
  <Layout>
    <Page WIDTH="2480" HEIGHT="3508">
      <PrintSpace>
        <TextBlock>
          <TextLine>
            <String CONTENT="Document" WC="0.92" HPOS="50" VPOS="100" WIDTH="80" HEIGHT="25"/>
          </TextLine>
        </TextBlock>
      </PrintSpace>
    </Page>
  </Layout>
</alto>'''


@pytest.fixture
def sample_alto_xml_no_namespace():
    """ALTO XML without namespace (some legacy ABBYY output)."""
    return '''<?xml version="1.0" encoding="UTF-8"?>
<alto>
  <Layout>
    <Page WIDTH="1200" HEIGHT="1600">
      <PrintSpace>
        <TextBlock>
          <TextLine>
            <String CONTENT="Legacy" WC="0.75" HPOS="10" VPOS="20" WIDTH="60" HEIGHT="15"/>
          </TextLine>
        </TextBlock>
      </PrintSpace>
    </Page>
  </Layout>
</alto>'''


@pytest.fixture
def sample_alto_xml_multipage():
    """Multi-page ALTO XML for batch testing."""
    return '''<?xml version="1.0" encoding="UTF-8"?>
<alto xmlns="http://www.loc.gov/standards/alto/ns-v3#">
  <Layout>
    <Page WIDTH="2480" HEIGHT="3508" PHYSICAL_IMG_NR="1">
      <PrintSpace>
        <TextBlock>
          <TextLine>
            <String CONTENT="Page" WC="0.99" HPOS="100" VPOS="100" WIDTH="40" HEIGHT="20"/>
            <String CONTENT="One" WC="0.97" HPOS="150" VPOS="100" WIDTH="30" HEIGHT="20"/>
          </TextLine>
        </TextBlock>
      </PrintSpace>
    </Page>
    <Page WIDTH="2480" HEIGHT="3508" PHYSICAL_IMG_NR="2">
      <PrintSpace>
        <TextBlock>
          <TextLine>
            <String CONTENT="Page" WC="0.98" HPOS="100" VPOS="100" WIDTH="40" HEIGHT="20"/>
            <String CONTENT="Two" WC="0.96" HPOS="150" VPOS="100" WIDTH="30" HEIGHT="20"/>
          </TextLine>
        </TextBlock>
      </PrintSpace>
    </Page>
  </Layout>
</alto>'''


# =============================================================================
# OCR Result Fixtures
# =============================================================================

@pytest.fixture
def sample_alto_word():
    """Sample ALTOWord for testing."""
    from athena.models.ocr import ALTOWord
    return ALTOWord(
        content="Test",
        x=100,
        y=200,
        width=50,
        height=20,
        confidence=0.95,
        page=1,
    )


@pytest.fixture
def sample_alto_page():
    """Sample ALTOPage with multiple words."""
    from athena.models.ocr import ALTOPage, ALTOWord
    return ALTOPage(
        page_number=1,
        width=2480,
        height=3508,
        words=[
            ALTOWord(content="Hello", x=100, y=200, width=50, height=20, confidence=0.95, page=1),
            ALTOWord(content="World", x=160, y=200, width=55, height=20, confidence=0.88, page=1),
            ALTOWord(content="Low", x=100, y=250, width=30, height=20, confidence=0.60, page=1),
        ],
    )


@pytest.fixture
def sample_ocr_result():
    """Sample OCRResult for pipeline testing."""
    from athena.models.ocr import OCRResult
    from athena.models.enums import OCRSource
    return OCRResult(
        page=1,
        ocr_source=OCRSource.ABBYY,
        full_text="Hello World Low",
        word_count=3,
        average_confidence=0.81,
        needs_vision_review=False,
        page_width=2480,
        page_height=3508,
    )


@pytest.fixture
def sample_ocr_result_vision_needed():
    """OCRResult that needs vision review."""
    from athena.models.ocr import OCRResult
    from athena.models.enums import OCRSource, VisionTrigger
    return OCRResult(
        page=2,
        ocr_source=OCRSource.ABBYY,
        full_text="Illegible text here",
        word_count=3,
        average_confidence=0.45,
        needs_vision_review=True,
        vision_triggers=[VisionTrigger.LOW_OCR_CONFIDENCE],
        page_width=2480,
        page_height=3508,
    )


# =============================================================================
# Discovery Fixtures
# =============================================================================

@pytest.fixture
def sample_discovery_result():
    """Sample DiscoveryResult."""
    from athena.models.discovery import DiscoveryResult
    return DiscoveryResult(
        page=1,
        document_type="memorandum",
        era_estimate="1980s",
        entities_found={
            "equipment": ["Apollo CSM", "LM-5"],
            "people": ["J. Smith"],
            "dates": ["1980-03-15"],
        },
        vocabulary_notes=["CSM", "LM", "EVA"],
        form_number="NASA-1234",
        condition_notes=["typed", "clear"],
        content_summary="Test memo regarding equipment.",
    )


# =============================================================================
# Mock LLM Provider
# =============================================================================

@pytest.fixture
def mock_llm_provider():
    """Mock LLMProvider for discovery/pipeline testing."""
    provider = MagicMock()

    # Mock response object
    mock_response = MagicMock()
    mock_response.content = '''{
        "document_type": "memorandum",
        "era_estimate": "1980s",
        "entities_found": {
            "equipment": ["Test Equipment"],
            "people": ["J. Smith"],
            "dates": ["1980-01-01"]
        },
        "vocabulary_notes": ["technical", "memo"],
        "form_number": null,
        "condition_notes": ["typed"],
        "content_summary": "Test document"
    }'''

    provider.complete_text = AsyncMock(return_value=mock_response)
    return provider


@pytest.fixture
def mock_llm_provider_invalid_json():
    """Mock LLMProvider that returns invalid JSON."""
    provider = MagicMock()
    mock_response = MagicMock()
    mock_response.content = "This is not valid JSON"
    provider.complete_text = AsyncMock(return_value=mock_response)
    return provider


# =============================================================================
# Separator Fixtures
# =============================================================================

@pytest.fixture
def sample_separator_result():
    """Sample SeparatorResult."""
    from athena.models.separator import SeparatorResult
    return SeparatorResult(
        separator_id="test-uuid-12345",
        confidence=1.0,
        folder_name="Engineering Records 1980",
        date_range_start="1980-01-01",
        date_range_end="1980-12-31",
        doc_count_expected=50,
        notes="Test folder",
        scanned_by="J. Doe",
        scan_date="2025-01-15",
    )


@pytest.fixture
def sample_folder_segment(sample_separator_result):
    """Sample FolderSegment."""
    from athena.models.separator import FolderSegment
    return FolderSegment(
        batch_id="batch-001",
        separator=sample_separator_result,
        page_range=(1, 50),
        page_count=50,
    )


# =============================================================================
# Test Enum for Parsing Tests
# =============================================================================

@pytest.fixture
def test_enum():
    """Sample enum for parsing tests."""
    from enum import Enum

    class TestStatus(Enum):
        PENDING = "pending"
        ACTIVE = "active"
        COMPLETED = "completed"

    return TestStatus
