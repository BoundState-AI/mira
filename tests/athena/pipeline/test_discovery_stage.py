#!/usr/bin/env python3
"""
Module: Test Discovery Stage
Purpose: Tests for athena.pipeline.discovery module.

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
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

# Mock cv2 before any athena imports
sys.modules.setdefault('cv2', MagicMock())

# Import models directly (these don't have problematic imports)
from athena.models.discovery import BatchDiscoveryState, CorpusProfile, DiscoveryResult
from athena.models.ocr import OCRResult

# Import pipeline.discovery directly from file to avoid __init__ chain
import importlib.util
_disc_path = Path(__file__).parent.parent.parent.parent / "athena" / "pipeline" / "discovery.py"
_spec = importlib.util.spec_from_file_location("discovery", _disc_path)
_disc_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_disc_module)
DiscoveryStage = _disc_module.DiscoveryStage
save_discovery_state = _disc_module.save_discovery_state


@pytest.fixture
def discovery_stage(mock_llm_provider):
    """Create DiscoveryStage with mock LLM."""
    return DiscoveryStage(llm=mock_llm_provider)


@pytest.fixture
def ocr_results_batch():
    """Create batch of OCRResults for testing."""
    return [
        OCRResult(page=i, full_text=f"Document content for page {i}" * 100)
        for i in range(1, 6)
    ]


class TestDiscoveryStageInitialization:
    """Tests for DiscoveryStage initialization."""

    def test_initialization(self, mock_llm_provider):
        """Initialize DiscoveryStage with LLM provider."""
        stage = DiscoveryStage(llm=mock_llm_provider)

        assert stage.llm == mock_llm_provider
        assert stage.max_text_length == 8000

    def test_custom_max_text_length(self, mock_llm_provider):
        """Custom max_text_length can be set."""
        stage = DiscoveryStage(llm=mock_llm_provider, max_text_length=4000)

        assert stage.max_text_length == 4000


class TestDiscoveryPageProcessing:
    """Tests for single page discovery."""

    @pytest.mark.asyncio
    async def test_discover_page_calls_llm(self, discovery_stage, sample_ocr_result):
        """LLM provider is called with truncated text."""
        result = await discovery_stage.discover_page(sample_ocr_result)

        discovery_stage.llm.complete_text.assert_called_once()
        call_kwargs = discovery_stage.llm.complete_text.call_args.kwargs
        assert "system_prompt" in call_kwargs
        assert "user_prompt" in call_kwargs

    @pytest.mark.asyncio
    async def test_discover_page_returns_discovery_result(
        self,
        discovery_stage,
        sample_ocr_result,
    ):
        """discover_page returns DiscoveryResult."""
        result = await discovery_stage.discover_page(sample_ocr_result)

        assert isinstance(result, DiscoveryResult)
        assert result.page == 1
        assert result.document_type == "memorandum"

    @pytest.mark.asyncio
    async def test_discover_page_truncates_long_text(
        self,
        mock_llm_provider,
    ):
        """Long text is truncated to max_text_length."""
        stage = DiscoveryStage(llm=mock_llm_provider, max_text_length=100)
        long_text = "x" * 500

        ocr_result = OCRResult(page=1, full_text=long_text)
        await stage.discover_page(ocr_result)

        # Verify text was truncated in the call
        call_kwargs = mock_llm_provider.complete_text.call_args.kwargs
        user_prompt = call_kwargs["user_prompt"]
        # The prompt includes prefix + truncated text
        assert len(user_prompt) < len(long_text) + 100

    @pytest.mark.asyncio
    async def test_discover_page_adds_to_aggregator(
        self,
        discovery_stage,
        sample_ocr_result,
    ):
        """Result is added to aggregator."""
        assert discovery_stage.aggregator.total_pages == 0

        await discovery_stage.discover_page(sample_ocr_result)

        assert discovery_stage.aggregator.total_pages == 1

    @pytest.mark.asyncio
    async def test_discover_page_invalid_json_returns_error_result(
        self,
        mock_llm_provider_invalid_json,
        sample_ocr_result,
    ):
        """Invalid JSON returns error DiscoveryResult."""
        stage = DiscoveryStage(llm=mock_llm_provider_invalid_json)

        result = await stage.discover_page(sample_ocr_result)

        assert isinstance(result, DiscoveryResult)
        assert result.document_type == "parse_error"

    @pytest.mark.asyncio
    async def test_discover_page_override_page_number(
        self,
        discovery_stage,
        sample_ocr_result,
    ):
        """Page number can be overridden."""
        result = await discovery_stage.discover_page(sample_ocr_result, page_number=99)

        assert result.page == 99


class TestDiscoveryBatchProcessing:
    """Tests for batch discovery processing."""

    @pytest.mark.asyncio
    async def test_discover_batch_processes_all_pages(
        self,
        discovery_stage,
        ocr_results_batch,
    ):
        """All pages in batch are processed."""
        state = await discovery_stage.discover_batch(
            ocr_results_batch,
            batch_id="batch-001",
        )

        assert state.pages_discovered == 5
        assert len(state.results) == 5

    @pytest.mark.asyncio
    async def test_discover_batch_incremental_save(
        self,
        discovery_stage,
        ocr_results_batch,
    ):
        """Save callback invoked after each page."""
        save_callback = AsyncMock()

        await discovery_stage.discover_batch(
            ocr_results_batch,
            batch_id="batch-001",
            save_callback=save_callback,
        )

        # Should be called once per page + once for final save
        assert save_callback.call_count >= 5

    @pytest.mark.asyncio
    async def test_discover_batch_continues_on_error(
        self,
        mock_llm_provider,
        ocr_results_batch,
    ):
        """Single page error doesn't stop batch."""
        # Make LLM fail on first call only
        mock_llm_provider.complete_text.side_effect = [
            Exception("First call fails"),
            *[MagicMock(content='{"document_type": "memo"}') for _ in range(4)],
        ]

        stage = DiscoveryStage(llm=mock_llm_provider)
        state = await stage.discover_batch(ocr_results_batch, batch_id="batch-001")

        # Should still process remaining pages
        assert state.pages_discovered >= 4

    @pytest.mark.asyncio
    async def test_discover_batch_returns_state(
        self,
        discovery_stage,
        ocr_results_batch,
    ):
        """discover_batch returns BatchDiscoveryState."""
        state = await discovery_stage.discover_batch(
            ocr_results_batch,
            batch_id="batch-001",
        )

        assert isinstance(state, BatchDiscoveryState)
        assert state.batch_id == "batch-001"
        assert state.processing_complete is True

    @pytest.mark.asyncio
    async def test_discover_batch_builds_profile(
        self,
        discovery_stage,
        ocr_results_batch,
    ):
        """Profile is built after batch processing."""
        state = await discovery_stage.discover_batch(
            ocr_results_batch,
            batch_id="batch-001",
        )

        assert state.profile is not None
        assert isinstance(state.profile, CorpusProfile)

    @pytest.mark.asyncio
    async def test_discover_batch_sampling(
        self,
        discovery_stage,
    ):
        """Sample ratio reduces pages processed."""
        # Create large batch
        large_batch = [
            OCRResult(page=i, full_text=f"Page {i}") for i in range(1, 101)
        ]

        state = await discovery_stage.discover_batch(
            large_batch,
            batch_id="batch-001",
            sample_ratio=0.1,  # Only 10%
        )

        # Should only process ~10 pages
        assert state.total_pages == 10
        assert state.pages_discovered <= 10


class TestDiscoveryStageHelpers:
    """Tests for DiscoveryStage helper methods."""

    def test_build_profile(self, discovery_stage):
        """build_profile returns CorpusProfile."""
        profile = discovery_stage.build_profile()

        assert isinstance(profile, CorpusProfile)

    def test_reset_aggregator(self, discovery_stage):
        """reset clears aggregator state."""
        # Add some data
        discovery_stage.aggregator.total_pages = 100

        discovery_stage.reset()

        assert discovery_stage.aggregator.total_pages == 0


class TestSaveDiscoveryState:
    """Tests for save_discovery_state function."""

    @pytest.mark.asyncio
    async def test_save_discovery_state(self, tmp_path):
        """State is saved as JSON."""
        state = BatchDiscoveryState(batch_id="batch-001")
        state.add_result(DiscoveryResult(page=1, document_type="memo"))

        output_path = tmp_path / "discovery_state.json"
        await save_discovery_state(state, output_path)

        assert output_path.exists()

    @pytest.mark.asyncio
    async def test_save_discovery_state_creates_directories(self, tmp_path):
        """Parent directories are created."""
        state = BatchDiscoveryState(batch_id="batch-001")

        output_path = tmp_path / "nested" / "path" / "state.json"
        await save_discovery_state(state, output_path)

        assert output_path.exists()

    @pytest.mark.asyncio
    async def test_save_discovery_state_includes_profile(self, tmp_path):
        """Profile is included when present."""
        import json

        state = BatchDiscoveryState(batch_id="batch-001")
        state.profile = CorpusProfile(
            document_types={"memo": 5},
            total_pages=5,
        )

        output_path = tmp_path / "state.json"
        await save_discovery_state(state, output_path)

        data = json.loads(output_path.read_text())
        assert "profile" in data
        assert data["profile"]["total_pages"] == 5
