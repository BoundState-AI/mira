"""Frontier-model synthesis with deterministic template fallback."""

from __future__ import annotations

import json
import logging
import os
import time
from typing import TYPE_CHECKING, Any

from mira.utils.json_extract import extract_json

from .models import Claim, SynthesisResult

LOGGER = logging.getLogger(__name__)

_PROMPT_VERSION = "v1.0.0"
_DEFAULT_MODEL_ID = "anthropic.claude-sonnet-4-5-20250929-v1:0"
_ALLOWED_GOVCLOUD_RUNTIME_HOSTS = {
    "bedrock-runtime.us-gov-west-1.amazonaws.com",
    "bedrock-runtime-fips.us-gov-west-1.amazonaws.com",
}

if TYPE_CHECKING:
    from mira.mua.classifier.models import ClassifierResult


def _model_enabled() -> bool:
    explicit = os.getenv("MUA_SYNTHESIS_USE_MODEL")
    if explicit is not None:
        return explicit.strip().lower() in {"1", "true", "yes", "on"}

    env = os.getenv("MIRA_ENV", "").strip().lower()
    return env in {"production", "staging", "govcloud"}


def synthesize_rationale(
    result: "ClassifierResult",
    evidence,
    material_name: str,
) -> SynthesisResult:
    """Synthesize rationale text from deterministic template + precedent evidence.

    Falls back to deterministic templates on any model/provider failure.
    """
    from mira.mua.classifier.models import MUAType
    from mira.mua.classifier.rationale import render_disposition, render_rationale

    template_rationale = render_rationale(result=result, material_name=material_name)
    template_disposition = render_disposition(result=result)

    # Standard/no-MUA and hard human-routed outcomes stay deterministic.
    if result.mua_type in {MUAType.STANDARD, MUAType.FLAG_FOR_HUMAN}:
        return _template_fallback(
            rationale=template_rationale,
            disposition=template_disposition,
            reason="non-automatable or no-MUA type",
        )

    # REAL_PROBLEM / REAL_GAP: provide structured precedent guidance for engineers.
    if result.mua_type in {MUAType.REAL_PROBLEM, MUAType.REAL_GAP}:
        return SynthesisResult(
            rationale=template_rationale,
            disposition=template_disposition,
            claims=[
                Claim(
                    text=template_rationale,
                    source_mua="TEMPLATE",
                    source_type="template",
                    confidence=1.0,
                )
            ],
            model_id="suggested-elements-only",
            prompt_version=_PROMPT_VERSION,
            tokens_used=0,
            latency_ms=0,
            template_fallback=True,
            suggested_elements=_build_suggested_elements(evidence),
        )

    if not result.automatable:
        return _template_fallback(
            rationale=template_rationale,
            disposition=template_disposition,
            reason="result not automatable",
        )

    if not _model_enabled():
        return _template_fallback(
            rationale=template_rationale,
            disposition=template_disposition,
            reason="frontier synthesis disabled in current environment",
        )

    model_id = os.getenv("MUA_SYNTHESIS_MODEL", _DEFAULT_MODEL_ID).strip() or _DEFAULT_MODEL_ID

    try:
        payload, usage, latency_ms = _invoke_bedrock(
            model_id=model_id,
            prompt=_build_prompt(
                result=result,
                evidence=evidence,
                material_name=material_name,
                template_rationale=template_rationale,
            ),
            max_tokens=int(os.getenv("MUA_SYNTHESIS_MAX_TOKENS", "1000")),
            temperature=float(os.getenv("MUA_SYNTHESIS_TEMPERATURE", "0")),
        )

        rationale = str(payload.get("rationale") or "").strip()
        disposition = str(payload.get("disposition") or "").strip()
        if not rationale or not disposition:
            raise ValueError("Synthesis response missing rationale or disposition")

        claims_raw = payload.get("claims") or []
        claims: list[Claim] = []
        for item in claims_raw:
            if not isinstance(item, dict):
                continue
            text = str(item.get("text") or "").strip()
            if not text:
                continue
            claims.append(
                Claim(
                    text=text,
                    source_mua=str(item.get("source_mua") or "TEMPLATE"),
                    source_type=str(item.get("source_type") or "template"),
                    confidence=float(item.get("confidence") or 0.8),
                )
            )

        if not claims:
            claims = [
                Claim(
                    text=rationale,
                    source_mua="TEMPLATE",
                    source_type="template",
                    confidence=0.8,
                )
            ]

        return SynthesisResult(
            rationale=rationale,
            disposition=disposition,
            claims=claims,
            model_id=model_id,
            prompt_version=_PROMPT_VERSION,
            tokens_used=usage,
            latency_ms=latency_ms,
            template_fallback=False,
        )
    except Exception as exc:  # pragma: no cover - depends on runtime infrastructure
        LOGGER.warning("Synthesis failed; using template fallback: %s", exc)
        return _template_fallback(
            rationale=template_rationale,
            disposition=template_disposition,
            reason=str(exc),
        )


def _build_prompt(
    *,
    result: "ClassifierResult",
    evidence,
    material_name: str,
    template_rationale: str,
) -> str:
    summary = evidence.precedent_summary
    total_count = summary.total_count if summary else 0
    approved_count = summary.approved_count if summary else 0
    common_category = summary.most_common_category if summary else ""

    formatted_phrases: list[str] = []
    for phrase in (evidence.phrases or [])[:8]:
        formatted_phrases.append(f"- [{phrase.mua_number}] {phrase.phrase}")

    if not formatted_phrases:
        for exemplar in (evidence.exemplars or [])[:5]:
            snippet = exemplar.rationale_text.strip().replace("\n", " ")
            if len(snippet) > 240:
                snippet = f"{snippet[:237]}..."
            formatted_phrases.append(f"- [{exemplar.mua_number}] {snippet}")

    phrases_block = "\n".join(formatted_phrases) if formatted_phrases else "- No precedent phrase samples available"

    return f"""
SYSTEM: You are drafting an MUA rationale for NASA Form 551. You write
like a 30-year materials and processes engineer - precise, terse,
citation-heavy. Every claim must trace to either a test standard, a
MAPTIS rating definition, or a specific prior approved MUA number.

Never speculate. Never use phrases like \"it is believed\" or \"it is
expected.\" State facts. Cite sources. Close the gap.

CONTEXT:
Material: {material_name} (MAPTIS {result.maptis_code})
Issue: {result.issue_key}={result.rating}
Classification: {result.mua_type.value}
Service Environment: {result.media}
Material Class: {result.material_class.value}

TEMPLATE SKELETON (structural basis - preserve core logic):
{template_rationale}

PRECEDENT EVIDENCE (real language from prior approved MUAs):
{phrases_block}

PRECEDENT SUMMARY:
{total_count} prior MUAs for this scenario, {approved_count} approved,
most common category: {common_category or 'unknown'}

TASK: Write a single rationale paragraph that:
1. Starts with material identification and rating.
2. States why the flag does or does not apply in this environment.
3. Incorporates 1-2 supporting precedent phrases naturally.
4. Cites specific MUA numbers parenthetically where used.
5. Ends with the precedent count sentence.
6. Total length: 4-7 sentences. Terse.

Also write one disposition sentence suitable for Form 551.

Return JSON ONLY:
{{
  "rationale": "...",
  "disposition": "...",
  "claims": [
    {{"text": "...", "source_mua": "MUA-XXXX|TEMPLATE|STANDARD", "source_type": "precedent|template|standard|domain_fact", "confidence": 0.0}}
  ]
}}
""".strip()


def _resolve_runtime_endpoint_host() -> str:
    explicit = os.getenv("MUA_BEDROCK_RUNTIME_ENDPOINT", "").strip()
    if explicit:
        return explicit.replace("https://", "").replace("http://", "").rstrip("/")

    use_fips = os.getenv("MUA_BEDROCK_USE_FIPS", "").strip().lower() in {"1", "true", "yes", "on"}
    if use_fips:
        return "bedrock-runtime-fips.us-gov-west-1.amazonaws.com"
    return "bedrock-runtime.us-gov-west-1.amazonaws.com"


def _verify_govcloud_runtime_host(host: str) -> None:
    if host not in _ALLOWED_GOVCLOUD_RUNTIME_HOSTS:
        raise RuntimeError(
            f"Bedrock runtime endpoint '{host}' is not an approved GovCloud runtime endpoint"
        )


def _invoke_bedrock(
    *,
    model_id: str,
    prompt: str,
    max_tokens: int,
    temperature: float,
) -> tuple[dict[str, Any], int, int]:
    import boto3

    region = os.getenv("MUA_BEDROCK_REGION", "us-gov-west-1").strip() or "us-gov-west-1"
    host = _resolve_runtime_endpoint_host()
    _verify_govcloud_runtime_host(host)

    endpoint_url = f"https://{host}"
    LOGGER.info("Invoking Bedrock synthesis model '%s' via %s in %s", model_id, host, region)

    client = boto3.client(
        service_name="bedrock-runtime",
        region_name=region,
        endpoint_url=endpoint_url,
    )

    request_body = {
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": max_tokens,
        "temperature": temperature,
        "messages": [
            {
                "role": "user",
                "content": prompt,
            }
        ],
    }

    t0 = time.monotonic()
    response = client.invoke_model(
        modelId=model_id,
        contentType="application/json",
        accept="application/json",
        body=json.dumps(request_body),
    )
    latency_ms = int((time.monotonic() - t0) * 1000)

    raw_body = response.get("body")
    body_text = raw_body.read().decode("utf-8") if raw_body else "{}"
    body_json = json.loads(body_text)

    content_blocks = body_json.get("content") or []
    parts: list[str] = []
    for block in content_blocks:
        text = block.get("text") if isinstance(block, dict) else None
        if text:
            parts.append(str(text))

    text_payload = "\n".join(parts).strip()
    parsed = extract_json(text_payload, expect="object")

    usage = body_json.get("usage") or {}
    tokens_used = int(usage.get("input_tokens") or 0) + int(usage.get("output_tokens") or 0)

    return parsed, tokens_used, latency_ms


def _template_fallback(rationale: str, disposition: str, reason: str) -> SynthesisResult:
    LOGGER.info("Using template fallback rationale (%s)", reason)
    return SynthesisResult(
        rationale=rationale,
        disposition=disposition,
        claims=[
            Claim(
                text=rationale,
                source_mua="TEMPLATE",
                source_type="template",
                confidence=1.0,
            )
        ],
        model_id="template-only",
        prompt_version=_PROMPT_VERSION,
        tokens_used=0,
        latency_ms=0,
        template_fallback=True,
    )


def _build_suggested_elements(evidence) -> list[str]:
    suggestions: list[str] = []
    seen: set[str] = set()

    for phrase in (getattr(evidence, "phrases", None) or [])[:8]:
        text = str(getattr(phrase, "phrase", "") or "").strip()
        mua_number = str(getattr(phrase, "mua_number", "") or "").strip()
        if not text:
            continue
        line = f"{text} ({mua_number})" if mua_number else text
        key = line.lower()
        if key in seen:
            continue
        seen.add(key)
        suggestions.append(line)
        if len(suggestions) >= 5:
            return suggestions

    for exemplar in (getattr(evidence, "exemplars", None) or [])[:5]:
        snippet = str(getattr(exemplar, "rationale_text", "") or "").strip().replace("\n", " ")
        if not snippet:
            continue
        if len(snippet) > 180:
            snippet = f"{snippet[:177]}..."
        mua_number = str(getattr(exemplar, "mua_number", "") or "").strip()
        line = f"{snippet} ({mua_number})" if mua_number else snippet
        key = line.lower()
        if key in seen:
            continue
        seen.add(key)
        suggestions.append(line)
        if len(suggestions) >= 5:
            break

    return suggestions
