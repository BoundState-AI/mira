#!/usr/bin/env python3
"""Quick test for fluorosilicone search."""
import sys
sys.path.insert(0, r"C:\BoundState")

from mira.core.search_engine import SemanticSearchEngine

# Clear caches
SemanticSearchEngine._fluorosilicone_materials_cache = None
SemanticSearchEngine._fluorosilicone_material_keys = None

e = SemanticSearchEngine()
results = e.search("fluorosilicone o2 compatible", top_k=50)

print(f"\nFound {len(results)} results:\n")
for i, r in enumerate(results, 1):
    mat = r.get('material', {})
    designation = (mat.get('designation') or 'N/A')[:48]
    flamm = r.get('o2_rating') or r.get('flamm_rating') or mat.get('flamm_rating') or 'N/A'
    mat_type = (mat.get('material_type_name') or 'N/A')[:12]
    print(f"{i:2}. {designation:<48} flamm={flamm:<3} type={mat_type}")
