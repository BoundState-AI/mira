#!/usr/bin/env python3
"""
Module: Mua Search
Purpose: A single MUA precedent from the search.

BoundState AI 2025
Version: 1.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Fran OpenAI 5 <noreply@openai.com>
Co-Authored-By: Grok 4.0 <noreply@x.ai>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: SWE-013, NASA-STD-8739.8B
Safety Critical: True
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

LOGGER = logging.getLogger(__name__)

# Optional dependencies
try:
    import faiss
    import numpy as np
    FAISS_AVAILABLE = True
except ImportError:
    FAISS_AVAILABLE = False

try:
    from sentence_transformers import SentenceTransformer
    TRANSFORMERS_AVAILABLE = True
except ImportError:
    TRANSFORMERS_AVAILABLE = False


# Default paths
DEFAULT_INDEX_DIR = Path(__file__).parent.parent / "databases" / "mira_v2_faiss"


@dataclass
class MUAPrecedent:
    """A single MUA precedent from the search."""
    mua_id: str
    material_name: str
    environment: Optional[str]
    determination: str  # APPROVED, CONDITIONAL, DENIED
    summary: str
    score: float  # Semantic similarity score (0-1)
    pressure_max_psi: Optional[float] = None
    temp_min_c: Optional[float] = None
    temp_max_c: Optional[float] = None

    def is_approved(self) -> bool:
        """Check if MUA was approved."""
        return self.determination.upper() in ("APPROVED", "CONDITIONAL")

    def is_denied(self) -> bool:
        """Check if MUA was denied."""
        return self.determination.upper() == "DENIED"


class MUASearch:
    """Search MUA precedents via FAISS semantic similarity.

    Uses the MUA FAISS index (14 MB, 9,734 entries) to find relevant
    historic Material Usage Agreements.
    """

    # Confidence thresholds
    HIGH_CONFIDENCE = 0.68
    MEDIUM_CONFIDENCE = 0.60
    LOW_CONFIDENCE = 0.55

    def __init__(self, index_dir: Optional[Path] = None):
        """Initialize MUA search.

        Args:
            index_dir: Path to FAISS indexes. Defaults to databases/mira_v2_faiss/
        """
        self.index_dir = Path(index_dir) if index_dir else DEFAULT_INDEX_DIR
        self._index = None
        self._metadata = None
        self._encoder = None
        self._loaded = False

    def _ensure_loaded(self) -> bool:
        """Load FAISS index and metadata if not already loaded."""
        if self._loaded:
            return self._index is not None

        if not FAISS_AVAILABLE:
            LOGGER.warning("FAISS not available - MUA search disabled")
            self._loaded = True
            return False

        if not TRANSFORMERS_AVAILABLE:
            LOGGER.warning("sentence-transformers not available - MUA search disabled")
            self._loaded = True
            return False

        index_path = self.index_dir / "mua_faiss_index.bin"
        metadata_path = self.index_dir / "mua_index_metadata.json"

        if not index_path.exists():
            LOGGER.warning(f"MUA index not found: {index_path}")
            self._loaded = True
            return False

        try:
            # Load FAISS index
            self._index = faiss.read_index(str(index_path))
            LOGGER.info(f"Loaded MUA index: {self._index.ntotal} entries")

            # Load metadata
            if metadata_path.exists():
                with open(metadata_path, "r", encoding="utf-8") as f:
                    self._metadata = json.load(f)
                LOGGER.info(f"Loaded MUA metadata: {len(self._metadata)} entries")
            else:
                LOGGER.warning(f"MUA metadata not found: {metadata_path}")
                self._metadata = []

            # Load encoder
            self._encoder = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")

            self._loaded = True
            return True

        except Exception as e:
            LOGGER.error(f"Failed to load MUA index: {e}")
            self._loaded = True
            return False

    def find_precedents(
        self,
        material: str,
        environment: Optional[str] = None,
        top_k: int = 10,
        min_score: float = 0.50,
    ) -> list[MUAPrecedent]:
        """Find MUA precedents for a material.

        Args:
            material: Material name to search for
            environment: Optional environment filter (oxygen, hydrogen, etc.)
            top_k: Maximum number of results
            min_score: Minimum similarity score threshold

        Returns:
            List of MUAPrecedent objects sorted by relevance.
        """
        if not self._ensure_loaded():
            return []

        # Build query text
        query_text = material
        if environment:
            query_text = f"{material} {environment} service"

        try:
            # Encode query
            query_vec = self._encoder.encode([query_text], convert_to_numpy=True)
            query_vec = query_vec.astype("float32")

            # Search FAISS index
            distances, indices = self._index.search(query_vec, top_k * 2)  # Over-fetch for filtering

            results = []
            for i, (dist, idx) in enumerate(zip(distances[0], indices[0])):
                if idx < 0 or idx >= len(self._metadata):
                    continue

                # Convert L2 distance to similarity score (0-1)
                # FAISS uses L2 distance, so smaller is better
                # Approximate conversion: score = 1 / (1 + dist)
                score = 1.0 / (1.0 + float(dist))

                if score < min_score:
                    continue

                meta = self._metadata[idx]

                # Apply environment filter if specified
                if environment:
                    meta_env = meta.get("environment", "").lower()
                    if environment.lower() not in meta_env and meta_env not in environment.lower():
                        # Partial match allowed (e.g., "h2" in "hydrogen")
                        if not any(kw in meta_env for kw in ["hydrogen", "h2", "gh2", "lh2"]):
                            if environment.lower() in ["hydrogen", "h2"]:
                                continue

                precedent = MUAPrecedent(
                    mua_id=meta.get("mua_number", f"MUA-{idx}"),
                    material_name=meta.get("material_name", material),
                    environment=meta.get("environment"),
                    determination=meta.get("determination", "UNKNOWN"),
                    summary=meta.get("summary", meta.get("text", "")[:200]),
                    score=score,
                    pressure_max_psi=meta.get("pressure_psi_max"),
                    temp_min_c=meta.get("temp_c_min"),
                    temp_max_c=meta.get("temp_c_max"),
                )
                results.append(precedent)

                if len(results) >= top_k:
                    break

            return results

        except Exception as e:
            LOGGER.error(f"MUA search failed: {e}")
            return []

    def find_hydrogen_precedents(
        self,
        material: str,
        top_k: int = 5,
    ) -> list[MUAPrecedent]:
        """Convenience method for hydrogen-specific precedent search.

        Args:
            material: Material name
            top_k: Maximum results

        Returns:
            List of hydrogen-relevant MUA precedents.
        """
        return self.find_precedents(
            material=material,
            environment="hydrogen",
            top_k=top_k,
            min_score=self.MEDIUM_CONFIDENCE,
        )

    def has_approved_precedent(
        self,
        material: str,
        environment: str = "hydrogen",
        min_score: float = 0.65,
    ) -> tuple[bool, Optional[MUAPrecedent]]:
        """Check if material has an approved MUA precedent.

        Args:
            material: Material name
            environment: Environment type
            min_score: Minimum confidence threshold

        Returns:
            Tuple of (has_approved, best_precedent)
        """
        precedents = self.find_precedents(
            material=material,
            environment=environment,
            top_k=5,
            min_score=min_score,
        )

        for p in precedents:
            if p.is_approved():
                return True, p

        return False, precedents[0] if precedents else None

    def has_denied_precedent(
        self,
        material: str,
        environment: str = "hydrogen",
        min_score: float = 0.65,
    ) -> tuple[bool, Optional[MUAPrecedent]]:
        """Check if material has a denied MUA precedent.

        SAFETY CRITICAL: Denied precedents should trigger PROHIBITED verdict.

        Args:
            material: Material name
            environment: Environment type
            min_score: Minimum confidence threshold

        Returns:
            Tuple of (has_denied, denied_precedent)
        """
        precedents = self.find_precedents(
            material=material,
            environment=environment,
            top_k=5,
            min_score=min_score,
        )

        for p in precedents:
            if p.is_denied():
                return True, p

        return False, None

    def get_stats(self) -> dict:
        """Get index statistics."""
        self._ensure_loaded()

        return {
            "available": self._index is not None,
            "total_entries": self._index.ntotal if self._index else 0,
            "metadata_entries": len(self._metadata) if self._metadata else 0,
            "index_path": str(self.index_dir / "mua_faiss_index.bin"),
        }
