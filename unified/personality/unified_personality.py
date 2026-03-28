from __future__ import annotations

from pydantic import BaseModel, Field

from unified.discovery.capabilities import UnifiedCapabilities


class UnifiedVoiceProfile(BaseModel):
    tone: str = "professional, evidence-focused"
    formality: str = "moderate"
    citation_density: str = "high"
    uncertainty_handling: str = "explicit disclosure"


class UnifiedPersonalityProfile(BaseModel):
    name: str
    role: str
    domain: str
    core_trait: str
    voice: UnifiedVoiceProfile = Field(default_factory=UnifiedVoiceProfile)
    behavioral_rules: list[str] = Field(default_factory=list)
    derived_from: dict[str, str] = Field(default_factory=dict)


class UnifiedPersonalityEngine:
    def derive(
        self,
        capabilities: UnifiedCapabilities,
        name: str = "IC",
        user_role: str = "engineer",
    ) -> UnifiedPersonalityProfile:
        domain = ", ".join(
            capabilities.overlap_terms[:6] or capabilities.db_tables[:3] or capabilities.doc_ids[:3]
        ) or "general materials intelligence"
        high_risk = "compliance_check" in capabilities.supported_intents
        tone = "careful, precise, evidence-focused" if high_risk else "practical, technical, direct"
        rules = [
            "Always cite evidence sources for factual claims",
            "State conflicts explicitly instead of hiding them",
            "Do not cross the engineering authority boundary",
        ]
        if user_role == "manager":
            rules.append("Summarize risk and uncertainty first")
        elif user_role == "auditor":
            rules.append("Prefer full provenance chains over short summaries")

        return UnifiedPersonalityProfile(
            name=name,
            role=f"bounded intelligence compiler for {domain}",
            domain=domain,
            core_trait="evidence-obsessed" if high_risk else "bounded and practical",
            voice=UnifiedVoiceProfile(
                tone=tone,
                formality="formal" if high_risk else "technical",
                citation_density="very high" if high_risk else "high",
                uncertainty_handling="explicit disclosure with referral",
            ),
            behavioral_rules=rules,
            derived_from={
                "sources": ",".join(capabilities.supported_sources),
                "user_role": user_role,
            },
        )

