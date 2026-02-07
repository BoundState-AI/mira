# M&P Plan Generator: Complete Specification V2

**Version**: 2.0.0  
**Date**: January 26, 2026  
**Classification**: BoundState Proprietary  

**Authors**:
- Dr. Joseph Wilde, BoundState AI (Architecture Owner)
- Claude Sonnet 4 "Beth" (Synthesis)
- GPT-4.5 "Fran" (Deterministic Architecture, Correctness Review)
- Gemini (State Machine Architecture)
- Grok (Senior M&P Implementation)
- Claude Code "VSClaude" (Implementation Planning)

**Compliance**: NASA-STD-8739.8B, SWE-013, SWE-033

---

## Changelog V1 → V2 (Fran Corrections)

| # | Issue | V2 Fix |
|---|-------|--------|
| 1 | Hardcoded "213 MPRs" | `len(mpr_index.mprs)` - derived from loaded index |
| 2 | Single environment assumption | `session.environments: list[EnvironmentDefinition]` + `material.use_environments: list[env_id]` |
| 3 | Free-text citations | `EvidenceRef` struct with doc_id, rev, section, paragraph_id |
| 4 | Oversimplified minor quantity | `MinorQuantityAggregation` by zone + ignition source + adjacency |
| 5 | Hand-waved invalidation triggers | Explicit `depends_on` fields + dependency graph |
| 6 | Hardcoded tribal knowledge | `PolicyPack` (YAML) with presets, thresholds, closure paths |
| 7 | Mixed gap types | `Deficiency` (blocks decision) vs `Nonconformance` (requires closure) |
| 8 | Can't generate with open gaps | `accepted_open` status with owner + due date |
| 9 | Logic in templates | Templates are dumb renderers - all conditionals from computed state |
| 10 | Incomplete cache keys | Hash includes MPRIndex + PolicyPack + MAPTIS version + git sha |
| 11 | LLM output mixed with decisions | `DraftTextBox` type - never input to decision engines |
| 12 | No dependency tracking | `DecisionGraph` with nodes/edges for recompute |
| 13 | Missing review packet | `ReviewPacketGenerator` with risks, assumptions, evidence gaps |

---

## Part 1: Core Architecture (V2)

### 1.1 The Four Components (Unchanged)

```
ENGINE A: Data Acquisition & Normalization
ENGINE B: Applicability Engine (Rule-Based)
ENGINE C: Compliance Evaluation (Deterministic)
DRAFTING ASSISTANT: LLM in Governed Boxes
```

### 1.2 Multi-Environment Model (NEW - Fran Fix #2)

```python
class EnvironmentDefinition(BaseModel):
    """Single environment zone."""
    environment_id: str
    name: str  # "Internal Cabin", "External Vacuum", "EVA Only"
    
    # Parameters
    o2_pct: float = Field(..., gt=0, le=100)
    pressure_psia: float = Field(..., gt=0)
    temp_range_c: tuple[float, float]
    habitable: bool
    vacuum_exposure: bool = False
    lunar_dust: bool = False
    
    # Phase/condition
    phase: str  # "nominal", "contingency", "ground_ops"
    
    # Evidence
    source_evidence: EvidenceRef
    
    model_config = {"extra": "forbid"}


class MaterialEnvironmentUsage(BaseModel):
    """Material usage in specific environment."""
    material_id: str
    environment_id: str
    
    # Location within zone
    location: str
    
    # Exposure characteristics
    continuous_exposure: bool = True
    exposure_duration_hours: Optional[float] = None
    
    # Adjacency (for minor quantity aggregation)
    adjacency_group: Optional[str] = None
    ignition_source_proximity: Optional[str] = None  # "none", "adjacent", "contact"
    
    model_config = {"extra": "forbid"}


class PlanGeneratorSession(BaseModel):
    """Session with multi-environment support."""
    # ...
    
    # V2: Multiple environments
    environments: list[EnvironmentDefinition] = []
    
    # V2: Material-environment mappings
    material_environment_usages: list[MaterialEnvironmentUsage] = []
    
    # Applicability and compliance operate per (material, environment) pair
```

### 1.3 Structured Evidence References (NEW - Fran Fix #3)

```python
class EvidenceRef(BaseModel):
    """
    Structured evidence reference for auditability.
    
    Not free text - must resolve to authoritative source.
    
    Compliance: SWE-033 (evidence traceability).
    """
    # Source identification
    source_type: SourceType  # STANDARD, MAPTIS, TEST_REPORT, ANALYSIS, etc.
    document_id: str  # e.g., "NASA-STD-6016C"
    revision: str  # e.g., "Rev C w/Change 2"
    
    # Location within document
    section: Optional[str] = None  # e.g., "4.2.1.1"
    paragraph_id: Optional[str] = None  # e.g., "MPR 44(c)"
    line_range: Optional[tuple[int, int]] = None
    table_id: Optional[str] = None
    figure_id: Optional[str] = None
    
    # Content
    extracted_text: Optional[str] = None
    extracted_text_hash: Optional[str] = None  # SHA-256 of extracted text
    
    # Access
    url_or_path: Optional[str] = None
    
    # Retrieval
    retrieved_at: datetime
    retrieval_method: str
    
    model_config = {"extra": "forbid"}
    
    def to_citation(self) -> str:
        """Generate citation string for display."""
        parts = [self.document_id]
        if self.revision:
            parts.append(self.revision)
        if self.section:
            parts.append(f"§{self.section}")
        if self.paragraph_id:
            parts.append(self.paragraph_id)
        return ", ".join(parts)
```

### 1.4 Policy Pack (NEW - Fran Fix #6)

```python
class PolicyPack(BaseModel):
    """
    Data-driven policy configuration.
    
    Enables center/program tailoring without code changes.
    
    Compliance: SWE-013 (configurable policy).
    """
    policy_pack_id: str
    name: str
    version: str
    
    # Applies to
    applicable_centers: list[str]  # ["MSFC", "JSC", "KSC"]
    applicable_programs: list[str]  # ["HLS", "Gateway", "Orion"]
    
    # Vehicle environment presets (tribal knowledge)
    vehicle_environments: dict[str, dict[str, Any]]
    vehicle_environment_evidence: dict[str, EvidenceRef]
    
    # Hardware type implications
    hardware_type_implications: dict[str, dict[str, bool]]
    hardware_type_evidence: dict[str, EvidenceRef]
    
    # Threshold overrides
    threshold_overrides: dict[str, "RoutingThreshold"]
    
    # Allowed closure paths by context
    closure_path_rules: list["ClosurePathRule"]
    
    # Reviewer simulator heuristics
    reviewer_heuristics: list["ReviewerHeuristic"]
    
    # Metadata
    created_at: datetime
    created_by: str
    approved_by: Optional[str] = None
    approved_at: Optional[datetime] = None
    
    # Hash for cache validation
    content_hash: str
    
    model_config = {"extra": "forbid"}


class RoutingThreshold(BaseModel):
    """Threshold with mandatory evidence."""
    parameter: str
    operator: str  # "gt", "gte", "lt", "lte", "eq"
    value: float
    evidence: EvidenceRef
    
    model_config = {"extra": "forbid"}


class ClosurePathRule(BaseModel):
    """Rule for when closure path is allowed."""
    closure_path: str
    conditions: dict[str, Any]  # e.g., {"consequence_class": "low", "habitable": false}
    allowed: bool
    evidence: EvidenceRef
    
    model_config = {"extra": "forbid"}
```

---

## Part 2: Gap Model (V2 - Split Types)

### 2.1 Deficiency vs Nonconformance (Fran Fix #7)

```python
class GapType(str, Enum):
    """Gap classification."""
    DEFICIENCY = "deficiency"        # Missing input/evidence - blocks decision
    NONCONFORMANCE = "nonconformance"  # Evidence indicates fail - requires closure


class DeficiencySignal(BaseModel):
    """
    Missing input or evidence that blocks a decision.
    
    Not a compliance failure - we just can't determine compliance yet.
    """
    deficiency_id: str
    deficiency_type: str  # "missing_maptis_code", "missing_mass", "missing_test_report"
    
    # What's missing
    missing_field: str
    missing_for: str  # What decision is blocked
    
    # Material/environment context
    material_id: Optional[str] = None
    environment_id: Optional[str] = None
    
    # Blocked decisions
    blocked_decision_ids: list[str]
    
    # Can we proceed with conservative assumption?
    conservative_default_available: bool = False
    conservative_default_value: Optional[Any] = None
    conservative_default_rationale: Optional[str] = None
    
    # Source
    source: str
    
    model_config = {"extra": "forbid"}


class NonconformanceSignal(BaseModel):
    """
    Evidence indicates material/process doesn't meet requirement.
    
    Requires closure path selection.
    """
    nonconformance_id: str
    gap_type: FailureMode  # FLAM, HEE, TVS, TOX, etc.
    
    # What failed
    failing_requirement: str
    failing_value: Optional[str] = None
    required_value: Optional[str] = None
    
    # Material/environment
    material_id: str
    environment_id: str
    
    # Affected MPRs
    affected_mprs: list[str]
    
    # Severity
    severity: GapSeverity
    confidence: float
    
    # Closure
    closure_decision: Optional["ClosureDecision"] = None
    
    # Evidence
    evidence_refs: list[EvidenceRef]
    
    # Source
    source_adapter: str
    
    model_config = {"extra": "forbid"}
```

### 2.2 Accepted Open Gaps (Fran Fix #8)

```python
class AcceptedOpenGap(BaseModel):
    """
    Gap accepted as open for generation.
    
    Allows plan generation with known open items.
    """
    gap_id: str
    gap_type: GapType
    
    # Acceptance
    accepted_by: str
    accepted_at: datetime
    acceptance_rationale: str
    
    # Tracking
    owner: str
    due_date: date
    risk_statement: str
    
    # Will be flagged in output
    flag_in_output: bool = True
    
    model_config = {"extra": "forbid"}
```

---

## Part 3: Minor Quantity Aggregation (V2 - Fran Fix #4)

```python
class MinorQuantityGroup(BaseModel):
    """
    Aggregation group for minor quantity calculation.
    
    NASA reviewers check aggregation and interaction, not just per-material.
    """
    group_id: str
    
    # Grouping keys
    environment_id: str
    ignition_source_class: str  # "none", "low_energy", "high_energy"
    adjacency_group: str  # Materials that are co-located
    
    # Members
    material_ids: list[str]
    
    # Aggregated values
    total_mass_g: float
    total_surface_area_cm2: float
    
    # Eligibility
    eligible: bool
    eligibility_rationale: str
    
    # Evidence
    evidence: EvidenceRef  # MPR 44(c) citation
    
    model_config = {"extra": "forbid"}


class MinorQuantityAggregation(BaseModel):
    """
    Complete minor quantity analysis.
    
    Fran: "NASA reviewers don't just check mass/area; they check aggregation and interaction."
    """
    # Groupings
    groups: list[MinorQuantityGroup]
    
    # Blocking questions generated when grouping is unclear
    grouping_assumptions: list["GroupingAssumption"]
    
    # Overall program total (for reviewer awareness)
    program_total_mass_g: float
    program_total_area_cm2: float
    
    # Evidence
    methodology_evidence: EvidenceRef
    
    model_config = {"extra": "forbid"}


class GroupingAssumption(BaseModel):
    """Assumption about material grouping that needs user confirmation."""
    assumption_id: str
    description: str  # "Are TY-RAP and VELCRO co-located?"
    materials_involved: list[str]
    assumed_value: bool
    confirmed: bool = False
    confirmed_by: Optional[str] = None
    
    model_config = {"extra": "forbid"}
```

---

## Part 4: Dependency Graph (V2 - Fran Fix #5, #12)

```python
class DecisionNode(BaseModel):
    """Node in decision graph."""
    node_id: str
    node_type: str  # "material", "environment", "mpr", "gap", "closure", "determination"
    
    # The actual object ID
    object_id: str
    object_type: str
    
    # Dependencies
    depends_on: list[str]  # Node IDs this depends on
    
    # Derived from
    derived_from_fields: list[str]  # e.g., ["material.mass_g", "environment.o2_pct"]
    
    model_config = {"extra": "forbid"}


class DecisionEdge(BaseModel):
    """Edge in decision graph."""
    from_node: str
    to_node: str
    edge_type: str  # "depends_on", "triggers", "satisfies", "invalidates"
    
    model_config = {"extra": "forbid"}


class DecisionGraph(BaseModel):
    """
    Explicit dependency graph for recompute.
    
    Fran: "This is what makes recompute correct and explainable."
    """
    nodes: dict[str, DecisionNode]
    edges: list[DecisionEdge]
    
    def get_invalidated_by(self, changed_field: str) -> list[str]:
        """Get all nodes invalidated by a field change."""
        # Find nodes that depend on this field
        affected = []
        for node_id, node in self.nodes.items():
            if changed_field in node.derived_from_fields:
                affected.append(node_id)
                # Cascade to dependents
                affected.extend(self._get_dependents(node_id))
        return list(set(affected))
    
    def _get_dependents(self, node_id: str) -> list[str]:
        """Get all nodes that depend on this node."""
        dependents = []
        for edge in self.edges:
            if edge.from_node == node_id and edge.edge_type == "depends_on":
                dependents.append(edge.to_node)
                dependents.extend(self._get_dependents(edge.to_node))
        return dependents
```

---

## Part 5: Closure Paths with Invalidation (V2 - Fran Fix #5)

```python
class ClosureOption(BaseModel):
    """
    Closure path option with explicit dependencies.
    
    Fran: "You created invalidation_triggers but never defined how they're generated."
    """
    path: str
    eligible: bool
    citation: str
    rationale: str
    
    # Required inputs to select this path
    required_inputs: list[str]
    
    # What this path produces
    output_artifact: str
    
    # EXPLICIT DEPENDENCIES (Fran Fix #5)
    depends_on: list[str]  # Field names: ["material.mass_g", "material.surface_area_cm2", "environment.o2_pct"]
    
    # What invalidates this option's eligibility
    invalidation_triggers: list["InvalidationTrigger"]
    
    # Evidence for eligibility
    eligibility_evidence: Optional[EvidenceRef] = None
    
    model_config = {"extra": "forbid"}


class InvalidationTrigger(BaseModel):
    """What causes a closure option to become ineligible."""
    field: str
    condition: str  # "changes", "exceeds_threshold", "becomes_null"
    threshold: Optional[float] = None
    
    model_config = {"extra": "forbid"}


# Example: Minor quantity option with dependencies
def create_minor_quantity_option(
    material: MaterialEntry,
    environment: EnvironmentDefinition,
    aggregation: MinorQuantityAggregation,
    policy: PolicyPack,
) -> ClosureOption:
    """Create minor quantity closure option with explicit dependencies."""
    
    # Check eligibility
    group = find_group_for_material(aggregation, material.id, environment.environment_id)
    eligible = group is not None and group.eligible
    
    return ClosureOption(
        path="MINOR_QUANTITY",
        eligible=eligible,
        citation="MPR 44(c)",
        rationale=f"Group total: {group.total_mass_g}g, {group.total_surface_area_cm2}cm²" if group else "No group",
        required_inputs=["aggregation_confirmation"],
        output_artifact="MUA with minor quantity rationale",
        
        # EXPLICIT DEPENDENCIES
        depends_on=[
            f"material.{material.id}.mass_g",
            f"material.{material.id}.surface_area_cm2",
            f"aggregation.{group.group_id}.total_mass_g" if group else "aggregation.none",
            f"aggregation.{group.group_id}.total_surface_area_cm2" if group else "aggregation.none",
            "policy.minor_quantity_thresholds",
        ],
        
        invalidation_triggers=[
            InvalidationTrigger(field=f"material.{material.id}.mass_g", condition="exceeds_threshold", threshold=45.0),
            InvalidationTrigger(field=f"material.{material.id}.surface_area_cm2", condition="exceeds_threshold", threshold=13.0),
            InvalidationTrigger(field=f"aggregation.{group.group_id}.total_mass_g" if group else "aggregation.none", condition="exceeds_threshold", threshold=45.0),
        ],
        
        eligibility_evidence=EvidenceRef(
            source_type=SourceType.STANDARD,
            document_id="NASA-STD-6016C",
            revision="Rev C w/Change 2",
            section="4.2.1.1",
            paragraph_id="MPR 44(c)",
            retrieved_at=datetime.now(),
            retrieval_method="policy_pack",
        ),
    )
```

---

## Part 6: LLM Output Isolation (V2 - Fran Fix #11)

```python
class DraftTextBox(BaseModel):
    """
    LLM-generated text in isolated container.
    
    Fran: "Drafted text objects should live in a different namespace/type
    and never be allowed as input to decision engines."
    
    This type is NEVER used as input to any decision logic.
    """
    box_id: str
    
    # What was drafted
    draft_type: str  # "mua_rationale", "tailoring_narrative", "config_analysis"
    
    # The draft content
    content: str
    
    # Provenance
    prompt_template_id: str
    prompt_hash: str  # SHA-256 of actual prompt
    model_id: str  # e.g., "claude-sonnet-4-20250514"
    inputs_hash: str  # SHA-256 of structured inputs
    
    # Timestamps
    generated_at: datetime
    
    # NOT AUTHORITATIVE
    is_authoritative: bool = False  # Always False
    requires_human_review: bool = True  # Always True
    
    model_config = {"extra": "forbid"}
    
    @model_validator(mode="after")
    def enforce_non_authoritative(self) -> "DraftTextBox":
        """Enforce that drafts are never authoritative."""
        if self.is_authoritative:
            raise ValueError("DraftTextBox can never be authoritative")
        if not self.requires_human_review:
            raise ValueError("DraftTextBox always requires human review")
        return self
```

---

## Part 7: Cache Keys (V2 - Fran Fix #10)

```python
class ComputationContext(BaseModel):
    """
    All version information needed for cache validation.
    
    Fran: "Your computation_hash should include MPRIndex hash,
    PolicyPack hash, MAPTIS dataset version hash, code version."
    """
    # Index versions
    mpr_index_hash: str
    mpr_index_version: str
    mpr_count: int  # Derived, not hardcoded "213"
    
    # Policy versions
    policy_pack_hash: str
    policy_pack_version: str
    
    # Data versions
    maptis_dataset_version: str
    maptis_dataset_hash: str
    
    # Code version
    code_version: str  # Git SHA
    code_branch: str
    
    # Compute timestamp
    computed_at: datetime
    
    def compute_cache_key(self) -> str:
        """Compute cache key from all components."""
        components = [
            self.mpr_index_hash,
            self.policy_pack_hash,
            self.maptis_dataset_hash,
            self.code_version,
        ]
        return hashlib.sha256("|".join(components).encode()).hexdigest()


class RunManifest(BaseModel):
    """
    Complete run manifest with all version info.
    """
    run_id: str
    session_id: str
    
    # Context (V2: includes all hashes)
    computation_context: ComputationContext
    
    # Inputs
    input_fingerprints: dict[str, str]
    
    # Decisions
    decision_graph: DecisionGraph
    user_decisions: list[UserDecision]
    
    # Outputs
    generated_artifacts: list[GeneratedArtifact]
    
    # V2: Policy pack used
    policy_pack_id: str
    policy_pack_hash: str
    
    model_config = {"extra": "forbid"}
```

---

## Part 8: Template Rules (V2 - Fran Fix #9)

```python
"""
TEMPLATE RULES (Fran Fix #9)

Templates are DUMB RENDERERS. No logic allowed.

BANNED in templates:
- if o2_pct > 23.5
- if material.rating == "X"
- any conditional based on data values

ALLOWED in templates:
- if section.content is not None  (just checking if there's content)
- for item in items  (iteration over computed list)
- {{ value }}  (simple value insertion)

All conditionals are resolved BEFORE template rendering.
The template receives a fully computed SectionContent object.
"""


class SectionContent(BaseModel):
    """
    Pre-computed section content for template.
    
    Template just renders this - no logic.
    """
    section_id: str
    section_number: str
    title: str
    
    # Content type
    content_type: str  # "text", "table", "list", "na_statement"
    
    # Pre-computed content (template just renders)
    text_content: Optional[str] = None
    table_content: Optional[list[dict]] = None
    list_content: Optional[list[str]] = None
    
    # NA handling (pre-computed)
    is_applicable: bool = True
    na_rationale: Optional[str] = None
    na_evidence: Optional[EvidenceRef] = None
    
    # Sub-sections (pre-computed)
    subsections: list["SectionContent"] = []
    
    model_config = {"extra": "forbid"}


def render_section(template: str, content: SectionContent) -> str:
    """
    Render section using dumb template.
    
    Template has NO LOGIC - just value insertion and iteration.
    """
    # Jinja2 with logic disabled
    from jinja2 import Environment, select_autoescape
    
    env = Environment(
        autoescape=select_autoescape(),
        # Disable all logic extensions
    )
    
    # Template can only use:
    # {{ content.title }}
    # {{ content.text_content }}
    # {% for row in content.table_content %}...{% endfor %}
    
    return env.from_string(template).render(content=content)
```

---

## Part 9: Review Packet Generator (V2 - Fran Fix #13)

```python
class ReviewPacket(BaseModel):
    """
    Reviewer-focused summary packet.
    
    Fran: "In addition to the plan, generate a reviewer packet."
    """
    # Top risks
    top_risks: list["RiskItem"]
    
    # Open assumptions
    open_assumptions: list["AssumptionItem"]
    
    # Evidence gaps
    evidence_gaps: list["EvidenceGap"]
    
    # Unknown states
    unknown_states: list["UnknownState"]
    
    # Test condition deltas
    test_condition_deltas: list["TestConditionDelta"]
    
    # Accepted open gaps
    accepted_open_gaps: list[AcceptedOpenGap]
    
    # Reviewer predictions
    predicted_questions: list["ReviewerQuestion"]
    
    model_config = {"extra": "forbid"}


class RiskItem(BaseModel):
    """Top risk for reviewer awareness."""
    risk_id: str
    description: str
    severity: str
    affected_materials: list[str]
    affected_mprs: list[str]
    mitigation: str
    
    model_config = {"extra": "forbid"}


class TestConditionDelta(BaseModel):
    """Where test conditions don't match use conditions."""
    material_id: str
    material_name: str
    
    # Test conditions
    test_o2_pct: float
    test_pressure_psia: float
    test_temp_c: float
    
    # Use conditions
    use_o2_pct: float
    use_pressure_psia: float
    use_temp_range_c: tuple[float, float]
    
    # Delta assessment
    o2_delta_pct: float
    is_significant: bool
    rationale: str
    
    model_config = {"extra": "forbid"}


class ReviewerQuestion(BaseModel):
    """Predicted reviewer question."""
    question: str
    context: str
    evidence_available: bool
    evidence_location: Optional[str] = None
    evidence_missing: Optional[str] = None
    
    model_config = {"extra": "forbid"}


def generate_review_packet(session: PlanGeneratorSession) -> ReviewPacket:
    """
    Generate reviewer-focused packet.
    
    This reduces comment cycles by anticipating questions.
    """
    packet = ReviewPacket(
        top_risks=[],
        open_assumptions=[],
        evidence_gaps=[],
        unknown_states=[],
        test_condition_deltas=[],
        accepted_open_gaps=session.accepted_open_gaps,
        predicted_questions=[],
    )
    
    # Find test condition deltas
    for resolution in session.maptis_resolutions:
        for env in session.environments:
            for usage in session.material_environment_usages:
                if usage.material_id == resolution.material_id and usage.environment_id == env.environment_id:
                    if resolution.test_o2_pct < env.o2_pct:
                        delta = TestConditionDelta(
                            material_id=resolution.material_id,
                            material_name=get_material_name(session, resolution.material_id),
                            test_o2_pct=resolution.test_o2_pct,
                            test_pressure_psia=resolution.test_pressure_psia or 14.7,
                            test_temp_c=resolution.test_temp_c or 25.0,
                            use_o2_pct=env.o2_pct,
                            use_pressure_psia=env.pressure_psia,
                            use_temp_range_c=env.temp_range_c,
                            o2_delta_pct=env.o2_pct - resolution.test_o2_pct,
                            is_significant=env.o2_pct - resolution.test_o2_pct > 5.0,
                            rationale="Test O2% below use O2% - verify acceptability",
                        )
                        packet.test_condition_deltas.append(delta)
                        
                        # Predict reviewer question
                        packet.predicted_questions.append(ReviewerQuestion(
                            question=f"Verify flammability test O2% for {delta.material_name}",
                            context=f"Test: {delta.test_o2_pct}%, Use: {delta.use_o2_pct}%",
                            evidence_available=resolution.test_report_ref is not None,
                            evidence_location=resolution.test_report_ref,
                            evidence_missing="Test report not linked" if not resolution.test_report_ref else None,
                        ))
    
    return packet
```

---

## Part 10: Updated Session Model (V2)

```python
class PlanGeneratorSession(BaseModel):
    """
    Complete session state V2.
    
    Changes from V1:
    - Multi-environment support
    - Split gap types (deficiency vs nonconformance)
    - Accepted open gaps
    - Decision graph
    - Policy pack reference
    - Computation context with full hashes
    """
    model_config = {"extra": "forbid", "populate_by_name": True}
    
    # Identity
    session_id: str
    created_at: datetime
    updated_at: datetime
    source: str = "interactive_session"
    
    # Program context
    program_name: Optional[str] = None
    program_phase: Optional[str] = None
    lead_organization: Optional[str] = None
    
    # V2: Policy pack
    policy_pack_id: str
    policy_pack: Optional[PolicyPack] = None
    
    # V2: Multiple environments
    environments: list[EnvironmentDefinition] = []
    
    # Hardware context
    hardware_context: Optional[HardwareContext] = None
    
    # Materials
    materials: list[MaterialEntry] = []
    maptis_resolutions: list[MaterialResolutionResult] = []
    
    # V2: Material-environment mappings
    material_environment_usages: list[MaterialEnvironmentUsage] = []
    
    # V2: Minor quantity aggregation
    minor_quantity_aggregation: Optional[MinorQuantityAggregation] = None
    
    # COTS assessment
    cots_items: list[COTSItem] = []
    
    # Organization
    org_chart: Optional[OrgChart] = None
    
    # Applicability
    applicability_matrix: Optional[ApplicabilityMatrix] = None
    
    # Compliance
    mpr_determinations: list[MPRDetermination] = []
    
    # V2: Split gap types
    deficiencies: list[DeficiencySignal] = []
    nonconformances: list[NonconformanceSignal] = []
    
    # Constraints
    constraints: list[OperationalConstraint] = []
    
    # Closure decisions
    closure_decisions: list[ClosureDecision] = []
    
    # V2: Accepted open gaps
    accepted_open_gaps: list[AcceptedOpenGap] = []
    
    # V2: Draft text boxes (isolated from decisions)
    draft_text_boxes: list[DraftTextBox] = []
    
    # Blocking questions
    blocking_questions: list[BlockingQuestion] = []
    
    # User decisions
    user_decisions: list[UserDecision] = []
    
    # V2: Decision graph
    decision_graph: Optional[DecisionGraph] = None
    
    # V2: Computation context
    computation_context: Optional[ComputationContext] = None
    
    # Generated artifacts
    generated_artifacts: list[GeneratedArtifact] = []
    
    def can_generate(self) -> tuple[bool, list[str]]:
        """
        Check if session is ready for artifact generation.
        
        V2: Allows generation with accepted open gaps.
        """
        blockers = []
        
        if not self.environments:
            blockers.append("No environments defined")
        
        if not self.materials:
            blockers.append("No materials entered")
        
        # Check for unresolved materials
        resolved_ids = {r.material_id for r in self.maptis_resolutions}
        unresolved = [m for m in self.materials if m.id not in resolved_ids]
        if unresolved:
            blockers.append(f"{len(unresolved)} materials not resolved in MAPTIS")
        
        # Check for blocking deficiencies (not just any deficiency)
        blocking_deficiencies = [d for d in self.deficiencies 
                                  if not d.conservative_default_available]
        if blocking_deficiencies:
            blockers.append(f"{len(blocking_deficiencies)} blocking deficiencies")
        
        # V2: Nonconformances need closure OR acceptance
        closed_ids = {d.gap_id for d in self.closure_decisions}
        accepted_ids = {a.gap_id for a in self.accepted_open_gaps}
        open_nonconformances = [n for n in self.nonconformances 
                                 if n.nonconformance_id not in closed_ids 
                                 and n.nonconformance_id not in accepted_ids]
        if open_nonconformances:
            blockers.append(f"{len(open_nonconformances)} nonconformances without closure or acceptance")
        
        return len(blockers) == 0, blockers
```

---

## Part 11: Updated Implementation Phases

| Phase | Component | Days | V2 Changes |
|-------|-----------|------|------------|
| 1 | Core Infrastructure | 3 | + DecisionGraph, + ComputationContext |
| 2 | Engine A - Data Acquisition | 3 | + Multi-environment, + MaterialEnvironmentUsage |
| 3 | Engine B - Applicability | 3 | MPR count from index, not hardcoded |
| 3.5 | Policy Pack Loader | 1 | NEW: Load YAML, validate evidence refs |
| 4 | Engine C - Compliance Evaluation | 3 | + MinorQuantityAggregation, + split gaps |
| 5 | Gap Resolution | 2 | + Invalidation triggers, + AcceptedOpenGap |
| 6 | Document Generation | 3 | + Dumb templates, + ReviewPacket |
| 7 | API & CLI | 2 | No change |
| **Total** | | **20 days** | +2 days from V1 |

---

## Part 12: Success Criteria (V2)

| # | Criterion | Verification |
|---|-----------|--------------|
| 1 | MPR count from index | `assert len(result.mpr_decisions) == len(mpr_index.mprs)` |
| 2 | Multi-environment works | Material in 2 zones → 2 applicability evaluations |
| 3 | Evidence refs structured | All citations have document_id, section |
| 4 | Minor quantity aggregates | Group total shown, not just per-material |
| 5 | Dependency graph tracks | Field change → correct invalidations |
| 6 | Policy pack drives thresholds | Change YAML → different thresholds |
| 7 | Deficiency vs nonconformance | Split types in output |
| 8 | Can generate with accepted open | Open gap + acceptance → generation proceeds |
| 9 | Templates have no logic | Grep for `if.*pct` in templates returns nothing |
| 10 | Cache key includes all hashes | Same inputs + same versions → same cache key |
| 11 | DraftTextBox never in decisions | Type check: decisions don't reference DraftTextBox |
| 12 | Review packet generated | Packet includes test deltas, predicted questions |

---

*End of Specification V2*
