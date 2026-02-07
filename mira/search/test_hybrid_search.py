#!/usr/bin/env python3
"""
Module: Test Hybrid Search
Purpose: [Automatically migrated - needs manual review]

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

import sys
from pathlib import Path

# Add mira root to path
mira_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(mira_root))


def test_hybrid_search():
    """Quick validation that hybrid search improves exact matches."""
    from mira.search.hybrid_search import create_hybrid_search_from_mira

    # Find paths - mira_root is already C:\BoundState
    faiss_dir = mira_root / "mira" / "databases" / "mira_v2_faiss"
    faiss_index_path = faiss_dir / "maptis_faiss_index.bin"
    metadata_path = faiss_dir / "maptis_index_metadata.json"

    print(f"FAISS dir: {faiss_dir}")
    print(f"Index path: {faiss_index_path} (exists: {faiss_index_path.exists()})")
    print(f"Metadata path: {metadata_path} (exists: {metadata_path.exists()})")

    if not faiss_index_path.exists():
        print(f"ERROR: FAISS index not found at {faiss_index_path}")
        return False

    if not metadata_path.exists():
        print(f"ERROR: Metadata not found at {metadata_path}")
        return False

    print("Loading hybrid search engine...")
    hybrid = create_hybrid_search_from_mira(
        faiss_index_path=str(faiss_index_path),
        materials_metadata_path=str(metadata_path),
    )

    test_cases = [
        ("316L", "316"),                  # Exact match - BM25 should nail
        ("AISI 316L", "316"),             # Variant - BM25 should find
        ("stainless steel", "stainless"), # Semantic - FAISS should find
        ("Inconel 718", "718"),           # Exact match - BM25 should nail
        ("AMS 5648", "316"),              # Spec number - finds SS 316 with AMS5648G spec
    ]

    print("\n" + "=" * 70)
    print("HYBRID SEARCH VALIDATION TEST")
    print("=" * 70)
    print()

    all_passed = True
    for query, expected_substring in test_cases:
        results = hybrid.search(query, top_k=5)

        if not results:
            print(f"✗ Query: '{query}' - NO RESULTS")
            all_passed = False
            continue

        top_result = results[0]
        designation = top_result.designation

        passed = expected_substring.lower() in designation.lower()
        status = "PASS" if passed else "FAIL"

        if not passed:
            all_passed = False

        # Clean designation for safe printing (remove problematic Unicode)
        safe_designation = designation.encode('ascii', 'replace').decode('ascii')

        print(f"[{status}] Query: '{query}'")
        print(f"   Top result: {safe_designation}")
        print(f"   BM25 rank: {top_result.bm25_rank}")
        print(f"   FAISS rank: {top_result.faiss_rank}")
        print(f"   RRF score: {top_result.score:.4f}")
        print()

    print("=" * 70)
    if all_passed:
        print("ALL TESTS PASSED - Hybrid search is working correctly!")
    else:
        print("SOME TESTS FAILED - Check results above")
    print("=" * 70)

    return all_passed


if __name__ == "__main__":
    success = test_hybrid_search()
    sys.exit(0 if success else 1)
