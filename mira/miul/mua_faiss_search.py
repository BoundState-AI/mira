#!/usr/bin/env python3
"""
Module: Mua Faiss Search
Purpose: MUA FAISS-based precedent search with hybrid ranking.

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

from mira.core.safe_pickle import safe_pickle_load
import re
from pathlib import Path
from typing import List, Optional, Set
from dataclasses import dataclass

import numpy as np
try:
    import faiss  # type: ignore
except Exception:  # pragma: no cover - optional runtime dependency
    faiss = None

try:
    from sentence_transformers import SentenceTransformer  # type: ignore
except Exception:  # pragma: no cover - optional runtime dependency
    SentenceTransformer = None

# Default index location
DEFAULT_INDEX_DIR = Path(__file__).parent.parent / "databases" / "mua_bok_v2"

# Material family keywords for classification
MATERIAL_FAMILIES = {
    'stainless_steel': ['316', '304', '321', '347', 'cres', 'stainless', 'ss ', 'sst', 'a286', 'a-286'],
    'aluminum': ['aluminum', 'aluminium', 'al ', '6061', '7075', '2024', '2219'],
    'inconel': ['inconel', 'inc ', 'alloy 625', 'alloy 718', 'n06625', 'n07718'],
    'titanium': ['titanium', 'ti-6al', 'ti6al4v', 'ti ', 'r56400'],
    'copper': ['copper', 'cu ', 'monel', 'bronze', 'brass'],
    'polymer': ['teflon', 'ptfe', 'viton', 'kalrez', 'fluorocarbon', 'elastomer', 'rubber', 'vespel', 'polyimide', 'nylon', 'delrin'],
    'adhesive': ['adhesive', 'epoxy', 'loctite', 'eccobond', 'sealant', 'rtvs'],
    'lubricant': ['lubricant', 'grease', 'krytox', 'braycote'],
    'composite': ['composite', 'cfrp', 'fiberglass', 'kevlar'],
    'nickel': ['hastelloy', 'waspaloy', 'rene', 'mar-m', 'nimonic'],
}


def _get_gpu_resources():
    """Get GPU resources if available."""
    if faiss is None:
        return None
    try:
        if faiss.get_num_gpus() > 0:
            return faiss.StandardGpuResources()
    except Exception:
        pass
    return None


def _detect_material_family(material: str) -> Optional[str]:
    """Detect material family from designation."""
    if not material:
        return None
    mat_lower = material.lower()
    for family, keywords in MATERIAL_FAMILIES.items():
        if any(kw in mat_lower for kw in keywords):
            return family
    return 'other'


def _extract_alloy_numbers(material: str) -> Set[str]:
    """Extract numeric alloy identifiers for string matching."""
    if not material:
        return set()
    patterns = [
        r'\b(\d{3,4}[A-Z]?)\b',  # 304, 316L, 7075
        r'\bA-?(\d{3})\b',       # A286, A-286
    ]
    alloys = set()
    for pattern in patterns:
        matches = re.findall(pattern, material.upper())
        alloys.update(matches)
    return alloys


@dataclass
class MUASearchResult:
    """A semantic search result from FAISS."""
    rank: int
    score: float  # Combined score (lower = better)
    semantic_score: float  # FAISS L2 distance
    string_score: float  # String match bonus (0-1)
    file: str
    mua_number: Optional[str]
    material_designation: str
    material_family: Optional[str]
    is_umbrella: bool
    environment: Optional[str]
    category: Optional[str]
    determination: str
    rationale: Optional[str]
    application: Optional[str]


class MUAFAISSSearch:
    """FAISS-based semantic search with hybrid ranking over historic MUAs."""

    def __init__(self, index_dir: Path = DEFAULT_INDEX_DIR):
        self.index_dir = Path(index_dir)
        self.index = None
        self.metadata = None
        self.model = None
        self.using_gpu = False
        self._load()

    def _load(self):
        """Load FAISS index and metadata."""
        if faiss is None:
            raise RuntimeError(
                "MUA FAISS search dependency missing: install 'faiss-cpu' to enable this feature."
            )
        if SentenceTransformer is None:
            raise RuntimeError(
                "MUA embedding dependency missing: install 'sentence-transformers' to enable this feature."
            )

        index_path = self.index_dir / "mua_bok_v2.faiss"
        metadata_path = self.index_dir / "mua_bok_v2_metadata.pkl"

        if not index_path.exists():
            raise FileNotFoundError(f"FAISS index not found: {index_path}")

        # Load index
        cpu_index = faiss.read_index(str(index_path))

        # Try to move to GPU
        self.gpu_resources = _get_gpu_resources()
        if self.gpu_resources:
            self.index = faiss.index_cpu_to_gpu(self.gpu_resources, 0, cpu_index)
            self.using_gpu = True
        else:
            self.index = cpu_index
            self.using_gpu = False

        self.metadata = safe_pickle_load(metadata_path)

        # Load model (uses GPU automatically if CUDA available)
        self.model = SentenceTransformer("all-mpnet-base-v2")

    def _calculate_string_match_score(
        self,
        query_material: str,
        candidate_material: str
    ) -> float:
        """Calculate string match bonus (0-1, higher = better match)."""
        if not query_material or not candidate_material:
            return 0.0

        q_upper = query_material.upper()
        c_upper = candidate_material.upper()

        # Exact match
        if q_upper == c_upper:
            return 1.0

        # Substring match
        if q_upper in c_upper or c_upper in q_upper:
            return 0.7

        # Alloy number match
        q_alloys = _extract_alloy_numbers(query_material)
        c_alloys = _extract_alloy_numbers(candidate_material)
        if q_alloys and c_alloys and q_alloys & c_alloys:
            return 0.5

        # Family match only
        q_family = _detect_material_family(query_material)
        c_family = _detect_material_family(candidate_material)
        if q_family and c_family and q_family == c_family:
            return 0.2

        return 0.0

    def search(
        self,
        material: str,
        environment: Optional[str] = None,
        application: Optional[str] = None,
        k: int = 10,
        filter_umbrella: bool = True,
        family_filter: Optional[str] = None,
        string_weight: float = 0.4,
    ) -> List[MUASearchResult]:
        """Search for similar MUAs using hybrid semantic + string matching.

        Args:
            material: Material designation (e.g., "INCONEL 625")
            environment: Optional environment (e.g., "Oxygen", "Vacuum")
            application: Optional application context
            k: Number of results to return
            filter_umbrella: Filter out umbrella MUAs (default True)
            family_filter: Only return MUAs from this material family
            string_weight: Weight for string matching (0-1, default 0.4)

        Returns:
            List of MUASearchResult sorted by combined score (lowest = best)
        """
        # Build query text (same format as index)
        parts = [f"Material: {material}"]
        if environment:
            parts.append(f"Environment: {environment}")
        if application:
            parts.append(f"Application: {application}")

        query_text = " | ".join(parts)

        # Detect query material family for auto-filtering
        query_family = _detect_material_family(material)

        # Embed query
        query_embedding = self.model.encode([query_text], convert_to_numpy=True)

        # Search FAISS - get more candidates for filtering
        search_k = k * 5 if filter_umbrella else k * 2
        distances, indices = self.index.search(
            query_embedding.astype(np.float32), search_k
        )

        # Build results with hybrid scoring
        candidates = []
        for dist, idx in zip(distances[0], indices[0]):
            if idx < 0 or idx >= len(self.metadata):
                continue

            meta = self.metadata[idx]

            # Apply umbrella filter
            if filter_umbrella and meta.get("is_umbrella", False):
                continue

            # Apply family filter
            if family_filter and meta.get("material_family") != family_filter:
                continue

            # Calculate string match score
            string_score = self._calculate_string_match_score(
                material, meta.get("material_designation", "")
            )

            # Hybrid score: combine semantic (L2) and string match
            # Lower is better for semantic, higher is better for string
            # Normalize: semantic_score stays as-is, string_score inverted
            semantic_weight = 1.0 - string_weight
            combined_score = (
                semantic_weight * float(dist) -
                string_weight * string_score * 2.0  # Scale string boost
            )

            candidates.append({
                "meta": meta,
                "semantic_score": float(dist),
                "string_score": string_score,
                "combined_score": combined_score,
            })

        # Sort by combined score (lower = better)
        candidates.sort(key=lambda x: x["combined_score"])

        # Build final results
        results = []
        for rank, cand in enumerate(candidates[:k], 1):
            meta = cand["meta"]
            results.append(MUASearchResult(
                rank=rank,
                score=cand["combined_score"],
                semantic_score=cand["semantic_score"],
                string_score=cand["string_score"],
                file=meta.get("file", ""),
                mua_number=meta.get("mua_number"),
                material_designation=meta.get("material_designation", ""),
                material_family=meta.get("material_family"),
                is_umbrella=meta.get("is_umbrella", False),
                environment=meta.get("environment"),
                category=meta.get("category"),
                determination=meta.get("determination", "UNKNOWN"),
                rationale=meta.get("rationale"),
                application=meta.get("application"),
            ))

        return results


# Convenience function
def search_mua_precedents(
    material: str,
    environment: Optional[str] = None,
    limit: int = 5,
    filter_umbrella: bool = True,
) -> List[MUASearchResult]:
    """Quick hybrid search for MUA precedents."""
    search = MUAFAISSSearch()
    return search.search(
        material, environment,
        k=limit, filter_umbrella=filter_umbrella
    )


if __name__ == "__main__":
    # Quick test
    search = MUAFAISSSearch()
    print(f"Loaded {len(search.metadata)} MUAs")
    print(f"Using GPU: {search.using_gpu}")

    # Count umbrella vs non-umbrella
    umbrella_count = sum(1 for m in search.metadata if m.get("is_umbrella"))
    print(f"Umbrella MUAs: {umbrella_count}")
    print(f"Non-umbrella MUAs: {len(search.metadata) - umbrella_count}")

    print("\n--- Testing INCONEL 625 in Oxygen ---")
    results = search.search("INCONEL 625", "Oxygen", k=5)
    for r in results:
        print(f"\n{r.rank}. {r.file}")
        print(f"   Material: {r.material_designation}")
        print(f"   Family: {r.material_family}")
        print(f"   Score: {r.score:.3f} (semantic: {r.semantic_score:.3f}, string: {r.string_score:.2f})")
        print(f"   Environment: {r.environment}")
        print(f"   Determination: {r.determination}")
