#!/usr/bin/env python3
"""
Module: H2 Knowledge Twin V2
Purpose: from __future__ import annotations

BoundState AI 2025
Version: 1.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Fran OpenAI 5 <noreply@openai.com>
Co-Authored-By: Grok 4.0 <noreply@x.ai>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: SWE-013, NASA-STD-8739.8B
Safety Critical: True
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

# =============================================================================
# SECTION 1: DESIGN PRINCIPLES (NON-NEGOTIABLE)
# =============================================================================
"""
1. EVIDENCE-FIRST
   No claim without a pointer to a source and a concrete extracted value.
   
2. CONSERVATIVE UNDER UNCERTAINTY
   If envelope match is weak or missing key inputs, verdict trends toward
   Unknown or Allowed-with-constraints. Never "Allowed" by vibes.
   
3. DETERMINISTIC + AUDITABLE
   Same inputs → same result. Every step logs evidence IDs, match scores,
   and rule triggers.
   
4. HUMAN-LEGIBLE REASONING
   Engineers must be able to read the answer and disagree constructively.

5. DOMAIN-ACCURATE
   Data structures match the source documents exactly. No hand-wavy fields.
   Three loading rates, not one. Full heat treatment, not an enum.
"""

logger = logging.getLogger(__name__)


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



# =============================================================================
# SECTION 9: CLASSIFICATION FUNCTIONS
# =============================================================================

def classify_hee_band(index: float) -> HEEBand:
    """
    Classify HEE index to band per NASA/TM-2016-218602 Table 1.
    """
    if index >= 0.97:
        return HEEBand.NEGLIGIBLE
    elif index >= 0.90:
        return HEEBand.SMALL
    elif index >= 0.70:
        return HEEBand.HIGH
    elif index >= 0.50:
        return HEEBand.SEVERE
    else:
        return HEEBand.EXTREME


def band_to_verdict_floor(band: HEEBand) -> Verdict:
    """
    Map HEE band to minimum verdict (floor).
    Conservative: severe/extreme → not_recommended.
    """
    if band == HEEBand.NEGLIGIBLE:
        return Verdict.ALLOWED_WITH_CONSTRAINTS  # Need strong match for ALLOWED
    elif band == HEEBand.SMALL:
        return Verdict.ALLOWED_WITH_CONSTRAINTS
    elif band == HEEBand.HIGH:
        return Verdict.ALLOWED_WITH_CONSTRAINTS
    elif band == HEEBand.SEVERE:
        return Verdict.NOT_RECOMMENDED
    else:  # EXTREME
        return Verdict.NOT_RECOMMENDED


def apply_ni_predictor(
    ni_wt_pct: float,
    family: MaterialFamily,
    condition: HeatTreatCondition
) -> Tuple[Optional[HEEBand], str, float]:
    """
    Apply nickel content predictor for Fe-Ni-Cr systems.
    Per NASA/TM-2016-218602 Table 10, Figure 15.
    
    Returns: (predicted_band, rationale, confidence)
    """
    # Check applicability
    fe_ni_cr_families = [
        MaterialFamily.AUSTENITIC_SS_304,
        MaterialFamily.AUSTENITIC_SS_316,
        MaterialFamily.AUSTENITIC_SS_321_347,
        MaterialFamily.NITROGEN_SS,
        MaterialFamily.PH_SS_A286,
        MaterialFamily.IRON_SUPERALLOY,
        MaterialFamily.NICKEL_SUPERALLOY,
    ]
    
    if family not in fe_ni_cr_families:
        return (None, "Ni predictor only valid for Fe-Ni-Cr systems", 0.0)
    
    if condition not in [HeatTreatCondition.ANNEALED, HeatTreatCondition.SOLUTION_TREATED]:
        return (
            None,
            f"Ni predictor requires annealed/ST condition. "
            f"Aging significantly increases susceptibility regardless of Ni content.",
            0.0
        )
    
    # Apply predictor
    if ni_wt_pct < 8.0:
        return (
            HEEBand.SEVERE,
            f"Ni {ni_wt_pct}% < 8% → typically severe HEE",
            0.7
        )
    elif ni_wt_pct < NI_PREDICTOR["threshold_wt_pct"]:
        return (
            HEEBand.HIGH,
            f"Ni {ni_wt_pct}% in transition zone (8-12.5%)",
            0.6
        )
    elif ni_wt_pct <= NI_PREDICTOR["max_for_predictor"]:
        return (
            HEEBand.NEGLIGIBLE,
            f"Ni {ni_wt_pct}% in negligible range (12.5-35%) per Table 10",
            0.75
        )
    else:
        return (
            HEEBand.HIGH,
            f"Ni {ni_wt_pct}% > 35% → Ni-rich superalloys can show increased susceptibility",
            0.5
        )


def get_temperature_behavior(family: MaterialFamily, material_name: str) -> TemperatureBehavior:
    """
    Get expected temperature dependence for HEE.
    Per NASA/TM-2016-218602 Figures 12-14.
    
    CRITICAL: Some superalloys peak at 400-600°C, NOT room temp!
    """
    # Check for elevated temp peak materials
    for mat in ELEVATED_TEMP_PEAK_MATERIALS:
        if mat.lower() in material_name.lower():
            return TemperatureBehavior.PEAK_AT_ELEVATED
    
    # Most austenitic materials peak near ambient
    if family in [
        MaterialFamily.AUSTENITIC_SS_304,
        MaterialFamily.AUSTENITIC_SS_316,
        MaterialFamily.AUSTENITIC_SS_321_347,
        MaterialFamily.IRON_SUPERALLOY,
    ]:
        return TemperatureBehavior.PEAK_NEAR_AMBIENT
    
    return TemperatureBehavior.PEAK_NEAR_AMBIENT


# =============================================================================
# SECTION 10: ENVELOPE MATCHING ENGINE
# =============================================================================

class EnvelopeMatchScorer:
    """
    Compute envelope match scores between query and evidence.
    Per Fran's spec: deterministic, per-dimension scoring.
    """
    
    @staticmethod
    def score_pressure(query_mpa: Optional[float], evidence_mpa: Optional[float]) -> float:
        """
        Score pressure match on log scale (hydrogen effects are pressure-sensitive).
        """
        if query_mpa is None or evidence_mpa is None:
            return 0.5  # Neutral but flagged as gap
        
        if evidence_mpa <= 0 or query_mpa <= 0:
            return 0.0
        
        # Log scale ratio
        import math
        ratio = math.log10(query_mpa) / math.log10(evidence_mpa)
        
        # Score: 1.0 if exact, decreasing with distance
        if 0.8 <= ratio <= 1.2:
            return 1.0 - abs(1.0 - ratio) * 0.5
        elif 0.5 <= ratio <= 2.0:
            return 0.6
        else:
            return 0.3
    
    @staticmethod
    def score_temperature(query_c: Optional[float], evidence_c: Optional[float]) -> float:
        """
        Score temperature match.
        Special handling for cryo boundary.
        """
        if query_c is None or evidence_c is None:
            return 0.5
        
        # Cryo boundary: big change in behavior
        query_cryo = query_c < -150
        evidence_cryo = evidence_c < -150
        
        if query_cryo != evidence_cryo:
            return 0.2  # Heavy penalty for crossing cryo boundary
        
        # Within same regime: absolute distance
        diff = abs(query_c - evidence_c)
        if diff < 10:
            return 1.0
        elif diff < 50:
            return 0.8
        elif diff < 100:
            return 0.5
        else:
            return 0.3
    
    @staticmethod
    def score_phase(query: Phase, evidence: Phase) -> float:
        """GH2 vs LH2 mismatch penalized heavily."""
        if query == Phase.UNKNOWN or evidence == Phase.UNKNOWN:
            return 0.5
        if query == evidence:
            return 1.0
        return 0.3  # Heavy penalty
    
    @staticmethod
    def score_loading(query: LoadingMode, evidence: LoadingMode) -> float:
        """Static vs cyclic mismatch penalized."""
        if query == LoadingMode.UNKNOWN or evidence == LoadingMode.UNKNOWN:
            return 0.5
        if query == evidence:
            return 1.0
        # Cyclic is generally more severe
        if evidence == LoadingMode.CYCLIC and query == LoadingMode.STATIC:
            return 0.7  # Evidence is conservative
        return 0.4
    
    @staticmethod
    def score_condition(query_ht: Optional[HeatTreatment], evidence_ht: Optional[HeatTreatment]) -> float:
        """
        Score heat treatment condition match.
        CRITICAL: Aged vs non-aged is huge difference.
        """
        if query_ht is None or evidence_ht is None:
            return 0.5
        
        # Aged mismatch is severe
        query_aged = query_ht.is_aged()
        evidence_aged = evidence_ht.is_aged()
        
        if query_aged != evidence_aged:
            return 0.3  # Heavy penalty
        
        # Solution temp matters for superalloys
        if query_ht.solution_temp_c and evidence_ht.solution_temp_c:
            temp_diff = abs(query_ht.solution_temp_c - evidence_ht.solution_temp_c)
            if temp_diff > 100:
                return 0.5
        
        return 0.9
    
    @staticmethod
    def score_notch(query_notch: Optional[bool], evidence_specimen: SpecimenType) -> float:
        """
        Score notch/specimen type match.
        Notched data is more conservative.
        """
        if query_notch is None:
            return 0.5
        
        evidence_notched = evidence_specimen == SpecimenType.NOTCHED
        
        if query_notch == evidence_notched:
            return 1.0
        
        # Notched evidence for smooth query is conservative
        if evidence_notched and not query_notch:
            return 0.7
        
        # Smooth evidence for notched query is non-conservative
        return 0.4
    
    def compute_envelope_score(
        self,
        query: H2Query,
        evidence: EvidenceObject
    ) -> Tuple[float, Dict[str, float], List[str]]:
        """
        Compute overall envelope match score.
        
        Returns: (total_score, dimension_scores, gaps)
        """
        gaps = []
        scores = {}
        
        # Pressure
        query_pressure = query.pressure_mpa
        evidence_pressure = evidence.environment.pressure_mpa if evidence.environment else None
        scores["pressure"] = self.score_pressure(query_pressure, evidence_pressure)
        if query_pressure is None:
            gaps.append("pressure")
        
        # Temperature
        query_temp = query.temperature_c
        evidence_temp = evidence.environment.temperature_c if evidence.environment else None
        scores["temperature"] = self.score_temperature(query_temp, evidence_temp)
        if query_temp is None:
            gaps.append("temperature")
        
        # Phase
        evidence_phase = evidence.environment.phase if evidence.environment else Phase.UNKNOWN
        scores["phase"] = self.score_phase(query.phase, evidence_phase)
        
        # Loading
        evidence_loading = evidence.loading.mode if evidence.loading else LoadingMode.UNKNOWN
        scores["loading"] = self.score_loading(query.loading_mode, evidence_loading)
        
        # Condition
        scores["condition"] = self.score_condition(query.heat_treatment, evidence.heat_treatment)
        if query.condition == HeatTreatCondition.UNKNOWN:
            gaps.append("heat_treatment")
        
        # Notch
        scores["notch"] = self.score_notch(query.has_notch, evidence.specimen_type)
        
        # Strength (if available)
        if query.strength and evidence.loading:
            # Could add strength matching here
            scores["strength"] = 0.8
        else:
            scores["strength"] = 0.5
            if query.strength is None:
                gaps.append("strength")
        
        # Total: weighted average instead of product (product is too harsh)
        weights = {
            "pressure": 0.2,
            "temperature": 0.2,
            "phase": 0.15,
            "loading": 0.15,
            "condition": 0.15,
            "notch": 0.1,
            "strength": 0.05,
        }
        
        total = sum(scores[k] * weights[k] for k in scores.keys())
        
        # Penalty for gaps (but don't kill the score)
        gap_penalty = 0.05 * len(gaps)
        total = max(0.1, total - gap_penalty)
        
        return (total, scores, gaps)


# =============================================================================
# SECTION 11: RULE GATES
# =============================================================================

@dataclass
class RuleGate:
    """
    A rule that can trigger verdict floors, constraints, or warnings.
    """
    rule_id: str
    name: str
    trigger_predicate: str                        # Description of trigger
    effect_type: str                              # "hard_block", "soft_warning", "add_constraint"
    verdict_floor: Optional[Verdict] = None
    confidence_penalty: float = 0.0
    constraint: Optional[Constraint] = None
    driver: Optional[Driver] = None
    source: str = ""  # NASA SWE-013 traceability



class RuleEngine:
    """
    Rule engine for fast conservative gates.
    """
    
    def __init__(self):
        self.gates: List[RuleGate] = self._load_default_gates()
    
    def _load_default_gates(self) -> List[RuleGate]:
        """Load default rule gates."""
        return [
            # Hard block: severe HEE band with matching envelope
            RuleGate(
                rule_id="R001",
                name="Severe HEE Block",
                trigger_predicate="HEE band is SEVERE or EXTREME with envelope match > 0.65",
                effect_type="hard_block",
                verdict_floor=Verdict.NOT_RECOMMENDED,
                driver=Driver(
                    failure_mode="Hydrogen environment embrittlement",
                    severity="severe",
                    trigger_parameter="HEE_band",
                    explanation="Material shows severe susceptibility at test conditions"
                )
            ),
            
            # Soft warning: weld/HAZ
            RuleGate(
                rule_id="R002",
                name="Weld HAZ Warning",
                trigger_predicate="weld_state is HAZ",
                effect_type="soft_warning",
                confidence_penalty=0.15,
                constraint=Constraint(
                    parameter="weld_qualification",
                    limit_type="required",
                    rationale="HAZ often shows worse HEE than base metal - requires specific qualification"
                )
            ),
            
            # Soft warning: aged condition without evidence
            RuleGate(
                rule_id="R003",
                name="Aged Condition Warning",
                trigger_predicate="condition is aged but no aged-specific evidence",
                effect_type="soft_warning",
                confidence_penalty=0.2,
                driver=Driver(
                    failure_mode="Heat treatment sensitivity",
                    severity="high",
                    trigger_parameter="heat_treatment",
                    explanation="Aged conditions typically show much higher HEE susceptibility than annealed/ST"
                )
            ),
            
            # Constraint: high strength
            RuleGate(
                rule_id="R004",
                name="High Strength Constraint",
                trigger_predicate="yield_strength > 1200 MPa or UTS > 1400 MPa",
                effect_type="add_constraint",
                constraint=Constraint(
                    parameter="strength",
                    limit_type="max",
                    limit_value="1200 MPa yield",
                    rationale="High strength increases HEE susceptibility - verify with strength-specific data"
                )
            ),
        ]
    
    def evaluate(
        self,
        query: H2Query,
        evidence_band: Optional[HEEBand],
        envelope_score: float
    ) -> Tuple[Optional[Verdict], float, List[Driver], List[Constraint], List[str]]:
        """
        Evaluate rule gates.
        
        Returns: (verdict_floor, confidence_penalty, drivers, constraints, triggers)
        """
        verdict_floor = None
        total_penalty = 0.0
        drivers = []
        constraints = []
        triggers = []
        
        for gate in self.gates:
            triggered = False
            
            # R001: Severe HEE
            if gate.rule_id == "R001":
                if evidence_band in [HEEBand.SEVERE, HEEBand.EXTREME] and envelope_score >= 0.65:
                    triggered = True
            
            # R002: Weld HAZ
            elif gate.rule_id == "R002":
                if query.weld_state == WeldState.HAZ:
                    triggered = True
            
            # R003: Aged condition
            elif gate.rule_id == "R003":
                if query.condition == HeatTreatCondition.SOLUTION_TREATED_AGED:
                    triggered = True
            
            # R004: High strength
            elif gate.rule_id == "R004":
                if query.strength:
                    if (query.strength.yield_mpa and query.strength.yield_mpa > 1200) or \
                       (query.strength.uts_mpa and query.strength.uts_mpa > 1400):
                        triggered = True
            
            if triggered:
                triggers.append(gate.rule_id)
                total_penalty += gate.confidence_penalty
                
                if gate.verdict_floor:
                    if verdict_floor is None:
                        verdict_floor = gate.verdict_floor
                    elif gate.verdict_floor == Verdict.NOT_RECOMMENDED:
                        verdict_floor = Verdict.NOT_RECOMMENDED
                
                if gate.driver:
                    drivers.append(gate.driver)
                
                if gate.constraint:
                    constraints.append(gate.constraint)
        
        return (verdict_floor, total_penalty, drivers, constraints, triggers)


# =============================================================================
# SECTION 12: DECISION ENGINE
# =============================================================================

class H2DecisionEngine:
    """
    The core decision engine.
    
    Pipeline:
    1. Normalize material + condition → material_key
    2. Normalize environment + loading → env_envelope
    3. Retrieve candidate evidence by material_family + env tags
    4. Compute envelope match score per evidence
    5. Apply rule gates
    6. Aggregate conservatively → verdict
    7. Generate explanation + audit trail
    """
    
    def __init__(self, evidence_store: Optional[List[EvidenceObject]] = None):
        self.evidence_store = evidence_store or []
        self.scorer = EnvelopeMatchScorer()
        self.rules = RuleEngine()
        self.version = "2.0.0"
    
    def query(self, q: H2Query) -> H2Response:
        """
        Execute a compatibility query.
        """
        query_id = str(uuid.uuid4())
        timestamp = datetime.now()
        
        # Initialize response components
        drivers = []
        constraints = []
        all_gaps = []
        warnings = []
        match_stats = []
        
        # Step 1: Environment validity check
        if q.pressure_mpa and q.temperature_c:
            env = HydrogenEnvironment(
                phase=q.phase,
                pressure_mpa=q.pressure_mpa,
                temperature_c=q.temperature_c
            )
            is_valid, env_warnings = env.is_within_nasa_envelope()
            warnings.extend(env_warnings)
        
        # Step 2: Find matching evidence
        candidates = self._find_candidates(q)
        
        if not candidates:
            # No evidence found
            return H2Response(
                verdict=Verdict.UNKNOWN,
                confidence=0.0,
                decision_summary=(
                    f"No evidence found for {q.material_name} in hydrogen environment. "
                    "Cannot make a compatibility determination. "
                    "Recommend conducting baseline HEE testing per ASTM G129."
                ),
                gaps=[Gap(
                    parameter="evidence",
                    impact="No data available for this material/condition combination",
                    default_assumption=None
                )],
                recommended_tests=[RecommendedTest(
                    test_type="notched tensile",
                    description="Baseline HEE characterization",
                    target_conditions=f"in H2 at target pressure/temperature",
                    standard="ASTM G129"
                )],
                warnings=warnings,
                audit=AuditTrail(
                    query_id=query_id,
                    timestamp=timestamp,
                    engine_version=self.version,
                    rule_triggers=[],
                    match_stats=[],
                    dominant_evidence_ids=[],
                    confidence_calculation="No evidence found"
                )
            )
        
        # Step 3: Score each evidence object
        scored_evidence = []
        for ev in candidates:
            score, dim_scores, gaps = self.scorer.compute_envelope_score(q, ev)
            all_gaps.extend(gaps)
            
            # Weight by evidence grade
            grade_weight = {
                EvidenceGrade.PRIMARY_TEST: 1.0,
                EvidenceGrade.SECONDARY_SUMMARY: 0.7,
                EvidenceGrade.GUIDELINE_STATEMENT: 0.4,
            }.get(ev.grade, 0.5)
            
            final_weight = score * grade_weight * ev.extraction_confidence
            
            scored_evidence.append((ev, score, final_weight, dim_scores, gaps))
            match_stats.append(MatchStats(
                evidence_id=ev.evidence_id,
                envelope_match_score=score,
                dimension_scores=dim_scores,
                evidence_weight=final_weight
            ))
        
        # Step 4: Find best matching evidence
        threshold = 0.4  # Minimum match threshold
        credible = [(ev, score, weight, dims, gaps) 
                    for ev, score, weight, dims, gaps in scored_evidence 
                    if score >= threshold]
        
        if not credible:
            # Evidence exists but no good match
            unique_gaps = list(set(all_gaps))
            return H2Response(
                verdict=Verdict.UNKNOWN,
                confidence=0.2,
                decision_summary=(
                    f"Evidence exists for {q.material_name} but envelope match is poor. "
                    f"Test conditions differ significantly from query conditions. "
                    f"Missing or mismatched: {', '.join(unique_gaps) if unique_gaps else 'conditions'}."
                ),
                gaps=[Gap(parameter=g, impact="Weak envelope match") for g in unique_gaps],
                evidence=[ev for ev, _, _, _, _ in scored_evidence[:3]],
                warnings=warnings,
                audit=AuditTrail(
                    query_id=query_id,
                    timestamp=timestamp,
                    engine_version=self.version,
                    rule_triggers=[],
                    match_stats=match_stats,
                    dominant_evidence_ids=[],
                    confidence_calculation="Envelope match below threshold"
                )
            )
        
        # Step 5: Get worst credible evidence (conservative)
        worst_ev = None
        worst_band = HEEBand.NEGLIGIBLE
        best_score = 0.0
        
        for ev, score, weight, _, _ in credible:
            if ev.hee_band:
                # Find worst band among credible evidence
                band_order = [HEEBand.NEGLIGIBLE, HEEBand.SMALL, HEEBand.HIGH, 
                              HEEBand.SEVERE, HEEBand.EXTREME]
                if band_order.index(ev.hee_band) > band_order.index(worst_band):
                    worst_band = ev.hee_band
                    worst_ev = ev
            if score > best_score:
                best_score = score
        
        # Step 6: Apply rule gates
        rule_verdict, conf_penalty, rule_drivers, rule_constraints, triggers = \
            self.rules.evaluate(q, worst_band, best_score)
        
        drivers.extend(rule_drivers)
        constraints.extend(rule_constraints)
        
        # Step 7: Determine verdict
        base_verdict = band_to_verdict_floor(worst_band)
        
        if rule_verdict == Verdict.NOT_RECOMMENDED:
            final_verdict = Verdict.NOT_RECOMMENDED
        elif base_verdict == Verdict.NOT_RECOMMENDED:
            final_verdict = Verdict.NOT_RECOMMENDED
        elif best_score >= 0.8 and not all_gaps and worst_band in [HEEBand.NEGLIGIBLE, HEEBand.SMALL]:
            # Strong match, minimal gaps, good band → could be ALLOWED
            # But per Fran: need primary_test grade
            has_primary = any(ev.grade == EvidenceGrade.PRIMARY_TEST for ev, s, w, _, _ in credible if s >= 0.8)
            if has_primary:
                final_verdict = Verdict.ALLOWED
            else:
                final_verdict = Verdict.ALLOWED_WITH_CONSTRAINTS
        else:
            final_verdict = Verdict.ALLOWED_WITH_CONSTRAINTS
        
        # Step 8: Calculate confidence
        base_confidence = best_score
        
        # Adjust for evidence quality
        primary_count = sum(1 for ev, _, _, _, _ in credible if ev.grade == EvidenceGrade.PRIMARY_TEST)
        if primary_count >= 2:
            base_confidence = min(base_confidence + 0.1, 1.0)
        elif primary_count == 0:
            base_confidence *= 0.7
        
        # Apply rule penalties
        final_confidence = max(0.0, base_confidence - conf_penalty)
        
        # Gap penalty
        unique_gaps = list(set(all_gaps))
        final_confidence -= 0.05 * len(unique_gaps)
        final_confidence = max(0.0, final_confidence)
        
        # Step 9: Generate explanation
        summary_parts = []
        
        if final_verdict == Verdict.ALLOWED:
            summary_parts.append(
                f"{q.material_name} is compatible with the specified hydrogen environment."
            )
        elif final_verdict == Verdict.ALLOWED_WITH_CONSTRAINTS:
            summary_parts.append(
                f"{q.material_name} may be used with constraints in the specified hydrogen environment."
            )
        elif final_verdict == Verdict.NOT_RECOMMENDED:
            summary_parts.append(
                f"{q.material_name} is NOT recommended for the specified hydrogen environment."
            )
        
        if worst_ev and worst_ev.hee_band:
            summary_parts.append(
                f"HEE susceptibility rated '{worst_ev.hee_band.value}' per matched evidence."
            )
        
        if warnings:
            summary_parts.append(f"Note: {warnings[0]}")
        
        decision_summary = " ".join(summary_parts)
        
        # Build gaps list
        gap_objects = []
        for g in unique_gaps:
            gap_objects.append(Gap(
                parameter=g,
                impact=f"Missing {g} weakens envelope match",
                default_assumption="conservative"
            ))
        
        # Build recommended tests
        recommended = []
        if unique_gaps or final_verdict != Verdict.ALLOWED:
            recommended.append(RecommendedTest(
                test_type="notched tensile",
                description="HEE characterization at service conditions",
                target_conditions=f"in H2 at {q.pressure_mpa or 'target'} MPa, {q.temperature_c or 'target'}°C",
                standard="ASTM G129"
            ))
        
        # Add driver for worst evidence
        if worst_ev and worst_ev.hee_band:
            drivers.append(Driver(
                failure_mode="Hydrogen environment embrittlement",
                severity=worst_ev.hee_band.value,
                trigger_parameter="HEE_index",
                explanation=f"Based on {worst_ev.metric.metric_name if worst_ev.metric else 'N/A'} "
                           f"= {worst_ev.metric.value if worst_ev.metric else 'N/A'}",
                evidence_ids=[worst_ev.evidence_id]
            ))
        
        return H2Response(
            verdict=final_verdict,
            confidence=round(final_confidence, 2),
            decision_summary=decision_summary,
            drivers=drivers,
            constraints=constraints,
            gaps=gap_objects,
            recommended_tests=recommended,
            evidence=[ev for ev, _, _, _, _ in credible[:5]],
            warnings=warnings,
            audit=AuditTrail(
                query_id=query_id,
                timestamp=timestamp,
                engine_version=self.version,
                rule_triggers=triggers,
                match_stats=match_stats,
                dominant_evidence_ids=[worst_ev.evidence_id] if worst_ev else [],
                confidence_calculation=f"base={best_score:.2f}, penalty={conf_penalty:.2f}, gaps={len(unique_gaps)}"
            )
        )
    
    def _find_candidates(self, q: H2Query) -> List[EvidenceObject]:
        """Find candidate evidence objects for query."""
        candidates = []
        
        # Normalize query name: lowercase, remove special chars
        query_tokens = set(q.material_name.lower().replace("_", " ").replace("-", " ").split())
        
        for ev in self.evidence_store:
            # Normalize evidence key
            ev_tokens = set(ev.material_key.lower().replace("_", " ").replace("-", " ").split())
            
            # Token overlap matching
            overlap = query_tokens & ev_tokens
            if len(overlap) >= 1:  # At least one meaningful token matches
                # Check it's a meaningful token (not just "steel" alone)
                meaningful = any(len(t) > 3 for t in overlap)
                if meaningful or len(overlap) >= 2:
                    candidates.append(ev)
                    continue
            
            # Direct substring match as fallback
            query_clean = q.material_name.lower().replace(" ", "").replace("-", "").replace("_", "")
            ev_clean = ev.material_key.lower().replace(" ", "").replace("-", "").replace("_", "")
            if query_clean in ev_clean or ev_clean in query_clean:
                candidates.append(ev)
        
        return candidates
    
    def add_evidence(self, evidence: EvidenceObject):
        """Add evidence to the store."""
        self.evidence_store.append(evidence)


# =============================================================================
# SECTION 13: EXAMPLE DATA + DEMO
# =============================================================================

def create_example_evidence() -> List[EvidenceObject]:
    """
    Create example evidence from NASA/TM-2016-218602.
    """
    evidence = []
    
    # 316 SS - Negligible HEE (Table 3)
    evidence.append(EvidenceObject(
        evidence_id="NASA-TM-218602-T3-316",
        material_key="316_stainless_steel",
        material_family=MaterialFamily.AUSTENITIC_SS_316,
        material_condition="annealed",
        heat_treatment=HeatTreatment(condition=HeatTreatCondition.ANNEALED),
        product_form=ProductForm.BAR,
        environment=HydrogenEnvironment(
            phase=Phase.GH2,
            pressure_mpa=68.9,
            temperature_c=24.0
        ),
        loading=LoadingState(mode=LoadingMode.STATIC),
        specimen_type=SpecimenType.NOTCHED,
        metric=MetricValue(
            metric_name="NTS_ratio",
            value=1.00,
            units="ratio"
        ),
        hee_band=HEEBand.NEGLIGIBLE,
        grade=EvidenceGrade.PRIMARY_TEST,
        provenance=Provenance(
            doc_id="NASA-TM-2016-218602",
            doc_title="Hydrogen Embrittlement",
            page=9,
            table_id="Table 3"
        )
    ))
    
    # Inconel 718 HT-A (Severe) - Table 9
    evidence.append(EvidenceObject(
        evidence_id="NASA-TM-218602-T9-718-HTA",
        material_key="inconel_718",
        material_family=MaterialFamily.NICKEL_SUPERALLOY,
        material_condition="STA",
        heat_treatment=HeatTreatment(
            condition=HeatTreatCondition.SOLUTION_TREATED_AGED,
            solution_temp_c=940,
            solution_time_hr=1.0,
            age_temp_c=720,
            age_time_hr=8.0,
            second_age_temp_c=620,
            second_age_time_hr=8.0,
            description="940°C/1hr + 720°C/8hr + 620°C/8hr (HT-A)"
        ),
        product_form=ProductForm.ROLLED_BAR,
        environment=HydrogenEnvironment(
            phase=Phase.GH2,
            pressure_mpa=34.5,
            temperature_c=22.0
        ),
        loading=LoadingState(mode=LoadingMode.STATIC),
        specimen_type=SpecimenType.NOTCHED,
        metric=MetricValue(
            metric_name="NTS_ratio",
            value=0.54,
            units="ratio"
        ),
        hee_band=HEEBand.SEVERE,
        grade=EvidenceGrade.PRIMARY_TEST,
        provenance=Provenance(
            doc_id="NASA-TM-2016-218602",
            doc_title="Hydrogen Embrittlement",
            page=31,
            table_id="Table 9",
            original_authors="Chandler, Walter"
        ),
        notes="Heat treatment A - lower solution temp (940°C vs 1037°C) yields δ phase at grain boundaries"
    ))
    
    # Inconel 718 - Better heat treatment (Small HEE)
    evidence.append(EvidenceObject(
        evidence_id="NASA-TM-218602-T7-718-BETTER",
        material_key="inconel_718",
        material_family=MaterialFamily.NICKEL_SUPERALLOY,
        material_condition="ST-no-age",
        heat_treatment=HeatTreatment(
            condition=HeatTreatCondition.SOLUTION_TREATED,
            solution_temp_c=1025,
            solution_time_hr=0.17,  # 10 min
            description="1025°C/10min, no aging (HT-D)"
        ),
        product_form=ProductForm.ROLLED_BAR,
        environment=HydrogenEnvironment(
            phase=Phase.GH2,
            pressure_mpa=34.5,
            temperature_c=22.0
        ),
        loading=LoadingState(mode=LoadingMode.STATIC),
        specimen_type=SpecimenType.NOTCHED,
        metric=MetricValue(
            metric_name="NTS_ratio",
            value=0.83,
            units="ratio"
        ),
        hee_band=HEEBand.HIGH,
        grade=EvidenceGrade.PRIMARY_TEST,
        provenance=Provenance(
            doc_id="NASA-TM-2016-218602",
            doc_title="Hydrogen Embrittlement",
            page=31,
            table_id="Table 9"
        ),
        notes="Solution treated WITHOUT aging - significantly better than aged condition"
    ))
    
    # 7075-T73 Aluminum - Negligible (Table 2)
    evidence.append(EvidenceObject(
        evidence_id="NASA-TM-218602-T2-7075",
        material_key="7075_aluminum",
        material_family=MaterialFamily.ALUMINUM,
        material_condition="T73",
        environment=HydrogenEnvironment(
            phase=Phase.GH2,
            pressure_mpa=68.9,
            temperature_c=24.0
        ),
        loading=LoadingState(mode=LoadingMode.STATIC),
        specimen_type=SpecimenType.NOTCHED,
        metric=MetricValue(
            metric_name="NTS_ratio",
            value=0.98,
            units="ratio"
        ),
        hee_band=HEEBand.NEGLIGIBLE,
        grade=EvidenceGrade.PRIMARY_TEST,
        provenance=Provenance(
            doc_id="NASA-TM-2016-218602",
            doc_title="Hydrogen Embrittlement",
            page=8,
            table_id="Table 2"
        ),
        notes="Aluminum alloys generally show negligible HEE"
    ))
    
    return evidence


def demo():
    """Demonstrate the H2 Knowledge Twin."""
    print("=" * 70)
    print("H2 KNOWLEDGE TWIN v2.0 - DEMONSTRATION")
    print("=" * 70)
    
    # Initialize engine with example evidence
    evidence = create_example_evidence()
    engine = H2DecisionEngine(evidence_store=evidence)
    
    print(f"\nLoaded {len(evidence)} evidence objects")
    
    # Query 1: 316 SS - should be good
    print("\n" + "-" * 70)
    print("QUERY 1: 316 Stainless Steel at 70 MPa, room temp")
    print("-" * 70)
    
    q1 = H2Query(
        material_name="316 stainless steel",
        condition=HeatTreatCondition.ANNEALED,
        phase=Phase.GH2,
        pressure_mpa=70.0,
        temperature_c=25.0,
        loading_mode=LoadingMode.STATIC
    )
    
    r1 = engine.query(q1)
    print(f"Verdict: {r1.verdict.value}")
    print(f"Confidence: {r1.confidence}")
    print(f"Summary: {r1.decision_summary}")
    if r1.warnings:
        print(f"Warnings: {r1.warnings}")
    
    # Query 2: Inconel 718 aged - should be NOT RECOMMENDED
    print("\n" + "-" * 70)
    print("QUERY 2: Inconel 718 (aged) at 35 MPa, room temp")
    print("-" * 70)
    
    q2 = H2Query(
        material_name="Inconel 718",
        condition=HeatTreatCondition.SOLUTION_TREATED_AGED,
        heat_treatment=HeatTreatment(
            condition=HeatTreatCondition.SOLUTION_TREATED_AGED,
            solution_temp_c=940
        ),
        phase=Phase.GH2,
        pressure_mpa=35.0,
        temperature_c=22.0,
        loading_mode=LoadingMode.STATIC
    )
    
    r2 = engine.query(q2)
    print(f"Verdict: {r2.verdict.value}")
    print(f"Confidence: {r2.confidence}")
    print(f"Summary: {r2.decision_summary}")
    if r2.drivers:
        print(f"Drivers: {[d.failure_mode + ' (' + d.severity + ')' for d in r2.drivers]}")
    
    # Query 3: Unknown material
    print("\n" + "-" * 70)
    print("QUERY 3: Unknown exotic alloy")
    print("-" * 70)
    
    q3 = H2Query(
        material_name="Unobtanium XYZ",
        phase=Phase.GH2,
        pressure_mpa=50.0,
        temperature_c=25.0
    )
    
    r3 = engine.query(q3)
    print(f"Verdict: {r3.verdict.value}")
    print(f"Confidence: {r3.confidence}")
    print(f"Summary: {r3.decision_summary}")
    if r3.recommended_tests:
        print(f"Recommended: {[t.test_type for t in r3.recommended_tests]}")
    
    # Query 4: Cryogenic LH2
    print("\n" + "-" * 70)
    print("QUERY 4: 316 SS in LH2 (cryogenic)")
    print("-" * 70)
    
    q4 = H2Query(
        material_name="316 stainless steel",
        condition=HeatTreatCondition.ANNEALED,
        phase=Phase.LH2,
        pressure_mpa=0.5,
        temperature_c=-253.0,  # LH2 boiling point
        loading_mode=LoadingMode.STATIC
    )
    
    r4 = engine.query(q4)
    print(f"Verdict: {r4.verdict.value}")
    print(f"Confidence: {r4.confidence}")
    print(f"Summary: {r4.decision_summary}")
    if r4.warnings:
        print(f"Warnings: {r4.warnings[0][:100]}...")
    
    print("\n" + "=" * 70)
    print("DEMONSTRATION COMPLETE")
    print("=" * 70)


if __name__ == "__main__":
    demo()
