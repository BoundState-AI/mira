"""Question map Pydantic models.

v4.1 enhancements:
  - Questions carry confidence scores and data quality caveats.
  - Capability map summarises which questions the DB can reliably answer.
  - Semantic context (detected units, property) informs question text.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from mira.forge_claude.introspector.manifest import ConfidenceScore


class Question(BaseModel):
    """A single generated question."""

    id: str
    natural_language: str
    template_type: str
    target_table: str
    target_columns: list[str] = Field(default_factory=list)
    join_tables: list[str] = Field(default_factory=list)
    ui_component: str
    priority: str = "medium"
    # v4.1 additions
    confidence: ConfidenceScore = Field(default_factory=lambda: ConfidenceScore(
        score=1.0, source="question_gen", method="deterministic",
    ))
    capability_id: str = ""
    intent_family: str = ""
    execution_plan: dict = Field(default_factory=dict)
    data_caveats: list[str] = Field(default_factory=list)
    semantic_context: dict = Field(default_factory=dict)  # units, property, etc.
    discovery_source: str = "schema_pattern"  # schema_pattern, semantic, relationship, entropy


class QuestionCategory(BaseModel):
    """A category of related questions."""

    category: str
    questions: list[Question] = Field(default_factory=list)


class CapabilityEntry(BaseModel):
    """A single capability assessment for a question."""

    question_id: str
    reliable: bool = True
    reliability_score: float = 1.0
    limiting_factors: list[str] = Field(default_factory=list)


class StructuralMotifEntry(BaseModel):
    """A discovered structural motif from the schema/relationship graph."""

    motif_type: str
    tables: list[str] = Field(default_factory=list)
    columns: list[str] = Field(default_factory=list)
    confidence: float = 0.0
    description: str = ""


class CandidateArchetypeEntry(BaseModel):
    """A discovery-suggested archetype candidate not yet promoted to the ontology."""

    motif_type: str
    proposed_intent: str
    tables_involved: list[str] = Field(default_factory=list)
    confidence: float = 0.0
    reason: str = ""


class CapabilityCoverageEntry(BaseModel):
    """Capability-family coverage inferred from the schema and curated surface."""

    capability_id: str
    label: str
    support_level: str = "unsupported"
    evidence: list[str] = Field(default_factory=list)
    rationale: str = ""


class QuestionMap(BaseModel):
    """Complete question map for a database."""

    database_name: str
    generated_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")
    domain_summary: str = ""
    question_categories: list[QuestionCategory] = Field(default_factory=list)
    recommended_landing_page: str = ""
    estimated_ui_pages: int = 1
    # v4.1 additions
    capability_map: list[CapabilityEntry] = Field(default_factory=list)
    total_reliable: int = 0
    total_caveated: int = 0
    structural_motifs: list[StructuralMotifEntry] = Field(default_factory=list)
    candidate_archetypes: list[CandidateArchetypeEntry] = Field(default_factory=list)
    capability_coverage: list[CapabilityCoverageEntry] = Field(default_factory=list)

    def all_questions(self) -> list[Question]:
        """Return a flat list of all questions across categories."""
        return [q for cat in self.question_categories for q in cat.questions]
