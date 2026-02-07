#!/usr/bin/env python3
"""Debug fluorosilicone search."""
import sys
sys.path.insert(0, r"C:\BoundState")

import logging
logging.basicConfig(level=logging.WARNING)

from mira.core.search_engine import SemanticSearchEngine

# Clear caches
SemanticSearchEngine._fluorosilicone_materials_cache = None
SemanticSearchEngine._fluorosilicone_material_keys = None

e = SemanticSearchEngine()

# Get fluorosilicone materials from DB
fluoro = e._get_fluorosilicone_materials_from_db()
print(f"DB returned {len(fluoro)} fluorosilicone materials")

# Check how many have flamm_rating
with_flamm = [r for r in fluoro if r.get("original_material", {}).get("flamm_rating")]
print(f"With flamm_rating: {len(with_flamm)}")

# Show some with ratings
print("\nSample with ratings:")
for r in with_flamm[:10]:
    mat = r.get("original_material", {})
    print(f"  {mat.get('designation', 'N/A')[:40]}: flamm={mat.get('flamm_rating')}")
