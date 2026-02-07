#!/usr/bin/env python3
"""
Module: Runner
Purpose: [Automatically migrated - needs manual review]

BoundState AI 2025
Version: 1.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Fran OpenAI 5 <noreply@openai.com>
Co-Authored-By: Grok 4.0 <noreply@x.ai>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: SWE-013, SWE-033, NASA-STD-6016, NASA-STD-8739.8B
Safety Critical: True
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from mira.precedent_engine.core.narrator import NarratorLLM
from mira.precedent_engine.core.precedent_engine import PrecedentEngine
from mira.precedent_engine.core.storage import VectorStore
from mira.precedent_engine.models.candidate import CandidateMUA, EngineResult, RationaleSegment
from mira.precedent_engine.models.enums import LLMContribution, PrecedentAdequacyLevel
import uuid

if TYPE_CHECKING:
    from mira.precedent_engine.models.config import EngineConfig
    from mira.precedent_engine.models.enriched import EnrichedMUA
    from mira.precedent_engine.models.precedent import PrecedentRetrievalResult


class MUAPrecedentRunner:
    """
    Main orchestration for MUA precedent processing.

    This class coordinates the async and sync components:
    - ASYNC: Vector search for candidates (VectorStore)
    - SYNC: Precedent tier assignment and scoring (PrecedentEngine)
    - ASYNC: Rationale synthesis (NarratorLLM)

    Compliance: SWE-013, SWE-033
    Safety Critical: True
    """

    def __init__(
        self,
        config: "EngineConfig",
        vector_store: VectorStore,
        narrator: NarratorLLM,
    ) -> None:
        """
        Initialize the runner.

        Args:
            config: Engine configuration
            vector_store: Vector store for candidate retrieval
            narrator: LLM narrator for rationale synthesis
        """
        self.config = config
        self.vector_store = vector_store
        self.narrator = narrator
        self.engine = PrecedentEngine(config.equivalence, config.adequacy)

    async def process_case(
        self,
        query: "EnrichedMUA",
    ) -> EngineResult:
        """
        Process a new MUA case end-to-end.

        1. Retrieve candidates from vector store (ASYNC)
        2. Evaluate with PrecedentEngine (SYNC - pure computation)
        3. Check adequacy gate
        4. Generate rationale if adequate (ASYNC)
        5. Return result

        IMPORTANT: The determination field is NEVER auto-populated.
        All decisions remain with human engineers.

        Args:
            query: Enriched MUA query to process

        Returns:
            EngineResult with candidate MUA or escalation status
        """
        try:
            # Step 1: Vector search for candidates (ASYNC)
            candidates = await self.vector_store.search(
                query=query,
                top_k=self.config.top_k_initial,
                score_threshold=self.config.score_threshold_initial,
            )

            # Step 2: Tier assignment and scoring (SYNC - no await)
            retrieval = self.engine.evaluate_candidates(query, candidates)

            # Step 3: Adequacy gate
            if retrieval.adequacy == PrecedentAdequacyLevel.INSUFFICIENT:
                return EngineResult(
                    status="escalate",
                    reason=retrieval.adequacy_reasoning,
                    retrieval_result=retrieval,
                    query_material=query.material_name,
                    query_environment=retrieval.query_environment_summary,
                )

            # Step 4: Generate rationale (ASYNC)
            precedents = retrieval.tier1_matches + retrieval.tier2_matches[:3]
            narrative = await self.narrator.generate_rationale(
                query, precedents, retrieval
            )

            # Step 5: Build candidate MUA (SYNC)
            candidate = self._build_candidate(query, retrieval, narrative)

            # Add warnings for MODERATE adequacy
            if retrieval.adequacy == PrecedentAdequacyLevel.MODERATE:
                candidate.warnings.append(
                    "Precedent adequacy is MODERATE. Additional engineering review recommended."
                )

            return EngineResult(
                status="candidate",
                candidate_mua=candidate,
                retrieval_result=retrieval,
                query_material=query.material_name,
                query_environment=retrieval.query_environment_summary,
            )

        except Exception as e:
            return EngineResult(
                status="error",
                reason=f"Processing error: {str(e)}",
                query_material=query.material_name,
                query_environment=None,
            )

    def _build_candidate(
        self,
        query: "EnrichedMUA",
        retrieval: "PrecedentRetrievalResult",
        narrative: dict,
    ) -> CandidateMUA:
        """
        Build CandidateMUA from components.

        CRITICAL: The determination field is ALWAYS None.
        This is a draft for human review, not an approval.
        """
        # Precedent summary
        stats = retrieval.statistics
        summary_parts = [
            f"{stats.n_total_with_material} prior MUAs with this material",
            f"{stats.n_approved} approved",
            f"{stats.n_rejected} rejected",
        ]
        precedent_summary = "; ".join(summary_parts)

        # Category routing (per Addendum C - this is a ROUTING HINT, not compliance)
        if query.o2_pct >= 23.5 or query.media in ("GOX", "LOX"):
            suggested_category = "I"
            category_reasoning = "Oxygen service ≥23.5% requires Category I per NASA-STD-6016"
        elif retrieval.adequacy == PrecedentAdequacyLevel.STRONG:
            suggested_category = "II"
            category_reasoning = "Strong precedent supports Category II routing"
        else:
            suggested_category = "II"
            category_reasoning = "Default to Category II for engineering review"

        # Build rationale segments
        rationale_segments = []
        for deviation in query.deviation_types:
            segment = RationaleSegment(
                deviation_type=deviation,
                text=narrative.get("rationale_text", ""),
                source_mua_ids=narrative.get("citations", []),
                contribution_type=LLMContribution.MERGED,
                has_gap=len(narrative.get("gaps", [])) > 0,
                gap_description="; ".join(narrative.get("gaps", [])) or None,
            )
            rationale_segments.append(segment)

        # If no deviation types but we have rationale, create a generic segment
        if not rationale_segments and narrative.get("rationale_text"):
            from mira.precedent_engine.models.enums import DeviationType

            rationale_segments.append(
                RationaleSegment(
                    deviation_type=DeviationType.OTHER,
                    text=narrative.get("rationale_text", ""),
                    source_mua_ids=narrative.get("citations", []),
                    contribution_type=LLMContribution.MERGED,
                    has_gap=len(narrative.get("gaps", [])) > 0,
                    gap_description="; ".join(narrative.get("gaps", [])) or None,
                )
            )

        # Generate MUA number
        timestamp = datetime.now().strftime("%Y%m%d%H%M")
        mat_prefix = query.material_name[:20].replace(" ", "-").upper()
        mua_number = f"AUTO-PRECEDENT-{mat_prefix}-{timestamp}"

        return CandidateMUA(
            mua_number=mua_number,
            material_name=query.material_name,
            material_key=query.material_key,
            specification=query.specification,
            manufacturer=query.manufacturer,
            trade_name=query.trade_name,
            application_description=query.application_text,
            environment_envelope=retrieval.query_environment_summary,
            media=query.media,
            o2_pct=query.o2_pct,
            location_class=query.location_class,
            temp_max_f=query.temp_max_f,
            temp_min_f=query.temp_min_f,
            pressure_max_psia=query.pressure_max_psia,
            suggested_routing_category=suggested_category,
            routing_category_reasoning=category_reasoning,
            rationales=rationale_segments,
            combined_rationale_text=narrative.get("rationale_text"),
            determination=None,  # CRITICAL: NEVER auto-populated
            precedent_adequacy=retrieval.adequacy,
            precedent_summary=precedent_summary,
            precedent_mua_ids=[
                m.contract_id for m in retrieval.tier1_matches + retrieval.tier2_matches
            ],
            base_mua_id=(
                retrieval.recommended_base.contract_id if retrieval.recommended_base else None
            ),
            base_mua_similarity=(
                retrieval.recommended_base.similarity_score
                if retrieval.recommended_base
                else None
            ),
            statistics=stats,
            retrieval_result=retrieval,
            warnings=list(narrative.get("gaps", [])),
            requires_manual_justification=(
                retrieval.adequacy != PrecedentAdequacyLevel.STRONG
            ),
        )

    def close(self) -> None:
        """Cleanup resources."""
        self.vector_store.close()
        self.narrator.close()

    def __enter__(self) -> "MUAPrecedentRunner":
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Context manager exit."""
        self.close()
