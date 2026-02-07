#!/usr/bin/env python3
"""
Module: Hybrid Search
Purpose: MIRA Hybrid Search Integration

BoundState AI 2025
Version: 1.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Fran OpenAI 5 <noreply@openai.com>
Co-Authored-By: Grok 4.0 <noreply@x.ai>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: SWE-032 (Data validation), SWE-033 (Requirements Traceability)
Safety Critical: False
"""

from typing import List, Dict, Any, Optional
from dataclasses import dataclass
import numpy as np
import logging

# For standalone use without full Athena import:
from rank_bm25 import BM25Okapi
import faiss

logger = logging.getLogger(__name__)


@dataclass
class HybridSearchResult:
    """Unified search result with provenance."""
    material_key: str
    designation: str
    score: float
    bm25_rank: Optional[int] = None
    faiss_rank: Optional[int] = None
    payload: Optional[Dict[str, Any]] = None


class MIRAHybridSearch:
    """
    Hybrid search for MAPTIS materials.

    Combines:
    - BM25 for exact/lexical matches (catches "316L", "AISI 316L", spec numbers)
    - FAISS for semantic matches (catches "stainless steel" → "SS 316")
    - RRF fusion to merge rankings

    Config matches Athena defaults:
    - rrf_k=60 (standard RRF constant)
    - bm25_k1=1.2, bm25_b=0.75 (BM25 tuning)
    - semantic_weight=0.8, lexical_weight=0.2 (for cross-encoder stage)
    """

    def __init__(
        self,
        faiss_index: faiss.Index,
        materials_lookup: Dict[str, Dict],  # material_key -> {designation, composition, ...}
        embedding_model,  # sentence-transformers model
        rrf_k: int = 60,
        bm25_k1: float = 1.2,
        bm25_b: float = 0.75,
        index_to_key: Optional[Dict[int, str]] = None,  # FAISS index -> material_key
    ):
        self.faiss_index = faiss_index
        self.materials_lookup = materials_lookup
        self.embedding_model = embedding_model
        self.rrf_k = rrf_k

        # FAISS index position -> material_key mapping
        self.index_to_key = index_to_key or {}

        # Build BM25 index from material designations + compositions
        self._build_bm25_index(bm25_k1, bm25_b)

        # Material keys for BM25 (corpus order matches BM25 index)
        self.material_keys = list(materials_lookup.keys())

        logger.info(f"MIRAHybridSearch initialized with {len(self.material_keys)} materials")
        logger.info(f"  FAISS index mapping: {len(self.index_to_key)} entries")
        logger.info(f"  BM25 params: k1={bm25_k1}, b={bm25_b}")
        logger.info(f"  RRF constant: k={rrf_k}")

    def _build_bm25_index(self, k1: float, b: float):
        """Build BM25 index over material text corpus."""
        import re
        corpus = []
        for mat_key, mat_data in self.materials_lookup.items():
            # Combine searchable fields
            text_parts = [
                mat_data.get('designation', ''),
                mat_data.get('composition_key', ''),
                mat_data.get('material_code', ''),
                mat_data.get('specification', ''),
            ]
            # Tokenize with alphanumeric boundary splitting
            # "AMS5648G" -> ["ams5648g", "ams", "5648", "g"]
            text = ' '.join(text_parts).lower()
            # Split on whitespace first
            words = text.split()
            tokens = []
            for word in words:
                tokens.append(word)  # Keep original token
                # Also split on letter/digit boundaries for partial matching
                # e.g., "ams5648g" -> ["ams", "5648", "g"]
                parts = re.findall(r'[a-z]+|\d+', word)
                if len(parts) > 1:
                    tokens.extend(parts)
            corpus.append(tokens)

        self.bm25 = BM25Okapi(corpus, k1=k1, b=b)
        self.corpus_keys = list(self.materials_lookup.keys())
        logger.info(f"Built BM25 index for {len(corpus)} materials")

    def search(
        self,
        query: str,
        top_k: int = 20,
        bm25_candidates: int = 50,
        faiss_candidates: int = 50,
    ) -> List[HybridSearchResult]:
        """
        Hybrid search with RRF fusion.

        Args:
            query: Natural language or spec number query
            top_k: Final results to return
            bm25_candidates: BM25 results to consider
            faiss_candidates: FAISS results to consider

        Returns:
            Ranked list of HybridSearchResult with fused scores
        """
        # Phase 1: BM25 lexical search
        bm25_results = self._bm25_search(query, bm25_candidates)

        # Phase 2: FAISS semantic search
        faiss_results = self._faiss_search(query, faiss_candidates)

        # Phase 3: RRF fusion
        fused = self._rrf_fuse(bm25_results, faiss_results)

        logger.debug(f"Hybrid search '{query}': BM25={len(bm25_results)}, FAISS={len(faiss_results)}, fused={len(fused)}")

        # Return top_k
        return fused[:top_k]

    def _bm25_search(self, query: str, top_k: int) -> List[tuple]:
        """BM25 lexical search. Returns [(material_key, rank), ...]"""
        import re
        # Tokenize with same alphanumeric boundary splitting as index
        words = query.lower().split()
        tokens = []
        for word in words:
            tokens.append(word)
            parts = re.findall(r'[a-z]+|\d+', word)
            if len(parts) > 1:
                tokens.extend(parts)
        scores = self.bm25.get_scores(tokens)

        # Get top indices
        top_indices = np.argsort(scores)[::-1][:top_k]

        results = []
        for rank, idx in enumerate(top_indices):
            if scores[idx] > 0:  # Only include actual matches
                results.append((self.corpus_keys[idx], rank + 1))

        return results

    def _faiss_search(self, query: str, top_k: int) -> List[tuple]:
        """FAISS semantic search. Returns [(material_key, rank), ...]"""
        # Embed query
        query_vec = self.embedding_model.encode([query])[0]
        query_vec = query_vec.reshape(1, -1).astype('float32')

        # Search FAISS
        distances, indices = self.faiss_index.search(query_vec, top_k)

        results = []
        for rank, (dist, idx) in enumerate(zip(distances[0], indices[0])):
            if idx >= 0:
                # Use index_to_key mapping to get material_key
                material_key = self.index_to_key.get(idx)
                if material_key and material_key in self.materials_lookup:
                    results.append((material_key, rank + 1))

        return results

    def _rrf_fuse(
        self,
        bm25_results: List[tuple],
        faiss_results: List[tuple],
    ) -> List[HybridSearchResult]:
        """
        Reciprocal Rank Fusion.

        RRF score = Σ 1/(k + rank_i) for each ranking system

        Using k=60 (standard) dampens the impact of high ranks
        while still preferring results that appear in multiple lists.

        Note: Deduplicates by material_key, keeping only the best rank
        for each material in each retriever to prevent inflation from
        multiple test records per material.
        """
        scores = {}  # material_key -> {rrf_score, bm25_rank, faiss_rank}

        # Score BM25 results (already deduplicated by material_key)
        for mat_key, rank in bm25_results:
            if mat_key not in scores:
                scores[mat_key] = {'rrf': 0, 'bm25': None, 'faiss': None}
            scores[mat_key]['rrf'] += 1.0 / (self.rrf_k + rank)
            scores[mat_key]['bm25'] = rank

        # Score FAISS results - deduplicate by material_key, keep best rank
        seen_faiss = set()
        for mat_key, rank in faiss_results:
            if mat_key in seen_faiss:
                continue  # Skip duplicates
            seen_faiss.add(mat_key)

            if mat_key not in scores:
                scores[mat_key] = {'rrf': 0, 'bm25': None, 'faiss': None}
            scores[mat_key]['rrf'] += 1.0 / (self.rrf_k + rank)
            scores[mat_key]['faiss'] = rank

        # Sort by RRF score
        sorted_keys = sorted(scores.keys(), key=lambda k: scores[k]['rrf'], reverse=True)

        # Build results with relevance filtering
        # Only include results that have EITHER:
        # 1. A BM25 hit (lexical match on material name), OR
        # 2. A top-10 FAISS hit (strong semantic match)
        # This prevents returning garbage when query doesn't match any materials
        MIN_RRF_SCORE = 0.008  # ~rank 65 in one system, filters bottom-of-barrel
        results = []
        for mat_key in sorted_keys:
            s = scores[mat_key]
            # Skip if no BM25 hit AND not a top-20 FAISS result
            has_bm25 = s['bm25'] is not None
            has_good_faiss = s['faiss'] is not None and s['faiss'] <= 20
            if not has_bm25 and not has_good_faiss:
                continue
            # Skip very low scores (garbage)
            if s['rrf'] < MIN_RRF_SCORE:
                continue

            mat_data = self.materials_lookup.get(mat_key, {})
            results.append(HybridSearchResult(
                material_key=mat_key,
                designation=mat_data.get('designation', mat_key),
                score=s['rrf'],
                bm25_rank=s['bm25'],
                faiss_rank=s['faiss'],
                payload=mat_data,
            ))

        return results


# =============================================================================
# Integration with existing MIRA search endpoint
# =============================================================================

def create_hybrid_search_from_mira(
    faiss_index_path: str,
    materials_metadata_path: str,
    embedding_model_name: str = "all-MiniLM-L6-v2",
) -> MIRAHybridSearch:
    """
    Factory function to create hybrid search from existing MIRA artifacts.

    Args:
        faiss_index_path: Path to maptis_faiss_index.bin
        materials_metadata_path: Path to maptis_index_metadata.json
        embedding_model_name: Sentence transformer model name

    Returns:
        Configured MIRAHybridSearch instance
    """
    import json
    from sentence_transformers import SentenceTransformer

    logger.info(f"Loading FAISS index from: {faiss_index_path}")
    index = faiss.read_index(faiss_index_path)

    logger.info(f"Loading materials metadata from: {materials_metadata_path}")
    with open(materials_metadata_path, 'r') as f:
        metadata = json.load(f)

    # Build lookup dict AND index-ordered keys (handle MIRA V2 format with source_metadata.metadata)
    materials_lookup = {}
    index_to_key = {}  # FAISS index position -> material_key
    spec_lookup = {}  # material_key -> list of spec names (AMS5648, ASTM A276, etc.)
    rating_aggregator = {}  # material_key -> {flam: [], tvs: [], corr: [], scc: [], tox: [], o2_flam: []}

    if isinstance(metadata, dict) and 'source_metadata' in metadata:
        # MIRA V2 format: {source_metadata: {metadata: [...]}}
        records = metadata.get('source_metadata', {}).get('metadata', [])
        logger.info(f"Found {len(records)} records in source_metadata.metadata")

        # FIRST PASS: Build spec lookup from material_specifications_report records
        # These have matlspecs_name (spec name) and matlspecs_materialkey (links to material)
        for record in records:
            payload = record.get('payload', {})
            spec_name = payload.get('matlspecs_name', '')
            mat_key = payload.get('matlspecs_materialkey')

            # Skip empty/NULL specs or records without material link
            if not spec_name or spec_name == 'NULL' or not mat_key:
                continue

            key_str = str(mat_key)
            if key_str not in spec_lookup:
                spec_lookup[key_str] = set()
            spec_lookup[key_str].add(spec_name)

        logger.info(f"Built spec lookup with {len(spec_lookup)} materials having specs")
        if spec_lookup:
            # Log sample of specs found
            sample_key = next(iter(spec_lookup))
            logger.info(f"  Sample: material {sample_key} has specs: {list(spec_lookup[sample_key])[:3]}")

        # SECOND PASS: Build materials lookup with specs merged in
        for record in records:
            # Extract material_key from either top level or payload
            payload = record.get('payload', {})
            material_key = (
                record.get('material_key') or
                payload.get('materialkey') or
                payload.get('matl_materialkey')
            )

            # Store FAISS index -> material_key mapping
            idx = record.get('idx')
            if idx is not None and material_key:
                index_to_key[idx] = str(material_key)

            # Aggregate ratings from EVERY test record for this material
            # (not just first-seen - we need all tests to compute worst-case)
            if material_key:
                key_str = str(material_key)
                if key_str not in rating_aggregator:
                    rating_aggregator[key_str] = {
                        'flam': [], 'tvs': [], 'corr': [],
                        'scc': [], 'tox': [], 'o2_flam': [],
                    }
                agg = rating_aggregator[key_str]

                # Flammability rating
                flam_r = payload.get('flam_rating')
                if flam_r and flam_r not in ('NULL', '', None):
                    agg['flam'].append(flam_r)
                    # Derive O2 rating: flam tests conducted in enriched oxygen (>21%)
                    # Field is flam_originalpercentoxygen, values like "30.3000" or "NULL"
                    o2_pct_str = payload.get('flam_originalpercentoxygen') or ''
                    try:
                        o2_pct = float(o2_pct_str) if o2_pct_str and o2_pct_str != 'NULL' else 0
                    except (ValueError, TypeError):
                        o2_pct = 0
                    # Enriched O2 = above ambient (21%). Include tests at 24%+ to be safe.
                    if o2_pct > 23:
                        agg['o2_flam'].append(flam_r)

                # Other ratings (tvs, corr, scc, tox)
                for tag in ('tvs', 'corr', 'scc', 'tox'):
                    val = payload.get(f'{tag}_rating')
                    if val and val not in ('NULL', '', None):
                        agg[tag].append(val)

            if not material_key:
                continue

            key_str = str(material_key)

            # Extract designation from various possible fields
            designation = (
                payload.get('matl_designation') or
                payload.get('designation') or
                payload.get('name') or
                ''
            )

            # Build/update material entry (deduplicate by material_key)
            if key_str not in materials_lookup:
                # Get specs from spec_lookup (joined from material_specifications_report records)
                specs_for_material = spec_lookup.get(key_str, set())
                spec_string = ' '.join(specs_for_material) if specs_for_material else ''

                materials_lookup[key_str] = {
                    'designation': designation,
                    'material_code': payload.get('matl_materialcode') or payload.get('material_code') or '',
                    'composition_key': payload.get('matl_compositionkey') or payload.get('composition_key') or '',
                    # Include both test spec AND joined spec names for BM25
                    'specification': f"{payload.get('matl_testspec') or ''} {spec_string}".strip(),
                    'spec_names': list(specs_for_material),  # Keep original list for reference
                    'material_type_key': payload.get('matl_materialtypekey') or payload.get('material_type_key'),
                    'payload': payload,
                }
            elif designation and not materials_lookup[key_str].get('designation'):
                # Update if we found a designation for an existing entry
                materials_lookup[key_str]['designation'] = designation

    elif isinstance(metadata, list):
        # Legacy format: list of {material_key, payload, ...}
        for i, item in enumerate(metadata):
            key = str(item.get('material_key', ''))
            if key:
                materials_lookup[key] = item.get('payload', item)
                index_to_key[i] = key

    elif isinstance(metadata, dict):
        # Old format: dict keyed by material_key directly
        materials_lookup = {str(k): v for k, v in metadata.items()}

    # =========================================================================
    # Resolve aggregated ratings (worst-case per MAPTIS Expert Skills)
    # "Duplicate tests: ALWAYS take worst-case rating"
    # =========================================================================
    _RATING_SEVERITY = {'A': 0, 'B': 1, 'C': 2, 'D': 3, 'X': 4, 'U': 5}

    def _worst_rating(ratings: list) -> Optional[str]:
        """Return worst-case rating from a list. Handles MAPTIS junk values."""
        if not ratings:
            return None
        # Clean up MAPTIS junk: NULL strings, whitespace, empty strings
        valid = [
            r.upper().strip() for r in ratings
            if r and isinstance(r, str) and r.strip() and r.upper().strip() != 'NULL'
        ]
        if not valid:
            return None
        # Unrecognized ratings treated as severity 5 (unknown/worst)
        return max(valid, key=lambda r: _RATING_SEVERITY.get(r, 5))

    # Apply worst-case ratings to materials_lookup
    for mat_key, agg in rating_aggregator.items():
        if mat_key in materials_lookup:
            mat = materials_lookup[mat_key]
            mat['flamm_rating'] = _worst_rating(agg['flam'])
            mat['tvs_rating'] = _worst_rating(agg['tvs'])
            mat['corr_rating'] = _worst_rating(agg['corr'])
            mat['scc_rating'] = _worst_rating(agg['scc'])
            mat['tox_rating'] = _worst_rating(agg['tox'])
            mat['o2_rating'] = _worst_rating(agg['o2_flam'])
            mat['h2_rating'] = None  # H2 requires embrittlement/family analysis - separate problem

    # Log rating stats
    materials_with_o2 = sum(1 for m in materials_lookup.values() if m.get('o2_rating'))
    materials_with_flamm = sum(1 for m in materials_lookup.values() if m.get('flamm_rating'))
    logger.info(f"Aggregated ratings: {materials_with_flamm} materials with flamm_rating, {materials_with_o2} with o2_rating")

    logger.info(f"Built materials lookup with {len(materials_lookup)} unique materials")
    logger.info(f"Built FAISS index mapping with {len(index_to_key)} entries")

    # Log how many materials have spec names populated
    materials_with_specs = sum(1 for m in materials_lookup.values() if m.get('spec_names'))
    logger.info(f"Materials with spec names for BM25: {materials_with_specs}")

    # Load embedding model
    logger.info(f"Loading embedding model: {embedding_model_name}")
    model = SentenceTransformer(embedding_model_name)

    return MIRAHybridSearch(
        faiss_index=index,
        materials_lookup=materials_lookup,
        embedding_model=model,
        index_to_key=index_to_key,
    )


# =============================================================================
# Drop-in replacement for SemanticSearchEngine.search()
# =============================================================================

def patch_semantic_search_engine(engine, hybrid_search: MIRAHybridSearch):
    """
    Monkey-patch existing SemanticSearchEngine to use hybrid search.

    Usage:
        from mira.search.hybrid_search import patch_semantic_search_engine, create_hybrid_search_from_mira

        hybrid = create_hybrid_search_from_mira(
            faiss_index_path="databases/maptis_faiss_index.bin",
            materials_metadata_path="databases/maptis_index_metadata.json",
        )
        patch_semantic_search_engine(search_engine, hybrid)
    """
    original_search = engine.search

    def hybrid_search_wrapper(query: str, top_k: int = 20, **kwargs):
        # Get query intent for filtering (reuse engine's intent understanding)
        query_intent = {}
        try:
            if hasattr(engine, 'understand_query_intent'):
                query_intent = engine.understand_query_intent(query)
        except Exception as e:
            logger.warning(f"[HYBRID] Intent detection failed: {e}")

        # Expand candidate pool if filtering will be applied
        search_top_k = top_k
        if query_intent.get('material_subtype_hint') or query_intent.get('material_type_hint'):
            search_top_k = min(top_k * 10, 500)  # Get more candidates to filter from
            logger.info(f"[HYBRID] Intent filters detected, expanding search to {search_top_k} candidates")

        results = hybrid_search.search(query, top_k=search_top_k)

        # Convert to ui_endpoints.py expected format (nested material/original_material dicts)
        converted = []
        for r in results:
            payload = r.payload or {}
            # Get aggregated ratings from materials_lookup (worst-case across all test records)
            mat_lookup = hybrid_search.materials_lookup.get(r.material_key, {})
            material_code = (
                payload.get('matl_materialcode') or
                payload.get('material_code') or
                ''
            )
            material_type_key = (
                payload.get('matl_materialtypekey') or
                payload.get('material_type_key') or
                mat_lookup.get('material_type_key')
            )
            # Build original_material with all payload fields
            original_material = {
                'material_key': r.material_key,
                'material_code': material_code,
                'matl_designation': r.designation,
                'designation': r.designation,
                'material_type_key': material_type_key,
                **payload,  # raw test-level fields
                # Override with aggregated worst-case ratings from materials_lookup
                'flamm_rating': mat_lookup.get('flamm_rating'),
                'tvs_rating': mat_lookup.get('tvs_rating'),
                'corr_rating': mat_lookup.get('corr_rating'),
                'scc_rating': mat_lookup.get('scc_rating'),
                'tox_rating': mat_lookup.get('tox_rating'),
                'o2_rating': mat_lookup.get('o2_rating'),
                'h2_rating': mat_lookup.get('h2_rating'),
            }
            converted.append({
                'material': {
                    'material_id': r.material_key,
                    'name': r.designation,
                    'designation': r.designation,
                    'material_code': material_code,
                    'composition': payload.get('matl_compositionkey') or payload.get('composition_key') or '',
                },
                'original_material': original_material,
                'similarity_score': r.score,
                'bm25_rank': r.bm25_rank,
                'faiss_rank': r.faiss_rank,
            })

        # Inject fluorosilicone materials from DB if fluorosilicone query detected
        try:
            subtype = query_intent.get('material_subtype_hint', '').lower()
            if subtype == 'fluorosilicone' or 'fluorosilicone' in query.lower():
                if hasattr(engine, '_get_fluorosilicone_materials_from_db'):
                    fluoro_results = engine._get_fluorosilicone_materials_from_db()
                    if fluoro_results:
                        before = len(converted)
                        converted.extend(fluoro_results)
                        logger.info(f"[HYBRID] Injected {len(fluoro_results)} fluorosilicone materials (pool {before} -> {len(converted)})")
        except Exception as e:
            logger.warning(f"[HYBRID] Fluorosilicone injection failed: {e}")

        # Apply intent filters (fluorosilicone, material type, etc.)
        if query_intent.get('material_subtype_hint') or query_intent.get('material_type_hint') or query_intent.get('rating_required'):
            try:
                if hasattr(engine, '_apply_intent_filters'):
                    before = len(converted)
                    converted = engine._apply_intent_filters(converted, query_intent)
                    logger.info(f"[HYBRID] Applied intent filters: {before} -> {len(converted)} results")
            except Exception as e:
                logger.warning(f"[HYBRID] Intent filtering failed: {e}")

        # Return top_k results after filtering
        return converted[:top_k]

    engine.search = hybrid_search_wrapper
    engine._original_search = original_search
    logger.info("Patched SemanticSearchEngine with hybrid BM25+FAISS+RRF search")
    return engine


if __name__ == "__main__":
    # Quick test
    print("MIRA Hybrid Search - P0 Integration")
    print("=" * 50)
    print("Components:")
    print("  - BM25 (rank_bm25) for lexical matching")
    print("  - FAISS for semantic similarity")
    print("  - RRF fusion (k=60)")
    print()
    print("Usage:")
    print("  hybrid = create_hybrid_search_from_mira(")
    print("      faiss_index_path='databases/maptis_faiss_index.bin',")
    print("      materials_metadata_path='databases/maptis_index_metadata.json',")
    print("  )")
    print("  results = hybrid.search('316L stainless steel')")
