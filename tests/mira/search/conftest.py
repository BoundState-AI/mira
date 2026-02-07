#!/usr/bin/env python3
"""
Module: Conftest
Purpose: Pytest Fixtures for Search Module Tests

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

import pytest
import numpy as np
import sys
from typing import Dict, List, Any, Optional
from unittest.mock import MagicMock, patch
from dataclasses import dataclass

sys.path.insert(0, r"C:\BoundState")


# =============================================================================
# Sample Materials Data
# =============================================================================

SAMPLE_MATERIALS = {
    "10001": {
        "designation": "316L Stainless Steel",
        "material_code": "10001",
        "matl_materialcode": "10001",
        "composition_key": "Fe-Cr-Ni-Mo",
        "specification": "AMS5648",
        "o2_rating": "A",
        "h2_rating": "B",
        "flamm_rating": "1",
        "corr_rating": "1",
        "scc_rating": "1",
        "tvs_rating": "2",
        "tox_rating": "1",
    },
    "10002": {
        "designation": "Inconel 718",
        "material_code": "10002",
        "matl_materialcode": "10002",
        "composition_key": "Ni-Cr-Fe-Mo-Nb",
        "specification": "AMS5662",
        "o2_rating": "A",
        "h2_rating": "A",
        "flamm_rating": "1",
        "corr_rating": "1",
        "scc_rating": "1",
        "tvs_rating": "1",
        "tox_rating": "1",
    },
    "10003": {
        "designation": "Ti-6Al-4V Titanium",
        "material_code": "10003",
        "matl_materialcode": "10003",
        "composition_key": "Ti-Al-V",
        "specification": "AMS4911",
        "o2_rating": "C",
        "h2_rating": "B",
        "flamm_rating": "2",
        "corr_rating": "1",
        "scc_rating": "2",
        "tvs_rating": "2",
        "tox_rating": "1",
    },
    "10004": {
        "designation": "A-286 Stainless Steel",
        "material_code": "10004",
        "matl_materialcode": "10004",
        "composition_key": "Fe-Ni-Cr-Ti",
        "specification": "AMS5731",
        "o2_rating": "A",
        "h2_rating": "A",
        "flamm_rating": "1",
        "corr_rating": "1",
        "scc_rating": "1",
        "tvs_rating": "1",
        "tox_rating": "1",
    },
    "10005": {
        "designation": "7075-T6 Aluminum",
        "material_code": "10005",
        "matl_materialcode": "10005",
        "composition_key": "Al-Zn-Mg-Cu",
        "specification": "AMS4045",
        "o2_rating": "B",
        "h2_rating": "A",
        "flamm_rating": "2",
        "corr_rating": "2",
        "scc_rating": "2",
        "tvs_rating": "2",
        "tox_rating": "1",
    },
    "10006": {
        "designation": "Monel 400",
        "material_code": "10006",
        "matl_materialcode": "10006",
        "composition_key": "Ni-Cu",
        "specification": "AMS4675",
        "o2_rating": "A",
        "h2_rating": "A",
        "flamm_rating": "1",
        "corr_rating": "1",
        "scc_rating": "1",
        "tvs_rating": "1",
        "tox_rating": "1",
    },
    "10007": {
        "designation": "304 Stainless Steel",
        "material_code": "10007",
        "matl_materialcode": "10007",
        "composition_key": "Fe-Cr-Ni",
        "specification": "ASTM A276",
        "o2_rating": "A",
        "h2_rating": "B",
        "flamm_rating": "1",
        "corr_rating": "1",
        "scc_rating": "2",
        "tvs_rating": "2",
        "tox_rating": "1",
    },
    "10008": {
        "designation": "6061-T6 Aluminum",
        "material_code": "10008",
        "matl_materialcode": "10008",
        "composition_key": "Al-Mg-Si",
        "specification": "AMS4027",
        "o2_rating": "B",
        "h2_rating": "A",
        "flamm_rating": "2",
        "corr_rating": "2",
        "scc_rating": "1",
        "tvs_rating": "2",
        "tox_rating": "1",
    },
    "10009": {
        "designation": "Hastelloy C-276",
        "material_code": "10009",
        "matl_materialcode": "10009",
        "composition_key": "Ni-Mo-Cr-W",
        "specification": "AMS5625",
        "o2_rating": "A",
        "h2_rating": "A",
        "flamm_rating": "1",
        "corr_rating": "1",
        "scc_rating": "1",
        "tvs_rating": "1",
        "tox_rating": "1",
    },
    "10010": {
        "designation": "CRES 321 Stainless Steel",
        "material_code": "10010",
        "matl_materialcode": "10010",
        "composition_key": "Fe-Cr-Ni-Ti",
        "specification": "AMS5570",
        "o2_rating": "A",
        "h2_rating": "B",
        "flamm_rating": "1",
        "corr_rating": "1",
        "scc_rating": "1",
        "tvs_rating": "2",
        "tox_rating": "1",
    },
}


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def sample_materials_lookup() -> Dict[str, Dict]:
    """Sample materials lookup dictionary."""
    return SAMPLE_MATERIALS.copy()


@pytest.fixture
def mock_faiss_index():
    """Mock FAISS index for testing."""
    mock_index = MagicMock()
    # Return all 10 materials with varying distances
    distances = np.array([[0.1, 0.15, 0.2, 0.25, 0.3, 0.35, 0.4, 0.45, 0.5, 0.55]])
    indices = np.array([[0, 1, 2, 3, 4, 5, 6, 7, 8, 9]])
    mock_index.search.return_value = (distances, indices)
    return mock_index


@pytest.fixture
def mock_embedding_model():
    """Mock sentence transformer embedding model."""
    mock_model = MagicMock()
    # Return consistent 384-dim embedding
    mock_model.encode.return_value = np.random.rand(1, 384).astype('float32')
    return mock_model


@pytest.fixture
def index_to_key(sample_materials_lookup) -> Dict[int, str]:
    """FAISS index position to material key mapping."""
    return {i: k for i, k in enumerate(sample_materials_lookup.keys())}


@pytest.fixture
def hybrid_search(sample_materials_lookup, mock_faiss_index, mock_embedding_model, index_to_key):
    """Create MIRAHybridSearch instance with all mocks."""
    from mira.search.hybrid_search import MIRAHybridSearch

    return MIRAHybridSearch(
        faiss_index=mock_faiss_index,
        materials_lookup=sample_materials_lookup,
        embedding_model=mock_embedding_model,
        index_to_key=index_to_key,
        rrf_k=60,
    )


@pytest.fixture
def patched_search_engine(hybrid_search):
    """Create a mock engine with hybrid search patched in."""
    from mira.search.hybrid_search import patch_semantic_search_engine

    mock_engine = MagicMock()
    patch_semantic_search_engine(mock_engine, hybrid_search)
    return mock_engine


@pytest.fixture
def mock_api_results() -> List[Dict]:
    """Mock API results in the format returned by patched engine."""
    return [
        {
            "material": {
                "material_id": "10001",
                "name": "316L Stainless Steel",
                "designation": "316L Stainless Steel",
                "material_code": "10001",
                "composition": "Fe-Cr-Ni-Mo",
            },
            "original_material": {
                "material_key": "10001",
                "material_code": "10001",
                "matl_designation": "316L Stainless Steel",
                "designation": "316L Stainless Steel",
                "o2_rating": "A",
                "h2_rating": "B",
                "flamm_rating": "1",
                "corr_rating": "1",
                "scc_rating": "1",
                "tvs_rating": "2",
                "tox_rating": "1",
            },
            "similarity_score": 0.0328,
            "bm25_rank": 1,
            "faiss_rank": 2,
        },
        {
            "material": {
                "material_id": "10002",
                "name": "Inconel 718",
                "designation": "Inconel 718",
                "material_code": "10002",
                "composition": "Ni-Cr-Fe-Mo-Nb",
            },
            "original_material": {
                "material_key": "10002",
                "material_code": "10002",
                "matl_designation": "Inconel 718",
                "designation": "Inconel 718",
                "o2_rating": "A",
                "h2_rating": "A",
                "flamm_rating": "1",
            },
            "similarity_score": 0.0164,
            "bm25_rank": None,
            "faiss_rank": 1,
        },
    ]


# =============================================================================
# Markers
# =============================================================================

def pytest_configure(config):
    """Configure custom pytest markers."""
    config.addinivalue_line(
        "markers", "integration: marks tests as integration tests (may require external resources)"
    )
    config.addinivalue_line(
        "markers", "slow: marks tests as slow (deselect with '-m \"not slow\"')"
    )
    config.addinivalue_line(
        "markers", "golden: marks tests as golden query tests"
    )
