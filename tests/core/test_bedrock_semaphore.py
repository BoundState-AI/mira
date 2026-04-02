"""
Tests for mira.core.bedrock_semaphore — Bedrock concurrency gate.

Covers:
  - Env-driven caps
  - Async limiter blocks above configured concurrency
  - Sync limiter blocks above configured concurrency
  - Peak in-flight concurrency measurement
  - Provider path uses the limiter (via import check)

BoundState AI 2026
Classification: BoundState Proprietary
"""

from __future__ import annotations

import asyncio
import os
import threading
import time
from types import SimpleNamespace

import pytest

from mira.core.bedrock_semaphore import (
    bedrock_limiter,
    bedrock_limiter_sync,
    get_async_limiter,
    get_sync_limiter,
    reset_limiters,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clean_limiters():
    """Reset limiters before and after every test."""
    reset_limiters()
    yield
    reset_limiters()
    # Clean env vars
    os.environ.pop("MIRA_BEDROCK_SONNET_CONCURRENCY", None)
    os.environ.pop("MIRA_BEDROCK_VISION_CONCURRENCY", None)


# ---------------------------------------------------------------------------
# Env-driven cap tests
# ---------------------------------------------------------------------------


class TestEnvDrivenCaps:
    def test_default_sonnet_cap(self):
        sem = get_sync_limiter("sonnet")
        # Default is 6 — acquire 6, 7th should block
        for _ in range(6):
            assert sem.acquire(blocking=False)
        assert not sem.acquire(blocking=False)
        for _ in range(6):
            sem.release()

    def test_default_vision_cap(self):
        sem = get_sync_limiter("vision")
        # Default is 4
        for _ in range(4):
            assert sem.acquire(blocking=False)
        assert not sem.acquire(blocking=False)
        for _ in range(4):
            sem.release()

    def test_env_override_sonnet(self):
        os.environ["MIRA_BEDROCK_SONNET_CONCURRENCY"] = "2"
        sem = get_sync_limiter("sonnet")
        assert sem.acquire(blocking=False)
        assert sem.acquire(blocking=False)
        assert not sem.acquire(blocking=False)
        sem.release()
        sem.release()

    def test_env_override_vision(self):
        os.environ["MIRA_BEDROCK_VISION_CONCURRENCY"] = "1"
        sem = get_sync_limiter("vision")
        assert sem.acquire(blocking=False)
        assert not sem.acquire(blocking=False)
        sem.release()

    def test_unknown_model_class_uses_sonnet_cap(self):
        os.environ["MIRA_BEDROCK_SONNET_CONCURRENCY"] = "3"
        sem = get_sync_limiter("haiku")
        for _ in range(3):
            assert sem.acquire(blocking=False)
        assert not sem.acquire(blocking=False)
        for _ in range(3):
            sem.release()

    def test_unknown_model_class_shares_sonnet_pool(self):
        assert get_sync_limiter("haiku") is get_sync_limiter("sonnet")


# ---------------------------------------------------------------------------
# Async limiter tests
# ---------------------------------------------------------------------------


class TestAsyncLimiter:
    @pytest.mark.asyncio
    async def test_async_limiter_blocks_above_cap(self):
        """Prove that the async limiter actually blocks concurrent tasks."""
        os.environ["MIRA_BEDROCK_SONNET_CONCURRENCY"] = "2"

        peak = 0
        current = 0
        lock = asyncio.Lock()

        async def fake_bedrock_call(delay: float = 0.05):
            nonlocal peak, current
            async with bedrock_limiter("sonnet"):
                async with lock:
                    current += 1
                    if current > peak:
                        peak = current
                await asyncio.sleep(delay)
                async with lock:
                    current -= 1

        # Launch 6 tasks with cap=2 — peak should never exceed 2
        tasks = [asyncio.create_task(fake_bedrock_call()) for _ in range(6)]
        await asyncio.gather(*tasks)

        assert peak == 2, f"Peak concurrency was {peak}, expected 2"

    @pytest.mark.asyncio
    async def test_async_vision_limiter_independent(self):
        """Sonnet and vision limiters are independent pools."""
        os.environ["MIRA_BEDROCK_SONNET_CONCURRENCY"] = "1"
        os.environ["MIRA_BEDROCK_VISION_CONCURRENCY"] = "1"

        order: list[str] = []

        async def sonnet_call():
            async with bedrock_limiter("sonnet"):
                order.append("sonnet_start")
                await asyncio.sleep(0.02)
                order.append("sonnet_end")

        async def vision_call():
            async with bedrock_limiter("vision"):
                order.append("vision_start")
                await asyncio.sleep(0.02)
                order.append("vision_end")

        # Both should run concurrently since they use different limiters
        await asyncio.gather(sonnet_call(), vision_call())

        # Both should have started before either ended
        sonnet_start_idx = order.index("sonnet_start")
        vision_start_idx = order.index("vision_start")
        sonnet_end_idx = order.index("sonnet_end")
        vision_end_idx = order.index("vision_end")
        assert sonnet_start_idx < sonnet_end_idx
        assert vision_start_idx < vision_end_idx
        # At least one pair should overlap (both started before either ended)
        first_end = min(sonnet_end_idx, vision_end_idx)
        assert sonnet_start_idx < first_end and vision_start_idx < first_end

    @pytest.mark.asyncio
    async def test_async_limiter_measures_peak_concurrency(self):
        """Comprehensive peak concurrency test with configurable cap."""
        cap = 3
        os.environ["MIRA_BEDROCK_SONNET_CONCURRENCY"] = str(cap)
        num_tasks = 12

        peak = 0
        current = 0
        lock = asyncio.Lock()

        async def fake_call():
            nonlocal peak, current
            async with bedrock_limiter("sonnet"):
                async with lock:
                    current += 1
                    if current > peak:
                        peak = current
                await asyncio.sleep(0.02)
                async with lock:
                    current -= 1

        tasks = [asyncio.create_task(fake_call()) for _ in range(num_tasks)]
        await asyncio.gather(*tasks)

        assert peak <= cap, f"Peak {peak} exceeded cap {cap}"
        assert peak == cap, f"Peak {peak} did not reach cap {cap} (all tasks should saturate)"

    @pytest.mark.asyncio
    async def test_sync_and_async_paths_share_one_cap(self):
        os.environ["MIRA_BEDROCK_SONNET_CONCURRENCY"] = "2"

        peak = 0
        current = 0
        lock = threading.Lock()

        def sync_call():
            nonlocal peak, current
            with bedrock_limiter_sync("sonnet"):
                with lock:
                    current += 1
                    peak = max(peak, current)
                time.sleep(0.05)
                with lock:
                    current -= 1

        async def async_call():
            nonlocal peak, current
            async with bedrock_limiter("sonnet"):
                with lock:
                    current += 1
                    peak = max(peak, current)
                await asyncio.sleep(0.05)
                with lock:
                    current -= 1

        threads = [threading.Thread(target=sync_call) for _ in range(2)]
        for thread in threads:
            thread.start()
        await asyncio.sleep(0.01)
        await async_call()
        for thread in threads:
            thread.join()

        assert peak == 2, f"Peak mixed concurrency was {peak}, expected 2"


# ---------------------------------------------------------------------------
# Sync limiter tests
# ---------------------------------------------------------------------------


class TestSyncLimiter:
    def test_sync_limiter_blocks_above_cap(self):
        """Prove sync limiter blocks threads above configured cap."""
        os.environ["MIRA_BEDROCK_SONNET_CONCURRENCY"] = "2"

        peak = 0
        current = 0
        lock = threading.Lock()

        def fake_bedrock_call():
            nonlocal peak, current
            with bedrock_limiter_sync("sonnet"):
                with lock:
                    current += 1
                    if current > peak:
                        peak = current
                time.sleep(0.03)
                with lock:
                    current -= 1

        threads = [threading.Thread(target=fake_bedrock_call) for _ in range(6)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert peak == 2, f"Peak concurrency was {peak}, expected 2"

    def test_sync_context_manager_releases_on_exception(self):
        """Ensure the semaphore is released even if the body raises."""
        os.environ["MIRA_BEDROCK_SONNET_CONCURRENCY"] = "1"

        with pytest.raises(ValueError):
            with bedrock_limiter_sync("sonnet"):
                raise ValueError("boom")

        # Should be able to acquire again — proof it was released
        sem = get_sync_limiter("sonnet")
        assert sem.acquire(blocking=False)
        sem.release()


# ---------------------------------------------------------------------------
# Integration: provider uses limiter
# ---------------------------------------------------------------------------


class TestProviderIntegration:
    def test_bedrock_converse_provider_imports_limiter(self):
        """Verify BedrockConverseProvider.complete references bedrock_limiter_sync."""
        import inspect
        from mira.providers.llm_provider import BedrockConverseProvider

        source = inspect.getsource(BedrockConverseProvider.complete)
        assert "bedrock_limiter_sync" in source

    def test_anthropic_provider_does_not_use_bedrock_limiter(self):
        """Commercial Anthropic traffic should not be gated by Bedrock quotas."""
        import inspect
        from mira.providers.llm_provider import AnthropicProvider

        source = inspect.getsource(AnthropicProvider.complete)
        assert "bedrock_limiter_sync" not in source

    def test_oca_vision_uses_limiter(self):
        """Verify OCA system vision only uses the limiter on Bedrock-backed traffic."""
        import inspect
        from mira.oca.system_vision import OCASystemVisionService

        source = inspect.getsource(OCASystemVisionService.build_mockup)
        assert "bedrock_limiter_sync" in source
        assert "self._use_bedrock" in source

    def test_maptis_pdf_extractor_uses_limiter(self):
        """Verify MAPTIS PDF extractor gates Bedrock vision calls."""
        import inspect
        from mira.maptis.pdf_extractor import MAPTISPDFExtractor

        source = inspect.getsource(MAPTISPDFExtractor._extract_via_vision)
        assert "bedrock_limiter_sync" in source
        assert "self.use_bedrock" in source

    def test_mua_synthesizer_uses_limiter(self):
        """Verify MUA synthesis invoke_model is gated."""
        import inspect
        from mira.mua.synthesis import synthesizer

        source = inspect.getsource(synthesizer._invoke_bedrock)
        assert "bedrock_limiter_sync" in source

    def test_precedent_engine_bedrock_util_uses_limiter(self):
        """Verify precedent engine Bedrock utility is gated."""
        import inspect
        from mira.precedent_engine.utils.bedrock import create_bedrock_llm_call

        source = inspect.getsource(create_bedrock_llm_call)
        assert "bedrock_limiter_sync" in source

    def test_precedent_narrator_uses_limiter(self):
        """Verify precedent narrator invoke_model is gated."""
        import inspect
        from mira.precedent_engine.core.narrator import NarratorLLM

        source = inspect.getsource(NarratorLLM._generate_rationale_sync)
        assert "bedrock_limiter_sync" in source

    def test_athena_bedrock_provider_uses_limiter(self):
        """Verify ATHENA Bedrock provider uses the async limiter path."""
        import inspect
        from athena.providers.bedrock import BedrockProvider

        vision_source = inspect.getsource(BedrockProvider.complete_vision)
        assert "bedrock_limiter" in vision_source
        assert '"vision"' in vision_source

        text_source = inspect.getsource(BedrockProvider.complete_text)
        assert "bedrock_limiter" in text_source
        assert '"sonnet"' in text_source

    def test_athena_anthropic_provider_not_gated(self):
        """ATHENA commercial Anthropic provider should NOT be Bedrock-gated."""
        import inspect
        from athena.providers.bedrock import AnthropicProvider

        vision_source = inspect.getsource(AnthropicProvider.complete_vision)
        assert "bedrock_limiter" not in vision_source

        text_source = inspect.getsource(AnthropicProvider.complete_text)
        assert "bedrock_limiter" not in text_source

    @pytest.mark.asyncio
    async def test_athena_bedrock_provider_complete_text_obeys_async_cap(self):
        """ATHENA async call path should honor the shared limiter without blocking the loop."""
        from athena.providers.bedrock import BedrockProvider

        os.environ["MIRA_BEDROCK_SONNET_CONCURRENCY"] = "1"

        peak = 0
        current = 0
        lock = threading.Lock()

        class _FakeMessages:
            def create(self, **_: object):
                nonlocal peak, current
                with lock:
                    current += 1
                    peak = max(peak, current)
                time.sleep(0.05)
                with lock:
                    current -= 1
                return SimpleNamespace(
                    content=[SimpleNamespace(text="ok")],
                    usage=SimpleNamespace(input_tokens=10, output_tokens=5),
                )

        provider = BedrockProvider.__new__(BedrockProvider)
        provider.client = SimpleNamespace(messages=_FakeMessages())
        provider.region = "us-gov-west-1"
        provider.models = {
            "triage": "us-gov.anthropic.claude-3-5-haiku-20241022-v1:0",
            "extract": "us-gov.anthropic.claude-sonnet-4-5-20250929-v1:0",
        }

        first, second = await asyncio.gather(
            provider.complete_text("sys", "one"),
            provider.complete_text("sys", "two"),
        )

        assert first.content == "ok"
        assert second.content == "ok"
        assert peak == 1, f"Peak ATHENA Bedrock concurrency was {peak}, expected 1"
