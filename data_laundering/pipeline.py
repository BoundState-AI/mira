#!/usr/bin/env python3
"""
Module: Data Laundering Pipeline Orchestrator
Purpose: Four-layer pipeline that launders raw user input into validated,
         cited, auditable responses.

BoundState AI 2026
Version: 1.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Claude "CC" <noreply@anthropic.com>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: NASA-STD-8739.8B, SWE-013, SWE-033
Safety Critical: True

THE PIPELINE:
  Layer 1 (Sanitize):  Raw input -> SanitizedQuery via LLM (Llama/local)
  Layer 2 (Reason):    SanitizedQuery -> ReasonerOutput via LLM (Sonnet/local)
  Layer 3 (Validate):  ReasonerOutput -> ValidatedResults via database adapter
  Layer 4 (Present):   ValidatedResults -> PresentedResponse via LLM (Haiku/local)

SECURITY MODEL:
  - Layer 2 NEVER sees raw user input. Only SanitizedQuery.
  - Layer 4 ONLY sees ValidatedResults. No raw input. No unvalidated candidates.
  - Raw input is hashed at Layer 1. The plaintext dies there.
  - Schema validation kills queries. No fallback. No retry with raw input.
  - The persona IS the security. Fat LLM with grumpy personality > regex.

Spec Reference: BS-DL-ARCH-001
"""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from .bedrock_client import LLMClient, LLMError, LLMResponse
from .domain_pack import DomainPack
from .models import (
    CandidateRecord,
    Citation,
    EnvironmentFilter,
    LayerTiming,
    PipelineEnvelope,
    PipelineStatus,
    PresentedResponse,
    QueryIntent,
    QueryType,
    ReasonerOutput,
    RejectionReason,
    SanitizedQuery,
    ValidatedResults,
)

logger = logging.getLogger(__name__)


class DataLaunderingPipeline:
    """Four-layer data laundering pipeline.

    Swap the DomainPack to target any structured database.
    The pipeline logic is domain-agnostic.

    Usage::

        from data_laundering.pipeline import DataLaunderingPipeline
        from data_laundering.domain_pack import create_mira_pack
        from data_laundering.granta_adapter import GrantaValidatorAdapter

        adapter = GrantaValidatorAdapter()
        pack = create_mira_pack(adapter)
        pipeline = DataLaunderingPipeline(pack)

        envelope = await pipeline.process("What alloys work in LOX at 500 psi?")

    Compliance: SWE-013, SWE-033, NASA-STD-8739.8B
    """

    def __init__(
        self,
        pack: DomainPack,
        llm_client: Optional[LLMClient] = None,
        sanitizer_model: str = "llama3.1:8b",
        reasoner_model: str = "llama3.1:8b",
        presenter_model: str = "llama3.1:8b",
    ) -> None:
        """Initialize the pipeline.

        Args:
            pack: Domain configuration pack.
            llm_client: LLM client instance. If None, creates default local client.
            sanitizer_model: Model name for Layer 1 (biggest local LLM for parsing).
            reasoner_model: Model name for Layer 2 (local LLM).
            presenter_model: Model name for Layer 4 (local LLM).
        """
        self.pack = pack
        self.llm = llm_client or LLMClient()
        self._sanitizer_model = sanitizer_model
        self._reasoner_model = reasoner_model
        self._presenter_model = presenter_model

        logger.info(
            "DataLaunderingPipeline initialized: domain=%s, "
            "sanitizer=%s, reasoner=%s, presenter=%s",
            pack.domain_id, sanitizer_model, reasoner_model, presenter_model,
        )

    async def process(self, raw_input: str) -> PipelineEnvelope:
        """Run raw user input through all four layers.

        This is the main entry point. Raw input goes in, auditable
        envelope comes out. The raw input text is dead after Layer 1.

        Args:
            raw_input: The raw user input string.

        Returns:
            PipelineEnvelope containing all layer outputs and audit data.
        """
        input_hash = SanitizedQuery.hash_input(raw_input)
        envelope = PipelineEnvelope(
            domain=self.pack.domain_id,
            input_hash=input_hash,
        )

        logger.info(
            "Pipeline started: domain=%s, input_hash=%s...",
            self.pack.domain_id, input_hash[:16],
        )

        # Layer 1: Sanitize
        sanitized = await self._sanitize(raw_input, envelope)
        if sanitized is None:
            envelope.mark_completed(envelope.status)
            return envelope

        # Layer 2: Reason
        reasoned = await self._reason(sanitized, envelope)
        if reasoned is None:
            envelope.mark_completed(envelope.status)
            return envelope

        # Layer 3: Validate
        validated = await self._validate(reasoned, sanitized, envelope)
        if validated is None:
            envelope.mark_completed(envelope.status)
            return envelope

        # Layer 4: Present
        await self._present(validated, sanitized, envelope)
        envelope.mark_completed(PipelineStatus.COMPLETED)

        logger.info(
            "Pipeline completed: domain=%s, status=%s, duration=%.0fms",
            self.pack.domain_id, envelope.status.value,
            envelope.total_duration_ms or 0,
        )

        return envelope

    # =========================================================================
    # Layer 1: Sanitize
    # =========================================================================

    async def _sanitize(
        self,
        raw_input: str,
        envelope: PipelineEnvelope,
    ) -> Optional[SanitizedQuery]:
        """Layer 1: Convert raw user input to rigid typed JSON.

        The raw input text dies here. Only the SHA-256 hash survives.
        If the LLM output doesn't parse into SanitizedQuery, the query
        is DEAD. No fallback. No retry with raw input.

        Args:
            raw_input: Raw user input string.
            envelope: Pipeline envelope for audit trail.

        Returns:
            SanitizedQuery if successful, None if query should die.
        """
        timing = LayerTiming(
            layer=1,
            layer_name="sanitize",
            started_at=datetime.now(timezone.utc).isoformat(),
        )

        try:
            # Call LLM
            response = await self.llm.invoke_sanitizer(
                prompt=raw_input,
                system=self.pack.layer_1_system_prompt,
                model=self._sanitizer_model,
            )

            timing.llm_model = response.model
            timing.llm_input_tokens = response.input_tokens
            timing.llm_output_tokens = response.output_tokens

            # Parse LLM output into structured query
            sanitized = self._parse_sanitizer_output(
                response.text, envelope.input_hash
            )

            if sanitized is None:
                envelope.status = PipelineStatus.REJECTED_LAYER_1
                envelope.rejection_reason = RejectionReason.PARSE_FAILURE
                envelope.rejection_detail = (
                    "Layer 1 LLM output did not parse into SanitizedQuery"
                )
                logger.warning(
                    "Layer 1 REJECTED: parse failure for input_hash=%s...",
                    envelope.input_hash[:16],
                )
                self._finalize_timing(timing)
                envelope.add_layer_timing(timing)
                return None

            envelope.layer_1_output = sanitized
            self._finalize_timing(timing)
            envelope.add_layer_timing(timing)

            logger.info(
                "Layer 1 completed: intent=%s, material=%s, safety=%s",
                sanitized.intent.value,
                sanitized.material_name,
                sanitized.safety_context,
            )

            return sanitized

        except LLMError as exc:
            envelope.status = PipelineStatus.REJECTED_LAYER_1
            envelope.rejection_reason = RejectionReason.LLM_ERROR
            envelope.rejection_detail = f"Layer 1 LLM error: {exc}"
            timing.error = str(exc)
            self._finalize_timing(timing)
            envelope.add_layer_timing(timing)
            logger.error("Layer 1 LLM error: %s", exc)
            return None

    def _parse_sanitizer_output(
        self,
        llm_text: str,
        input_hash: str,
    ) -> Optional[SanitizedQuery]:
        """Parse LLM output text into a SanitizedQuery.

        Extracts JSON from the LLM response and validates it against
        the SanitizedQuery schema. If parsing fails, returns None
        and the query dies.

        Args:
            llm_text: Raw text from the LLM.
            input_hash: SHA-256 hash of the original input.

        Returns:
            SanitizedQuery if parsing succeeds, None otherwise.
        """
        # Extract JSON from LLM response (may be wrapped in markdown)
        json_str = self._extract_json(llm_text)
        if json_str is None:
            logger.warning("No JSON found in Layer 1 output")
            return None

        try:
            parsed = json.loads(json_str)
        except json.JSONDecodeError as exc:
            logger.warning("Layer 1 JSON parse error: %s", exc)
            return None

        # Check for explicit error response from LLM
        if "error" in parsed:
            logger.warning(
                "Layer 1 LLM returned error: %s - %s",
                parsed.get("error"), parsed.get("reason", "no reason"),
            )
            return None

        # Map parsed fields to SanitizedQuery
        try:
            environment = EnvironmentFilter(
                temperature_c=parsed.get("environment", {}).get("temperature_c"),
                pressure_kpa=parsed.get("environment", {}).get("pressure_kpa"),
                o2_pct=parsed.get("environment", {}).get("o2_pct"),
                fluid_medium=parsed.get("environment", {}).get("fluid_medium"),
                duration_hr=parsed.get("environment", {}).get("duration_hr"),
                cycles=parsed.get("environment", {}).get("cycles"),
            )

            sanitized = SanitizedQuery(
                input_hash=input_hash,
                query_type=QueryType(parsed.get("query_type", "exploratory")),
                intent=QueryIntent(parsed.get("intent", "general")),
                material_name=parsed.get("material_name"),
                property_names=parsed.get("property_names", []),
                environment=environment,
                filters=parsed.get("filters", {}),
                safety_context=parsed.get("safety_context"),
            )

            return sanitized

        except (ValueError, KeyError) as exc:
            logger.warning("Layer 1 schema validation error: %s", exc)
            return None

    # =========================================================================
    # Layer 2: Reason
    # =========================================================================

    async def _reason(
        self,
        sanitized: SanitizedQuery,
        envelope: PipelineEnvelope,
    ) -> Optional[ReasonerOutput]:
        """Layer 2: Generate ranked candidate list from sanitized query.

        Layer 2 NEVER sees raw user input. Only the SanitizedQuery.

        Args:
            sanitized: Layer 1 output.
            envelope: Pipeline envelope for audit trail.

        Returns:
            ReasonerOutput if successful, None if query should die.
        """
        timing = LayerTiming(
            layer=2,
            layer_name="reason",
            started_at=datetime.now(timezone.utc).isoformat(),
        )

        try:
            # Build prompt from sanitized query (NO raw input)
            prompt = self._build_reasoner_prompt(sanitized)

            response = await self.llm.invoke_reasoner(
                prompt=prompt,
                system=self.pack.layer_2_system_prompt,
                model=self._reasoner_model,
                temperature=self.pack.layer_2_temperature,
            )

            timing.llm_model = response.model
            timing.llm_input_tokens = response.input_tokens
            timing.llm_output_tokens = response.output_tokens

            # Parse LLM output into ReasonerOutput
            reasoned = self._parse_reasoner_output(response.text)

            if reasoned is None:
                envelope.status = PipelineStatus.REJECTED_LAYER_2
                envelope.rejection_reason = RejectionReason.NO_CANDIDATES
                envelope.rejection_detail = (
                    "Layer 2 LLM output did not produce valid candidates"
                )
                logger.warning("Layer 2 REJECTED: no valid candidates")
                self._finalize_timing(timing)
                envelope.add_layer_timing(timing)
                return None

            # Enforce max candidates
            if len(reasoned.candidates) > self.pack.max_candidates:
                reasoned = ReasonerOutput(
                    candidates=reasoned.candidates[:self.pack.max_candidates],
                    search_strategy=reasoned.search_strategy,
                    filters_applied=reasoned.filters_applied,
                    total_considered=reasoned.total_considered,
                )

            envelope.layer_2_output = reasoned
            self._finalize_timing(timing)
            envelope.add_layer_timing(timing)

            logger.info(
                "Layer 2 completed: %d candidates, strategy=%s",
                len(reasoned.candidates), reasoned.search_strategy,
            )

            return reasoned

        except LLMError as exc:
            envelope.status = PipelineStatus.REJECTED_LAYER_2
            envelope.rejection_reason = RejectionReason.LLM_ERROR
            envelope.rejection_detail = f"Layer 2 LLM error: {exc}"
            timing.error = str(exc)
            self._finalize_timing(timing)
            envelope.add_layer_timing(timing)
            logger.error("Layer 2 LLM error: %s", exc)
            return None

    def _build_reasoner_prompt(self, sanitized: SanitizedQuery) -> str:
        """Build the Layer 2 prompt from sanitized query data.

        This prompt contains ONLY structured data from Layer 1.
        No raw user input.
        """
        query_data = sanitized.model_dump(exclude={"input_hash"})
        # Convert enums to strings for JSON serialization
        query_data["query_type"] = sanitized.query_type.value
        query_data["intent"] = sanitized.intent.value

        return (
            "Find candidate materials matching this structured query. "
            "Return a JSON object with 'candidates' array, 'search_strategy' string, "
            "'filters_applied' object, and 'total_considered' integer.\n\n"
            "Each candidate must have: 'material_key', 'record_id' (or null), "
            "'reasoning', 'relevance_score' (0.0-1.0), 'properties' object.\n\n"
            f"QUERY:\n{json.dumps(query_data, indent=2, default=str)}"
        )

    def _parse_reasoner_output(
        self,
        llm_text: str,
    ) -> Optional[ReasonerOutput]:
        """Parse LLM output into ReasonerOutput."""
        json_str = self._extract_json(llm_text)
        if json_str is None:
            logger.warning("No JSON found in Layer 2 output")
            return None

        try:
            parsed = json.loads(json_str)
        except json.JSONDecodeError as exc:
            logger.warning("Layer 2 JSON parse error: %s", exc)
            return None

        try:
            candidates = []
            for c in parsed.get("candidates", []):
                candidates.append(CandidateRecord(
                    material_key=c.get("material_key", "UNKNOWN"),
                    record_id=c.get("record_id"),
                    reasoning=c.get("reasoning", "No reasoning provided"),
                    relevance_score=float(c.get("relevance_score", 0.5)),
                    properties=c.get("properties", {}),
                ))

            if not candidates:
                return None

            return ReasonerOutput(
                candidates=candidates,
                search_strategy=parsed.get("search_strategy", "llm_reasoning"),
                filters_applied=parsed.get("filters_applied", {}),
                total_considered=parsed.get("total_considered", len(candidates)),
            )
        except (ValueError, KeyError) as exc:
            logger.warning("Layer 2 schema validation error: %s", exc)
            return None

    # =========================================================================
    # Layer 3: Validate
    # =========================================================================

    async def _validate(
        self,
        reasoned: ReasonerOutput,
        sanitized: SanitizedQuery,
        envelope: PipelineEnvelope,
    ) -> Optional[ValidatedResults]:
        """Layer 3: Validate candidates against ground truth.

        This is where the validator adapter does its work. No LLM here —
        just database queries, dirty data checks, heritage vetoes,
        provenance hashes, and confidence scores.

        The validator is ALWAYS called. No shortcuts. No bypass.

        Args:
            reasoned: Layer 2 output with candidates.
            sanitized: Layer 1 output for query context.
            envelope: Pipeline envelope for audit trail.

        Returns:
            ValidatedResults if any candidates survive, None otherwise.
        """
        timing = LayerTiming(
            layer=3,
            layer_name="validate",
            started_at=datetime.now(timezone.utc).isoformat(),
        )

        try:
            validated = await self.pack.validator.validate_candidates(
                candidates=reasoned.candidates,
                query=sanitized,
            )

            if not validated.records:
                envelope.status = PipelineStatus.REJECTED_LAYER_3
                envelope.rejection_reason = (
                    RejectionReason.ALL_CANDIDATES_FAILED_VALIDATION
                )
                envelope.rejection_detail = (
                    f"All {validated.total_candidates} candidates failed "
                    f"ground-truth validation"
                )

                # Preserve relaxation suggestions in the envelope
                if validated.relaxation_suggestions:
                    envelope.rejection_detail += (
                        f". {len(validated.relaxation_suggestions)} "
                        f"filter relaxation(s) suggested."
                    )

                envelope.layer_3_output = validated
                self._finalize_timing(timing)
                envelope.add_layer_timing(timing)
                logger.warning(
                    "Layer 3 REJECTED: all candidates failed validation"
                )
                return None

            envelope.layer_3_output = validated
            self._finalize_timing(timing)
            envelope.add_layer_timing(timing)

            logger.info(
                "Layer 3 completed: %d/%d candidates validated, "
                "query_hash=%s...",
                validated.candidates_validated,
                validated.total_candidates,
                validated.query_hash[:16],
            )

            return validated

        except Exception as exc:
            envelope.status = PipelineStatus.REJECTED_LAYER_3
            envelope.rejection_reason = RejectionReason.VALIDATOR_ERROR
            envelope.rejection_detail = f"Layer 3 validator error: {exc}"
            timing.error = str(exc)
            self._finalize_timing(timing)
            envelope.add_layer_timing(timing)
            logger.error("Layer 3 validator error: %s", exc)
            return None

    # =========================================================================
    # Layer 4: Present
    # =========================================================================

    async def _present(
        self,
        validated: ValidatedResults,
        sanitized: SanitizedQuery,
        envelope: PipelineEnvelope,
    ) -> Optional[PresentedResponse]:
        """Layer 4: Format validated results into a user response.

        Layer 4 ONLY sees validated data from Layer 3. It does not see
        raw input or unvalidated candidates. It presents, it doesn't create.

        Args:
            validated: Layer 3 output.
            sanitized: Layer 1 output (for intent context only, no raw input).
            envelope: Pipeline envelope for audit trail.

        Returns:
            PresentedResponse with formatted text and citations.
        """
        timing = LayerTiming(
            layer=4,
            layer_name="present",
            started_at=datetime.now(timezone.utc).isoformat(),
        )

        try:
            prompt = self._build_presenter_prompt(validated, sanitized)

            response = await self.llm.invoke_presenter(
                prompt=prompt,
                system=self.pack.layer_4_system_prompt,
                model=self._presenter_model,
            )

            timing.llm_model = response.model
            timing.llm_input_tokens = response.input_tokens
            timing.llm_output_tokens = response.output_tokens

            presented = self._parse_presenter_output(response.text, validated)

            envelope.layer_4_output = presented
            self._finalize_timing(timing)
            envelope.add_layer_timing(timing)

            logger.info(
                "Layer 4 completed: %d citations, %d warnings",
                len(presented.citations), len(presented.warnings),
            )

            return presented

        except LLMError as exc:
            # Layer 4 failure is NOT fatal — we still have validated data
            timing.error = str(exc)
            self._finalize_timing(timing)
            envelope.add_layer_timing(timing)
            logger.error("Layer 4 LLM error: %s", exc)

            # Fallback: create a minimal response from validated data
            presented = self._fallback_presentation(validated)
            envelope.layer_4_output = presented
            return presented

    def _build_presenter_prompt(
        self,
        validated: ValidatedResults,
        sanitized: SanitizedQuery,
    ) -> str:
        """Build the Layer 4 prompt from validated results.

        Contains ONLY validated data and intent context.
        No raw input. No unvalidated candidates.
        """
        records_data = [r.model_dump() for r in validated.records]

        prompt_data = {
            "intent": sanitized.intent.value,
            "query_type": sanitized.query_type.value,
            "material_name": sanitized.material_name,
            "property_names": sanitized.property_names,
            "validated_records": records_data,
            "schema_version": validated.schema_version,
        }

        if validated.relaxation_suggestions:
            prompt_data["relaxation_suggestions"] = validated.relaxation_suggestions

        if validated.dirty_data_summary:
            prompt_data["dirty_data_summary"] = validated.dirty_data_summary

        return (
            "Present these validated results to the user. Include citations "
            "for every property value. Flag any warnings (dirty data, heritage "
            "vetoes). Be concise.\n\n"
            "Return a JSON object with: 'response_text', 'citations' array "
            "(each with 'record_id', 'source', 'claim'), 'warnings' array, "
            "and 'confidence_summary'.\n\n"
            f"DATA:\n{json.dumps(prompt_data, indent=2, default=str)}"
        )

    def _parse_presenter_output(
        self,
        llm_text: str,
        validated: ValidatedResults,
    ) -> PresentedResponse:
        """Parse LLM output into PresentedResponse."""
        json_str = self._extract_json(llm_text)

        if json_str:
            try:
                parsed = json.loads(json_str)
                citations = []
                for c in parsed.get("citations", []):
                    citations.append(Citation(
                        record_id=c.get("record_id", "unknown"),
                        source=c.get("source", "unknown"),
                        claim=c.get("claim", ""),
                    ))

                return PresentedResponse(
                    response_text=parsed.get("response_text", llm_text),
                    citations=citations,
                    warnings=parsed.get("warnings", []),
                    confidence_summary=parsed.get("confidence_summary", ""),
                )
            except (json.JSONDecodeError, KeyError, ValueError):
                pass

        # Fallback: use LLM text as-is
        return self._fallback_presentation(validated, llm_text)

    def _fallback_presentation(
        self,
        validated: ValidatedResults,
        raw_text: Optional[str] = None,
    ) -> PresentedResponse:
        """Generate a minimal presentation from validated data.

        Used when Layer 4 LLM fails or returns unparseable output.
        """
        lines = []
        citations = []
        warnings = []

        for record in validated.records:
            lines.append(
                f"- {record.material_key} (Record: {record.record_id}, "
                f"Source: {record.source}, Confidence: {record.confidence_score:.2f})"
            )
            citations.append(Citation(
                record_id=record.record_id,
                source=record.source,
                claim=f"Material {record.material_key} validated",
            ))
            if record.dirty_flag:
                warnings.append(
                    f"Record {record.record_id} contains non-typed data "
                    f"in fields: {', '.join(record.dirty_fields)}"
                )
            if record.heritage_vetoed:
                msg = f"Heritage veto on {record.material_key}"
                if record.heritage_requires_acknowledgment:
                    msg += " (SAFETY-CRITICAL: requires engineer acknowledgment)"
                warnings.append(msg)

        response_text = raw_text or "Validated Results:\n" + "\n".join(lines)

        return PresentedResponse(
            response_text=response_text,
            citations=citations,
            warnings=warnings,
            confidence_summary=(
                f"{len(validated.records)} records validated, "
                f"{validated.candidates_rejected} rejected"
            ),
        )

    # =========================================================================
    # Utilities
    # =========================================================================

    @staticmethod
    def _extract_json(text: str) -> Optional[str]:
        """Extract JSON from LLM output that may be wrapped in markdown.

        Handles:
          - Pure JSON
          - JSON wrapped in ```json ... ```
          - JSON wrapped in ``` ... ```
          - JSON embedded in prose (finds first { to last })
        """
        text = text.strip()

        # Try direct parse first
        if text.startswith("{") or text.startswith("["):
            return text

        # Try markdown code blocks
        if "```json" in text:
            start = text.index("```json") + 7
            end = text.index("```", start)
            return text[start:end].strip()

        if "```" in text:
            start = text.index("```") + 3
            end = text.index("```", start)
            extracted = text[start:end].strip()
            if extracted.startswith("{") or extracted.startswith("["):
                return extracted

        # Try finding JSON object in text
        brace_start = text.find("{")
        if brace_start >= 0:
            # Find matching closing brace
            depth = 0
            for i in range(brace_start, len(text)):
                if text[i] == "{":
                    depth += 1
                elif text[i] == "}":
                    depth -= 1
                    if depth == 0:
                        return text[brace_start:i + 1]

        return None

    @staticmethod
    def _finalize_timing(timing: LayerTiming) -> None:
        """Set completion timestamp and duration on a timing record."""
        timing.completed_at = datetime.now(timezone.utc).isoformat()
        started = datetime.fromisoformat(timing.started_at)
        completed = datetime.fromisoformat(timing.completed_at)
        timing.duration_ms = (completed - started).total_seconds() * 1000
