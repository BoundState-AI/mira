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
Dependency injection for SENTINEL API.

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI
"""

from __future__ import annotations

import os
from functools import lru_cache
from typing import Optional

from pydantic import Field
from pydantic_settings import BaseSettings

from gptl.engine import GPTLEngine
from gptl.config_loader import load_domain_pack
from gptl.providers.faiss_provider import FaissProvider, FAISS_AVAILABLE
from gptl.providers.feature_cache import JsonFeatureCache

__safety_critical__: bool = True


class Settings(BaseSettings):
    """Application settings from environment."""

    # API
    anthropic_api_key: str = Field(default="", alias="ANTHROPIC_API_KEY")

    # Auth
    auth_mode: str = Field(default="open_demo", alias="SENTINEL_AUTH_MODE")
    api_keys: str = Field(default="", alias="SENTINEL_API_KEYS")
    rate_limit_rps: int = Field(default=10, alias="SENTINEL_RATE_LIMIT_RPS")

    # Storage
    faiss_path: str = Field(default="data/sentinel.faiss", alias="SENTINEL_FAISS_PATH")
    store_path: str = Field(default="data/sentinel.store", alias="SENTINEL_STORE_PATH")
    features_path: str = Field(default="data/features.json", alias="SENTINEL_FEATURES_PATH")
    corpus_snapshot_id: str = Field(default="demo-v1", alias="SENTINEL_CORPUS_SNAPSHOT_ID")

    # CORS
    cors_origins: str = Field(default="*", alias="SENTINEL_CORS_ORIGINS")

    # Domain
    default_domain: str = Field(default="sentinel-demo", alias="SENTINEL_DEFAULT_DOMAIN")

    # GPU
    use_gpu: bool = Field(default=False, alias="SENTINEL_USE_GPU")

    model_config = {
        "env_file": ".env",
        "extra": "ignore",
        "populate_by_name": True,
    }


@lru_cache()
def get_settings() -> Settings:
    """Get cached settings."""
    return Settings()


# Global providers (initialized on startup)
_vector_store: Optional[FaissProvider] = None
_feature_cache: Optional[JsonFeatureCache] = None


def init_providers(settings: Settings) -> None:
    """Initialize providers on startup."""
    global _vector_store, _feature_cache

    if FAISS_AVAILABLE:
        _vector_store = FaissProvider(
            index_path=settings.faiss_path,
            store_path=settings.store_path,
            use_gpu=settings.use_gpu,
        )
    else:
        _vector_store = None

    _feature_cache = JsonFeatureCache(
        cache_path=settings.features_path,
    )


def get_vector_store() -> FaissProvider:
    """Get vector store provider."""
    if _vector_store is None:
        raise RuntimeError("Providers not initialized or FAISS not available")
    return _vector_store


def get_feature_cache() -> JsonFeatureCache:
    """Get feature cache provider."""
    if _feature_cache is None:
        raise RuntimeError("Providers not initialized")
    return _feature_cache


def get_engine(domain_id: str) -> GPTLEngine:
    """Get GPTL engine for a domain."""
    domain_pack = load_domain_pack(domain_id)
    return GPTLEngine(domain_pack=domain_pack)


__all__ = [
    "Settings",
    "get_settings",
    "init_providers",
    "get_vector_store",
    "get_feature_cache",
    "get_engine",
]
