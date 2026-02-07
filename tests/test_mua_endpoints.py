#!/usr/bin/env python3
"""
Module: Test Mua Endpoints
Purpose: Integration tests for all MUA endpoints.

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

import pytest
import sys
sys.path.insert(0, r'C:\BoundState')


class TestCorpusDraftEndpoints:
    """Test the new Corpus Draft endpoints (Corpus tab)."""

    def test_corpus_search(self):
        """Test /mua/v6/corpus/search endpoint."""
        from mira.mua.v6.index_builder import V6IndexBuilder

        builder = V6IndexBuilder()
        builder.load()

        results = builder.search("6061 aluminum flammability", top_k=5)
        assert len(results) > 0
        record, score = results[0]
        assert record.mua_number is not None
        assert score > 0
        print(f"  Found {len(results)} precedents, top: {record.mua_number} ({score:.3f})")

    def test_corpus_draft_generation(self):
        """Test /mua/v6/corpus/draft endpoint."""
        from mira.mua.v6.index_builder import V6IndexBuilder
        from mira.mua.v6.draft_generator import generate_mua_draft

        builder = V6IndexBuilder()
        builder.load()

        results = builder.search("Inconel 718 oxygen flammability", top_k=15)
        draft = generate_mua_draft(
            material="Inconel 718",
            environment="Enriched Oxygen (30%)",
            application="Structural component",
            precedents=results,
            o2_percent=30.0,
            pressure_psia=14.7,
        )

        assert draft.recommended_determination in ["APPROVED", "CONDITIONAL", "REQUIRES_REVIEW"]
        assert draft.confidence >= 0
        assert len(draft.precedents_cited) > 0
        print(f"  Determination: {draft.recommended_determination} ({draft.confidence:.1%})")


class TestV6PipelineEndpoints:
    """Test V6 Pipeline endpoints (V6 Pipeline tab)."""

    def test_enriched_search(self):
        """Test /mua/v6/precedents/search endpoint."""
        from mira.mua.v6 import search_enriched_precedents

        results = search_enriched_precedents(
            material="316 Stainless Steel",
            environment="vacuum",
            k=10,
        )

        assert results.supporting_count >= 0
        print(f"  Supporting: {results.supporting_count}, Conflicting: {results.conflicting_count}")

    def test_material_resolution(self):
        """Test material identity resolution."""
        from mira.mua.v6 import resolve_material_identity

        identity = resolve_material_identity("316L Stainless Steel")
        print(f"  Resolved: {identity.is_resolved}, Code: {identity.material_code}")


class TestBOKEngine:
    """Test BOK Engine (Precedent Engine, Interactive, AI Synthesis tabs)."""

    def test_bok_index_loads(self):
        """Test MUA BOK v2 index loads correctly."""
        from mira.miul.mua_bok_engine import MUABOKEngine

        engine = MUABOKEngine()
        assert engine.index is not None, "BOK index should load"
        assert len(engine.metadata) > 0, "BOK metadata should have records"
        print(f"  BOK has {len(engine.metadata)} MUA records")

    def test_bok_search(self):
        """Test BOK search functionality."""
        from mira.miul.mua_bok_engine import MUABOKEngine

        engine = MUABOKEngine()
        precedents = engine.search_precedents(
            material="Viton",
            environment="oxygen",
            gaps={"FLAM": "C"},
            k=5,
        )

        assert len(precedents) > 0, "Should find precedents for Viton"
        print(f"  Found {len(precedents)} precedents for Viton in oxygen")


class TestMUAFAISSSearch:
    """Test MUA FAISS Search (Interactive tab)."""

    def test_faiss_search_loads(self):
        """Test FAISS search index loads."""
        from mira.miul.mua_faiss_search import MUAFAISSSearch

        search = MUAFAISSSearch()
        assert search.index is not None, "FAISS index should load"
        assert len(search.metadata) > 0, "Should have metadata"
        print(f"  FAISS index has {len(search.metadata)} records")

    def test_faiss_search(self):
        """Test FAISS search functionality."""
        from mira.miul.mua_faiss_search import MUAFAISSSearch

        search = MUAFAISSSearch()
        results = search.search(
            material="Teflon PTFE",
            environment="oxygen",
            k=5,
        )

        assert len(results) > 0, "Should find results for Teflon"
        print(f"  Found {len(results)} results for Teflon in oxygen")


class TestMUASynthesizer:
    """Test MUA Synthesizer (AI Synthesis tab)."""

    def test_synthesizer_init(self):
        """Test synthesizer initialization (requires API key)."""
        import os
        if not os.environ.get("ANTHROPIC_API_KEY"):
            pytest.skip("ANTHROPIC_API_KEY not set")

        from mira.miul.mua_synthesizer import MUASynthesizer
        synth = MUASynthesizer()
        assert synth is not None


class TestBatchMUA:
    """Test Batch MUA generation (Batch tab)."""

    def test_batch_mua_generation(self):
        """Test batch MUA generation with real MIUL file."""
        import pandas as pd
        from pathlib import Path
        from mira.mua.service import generate_mua
        from mira.mua.api_models import (
            EnvironmentSpec,
            MaterialRating,
            MuaGenerationRequest,
        )

        # Check for test file
        test_file = Path(r"C:\Users\jwilde2\Desktop\DMLLV\MIUL_enriched (21).xlsx")
        if not test_file.exists():
            pytest.skip("Test MIUL file not found")

        df = pd.read_excel(test_file, sheet_name="MIUL")

        # Rating column mapping (API test_class -> column name variants)
        rating_column_variants = [
            ("FLAMM", ["FLAM", "FLAMM", "FLAMM Rating"]),
            ("CORR", ["CORR", "CORR Rating"]),
            ("SCC", ["SCC", "SCC Rating"]),
            ("TVS", ["TVS", "TVS Rating"]),
            ("TOX", ["TOX", "TOX Rating"]),
            ("FS", ["FS", "FS Rating"]),
        ]

        rating_column_map = {}
        for api_test_class, variants in rating_column_variants:
            for v in variants:
                if v in df.columns:
                    rating_column_map[api_test_class] = v
                    break

        # Process first material with gaps
        for idx, row in df.iterrows():
            material_code = row.get("Material Code")
            if pd.isna(material_code):
                continue

            known_ratings = []
            has_gap = False

            for test_class, col_name in rating_column_map.items():
                if col_name in row and pd.notna(row[col_name]):
                    rating = str(row[col_name]).strip().upper()
                    if rating and rating not in ("", "N/A"):
                        known_ratings.append(MaterialRating(test_class=test_class, rating=rating))
                        if rating != "A":
                            has_gap = True

            if not has_gap:
                continue

            # Generate MUA for this material
            request = MuaGenerationRequest(
                material_key=str(int(material_code)),
                material_name=str(row.get("Designation", "")),
                program="TEST",
                hardware_name="",
                environment=EnvironmentSpec(),
                known_ratings=known_ratings,
            )

            response = generate_mua(request)
            assert response.success, f"MUA generation failed for {row.get('Designation')}"
            assert response.category in ["I", "II", "III"]
            print(f"  Generated MUA for {row.get('Designation')}: Category {response.category}")
            break  # Only test one


def run_all_tests():
    """Run all tests and report results."""
    import traceback

    test_classes = [
        TestCorpusDraftEndpoints,
        TestV6PipelineEndpoints,
        TestBOKEngine,
        TestMUAFAISSSearch,
        TestMUASynthesizer,
        TestBatchMUA,
    ]

    results = {"passed": 0, "failed": 0, "skipped": 0}

    for test_class in test_classes:
        print(f"\n{'='*60}")
        print(f"Testing: {test_class.__name__}")
        print('='*60)

        instance = test_class()
        for method_name in dir(instance):
            if method_name.startswith("test_"):
                print(f"\n  {method_name}...")
                try:
                    method = getattr(instance, method_name)
                    method()
                    print(f"    PASSED")
                    results["passed"] += 1
                except pytest.skip.Exception as e:
                    print(f"    SKIPPED: {e}")
                    results["skipped"] += 1
                except Exception as e:
                    print(f"    FAILED: {e}")
                    traceback.print_exc()
                    results["failed"] += 1

    print(f"\n{'='*60}")
    print("SUMMARY")
    print('='*60)
    print(f"Passed:  {results['passed']}")
    print(f"Failed:  {results['failed']}")
    print(f"Skipped: {results['skipped']}")

    return results["failed"] == 0


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
