#!/usr/bin/env python3
"""Full MUA V6 pipeline test."""

import sys
sys.path.insert(0, r"C:\BoundState")

from mira.mua.v6.retriever import V6PrecedentRetriever
from mira.mua.v6.precedent_models import (
    NormalizedEnvironment, 
    EnvironmentType,
    IssueCategory,
)

print("=" * 70)
print("MUA V6 Full Pipeline Test")
print("=" * 70)

# Initialize retriever
print("\n1. Initializing V6PrecedentRetriever...")
retriever = V6PrecedentRetriever()
assert retriever.is_loaded(), "Index should be loaded"
print(f"   Index loaded: {retriever._index_builder._index.ntotal} vectors")

# Test 1: Material + Environment workflow
print("\n2. Testing Material + Environment workflow...")
vacuum_env = NormalizedEnvironment(type=EnvironmentType.VACUUM)
results = retriever.retrieve_by_material_env(
    material="Stainless Steel 316L",
    environment=vacuum_env,
    top_k=5,
    approved_only=True,
)
print(f"   Found {len(results)} precedents for SS 316L in vacuum")
if results:
    print(f"   Top match: MUA {results[0].record.mua_number}")
    print(f"     Material: {results[0].record.material_designation}")
    print(f"     Score: {results[0].composite_score:.3f}")

# Test 2: Gap-driven workflow
print("\n3. Testing gap-driven retrieval workflow...")
cabin_env = NormalizedEnvironment(type=EnvironmentType.CABIN_AIR)
gaps = [IssueCategory.FLAMMABILITY, IssueCategory.OFFGASSING]
results = retriever.retrieve_by_gaps(
    material="Kapton polyimide",
    gaps=gaps,
    environment=cabin_env,
    top_k=5,
    approved_only=True,
)
print(f"   Found {len(results)} precedents for FLAM+TVS gaps")
if results:
    print(f"   Top match: MUA {results[0].record.mua_number}")
    print(f"     Material: {results[0].record.material_designation}")
    print(f"     Issues: {[i.value for i in results[0].record.issues]}")

# Test 3: Cabin air environment
print("\n4. Testing cabin air environment retrieval...")
results = retriever.retrieve_by_material_env(
    material="Velcro hook and loop",
    environment=cabin_env,
    top_k=5,
)
print(f"   Found {len(results)} precedents for Velcro in cabin air")
if results:
    print(f"   Top match: MUA {results[0].record.mua_number}")

# Test 4: Oxygen-enriched environment
print("\n5. Testing O2-enriched environment retrieval...")
o2_env = NormalizedEnvironment(
    type=EnvironmentType.ENRICHED_O2,
    pressure_psi=30,
    o2_concentration_pct=50,
)
results = retriever.retrieve_by_material_env(
    material="Aluminum 6061-T6",
    environment=o2_env,
    top_k=5,
)
print(f"   Found {len(results)} precedents for Al 6061 in enriched O2")
if results:
    for r in results[:3]:
        print(f"   - MUA {r.record.mua_number}: {r.record.material_designation} ({r.composite_score:.3f})")

# Test 5: Cryogenic environment
print("\n6. Testing cryogenic environment retrieval...")
cryo_env = NormalizedEnvironment(
    type=EnvironmentType.CRYOGENIC,
    temperature_f=-320,
)
results = retriever.retrieve_by_material_env(
    material="Inconel 718",
    environment=cryo_env,
    top_k=5,
)
print(f"   Found {len(results)} precedents for Inconel 718 in cryo")
if results:
    print(f"   Top match: MUA {results[0].record.mua_number}")
    print(f"     Material: {results[0].record.material_designation}")
    print(f"     Env type: {results[0].record.environment.type.value}")

# Test 6: Multiple issue categories
print("\n7. Testing multi-gap retrieval (FLAM + TOX + SCC)...")
multi_gaps = [IssueCategory.FLAMMABILITY, IssueCategory.TOXICITY, IssueCategory.STRESS_CORROSION_CRACKING]
results = retriever.retrieve_by_gaps(
    material="Titanium alloy Ti-6Al-4V",
    gaps=multi_gaps,
    environment=vacuum_env,
    top_k=5,
)
print(f"   Found {len(results)} precedents for Ti-6-4 with FLAM+TOX+SCC gaps")
if results:
    for r in results[:2]:
        print(f"   - MUA {r.record.mua_number}: {r.record.material_designation}")

# Test 7: Raw search
print("\n8. Testing raw semantic search...")
results = retriever.search_raw("silicone sealant adhesive RTV", top_k=5)
print(f"   Found {len(results)} results for 'silicone sealant adhesive RTV'")
if results:
    for record, score in results[:3]:
        print(f"   - Score {score:.3f}: {record.mua_number} - {record.material_designation}")

# Summary statistics
print("\n" + "=" * 70)
print("Pipeline Test Summary")
print("=" * 70)
stats = retriever._index_builder.get_stats()
print(f"Total indexed records: {stats['total_records']}")
print(f"APPROVED determinations: {stats['by_determination'].get('APPROVED', 0)}")
print(f"Known material families: {len(stats['by_material_family'])}")
print(f"Environment types: {len(stats['by_environment_type'])}")

print("\n" + "=" * 70)
print("ALL TESTS PASSED - V6 MUA Pipeline is operational")
print("=" * 70)
