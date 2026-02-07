#!/usr/bin/env python3
"""
Module: Clustering
Purpose: [Automatically migrated - needs manual review]

BoundState AI 2025
Version: 1.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Fran OpenAI 5 <noreply@openai.com>
Co-Authored-By: Grok 4.0 <noreply@x.ai>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: SWE-013, NASA-STD-6016
Safety Critical: True
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from mira.precedent_engine.models.config import EngineConfig
    from mira.precedent_engine.models.enriched import EnrichedMUA


def assign_precedent_families(
    muas: list["EnrichedMUA"],
    embeddings: np.ndarray,
    min_cluster_size: int = 10,
    min_samples: int | None = None,
) -> dict[str, int]:
    """
    Assign precedent families to MUAs using HDBSCAN clustering.

    Precedent families group similar MUAs together, which helps with:
    - Efficient retrieval (search within families)
    - Diversity assessment (ensure coverage across families)
    - Trend analysis (track changes within families)

    Args:
        muas: List of EnrichedMUA records
        embeddings: Embedding vectors for the MUAs (n_muas x embed_dim)
        min_cluster_size: Minimum cluster size for HDBSCAN
        min_samples: Min samples for core points (defaults to min_cluster_size)

    Returns:
        Dict mapping contract_id to cluster label (-1 for noise)
    """
    if len(muas) < min_cluster_size:
        # Not enough MUAs to cluster
        return {mua.contract_id: -1 for mua in muas}

    try:
        import hdbscan
    except ImportError:
        # HDBSCAN not installed, return all as unclustered
        return {mua.contract_id: -1 for mua in muas}

    min_samples = min_samples or min_cluster_size

    # Run HDBSCAN
    clusterer = hdbscan.HDBSCAN(
        min_cluster_size=min_cluster_size,
        min_samples=min_samples,
        metric="euclidean",
        cluster_selection_method="eom",  # Excess of Mass
    )

    labels = clusterer.fit_predict(embeddings)

    # Build result dict
    result = {}
    for i, mua in enumerate(muas):
        result[mua.contract_id] = int(labels[i])

    return result


def cluster_statistics(labels: dict[str, int]) -> dict:
    """
    Compute statistics about clustering results.

    Args:
        labels: Dict mapping contract_id to cluster label

    Returns:
        Dict with cluster statistics
    """
    label_values = list(labels.values())

    n_clusters = len(set(label_values) - {-1})  # Exclude noise
    n_noise = sum(1 for l in label_values if l == -1)

    # Cluster sizes
    cluster_sizes = {}
    for label in label_values:
        if label != -1:
            cluster_sizes[label] = cluster_sizes.get(label, 0) + 1

    return {
        "n_clusters": n_clusters,
        "n_noise": n_noise,
        "n_total": len(labels),
        "noise_fraction": n_noise / len(labels) if labels else 0.0,
        "cluster_sizes": cluster_sizes,
        "avg_cluster_size": (
            sum(cluster_sizes.values()) / n_clusters if n_clusters > 0 else 0
        ),
        "max_cluster_size": max(cluster_sizes.values()) if cluster_sizes else 0,
        "min_cluster_size": min(cluster_sizes.values()) if cluster_sizes else 0,
    }


def update_muas_with_families(
    muas: list["EnrichedMUA"],
    family_assignments: dict[str, int],
) -> list["EnrichedMUA"]:
    """
    Update MUA records with their precedent family assignments.

    Note: This creates new EnrichedMUA instances since they may be frozen.

    Args:
        muas: List of EnrichedMUA records
        family_assignments: Dict mapping contract_id to family label

    Returns:
        New list of EnrichedMUA with precedent_family field set
    """
    result = []
    for mua in muas:
        family = family_assignments.get(mua.contract_id, -1)
        # Create updated MUA with family assignment
        updated = mua.model_copy(update={"precedent_family": family if family != -1 else None})
        result.append(updated)
    return result
