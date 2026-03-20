#!/usr/bin/env python3
"""
Module: Retrieval
Purpose: FAISS-backed retrieval utilities for MUA generation.

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

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

try:  # pragma: no cover - heavy deps
    import faiss  # type: ignore
except Exception:  # pragma: no cover - allow graceful fallback
    faiss = None  # type: ignore

try:  # pragma: no cover - heavy deps
    from sentence_transformers import SentenceTransformer  # type: ignore
except Exception:  # pragma: no cover
    SentenceTransformer = None  # type: ignore

from .models import MIULRef, Mitigation

import uuid

try:
    from .historic_retrieval import HistoricMUARetriever, get_historic_retriever
except ImportError:
    HistoricMUARetriever = None  # type: ignore
    get_historic_retriever = None  # type: ignore

LOGGER = logging.getLogger(__name__)

DEFAULT_INDEX_DIR = Path(os.getenv("MUA_STANDARDS_INDEX_DIR", "mira/databases/mua_standards"))
DEFAULT_MODEL_NAME = os.getenv("MUA_STANDARDS_MODEL", "all-MiniLM-L6-v2")

RATING_TO_CLAUSES: Dict[str, Set[str]] = {
    "FLAMM": {"\u00A74.2.1.1", "\u00A74.2.1.4"},
    "SCC": {"\u00A74.2.6.3"},
    "CORR": {"\u00A74.2.6.3"},
    "TVS": {"\u00A74.2.3.6"},
    "TOX": {"\u00A74.2.1.2"},
    "FS": {"\u00A74.2.1.3"},
}

RATING_TO_HAZARD: Dict[str, str] = {
    "FLAMM": "miul:FLAMM",
    "SCC": "miul:SCC",
    "CORR": "miul:CORR",
    "TVS": "miul:TVS",
    "TOX": "miul:TOX",
    "FS": "miul:FS",
}

SOURCE_PRIORITY: Dict[str, float] = {
    "NASA-STD-6016": 0.15,
    "JSC-27301F": 0.08,
    "KSC-KTI-5210C": 0.07,
    "MSFC-SCC": 0.07,
    "SSC-LOX": 0.07,
}


def build_retrieval_query(miul: MIULRef, gaps: Dict[str, str]) -> str:
    """Build semantic search query from MIUL context and gaps."""
    parts: List[str] = []

    if miul.material_designator:
        parts.append(miul.material_designator)
    if miul.application_context:
        parts.append(miul.application_context)

    fluid = (miul.environment.fluid_medium or "").strip()
    if fluid:
        parts.append(fluid)
    if miul.environment.oxygen_pct and miul.environment.oxygen_pct >= 23.5:
        parts.append("oxygen enriched environment")

    for test_class, rating in gaps.items():
        parts.append(f"{test_class.lower()} rating {rating}")

    return " ".join(parts)


def expected_clause_ids(gaps: Dict[str, str]) -> Set[str]:
    clause_ids: Set[str] = set()
    for test_class in gaps:
        clause_ids.update(RATING_TO_CLAUSES.get(test_class, set()))
    return clause_ids


def expected_hazard_tags(miul: MIULRef, gaps: Dict[str, str]) -> Set[str]:
    hazard_tags: Set[str] = set()
    for test_class in gaps:
        tag = RATING_TO_HAZARD.get(test_class)
        if tag:
            hazard_tags.add(tag)
    fluid = (miul.environment.fluid_medium or "").upper()
    if fluid in {"GOX", "LOX", "OXYGEN"} or (miul.environment.oxygen_pct and miul.environment.oxygen_pct >= 23.5):
        hazard_tags.add("hazard:oxygen")
    return hazard_tags


def _is_reference_table(text: str) -> bool:
    """
    Detect if text is a reference table (data dump) rather than actionable guidance.

    Reference tables contain lists of materials/alloys/conditions but no actual
    mitigation guidance. They should be filtered out.
    """
    text_lower = text.lower()

    # Strong indicators this is a reference table, not guidance
    reference_table_patterns = [
        "table i",  # "TABLE I", "TABLE II", "TABLE III"
        "table ii",
        "table iii",
        "alloys with high resistance",
        "alloys with moderate resistance",
        "alloys with low resistance",
        "wrought cast",  # Material form columns
        "alloy condition temper",  # Table headers
    ]

    # Count how many reference table indicators are present
    indicator_count = sum(1 for pattern in reference_table_patterns if pattern in text_lower)

    # If 2+ indicators, it's likely a reference table
    if indicator_count >= 2:
        return True

    # Additional check: if text has very high density of material codes/numbers
    # but few action verbs, it's likely a data table
    words = text_lower.split()
    if len(words) > 50:  # Only check longer chunks
        # Count action verbs (guidance indicators)
        action_verbs = ['shall', 'should', 'must', 'verify', 'test', 'conduct', 'perform', 'ensure']
        action_count = sum(1 for verb in action_verbs if verb in words)

        # Count material codes/numbers (data indicators)
        # Look for patterns like "4130", "7075", "A286", "UTS", "ksi"
        code_count = sum(1 for word in words if (
            word.isdigit() or
            any(c.isdigit() for c in word) and len(word) <= 6
        ))

        # If >30% of words are codes/numbers and <3 action verbs, it's likely a table
        if code_count / len(words) > 0.3 and action_count < 3:
            return True

    return False


def _apply_rerank(
    base_score: float,
    meta: Dict[str, Any],
    clause_targets: Set[str],
    hazard_targets: Set[str],
) -> float:
    """Apply heuristic boosts to FAISS similarity score."""
    score = float(base_score)

    clause_ids = set(meta.get("clause_ids") or [])
    hazards = set(meta.get("hazards") or [])
    meta_info = meta.get("meta") or {}

    if clause_targets:
        score += 0.08 * len(clause_targets.intersection(clause_ids))
    if hazard_targets:
        score += 0.06 * len(hazard_targets.intersection(hazards))
    if meta_info.get("acceptance"):
        score += 0.05
    if meta_info.get("has_table"):
        score += 0.03

    score += SOURCE_PRIORITY.get(meta.get("source_id", ""), 0.0)

    return float(min(score, 1.5))  # keep within reasonable bounds


class StandardsRetriever:
    """FAISS-backed retrieval over standards corpus."""

    def __init__(self, index_dir: Path, model_name: str = DEFAULT_MODEL_NAME):
        if faiss is None or SentenceTransformer is None:
            raise RuntimeError("FAISS and sentence-transformers are required for retrieval.")

        self.index_dir = Path(index_dir)
        meta_path = self.index_dir / "metadata.json"
        faiss_path = self.index_dir / "faiss.index"

        if not meta_path.exists() or not faiss_path.exists():
            raise FileNotFoundError(f"Standards index not found under {self.index_dir}")

        with open(meta_path, "r", encoding="utf-8") as f:
            self.metadata: List[Dict[str, Any]] = json.load(f)

        self.index = faiss.read_index(str(faiss_path))
        self.model = SentenceTransformer(model_name)

    def retrieve(self, miul: MIULRef, gaps: Dict[str, str], *, search_k: int = 12, top_k: int = 8) -> List[Mitigation]:
        if not gaps:
            return []

        query_text = build_retrieval_query(miul, gaps)
        query_vec = self.model.encode([query_text], normalize_embeddings=True).astype("float32")
        scores, indices = self.index.search(query_vec, search_k)

        clause_targets = expected_clause_ids(gaps)
        hazard_targets = expected_hazard_tags(miul, gaps)

        candidates: List[Tuple[float, Mitigation]] = []
        filtered_count = 0
        for base_score, idx in zip(scores[0], indices[0]):
            if idx < 0:
                continue
            meta = self.metadata[idx]
            text = meta.get("text")
            if not text:
                continue

            # Filter out reference tables (data dumps without actionable guidance)
            if _is_reference_table(text):
                filtered_count += 1
                LOGGER.debug(f"Filtered reference table from {meta.get('source_id')}")
                continue

            adjusted = _apply_rerank(float(base_score), meta, clause_targets, hazard_targets)
            meta_info = meta.get("meta") or {}
            mitigation = Mitigation(
                text=text,
                source_doc_id=meta.get("source_id", ""),
                clause_refs=meta.get("clause_ids") or [],
                score=adjusted,
                hazards=meta.get("hazards") or [],
                source_center=meta.get("center"),
                acceptance=meta_info.get("acceptance") or {},
                has_table=bool(meta_info.get("has_table")),
                metadata=meta,
            )
            candidates.append((adjusted, mitigation))

        if filtered_count > 0:
            LOGGER.info(f"Filtered {filtered_count} reference tables from standards results")

        candidates.sort(key=lambda pair: pair[0], reverse=True)
        return [mit for _, mit in candidates[:top_k]]


class HybridRetriever:
    """
    Two-stage hybrid retriever combining standards (compliance rules)
    and historic MUAs (precedents).
    """

    def __init__(
        self,
        standards_retriever: Optional[StandardsRetriever],
        historic_retriever: Optional[HistoricMUARetriever],
    ):
        self.standards = standards_retriever
        self.historic = historic_retriever

        if not self.standards and not self.historic:
            LOGGER.warning("Both standards and historic retrievers unavailable")

    def retrieve(self, miul: MIULRef, gaps: Dict[str, str], *, top_k: int = 8) -> List[Mitigation]:
        """
        Retrieve mitigations using two-stage hybrid approach:
        1. Standards retrieval (compliance rules, acceptance criteria)
        2. Historic MUA retrieval (precedent mitigations)
        3. Merge, deduplicate, and rank
        """
        if not gaps:
            return []

        all_mitigations: List[Mitigation] = []

        # Stage 1: Standards (governing body - compliance rules)
        # Get 2-3 clean, actionable standards guidance
        if self.standards:
            try:
                standards_mits = self.standards.retrieve(miul, gaps, search_k=15, top_k=3)
                # Filter out boilerplate (rationale code lists, material spec lists, etc.)
                actionable_standards = []
                for mit in standards_mits:
                    text_lower = mit.text.lower()
                    # Skip if it's a rationale code list or material spec list
                    is_boilerplate = (
                        'rationale' in text_lower and 'code' in text_lower and text_lower.count('code') > 3 or
                        'sae-ams' in text_lower and text_lower.count('sae-ams') > 5 or
                        'astm-' in text_lower and text_lower.count('astm-') > 5
                    )
                    if not is_boilerplate:
                        actionable_standards.append(mit)

                LOGGER.info(f"Standards retrieval: {len(actionable_standards)}/{len(standards_mits)} actionable")
                all_mitigations.extend(actionable_standards)
            except Exception as exc:
                LOGGER.warning(f"Standards retrieval failed: {exc}")

        # Stage 2: Historic MUAs (precedent-based mitigations)
        # Get top 4-5 high-quality precedents
        if self.historic:
            try:
                historic_mits = self.historic.retrieve(miul, gaps, search_k=25, top_k=5)
                # Filter: only keep MUAs with substantive text (>200 chars, not just metadata)
                quality_mits = []
                for mit in historic_mits:
                    text_len = len(mit.text)
                    # Keep if:
                    # 1. Long text (>400 chars) - likely has good rationale
                    # 2. Medium text (>200 chars) AND starts with known good patterns
                    if text_len > 400:
                        quality_mits.append(mit)
                    elif text_len > 200 and any(pattern in mit.text.lower() for pattern in [
                        'rationale', 'shall', 'test', 'verify', 'acceptable', 'material is used',
                        'material has been', 'based on', 'compatibility', 'evaluation'
                    ]):
                        quality_mits.append(mit)

                LOGGER.info(f"Historic MUA retrieval: {len(quality_mits)}/{len(historic_mits)} quality precedents")
                all_mitigations.extend(quality_mits)
            except Exception as exc:
                LOGGER.warning(f"Historic MUA retrieval failed: {exc}")

        if not all_mitigations:
            LOGGER.warning("No mitigations retrieved from standards or historic MUAs")
            return []

        # Deduplicate similar mitigations (cosine similarity > 0.85)
        deduplicated = self._deduplicate_mitigations(all_mitigations, threshold=0.85)

        # Sort by score - prioritize historic precedents (higher scores due to matching)
        # NO boost for standards - let the natural scores determine ranking
        deduplicated.sort(key=lambda m: m.score, reverse=True)

        # Return top 5 max (less is more - quality over quantity)
        return deduplicated[:min(top_k, 5)]

    def _deduplicate_mitigations(
        self,
        mitigations: List[Mitigation],
        threshold: float = 0.85
    ) -> List[Mitigation]:
        """
        Deduplicate mitigations based on text similarity.
        Uses simple character-level overlap for fast deduplication.
        """
        if len(mitigations) <= 1:
            return mitigations

        # Sort by score descending to keep highest-scored duplicates
        sorted_mits = sorted(mitigations, key=lambda m: m.score, reverse=True)

        unique: List[Mitigation] = []
        for mit in sorted_mits:
            # Check if similar to any existing unique mitigation
            is_duplicate = False
            mit_words = set(mit.text.lower().split())

            for existing in unique:
                existing_words = set(existing.text.lower().split())

                # Jaccard similarity
                if len(mit_words) == 0 or len(existing_words) == 0:
                    continue

                intersection = len(mit_words & existing_words)
                union = len(mit_words | existing_words)
                similarity = intersection / union if union > 0 else 0.0

                if similarity >= threshold:
                    is_duplicate = True
                    LOGGER.debug(
                        f"Deduplicated: {mit.source_doc_id} similar to {existing.source_doc_id} "
                        f"(similarity={similarity:.2f})"
                    )
                    break

            if not is_duplicate:
                unique.append(mit)

        LOGGER.info(f"Deduplicated {len(mitigations)} → {len(unique)} mitigations")
        return unique


_RETRIEVER: Optional[HybridRetriever] = None
_LOAD_ERROR: Optional[Exception] = None


def get_retriever() -> HybridRetriever:
    """Get or create the singleton hybrid retriever."""
    global _RETRIEVER, _LOAD_ERROR

    if os.getenv("MUA_DISABLE_RETRIEVAL") == "1":
        raise RuntimeError("Mitigation retrieval explicitly disabled via MUA_DISABLE_RETRIEVAL")

    if _RETRIEVER is not None:
        return _RETRIEVER
    if _LOAD_ERROR is not None:
        raise RuntimeError("Mitigation retrieval previously failed to initialize") from _LOAD_ERROR

    try:
        # Load standards retriever
        standards_retriever = None
        try:
            index_dir = Path(os.getenv("MUA_STANDARDS_INDEX_DIR", DEFAULT_INDEX_DIR))
            standards_retriever = StandardsRetriever(index_dir=index_dir)
            LOGGER.info("Loaded standards retriever from %s", index_dir)
        except Exception as exc:
            LOGGER.warning("Standards retriever unavailable: %s", exc)

        # Load historic MUA retriever
        historic_retriever = None
        if get_historic_retriever:
            try:
                historic_retriever = get_historic_retriever()
                if historic_retriever:
                    LOGGER.info("Loaded historic MUA retriever")
            except Exception as exc:
                LOGGER.warning("Historic MUA retriever unavailable: %s", exc)

        # Create hybrid retriever
        if standards_retriever or historic_retriever:
            _RETRIEVER = HybridRetriever(
                standards_retriever=standards_retriever,
                historic_retriever=historic_retriever
            )
            LOGGER.info("Initialized hybrid retriever (standards + historic MUAs)")
        else:
            raise RuntimeError("Neither standards nor historic MUA retriever available")

    except Exception as exc:
        _LOAD_ERROR = exc
        LOGGER.error("Failed to load hybrid retriever: %s", exc)
        raise RuntimeError("Failed to initialize mitigation retrieval pipeline") from exc

    return _RETRIEVER


__all__ = [
    "StandardsRetriever",
    "HybridRetriever",
    "build_retrieval_query",
    "expected_clause_ids",
    "expected_hazard_tags",
    "get_retriever",
]

