"""Schema manifest and related artifact Pydantic models.

v4.1 artifacts produced by Step 1:
  - schema_manifest.json   (SchemaManifest)
  - semantic_map.json      (SemanticMap)
  - relationship_graph.json (RelationshipGraph)
  - latent_relationships.json (LatentRelationships)
  - data_quality_report.json (DataQualityReport)
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Scoring contract (Section 13 of v4.1 spec)
# ---------------------------------------------------------------------------

class ConfidenceScore(BaseModel):
    """Common scoring contract used across all modules."""

    score: float = 0.0
    source: str = ""
    method: str = ""
    inputs: list[str] = Field(default_factory=list)
    threshold: float = 0.5
    action_if_below: str = "flag_for_review"


# ---------------------------------------------------------------------------
# Column profiling (Section 3.6)
# ---------------------------------------------------------------------------

class ColumnProfile(BaseModel):
    """Enhanced column statistics from profiling."""

    min_value: float | None = None
    max_value: float | None = None
    mean_value: float | None = None
    null_count: int = 0
    null_rate: float = 0.0
    distribution_shape: str = ""  # normal, skewed, categorical, sparse, uniform
    value_frequencies: dict[str, int] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Schema manifest models (Section 3.1)
# ---------------------------------------------------------------------------

class ColumnInfo(BaseModel):
    """Information about a single database column."""

    name: str
    type: str
    primary_key: bool = False
    nullable: bool = True
    sample_values: list[str] = Field(default_factory=list)
    unique_count: int | None = None
    profile: ColumnProfile | None = None


class ForeignKey(BaseModel):
    """A foreign key constraint."""

    column: str
    references_table: str
    references_column: str


class TableInfo(BaseModel):
    """Information about a single database table."""

    name: str
    row_count: int = 0
    columns: list[ColumnInfo] = Field(default_factory=list)
    foreign_keys: list[ForeignKey] = Field(default_factory=list)
    indexes: list[str] = Field(default_factory=list)


class Relationship(BaseModel):
    """A detected relationship between tables."""

    type: str  # many_to_one, one_to_many, many_to_many
    from_table: str
    from_column: str
    to_table: str
    to_column: str
    confidence: ConfidenceScore = Field(default_factory=lambda: ConfidenceScore(
        score=1.0, source="fk_extraction", method="explicit_foreign_key",
    ))
    discovery_mechanism: str = "explicit_fk"  # explicit_fk, statistical, entropy


class SchemaStatistics(BaseModel):
    """Aggregate statistics about the schema."""

    total_tables: int = 0
    total_rows: int = 0
    total_columns: int = 0


class SchemaManifest(BaseModel):
    """Complete schema manifest for a database."""

    database_type: str
    database_name: str
    introspected_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")
    tables: list[TableInfo] = Field(default_factory=list)
    relationships: list[Relationship] = Field(default_factory=list)
    statistics: SchemaStatistics = Field(default_factory=SchemaStatistics)


# ---------------------------------------------------------------------------
# Semantic map models (Section 3.2)
# ---------------------------------------------------------------------------

class SemanticField(BaseModel):
    """Semantic inference for a single column."""

    table: str
    column: str
    column_type: str
    semantic_type: str = "unknown"  # identifier, measurement, category, temporal, text, etc.
    detected_property: str = ""     # e.g. "tensile_strength", "price", "email"
    detected_units: str = ""        # e.g. "MPa", "USD", "kg"
    confidence: ConfidenceScore = Field(default_factory=ConfidenceScore)


class SemanticMap(BaseModel):
    """Semantic field inferences for all columns in a database."""

    database_name: str
    generated_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")
    fields: list[SemanticField] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Relationship graph models (Section 3.3)
# ---------------------------------------------------------------------------

class DiscoveredRelationship(BaseModel):
    """A relationship found via any of the three discovery mechanisms."""

    from_table: str
    from_column: str
    to_table: str
    to_column: str
    mechanism: str  # explicit_fk, statistical_match, join_viability
    overlap_ratio: float | None = None   # Mechanism 2
    join_coverage: float | None = None   # Mechanism 3
    confidence: ConfidenceScore = Field(default_factory=ConfidenceScore)


class RelationshipGraph(BaseModel):
    """All discovered relationships across three mechanisms."""

    database_name: str
    generated_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")
    explicit: list[DiscoveredRelationship] = Field(default_factory=list)
    statistical: list[DiscoveredRelationship] = Field(default_factory=list)
    join_viability: list[DiscoveredRelationship] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Latent relationship models (Section 3.4)
# ---------------------------------------------------------------------------

class LatentJoin(BaseModel):
    """A latent relationship discovered via entropy analysis."""

    from_table: str
    from_column: str
    to_table: str
    to_column: str
    mutual_information: float = 0.0
    entropy_a: float = 0.0
    entropy_b: float = 0.0
    conditional_entropy: float = 0.0
    overlap_ratio: float = 0.0
    composite_score: float = 0.0
    status: str = "candidate"  # candidate, promoted, rejected, conflict
    conflict_with_fk: bool = False
    confidence: ConfidenceScore = Field(default_factory=ConfidenceScore)


class LatentRelationships(BaseModel):
    """Entropy-discovered latent joins."""

    database_name: str
    generated_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")
    joins: list[LatentJoin] = Field(default_factory=list)
    pairs_evaluated: int = 0
    pairs_skipped: int = 0
    budget_exceeded: bool = False


# ---------------------------------------------------------------------------
# Data quality report models (Section 3.5)
# ---------------------------------------------------------------------------

class ColumnQuality(BaseModel):
    """Quality assessment for a single column."""

    table: str
    column: str
    null_rate: float = 0.0
    null_count: int = 0
    outlier_count: int = 0
    outlier_values: list[str] = Field(default_factory=list)
    has_duplicates: bool = False
    duplicate_count: int = 0
    inconsistent_units: bool = False
    quality_score: ConfidenceScore = Field(default_factory=lambda: ConfidenceScore(
        score=1.0, source="quality_inspector", method="composite",
        threshold=0.7, action_if_below="flag_in_report",
    ))
    flags: list[str] = Field(default_factory=list)


class TableQuality(BaseModel):
    """Quality assessment for a table."""

    table: str
    row_count: int = 0
    missing_fk_candidates: list[str] = Field(default_factory=list)
    naming_anomalies: list[str] = Field(default_factory=list)
    index_recommendations: list[str] = Field(default_factory=list)
    columns: list[ColumnQuality] = Field(default_factory=list)


class DataQualityReport(BaseModel):
    """Complete data quality report for a database."""

    database_name: str
    generated_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")
    tables: list[TableQuality] = Field(default_factory=list)
    summary: dict = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Schema diff models (Section 3.7)
# ---------------------------------------------------------------------------

class SchemaDiff(BaseModel):
    """Diff between two schema manifests."""

    database_name: str
    diff_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")
    tables_added: list[str] = Field(default_factory=list)
    tables_removed: list[str] = Field(default_factory=list)
    columns_added: list[dict] = Field(default_factory=list)
    columns_removed: list[dict] = Field(default_factory=list)
    columns_type_changed: list[dict] = Field(default_factory=list)
    indexes_added: list[dict] = Field(default_factory=list)
    foreign_keys_added: list[dict] = Field(default_factory=list)
    row_count_changes: list[dict] = Field(default_factory=list)
    has_breaking_changes: bool = False
