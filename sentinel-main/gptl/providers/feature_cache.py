# Copyright 2025 BoundStateAI
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
DocFeatures cache implementation.

File-based for MVP. Switch to Postgres JSONB for production.

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Optional, Any
import logging

from gptl.schema import DocFeatures
from gptl.providers.base import FeatureCache

__safety_critical__: bool = True

logger = logging.getLogger(__name__)


class JsonFeatureCache(FeatureCache):
    """
    File-based DocFeatures cache.

    For MVP. Switch to Postgres JSONB for production scale.

    Features are pre-computed at ingestion time (L0).
    Query-time access must be O(1).
    """

    def __init__(self, cache_path: str = "data/features.json"):
        self.cache_path = Path(cache_path)
        self.cache: Dict[str, dict] = {}
        self._load()

    def _load(self) -> None:
        """Load cache from disk."""
        if self.cache_path.exists():
            try:
                with open(self.cache_path, 'r', encoding='utf-8') as f:
                    self.cache = json.load(f)
                logger.info(f"Loaded {len(self.cache)} features from cache")
            except json.JSONDecodeError as e:
                logger.error(f"Failed to load feature cache: {e}")
                self.cache = {}

    def _save(self) -> None:
        """Persist cache to disk."""
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.cache_path, 'w', encoding='utf-8') as f:
            json.dump(self.cache, f, indent=2, default=str)

    def get_features(self, chunk_id: str) -> Optional[DocFeatures]:
        """Get pre-computed features for a chunk. O(1)."""
        data = self.cache.get(chunk_id)
        if data:
            try:
                return DocFeatures.model_validate(data)
            except Exception as e:
                logger.error(f"Failed to parse features for {chunk_id}: {e}")
                return None
        return None

    def put_features(self, chunk_id: str, features: DocFeatures) -> None:
        """Store features for a chunk."""
        self.cache[chunk_id] = features.model_dump(mode='json')
        self._save()

    def bulk_get(self, chunk_ids: List[str]) -> Dict[str, DocFeatures]:
        """Bulk retrieve features. More efficient than individual calls."""
        results = {}
        for chunk_id in chunk_ids:
            features = self.get_features(chunk_id)
            if features:
                results[chunk_id] = features
        return results

    def bulk_put(self, features_map: Dict[str, DocFeatures]) -> None:
        """Bulk store features. Single save at end."""
        for chunk_id, features in features_map.items():
            self.cache[chunk_id] = features.model_dump(mode='json')
        self._save()
        logger.info(f"Stored {len(features_map)} features")

    def get_stats(self) -> Dict[str, Any]:
        """Return cache statistics."""
        return {
            "total_features": len(self.cache),
            "cache_path": str(self.cache_path),
            "cache_size_bytes": self.cache_path.stat().st_size if self.cache_path.exists() else 0,
        }

    def clear(self) -> None:
        """Clear all cached features (for testing)."""
        self.cache = {}
        if self.cache_path.exists():
            self.cache_path.unlink()


__all__ = ["JsonFeatureCache"]
