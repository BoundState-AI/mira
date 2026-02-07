#!/usr/bin/env python3
"""
Module: Narrator
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

import asyncio
import json
from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING
import uuid

if TYPE_CHECKING:
    from mira.precedent_engine.models.config import EngineConfig
    from mira.precedent_engine.models.enriched import EnrichedMUA
    from mira.precedent_engine.models.precedent import PrecedentMatch, PrecedentRetrievalResult


NARRATOR_SYSTEM_PROMPT = """You are NASA's MUA precedent narrator. You synthesize rationale text from existing precedent MUAs.

CRITICAL CONSTRAINTS:
1. You are NOT a decision-maker. You NEVER determine if a material is approved or rejected.
2. You ONLY rephrase and combine rationale text from the provided precedents.
3. You NEVER invent new test data, specifications, or requirements.
4. You NEVER extrapolate beyond the environmental bounds of the precedents.
5. If there are gaps between the new case and precedents, you MUST flag them explicitly.

Your output must be valid JSON with these fields:
{
  "rationale_text": "Combined rationale from precedents, citing MUA numbers",
  "gaps": ["List of gaps requiring additional justification"],
  "citations": ["MUA-1234", "MUA-5678"],
  "confidence_note": "Brief note on how well precedents match"
}"""


NARRATOR_USER_PROMPT = """Generate rationale for this new MUA case based on the provided precedents.

NEW CASE:
Material: {material_name}
Environment: {environment_summary}
Issue: {issue}
Application: {application}

PRECEDENT MUAs:
{precedents_json}

Combine the rationale text from these precedents. Cite specific MUA numbers.
Flag any gaps where the new case differs from precedent conditions.

Return ONLY valid JSON."""


class NarratorLLM:
    """
    LLM wrapper for rationale synthesis.

    CRITICAL: This is a narrator only, never a decision-maker.
    The narrator synthesizes existing rationale text from precedents.
    It CANNOT:
    - Make approval/rejection decisions
    - Invent test data or specifications
    - Extrapolate beyond precedent environmental bounds
    - Generate new requirement language

    This class wraps boto3 Bedrock calls and provides async interface
    via thread pool executor for non-blocking operation.

    Compliance: SWE-033
    Safety Critical: True
    """

    def __init__(self, config: "EngineConfig", max_workers: int = 4) -> None:
        """
        Initialize the narrator LLM.

        Args:
            config: Engine configuration with AWS/Bedrock settings
            max_workers: Thread pool size for async operations
        """
        self.config = config
        self._executor = ThreadPoolExecutor(max_workers=max_workers)
        self._client = None

    def _get_client(self):
        """Lazy-load the Bedrock client."""
        if self._client is None:
            import boto3

            self._client = boto3.client(
                "bedrock-runtime",
                region_name=self.config.aws_region,
            )
        return self._client

    def _generate_rationale_sync(
        self,
        query: "EnrichedMUA",
        precedents: list["PrecedentMatch"],
        retrieval_result: "PrecedentRetrievalResult",
    ) -> dict:
        """
        Synchronously generate rationale text from precedents.

        This is the actual boto3 call wrapped in a sync function
        for use with the thread pool executor.

        Returns dict with:
        - rationale_text: Combined rationale
        - gaps: List of gaps flagged
        - citations: MUA numbers cited
        - confidence_note: How well precedents match
        """
        # Format precedents for prompt
        precedents_data = [
            {
                "mua_number": p.contract_id,
                "material": p.material_name,
                "category": p.category,
                "similarity_score": p.similarity_score,
                "rationale": p.rationale_text[:1000] if p.rationale_text else None,
                "environment": f"{p.media}, {p.temp_max_f}°F max, {p.pressure_max_psia} psia",
            }
            for p in precedents[: self.config.synthesis.max_precedents_to_merge]
        ]

        user_prompt = NARRATOR_USER_PROMPT.format(
            material_name=query.material_name,
            environment_summary=retrieval_result.query_environment_summary,
            issue=query.issue_text or "Not specified",
            application=query.application_text or "Not specified",
            precedents_json=json.dumps(precedents_data, indent=2),
        )

        # Call Bedrock
        client = self._get_client()
        response = client.invoke_model(
            modelId=self.config.bedrock_model_id,
            body=json.dumps(
                {
                    "anthropic_version": "bedrock-2023-05-31",
                    "max_tokens": 2048,
                    "temperature": 0.0,
                    "system": NARRATOR_SYSTEM_PROMPT,
                    "messages": [{"role": "user", "content": user_prompt}],
                }
            ),
        )

        response_body = json.loads(response["body"].read())
        raw_text = response_body["content"][0]["text"]

        # Parse response
        try:
            result = json.loads(raw_text)
            return {
                "rationale_text": result.get("rationale_text", ""),
                "gaps": result.get("gaps", []),
                "citations": result.get("citations", []),
                "confidence_note": result.get("confidence_note", ""),
            }
        except json.JSONDecodeError:
            # Fallback for malformed response
            return {
                "rationale_text": f"[RAW LLM OUTPUT] {raw_text[:2000]}",
                "gaps": ["LLM returned invalid JSON - manual review required"],
                "citations": [p.contract_id for p in precedents],
                "confidence_note": "Parse error - escalate for review",
            }

    async def generate_rationale(
        self,
        query: "EnrichedMUA",
        precedents: list["PrecedentMatch"],
        retrieval_result: "PrecedentRetrievalResult",
    ) -> dict:
        """
        Asynchronously generate rationale text from precedents.

        CRITICAL: The narrator only combines existing text. It does NOT:
        - Make approval/rejection decisions
        - Invent new test data
        - Extrapolate beyond precedent bounds

        Args:
            query: The query MUA to generate rationale for
            precedents: List of matched precedents with rationale text
            retrieval_result: Full retrieval result with statistics

        Returns:
            dict with rationale_text, gaps, citations, confidence_note
        """
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            self._executor,
            self._generate_rationale_sync,
            query,
            precedents,
            retrieval_result,
        )

    def close(self) -> None:
        """Shutdown the thread pool executor."""
        self._executor.shutdown(wait=True)

    def __enter__(self) -> "NarratorLLM":
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Context manager exit."""
        self.close()


class MockNarratorLLM:
    """
    Mock narrator for testing without AWS Bedrock.

    Returns deterministic output based on input precedents.
    """

    def __init__(self, config: "EngineConfig | None" = None) -> None:
        """Initialize mock narrator."""
        self.config = config

    async def generate_rationale(
        self,
        query: "EnrichedMUA",
        precedents: list["PrecedentMatch"],
        retrieval_result: "PrecedentRetrievalResult",
    ) -> dict:
        """Generate mock rationale."""
        citations = [p.contract_id for p in precedents]

        # Collect rationale fragments
        rationale_parts = []
        for p in precedents[:3]:
            if p.rationale_text:
                rationale_parts.append(
                    f"Per {p.contract_id}: {p.rationale_text[:200]}..."
                )

        combined_rationale = " ".join(rationale_parts) or "No rationale text available in precedents."

        # Identify gaps
        gaps = []
        if not precedents:
            gaps.append("No precedents available")
        elif retrieval_result.n_tier1 == 0:
            gaps.append("No Tier 1 (exact) matches found")

        return {
            "rationale_text": combined_rationale,
            "gaps": gaps,
            "citations": citations,
            "confidence_note": f"Mock rationale from {len(precedents)} precedents",
        }

    def close(self) -> None:
        """No-op for mock."""
        pass
