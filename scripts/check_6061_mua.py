#!/usr/bin/env python3
"""Check what MUAs exist for 6061 aluminum."""

import sys
sys.path.insert(0, r"C:\BoundState")

from mira.mua.v6.retriever import V6PrecedentRetriever

print("Checking 6061 aluminum MUAs in V6 index...")
retriever = V6PrecedentRetriever()

# Search for 6061 aluminum
results = retriever.search_raw("6061 aluminum oxygen compatibility", top_k=10)

print(f"\nFound {len(results)} results for '6061 aluminum oxygen compatibility':")
for record, score in results:
    print(f"\n  Score: {score:.3f}")
    print(f"  MUA: {record.mua_number}")
    print(f"  Material: {record.material_designation}")
    print(f"  Determination: {record.determination}")
    print(f"  Environment: {record.environment.type.value if record.environment else 'N/A'}")
    print(f"  Issues: {[i.value for i in record.issues] if record.issues else []}")
