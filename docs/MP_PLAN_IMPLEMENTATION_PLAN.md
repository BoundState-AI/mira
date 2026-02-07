# M&P Plan Generator V2 - Gap Closure Plan

## Executive Summary

Current implementation is ~50% complete. This plan closes the gaps to deliver a NASA review-ready deterministic compliance pipeline.

**Priority Order:**
1. Output Quality (High-impact, fast wins)
2. MPR Index Expansion (Foundation for Engine B)
3. Closure Path Implementations (Core functionality)
4. API & CLI (Integration layer)
5. Export Artifacts (Compliance deliverables)

---

## Phase 1: Output Quality Fixes (2 days)

### 1.1 Section Builder Improvements ✅ DONE
- [x] Add Section 1.0 Scope and Purpose with subsections
- [x] Add Section 4.0 Test Condition Deltas
- [x] Surface O2 envelope violations in document

### 1.2 MIUL Summary Sheet ✅ DONE
- [x] Add comprehensive metrics to Summary sheet
- [x] Material counts by rating (A/B/C/Not Resolved)
- [x] Test deltas outside envelope count
- [x] Action items with color coding

### 1.3 Remaining Output Improvements
- [ ] Add Appendix placeholders for MAPTIS data sheets
- [ ] Add operational constraints section
- [ ] Improve table formatting in DOCX

**Files:**
- `mira/mp_plan/generation/section_builder.py` ✅
- `mira/mp_plan/generation/miul_xlsx.py` ✅
- `mira/mp_plan/generation/mp_plan_docx.py`

---

## Phase 2: MPR Index Expansion (3 days)

### 2.1 Expand mprs_6016c.yaml
Current: 15 MPRs
Target: 54 core MPRs (NASA-STD-6016C Table 1)

**Structure per MPR:**
```yaml
- mpr_number: 44
  mpr_id: "MPR-044"
  section: "4.2.4.1"
  title: "Flammability"
  shall_text: "Materials shall be tested for flammability..."
  verification_method: "Test"
  applicability_triggers:
    - "o2_service"
    - "habitable"
  related_failure_modes:
    - "flam"
  priority: 10
  exceptions:
    - "minor_quantity"  # MPR 44(c)
    - "heat_sink"       # MPR 44(g)
    - "configuration"   # MPR 44(h)
```

### 2.2 MPR Categories to Define

| Category | MPR Range | Count |
|----------|-----------|-------|
| Materials Selection | 1-10 | 10 |
| Flammability | 41-48 | 8 |
| Offgassing | 51-55 | 5 |
| Fluid Compatibility | 61-68 | 8 |
| Stress Corrosion | 71-75 | 5 |
| Fracture Control | 81-88 | 8 |
| Process Control | 91-98 | 8 |
| Special Materials | 101-102 | 2 |

### 2.3 Trigger Definitions
```yaml
# In policy pack or separate triggers.yaml
triggers:
  o2_service:
    condition: "environment.o2_pct > 23.5"
    evidence: "NASA-STD-6016C Section 4.2.4"

  habitable:
    condition: "environment.habitable == true"
    evidence: "NASA-STD-6016C Section 4.2.1"

  hydrogen_service:
    condition: "environment.h2_exposure == true OR material.h2_contact == true"
    evidence: "NASA-STD-6016C Section 4.2.6"

  cryogenic:
    condition: "environment.temp_min_c < -150"
    evidence: "NASA-STD-6016C Section 4.2.3"
```

**Files:**
- `mira/compliance/data/mprs_6016c.yaml` - Expand to 54 MPRs
- `mira/mp_plan/data/mpr_triggers.yaml` - New file

---

## Phase 3: Closure Path Implementations (4 days)

### 3.1 Create gap_resolution Module
```
mira/mp_plan/gap_resolution/
├── __init__.py
├── base.py                 # ClosurePathBase abstract class
├── minor_quantity.py       # MPR 44(c) - mass/area check
├── configuration.py        # JSC 29353 - self-extinguishing
├── heat_sink.py           # MPR 44(g) - bonded to metal
├── substitution.py        # MAPTIS alternative search
├── test_program.py        # New testing path
└── full_mua.py            # Category I MUA generation
```

### 3.2 ClosurePathBase Interface
```python
class ClosurePathBase(ABC):
    """Base class for closure path implementations."""

    path_id: str
    citation: str
    required_inputs: list[str]
    output_artifact: str

    @abstractmethod
    def check_eligibility(
        self,
        gap: NonconformanceSignal,
        material: MaterialEntry,
        environment: EnvironmentDefinition,
        session: PlanGeneratorSession,
    ) -> tuple[bool, str]:
        """Check if this path is eligible. Returns (eligible, rationale)."""

    @abstractmethod
    def generate_artifact(
        self,
        gap: NonconformanceSignal,
        inputs: dict[str, Any],
        session: PlanGeneratorSession,
    ) -> GeneratedArtifact:
        """Generate the closure artifact."""
```

### 3.3 Minor Quantity Implementation
```python
class MinorQuantityPath(ClosurePathBase):
    """MPR 44(c) - Minor quantity exception."""

    path_id = "MINOR_QUANTITY"
    citation = "NASA-STD-6016C Section 4.2.4.1(c)"
    required_inputs = ["mass_g", "surface_area_cm2", "adjacency_group"]
    output_artifact = "minor_quantity_analysis"

    # MPR 44(c) thresholds
    MASS_THRESHOLD_G = 45.0
    AREA_THRESHOLD_CM2 = 13.0

    def check_eligibility(self, gap, material, environment, session):
        # Must be a FLAM gap
        if gap.gap_type != FailureMode.FLAM:
            return False, "Minor quantity only applies to flammability gaps"

        # Get aggregated totals for adjacency group
        agg = session.minor_quantity_aggregation
        if not agg:
            return False, "Minor quantity aggregation not computed"

        group = agg.get_group_for_material(material.id, environment.environment_id)
        if not group:
            return False, "Material not in any aggregation group"

        # Check thresholds
        if group.total_mass_g > self.MASS_THRESHOLD_G:
            return False, f"Aggregated mass {group.total_mass_g}g exceeds {self.MASS_THRESHOLD_G}g threshold"

        if group.total_surface_area_cm2 > self.AREA_THRESHOLD_CM2:
            return False, f"Aggregated area {group.total_surface_area_cm2}cm² exceeds {self.AREA_THRESHOLD_CM2}cm² threshold"

        return True, f"Eligible: aggregated mass {group.total_mass_g}g, area {group.total_surface_area_cm2}cm²"
```

### 3.4 Configuration Analysis Implementation
```python
class ConfigurationAnalysisPath(ClosurePathBase):
    """JSC 29353 - Self-extinguishing in configuration."""

    path_id = "CONFIGURATION_ANALYSIS"
    citation = "JSC 29353, NASA-STD-6016C Section 4.2.4.1(h)"
    required_inputs = ["mounting_method", "adjacent_materials", "heat_sink_mass_g"]
    output_artifact = "configuration_analysis_docx"

    def check_eligibility(self, gap, material, environment, session):
        # Must be a FLAM gap
        if gap.gap_type != FailureMode.FLAM:
            return False, "Configuration analysis only applies to flammability gaps"

        # Check for heat sink presence
        if material.heat_sink_mass_g and material.heat_sink_mass_g > 100:
            return True, "Material has significant heat sink (>100g metal)"

        # Check mounting
        if material.mounting_method in ["bonded", "mechanically_attached"]:
            return True, "Material mounting supports self-extinguishing"

        return False, "No self-extinguishing configuration identified"
```

**Files:**
- `mira/mp_plan/gap_resolution/__init__.py`
- `mira/mp_plan/gap_resolution/base.py`
- `mira/mp_plan/gap_resolution/minor_quantity.py`
- `mira/mp_plan/gap_resolution/configuration.py`
- `mira/mp_plan/gap_resolution/heat_sink.py`
- `mira/mp_plan/gap_resolution/substitution.py`
- `mira/mp_plan/gap_resolution/test_program.py`
- `mira/mp_plan/gap_resolution/full_mua.py`

---

## Phase 4: API Router (2 days)

### 4.1 Create mp_plan Router
```python
# mira/api/routers/mp_plan.py

router = APIRouter(prefix="/mp-plan", tags=["mp-plan"])

# Session Management
@router.post("/sessions", response_model=SessionResponse)
async def create_session(request: CreateSessionRequest)

@router.get("/sessions/{session_id}", response_model=SessionResponse)
async def get_session(session_id: str)

@router.delete("/sessions/{session_id}")
async def delete_session(session_id: str)

# Data Entry
@router.post("/sessions/{session_id}/environments")
async def add_environment(session_id: str, env: EnvironmentRequest)

@router.post("/sessions/{session_id}/materials")
async def add_materials(session_id: str, materials: list[MaterialRequest])

@router.post("/sessions/{session_id}/resolve")
async def resolve_materials(session_id: str)

# Compute Loop
@router.get("/sessions/{session_id}/questions")
async def get_blocking_questions(session_id: str)

@router.post("/sessions/{session_id}/answer")
async def submit_answer(session_id: str, answer: AnswerRequest)

@router.post("/sessions/{session_id}/closure")
async def submit_closure(session_id: str, closure: ClosureRequest)

@router.post("/sessions/{session_id}/accept-open")
async def accept_open_gap(session_id: str, acceptance: AcceptanceRequest)

@router.post("/sessions/{session_id}/compute")
async def run_compute_loop(session_id: str)

# Generation
@router.post("/sessions/{session_id}/generate")
async def generate_artifacts(session_id: str, types: list[ArtifactType])

@router.get("/sessions/{session_id}/download/{artifact_type}")
async def download_artifact(session_id: str, artifact_type: str)

@router.get("/sessions/{session_id}/review-packet")
async def get_review_packet(session_id: str)

# Reference Data
@router.get("/policy-packs")
async def list_policy_packs()

@router.get("/vehicle-presets")
async def list_vehicle_presets()

@router.get("/closure-paths")
async def list_closure_paths()
```

### 4.2 Register Router
```python
# In mira/api/app.py
from mira.api.routers.mp_plan import router as mp_plan_router
app.include_router(mp_plan_router)
```

**Files:**
- `mira/api/routers/mp_plan.py` - New router
- `mira/api/schemas/mp_plan.py` - Request/response models
- `mira/api/app.py` - Register router

---

## Phase 5: Export Artifacts (2 days)

### 5.1 Applicability Matrix Excel
```python
def generate_applicability_matrix_xlsx(session: PlanGeneratorSession) -> bytes:
    """
    Generate applicability matrix with all MPRs.

    Columns:
    - MPR Number
    - MPR Title
    - Status (Applicable/Not Applicable/Tailored Out)
    - Rationale
    - Evidence/Citation
    - Triggered By (environment/material condition)
    """
```

### 5.2 Gap Register JSON
```python
def generate_gap_register_json(session: PlanGeneratorSession) -> dict:
    """
    Export all gaps with typed signals.

    Structure:
    {
        "session_id": "...",
        "generated_at": "...",
        "gaps": [
            {
                "gap_id": "...",
                "gap_type": "nonconformance",
                "material_id": "...",
                "environment_id": "...",
                "failure_mode": "FLAM",
                "severity": "medium",
                "failing_requirement": "MPR 44(a)",
                "failing_value": "C @ 23.5% O2",
                "required_value": "A @ 30% O2",
                "closure_status": "open|closed|accepted_open",
                "closure_path": "MINOR_QUANTITY",
                "closure_rationale": "..."
            }
        ],
        "summary": {
            "total_gaps": 1,
            "closed": 0,
            "accepted_open": 0,
            "open": 1
        }
    }
    """
```

### 5.3 Run Manifest JSON
```python
def generate_run_manifest_json(session: PlanGeneratorSession) -> dict:
    """
    Complete audit trail.

    Structure:
    {
        "manifest_id": "...",
        "generated_at": "...",
        "session": {
            "session_id": "...",
            "created_at": "...",
            "policy_pack_id": "...",
            "policy_pack_hash": "..."
        },
        "inputs": {
            "environments": [...],
            "materials": [...],
            "resolutions": [...]
        },
        "decisions": {
            "user_answers": [...],
            "closure_decisions": [...],
            "accepted_open_gaps": [...]
        },
        "outputs": {
            "artifacts_generated": [
                {"type": "mp_plan_docx", "hash": "...", "generated_at": "..."},
                {"type": "miul_xlsx", "hash": "...", "generated_at": "..."}
            ]
        },
        "engine_versions": {
            "mp_plan": "2.0.0",
            "compliance": "1.0.0",
            "maptis_adapter": "1.0.0"
        },
        "fingerprints": {
            "session_state_hash": "...",
            "policy_pack_hash": "...",
            "mpr_index_hash": "..."
        }
    }
    """
```

**Files:**
- `mira/mp_plan/generation/applicability_xlsx.py`
- `mira/mp_plan/generation/gap_register.py`
- `mira/mp_plan/generation/run_manifest.py`

---

## Phase 6: CLI (1 day)

### 6.1 CLI Commands
```python
# mira/mp_plan/cli.py

@click.group()
def mp_plan():
    """M&P Plan Generator CLI."""

@mp_plan.command()
@click.option("--program", required=True)
@click.option("--vehicle", type=click.Choice(["ISS", "HLS", "ORION", "GATEWAY"]))
def create(program: str, vehicle: str):
    """Create a new session."""

@mp_plan.command()
@click.argument("session_id")
@click.option("--name", required=True)
@click.option("--application", required=True)
@click.option("--maptis-code")
def add_material(session_id: str, name: str, application: str, maptis_code: str):
    """Add a material to the session."""

@mp_plan.command()
@click.argument("session_id")
def compute(session_id: str):
    """Run the compute loop."""

@mp_plan.command()
@click.argument("session_id")
def questions(session_id: str):
    """Show blocking questions."""

@mp_plan.command()
@click.argument("session_id")
@click.option("--output-dir", type=click.Path(), default=".")
def generate(session_id: str, output_dir: str):
    """Generate all artifacts."""
```

**Files:**
- `mira/mp_plan/cli.py`

---

## Implementation Schedule

| Phase | Component | Days | Dependencies |
|-------|-----------|------|--------------|
| 1 | Output Quality Fixes | 2 | None |
| 2 | MPR Index Expansion | 3 | None |
| 3 | Closure Paths | 4 | Phase 2 |
| 4 | API Router | 2 | Phase 3 |
| 5 | Export Artifacts | 2 | Phase 3 |
| 6 | CLI | 1 | Phase 4 |

**Total: 14 days**

---

## Verification Checklist

| # | Criterion | Test |
|---|-----------|------|
| 1 | 54 MPRs in index | `len(mpr_index.mprs) == 54` |
| 2 | Closure paths work | Each path returns eligible/not eligible with rationale |
| 3 | API endpoints functional | All endpoints return 200 with valid data |
| 4 | Artifacts generated | All 6 artifact types produce valid files |
| 5 | Audit trail complete | Run manifest has all decisions logged |
| 6 | Test deltas in DOCX | Section 4.0 shows O2/pressure deltas |
| 7 | MIUL Summary populated | Metrics and action items shown |
| 8 | Reviewer questions predicted | Review packet generates relevant Qs |

---

## Files Summary

### New Files
```
mira/mp_plan/gap_resolution/
├── __init__.py
├── base.py
├── minor_quantity.py
├── configuration.py
├── heat_sink.py
├── substitution.py
├── test_program.py
└── full_mua.py

mira/mp_plan/generation/
├── applicability_xlsx.py
├── gap_register.py
└── run_manifest.py

mira/mp_plan/data/
└── mpr_triggers.yaml

mira/api/routers/
└── mp_plan.py

mira/api/schemas/
└── mp_plan.py

mira/mp_plan/
└── cli.py
```

### Modified Files
```
mira/compliance/data/mprs_6016c.yaml  # Expand 15 → 54 MPRs
mira/api/app.py                        # Register mp_plan router
mira/mp_plan/generation/__init__.py    # Export new generators
```

---

## Next Steps

1. **Start with Phase 1.3** - Finish remaining output improvements
2. **Then Phase 2** - MPR index expansion is foundational
3. **Phase 3** - Closure paths are the core differentiator

Which phase should we tackle first?
