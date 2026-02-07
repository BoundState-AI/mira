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
GPTL Prompts - Versioned Claude prompts for all GPTL layers
============================================================

All Claude prompts for GPTL are versioned and centralized here.
Changing a prompt = new version = new config_hash.

Prompt Design Principles:
1. Structured JSON output for deterministic parsing
2. Explicit reasoning requirements
3. Confidence calibration
4. Citation requirements
5. Bounded outputs with refusal on missing evidence

Compliance: SWE-032 (Data Validation), SWE-033 (Requirements Traceability)
Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any

__safety_critical__: bool = True


# =============================================================================
# OUTPUT SCHEMA DEFINITIONS (JSON Schema format)
# =============================================================================

# L0 Schemas
L0_DERIVATION_VALIDATION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["valid", "confidence", "reasoning"],
    "properties": {
        "valid": {"type": "boolean"},
        "corrected_types": {
            "type": "array",
            "items": {"type": "string"},
        },
        "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
        "reasoning": {"type": "string", "maxLength": 200},
    },
    "additionalProperties": False,
}

L0_NOISE_DETECTION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["is_noise_candidate", "noise_markers", "confidence", "reasoning"],
    "properties": {
        "is_noise_candidate": {"type": "boolean"},
        "noise_markers": {
            "type": "array",
            "items": {"type": "string"},
        },
        "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
        "reasoning": {"type": "string", "maxLength": 150},
    },
    "additionalProperties": False,
}

# L2 Schemas
L2_INTENT_CLASSIFICATION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["frame_id", "category", "decision_question", "confidence", "reasoning"],
    "properties": {
        "frame_id": {"type": "string"},
        "category": {"type": "string"},
        "decision_question": {"type": "string"},
        "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
        "reasoning": {"type": "string", "maxLength": 250},
        "evidence_requirements": {
            "type": "object",
            "properties": {
                "types": {"type": "array", "items": {"type": "string"}},
                "min_count": {"type": "integer", "minimum": 1},
            },
        },
        "escalate_to_opus": {"type": "boolean"},
    },
    "additionalProperties": False,
}

L2_INTENT_DISAMBIGUATION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["frame_id", "category", "decision_question", "confidence", "reasoning"],
    "properties": {
        "frame_id": {"type": "string"},
        "category": {"type": "string"},
        "decision_question": {"type": "string"},
        "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
        "reasoning": {"type": "string", "maxLength": 500},
        "alternative_interpretations": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "interpretation": {"type": "string"},
                    "likelihood": {"type": "number", "minimum": 0.0, "maximum": 1.0},
                },
            },
        },
        "evidence_requirements": {
            "type": "object",
            "properties": {
                "types": {"type": "array", "items": {"type": "string"}},
                "min_count": {"type": "integer", "minimum": 1},
                "required_entity_classes": {"type": "array", "items": {"type": "string"}},
            },
        },
        "clarifying_questions": {"type": "array", "items": {"type": "string"}},
    },
    "additionalProperties": False,
}

# L3 Schemas
L3_SEMANTIC_CHECK_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["decision", "confidence", "reasoning"],
    "properties": {
        "decision": {"type": "string", "enum": ["KEEP", "ELIMINATE", "DEPRIORITIZE"]},
        "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
        "reasoning": {"type": "string", "maxLength": 200},
    },
    "additionalProperties": False,
}

L3_CONSTRAINT_VIOLATION_EXPLAIN_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["explanation", "confidence"],
    "properties": {
        "explanation": {"type": "string", "maxLength": 300},
        "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
    },
    "additionalProperties": False,
}

# L4 Schemas
L4_ANOMALY_EXPLANATION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["explanation", "possible_causes", "recommendation", "severity"],
    "properties": {
        "explanation": {"type": "string", "maxLength": 500},
        "possible_causes": {"type": "array", "items": {"type": "string"}},
        "recommendation": {"type": "string"},
        "severity": {"type": "string", "enum": ["low", "medium", "high"]},
    },
    "additionalProperties": False,
}

L4_TEMPORAL_DERIVATIVE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["temporal_trend", "supersession_detected"],
    "properties": {
        "temporal_trend": {"type": "string"},
        "supersession_detected": {"type": "boolean"},
        "supersession_details": {"type": "array", "items": {"type": "string"}},
        "staleness_warnings": {"type": "array", "items": {"type": "string"}},
        "timeline_implication": {"type": "string"},
    },
    "additionalProperties": False,
}

# L5 Schemas
L5_SYNTHESIS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["finding", "implication", "action", "timeline", "confidence", "evidence"],
    "properties": {
        "finding": {"type": "string", "maxLength": 1000},
        "implication": {"type": "string", "maxLength": 500},
        "action": {"type": "string", "maxLength": 500},
        "timeline": {"type": "string"},
        "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
        "confidence_interval": {
            "type": "array",
            "items": {"type": "number"},
            "minItems": 2,
            "maxItems": 2,
        },
        "confidence_drivers": {"type": "array", "items": {"type": "string"}},
        "evidence": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["doc_id", "snippet", "relevance_score", "evidence_type"],
                "properties": {
                    "doc_id": {"type": "string"},
                    "doc_title": {"type": "string"},
                    "section": {"type": "string"},
                    "snippet": {"type": "string", "maxLength": 500},
                    "relevance_score": {"type": "number", "minimum": 0.0, "maximum": 1.0},
                    "evidence_type": {"type": "string"},
                },
            },
        },
        "evidence_conflicts_detected": {"type": "boolean"},
        "conflict_description": {"type": "string"},
        "insufficient_evidence": {"type": "boolean"},
        "refusal_reason": {"type": "string"},
    },
    "additionalProperties": False,
}

L5_SYNTHESIS_CRITICAL_SCHEMA: dict[str, Any] = {
    **L5_SYNTHESIS_SCHEMA,
    "properties": {
        **L5_SYNTHESIS_SCHEMA["properties"],
        "evidence_gaps": {"type": "array", "items": {"type": "string"}},
        "risk_factors": {"type": "array", "items": {"type": "string"}},
        "edge_cases_considered": {"type": "array", "items": {"type": "string"}},
    },
}

L5_CONFIDENCE_CALIBRATION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["calibrated_confidence", "confidence_interval", "calibration_reasoning"],
    "properties": {
        "calibrated_confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
        "confidence_interval": {
            "type": "array",
            "items": {"type": "number"},
            "minItems": 2,
            "maxItems": 2,
        },
        "calibration_reasoning": {"type": "string", "maxLength": 250},
        "confidence_drivers": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "factor": {"type": "string"},
                    "impact": {"type": "string", "enum": ["positive", "negative"]},
                    "weight": {"type": "number", "minimum": 0.0, "maximum": 1.0},
                },
            },
        },
    },
    "additionalProperties": False,
}

# Schema registry
OUTPUT_SCHEMAS: dict[str, dict[str, Any]] = {
    "L0_DERIVATION_VALIDATION_V1": L0_DERIVATION_VALIDATION_SCHEMA,
    "L0_NOISE_DETECTION_V1": L0_NOISE_DETECTION_SCHEMA,
    "L2_INTENT_CLASSIFICATION_V1": L2_INTENT_CLASSIFICATION_SCHEMA,
    "L2_INTENT_DISAMBIGUATION_V1": L2_INTENT_DISAMBIGUATION_SCHEMA,
    "L3_SEMANTIC_CHECK_V1": L3_SEMANTIC_CHECK_SCHEMA,
    "L3_CONSTRAINT_VIOLATION_EXPLAIN_V1": L3_CONSTRAINT_VIOLATION_EXPLAIN_SCHEMA,
    "L4_ANOMALY_EXPLANATION_V1": L4_ANOMALY_EXPLANATION_SCHEMA,
    "L4_TEMPORAL_DERIVATIVE_V1": L4_TEMPORAL_DERIVATIVE_SCHEMA,
    "L5_SYNTHESIS_V1": L5_SYNTHESIS_SCHEMA,
    "L5_SYNTHESIS_CRITICAL_V1": L5_SYNTHESIS_CRITICAL_SCHEMA,
    "L5_CONFIDENCE_CALIBRATION_V1": L5_CONFIDENCE_CALIBRATION_SCHEMA,
}


# =============================================================================
# PROMPT VERSIONING
# =============================================================================

@dataclass
class VersionedPrompt:
    """A versioned prompt with metadata and output schema."""
    name: str
    version: str
    prompt_template: str
    description: str
    layer: str  # L0, L2, L3, L4, L5
    model_tier: str  # haiku, sonnet, opus
    output_schema: dict[str, Any] | None = field(default=None)

    def __post_init__(self):
        """Set output schema from registry if not provided."""
        if self.output_schema is None:
            key = f"{self.name}_V{self.version.replace('.', '_')}" if '_V' not in self.name else self.name
            # Try to find schema in registry
            for registry_key in OUTPUT_SCHEMAS:
                if self.name in registry_key:
                    self.output_schema = OUTPUT_SCHEMAS[registry_key]
                    break

    @property
    def prompt_hash(self) -> str:
        """Compute hash of the prompt for determinism."""
        content = f"{self.name}:{self.version}:{self.prompt_template}"
        return hashlib.sha256(content.encode()).hexdigest()[:12]

    def format(self, **kwargs: Any) -> str:
        """Format the prompt with provided arguments."""
        return self.prompt_template.format(**kwargs)

    def get_output_schema(self) -> dict[str, Any] | None:
        """Get the expected output schema for this prompt."""
        return self.output_schema


# =============================================================================
# L0: FEATURE EXTRACTION / DERIVATION VALIDATION (HAIKU)
# =============================================================================

L0_DERIVATION_VALIDATION_V1 = VersionedPrompt(
    name="L0_DERIVATION_VALIDATION",
    version="1.0",
    layer="L0",
    model_tier="haiku",
    description="Validates evidence type derivation for a document at ingestion time",
    prompt_template="""You are validating evidence type derivation for a document.

Document metadata:
- doc_id: {doc_id}
- doc_type: {doc_type}
- has_measurements: {has_measurements}
- has_test_conditions: {has_test_conditions}
- has_spec_references: {has_spec_references}
- has_tables: {has_tables}
- has_figures: {has_figures}
- detected_entities: {entities}

Content sample (first 500 chars):
{content_sample}

Rule-derived evidence_types: {derived_types}

Evaluate if this derivation is correct. Consider:
1. Does the content actually contain the evidence type's defining characteristics?
2. Are there evidence types that should be added?
3. Are there evidence types that should be removed?

Respond with JSON:
{{
  "valid": true/false,
  "corrected_types": ["type1", "type2"],  // only if valid=false
  "confidence": 0.0-1.0,
  "reasoning": "brief explanation (max 50 words)"
}}

IMPORTANT: Only output valid JSON. No additional text."""
)


L0_NOISE_DETECTION_V1 = VersionedPrompt(
    name="L0_NOISE_DETECTION",
    version="1.0",
    layer="L0",
    model_tier="haiku",
    description="Detects noise markers in document content",
    prompt_template="""Analyze this document excerpt for noise indicators.

Document metadata:
- doc_id: {doc_id}
- doc_type: {doc_type}

Content sample:
{content_sample}

Identify noise markers that suggest this is NOT useful technical content:
- Marketing language (CTAs, promotional tone)
- Generic web content (navigation, cookie notices)
- Outdated/deprecated content indicators
- Non-technical fluff

Respond with JSON:
{{
  "is_noise_candidate": true/false,
  "noise_markers": ["marker1", "marker2"],
  "confidence": 0.0-1.0,
  "reasoning": "brief explanation (max 30 words)"
}}

IMPORTANT: Only output valid JSON. No additional text."""
)


# =============================================================================
# L2: INTENT FRAMING (SONNET / OPUS)
# =============================================================================

L2_INTENT_CLASSIFICATION_V1 = VersionedPrompt(
    name="L2_INTENT_CLASSIFICATION",
    version="1.0",
    layer="L2",
    model_tier="sonnet",
    description="Classifies user intent and maps to decision question",
    prompt_template="""You are classifying user intent for a {domain} document intelligence system.

User query: "{query}"

Available intent frames:
{intent_frames_json}

For each frame, you have:
- frame_id: identifier
- category: intent category
- decision_question: the real question being asked
- evidence_requirements: what evidence types are needed

Classify this query. Consider:
1. What is the user actually trying to decide?
2. What evidence would answer their real question?
3. How confident are you in this classification?
4. Is this query complex enough to warrant escalation to a more capable model?

Respond with JSON:
{{
  "frame_id": "selected_frame_id",
  "category": "intent_category",
  "decision_question": "the real question the user is asking",
  "confidence": 0.0-1.0,
  "reasoning": "why this frame matches (max 50 words)",
  "evidence_requirements": {{
    "types": ["type1", "type2"],
    "min_count": 2
  }},
  "escalate_to_opus": true/false
}}

If no frame matches well, use:
- frame_id: "general_query"
- category: "general_query"
- escalate_to_opus: true (for complex/ambiguous queries)

IMPORTANT: Only output valid JSON. No additional text."""
)


L2_INTENT_DISAMBIGUATION_V1 = VersionedPrompt(
    name="L2_INTENT_DISAMBIGUATION",
    version="1.0",
    layer="L2",
    model_tier="opus",
    description="Disambiguates complex or ambiguous intents (escalated from Sonnet)",
    prompt_template="""You are disambiguating a complex query for a {domain} document intelligence system.

User query: "{query}"

Sonnet's initial classification:
{sonnet_classification}

Sonnet escalated because: {escalation_reason}

Available intent frames:
{intent_frames_json}

This query requires deeper analysis. Consider:
1. Are there multiple valid interpretations?
2. What implicit assumptions is the user making?
3. What is the REAL decision they need to make?
4. What evidence would definitively answer their question?

Respond with JSON:
{{
  "frame_id": "selected_frame_id",
  "category": "intent_category",
  "decision_question": "the precise decision question",
  "confidence": 0.0-1.0,
  "reasoning": "detailed reasoning for this interpretation (max 100 words)",
  "alternative_interpretations": [
    {{"interpretation": "alternative 1", "likelihood": 0.0-1.0}},
    {{"interpretation": "alternative 2", "likelihood": 0.0-1.0}}
  ],
  "evidence_requirements": {{
    "types": ["type1", "type2"],
    "min_count": 2,
    "required_entity_classes": ["material", "standard"]
  }},
  "clarifying_questions": ["question1", "question2"]  // if truly ambiguous
}}

IMPORTANT: Only output valid JSON. No additional text."""
)


# =============================================================================
# L3: NEGATIVE SELECTION / SEMANTIC CHECKS (HAIKU)
# =============================================================================

L3_SEMANTIC_CHECK_V1 = VersionedPrompt(
    name="L3_SEMANTIC_CHECK",
    version="1.0",
    layer="L3",
    model_tier="haiku",
    description="Semantic constraint check for ambiguous elimination cases",
    prompt_template="""You are evaluating if a document should be eliminated from search results.

Query intent: {decision_question}
Required evidence types: {required_evidence}

Document metadata:
- doc_id: {doc_id}
- doc_type: {doc_type}
- derived_evidence_types: {evidence_types}
- domain_scores: {domain_scores}
- tags: {tags}

Content sample:
{content_sample}

The rule-based filter is uncertain about this document.

Should this document be:
1. KEEP - relevant to the query, contains useful evidence
2. ELIMINATE - clearly irrelevant or violates constraints
3. DEPRIORITIZE - marginally relevant, should be ranked lower

Respond with JSON:
{{
  "decision": "KEEP" or "ELIMINATE" or "DEPRIORITIZE",
  "confidence": 0.0-1.0,
  "reasoning": "brief explanation (max 40 words)"
}}

IMPORTANT: Only output valid JSON. No additional text."""
)


L3_CONSTRAINT_VIOLATION_EXPLAIN_V1 = VersionedPrompt(
    name="L3_CONSTRAINT_VIOLATION_EXPLAIN",
    version="1.0",
    layer="L3",
    model_tier="haiku",
    description="Explains why a constraint was violated for audit",
    prompt_template="""A document was flagged by constraint rule: {rule_name}

Rule description: {rule_description}
Rule action: {rule_action}

Document:
- doc_id: {doc_id}
- doc_type: {doc_type}
- evidence_types: {evidence_types}

Violated conditions:
{violated_conditions}

Content sample:
{content_sample}

Provide a brief, human-readable explanation of why this document was {action_verb}.

Respond with JSON:
{{
  "explanation": "1-2 sentence explanation for audit log",
  "confidence": 0.0-1.0
}}

IMPORTANT: Only output valid JSON. No additional text."""
)


# =============================================================================
# L4: ANOMALY DETECTION (SONNET)
# =============================================================================

L4_ANOMALY_EXPLANATION_V1 = VersionedPrompt(
    name="L4_ANOMALY_EXPLANATION",
    version="1.0",
    layer="L4",
    model_tier="sonnet",
    description="Explains detected anomalies in survivor set",
    prompt_template="""You are analyzing anomalies detected in document search results.

Query: "{query}"
Decision question: {decision_question}

Detected anomaly: {anomaly_type}
Anomaly details: {anomaly_details}

Affected documents:
{affected_documents}

Explain this anomaly in terms the user can understand. Consider:
1. What makes this unusual?
2. What might explain it?
3. How should the user interpret results given this anomaly?

Respond with JSON:
{{
  "explanation": "clear explanation of the anomaly (max 100 words)",
  "possible_causes": ["cause1", "cause2"],
  "recommendation": "how user should interpret results",
  "severity": "low" or "medium" or "high"
}}

IMPORTANT: Only output valid JSON. No additional text."""
)


L4_TEMPORAL_DERIVATIVE_V1 = VersionedPrompt(
    name="L4_TEMPORAL_DERIVATIVE",
    version="1.0",
    layer="L4",
    model_tier="sonnet",
    description="Analyzes temporal patterns in document set",
    prompt_template="""Analyze the temporal patterns in these documents related to: {query}

Documents with dates:
{documents_with_dates}

Identify:
1. Temporal trends (increasing/decreasing mentions, evolving standards)
2. Version supersession (newer docs replacing older)
3. Potential staleness (old docs that may be outdated)
4. Timeline implications for the user's decision

Respond with JSON:
{{
  "temporal_trend": "description of trend",
  "supersession_detected": true/false,
  "supersession_details": ["doc_a superseded by doc_b"],
  "staleness_warnings": ["doc_id is from YYYY, may be outdated"],
  "timeline_implication": "what this means for the decision"
}}

IMPORTANT: Only output valid JSON. No additional text."""
)


# =============================================================================
# L5: INTELLIGENCE SYNTHESIS (SONNET / OPUS)
# =============================================================================

L5_SYNTHESIS_V1 = VersionedPrompt(
    name="L5_SYNTHESIS",
    version="1.0",
    layer="L5",
    model_tier="sonnet",
    description="Synthesizes actionable intelligence from evidence",
    prompt_template="""You are generating actionable intelligence for a {domain} query.

Query: "{query}"
Decision question: "{decision_question}"
Intent category: {intent_category}

Evidence documents (ranked by relevance):
{evidence_with_citations}

Negative selection summary:
- Total candidates: {total_candidates}
- Eliminated: {eliminated} ({reduction_ratio}%)
- Survivors used: {survivors}

Generate a structured intelligence output. You MUST:
1. Cite specific documents for every factual claim
2. If evidence is insufficient, say so explicitly
3. If documents conflict, note the conflict
4. Provide actionable recommendations

Respond with JSON:
{{
  "finding": "What does the evidence support? Be specific, cite sources. (max 200 words)",
  "implication": "What does this mean for the decision at hand? (max 100 words)",
  "action": "What should the user do next? (max 100 words)",
  "timeline": "When does this matter? Use 'unknown' if insufficient date data.",

  "confidence": 0.0-1.0,
  "confidence_interval": [lower, upper],
  "confidence_drivers": ["reason1", "reason2"],

  "evidence": [
    {{
      "doc_id": "id",
      "doc_title": "title",
      "section": "section if known",
      "snippet": "relevant quote (max 100 chars)",
      "relevance_score": 0.0-1.0,
      "evidence_type": "type"
    }}
  ],

  "evidence_conflicts_detected": true/false,
  "conflict_description": "description if conflicts exist",

  "insufficient_evidence": true/false,
  "refusal_reason": "reason if insufficient evidence"
}}

CRITICAL RULES:
- NEVER make claims without citing a source document
- NEVER extrapolate beyond what the evidence shows
- If you cannot answer with confidence, set insufficient_evidence=true
- Use "bounded outputs with refusal on missing evidence" approach

IMPORTANT: Only output valid JSON. No additional text."""
)


L5_SYNTHESIS_CRITICAL_V1 = VersionedPrompt(
    name="L5_SYNTHESIS_CRITICAL",
    version="1.0",
    layer="L5",
    model_tier="opus",
    description="Synthesizes intelligence for critical/high-stakes queries",
    prompt_template="""You are generating intelligence for a CRITICAL {domain} query.

This is a high-stakes query requiring extra rigor. Categories that trigger critical mode:
- Failure prediction
- Liability assessment
- Safety-critical decisions
- Compliance/certification

Query: "{query}"
Decision question: "{decision_question}"
Intent category: {intent_category}
Quality tier: CRITICAL

Evidence documents (ranked by relevance):
{evidence_with_citations}

Negative selection summary:
- Total candidates: {total_candidates}
- Eliminated: {eliminated}
- Survivors: {survivors}

For this CRITICAL query, you must:
1. Be MORE conservative in claims
2. Highlight uncertainty more prominently
3. Identify gaps in evidence that matter for the decision
4. Consider failure modes and edge cases
5. Provide explicit caveats

Respond with JSON:
{{
  "finding": "Conservative, well-supported finding. Cite sources. (max 300 words)",
  "implication": "What does this mean? Include caveats. (max 150 words)",
  "action": "Recommended actions with risk considerations. (max 150 words)",
  "timeline": "When does this matter? Explicit about uncertainty.",

  "confidence": 0.0-1.0,
  "confidence_interval": [lower, upper],
  "confidence_drivers": ["reason1", "reason2"],

  "evidence": [
    {{
      "doc_id": "id",
      "doc_title": "title",
      "section": "section",
      "snippet": "relevant quote",
      "relevance_score": 0.0-1.0,
      "evidence_type": "type"
    }}
  ],

  "evidence_conflicts_detected": true/false,
  "conflict_description": "description if conflicts",

  "evidence_gaps": ["gap1", "gap2"],
  "risk_factors": ["risk1", "risk2"],
  "edge_cases_considered": ["case1", "case2"],

  "insufficient_evidence": true/false,
  "refusal_reason": "reason if insufficient"
}}

CRITICAL: For liability/safety queries, err on the side of caution.
Better to refuse than to provide unreliable guidance.

IMPORTANT: Only output valid JSON. No additional text."""
)


L5_CONFIDENCE_CALIBRATION_V1 = VersionedPrompt(
    name="L5_CONFIDENCE_CALIBRATION",
    version="1.0",
    layer="L5",
    model_tier="sonnet",
    description="Calibrates confidence for synthesis output",
    prompt_template="""Calibrate the confidence for this intelligence output.

Original synthesis:
{synthesis_json}

Evidence summary:
- Number of documents: {doc_count}
- Evidence types present: {evidence_types}
- Highest relevance score: {max_relevance}
- Evidence conflicts: {has_conflicts}

Query characteristics:
- Intent category: {intent_category}
- Quality tier: {quality_tier}

Evaluate confidence considering:
1. Evidence quantity (more docs = more confidence)
2. Evidence quality (primary types > contextual)
3. Evidence agreement (conflicts reduce confidence)
4. Query complexity (complex queries need more evidence)
5. Specificity of answer (vague answers = lower confidence)

Respond with JSON:
{{
  "calibrated_confidence": 0.0-1.0,
  "confidence_interval": [lower, upper],
  "calibration_reasoning": "why this confidence level (max 50 words)",
  "confidence_drivers": [
    {{"factor": "name", "impact": "positive" or "negative", "weight": 0.0-1.0}}
  ]
}}

IMPORTANT: Only output valid JSON. No additional text."""
)


# =============================================================================
# PROMPT REGISTRY
# =============================================================================

PROMPT_REGISTRY: dict[str, VersionedPrompt] = {
    # L0
    "L0_DERIVATION_VALIDATION_V1": L0_DERIVATION_VALIDATION_V1,
    "L0_NOISE_DETECTION_V1": L0_NOISE_DETECTION_V1,

    # L2
    "L2_INTENT_CLASSIFICATION_V1": L2_INTENT_CLASSIFICATION_V1,
    "L2_INTENT_DISAMBIGUATION_V1": L2_INTENT_DISAMBIGUATION_V1,

    # L3
    "L3_SEMANTIC_CHECK_V1": L3_SEMANTIC_CHECK_V1,
    "L3_CONSTRAINT_VIOLATION_EXPLAIN_V1": L3_CONSTRAINT_VIOLATION_EXPLAIN_V1,

    # L4
    "L4_ANOMALY_EXPLANATION_V1": L4_ANOMALY_EXPLANATION_V1,
    "L4_TEMPORAL_DERIVATIVE_V1": L4_TEMPORAL_DERIVATIVE_V1,

    # L5
    "L5_SYNTHESIS_V1": L5_SYNTHESIS_V1,
    "L5_SYNTHESIS_CRITICAL_V1": L5_SYNTHESIS_CRITICAL_V1,
    "L5_CONFIDENCE_CALIBRATION_V1": L5_CONFIDENCE_CALIBRATION_V1,
}


def get_prompt(name: str) -> VersionedPrompt:
    """Get a prompt by name."""
    if name not in PROMPT_REGISTRY:
        raise ValueError(f"Unknown prompt: {name}. Available: {list(PROMPT_REGISTRY.keys())}")
    return PROMPT_REGISTRY[name]


def get_all_prompt_hashes() -> dict[str, str]:
    """Get hashes of all prompts for config_hash computation."""
    return {name: prompt.prompt_hash for name, prompt in PROMPT_REGISTRY.items()}


def compute_prompts_hash() -> str:
    """Compute a combined hash of all prompts."""
    all_hashes = get_all_prompt_hashes()
    combined = ":".join(f"{k}={v}" for k, v in sorted(all_hashes.items()))
    return hashlib.sha256(combined.encode()).hexdigest()[:16]


# =============================================================================
# PROMPT FORMATTING HELPERS
# =============================================================================

def format_evidence_for_synthesis(
    documents: list[dict],
    max_snippet_len: int = 500,
) -> str:
    """Format evidence documents for synthesis prompts."""
    lines = []
    for i, doc in enumerate(documents, 1):
        snippet = doc.get("snippet", doc.get("text", ""))[:max_snippet_len]
        lines.append(f"""
Document {i}:
- ID: {doc.get('doc_id', 'unknown')}
- Title: {doc.get('title', 'untitled')}
- Type: {doc.get('evidence_type', 'unknown')}
- Relevance: {doc.get('relevance_score', 0.0):.2f}
- Content: {snippet}
""")
    return "\n".join(lines)


def format_intent_frames_for_classification(frames: list) -> str:
    """Format intent frames for classification prompts."""
    import json

    formatted = []
    for frame in frames:
        formatted.append({
            "frame_id": frame.frame_id if hasattr(frame, 'frame_id') else frame.get('frame_id'),
            "category": frame.category.value if hasattr(frame, 'category') else frame.get('category'),
            "decision_question": frame.decision_question if hasattr(frame, 'decision_question') else frame.get('decision_question'),
            "evidence_requirements": {
                "types": [t.value if hasattr(t, 'value') else t for t in (frame.evidence_requirements.types if hasattr(frame, 'evidence_requirements') else frame.get('evidence_requirements', {}).get('types', []))],
            }
        })
    return json.dumps(formatted, indent=2)


__all__ = [
    # Prompt class
    "VersionedPrompt",

    # Output schemas
    "OUTPUT_SCHEMAS",
    "L0_DERIVATION_VALIDATION_SCHEMA",
    "L0_NOISE_DETECTION_SCHEMA",
    "L2_INTENT_CLASSIFICATION_SCHEMA",
    "L2_INTENT_DISAMBIGUATION_SCHEMA",
    "L3_SEMANTIC_CHECK_SCHEMA",
    "L3_CONSTRAINT_VIOLATION_EXPLAIN_SCHEMA",
    "L4_ANOMALY_EXPLANATION_SCHEMA",
    "L4_TEMPORAL_DERIVATIVE_SCHEMA",
    "L5_SYNTHESIS_SCHEMA",
    "L5_SYNTHESIS_CRITICAL_SCHEMA",
    "L5_CONFIDENCE_CALIBRATION_SCHEMA",

    # L0 prompts
    "L0_DERIVATION_VALIDATION_V1",
    "L0_NOISE_DETECTION_V1",

    # L2 prompts
    "L2_INTENT_CLASSIFICATION_V1",
    "L2_INTENT_DISAMBIGUATION_V1",

    # L3 prompts
    "L3_SEMANTIC_CHECK_V1",
    "L3_CONSTRAINT_VIOLATION_EXPLAIN_V1",

    # L4 prompts
    "L4_ANOMALY_EXPLANATION_V1",
    "L4_TEMPORAL_DERIVATIVE_V1",

    # L5 prompts
    "L5_SYNTHESIS_V1",
    "L5_SYNTHESIS_CRITICAL_V1",
    "L5_CONFIDENCE_CALIBRATION_V1",

    # Registry and utilities
    "PROMPT_REGISTRY",
    "get_prompt",
    "get_all_prompt_hashes",
    "compute_prompts_hash",
    "format_evidence_for_synthesis",
    "format_intent_frames_for_classification",
]
