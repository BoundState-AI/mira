#!/usr/bin/env python3
"""Test semantic search in BOK engine."""

import sys
sys.path.insert(0, r"C:\BoundState")
import os
os.environ['MIRA_INDEX_DIR'] = r"C:\BoundState\mira\MIRA_V2\data\faiss_indexes"

from mira.MIRA_V2.src.query_engine_v2 import EvidenceFirstQueryEngine, MaterialConstraints

print("=" * 70)
print("Testing BOK Query Engine with Semantic Search")
print("=" * 70)

# Initialize engine WITH semantic search
print("\nInitializing EvidenceFirstQueryEngine with semantic search...")
engine = EvidenceFirstQueryEngine(enable_semantic=True, llm_provider="ollama")

# Check if semantic is enabled
print(f"Semantic retriever: {engine.semantic_retriever is not None}")
print(f"V6 retriever: {engine.v6_retriever is not None}")

# Test query
print("\n" + "=" * 50)
print("Test: 6061 aluminum in oxygen")
print("=" * 50)

constraints = MaterialConstraints(
    material="6061 aluminum",
    environment="oxygen",
)

# Test semantic evidence query directly
if engine.semantic_retriever:
    print("\nQuerying semantic evidence...")
    result = engine.query_semantic_evidence("6061 aluminum oxygen compatibility", constraints)
    if result:
        print(f"Total results: {result.get('total_results', 0)}")
        print(f"BOK standards: {len(result.get('bok_standards', {}).get('high', []))}")
        print(f"MUA precedents: {len(result.get('mua_precedents', {}).get('high', []))}")
        print(f"MAPTIS data: {len(result.get('maptis_data', {}).get('high', []))}")
    else:
        print("No semantic results returned")
else:
    print("Semantic retriever not available")

print("\n" + "=" * 70)
print("Done")
print("=" * 70)
