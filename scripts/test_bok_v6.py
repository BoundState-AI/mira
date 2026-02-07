#!/usr/bin/env python3
"""Test BOK engine with V6 retriever."""

import sys
sys.path.insert(0, r"C:\BoundState")

from mira.MIRA_V2.src.query_engine_v2 import EvidenceFirstQueryEngine, MaterialConstraints

print("=" * 70)
print("Testing BOK Query Engine with V6 MUA Retriever")
print("=" * 70)

# Initialize engine
print("\nInitializing EvidenceFirstQueryEngine...")
engine = EvidenceFirstQueryEngine(enable_semantic=False)  # Disable semantic to focus on MUA

# Test 1: 6061 aluminum in oxygen
print("\n" + "=" * 50)
print("Test 1: 6061 aluminum in oxygen environment")
print("=" * 50)

constraints = MaterialConstraints(
    material="6061 aluminum",
    environment="oxygen",
)

results = engine.query_mua_precedents(constraints)
print(f"\nFound {len(results)} MUA precedents:")
for r in results[:5]:
    print(f"  {r['mua_number']}: {r['material_name'][:40]}")
    print(f"    Env: {r.get('inferred_environment', 'N/A')}, Primary: {r.get('is_primary_for_env')}")
    print(f"    Source: {r.get('source', 'bok_table')}")
    if r.get('v6_score'):
        print(f"    Score: {r['v6_score']:.3f}")

# Test 2: Generic oxygen query (any material)
print("\n" + "=" * 50)
print("Test 2: Generic oxygen compatibility query")
print("=" * 50)

constraints = MaterialConstraints(
    material=None,
    environment="oxygen",
)

results = engine.query_mua_precedents(constraints)
print(f"\nFound {len(results)} MUA precedents:")
for r in results[:5]:
    print(f"  {r['mua_number']}: {r['material_name'][:40]}")
    print(f"    Env: {r.get('inferred_environment', 'N/A')}, Primary: {r.get('is_primary_for_env')}")

# Test 3: Stainless steel in hydrogen
print("\n" + "=" * 50)
print("Test 3: Stainless steel in hydrogen")
print("=" * 50)

constraints = MaterialConstraints(
    material="stainless steel",
    environment="hydrogen",
)

results = engine.query_mua_precedents(constraints)
print(f"\nFound {len(results)} MUA precedents:")
for r in results[:5]:
    print(f"  {r['mua_number']}: {r['material_name'][:40]}")
    print(f"    Env: {r.get('inferred_environment', 'N/A')}, Primary: {r.get('is_primary_for_env')}")

print("\n" + "=" * 70)
print("BOK V6 Test Complete")
print("=" * 70)
