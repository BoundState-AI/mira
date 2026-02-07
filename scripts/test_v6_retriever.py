#!/usr/bin/env python3
"""Quick test of V6 MUA retriever."""

import sys
sys.path.insert(0, r"C:\BoundState")

from mira.mua.v6.retriever import V6PrecedentRetriever

print("=" * 60)
print("V6 MUA Retriever Test")
print("=" * 60)

# Initialize retriever
print("\nInitializing retriever...")
retriever = V6PrecedentRetriever()

if not retriever.is_loaded():
    print("ERROR: Index not loaded!")
    sys.exit(1)

# Access stats through the index builder
print(f"  Index loaded: {retriever._index_builder._index.ntotal} vectors")
print(f"  Metadata records: {len(retriever._index_builder._metadata)}")

# Test query 1: Hydrogen compatibility
print("\n--- Query 1: Hydrogen compatibility for stainless steel ---")
query = "stainless steel hydrogen compatibility austenitic"
results = retriever.search_raw(query, top_k=5)

print(f"Found {len(results)} results:")
for record, score in results[:3]:
    print(f"  Score: {score:.3f} | MUA: {record.mua_number}")
    print(f"    Material: {record.material_designation}")
    print(f"    Family: {record.material_family}")
    print(f"    Determination: {record.determination}")
    if record.environment:
        env_type = getattr(record.environment, 'type', None)
        print(f"    Environment: {env_type}")
    print()

# Test query 2: Oxygen compatibility
print("\n--- Query 2: Oxygen compatibility titanium ---")
query = "titanium oxygen compatibility LOX"
results = retriever.search_raw(query, top_k=5)

print(f"Found {len(results)} results:")
for record, score in results[:3]:
    print(f"  Score: {score:.3f} | MUA: {record.mua_number}")
    print(f"    Material: {record.material_designation}")
    print(f"    Determination: {record.determination}")
    print()

# Test query 3: Flammability
print("\n--- Query 3: Aluminum alloy flammability ---")
query = "aluminum alloy flammability 6061"
results = retriever.search_raw(query, top_k=5)

print(f"Found {len(results)} results:")
for record, score in results[:3]:
    print(f"  Score: {score:.3f} | MUA: {record.mua_number}")
    print(f"    Material: {record.material_designation}")
    print(f"    Determination: {record.determination}")
    print()

# Get index stats via index builder
print("\n--- Index Statistics ---")
stats = retriever._index_builder.get_stats()
print(f"Total records: {stats.get('total_records', 'N/A')}")
print(f"Index vectors: {stats.get('index_vectors', 'N/A')}")

print("\nBy Determination:")
for det, count in sorted(stats.get('by_determination', {}).items(), key=lambda x: -x[1])[:5]:
    print(f"  {det}: {count}")

print("\nBy Environment Type:")
for env, count in sorted(stats.get('by_environment_type', {}).items(), key=lambda x: -x[1])[:5]:
    print(f"  {env}: {count}")

print("\nBy Material Family:")
for fam, count in sorted(stats.get('by_material_family', {}).items(), key=lambda x: -x[1])[:5]:
    print(f"  {fam}: {count}")

print("\n" + "=" * 60)
print("V6 Retriever test PASSED")
print("=" * 60)
