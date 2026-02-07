#!/usr/bin/env python3
"""
Tests for Pipeline Router — Enforces RULES.md §3.

These tests are THE authority on routing behavior.
If a test fails, the code is wrong, not the test.

BoundState AI 2026

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI
"""

import pytest
from mira.pipeline.context import QueryContext, QueryIntent
from mira.pipeline.router import RouteStage, _has_compatibility_signal


# ══════════════════════════════════════════════════════════════════════
# Rule 3.2: Binary compatibility signal detection
# ══════════════════════════════════════════════════════════════════════

class TestCompatibilitySignals:
    """ANY single match = compatibility. No exceptions."""

    @pytest.mark.parametrize("query", [
        "Is aluminum 6061 compatible with oxygen at 200 psi?",
        "Can I use PTFE in GOX service?",
        "Stainless steel 316 for LOX at 3000 psia",
        "Is viton suitable for O2 service?",
        "fluorosilicone in hydrogen environment",
        "material rated for GH2",
        "safe for LH2 service at 500 psi",
        "aluminum 6061 at 3000 psi",
        "Can we use inconel 718 for O₂?",
        "H2 compatibility of monel 400",
    ])
    def test_compatibility_signals_detected(self, query):
        assert _has_compatibility_signal(query), f"Should detect compatibility: {query}"

    @pytest.mark.parametrize("query", [
        "show me all fluorosilicone materials",
        "list aluminum alloys",
        "find NASA-STD-6016C",
        "what is MIRA?",
        "hello",
        "compare the properties of inconel vs hastelloy",
    ])
    def test_no_false_compatibility_signals(self, query):
        assert not _has_compatibility_signal(query), f"Should NOT detect compatibility: {query}"


# ══════════════════════════════════════════════════════════════════════
# Rule 3.3: When in doubt, route to compatibility (for gas service)
# Rule 3.4: Scoring thresholds
# ══════════════════════════════════════════════════════════════════════

class TestRouteStage:
    """Full routing logic tests."""

    def _make_ctx(self, query: str, **intent_scores) -> QueryContext:
        ctx = QueryContext(raw_query=query)
        ctx.intent_scores = intent_scores
        return ctx

    def test_binary_signal_overrides_classifier(self):
        """Rule 3.2: Binary signal wins even if classifier says materials_search."""
        ctx = self._make_ctx(
            "show me fluorosilicone materials compatible with oxygen",
            materials_query=0.8,
            compatibility_query=0.2,
        )
        router = RouteStage()
        ctx = router.execute(ctx)
        assert ctx.pipeline_name == "compatibility"

    def test_materials_search_only_when_compat_zero(self):
        """Rule 3.4: materials_search only wins when compatibility score == 0."""
        ctx = self._make_ctx(
            "show me all titanium alloys",
            materials_query=0.6,
            compatibility_query=0.0,
        )
        router = RouteStage()
        ctx = router.execute(ctx)
        assert ctx.pipeline_name == "materials_search"

    def test_materials_search_loses_to_any_compat_score(self):
        """Even tiny compatibility score blocks materials_search."""
        ctx = self._make_ctx(
            "show me titanium alloys",
            materials_query=0.8,
            compatibility_query=0.1,
        )
        router = RouteStage()
        ctx = router.execute(ctx)
        # Binary signal check catches "titanium" — nope, titanium alone isn't
        # a gas service keyword. So this falls to classifier scores.
        # compat_score > 0 → compatibility
        assert ctx.pipeline_name == "compatibility"

    def test_document_lookup_routing(self):
        ctx = self._make_ctx(
            "find NASA-STD-6016C section 4.2",
            document_lookup=0.6,
        )
        router = RouteStage()
        ctx = router.execute(ctx)
        assert ctx.pipeline_name == "document_lookup"

    def test_general_fallback(self):
        ctx = self._make_ctx("what is MIRA?")
        router = RouteStage()
        ctx = router.execute(ctx)
        assert ctx.pipeline_name == "general"

    def test_comparison_routes_to_compatibility(self):
        """Comparisons need full evidence pipeline."""
        ctx = self._make_ctx(
            "compare 316 vs 304",
            comparison=0.6,
        )
        router = RouteStage()
        ctx = router.execute(ctx)
        assert ctx.pipeline_name == "compatibility"


# ══════════════════════════════════════════════════════════════════════
# Rule 3.2: Gas service keyword exhaustive coverage
# ══════════════════════════════════════════════════════════════════════

class TestGasServiceKeywords:
    """Every gas service keyword must trigger compatibility."""

    @pytest.mark.parametrize("keyword", [
        "oxygen", "O2", "GOX", "LOX",
        "hydrogen", "H2", "GH2", "LH2",
        "O₂", "H₂",
    ])
    def test_gas_keyword_triggers_compatibility(self, keyword):
        query = f"material for {keyword}"
        assert _has_compatibility_signal(query)

    @pytest.mark.parametrize("phrase", [
        "compatible with", "compatibility of",
        "approved for", "rated for", "safe for",
        "at 3000 psi", "at 200 psia", "at 100 bar",
        "Can I use", "Can we use",
        "is suitable", "is acceptable", "is allowed",
    ])
    def test_compat_phrase_triggers(self, phrase):
        query = f"aluminum {phrase} something"
        assert _has_compatibility_signal(query)
