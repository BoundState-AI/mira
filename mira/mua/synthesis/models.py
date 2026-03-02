"""Synthesis models for MUA rationale drafting."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Claim:
    """A single factual claim in the rationale with evidence link."""

    text: str
    source_mua: str
    source_type: str  # precedent, template, standard, domain_fact
    confidence: float = 0.0


@dataclass(frozen=True)
class SynthesisResult:
    """Output of frontier model synthesis."""

    rationale: str
    disposition: str
    claims: list[Claim] = field(default_factory=list)
    model_id: str = ""
    prompt_version: str = "v1.0.0"
    tokens_used: int = 0
    latency_ms: int = 0
    template_fallback: bool = False
