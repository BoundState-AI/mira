#!/usr/bin/env python3
"""
Module: Model Evaluation Harness
Purpose: Compare non-Anthropic LLM candidates on MIRA P0 behaviors.

BoundState AI 2026
Version: 1.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude "CC" <noreply@anthropic.com>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: NASA-STD-8739.8B, SWE-013
Safety Critical: False (evaluation tooling)

Runs test cases from test_cases.json across configurable model candidates,
scoring each on parseability, classification correctness, key-fact presence,
uncertainty discipline, latency, and token cost.

Produces:
  - results/results.json         (machine-readable per-case scores)
  - results/leaderboard.csv      (ranked model summary)
  - results/summary.md           (human-readable winner recommendation)

Usage:
  python -m tests.model_eval.eval_runner                              # defaults
  python -m tests.model_eval.eval_runner --models gpt-4o,mistral-large-latest
  python -m tests.model_eval.eval_runner --tier sonnet --provider openai

Environment variables:
  EVAL_OPENAI_API_KEY        OpenAI-compatible API key
  EVAL_OPENAI_BASE_URL       OpenAI-compatible base URL (default: https://api.openai.com/v1)
  EVAL_BEDROCK_REGION        AWS Bedrock region (default: us-east-1)
  EVAL_PROVIDER              Default provider: openai | bedrock | azure (default: openai)
  EVAL_MODELS_SONNET         Comma-separated Sonnet-tier candidate model IDs
  EVAL_MODELS_HAIKU          Comma-separated Haiku-tier candidate model IDs
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import os
import re
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from mira.utils.json_extract import ExtractionError, extract_json

logger = logging.getLogger("model_eval")

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
_HERE = Path(__file__).resolve().parent
_TEST_CASES_PATH = _HERE / "test_cases.json"
_RESULTS_DIR = _HERE / "results"

# ---------------------------------------------------------------------------
# Scoring weights (must sum to 1.0)
# ---------------------------------------------------------------------------
W_PARSEABLE = 0.30
W_CLASSIFICATION = 0.25
W_KEY_FACTS = 0.20
W_UNCERTAINTY = 0.15
W_LATENCY = 0.05
W_COST = 0.05

# Latency thresholds (seconds) for scoring
_LATENCY_EXCELLENT = 2.0   # 1.0 score
_LATENCY_GOOD = 5.0        # 0.7 score
_LATENCY_OK = 10.0         # 0.4 score
# >10s => 0.1

# Token-cost normalization: cost per 1K tokens (input, output) in USD
# Used to normalize across providers. Updated as pricing changes.
_DEFAULT_COST_PER_1K = {"input": 0.003, "output": 0.015}


# ============================================================================
# Provider abstraction
# ============================================================================


@dataclass
class LLMResponse:
    """Standardized response from any LLM provider."""
    text: str
    model: str
    input_tokens: int
    output_tokens: int
    latency_s: float
    raw: Optional[Dict[str, Any]] = None


class ProviderError(Exception):
    """Raised when a provider call fails."""


def _call_openai_compat(
    *,
    model: str,
    system: str,
    user: str,
    temperature: float = 0.0,
    max_tokens: int = 1024,
    base_url: Optional[str] = None,
    api_key: Optional[str] = None,
) -> LLMResponse:
    """Call an OpenAI-compatible chat/completions endpoint.

    Works with OpenAI, Azure OpenAI, Mistral, Groq, Together, vLLM,
    Ollama (with /v1 prefix), and any OpenAI-schema-compatible provider.
    """
    import httpx

    base = (base_url or os.environ.get("EVAL_OPENAI_BASE_URL", "")).strip()
    if not base:
        base = "https://api.openai.com/v1"
    base = base.rstrip("/")

    key = (api_key or os.environ.get("EVAL_OPENAI_API_KEY", "")).strip()
    headers: Dict[str, str] = {"Content-Type": "application/json"}
    if key:
        headers["Authorization"] = f"Bearer {key}"

    payload = {
        "model": model,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    }

    t0 = time.perf_counter()
    try:
        resp = httpx.post(
            f"{base}/chat/completions",
            json=payload,
            headers=headers,
            timeout=120.0,
        )
        resp.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise ProviderError(
            f"OpenAI-compat {model} HTTP {exc.response.status_code}: "
            f"{exc.response.text[:300]}"
        ) from exc
    except httpx.RequestError as exc:
        raise ProviderError(f"OpenAI-compat {model} request error: {exc}") from exc
    latency = time.perf_counter() - t0

    body = resp.json()
    usage = body.get("usage", {})
    choice = body.get("choices", [{}])[0]
    text = choice.get("message", {}).get("content", "")

    return LLMResponse(
        text=text,
        model=body.get("model", model),
        input_tokens=usage.get("prompt_tokens", 0),
        output_tokens=usage.get("completion_tokens", 0),
        latency_s=latency,
        raw=body,
    )


def _call_bedrock(
    *,
    model: str,
    system: str,
    user: str,
    temperature: float = 0.0,
    max_tokens: int = 1024,
    region: Optional[str] = None,
) -> LLMResponse:
    """Call AWS Bedrock converse API."""
    try:
        import boto3
    except ImportError:
        raise ProviderError("boto3 not installed; cannot use Bedrock provider")

    region = region or os.environ.get("EVAL_BEDROCK_REGION", "us-east-1")
    client = boto3.client("bedrock-runtime", region_name=region)

    t0 = time.perf_counter()
    request: Dict[str, Any] = {
        "modelId": model,
        "messages": [{"role": "user", "content": [{"text": user}]}],
        "inferenceConfig": {
            "temperature": temperature,
            "maxTokens": max_tokens,
        },
    }
    if system and system.strip():
        request["system"] = [{"text": system}]

    try:
        resp = client.converse(**request)
    except Exception as exc:
        raise ProviderError(f"Bedrock {model}: {exc}") from exc
    latency = time.perf_counter() - t0

    output = resp.get("output", {})
    message = output.get("message", {})
    text = ""
    for block in message.get("content", []):
        if "text" in block:
            text += block["text"]

    usage = resp.get("usage", {})
    return LLMResponse(
        text=text,
        model=model,
        input_tokens=usage.get("inputTokens", 0),
        output_tokens=usage.get("outputTokens", 0),
        latency_s=latency,
        raw=resp,
    )


def call_model(
    *,
    provider: str,
    model: str,
    system: str,
    user: str,
    temperature: float = 0.0,
    max_tokens: int = 1024,
) -> LLMResponse:
    """Dispatch to the correct provider."""
    if provider in ("openai", "azure", "mistral", "groq", "together", "ollama"):
        return _call_openai_compat(
            model=model, system=system, user=user,
            temperature=temperature, max_tokens=max_tokens,
        )
    elif provider == "bedrock":
        return _call_bedrock(
            model=model, system=system, user=user,
            temperature=temperature, max_tokens=max_tokens,
        )
    else:
        raise ProviderError(f"Unknown provider: {provider}")


# ============================================================================
# JSON extraction (mirrors production runtime extractor contract)
# ============================================================================


def extract_json_object(text: str) -> Optional[Dict[str, Any]]:
    """Extract first JSON object from text using the shared production helper."""
    try:
        parsed = extract_json(text, expect="object")
    except ExtractionError:
        return None
    return parsed if isinstance(parsed, dict) else None


def extract_verdict_line(text: str) -> Optional[str]:
    """Extract VERDICT_EXACT or FC_VERDICT from formatter output."""
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("VERDICT_EXACT:"):
            return stripped.split(":", 1)[1].strip()
        if stripped.startswith("FC_VERDICT:"):
            return stripped.split(":", 1)[1].strip()
    return None


# ============================================================================
# Scoring functions
# ============================================================================


@dataclass
class CaseScore:
    """Per-case scoring breakdown."""
    case_id: str
    model: str
    prompt_type: str
    parseable: float = 0.0
    classification: float = 0.0
    key_facts: float = 0.0
    uncertainty: float = 0.0
    latency_score: float = 0.0
    cost_score: float = 0.0
    weighted_total: float = 0.0
    latency_s: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    error: Optional[str] = None
    raw_response: str = ""
    parsed_output: Optional[Dict[str, Any]] = None


def _score_latency(seconds: float) -> float:
    if seconds <= _LATENCY_EXCELLENT:
        return 1.0
    if seconds <= _LATENCY_GOOD:
        return 0.7
    if seconds <= _LATENCY_OK:
        return 0.4
    return 0.1


def _score_cost(input_tokens: int, output_tokens: int) -> float:
    """Lower cost = higher score.  Normalized against a 'budget' baseline."""
    total_cost = (
        (input_tokens / 1000) * _DEFAULT_COST_PER_1K["input"]
        + (output_tokens / 1000) * _DEFAULT_COST_PER_1K["output"]
    )
    # Budget baseline: 500 input + 500 output tokens
    budget = (500 / 1000) * _DEFAULT_COST_PER_1K["input"] + (500 / 1000) * _DEFAULT_COST_PER_1K["output"]
    if total_cost <= budget:
        return 1.0
    if total_cost <= budget * 3:
        return 0.7
    if total_cost <= budget * 6:
        return 0.4
    return 0.1


def _score_parse_case(
    parsed: Optional[Dict[str, Any]],
    expected: Dict[str, Any],
    response_text: str,
) -> Tuple[float, float, float, float]:
    """Score a JSON-output prompt case (query_parse, bouncer, fracture_parse).

    Returns (parseable, classification, key_facts, uncertainty).
    """
    # --- Parseable (0 or 1) ---
    if parsed is None:
        return (0.0, 0.0, 0.0, 0.0)
    parseable = 1.0

    # --- Classification correctness ---
    classification_fields = expected.get("classification_fields", [])
    if not classification_fields:
        classification = 1.0
    else:
        hits = 0
        for fld in classification_fields:
            exp_val = expected.get(fld)
            got_val = parsed.get(fld)
            if exp_val is not None and got_val is not None:
                if isinstance(exp_val, str) and isinstance(got_val, str):
                    if exp_val.lower() == got_val.lower():
                        hits += 1
                elif exp_val == got_val:
                    hits += 1
            elif exp_val is None and got_val is None:
                hits += 1
        classification = hits / len(classification_fields) if classification_fields else 1.0

    # --- Key facts present ---
    key_fields = expected.get("key_fields", [])
    if not key_fields:
        key_facts = 1.0
    else:
        present = 0
        for fld in key_fields:
            val = parsed.get(fld)
            if val is not None and val != "" and val != []:
                present += 1
        key_facts = present / len(key_fields) if key_fields else 1.0

    # --- Uncertainty discipline ---
    # Check that null-expected fields are actually null, and that the model
    # didn't hallucinate values for fields that should be absent.
    null_fields = expected.get("null_fields", [])
    hallucination_traps = expected.get("hallucination_traps", [])
    checks = null_fields + hallucination_traps
    if not checks:
        uncertainty = 1.0
    else:
        correct = 0
        for fld in checks:
            val = parsed.get(fld)
            if val is None:
                correct += 1
        uncertainty = correct / len(checks) if checks else 1.0

    return (parseable, classification, key_facts, uncertainty)


def _score_formatter_case(
    response_text: str,
    expected: Dict[str, Any],
) -> Tuple[float, float, float, float]:
    """Score a formatter-output prompt case (response_format, fc_format).

    Returns (parseable, classification, key_facts, uncertainty).
    """
    # --- Parseable: verdict line present? ---
    verdict = extract_verdict_line(response_text)
    parseable = 1.0 if verdict else 0.0

    # --- Classification: verdict matches expected? ---
    expected_verdict = expected.get("expected_verdict")
    if expected_verdict and verdict:
        classification = 1.0 if verdict.upper() == expected_verdict.upper() else 0.0
    elif not expected_verdict:
        classification = 1.0
    else:
        classification = 0.0

    # --- Key facts: required phrases present in response ---
    required_phrases = expected.get("required_phrases", [])
    if not required_phrases:
        key_facts = 1.0
    else:
        text_lower = response_text.lower()
        hits = sum(1 for p in required_phrases if p.lower() in text_lower)
        key_facts = hits / len(required_phrases)

    # --- Uncertainty: prohibited phrases absent ---
    prohibited_phrases = expected.get("prohibited_phrases", [])
    if not prohibited_phrases:
        uncertainty = 1.0
    else:
        text_lower = response_text.lower()
        violations = sum(1 for p in prohibited_phrases if p.lower() in text_lower)
        uncertainty = 1.0 - (violations / len(prohibited_phrases))

    return (parseable, classification, key_facts, uncertainty)


def score_case(
    case: Dict[str, Any],
    response: Optional[LLMResponse],
    error: Optional[str] = None,
) -> CaseScore:
    """Compute the full weighted score for a single test case."""
    cs = CaseScore(
        case_id=case["id"],
        model=response.model if response else "N/A",
        prompt_type=case["prompt_type"],
    )

    if error or response is None:
        cs.error = error or "No response"
        return cs

    cs.raw_response = response.text
    cs.latency_s = response.latency_s
    cs.input_tokens = response.input_tokens
    cs.output_tokens = response.output_tokens

    prompt_type = case["prompt_type"]
    expected = case.get("expected", {})

    if prompt_type in ("query_parse", "bouncer", "fracture_parse"):
        parsed = extract_json_object(response.text)
        cs.parsed_output = parsed
        cs.parseable, cs.classification, cs.key_facts, cs.uncertainty = (
            _score_parse_case(parsed, expected, response.text)
        )
    elif prompt_type in ("response_format", "fc_format"):
        cs.parseable, cs.classification, cs.key_facts, cs.uncertainty = (
            _score_formatter_case(response.text, expected)
        )
    else:
        # Unknown prompt type — only score parseability
        parsed = extract_json_object(response.text)
        cs.parsed_output = parsed
        cs.parseable = 1.0 if parsed is not None else 0.0

    cs.latency_score = _score_latency(response.latency_s)
    cs.cost_score = _score_cost(response.input_tokens, response.output_tokens)

    cs.weighted_total = (
        W_PARSEABLE * cs.parseable
        + W_CLASSIFICATION * cs.classification
        + W_KEY_FACTS * cs.key_facts
        + W_UNCERTAINTY * cs.uncertainty
        + W_LATENCY * cs.latency_score
        + W_COST * cs.cost_score
    )

    return cs


# ============================================================================
# Prompt dispatch — map test case prompt_type to system prompts
# ============================================================================

# These are extracted verbatim from the production codebase.
# The harness sends the same system prompt so we evaluate whether the
# candidate model can follow the *exact same* contract.

SYSTEM_PROMPTS: Dict[str, str] = {}


def _load_system_prompts() -> None:
    """Lazy-load system prompts from the production codebase.

    Falls back to bundled copies if production files aren't importable.
    """
    global SYSTEM_PROMPTS
    if SYSTEM_PROMPTS:
        return

    # Try importing from production code on sys.path
    prompts_loaded = False
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
        from mira.api.routers.mira_v4 import (
            _PARSE_SYSTEM_PROMPT,
            _RESPONSE_SYSTEM_PROMPT,
        )
        SYSTEM_PROMPTS["query_parse"] = _PARSE_SYSTEM_PROMPT
        SYSTEM_PROMPTS["response_format"] = _RESPONSE_SYSTEM_PROMPT
        prompts_loaded = True
    except Exception:
        pass

    try:
        from mira.bsmh.bouncer import _BOUNCER_SYSTEM_PROMPT
        SYSTEM_PROMPTS["bouncer"] = _BOUNCER_SYSTEM_PROMPT
        prompts_loaded = True
    except Exception:
        pass

    try:
        from mira.bsmh.response_formatter import (
            _FORMATTER_SYSTEM_PROMPT,
            _FC_FORMATTER_SYSTEM_PROMPT,
        )
        SYSTEM_PROMPTS["response_format"] = SYSTEM_PROMPTS.get(
            "response_format", _FORMATTER_SYSTEM_PROMPT
        )
        SYSTEM_PROMPTS["fc_format"] = _FC_FORMATTER_SYSTEM_PROMPT
        prompts_loaded = True
    except Exception:
        pass

    try:
        from mira.bsmh.service import _FC_CONTEXT_PARSE_PROMPT
        SYSTEM_PROMPTS["fracture_parse"] = _FC_CONTEXT_PARSE_PROMPT
        prompts_loaded = True
    except Exception:
        pass

    if not prompts_loaded:
        logger.warning(
            "Could not import production prompts.  Using bundled fallbacks."
        )
        _load_bundled_prompts()


def _load_bundled_prompts() -> None:
    """Hardcoded prompt copies as fallback for standalone execution."""
    SYSTEM_PROMPTS["query_parse"] = (
        'You are a NASA materials engineer AI for the MIRA system.\n'
        'Your job: given a query about materials for a specific application/environment,\n'
        'RECOMMEND specific materials that would work, AND extract the environment details.\n\n'
        'Return ONLY valid JSON with these fields:\n'
        '{\n'
        '  "intent": "<one of: compatibility_query, risk_query, materials_query, '
        'property_query, comparison, recommendation, general_search>",\n'
        '  "safety_context": "<one of: oxygen, hydrogen, cryogenic, high_pressure, general>",\n'
        '  "domain_scope": "<one of: in_scope, out_of_scope, uncertain>",\n'
        '  "scope_reason": "<short reason for scope classification>",\n'
        '  "material_key": "<specific material name/spec if user named one, or null>",\n'
        '  "candidate_materials": [\n'
        '    "<specific material designations that would work for this application>"\n'
        '  ],\n'
        '  "material_families": ["<broader material families to search>"],\n'
        '  "material_type": "<one of: Metal, Polymer, Adhesive, Coating, Composite, Foam, null>",\n'
        '  "environment": {\n'
        '    "temperature_c": null,\n'
        '    "pressure_kpa": null,\n'
        '    "o2_pct": null,\n'
        '    "fluid_medium": null,\n'
        '    "duration_hr": null,\n'
        '    "cycles": null\n'
        '  },\n'
        '  "reasoning": "<1-2 sentences explaining why these materials were chosen>",\n'
        '  "filters": {}\n'
        '}\n\n'
        'CRITICAL RULES:\n'
        '- candidate_materials is the MOST IMPORTANT field. List 5-15 specific materials.\n'
        '- safety_context: "oxygen" if O2/LOX/GOX, "hydrogen" if H2/LH2/GH2, '
        '"cryogenic" if T < -73C, "high_pressure" if P > 20684 kPa, else "general".\n'
        '- domain_scope: "in_scope" for NASA materials/process questions, '
        '"out_of_scope" for unrelated prompts, "uncertain" if ambiguous.\n'
    )

    SYSTEM_PROMPTS["bouncer"] = (
        'You are a retired NASA Materials & Processes engineer with 40 years of '
        'Shuttle-era experience.\nYou ONLY handle materials science and M&P engineering questions.\n\n'
        'Return STRICT JSON only:\n'
        '{\n'
        '  "status": "accepted" | "rejected",\n'
        '  "rejection_reason": "string or null",\n'
        '  "structured_query": {\n'
        '    "material": "primary material string or null",\n'
        '    "materials": ["list of explicitly requested materials"],\n'
        '    "environment": "string or null",\n'
        '    "pressure_psi": null,\n'
        '    "temperature_f": null,\n'
        '    "o2_pct": null,\n'
        '    "intent": "compatibility_check|lookup|comparison|recommendation|mua_precedent|general",\n'
        '    "original_query": "exact original query"\n'
        '  }\n'
        '}\n'
    )

    SYSTEM_PROMPTS["fracture_parse"] = (
        'You are a NASA fracture control engineer. Extract structured context '
        'from the user\'s query.\n\n'
        'Return STRICT JSON only with these fields (use null for anything not '
        'explicitly stated):\n'
        '{\n'
        '  "material": "string or null",\n'
        '  "part_name": "string or null",\n'
        '  "pressure_boundary": true/false/null,\n'
        '  "consequence_of_failure": "catastrophic"|"critical"|"non_critical"|null,\n'
        '  "inspectability": "inspectable"|"limited_access"|"non_inspectable"|null,\n'
        '  "geometry_type": "pressure_vessel"|"fitting"|"line"|"structural"|"fastener"|"mechanism"|"other"|null,\n'
        '  "material_condition": "wrought"|"cast"|"forged"|"welded"|"am_printed"|"powder_metallurgy"|null,\n'
        '  "center_code": "MSFC"|"JSC"|"KSC"|"GRC"|null,\n'
        '  "design_life_cycles": null,\n'
        '  "operating_pressure_psi": null,\n'
        '  "operating_pressure_unit": null,\n'
        '  "operating_temperature_f": null,\n'
        '  "operating_temperature_unit": null,\n'
        '  "proof_factor": null\n'
        '}\n'
    )

    SYSTEM_PROMPTS["response_format"] = (
        'You are a senior NASA Materials & Processes engineer writing assessment responses.\n'
        'Given a deterministic decision packet, write a concise engineering assessment.\n\n'
        'STRUCTURE:\n'
        '1. First line MUST be exactly: VERDICT_EXACT: <decision.verdict>\n'
        '2. One-sentence engineering answer.\n'
        '3. Material-by-material summary.\n'
        '4. Limitations and next steps (if any).\n\n'
        'PROHIBITED: "signal", "compatibility signal", "determination set", '
        'raw decimal scores, "score" as noun, "evidence volume is below minimum threshold".\n'
    )

    SYSTEM_PROMPTS["fc_format"] = (
        'You are a senior NASA structural engineer writing fracture control assessments.\n'
        'Given a deterministic fracture classification result, write a concise response.\n\n'
        'STRUCTURE:\n'
        '1. First line MUST be exactly: FC_VERDICT: <decision.verdict>\n'
        '2. One-sentence classification.\n'
        '3. Applicable FCRs.\n'
        '4. NDE requirements.\n'
        '5. Required documentation.\n'
    )


# ============================================================================
# Default candidate models
# ============================================================================

# These are placeholders.  Override via CLI --models or env vars.
# GovCloud-available IDs are noted in comments.

DEFAULT_SONNET_CANDIDATES = [
    "gpt-4o",                      # OpenAI GPT-4o
    "gpt-4o-mini",                 # OpenAI GPT-4o-mini (cost baseline)
    "mistral-large-latest",        # Mistral Large
    # Bedrock / GovCloud IDs (uncomment when credentials available):
    # "us.meta.llama3-3-70b-instruct-v1:0",
    # "us.amazon.nova-pro-v1:0",
    # "us.mistral.mistral-large-2411-v1:0",
]

DEFAULT_HAIKU_CANDIDATES = [
    "gpt-4o-mini",                 # OpenAI GPT-4o-mini
    "mistral-small-latest",        # Mistral Small
    "gpt-3.5-turbo",              # OpenAI GPT-3.5-turbo (cost floor)
    # Bedrock / GovCloud IDs:
    # "us.meta.llama3-2-3b-instruct-v1:0",
    # "us.amazon.nova-lite-v1:0",
]


# ============================================================================
# Test case loading
# ============================================================================


def load_test_cases(path: Optional[Path] = None) -> List[Dict[str, Any]]:
    """Load test cases from JSON file."""
    p = path or _TEST_CASES_PATH
    with open(p, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data["test_cases"]


# ============================================================================
# Main runner
# ============================================================================


@dataclass
class ModelResult:
    """Aggregate results for a single model."""
    model: str
    tier: str  # "sonnet" or "haiku"
    provider: str
    total_cases: int = 0
    avg_parseable: float = 0.0
    avg_classification: float = 0.0
    avg_key_facts: float = 0.0
    avg_uncertainty: float = 0.0
    avg_latency_score: float = 0.0
    avg_cost_score: float = 0.0
    weighted_avg: float = 0.0
    avg_latency_s: float = 0.0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    failures: int = 0
    case_scores: List[CaseScore] = field(default_factory=list)


def _resolve_temperature(case: Dict[str, Any]) -> float:
    """Determine temperature for a test case.  Default 0 for determinism."""
    return case.get("temperature", 0.0)


def _resolve_max_tokens(case: Dict[str, Any]) -> int:
    """Determine max_tokens for a test case."""
    prompt_type = case["prompt_type"]
    defaults = {
        "query_parse": 1024,
        "bouncer": 512,
        "fracture_parse": 1024,
        "response_format": 2048,
        "fc_format": 2048,
    }
    return case.get("max_tokens", defaults.get(prompt_type, 1024))


def run_eval(
    *,
    provider: str,
    models: List[str],
    tier: str,
    cases: List[Dict[str, Any]],
) -> List[ModelResult]:
    """Run evaluation across all models and cases.

    Args:
        provider: LLM provider name (openai, bedrock, etc.)
        models: List of model IDs to evaluate.
        tier: "sonnet" or "haiku" — filters test cases by target_tier.
        cases: Loaded test cases.

    Returns:
        List of ModelResult, one per model, sorted by weighted_avg descending.
    """
    _load_system_prompts()

    # Filter cases to the requested tier
    tier_cases = [c for c in cases if c.get("target_tier", "sonnet") == tier]
    if not tier_cases:
        logger.warning("No test cases for tier=%s", tier)
        return []

    results: List[ModelResult] = []

    for model_id in models:
        logger.info("=== Evaluating model: %s (tier=%s, provider=%s) ===", model_id, tier, provider)
        mr = ModelResult(model=model_id, tier=tier, provider=provider)

        for case in tier_cases:
            case_id = case["id"]
            prompt_type = case["prompt_type"]
            system_prompt = SYSTEM_PROMPTS.get(prompt_type, "")
            user_input = case["input"]
            temperature = _resolve_temperature(case)
            max_tokens = _resolve_max_tokens(case)

            logger.info("  Case %s (%s) ...", case_id, prompt_type)

            response: Optional[LLMResponse] = None
            error: Optional[str] = None
            try:
                response = call_model(
                    provider=provider,
                    model=model_id,
                    system=system_prompt,
                    user=user_input,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
            except ProviderError as exc:
                error = str(exc)
                logger.error("    FAIL: %s", error)
            except Exception as exc:
                error = f"Unexpected: {exc}"
                logger.error("    FAIL: %s", error)

            cs = score_case(case, response, error)
            cs.model = model_id
            mr.case_scores.append(cs)
            mr.total_cases += 1

            if error:
                mr.failures += 1
            else:
                logger.info(
                    "    OK: parse=%.2f class=%.2f facts=%.2f uncert=%.2f "
                    "lat=%.2fs total=%.2f",
                    cs.parseable, cs.classification, cs.key_facts,
                    cs.uncertainty, cs.latency_s, cs.weighted_total,
                )

        # Aggregate
        n = mr.total_cases or 1
        mr.avg_parseable = sum(c.parseable for c in mr.case_scores) / n
        mr.avg_classification = sum(c.classification for c in mr.case_scores) / n
        mr.avg_key_facts = sum(c.key_facts for c in mr.case_scores) / n
        mr.avg_uncertainty = sum(c.uncertainty for c in mr.case_scores) / n
        mr.avg_latency_score = sum(c.latency_score for c in mr.case_scores) / n
        mr.avg_cost_score = sum(c.cost_score for c in mr.case_scores) / n
        mr.weighted_avg = sum(c.weighted_total for c in mr.case_scores) / n
        mr.avg_latency_s = sum(c.latency_s for c in mr.case_scores) / n
        mr.total_input_tokens = sum(c.input_tokens for c in mr.case_scores)
        mr.total_output_tokens = sum(c.output_tokens for c in mr.case_scores)

        logger.info(
            "  Model %s: weighted_avg=%.3f failures=%d/%d",
            model_id, mr.weighted_avg, mr.failures, mr.total_cases,
        )
        results.append(mr)

    results.sort(key=lambda r: r.weighted_avg, reverse=True)
    return results


# ============================================================================
# Output generation
# ============================================================================


def write_results_json(
    sonnet_results: List[ModelResult],
    haiku_results: List[ModelResult],
    output_dir: Path,
) -> Path:
    """Write detailed results to results.json."""
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / "results.json"

    def _serialize_model(mr: ModelResult) -> Dict[str, Any]:
        return {
            "model": mr.model,
            "tier": mr.tier,
            "provider": mr.provider,
            "total_cases": mr.total_cases,
            "failures": mr.failures,
            "avg_parseable": round(mr.avg_parseable, 4),
            "avg_classification": round(mr.avg_classification, 4),
            "avg_key_facts": round(mr.avg_key_facts, 4),
            "avg_uncertainty": round(mr.avg_uncertainty, 4),
            "avg_latency_score": round(mr.avg_latency_score, 4),
            "avg_cost_score": round(mr.avg_cost_score, 4),
            "weighted_avg": round(mr.weighted_avg, 4),
            "avg_latency_s": round(mr.avg_latency_s, 3),
            "total_input_tokens": mr.total_input_tokens,
            "total_output_tokens": mr.total_output_tokens,
            "cases": [
                {
                    "case_id": cs.case_id,
                    "prompt_type": cs.prompt_type,
                    "parseable": round(cs.parseable, 4),
                    "classification": round(cs.classification, 4),
                    "key_facts": round(cs.key_facts, 4),
                    "uncertainty": round(cs.uncertainty, 4),
                    "latency_score": round(cs.latency_score, 4),
                    "cost_score": round(cs.cost_score, 4),
                    "weighted_total": round(cs.weighted_total, 4),
                    "latency_s": round(cs.latency_s, 3),
                    "input_tokens": cs.input_tokens,
                    "output_tokens": cs.output_tokens,
                    "error": cs.error,
                }
                for cs in mr.case_scores
            ],
        }

    payload = {
        "eval_timestamp": datetime.now(timezone.utc).isoformat(),
        "scoring_weights": {
            "parseable": W_PARSEABLE,
            "classification": W_CLASSIFICATION,
            "key_facts": W_KEY_FACTS,
            "uncertainty": W_UNCERTAINTY,
            "latency": W_LATENCY,
            "cost": W_COST,
        },
        "sonnet_tier": [_serialize_model(mr) for mr in sonnet_results],
        "haiku_tier": [_serialize_model(mr) for mr in haiku_results],
    }

    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)

    logger.info("Wrote results.json -> %s", path)
    return path


def write_leaderboard_csv(
    sonnet_results: List[ModelResult],
    haiku_results: List[ModelResult],
    output_dir: Path,
) -> Path:
    """Write leaderboard.csv with ranked model summary."""
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / "leaderboard.csv"

    rows = []
    for rank, mr in enumerate(sonnet_results, 1):
        rows.append({
            "rank": rank,
            "tier": "sonnet",
            "model": mr.model,
            "provider": mr.provider,
            "weighted_avg": f"{mr.weighted_avg:.3f}",
            "parseable": f"{mr.avg_parseable:.3f}",
            "classification": f"{mr.avg_classification:.3f}",
            "key_facts": f"{mr.avg_key_facts:.3f}",
            "uncertainty": f"{mr.avg_uncertainty:.3f}",
            "latency_score": f"{mr.avg_latency_score:.3f}",
            "cost_score": f"{mr.avg_cost_score:.3f}",
            "avg_latency_s": f"{mr.avg_latency_s:.2f}",
            "failures": mr.failures,
            "total_cases": mr.total_cases,
        })
    for rank, mr in enumerate(haiku_results, 1):
        rows.append({
            "rank": rank,
            "tier": "haiku",
            "model": mr.model,
            "provider": mr.provider,
            "weighted_avg": f"{mr.weighted_avg:.3f}",
            "parseable": f"{mr.avg_parseable:.3f}",
            "classification": f"{mr.avg_classification:.3f}",
            "key_facts": f"{mr.avg_key_facts:.3f}",
            "uncertainty": f"{mr.avg_uncertainty:.3f}",
            "latency_score": f"{mr.avg_latency_score:.3f}",
            "cost_score": f"{mr.avg_cost_score:.3f}",
            "avg_latency_s": f"{mr.avg_latency_s:.2f}",
            "failures": mr.failures,
            "total_cases": mr.total_cases,
        })

    fieldnames = [
        "rank", "tier", "model", "provider", "weighted_avg",
        "parseable", "classification", "key_facts", "uncertainty",
        "latency_score", "cost_score", "avg_latency_s", "failures", "total_cases",
    ]

    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    logger.info("Wrote leaderboard.csv -> %s", path)
    return path


def write_summary_md(
    sonnet_results: List[ModelResult],
    haiku_results: List[ModelResult],
    output_dir: Path,
) -> Path:
    """Write summary.md with winner recommendation."""
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / "summary.md"

    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    lines = [
        f"# Model Evaluation Summary",
        f"",
        f"**Generated:** {ts}",
        f"",
        f"## Scoring Weights",
        f"",
        f"| Dimension | Weight |",
        f"|-----------|--------|",
        f"| Parseable by current parser | {W_PARSEABLE:.0%} |",
        f"| Classification correctness | {W_CLASSIFICATION:.0%} |",
        f"| Key facts present | {W_KEY_FACTS:.0%} |",
        f"| Uncertainty discipline | {W_UNCERTAINTY:.0%} |",
        f"| Latency | {W_LATENCY:.0%} |",
        f"| Token cost | {W_COST:.0%} |",
        f"",
    ]

    def _tier_section(tier_name: str, results: List[ModelResult], env_var: str) -> List[str]:
        section = [
            f"## {tier_name} Tier",
            f"",
        ]
        if not results:
            section.append("*No candidates evaluated.*\n")
            return section

        section += [
            f"| Rank | Model | Weighted | Parse | Class | Facts | Uncert | Lat(s) | Fails |",
            f"|------|-------|----------|-------|-------|-------|--------|--------|-------|",
        ]
        for rank, mr in enumerate(results, 1):
            marker = " **[RECOMMENDED]**" if rank == 1 else ""
            section.append(
                f"| {rank} | {mr.model}{marker} | {mr.weighted_avg:.3f} | "
                f"{mr.avg_parseable:.2f} | {mr.avg_classification:.2f} | "
                f"{mr.avg_key_facts:.2f} | {mr.avg_uncertainty:.2f} | "
                f"{mr.avg_latency_s:.1f} | {mr.failures}/{mr.total_cases} |"
            )
        section.append("")

        winner = results[0]
        section += [
            f"### Recommendation",
            f"",
            f"Set `{env_var}={winner.model}`",
            f"",
            f"- **Weighted score:** {winner.weighted_avg:.3f}",
            f"- **Parse rate:** {winner.avg_parseable:.0%}",
            f"- **Classification accuracy:** {winner.avg_classification:.0%}",
            f"- **Avg latency:** {winner.avg_latency_s:.1f}s",
            f"- **Failure rate:** {winner.failures}/{winner.total_cases}",
            f"",
        ]

        if len(results) > 1:
            runner = results[1]
            delta = winner.weighted_avg - runner.weighted_avg
            section += [
                f"**Runner-up:** {runner.model} (score {runner.weighted_avg:.3f}, "
                f"delta {delta:+.3f})",
                f"",
            ]

        # Per-case failure diagnostics
        failed_cases = [cs for mr in results for cs in mr.case_scores if cs.error]
        if failed_cases:
            section += [
                f"### Failure Diagnostics",
                f"",
                f"| Model | Case | Error |",
                f"|-------|------|-------|",
            ]
            for cs in failed_cases:
                err_short = (cs.error or "")[:80].replace("|", "/")
                section.append(f"| {cs.model} | {cs.case_id} | {err_short} |")
            section.append("")

        # Low-parse cases (non-failures with parseable < 1.0)
        low_parse = [
            cs for mr in results for cs in mr.case_scores
            if not cs.error and cs.parseable < 1.0
        ]
        if low_parse:
            section += [
                f"### Parse Failures (non-error cases with parseable < 1.0)",
                f"",
                f"| Model | Case | Parse | Response (first 120 chars) |",
                f"|-------|------|-------|----------------------------|",
            ]
            for cs in low_parse:
                snippet = cs.raw_response[:120].replace("|", "/").replace("\n", " ")
                section.append(
                    f"| {cs.model} | {cs.case_id} | {cs.parseable:.2f} | {snippet} |"
                )
            section.append("")

        return section

    lines += _tier_section("Sonnet", sonnet_results, "LLM_SONNET_MODEL")
    lines += _tier_section("Haiku", haiku_results, "LLM_HAIKU_MODEL")

    # Tradeoffs section
    lines += [
        "## Tradeoffs",
        "",
        "| Consideration | Notes |",
        "|---------------|-------|",
        "| GovCloud availability | Check Bedrock model catalog for us-gov-west-1 region |",
        "| JSON discipline | Models with lower parse scores need retry wrappers or structured output mode |",
        "| Latency vs accuracy | Haiku-tier models trade accuracy for speed; verify parse rate > 90% |",
        "| Cost | Token costs vary 10-50x across providers; weigh against call volume |",
        "| Determinism | temperature=0 required for parsing; some providers don't guarantee identical outputs |",
        "",
        "---",
        "*Generated by MIRA Model Evaluation Harness v1.0.0*",
    ]

    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    logger.info("Wrote summary.md -> %s", path)
    return path


# ============================================================================
# CLI
# ============================================================================


def main() -> None:
    parser = argparse.ArgumentParser(
        description="MIRA Model Evaluation Harness",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python -m tests.model_eval.eval_runner\n"
            "  python -m tests.model_eval.eval_runner --tier sonnet --models gpt-4o,mistral-large-latest\n"
            "  python -m tests.model_eval.eval_runner --provider bedrock --tier haiku\n"
            "  python -m tests.model_eval.eval_runner --dry-run\n"
        ),
    )
    parser.add_argument(
        "--models",
        help="Comma-separated model IDs (overrides defaults for selected tier)",
    )
    parser.add_argument(
        "--tier",
        choices=["sonnet", "haiku", "both"],
        default="both",
        help="Which tier to evaluate (default: both)",
    )
    parser.add_argument(
        "--provider",
        default=os.environ.get("EVAL_PROVIDER", "openai"),
        help="LLM provider (default: openai)",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=_RESULTS_DIR,
        help=f"Output directory (default: {_RESULTS_DIR})",
    )
    parser.add_argument(
        "--test-cases",
        type=Path,
        default=_TEST_CASES_PATH,
        help=f"Test cases JSON (default: {_TEST_CASES_PATH})",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Load test cases and validate config without calling models",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable debug logging",
    )

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    # Load test cases
    cases = load_test_cases(args.test_cases)
    logger.info("Loaded %d test cases from %s", len(cases), args.test_cases)

    # Resolve model lists
    if args.models:
        explicit_models = [m.strip() for m in args.models.split(",") if m.strip()]
    else:
        explicit_models = None

    sonnet_models = (
        explicit_models
        if explicit_models and args.tier in ("sonnet", "both")
        else [
            m.strip()
            for m in os.environ.get("EVAL_MODELS_SONNET", "").split(",")
            if m.strip()
        ] or DEFAULT_SONNET_CANDIDATES
    )

    haiku_models = (
        explicit_models
        if explicit_models and args.tier in ("haiku", "both")
        else [
            m.strip()
            for m in os.environ.get("EVAL_MODELS_HAIKU", "").split(",")
            if m.strip()
        ] or DEFAULT_HAIKU_CANDIDATES
    )

    if args.dry_run:
        logger.info("=== DRY RUN ===")
        logger.info("Provider: %s", args.provider)
        logger.info("Sonnet candidates: %s", sonnet_models)
        logger.info("Haiku candidates: %s", haiku_models)
        sonnet_cases = [c for c in cases if c.get("target_tier", "sonnet") == "sonnet"]
        haiku_cases = [c for c in cases if c.get("target_tier", "sonnet") == "haiku"]
        logger.info("Sonnet-tier cases: %d", len(sonnet_cases))
        logger.info("Haiku-tier cases: %d", len(haiku_cases))
        _load_system_prompts()
        logger.info("System prompts loaded: %s", list(SYSTEM_PROMPTS.keys()))
        logger.info("Output dir: %s", args.output_dir)
        logger.info("=== Dry run complete — no model calls made ===")
        return

    # Run evaluations
    sonnet_results: List[ModelResult] = []
    haiku_results: List[ModelResult] = []

    if args.tier in ("sonnet", "both"):
        sonnet_results = run_eval(
            provider=args.provider,
            models=sonnet_models,
            tier="sonnet",
            cases=cases,
        )

    if args.tier in ("haiku", "both"):
        haiku_results = run_eval(
            provider=args.provider,
            models=haiku_models,
            tier="haiku",
            cases=cases,
        )

    # Write outputs
    write_results_json(sonnet_results, haiku_results, args.output_dir)
    write_leaderboard_csv(sonnet_results, haiku_results, args.output_dir)
    write_summary_md(sonnet_results, haiku_results, args.output_dir)

    # Print quick summary to stdout
    print("\n" + "=" * 70)
    print("MIRA MODEL EVALUATION COMPLETE")
    print("=" * 70)

    if sonnet_results:
        winner = sonnet_results[0]
        print(f"\n  LLM_SONNET_MODEL recommendation: {winner.model}")
        print(f"    Weighted score: {winner.weighted_avg:.3f}  "
              f"Parse: {winner.avg_parseable:.0%}  "
              f"Failures: {winner.failures}/{winner.total_cases}")

    if haiku_results:
        winner = haiku_results[0]
        print(f"\n  LLM_HAIKU_MODEL recommendation: {winner.model}")
        print(f"    Weighted score: {winner.weighted_avg:.3f}  "
              f"Parse: {winner.avg_parseable:.0%}  "
              f"Failures: {winner.failures}/{winner.total_cases}")

    print(f"\n  Results: {args.output_dir}")
    print("=" * 70)


if __name__ == "__main__":
    main()
