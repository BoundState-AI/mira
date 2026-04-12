#!/usr/bin/env python3
"""
Module: H2 Knowledge Twin V2 — Type Definitions
Purpose: Enums and dataclasses for the H2 compatibility assessment engine.

BoundState AI 2025
Version: 2.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude "Atlas" <noreply@anthropic.com>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: SWE-013, NASA-STD-8739.8B
Safety Critical: True

Extracted from h2_knowledge_twin_v2.py to separate pure type definitions
(enums, dataclasses) from engine logic (scoring, rules, decisions).
No business logic. No side effects. No imports beyond stdlib.

Design principles (from original module, non-negotiable):
1. EVIDENCE-FIRST — No claim without source pointer and extracted value.
2. CONSERVATIVE UNDER UNCERTAINTY — Weak match → trend toward Unknown.
3. DETERMINISTIC + AUDITABLE — Same inputs → same result.
4. HUMAN-LEGIBLE REASONING — Engineers can read and disagree.
5. DOMAIN-ACCURATE — Structures match source documents exactly.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

# =============================================================================
# SECTION 2: ENUMERATIONS
# =============================================================================

class Verdict(Enum):
    """
    Decision output per Fran's spec.
    """
    ALLOWED = "allowed"                           # Strong match, minimal gaps, primary test evidence
    ALLOWED_WITH_CONSTRAINTS = "allowed_with_constraints"  # Decent match, some gaps
    NOT_RECOMMENDED = "not_recommended"           # Evidence shows severe risk
    UNKNOWN = "unknown"                           # Insufficient evidence


class HEEBand(Enum):
    """
    HEE Classification per NASA/TM-2016-218602 Table 1.
    THESE ARE THE AUTHORITATIVE THRESHOLDS.
    """
    NEGLIGIBLE = "negligible"   # 0.97-1.00
    SMALL = "small"             # 0.90-0.96
    HIGH = "high"               # 0.70-0.89
    SEVERE = "severe"           # 0.50-0.69
    EXTREME = "extreme"         # 0.00-0.49


class HEMechanism(Enum):
    """
    Three distinct hydrogen embrittlement mechanisms.
    Per NASA/TM-2016-218602 Figure 1.
    
    THESE ARE NOT INTERCHANGEABLE. IHE data should not be mixed with
    HEE data without explicit flagging.
    """
    HEE = "HEE"  # Hydrogen Environment Embrittlement - external gaseous H2
    IHE = "IHE"  # Internal Hydrogen Embrittlement - absorbed/dissolved H2
    HRE = "HRE"  # Hydrogen Reaction Embrittlement - chemical reaction (hydrides)


class EvidenceGrade(Enum):
    """
    Evidence quality hierarchy per Fran's spec.
    PRIMARY_TEST > SECONDARY_SUMMARY > GUIDELINE_STATEMENT
    
    Guideline statements can exist but must NEVER dominate over
    primary tests when both exist.
    """
    PRIMARY_TEST = "primary_test"           # Direct test result from source
    SECONDARY_SUMMARY = "secondary_summary" # Summarized from multiple tests
    GUIDELINE_STATEMENT = "guideline_statement"  # General guidance without specific test


class Phase(Enum):
    """Hydrogen phase."""
    GH2 = "GH2"      # Gaseous hydrogen
    LH2 = "LH2"      # Liquid hydrogen (cryogenic)
    UNKNOWN = "unknown"


class LoadingMode(Enum):
    """Loading mode for service conditions."""
    STATIC = "static"
    CYCLIC = "cyclic"
    IMPACT = "impact"
    UNKNOWN = "unknown"


class SpecimenType(Enum):
    """
    Test specimen geometry.
    CRITICAL: Each type uses a DIFFERENT loading rate parameter.
    """
    SMOOTH = "smooth"           # For RA and EL → uses strain_rate
    NOTCHED = "notched"         # For NTS → uses stroke_rate
    PRECRACKED = "precracked"   # For KTH/KIC → uses displacement_rate


class ProductForm(Enum):
    """
    Product form affects HEE susceptibility significantly.
    Per NASA/TM-2016-218602 Tables 7, 9, 11.
    """
    PLATE = "plate"
    BAR = "bar"
    ROLLED_BAR = "rolled_bar"
    FORGING = "forging"
    SHEET = "sheet"
    TUBING = "tubing"
    FASTENER = "fastener"
    CASTING = "casting"
    POWDER_METALLURGY = "PM"
    WIRE = "wire"
    UNKNOWN = "unknown"


class WeldState(Enum):
    """Weld condition - HAZ often worse than base metal."""
    BASE_METAL = "base_metal"
    WELD_METAL = "weld_metal"
    HAZ = "HAZ"                 # Heat Affected Zone - OFTEN WORSE
    UNKNOWN = "unknown"


class MaterialFamily(Enum):
    """
    Material family classification.
    Aligned with Sandia material codes.
    """
    # Ferritic Steels (Sandia 1xxx)
    CARBON_STEEL = "carbon_steel"                 # 1100
    LOW_ALLOY_CR_MO = "low_alloy_cr_mo"          # 1211
    LOW_ALLOY_NI_CR_MO = "low_alloy_ni_cr_mo"    # 1212
    HIGH_STRENGTH_9NI_4CO = "high_strength_9ni_4co"  # 1401
    FERRITIC_SS = "ferritic_ss"                  # 1500
    DUPLEX_SS = "duplex_ss"                      # 1600
    SEMI_AUSTENITIC_SS = "semi_austenitic_ss"    # 1700
    MARTENSITIC_SS_PH = "martensitic_ss_ph"      # 1810
    MARTENSITIC_SS_HT = "martensitic_ss_ht"      # 1820
    
    # Austenitic Steels (Sandia 2xxx)
    AUSTENITIC_SS_304 = "austenitic_ss_304"      # 2101
    AUSTENITIC_SS_316 = "austenitic_ss_316"      # 2103
    AUSTENITIC_SS_321_347 = "austenitic_ss_321_347"  # 2104
    NITROGEN_SS = "nitrogen_ss"                  # 2201, 2202
    PH_SS_A286 = "ph_ss_a286"                    # 2301
    
    # Superalloys
    NICKEL_SUPERALLOY = "nickel_superalloy"      # Inconel, Waspaloy, etc.
    IRON_SUPERALLOY = "iron_superalloy"          # A-286, JBK-75, Incoloy
    COBALT_SUPERALLOY = "cobalt_superalloy"      # Haynes 188
    
    # Other
    ALUMINUM = "aluminum"                        # 3xxx - Generally negligible HEE
    COPPER = "copper"                            # 4xxx - Generally negligible HEE
    TITANIUM = "titanium"                        # Forms hydrides (HRE risk)
    NICKEL_ALLOY = "nickel_alloy"               # 5xxx
    
    UNKNOWN = "unknown"


class HeatTreatCondition(Enum):
    """Heat treatment condition category."""
    ANNEALED = "annealed"
    SOLUTION_TREATED = "solution_treated"        # ST - often BETTER than aged
    SOLUTION_TREATED_AGED = "solution_treated_aged"  # STA - often WORSE
    NORMALIZED = "normalized"
    QUENCHED_TEMPERED = "quenched_tempered"
    AS_RECEIVED = "as_received"
    UNKNOWN = "unknown"


class ReferenceEnvironment(Enum):
    """Reference environment for ratio calculations."""
    HELIUM = "helium"    # Preferred
    AIR = "air"
    NITROGEN = "nitrogen"
    ARGON = "argon"


class TemperatureBehavior(Enum):
    """
    Temperature dependence pattern for HEE.
    Per NASA/TM-2016-218602 Figures 12-14.
    
    CRITICAL: Some superalloys are WORST at elevated temp, not room temp!
    """
    PEAK_NEAR_AMBIENT = "peak_near_ambient"      # Most austenitic SS, Inconel 718
    PEAK_AT_ELEVATED = "peak_at_elevated"        # EP99, EP741, Astroloy, MERL 76
    NEGLIGIBLE_AT_CRYO = "negligible_at_cryo"    # Most materials good below -200°C


# =============================================================================
# SECTION 3: AUTHORITATIVE THRESHOLDS (TRACEABLE)
# =============================================================================

# NASA/TM-2016-218602, Table 1 - THE NUMBERS
HEE_BAND_THRESHOLDS: Dict[HEEBand, Tuple[float, float]] = {
    HEEBand.NEGLIGIBLE: (0.97, 1.00),
    HEEBand.SMALL:      (0.90, 0.96),
    HEEBand.HIGH:       (0.70, 0.89),
    HEEBand.SEVERE:     (0.50, 0.69),
    HEEBand.EXTREME:    (0.00, 0.49),
}

# Test condition validity envelope - NASA data bounds
# Source: NASA/TM-2016-218602 Section 3.3
VALIDITY_ENVELOPE = {
    "temperature_c": {"min": 20.0, "max": 26.0, "nominal": 22.0},
    "pressure_mpa": {"min": 34.5, "max": 69.0},
}

# Nickel content predictor for Fe-Ni-Cr systems
# Source: NASA/TM-2016-218602 Table 10, Figure 15
NI_PREDICTOR = {
    "threshold_wt_pct": 12.5,  # Above this → typically negligible HEE
    "max_for_predictor": 35.0,  # Above this → Ni-rich superalloys can be WORSE
    "valid_conditions": ["annealed", "solution_treated"],  # NOT valid for aged!
}

# Sandia material codes mapping
SANDIA_CODES = {
    "1100": MaterialFamily.CARBON_STEEL,
    "1211": MaterialFamily.LOW_ALLOY_CR_MO,
    "1212": MaterialFamily.LOW_ALLOY_NI_CR_MO,
    "1401": MaterialFamily.HIGH_STRENGTH_9NI_4CO,
    "1500": MaterialFamily.FERRITIC_SS,
    "1600": MaterialFamily.DUPLEX_SS,
    "1700": MaterialFamily.SEMI_AUSTENITIC_SS,
    "1810": MaterialFamily.MARTENSITIC_SS_PH,
    "1820": MaterialFamily.MARTENSITIC_SS_HT,
    "2101": MaterialFamily.AUSTENITIC_SS_304,
    "2103": MaterialFamily.AUSTENITIC_SS_316,
    "2104": MaterialFamily.AUSTENITIC_SS_321_347,
    "2201": MaterialFamily.NITROGEN_SS,
    "2202": MaterialFamily.NITROGEN_SS,
    "2301": MaterialFamily.PH_SS_A286,
    "3101": MaterialFamily.ALUMINUM,
    "3210": MaterialFamily.ALUMINUM,
    "3230": MaterialFamily.ALUMINUM,
    "4001": MaterialFamily.COPPER,
    "5110": MaterialFamily.NICKEL_ALLOY,
}

# Materials with elevated temperature HEE peak (NOT room temp)
# Source: NASA/TM-2016-218602 Figures 13-14
ELEVATED_TEMP_PEAK_MATERIALS = [
    "EP99", "EP741", "Astroloy", "MERL 76", "IN100", 
    "Waspaloy", "Udimet 700"
]


# =============================================================================
# SECTION 4: CORE DATA MODELS
# =============================================================================

@dataclass
class Composition:
    """
    Chemical composition - critical for predictive rules.
    Weight percentages. All optional but Ni is KEY for Fe-Ni-Cr systems.
    """
    ni_wt_pct: Optional[float] = None  # KEY PREDICTOR
    cr_wt_pct: Optional[float] = None
    fe_wt_pct: Optional[float] = None
    mo_wt_pct: Optional[float] = None
    mn_wt_pct: Optional[float] = None
    c_wt_pct: Optional[float] = None
    n_wt_pct: Optional[float] = None
    si_wt_pct: Optional[float] = None
    ti_wt_pct: Optional[float] = None
    al_wt_pct: Optional[float] = None
    cu_wt_pct: Optional[float] = None
    co_wt_pct: Optional[float] = None
    nb_wt_pct: Optional[float] = None
    v_wt_pct: Optional[float] = None
    w_wt_pct: Optional[float] = None
    source: str = ""  # NASA SWE-013 traceability

    
    def nickel_equivalent(self) -> Optional[float]:
        """
        Calculate Ni equivalent for austenite stability.
        Nieq = Ni + 30*C + 0.5*Mn + 30*N
        """
        if self.ni_wt_pct is None:
            return None
        nieq = self.ni_wt_pct
        if self.c_wt_pct:
            nieq += 30 * self.c_wt_pct
        if self.mn_wt_pct:
            nieq += 0.5 * self.mn_wt_pct
        if self.n_wt_pct:
            nieq += 30 * self.n_wt_pct
        return nieq


@dataclass
class HeatTreatment:
    """
    Full heat treatment specification.
    NOT AN ENUM - because Inconel 718 at 940°C ST vs 1037°C ST
    is the difference between 0.53 and 0.92 HEE index.
    
    Per NASA/TM-2016-218602 Tables 7, 8, 9.
    """
    condition: HeatTreatCondition
    solution_temp_c: Optional[float] = None
    solution_time_hr: Optional[float] = None
    quench_medium: Optional[str] = None       # "WQ", "OQ", "AC"
    age_temp_c: Optional[float] = None
    age_time_hr: Optional[float] = None
    second_age_temp_c: Optional[float] = None
    second_age_time_hr: Optional[float] = None
    description: Optional[str] = None
    source: str = ""  # NASA SWE-013 traceability

    
    def is_aged(self) -> bool:
        """Check if material is in aged condition."""
        return (
            self.condition == HeatTreatCondition.SOLUTION_TREATED_AGED or
            self.age_temp_c is not None
        )


@dataclass
class StrengthData:
    """Strength properties."""
    yield_mpa: Optional[float] = None
    uts_mpa: Optional[float] = None
    hardness_hrc: Optional[float] = None
    hardness_hv: Optional[float] = None
    source: str = ""  # NASA SWE-013 traceability



@dataclass 
class LoadingRates:
    """
    Loading rates for mechanical testing.
    
    CRITICAL: These are THREE DIFFERENT parameters for THREE DIFFERENT
    specimen types. They are NOT interchangeable.
    
    Per ASTM G129, NASA/TM-2016-218602 Section 3.2.
    """
    # For SMOOTH specimens (RA, EL measurements)
    strain_rate_per_s: Optional[float] = None       # ≤8.3×10⁻⁶ /s
    
    # For NOTCHED specimens (NTS measurements)  
    stroke_rate_mm_s: Optional[float] = None        # ≤2.1×10⁻⁴ mm/s
    
    # For PRECRACKED specimens (KTH/KIC measurements)
    displacement_rate_um_hr: Optional[float] = None # 1-10 µm/h
    source: str = ""  # NASA SWE-013 traceability



# =============================================================================
# SECTION 5: MATERIAL ENTITY
# =============================================================================

@dataclass
class MaterialRecord:
    """
    Material entity - the "what" being evaluated.
    """
    # Identity
    material_key: str                              # Canonical ID
    name: str                                      # Human readable
    spec: Optional[str] = None                     # AMS 5662, etc.
    uns: Optional[str] = None                      # Unified Numbering System
    
    # Classification
    family: MaterialFamily = MaterialFamily.UNKNOWN
    aliases: List[str] = field(default_factory=list)
    
    # Composition
    composition: Optional[Composition] = None
    
    # Condition
    heat_treatment: Optional[HeatTreatment] = None
    strength: Optional[StrengthData] = None
    product_form: ProductForm = ProductForm.UNKNOWN
    weld_state: WeldState = WeldState.BASE_METAL
    grain_direction: Optional[str] = None          # "longitudinal", "transverse"
    source: str = ""  # NASA SWE-013 traceability

    
    def condition_key(self) -> str:
        """Generate condition identifier for matching."""
        parts = [self.material_key]
        if self.heat_treatment:
            parts.append(self.heat_treatment.condition.value)
            if self.heat_treatment.solution_temp_c:
                parts.append(f"ST{int(self.heat_treatment.solution_temp_c)}")
        if self.product_form != ProductForm.UNKNOWN:
            parts.append(self.product_form.value)
        if self.weld_state != WeldState.BASE_METAL:
            parts.append(self.weld_state.value)
        return "_".join(parts)


# =============================================================================
# SECTION 6: ENVIRONMENT + LOADING ENTITIES
# =============================================================================

@dataclass
class HydrogenEnvironment:
    """
    Hydrogen environment specification.
    All values normalized to SI units internally.
    """
    phase: Phase
    pressure_mpa: float
    temperature_c: float
    purity_pct: float = 99.98
    exposure_type: str = "continuous"  # "continuous", "intermittent"
    source: str = ""  # NASA SWE-013 traceability

    
    def is_cryogenic(self) -> bool:
        """Check if environment is cryogenic (LH2 territory)."""
        return self.temperature_c < -150 or self.phase == Phase.LH2
    
    def is_within_nasa_envelope(self) -> Tuple[bool, List[str]]:
        """
        Check if environment is within NASA test data validity envelope.
        Returns (is_valid, list_of_warnings).
        
        CRITICAL: Outside this envelope, data may not apply!
        """
        warnings = []
        
        temp_env = VALIDITY_ENVELOPE["temperature_c"]
        if not (temp_env["min"] <= self.temperature_c <= temp_env["max"]):
            warnings.append(
                f"Temperature {self.temperature_c}°C outside NASA test envelope "
                f"({temp_env['min']}-{temp_env['max']}°C). "
                "HEE behavior at this temperature may differ significantly."
            )
        
        press_env = VALIDITY_ENVELOPE["pressure_mpa"]
        if not (press_env["min"] <= self.pressure_mpa <= press_env["max"]):
            warnings.append(
                f"Pressure {self.pressure_mpa} MPa outside NASA test envelope "
                f"({press_env['min']}-{press_env['max']} MPa)."
            )
        
        if self.phase == Phase.LH2:
            warnings.append(
                "LH2 (cryogenic) service. Most NASA HEE data is for room temperature. "
                "Many materials show NEGLIGIBLE HEE at cryogenic temps, but verify with cryo-specific data."
            )
        
        return (len(warnings) == 0, warnings)


@dataclass
class LoadingState:
    """
    Loading conditions for service.
    """
    mode: LoadingMode = LoadingMode.UNKNOWN
    sigma_max_mpa: Optional[float] = None
    fraction_of_yield: Optional[float] = None
    has_notch: Optional[bool] = None              # Stress concentration present?
    stress_concentration_kt: Optional[float] = None
    loading_rates: Optional[LoadingRates] = None  # For test conditions
    
    # For cyclic loading
    load_ratio_r: Optional[float] = None          # R = min/max
    frequency_hz: Optional[float] = None
    source: str = ""  # NASA SWE-013 traceability



# =============================================================================
# SECTION 7: EVIDENCE OBJECT (THE UNIT OF TRUTH)
# =============================================================================

@dataclass
class Provenance:
    """
    Full provenance tracking for traceability.
    Every claim must have this.
    """
    doc_id: str                                   # "NASA-TM-2016-218602"
    doc_title: str
    page: Optional[int] = None
    table_id: Optional[str] = None                # "Table 9"
    figure_id: Optional[str] = None
    section: Optional[str] = None
    snippet_text: Optional[str] = None            # Short excerpt
    bbox: Optional[Tuple[int, int, int, int]] = None  # For Athena extraction
    reference_key: Optional[str] = None           # "a, b" footnote refs
    original_authors: Optional[str] = None
    original_report: Optional[str] = None
    extraction_timestamp: datetime = field(default_factory=datetime.now)
    source: str = ""  # NASA SWE-013 traceability



@dataclass
class MetricValue:
    """
    A measured value with units and interpretation.
    """
    metric_name: str                              # "NTS_ratio", "RA_ratio", "KTH_KIC_ratio"
    value: float
    units: str                                    # "ratio", "MPa", "MPa√m"
    directionality: str = "higher_is_better"      # or "lower_is_better", "banded"
    source: str = ""  # NASA SWE-013 traceability

    
    def to_hee_band(self) -> Optional[HEEBand]:
        """Convert ratio metric to HEE band if applicable."""
        if "ratio" not in self.metric_name.lower():
            return None
        return classify_hee_band(self.value)


@dataclass
class EvidenceObject:
    """
    THE UNIT OF TRUTH.
    
    Each evidence object represents a single test result or data point
    from source literature. This is what the decision engine reasons over.
    
    Per Fran's spec: guideline_statement can exist but must NEVER dominate
    over primary_test when both exist for same envelope.
    """
    # Identity
    evidence_id: str
    
    # What material?
    material_key: str
    material_family: MaterialFamily
    material_condition: Optional[str] = None      # "ST", "STA", etc.
    
    # Heat treatment details (critical for superalloys)
    heat_treatment: Optional[HeatTreatment] = None
    
    # What product form?
    product_form: ProductForm = ProductForm.UNKNOWN
    weld_state: WeldState = WeldState.BASE_METAL
    grain_direction: Optional[str] = None
    
    # What environment?
    environment: Optional[HydrogenEnvironment] = None
    reference_environment: ReferenceEnvironment = ReferenceEnvironment.HELIUM
    
    # What loading?
    loading: Optional[LoadingState] = None
    
    # What test?
    test_method: str = ""                         # "ASTM G129", "ASTM E1681"
    specimen_type: SpecimenType = SpecimenType.NOTCHED
    he_mechanism: HEMechanism = HEMechanism.HEE
    
    # THE DATA
    metric: Optional[MetricValue] = None
    hee_band: Optional[HEEBand] = None
    
    # Quality assessment
    grade: EvidenceGrade = EvidenceGrade.PRIMARY_TEST
    extraction_confidence: float = 1.0            # 0-1
    
    # Provenance (REQUIRED)
    provenance: Optional[Provenance] = None
    
    # Notes
    notes: Optional[str] = None
    source: str = ""  # NASA SWE-013 traceability

    
    def __post_init__(self):
        """Auto-classify HEE band from metric if not provided."""
        if self.hee_band is None and self.metric:
            self.hee_band = self.metric.to_hee_band()


# =============================================================================
# SECTION 8: QUERY AND RESPONSE MODELS
# =============================================================================

@dataclass
class H2Query:
    """
    User query input.
    Per Fran's spec - minimum viable inputs with explicit unknowns.
    """
    # Material (required)
    material_name: str
    material_spec: Optional[str] = None
    
    # Condition (all optional, but gaps will be flagged)
    condition: HeatTreatCondition = HeatTreatCondition.UNKNOWN
    heat_treatment: Optional[HeatTreatment] = None
    strength: Optional[StrengthData] = None
    product_form: ProductForm = ProductForm.UNKNOWN
    weld_state: WeldState = WeldState.BASE_METAL
    
    # Environment (required for meaningful answer)
    phase: Phase = Phase.UNKNOWN
    pressure_mpa: Optional[float] = None
    temperature_c: Optional[float] = None
    
    # Loading (optional but recommended)
    loading_mode: LoadingMode = LoadingMode.UNKNOWN
    has_notch: Optional[bool] = None
    sigma_max_mpa: Optional[float] = None
    fraction_of_yield: Optional[float] = None
    
    # Options
    consequence_class: str = "medium"             # "low", "medium", "high"
    prefer_conservative: bool = True
    source: str = ""  # NASA SWE-013 traceability



@dataclass
class Driver:
    """
    A failure mode driver with evidence.
    """
    failure_mode: str                             # "HEE susceptibility"
    severity: str                                 # "severe", "high", etc.
    trigger_parameter: str                        # What caused this flag
    explanation: str
    evidence_ids: List[str] = field(default_factory=list)
    source: str = ""  # NASA SWE-013 traceability



@dataclass
class Constraint:
    """
    An explicit constraint on usage.
    Not "be careful" - specific actionable limits.
    """
    parameter: str                                # "strength", "temperature"
    limit_type: str                               # "max", "min", "avoid"
    limit_value: Optional[str] = None             # "1200 MPa", "-196°C"
    rationale: str = ""
    evidence_id: Optional[str] = None
    source: str = ""  # NASA SWE-013 traceability



@dataclass
class Gap:
    """
    Missing input that would strengthen the verdict.
    """
    parameter: str                                # "strength", "heat_treatment"
    impact: str                                   # How this affects the verdict
    default_assumption: Optional[str] = None      # What we assumed
    source: str = ""  # NASA SWE-013 traceability



@dataclass
class RecommendedTest:
    """
    Test that would resolve a gap.
    """
    test_type: str                                # "notched tensile"
    description: str
    target_conditions: str                        # "in H2 at 69 MPa, 22°C"
    standard: Optional[str] = None                # "ASTM G129"
    source: str = ""  # NASA SWE-013 traceability



@dataclass
class MatchStats:
    """
    Envelope match statistics for audit.
    """
    evidence_id: str
    envelope_match_score: float
    dimension_scores: Dict[str, float]            # Per-dimension breakdown
    evidence_weight: float
    source: str = ""  # NASA SWE-013 traceability



@dataclass
class AuditTrail:
    """
    Full audit trail for reproducibility.
    """
    query_id: str
    timestamp: datetime
    engine_version: str
    rule_triggers: List[str]
    match_stats: List[MatchStats]
    dominant_evidence_ids: List[str]
    confidence_calculation: str
    source: str = ""  # NASA SWE-013 traceability



@dataclass
class H2Response:
    """
    System response per Fran's spec.
    Everything is traceable. No vibes.
    """
    # The answer
    verdict: Verdict
    confidence: float                             # 0-1
    
    # Human readable
    decision_summary: str                         # 3-6 sentences
    
    # Supporting detail
    drivers: List[Driver] = field(default_factory=list)
    constraints: List[Constraint] = field(default_factory=list)
    gaps: List[Gap] = field(default_factory=list)
    recommended_tests: List[RecommendedTest] = field(default_factory=list)
    
    # Evidence
    evidence: List[EvidenceObject] = field(default_factory=list)
    
    # Audit
    audit: Optional[AuditTrail] = None
    
    # Warnings (envelope, weld, etc.)
    warnings: List[str] = field(default_factory=list)
    source: str = ""  # NASA SWE-013 traceability


