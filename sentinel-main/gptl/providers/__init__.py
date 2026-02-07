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
GPTL Providers - Vector Store and Feature Cache Implementations
================================================================

Provider protocols and implementations for SENTINEL.

Three distinct capabilities - do not conflate:
1. VectorStoreProvider: retrieval (vector search)
2. ContentProvider: content access (text retrieval)
3. FeatureCache: feature access (DocFeatures)

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI
"""

from gptl.providers.base import (
    VectorStoreProvider,
    ContentProvider,
    FeatureCache,
    SearchCandidate,
    StoredChunk,
)
from gptl.providers.faiss_provider import FaissProvider, FAISS_AVAILABLE
from gptl.providers.feature_cache import JsonFeatureCache

__all__ = [
    # Protocols
    "VectorStoreProvider",
    "ContentProvider",
    "FeatureCache",
    # Data Classes
    "SearchCandidate",
    "StoredChunk",
    # Implementations
    "FaissProvider",
    "JsonFeatureCache",
    # Flags
    "FAISS_AVAILABLE",
]
