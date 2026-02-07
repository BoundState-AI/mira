#!/usr/bin/env python3
"""
Test O2 Knowledge Twin Determinism

This test verifies that the O2 engine returns identical results
for identical queries, which is critical for safety-critical systems.

BoundState AI 2025
Compliance: NASA SWE-033 (Requirements Traceability)
"""

import pytest
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))


class TestO2Determinism:
    """Test suite for O2 engine determinism."""

    def test_evaluate_determinism(self):
        """Test that evaluate_o2_compatibility returns identical results for same input."""
        from mira.o2.models import O2CompatibilityRequest, OxygenPhase
        from mira.o2.engine import evaluate_o2_compatibility

        # Test case: Aluminum in GOX at 700 psia
        request = O2CompatibilityRequest(
            question="Is AL 6061 compatible with oxygen at 30% and 700 psi?",
            material_key="AL 6061",
            pressure_psia=700.0,
            temperature_k=294.26,  # ~70°F
            phase=OxygenPhase.GAS,
        )

        # Run evaluation multiple times
        results = []
        for i in range(5):
            result = evaluate_o2_compatibility(request)
            results.append({
                'classification': result.classification.value,
                'rationale': result.rationale,
                'evidence_count': len(result.evidence),
                'notes': result.notes,
            })

        # All results should be identical
        first_result = results[0]
        for i, result in enumerate(results[1:], start=2):
            assert result['classification'] == first_result['classification'], \
                f"Classification mismatch on run {i}: {result['classification']} != {first_result['classification']}"
            assert result['rationale'] == first_result['rationale'], \
                f"Rationale mismatch on run {i}"
            assert result['evidence_count'] == first_result['evidence_count'], \
                f"Evidence count mismatch on run {i}: {result['evidence_count']} != {first_result['evidence_count']}"

        print(f"[PASS] evaluate_o2_compatibility determinism verified (5 identical runs)")
        print(f"  Classification: {first_result['classification']}")

    def test_bok_search_determinism(self):
        """Test that search_o2_bok returns identical results for same query."""
        try:
            from mira.o2.engine import get_o2_engine

            # Get engine singleton
            engine = get_o2_engine()

            if not engine.o2_bok_index:
                pytest.skip("O2 BOK index not loaded")

            # Test query
            query = "aluminum oxygen service pressure limits"

            # Run search multiple times
            results_list = []
            for i in range(5):
                results = engine.search_o2_bok(query=query, k=10, use_hybrid=True)
                # Extract doc_ids and scores for comparison
                results_list.append([
                    (r.get('doc_id', ''), round(r.get('relevance_score', 0), 6))
                    for r in results
                ])

            # All results should be identical
            first_results = results_list[0]
            for i, results in enumerate(results_list[1:], start=2):
                assert len(results) == len(first_results), \
                    f"Result count mismatch on run {i}: {len(results)} != {len(first_results)}"

                for j, (doc_id, score) in enumerate(results):
                    expected_doc_id, expected_score = first_results[j]
                    assert doc_id == expected_doc_id, \
                        f"Doc ID mismatch on run {i}, position {j}: {doc_id} != {expected_doc_id}"
                    assert abs(score - expected_score) < 1e-6, \
                        f"Score mismatch on run {i}, position {j}: {score} != {expected_score}"

            print(f"[PASS] search_o2_bok determinism verified (5 identical runs)")
            print(f"  First 3 doc_ids: {[r[0][:30] + '...' if len(r[0]) > 30 else r[0] for r in first_results[:3]]}")

        except ImportError as e:
            pytest.skip(f"O2 engine not available: {e}")

    def test_bm25_search_determinism(self):
        """Test that BM25 search returns identical results for same query."""
        try:
            from mira.o2.engine import get_o2_engine

            # Get engine singleton
            engine = get_o2_engine()

            if not engine.bm25 and not engine.bm25_vocab:
                pytest.skip("BM25 index not loaded")

            # Test query
            query = "aluminum ignition temperature GOX"

            # Run search multiple times
            results_list = []
            for i in range(5):
                results = engine._search_bm25(query=query, k=10)
                results_list.append([
                    (r.get('doc_id', ''), round(r.get('bm25_score', 0), 6))
                    for r in results
                ])

            # All results should be identical
            first_results = results_list[0]
            for i, results in enumerate(results_list[1:], start=2):
                assert results == first_results, \
                    f"BM25 results mismatch on run {i}"

            print(f"[PASS] BM25 search determinism verified (5 identical runs)")

        except ImportError as e:
            pytest.skip(f"O2 engine not available: {e}")

    def test_semantic_search_determinism(self):
        """Test that semantic search returns identical results for same query."""
        try:
            from mira.o2.engine import get_o2_engine

            # Get engine singleton
            engine = get_o2_engine()

            if not engine.o2_bok_index:
                pytest.skip("O2 BOK index not loaded")

            # Test query
            query = "stainless steel oxygen compatibility"

            # Run search multiple times
            results_list = []
            for i in range(5):
                results = engine._search_semantic_only(query=query, k=10)
                results_list.append([
                    (r.get('doc_id', ''), round(r.get('relevance_score', 0), 6))
                    for r in results
                ])

            # All results should be identical
            first_results = results_list[0]
            for i, results in enumerate(results_list[1:], start=2):
                assert results == first_results, \
                    f"Semantic results mismatch on run {i}"

            print(f"[PASS] Semantic search determinism verified (5 identical runs)")

        except ImportError as e:
            pytest.skip(f"O2 engine not available: {e}")


if __name__ == "__main__":
    # Run tests
    test = TestO2Determinism()

    print("=" * 60)
    print("O2 Knowledge Twin Determinism Tests")
    print("=" * 60)
    print()

    try:
        test.test_evaluate_determinism()
    except Exception as e:
        print(f"[FAIL] test_evaluate_determinism failed: {e}")

    print()

    try:
        test.test_bok_search_determinism()
    except Exception as e:
        print(f"[FAIL] test_bok_search_determinism failed: {e}")

    print()

    try:
        test.test_bm25_search_determinism()
    except Exception as e:
        print(f"[FAIL] test_bm25_search_determinism failed: {e}")

    print()

    try:
        test.test_semantic_search_determinism()
    except Exception as e:
        print(f"[FAIL] test_semantic_search_determinism failed: {e}")

    print()
    print("=" * 60)
    print("Tests complete")
    print("=" * 60)
