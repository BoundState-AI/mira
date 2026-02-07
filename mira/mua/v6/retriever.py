#!/usr/bin/env python3
"""
Module: Retriever
Purpose: V6 Precedent Retriever - Search and rank historic MUA precedents.

BoundState AI 2025
Version: 1.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Fran OpenAI 5 <noreply@openai.com>
Co-Authored-By: Grok 4.0 <noreply@x.ai>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: SWE-013 (Traceability), SWE-032 (Data validation)
Safety Critical: False
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np

# BM25 for lexical matching
try:
    from rank_bm25 import BM25Okapi
    BM25_AVAILABLE = True
except ImportError:
    BM25_AVAILABLE = False

from .precedent_models import (
    CleanedMUARecord,
    IssueCategory,
    EnvironmentType,
    MaterialFamily,
    NormalizedEnvironment,
    PrecedentMatch,
    MatchFactors,
)
from .index_builder import V6IndexBuilder, DEFAULT_INDEX_DIR

logger = logging.getLogger(__name__)

__all__ = ["V6PrecedentRetriever", "StructuredFilterEngine", "PrecedentRanker"]


# =============================================================================
# Structured Filter Engine
# =============================================================================

class StructuredFilterEngine:
    """Apply structured filters to narrow precedent search results."""

    # Environment compatibility matrix - which types are compatible
    ENV_COMPATIBILITY = {
        EnvironmentType.VACUUM: {EnvironmentType.VACUUM},
        EnvironmentType.CABIN_AIR: {EnvironmentType.CABIN_AIR, EnvironmentType.AMBIENT},
        EnvironmentType.ENRICHED_O2: {EnvironmentType.ENRICHED_O2, EnvironmentType.CABIN_AIR, EnvironmentType.PURE_O2},
        EnvironmentType.PURE_O2: {EnvironmentType.PURE_O2, EnvironmentType.ENRICHED_O2, EnvironmentType.LOX_GOX},
        EnvironmentType.LOX_GOX: {EnvironmentType.LOX_GOX, EnvironmentType.PURE_O2},
        EnvironmentType.CRYOGENIC: {EnvironmentType.CRYOGENIC, EnvironmentType.LOX_GOX},
        EnvironmentType.HIGH_PRESSURE: {EnvironmentType.HIGH_PRESSURE},
        EnvironmentType.WATER: {EnvironmentType.WATER},
        EnvironmentType.CO2: {EnvironmentType.CO2},
    }

    def filter_by_environment_type(
        self,
        candidates: List[CleanedMUARecord],
        target_type: EnvironmentType,
        strict: bool = False,
    ) -> List[CleanedMUARecord]:
        """Filter to matching or compatible environment types.

        Args:
            candidates: List of candidate records
            target_type: Target environment type
            strict: If True, only exact matches; if False, allow compatible types

        Returns:
            Filtered list of records
        """
        if strict:
            return [r for r in candidates if r.environment.type == target_type]

        compatible = self.ENV_COMPATIBILITY.get(target_type, {target_type})
        return [r for r in candidates if r.environment.type in compatible]

    def filter_by_issues(
        self,
        candidates: List[CleanedMUARecord],
        required_issues: List[IssueCategory],
        require_all: bool = False,
    ) -> List[CleanedMUARecord]:
        """Filter to records that address required issues.

        Args:
            candidates: List of candidate records
            required_issues: Issues that must be addressed
            require_all: If True, record must address ALL issues; else ANY

        Returns:
            Filtered list of records
        """
        required_set = set(required_issues)

        if require_all:
            return [r for r in candidates if required_set.issubset(set(r.issues))]
        else:
            return [r for r in candidates if required_set.intersection(set(r.issues))]

    def filter_by_determination(
        self,
        candidates: List[CleanedMUARecord],
        allowed: List[str] = None,
    ) -> List[CleanedMUARecord]:
        """Filter by determination status.

        Args:
            candidates: List of candidate records
            allowed: List of allowed determinations (default: APPROVED only)

        Returns:
            Filtered list of records
        """
        if allowed is None:
            allowed = ["APPROVED"]

        allowed_upper = [d.upper() for d in allowed]
        return [r for r in candidates if r.determination in allowed_upper]

    def filter_by_material_family(
        self,
        candidates: List[CleanedMUARecord],
        target_family: MaterialFamily,
    ) -> List[CleanedMUARecord]:
        """Filter to matching material family.

        Args:
            candidates: List of candidate records
            target_family: Target material family

        Returns:
            Filtered list of records
        """
        return [r for r in candidates if r.material_family == target_family]

    def filter_by_confidence(
        self,
        candidates: List[CleanedMUARecord],
        min_confidence: float = 0.7,
    ) -> List[CleanedMUARecord]:
        """Filter by extraction confidence.

        Args:
            candidates: List of candidate records
            min_confidence: Minimum confidence threshold

        Returns:
            Filtered list of records
        """
        return [r for r in candidates if r.confidence >= min_confidence]

    def filter_by_habitability(
        self,
        candidates: List[CleanedMUARecord],
        is_habitable: bool,
    ) -> List[CleanedMUARecord]:
        """Filter by habitability requirement.

        Args:
            candidates: List of candidate records
            is_habitable: Whether target environment is habitable

        Returns:
            Filtered list of records
        """
        # For habitable requests, prefer habitable precedents
        # For non-habitable, allow any
        if is_habitable:
            return [r for r in candidates if r.environment.is_habitable]
        return candidates


# =============================================================================
# Precedent Ranker
# =============================================================================

class PrecedentRanker:
    """
    Rank precedent matches using weighted scoring.

    Scoring formula:
    score = (
        0.30 * material_match +      # Material similarity
        0.25 * environment_match +   # Environment compatibility
        0.25 * issue_match +         # Issue category overlap
        0.10 * determination_boost + # APPROVED > DEFERRED > others
        0.10 * confidence            # Extraction confidence
    )
    """

    WEIGHTS = {
        "material": 0.30,
        "environment": 0.25,
        "issue": 0.25,
        "determination": 0.10,
        "confidence": 0.10,
    }

    # Material family similarity scores
    FAMILY_SIMILARITY = {
        # Same general category gets partial credit
        (MaterialFamily.STAINLESS_STEEL, MaterialFamily.CARBON_STEEL): 0.6,
        (MaterialFamily.STAINLESS_STEEL, MaterialFamily.NICKEL_ALLOY): 0.5,
        (MaterialFamily.ALUMINUM, MaterialFamily.TITANIUM): 0.4,
        (MaterialFamily.POLYMER, MaterialFamily.ELASTOMER): 0.5,
        (MaterialFamily.COATING, MaterialFamily.ADHESIVE): 0.4,
        (MaterialFamily.SEALANT, MaterialFamily.ADHESIVE): 0.5,
    }

    def rank(
        self,
        query_material: str,
        query_env: NormalizedEnvironment,
        query_issues: List[IssueCategory],
        candidates: List[Tuple[CleanedMUARecord, float]],
        min_score: float = 0.3,
    ) -> List[PrecedentMatch]:
        """Rank candidates by composite score.

        Args:
            query_material: Query material designation
            query_env: Query normalized environment
            query_issues: Query issue categories
            candidates: List of (record, semantic_score) from FAISS search
            min_score: Minimum composite score threshold

        Returns:
            Ranked list of PrecedentMatch objects
        """
        matches = []

        for record, semantic_score in candidates:
            factors = self._compute_match_factors(
                query_material, query_env, query_issues, record
            )

            # Incorporate semantic score into composite
            composite = (
                factors.weighted_score() * 0.6 +  # Structured matching
                semantic_score * 0.4               # Semantic similarity
            )

            if composite >= min_score:
                matches.append(PrecedentMatch(
                    record=record,
                    semantic_score=semantic_score,
                    match_factors=factors,
                    composite_score=composite,
                    rank=0,  # Will be set after sorting
                ))

        # Sort by composite score descending
        matches.sort(key=lambda m: m.composite_score, reverse=True)

        # Assign ranks
        for i, match in enumerate(matches):
            match.rank = i + 1

        return matches

    def _compute_match_factors(
        self,
        query_material: str,
        query_env: NormalizedEnvironment,
        query_issues: List[IssueCategory],
        candidate: CleanedMUARecord,
    ) -> MatchFactors:
        """Compute detailed match factors for a candidate."""
        return MatchFactors(
            material_score=self._score_material(query_material, candidate),
            environment_score=self._score_environment(query_env, candidate.environment),
            issue_score=self._score_issues(query_issues, candidate.issues),
            determination_boost=self._score_determination(candidate.determination),
            confidence_score=candidate.confidence,
        )

    def _score_material(
        self,
        query: str,
        candidate: CleanedMUARecord,
    ) -> float:
        """Score material match (0-1)."""
        query_lower = query.lower()
        cand_lower = candidate.material_designation.lower()

        # Exact match
        if query_lower == cand_lower:
            return 1.0

        # Substring match (e.g., "6061" in "6061-T6")
        if query_lower in cand_lower or cand_lower in query_lower:
            return 0.9

        # Same material family
        query_family = self._detect_family(query)
        if query_family == candidate.material_family and query_family != MaterialFamily.UNKNOWN:
            return 0.8

        # Similar family
        if query_family != MaterialFamily.UNKNOWN:
            pair = (query_family, candidate.material_family)
            reverse_pair = (candidate.material_family, query_family)
            if pair in self.FAMILY_SIMILARITY:
                return self.FAMILY_SIMILARITY[pair]
            if reverse_pair in self.FAMILY_SIMILARITY:
                return self.FAMILY_SIMILARITY[reverse_pair]

        # Check for alloy number matches
        import re
        query_nums = set(re.findall(r'\d{3,4}', query))
        cand_nums = set(re.findall(r'\d{3,4}', candidate.material_designation))
        if query_nums and query_nums.intersection(cand_nums):
            return 0.7

        return 0.2  # Different but potentially applicable

    def _detect_family(self, material: str) -> MaterialFamily:
        """Quick family detection for scoring."""
        mat_lower = material.lower()

        if any(x in mat_lower for x in ['stainless', 'cres', '304', '316', '321', '17-4', '17-7']):
            return MaterialFamily.STAINLESS_STEEL
        if any(x in mat_lower for x in ['aluminum', 'aluminium', '2024', '6061', '7075']):
            return MaterialFamily.ALUMINUM
        if any(x in mat_lower for x in ['titanium', 'ti-6al']):
            return MaterialFamily.TITANIUM
        if any(x in mat_lower for x in ['inconel', 'hastelloy', 'monel', '625', '718']):
            return MaterialFamily.NICKEL_ALLOY
        if any(x in mat_lower for x in ['viton', 'epdm', 'silicone', 'o-ring', 'elastomer']):
            return MaterialFamily.ELASTOMER
        if any(x in mat_lower for x in ['teflon', 'ptfe', 'kapton', 'polymer', 'nylon']):
            return MaterialFamily.POLYMER

        return MaterialFamily.UNKNOWN

    def _score_environment(
        self,
        query: NormalizedEnvironment,
        candidate: NormalizedEnvironment,
    ) -> float:
        """Score environment match (0-1)."""
        score = 0.0

        # Type match
        if query.type == candidate.type:
            score += 0.5
        elif query.type in StructuredFilterEngine.ENV_COMPATIBILITY.get(candidate.type, set()):
            score += 0.3

        # O2 percentage match
        if query.o2_percent is not None and candidate.o2_percent is not None:
            diff = abs(query.o2_percent - candidate.o2_percent)
            if diff <= 5:
                score += 0.2
            elif diff <= 10:
                score += 0.1

        # Pressure proximity
        if query.pressure_psia and candidate.pressure_psia:
            ratio = min(query.pressure_psia, candidate.pressure_psia) / max(query.pressure_psia, candidate.pressure_psia)
            score += 0.15 * ratio

        # Habitability match
        if query.is_habitable == candidate.is_habitable:
            score += 0.15

        return min(1.0, score)

    def _score_issues(
        self,
        query_issues: List[IssueCategory],
        candidate_issues: List[IssueCategory],
    ) -> float:
        """Score issue category overlap (0-1)."""
        if not query_issues:
            return 0.5  # No specific issues requested

        query_set = set(query_issues)
        cand_set = set(candidate_issues)

        overlap = query_set.intersection(cand_set)
        if not overlap:
            return 0.1  # No overlap but might still be relevant

        # Jaccard-like score
        return len(overlap) / len(query_set)

    def _score_determination(self, determination: str) -> float:
        """Score determination status (0-1)."""
        scores = {
            "APPROVED": 1.0,
            "DEFERRED": 0.5,
            "CONDITIONAL": 0.5,
            "CANCELLED": 0.2,
            "REJECTED": 0.0,
            "UNKNOWN": 0.3,
        }
        return scores.get(determination, 0.3)


# =============================================================================
# V6 Precedent Retriever
# =============================================================================

class V6PrecedentRetriever:
    """
    Retrieve precedent MUAs from v6 parsed data.

    Combines FAISS semantic search with BM25 lexical search and structured
    filtering/ranking. Uses Reciprocal Rank Fusion (RRF) for hybrid results.
    Supports both material+environment and gap-driven workflows.
    """

    # BM25 tuning parameters (from proven Athena defaults)
    BM25_K1 = 1.2
    BM25_B = 0.75
    RRF_K = 60  # RRF fusion constant

    def __init__(
        self,
        index_dir: Path = DEFAULT_INDEX_DIR,
        auto_load: bool = True,
        enable_bm25: bool = True,
    ):
        """
        Args:
            index_dir: Path to FAISS index directory
            auto_load: Whether to auto-load index on init
            enable_bm25: Whether to enable BM25 hybrid search
        """
        self.index_dir = Path(index_dir)
        self._index_builder = V6IndexBuilder(index_dir=self.index_dir)
        self._filter_engine = StructuredFilterEngine()
        self._ranker = PrecedentRanker()
        self._loaded = False

        # BM25 hybrid search components
        self._enable_bm25 = enable_bm25 and BM25_AVAILABLE
        self._bm25: Optional[BM25Okapi] = None
        self._bm25_corpus_keys: List[int] = []  # Index into _index_builder._metadata

        if not BM25_AVAILABLE and enable_bm25:
            logger.warning("BM25 requested but rank_bm25 not installed. Using FAISS-only.")

        if auto_load and self.index_dir.exists():
            try:
                self.load()
            except FileNotFoundError:
                logger.warning(f"Index not found at {index_dir}, will need to build first")

    def load(self):
        """Load the FAISS index and build BM25 index."""
        self._index_builder.load(self.index_dir)
        self._loaded = True
        logger.info(f"Loaded FAISS index with {self._index_builder._index.ntotal} vectors")

        # Build BM25 index from loaded metadata
        if self._enable_bm25:
            self._build_bm25_index()

    def _build_bm25_index(self):
        """Build BM25 index from loaded MUA records."""
        if not self._index_builder._metadata:
            logger.warning("No metadata available for BM25 index")
            return

        corpus = []
        self._bm25_corpus_keys = []

        for idx, record_dict in enumerate(self._index_builder._metadata):
            # Build searchable text from record fields
            text_parts = [
                record_dict.get("material_designation", ""),
                record_dict.get("specification", "") or "",
                record_dict.get("manufacturer", "") or "",
                record_dict.get("trade_name", "") or "",
                record_dict.get("application", "") or "",
                record_dict.get("mua_number", "") or "",
            ]

            # Add environment info
            env = record_dict.get("environment", {})
            if isinstance(env, dict):
                text_parts.append(env.get("raw_text", "") or "")
                text_parts.append(env.get("type", "") or "")

            # Add issue categories
            issues = record_dict.get("issues", [])
            if issues:
                text_parts.extend(issues)

            # Combine and tokenize
            text = " ".join(str(p) for p in text_parts if p).lower()
            tokens = self._tokenize_bm25(text)

            if tokens:
                corpus.append(tokens)
                self._bm25_corpus_keys.append(idx)

        if corpus:
            self._bm25 = BM25Okapi(corpus, k1=self.BM25_K1, b=self.BM25_B)
            logger.info(f"Built BM25 index with {len(corpus)} documents")
        else:
            logger.warning("No documents for BM25 index")

    def _tokenize_bm25(self, text: str) -> List[str]:
        """Tokenize text for BM25 with alphanumeric boundary splitting.

        Splits "6061-T6" into ["6061-t6", "6061", "t6"] for partial matching.
        """
        words = text.lower().split()
        tokens = []
        for word in words:
            tokens.append(word)
            # Split on letter/digit boundaries for partial matching
            parts = re.findall(r'[a-z]+|\d+', word)
            if len(parts) > 1:
                tokens.extend(parts)
        return tokens

    def is_loaded(self) -> bool:
        """Check if index is loaded."""
        return self._loaded

    def retrieve_by_material_env(
        self,
        material: str,
        environment: NormalizedEnvironment,
        top_k: int = 10,
        approved_only: bool = True,
        min_confidence: float = 0.5,
    ) -> List[PrecedentMatch]:
        """
        Material + Environment workflow.

        Args:
            material: Material designation (e.g., "6061-T6 Aluminum")
            environment: Normalized environment specification
            top_k: Number of results to return
            approved_only: Whether to filter to APPROVED only
            min_confidence: Minimum extraction confidence

        Returns:
            Ranked list of PrecedentMatch objects
        """
        if not self._loaded:
            raise RuntimeError("Index not loaded. Call load() first.")

        # Build query text
        query = self._build_query_text(material, environment)

        # FAISS search - get more than needed for filtering
        search_k = top_k * 3
        raw_results = self._index_builder.search(query, top_k=search_k)

        # Apply filters
        candidates = raw_results
        if approved_only:
            candidates = [
                (rec, score) for rec, score in candidates
                if rec.determination == "APPROVED"
            ]

        if min_confidence > 0:
            candidates = [
                (rec, score) for rec, score in candidates
                if rec.confidence >= min_confidence
            ]

        # Rank with match factors
        matches = self._ranker.rank(
            query_material=material,
            query_env=environment,
            query_issues=[],  # No specific issues
            candidates=candidates,
        )

        return matches[:top_k]

    def retrieve_by_gaps(
        self,
        material: str,
        gaps: List[IssueCategory],
        environment: NormalizedEnvironment,
        top_k: int = 10,
        approved_only: bool = True,
        min_confidence: float = 0.5,
    ) -> List[PrecedentMatch]:
        """
        Gap-driven workflow.

        Args:
            material: Material designation
            gaps: List of issue categories requiring mitigation
            environment: Normalized environment specification
            top_k: Number of results to return
            approved_only: Whether to filter to APPROVED only
            min_confidence: Minimum extraction confidence

        Returns:
            Ranked list of PrecedentMatch objects
        """
        if not self._loaded:
            raise RuntimeError("Index not loaded. Call load() first.")

        # Build query with gap emphasis
        gap_text = " ".join(gap.value for gap in gaps)
        query = self._build_query_text(material, environment, gap_text)

        # FAISS search
        search_k = top_k * 4  # More padding for issue filtering
        raw_results = self._index_builder.search(query, top_k=search_k)

        # Apply filters
        candidates = raw_results

        # Filter by issues (at least one gap must be addressed)
        if gaps:
            candidates = [
                (rec, score) for rec, score in candidates
                if set(gaps).intersection(set(rec.issues))
            ]

        if approved_only:
            candidates = [
                (rec, score) for rec, score in candidates
                if rec.determination == "APPROVED"
            ]

        if min_confidence > 0:
            candidates = [
                (rec, score) for rec, score in candidates
                if rec.confidence >= min_confidence
            ]

        # Rank with gap weighting
        matches = self._ranker.rank(
            query_material=material,
            query_env=environment,
            query_issues=gaps,
            candidates=candidates,
        )

        return matches[:top_k]

    def search_raw(
        self,
        query: str,
        top_k: int = 10,
    ) -> List[Tuple[CleanedMUARecord, float]]:
        """
        Raw semantic search without filtering/ranking.

        Args:
            query: Search query text
            top_k: Number of results

        Returns:
            List of (record, score) tuples
        """
        if not self._loaded:
            raise RuntimeError("Index not loaded. Call load() first.")

        return self._index_builder.search(query, top_k=top_k)

    def search_hybrid(
        self,
        query: str,
        top_k: int = 10,
        bm25_candidates: int = 50,
        faiss_candidates: int = 50,
    ) -> List[Tuple[CleanedMUARecord, float, int, int]]:
        """
        Hybrid BM25 + FAISS search with RRF fusion.

        Args:
            query: Search query text
            top_k: Number of final results
            bm25_candidates: BM25 results to consider
            faiss_candidates: FAISS results to consider

        Returns:
            List of (record, rrf_score, bm25_rank, faiss_rank) tuples
            Rank is None if result came from only one retriever.
        """
        if not self._loaded:
            raise RuntimeError("Index not loaded. Call load() first.")

        # Phase 1: FAISS semantic search
        faiss_results = self._index_builder.search(query, top_k=faiss_candidates)
        faiss_ranked = [(idx, rank + 1) for rank, (rec, score) in enumerate(faiss_results)
                        for idx in range(len(self._index_builder._metadata))
                        if self._index_builder._metadata[idx].get("mua_number") == rec.mua_number]

        # Build FAISS rank lookup by metadata index
        faiss_by_idx = {}
        for rank, (rec, score) in enumerate(faiss_results, 1):
            for idx, meta in enumerate(self._index_builder._metadata):
                if meta.get("mua_number") == rec.mua_number:
                    faiss_by_idx[idx] = rank
                    break

        # Phase 2: BM25 lexical search
        bm25_by_idx = {}
        if self._bm25 is not None:
            tokens = self._tokenize_bm25(query)
            scores = self._bm25.get_scores(tokens)

            # Get top indices from BM25
            top_bm25_indices = np.argsort(scores)[::-1][:bm25_candidates]

            for rank, corpus_idx in enumerate(top_bm25_indices, 1):
                if scores[corpus_idx] > 0:
                    metadata_idx = self._bm25_corpus_keys[corpus_idx]
                    bm25_by_idx[metadata_idx] = rank

        # Phase 3: RRF Fusion
        all_indices = set(faiss_by_idx.keys()) | set(bm25_by_idx.keys())
        rrf_scores = {}

        for idx in all_indices:
            rrf = 0.0
            if idx in faiss_by_idx:
                rrf += 1.0 / (self.RRF_K + faiss_by_idx[idx])
            if idx in bm25_by_idx:
                rrf += 1.0 / (self.RRF_K + bm25_by_idx[idx])
            rrf_scores[idx] = rrf

        # Sort by RRF score
        sorted_indices = sorted(rrf_scores.keys(), key=lambda i: rrf_scores[i], reverse=True)

        # Build results
        results = []
        for idx in sorted_indices[:top_k]:
            record_dict = self._index_builder._metadata[idx]
            record = CleanedMUARecord(**record_dict)
            rrf_score = rrf_scores[idx]
            bm25_rank = bm25_by_idx.get(idx)
            faiss_rank = faiss_by_idx.get(idx)
            results.append((record, rrf_score, bm25_rank, faiss_rank))

        logger.debug(
            f"Hybrid search '{query[:50]}...': FAISS={len(faiss_by_idx)}, "
            f"BM25={len(bm25_by_idx)}, fused={len(results)}"
        )

        return results

    def retrieve_by_material_env_hybrid(
        self,
        material: str,
        environment: NormalizedEnvironment,
        top_k: int = 10,
        approved_only: bool = True,
        min_confidence: float = 0.5,
        bm25_weight: float = 0.5,
    ) -> List[PrecedentMatch]:
        """
        Hybrid search with material + environment workflow.

        Uses BM25 + FAISS + RRF fusion, then applies structured filtering and ranking.

        Args:
            material: Material designation (e.g., "6061-T6 Aluminum")
            environment: Normalized environment specification
            top_k: Number of results to return
            approved_only: Whether to filter to APPROVED only
            min_confidence: Minimum extraction confidence
            bm25_weight: Weight for BM25 contribution (0-1, higher = more lexical)

        Returns:
            Ranked list of PrecedentMatch objects
        """
        if not self._loaded:
            raise RuntimeError("Index not loaded. Call load() first.")

        # Build query
        query = self._build_query_text(material, environment)

        # Get more candidates for filtering
        search_k = top_k * 4

        # Use hybrid search if BM25 available
        if self._bm25 is not None:
            hybrid_results = self.search_hybrid(
                query, top_k=search_k,
                bm25_candidates=search_k * 2,
                faiss_candidates=search_k * 2,
            )

            # Convert to candidates format (record, score)
            candidates = [(rec, rrf_score) for rec, rrf_score, _, _ in hybrid_results]
        else:
            # Fallback to FAISS-only
            raw_results = self._index_builder.search(query, top_k=search_k)
            candidates = raw_results

        # Apply filters
        if approved_only:
            candidates = [
                (rec, score) for rec, score in candidates
                if rec.determination == "APPROVED"
            ]

        if min_confidence > 0:
            candidates = [
                (rec, score) for rec, score in candidates
                if rec.confidence >= min_confidence
            ]

        # Rank with match factors
        matches = self._ranker.rank(
            query_material=material,
            query_env=environment,
            query_issues=[],
            candidates=candidates,
        )

        return matches[:top_k]

    def _build_query_text(
        self,
        material: str,
        environment: NormalizedEnvironment,
        additional: str = "",
    ) -> str:
        """Build query text for FAISS search."""
        parts = [material]

        # Add environment info
        if environment.raw_text:
            parts.append(environment.raw_text)
        else:
            parts.append(environment.type.value)
            if environment.o2_percent:
                parts.append(f"{environment.o2_percent}% O2")
            if environment.pressure_psia:
                parts.append(f"{environment.pressure_psia} PSIA")

        if additional:
            parts.append(additional)

        return " | ".join(parts)

    def get_stats(self) -> Dict:
        """Get retriever statistics."""
        if not self._loaded:
            return {"status": "not_loaded"}

        return self._index_builder.get_stats()


# =============================================================================
# Convenience Functions
# =============================================================================

def get_retriever(index_dir: Path = DEFAULT_INDEX_DIR) -> V6PrecedentRetriever:
    """Get a loaded retriever instance."""
    retriever = V6PrecedentRetriever(index_dir=index_dir, auto_load=True)
    if not retriever.is_loaded():
        raise FileNotFoundError(f"Index not found at {index_dir}. Run index_builder first.")
    return retriever
