#!/usr/bin/env python3
"""
Module: Types
Purpose: Knowledge Twins - Shared Types

BoundState AI 2025
Version: 1.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Fran OpenAI 5 <noreply@openai.com>
Co-Authored-By: Grok 4.0 <noreply@x.ai>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: SWE-013, NASA-STD-8739.8B
Safety Critical: False
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple


# =============================================================================
# ENUMERATIONS
# =============================================================================

class Verdict(Enum):
    """Decision output per Fran's spec."""
    ALLOWED = "allowed"
    ALLOWED_WITH_CONSTRAINTS = "allowed_with_constraints"
    NOT_RECOMMENDED = "not_recommended"
    UNKNOWN = "unknown"


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
    """
    HEE = "HEE"  # Hydrogen Environment Embrittlement - external gaseous H2
    IHE = "IHE"  # Internal Hydrogen Embrittlement - absorbed/dissolved H2
    HRE = "HRE"  # Hydrogen Reaction Embrittlement - chemical reaction (hydrides)


class EvidenceGrade(Enum):
    """
    Evidence quality hierarchy.
    PRIMARY_TEST > SECONDARY_SUMMARY > GUIDELINE_STATEMENT
    """
    PRIMARY_TEST = "primary_test"
    SECONDARY_SUMMARY = "secondary_summary"
    GUIDELINE_STATEMENT = "guideline_statement"


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
    """Test specimen geometry."""
    SMOOTH = "smooth"           # For RA and EL
    NOTCHED = "notched"         # For NTS
    PRECRACKED = "precracked"   # For KTH/KIC


class ProductForm(Enum):
    """Product form affects HEE susceptibility significantly."""
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
    HAZ = "HAZ"
    UNKNOWN = "unknown"


class MaterialFamily(Enum):
    """Material family classification aligned with Sandia codes."""
    # Ferritic Steels
    CARBON_STEEL = "carbon_steel"
    LOW_ALLOY_CR_MO = "low_alloy_cr_mo"
    LOW_ALLOY_NI_CR_MO = "low_alloy_ni_cr_mo"
    HIGH_STRENGTH_9NI_4CO = "high_strength_9ni_4co"
    FERRITIC_SS = "ferritic_ss"
    DUPLEX_SS = "duplex_ss"
    SEMI_AUSTENITIC_SS = "semi_austenitic_ss"
    MARTENSITIC_SS_PH = "martensitic_ss_ph"
    MARTENSITIC_SS_HT = "martensitic_ss_ht"

    # Austenitic Steels
    AUSTENITIC_SS_304 = "austenitic_ss_304"
    AUSTENITIC_SS_316 = "austenitic_ss_316"
    AUSTENITIC_SS_321_347 = "austenitic_ss_321_347"
    NITROGEN_SS = "nitrogen_ss"
    PH_SS_A286 = "ph_ss_a286"

    # Superalloys
    NICKEL_SUPERALLOY = "nickel_superalloy"
    IRON_SUPERALLOY = "iron_superalloy"
    COBALT_SUPERALLOY = "cobalt_superalloy"

    # Other
    ALUMINUM = "aluminum"
    COPPER = "copper"
    TITANIUM = "titanium"
    NICKEL_ALLOY = "nickel_alloy"

    UNKNOWN = "unknown"


class HeatTreatCondition(Enum):
    """Heat treatment condition category."""
    ANNEALED = "annealed"
    SOLUTION_TREATED = "solution_treated"
    SOLUTION_TREATED_AGED = "solution_treated_aged"
    NORMALIZED = "normalized"
    QUENCHED_TEMPERED = "quenched_tempered"
    AS_RECEIVED = "as_received"
    UNKNOWN = "unknown"


class ReferenceEnvironment(Enum):
    """Reference environment for ratio calculations."""
    HELIUM = "helium"
    AIR = "air"
    NITROGEN = "nitrogen"
    ARGON = "argon"


class TemperatureBehavior(Enum):
    """Temperature dependence pattern for HEE."""
    PEAK_NEAR_AMBIENT = "peak_near_ambient"
    PEAK_AT_ELEVATED = "peak_at_elevated"
    NEGLIGIBLE_AT_CRYO = "negligible_at_cryo"


# =============================================================================
# CONSTANTS (NASA/Sandia Traceable)
# =============================================================================

HEE_BAND_THRESHOLDS: Dict[HEEBand, Tuple[float, float]] = {
    HEEBand.NEGLIGIBLE: (0.97, 1.00),
    HEEBand.SMALL:      (0.90, 0.96),
    HEEBand.HIGH:       (0.70, 0.89),
    HEEBand.SEVERE:     (0.50, 0.69),
    HEEBand.EXTREME:    (0.00, 0.49),
}

VALIDITY_ENVELOPE = {
    "temperature_c": {"min": 20.0, "max": 26.0, "nominal": 22.0},
    "pressure_mpa": {"min": 34.0, "max": 69.0},
}

NI_PREDICTOR = {
    "threshold_wt_pct": 12.5,
    "max_for_predictor": 35.0,
    "valid_conditions": ["annealed", "solution_treated"],
}

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

ELEVATED_TEMP_PEAK_MATERIALS = [
    "EP99", "EP741", "Astroloy", "MERL 76", "IN100",
    "Waspaloy", "Udimet 700"
]


# =============================================================================
# DATACLASSES - Composition & Heat Treatment
# =============================================================================

@dataclass
class Composition:
    """Chemical composition - critical for predictive rules."""
    ni_wt_pct: Optional[float] = None
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

    def nickel_equivalent(self) -> Optional[float]:
        """Calculate Ni equivalent: Nieq = Ni + 30*C + 0.5*Mn + 30*N"""
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
    """Full heat treatment specification."""
    condition: HeatTreatCondition
    solution_temp_c: Optional[float] = None
    solution_time_hr: Optional[float] = None
    quench_medium: Optional[str] = None
    age_temp_c: Optional[float] = None
    age_time_hr: Optional[float] = None
    second_age_temp_c: Optional[float] = None
    second_age_time_hr: Optional[float] = None
    description: Optional[str] = None

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


@dataclass
class LoadingRates:
    """Loading rates for mechanical testing - THREE DIFFERENT parameters."""
    strain_rate_per_s: Optional[float] = None       # For SMOOTH specimens
    stroke_rate_mm_s: Optional[float] = None        # For NOTCHED specimens
    displacement_rate_um_hr: Optional[float] = None # For PRECRACKED specimens


# =============================================================================
# DATACLASSES - Material & Environment
# =============================================================================

@dataclass
class MaterialRecord:
    """Material entity - the 'what' being evaluated."""
    material_key: str
    name: str
    spec: Optional[str] = None
    uns: Optional[str] = None
    family: MaterialFamily = MaterialFamily.UNKNOWN
    aliases: List[str] = field(default_factory=list)
    composition: Optional[Composition] = None
    heat_treatment: Optional[HeatTreatment] = None
    strength: Optional[StrengthData] = None
    product_form: ProductForm = ProductForm.UNKNOWN
    weld_state: WeldState = WeldState.BASE_METAL
    grain_direction: Optional[str] = None

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


@dataclass
class HydrogenEnvironment:
    """Hydrogen environment specification."""
    phase: Phase
    pressure_mpa: float
    temperature_c: float
    purity_pct: float = 99.98
    exposure_type: str = "continuous"

    def is_cryogenic(self) -> bool:
        """Check if environment is cryogenic (LH2 territory)."""
        return self.temperature_c < -150 or self.phase == Phase.LH2

    def is_within_nasa_envelope(self) -> Tuple[bool, List[str]]:
        """Check if environment is within NASA test data validity envelope."""
        warnings = []

        temp_env = VALIDITY_ENVELOPE["temperature_c"]
        if not (temp_env["min"] <= self.temperature_c <= temp_env["max"]):
            warnings.append(
                f"Temperature {self.temperature_c}C outside NASA envelope "
                f"({temp_env['min']}-{temp_env['max']}C)."
            )

        press_env = VALIDITY_ENVELOPE["pressure_mpa"]
        if not (press_env["min"] <= self.pressure_mpa <= press_env["max"]):
            warnings.append(
                f"Pressure {self.pressure_mpa} MPa outside NASA envelope "
                f"({press_env['min']}-{press_env['max']} MPa)."
            )

        if self.phase == Phase.LH2:
            warnings.append(
                "LH2 (cryogenic) service. Most NASA HEE data is for room temperature."
            )

        return (len(warnings) == 0, warnings)


@dataclass
class LoadingState:
    """Loading conditions for service."""
    mode: LoadingMode = LoadingMode.UNKNOWN
    sigma_max_mpa: Optional[float] = None
    fraction_of_yield: Optional[float] = None
    has_notch: Optional[bool] = None
    stress_concentration_kt: Optional[float] = None
    loading_rates: Optional[LoadingRates] = None
    load_ratio_r: Optional[float] = None
    frequency_hz: Optional[float] = None


# =============================================================================
# DATACLASSES - Evidence & Provenance
# =============================================================================

@dataclass
class Provenance:
    """Full provenance tracking for traceability."""
    doc_id: str
    doc_title: str
    page: Optional[int] = None
    table_id: Optional[str] = None
    figure_id: Optional[str] = None
    section: Optional[str] = None
    snippet_text: Optional[str] = None
    bbox: Optional[Tuple[int, int, int, int]] = None
    reference_key: Optional[str] = None
    original_authors: Optional[str] = None
    original_report: Optional[str] = None
    extraction_timestamp: datetime = field(default_factory=datetime.now)


@dataclass
class MetricValue:
    """A measured value with units and interpretation."""
    metric_name: str
    value: float
    units: str
    directionality: str = "higher_is_better"

    def to_hee_band(self) -> Optional[HEEBand]:
        """Convert ratio metric to HEE band if applicable."""
        if "ratio" not in self.metric_name.lower():
            return None
        return classify_hee_band(self.value)


@dataclass
class EvidenceObject:
    """THE UNIT OF TRUTH - represents a single test result from source literature."""
    evidence_id: str
    material_key: str
    material_family: MaterialFamily
    material_condition: Optional[str] = None
    heat_treatment: Optional[HeatTreatment] = None
    product_form: ProductForm = ProductForm.UNKNOWN
    weld_state: WeldState = WeldState.BASE_METAL
    grain_direction: Optional[str] = None
    environment: Optional[HydrogenEnvironment] = None
    reference_environment: ReferenceEnvironment = ReferenceEnvironment.HELIUM
    loading: Optional[LoadingState] = None
    test_method: str = ""
    specimen_type: SpecimenType = SpecimenType.NOTCHED
    he_mechanism: HEMechanism = HEMechanism.HEE
    metric: Optional[MetricValue] = None
    hee_band: Optional[HEEBand] = None
    grade: EvidenceGrade = EvidenceGrade.PRIMARY_TEST
    extraction_confidence: float = 1.0
    provenance: Optional[Provenance] = None
    notes: Optional[str] = None

    def __post_init__(self):
        """Auto-classify HEE band from metric if not provided."""
        if self.hee_band is None and self.metric:
            self.hee_band = self.metric.to_hee_band()


# =============================================================================
# DATACLASSES - Query & Response
# =============================================================================

@dataclass
class Driver:
    """A failure mode driver with evidence."""
    failure_mode: str
    severity: str
    trigger_parameter: str
    explanation: str
    evidence_ids: List[str] = field(default_factory=list)


@dataclass
class Constraint:
    """An explicit constraint on usage."""
    parameter: str
    limit_type: str
    limit_value: Optional[str] = None
    rationale: str = ""
    evidence_id: Optional[str] = None


@dataclass
class Gap:
    """Missing input that would strengthen the verdict."""
    parameter: str
    impact: str
    default_assumption: Optional[str] = None


@dataclass
class RecommendedTest:
    """Test that would resolve a gap."""
    test_type: str
    description: str
    target_conditions: str
    standard: Optional[str] = None


@dataclass
class MatchStats:
    """Envelope match statistics for audit."""
    evidence_id: str
    envelope_match_score: float
    dimension_scores: Dict[str, float]
    evidence_weight: float


@dataclass
class AuditTrail:
    """Full audit trail for reproducibility."""
    query_id: str
    timestamp: datetime
    engine_version: str
    rule_triggers: List[str]
    match_stats: List[MatchStats]
    dominant_evidence_ids: List[str]
    confidence_calculation: str


# =============================================================================
# CLASSIFICATION FUNCTIONS
# =============================================================================

def classify_hee_band(index: float) -> HEEBand:
    """Classify HEE index to band per NASA/TM-2016-218602 Table 1."""
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
    """Map HEE band to minimum verdict (floor). Conservative: severe/extreme -> not_recommended."""
    if band == HEEBand.NEGLIGIBLE:
        return Verdict.ALLOWED_WITH_CONSTRAINTS
    elif band == HEEBand.SMALL:
        return Verdict.ALLOWED_WITH_CONSTRAINTS
    elif band == HEEBand.HIGH:
        return Verdict.ALLOWED_WITH_CONSTRAINTS
    elif band == HEEBand.SEVERE:
        return Verdict.NOT_RECOMMENDED
    else:  # EXTREME
        return Verdict.NOT_RECOMMENDED


def get_temperature_behavior(family: MaterialFamily, material_name: str) -> TemperatureBehavior:
    """Determine temperature behavior pattern for a material."""
    if any(name.lower() in material_name.lower() for name in ELEVATED_TEMP_PEAK_MATERIALS):
        return TemperatureBehavior.PEAK_AT_ELEVATED
    return TemperatureBehavior.PEAK_NEAR_AMBIENT
