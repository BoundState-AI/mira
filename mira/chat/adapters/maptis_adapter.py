"""
Module: MIRA Chat -- MAPTIS Search Adapter
Purpose: Adapter bridging the MAPTIS semantic search engine into the
         MIRA Chat unified envelope per BS-SPEC-MIRA-CHAT-001-REV2.

Instantiates ``mira.core.search_engine.SemanticSearchEngine`` and
translates ``search()`` results (list of dicts) into a standard
``EngineEnvelope``.

BoundState AI 2026
Classification: BoundState Proprietary

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: SWE-032 (Data validation), SWE-033 (Requirements Traceability)
Safety Critical: False
"""

from __future__ import annotations

__version__ = "1.0.0"
__safety_critical__ = False

import logging
from typing import Any, Optional

from mira.chat.engine_adapter import EngineAdapter
from mira.chat.models import EngineEnvelope, SideEffectLevel, Status, TaskMode

LOGGER = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Lazy singleton for the search engine (expensive to construct)
# ---------------------------------------------------------------------------

_SEARCH_ENGINE: Optional[Any] = None
_SEARCH_ENGINE_ERROR: Optional[Exception] = None
_SEARCH_AVAILABLE: Optional[bool] = None


def _get_search_engine():
    """Lazy-load the SemanticSearchEngine singleton."""
    global _SEARCH_ENGINE, _SEARCH_ENGINE_ERROR, _SEARCH_AVAILABLE

    if _SEARCH_ENGINE is not None:
        return _SEARCH_ENGINE
    if _SEARCH_ENGINE_ERROR is not None:
        return None

    try:
        from mira.core.search_engine import SemanticSearchEngine

        _SEARCH_ENGINE = SemanticSearchEngine()
        _SEARCH_AVAILABLE = True
        LOGGER.info("MAPTIS SemanticSearchEngine loaded for chat adapter")
        return _SEARCH_ENGINE
    except Exception as exc:
        _SEARCH_ENGINE_ERROR = exc
        _SEARCH_AVAILABLE = False
        LOGGER.warning("MAPTIS search engine not available: %s", exc)
        return None


# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

_DEFAULT_TOP_K = 10
_DEFAULT_MIN_SIMILARITY = 0.15


# ---------------------------------------------------------------------------
# MAPTIS Search Adapter
# ---------------------------------------------------------------------------


class MAPTISAdapter(EngineAdapter):
    """
    Adapter for MAPTIS semantic search.

    Expects ``parsed_input`` keys:

    * ``query`` (str, required) -- the search query
    * ``top_k`` (int, optional) -- max results to return (default 10)
    * ``min_similarity`` (float, optional) -- similarity threshold (default 0.15)
    """

    engine_id: str = "maptis_search"
    engine_version: str = __version__
    supported_tasks: list[TaskMode] = [TaskMode.ANSWER_ONLY]
    side_effect_level: SideEffectLevel = SideEffectLevel.READ_ONLY

    async def execute(
        self,
        parsed_input: dict[str, Any],
        session_context: dict[str, Any],
    ) -> EngineEnvelope:
        """Run a MAPTIS semantic search and return results in a normalised envelope."""
        engine = _get_search_engine()
        if engine is None:
            return self.wrap_error(
                exc=RuntimeError(
                    "MAPTIS semantic search engine is not available. "
                    "Check FAISS index configuration."
                ),
            )

        query = (parsed_input.get("query") or "").strip()
        if not query:
            return self.wrap_refusal(
                reason="A search query is required for MAPTIS material lookup.",
            )

        top_k = int(parsed_input.get("top_k") or _DEFAULT_TOP_K)
        min_similarity = float(parsed_input.get("min_similarity") or _DEFAULT_MIN_SIMILARITY)

        try:
            raw_results = engine.search(
                query=query,
                top_k=top_k,
                min_similarity=min_similarity,
            )
        except Exception as exc:
            LOGGER.error("MAPTIS search raised: %s", exc, exc_info=True)
            return self.wrap_error(exc=exc)

        return self._adapt_results(raw_results, query)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _adapt_results(
        self,
        raw_results: list[dict[str, Any]],
        query: str,
    ) -> EngineEnvelope:
        """Map search results to an EngineEnvelope.

        ``raw_results`` is the list returned by
        ``SemanticSearchEngine.search()``, where each item has the shape::

            {
                "material": { "material_id": ..., "name": ..., "designation": ..., ... },
                "similarity_score": float,
                "original_material": { ... },
            }
        """
        if not raw_results:
            return self.wrap_envelope(
                status=Status.INSUFFICIENT_DATA,
                response_text=(
                    f"No MAPTIS materials matched the query '{query}'. "
                    "Try rephrasing with a more specific material name or designation."
                ),
                missing_inputs=[f"No materials found for: {query}"],
            )

        # Build a concise textual summary
        top_n = raw_results[:5]
        lines: list[str] = [
            f"Found {len(raw_results)} MAPTIS material(s) matching '{query}'.",
            "",
        ]
        for i, item in enumerate(top_n, 1):
            mat = item.get("material", {})
            name = mat.get("name") or mat.get("designation") or "Unknown"
            mat_id = mat.get("material_id", "?")
            score = item.get("similarity_score", 0.0)
            mat_type = mat.get("material_type") or mat.get("category") or ""
            type_label = f" ({mat_type})" if mat_type else ""
            lines.append(f"  {i}. {name}{type_label} [ID {mat_id}] -- similarity {score:.3f}")

        if len(raw_results) > 5:
            lines.append(f"  ... and {len(raw_results) - 5} more result(s).")

        response_text = "\n".join(lines)

        # Build structured evidence cards
        evidence: list[dict[str, Any]] = []
        for item in raw_results:
            mat = item.get("material", {})
            evidence.append(
                {
                    "source_id": str(mat.get("material_id", "")),
                    "material_name": mat.get("name") or mat.get("designation"),
                    "material_type": mat.get("material_type") or mat.get("category"),
                    "composition": mat.get("composition"),
                    "manufacturer": mat.get("manufacturer"),
                    "specification": mat.get("specification"),
                    "similarity_score": item.get("similarity_score"),
                }
            )

        # Domain payload carries full structured results for the frontend
        domain_payload: dict[str, Any] = {
            "result_count": len(raw_results),
            "query": query,
            "materials": [
                {
                    "material_id": (item.get("material", {}).get("material_id")),
                    "name": (
                        item.get("material", {}).get("name")
                        or item.get("material", {}).get("designation")
                    ),
                    "similarity_score": item.get("similarity_score"),
                }
                for item in raw_results
            ],
        }

        return self.wrap_envelope(
            status=Status.PASS,
            response_text=response_text,
            authority_basis=["MAPTIS Database"],
            citations=["MAPTIS / NASA MSFC Materials Database"],
            evidence=evidence,
            domain_payload=domain_payload,
        )
