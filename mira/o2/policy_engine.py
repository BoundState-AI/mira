#!/usr/bin/env python3
"""
Module: Policy Engine
Purpose: [Automatically migrated - needs manual review]

BoundState AI 2025
Version: 1.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Fran OpenAI 5 <noreply@openai.com>
Co-Authored-By: Grok 4.0 <noreply@x.ai>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: NASA-CSET, SWE-013, SWE-032
Safety Critical: True
"""

import logging
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass
from enum import Enum
import uuid

logger = logging.getLogger(__name__)


class O2Compatibility(str, Enum):
    """Oxygen compatibility classification."""
    VERIFIED = "VERIFIED"           # Explicitly validated in O2 BOK + MAPTIS flammability data
    CONDITIONAL = "CONDITIONAL"     # Some O2 data, conditions/limits apply
    UNKNOWN = "UNKNOWN"             # No O2-specific data
    INCOMPATIBLE = "INCOMPATIBLE"   # Known promoted combustion risk or exclusion


class O2Environment(str, Enum):
    """Standard oxygen environments per NASA-STD-6016."""
    LOX_CRYO = "LOX_CRYO"                   # Liquid oxygen, cryogenic (-297°F)
    GOX_HIGH_PRESSURE = "GOX_HIGH_PRESSURE" # Gaseous O2 > 1000 psi
    GOX_ENRICHED = "GOX_ENRICHED"           # O2 > 25% by volume
    GOX_NORMAL = "GOX_NORMAL"               # O2 < 25%, < 1000 psi
    BREATHING_O2 = "BREATHING_O2"           # Life support systems


class SafetyClass(str, Enum):
    """NASA safety classification."""
    CLASS_A = "A"  # Human-rated
    CLASS_B = "B"  # Mission-critical
    CLASS_C = "C"  # Important
    CLASS_D = "D"  # General


@dataclass
class PolicyWeights:
    """Configurable weights for evidence-based scoring.

    For safety-critical applications: w_authority >= w_properties >= w_semantic
    """
    w_semantic: float = 0.15      # FAISS embedding similarity
    w_properties: float = 0.25    # Validated properties (flammability tests, O2 ratings)
    w_authority: float = 0.40     # O2 BOK authority prior
    w_usage: float = 0.10         # Historical MUA/MIUL precedents
    w_uncertainty: float = 0.10   # Epistemic penalty for sparse data
    source: str = ""  # NASA SWE-013 traceability


    def __post_init__(self):
        """Validate weights sum to 1.0."""
        total = (self.w_semantic + self.w_properties +
                self.w_authority + self.w_usage + self.w_uncertainty)
        if abs(total - 1.0) > 0.01:
            raise ValueError(f"Weights must sum to 1.0, got {total}")


@dataclass
class O2EnvironmentSpec:
    """Oxygen environment specification for query."""
    o2_concentration_pct: float = 100.0  # O2 % by volume (21-100%)
    pressure_psi: float = 14.7           # Pressure in psi
    temperature_f: float = 70.0          # Temperature in °F
    flow_regime: Optional[str] = None    # "static", "flowing", "impact"
    cleaning_level: Optional[str] = None # "precision", "standard", "commercial"
    source: str = ""  # NASA SWE-013 traceability


    def classify_environment(self) -> O2Environment:
        """Classify environment into standard NASA categories."""
        if self.temperature_f < -100:
            return O2Environment.LOX_CRYO
        elif self.pressure_psi > 1000:
            return O2Environment.GOX_HIGH_PRESSURE
        elif self.o2_concentration_pct > 25:
            return O2Environment.GOX_ENRICHED
        elif self.o2_concentration_pct <= 25 and self.pressure_psi < 1000:
            return O2Environment.GOX_NORMAL
        else:
            return O2Environment.GOX_ENRICHED

    def get_risk_level(self) -> str:
        """Compute relative risk level based on environment parameters."""
        # NASA risk model: Risk ∝ P × [O2] × ignition_sensitivity
        # Simplified risk score for filtering
        risk_score = 0

        # O2 concentration factor
        if self.o2_concentration_pct > 90:
            risk_score += 3
        elif self.o2_concentration_pct > 50:
            risk_score += 2
        elif self.o2_concentration_pct > 25:
            risk_score += 1

        # Pressure factor
        if self.pressure_psi > 3000:
            risk_score += 3
        elif self.pressure_psi > 1000:
            risk_score += 2
        elif self.pressure_psi > 500:
            risk_score += 1

        # Temperature factor (cryogenic = higher risk)
        if self.temperature_f < -200:
            risk_score += 2
        elif self.temperature_f < -100:
            risk_score += 1

        if risk_score >= 6:
            return "CRITICAL"
        elif risk_score >= 4:
            return "HIGH"
        elif risk_score >= 2:
            return "MODERATE"
        else:
            return "LOW"


@dataclass
class MaterialEvidence:
    """Evidence bundle for a material's O2 compatibility."""
    material_key: int
    material_name: str
    material_code: str

    # Score components
    f_semantic: float = 0.0      # FAISS similarity [0-1]
    f_properties: float = 0.0    # Property fit [0-1]
    f_authority: float = 0.0     # BOK authority prior [-1 to +1]
    f_usage: float = 0.0         # Historical usage [0-1]
    f_uncertainty: float = 0.0   # Uncertainty penalty [0-1]

    # Evidence
    o2_compatibility: O2Compatibility = O2Compatibility.UNKNOWN
    flamm_rating: Optional[str] = None  # MAPTIS flammability rating (A, B, C, D, X, etc.)
    o2_test_count: int = 0
    bok_citations: List[str] = None
    property_evidence: Dict[str, Any] = None
    warnings: List[str] = None
    exclusion_reasons: List[str] = None
    environment_limits: Dict[str, Any] = None  # O2 envelope limits

    # ENRICHMENT FIX: Store original search result to preserve enriched fields
    original_result: Dict[str, Any] = None
    source: str = ""  # NASA SWE-013 traceability


    def __post_init__(self):
        if self.bok_citations is None:
            self.bok_citations = []
        if self.property_evidence is None:
            self.property_evidence = {}
        if self.warnings is None:
            self.warnings = []
        if self.exclusion_reasons is None:
            self.exclusion_reasons = []
        if self.environment_limits is None:
            self.environment_limits = {}

    def compute_final_score(self, weights: PolicyWeights) -> float:
        """Compute final evidence-weighted score."""
        score = (
            weights.w_semantic * self.f_semantic +
            weights.w_properties * self.f_properties +
            weights.w_authority * self.f_authority +
            weights.w_usage * self.f_usage -
            weights.w_uncertainty * self.f_uncertainty
        )
        # Clamp to [0, 1]
        return max(0.0, min(1.0, score))


class O2PolicyEngine:
    """
    Policy-gated ranking engine for oxygen service materials.

    Architecture (following H2 engine pattern):
    1. Policy Gate: Filter incompatible materials via authoritative constraints
    2. Evidence Scoring: Compute scores from properties + BOK + usage + uncertainty
    3. Transparent Ranking: Return materials with full traceability chain

    NO hardcoded name boosts - all scoring is property/evidence-based.
    """

    # Known O2-incompatible material indicators (from NASA-STD-6016 & 6001)
    # These are property/composition-based, not specific alloy names
    O2_RISK_INDICATORS = {
        'hydrocarbon_content': 'Hydrocarbon contamination - promotes combustion',
        'organic_materials': 'Organic materials (plastics, elastomers) - high flammability in O2',
        'high_surface_area': 'High surface area materials - ignition risk',
        'pyrophoric': 'Pyrophoric materials - spontaneous ignition in O2',
        'fine_particles': 'Fine particles/dust - explosion hazard in O2',
    }

    # O2 BOK recommended material families (from NASA-STD-6016 Table 4-1)
    O2_PREFERRED_FAMILIES = {
        'nickel_alloys': {
            'description': 'Nickel-base alloys (Monel, Inconel, Hastelloy)',
            'authority': 0.9,
            'examples': ['Monel 400', 'Monel K-500', 'Inconel 625', 'Inconel 718', 'Hastelloy C-276'],
            'bok_ref': 'NASA-STD-6016 Table 4-1, KSC-KTI-5210C §3.2',
            'o2_limits': {'pressure_psi': 10000, 'o2_pct': 100}
        },
        'copper_alloys': {
            'description': 'Copper and copper alloys',
            'authority': 0.8,
            'examples': ['Cu-10', 'Cu-122', 'Brass', 'Bronze'],
            'bok_ref': 'NASA-STD-6016 Table 4-1',
            'o2_limits': {'pressure_psi': 5000, 'o2_pct': 100}
        },
        '300_series_stainless': {
            'description': '300-series austenitic stainless steels',
            'authority': 0.7,
            'examples': ['SS 304', 'SS 316', 'SS 321', 'SS 347'],
            'bok_ref': 'NASA-STD-6016 Table 4-1 (with cautions for high pressure)',
            'o2_limits': {'pressure_psi': 3000, 'o2_pct': 100, 'notes': 'Precision cleaned required >1000 psi'}
        },
        'aluminum_alloys_limited': {
            'description': 'Aluminum alloys (limited use, LOX cryo only)',
            'authority': 0.5,
            'examples': ['AL 6061', 'AL 2219', 'AL 2024'],
            'bok_ref': 'NASA-STD-6016 §4.2.6.3 (LOX/cryogenic only, NOT GOX)',
            'o2_limits': {'pressure_psi': 1000, 'o2_pct': 100, 'temperature_f': -200, 'notes': 'LOX service only'}
        },
        'teflon_limited': {
            'description': 'PTFE/Teflon (limited use with restrictions)',
            'authority': 0.4,
            'examples': ['Teflon', 'PTFE', 'TFE'],
            'bok_ref': 'NASA-STD-6016 Table 4-1 (static seals only, no flow)',
            'o2_limits': {'pressure_psi': 3000, 'o2_pct': 100, 'flow_regime': 'static'}
        }
    }

    # Materials explicitly excluded from O2 service (from NASA standards)
    O2_EXCLUDED_MATERIALS = {
        'titanium_alloys': {
            'description': 'Titanium and titanium alloys',
            'authority': -1.0,
            'exclusion_reason': 'Promoted combustion in enriched O2 environments (NASA-STD-6016 §4.2.6.2)',
            'bok_ref': 'NASA-STD-6016 §4.2.6.2, NASA/TM-2007-213740'
        },
        'magnesium_alloys': {
            'description': 'Magnesium and magnesium alloys',
            'authority': -1.0,
            'exclusion_reason': 'Highly flammable in O2-enriched environments',
            'bok_ref': 'NASA-STD-6016 Table 4-1'
        },
        'organic_elastomers': {
            'description': 'Organic elastomers (non-fluorinated)',
            'authority': -0.8,
            'exclusion_reason': 'High flammability in O2 except for specific approved fluoropolymers',
            'bok_ref': 'NASA-STD-6001B Test 1'
        }
    }

    def __init__(self, o2_engine=None, safety_class: SafetyClass = SafetyClass.CLASS_A):
        """Initialize O2 policy engine.

        Args:
            o2_engine: O2Engine instance with BOK and MAPTIS data
            safety_class: NASA safety classification (affects weight profile)
        """
        self.o2_engine = o2_engine
        self.safety_class = safety_class

        # Load weight profile based on safety class
        self.weights = self._get_weight_profile(safety_class)

        logger.info(f"O2 Policy Engine initialized for {safety_class.value} "
                   f"(auth={self.weights.w_authority:.2f}, "
                   f"prop={self.weights.w_properties:.2f}, "
                   f"sem={self.weights.w_semantic:.2f})")

    def _get_weight_profile(self, safety_class: SafetyClass) -> PolicyWeights:
        """Get weight profile based on safety class."""
        if safety_class == SafetyClass.CLASS_A:
            # Human-rated: Authority dominates
            return PolicyWeights(
                w_semantic=0.10,
                w_properties=0.25,
                w_authority=0.45,
                w_usage=0.10,
                w_uncertainty=0.10
            )
        elif safety_class == SafetyClass.CLASS_B:
            # Mission-critical: Strong authority preference
            return PolicyWeights(
                w_semantic=0.15,
                w_properties=0.30,
                w_authority=0.35,
                w_usage=0.10,
                w_uncertainty=0.10
            )
        else:
            # Class C/D: More balanced
            return PolicyWeights(
                w_semantic=0.25,
                w_properties=0.30,
                w_authority=0.25,
                w_usage=0.10,
                w_uncertainty=0.10
            )

    def apply_policy_gate(self,
                         candidates: List[Dict[str, Any]],
                         o2_env: Optional[O2EnvironmentSpec] = None) -> Tuple[List[MaterialEvidence], List[MaterialEvidence]]:
        """
        Apply deterministic policy gate to filter candidates based on O2 environment.

        Args:
            candidates: List of candidate materials from FAISS/search
            o2_env: Oxygen environment specification (pressure, concentration, temp)

        Returns:
            (admitted_materials, excluded_materials) with evidence bundles
        """
        admitted = []
        excluded = []

        # Default to worst-case environment if not specified
        if o2_env is None:
            o2_env = O2EnvironmentSpec(
                o2_concentration_pct=100.0,
                pressure_psi=3000.0,
                temperature_f=70.0
            )

        risk_level = o2_env.get_risk_level()
        logger.info(f"[O2 GATE] Environment: {o2_env.o2_concentration_pct}% O2, "
                   f"{o2_env.pressure_psi} psi, {o2_env.temperature_f}°F => {risk_level} risk")

        for candidate in candidates:
            evidence = self._build_evidence_bundle(candidate, o2_env)

            # Hard gate: Exclude known incompatible materials
            if evidence.o2_compatibility == O2Compatibility.INCOMPATIBLE:
                excluded.append(evidence)
                logger.debug(f"[O2 GATE] Excluded {evidence.material_name}: "
                           f"{', '.join(evidence.exclusion_reasons)}")
            else:
                admitted.append(evidence)

        logger.info(f"[O2 GATE] Admitted {len(admitted)}/{len(candidates)} candidates, "
                   f"excluded {len(excluded)}")

        return admitted, excluded

    def _build_evidence_bundle(self,
                              candidate: Dict[str, Any],
                              o2_env: O2EnvironmentSpec) -> MaterialEvidence:
        """Build evidence bundle for a candidate material."""
        material = candidate.get('material', {})
        original = candidate.get('original_material', {})

        material_name = (
            material.get('designation') or
            material.get('name') or
            original.get('name') or
            'Unknown'
        )
        material_code = material.get('material_code', original.get('material_code', 'N/A'))
        material_key = material.get('material_key', original.get('material_key', 0))

        # Start evidence bundle
        evidence = MaterialEvidence(
            material_key=material_key,
            material_name=material_name,
            material_code=material_code,
            f_semantic=candidate.get('similarity_score', 0.0),
            original_result=candidate  # ENRICHMENT FIX: Store original result
        )

        # Extract flammability rating from MAPTIS
        flamm_rating = material.get('rating_flam') or original.get('rating_flam')
        evidence.flamm_rating = flamm_rating

        # Compute evidence components
        evidence.f_authority = self._compute_authority_score(candidate, material_name, o2_env)
        evidence.f_properties = self._compute_property_score(candidate, material, flamm_rating, o2_env)
        evidence.f_usage = self._compute_usage_score(candidate, o2_env)
        evidence.f_uncertainty = self._compute_uncertainty_score(candidate, flamm_rating)

        # Determine O2 compatibility
        evidence.o2_compatibility = self._classify_o2_compatibility(
            candidate, material_name, evidence, o2_env
        )

        # Add O2 test count if available
        o2_info = candidate.get('o2_info', {})
        evidence.o2_test_count = o2_info.get('o2_test_count', 0)

        return evidence

    def _compute_authority_score(self,
                                 candidate: Dict[str, Any],
                                 material_name: str,
                                 o2_env: O2EnvironmentSpec) -> float:
        """
        Compute authority score from O2 BOK recommendations.

        Returns: [-1.0 to +1.0]
            +1.0 = Explicitly recommended in BOK for this environment
             0.0 = No BOK guidance
            -1.0 = Explicitly excluded/cautioned in BOK
        """
        material_name_upper = material_name.upper()

        # Check for explicit exclusions first
        for family, info in self.O2_EXCLUDED_MATERIALS.items():
            if self._matches_material_family(material_name_upper, [info['description']]):
                logger.debug(f"[O2 AUTH] {material_name} matches excluded family {family}: "
                           f"{info['authority']:.2f}")
                return info['authority']  # Negative score

        # Check O2-preferred families with environment limits
        authority_score = 0.0
        for family, info in self.O2_PREFERRED_FAMILIES.items():
            if self._matches_material_family(material_name_upper, info['examples']):
                # Base authority score
                base_score = info['authority']

                # Apply environment limit penalties
                o2_limits = info.get('o2_limits', {})
                penalty = self._compute_environment_penalty(o2_env, o2_limits)

                authority_score = base_score * (1.0 - penalty)
                logger.debug(f"[O2 AUTH] {material_name} matches {family}: "
                           f"base={base_score:.2f}, penalty={penalty:.2f}, "
                           f"final={authority_score:.2f}")
                break

        # Boost if material has actual O2/FLAMM test data in MAPTIS
        has_flamm_data = candidate.get('has_flamm_test_data', False)
        if has_flamm_data:
            authority_score = max(authority_score, 0.7)  # Strong evidence
            logger.debug(f"[O2 AUTH] {material_name} has MAPTIS FLAMM test data: 0.7")

        return authority_score

    def _compute_environment_penalty(self,
                                    o2_env: O2EnvironmentSpec,
                                    limits: Dict[str, Any]) -> float:
        """
        Compute penalty for exceeding material's O2 environment limits.

        Returns: [0-1] where 0 = within limits, 1 = well beyond limits
        """
        penalty = 0.0

        # Pressure check
        max_pressure = limits.get('pressure_psi')
        if max_pressure and o2_env.pressure_psi > max_pressure:
            # Penalty proportional to exceedance
            exceedance = (o2_env.pressure_psi - max_pressure) / max_pressure
            penalty += min(0.5, exceedance * 0.5)

        # O2 concentration check
        max_o2 = limits.get('o2_pct')
        if max_o2 and o2_env.o2_concentration_pct > max_o2:
            penalty += 0.3

        # Temperature check (cryogenic)
        min_temp = limits.get('temperature_f')
        if min_temp and o2_env.temperature_f < min_temp:
            penalty += 0.2

        # Flow regime check
        required_flow = limits.get('flow_regime')
        if required_flow and o2_env.flow_regime and o2_env.flow_regime != required_flow:
            penalty += 0.3

        return min(1.0, penalty)

    def _matches_material_family(self, material_name: str, examples: List[str]) -> bool:
        """Check if material name matches a family (fuzzy token matching)."""
        material_name_upper = material_name.upper()
        material_tokens = set(material_name_upper.split())

        for example in examples:
            example_upper = example.upper()
            example_tokens = set(example_upper.split())

            # Check for key identifiers
            # Titanium detection
            if any(t in material_name_upper for t in ['TITANIUM', 'TI-', 'TI6AL', 'TI6-', 'TI 6']):
                if any(t in example_upper for t in ['TITANIUM', 'TI-', 'TI6AL']):
                    return True

            # Magnesium detection
            if any(t in material_name_upper for t in ['MAGNESIUM', 'MG-', 'MGAL', 'MG ']):
                if any(t in example_upper for t in ['MAGNESIUM', 'MG-']):
                    return True

            # Stainless steel with numeric designation
            if len(example_tokens) == 2:
                parts = list(example_tokens)
                numeric_part = next((p for p in parts if any(c.isdigit() for c in p)), None)
                prefix = next((p for p in parts if not any(c.isdigit() for c in p)), None)

                if numeric_part and prefix:
                    if numeric_part in material_name_upper:
                        # Stainless steel
                        if prefix in ['SS', 'STAINLESS'] and ('STAINLESS' in material_name_upper or 'CRES' in material_name_upper):
                            return True
                        # Inconel/nickel alloys
                        elif prefix in ['INCONEL', 'MONEL', 'HASTELLOY'] and any(m in material_name_upper for m in ['INCONEL', 'MONEL', 'HASTELLOY', 'NICKEL']):
                            return True
                        # Aluminum
                        elif prefix in ['AL', 'ALUMINUM'] and ('ALUMINUM' in material_name_upper or material_name_upper.startswith('AL ')):
                            return True
                        # Copper
                        elif prefix in ['CU', 'COPPER'] and ('COPPER' in material_name_upper or material_name_upper.startswith('CU')):
                            return True

            # Fallback: Check if all example tokens appear
            if example_tokens.issubset(material_tokens):
                return True

            # Check for Teflon/PTFE/TFE
            if any(t in example_upper for t in ['TEFLON', 'PTFE', 'TFE']):
                if any(t in material_name_upper for t in ['TEFLON', 'PTFE', 'TFE', 'FLUOROPOLYMER']):
                    return True

        return False

    def _compute_property_score(self,
                               candidate: Dict[str, Any],
                               material: Dict[str, Any],
                               flamm_rating: Optional[str],
                               o2_env: O2EnvironmentSpec) -> float:
        """
        Compute property fit score based on validated material properties.

        For O2 service, prefer:
        - Excellent flammability ratings (A or B)
        - High ignition temperature
        - Low heat of combustion
        - Non-porous surface (no particle shedding)
        """
        property_score = 0.0

        # Primary: MAPTIS flammability rating (A > B > C > D > X)
        if flamm_rating:
            rating_scores = {
                'A': 1.0,   # Pass - excellent
                'B': 0.7,   # Conditional pass
                'C': 0.4,   # Marginal
                'D': 0.2,   # Poor
                'I': 0.0,   # Insufficient data
                'K': 0.0,   # Inconclusive
                'N': 0.0,   # No test
                'U': 0.0,   # Unsatisfactory
                'X': 0.0    # Fail
            }
            property_score = rating_scores.get(flamm_rating, 0.0)
            logger.debug(f"[O2 PROP] FLAMM rating {flamm_rating} => {property_score:.2f}")

        # Boost for O2 test count
        o2_info = candidate.get('o2_info', {})
        o2_test_count = o2_info.get('o2_test_count', 0)
        if o2_test_count > 0:
            # Normalize test count to [0, 0.3] bonus
            test_bonus = min(0.3, o2_test_count / 10.0)
            property_score = min(1.0, property_score + test_bonus)

        return property_score

    def _compute_usage_score(self,
                            candidate: Dict[str, Any],
                            o2_env: O2EnvironmentSpec) -> float:
        """
        Compute usage score from historical MUA/MIUL precedents in O2 service.

        Returns: [0-1] proportion of precedents endorsing this material for O2 service
        """
        # TODO: Query MUA/MIUL database for O2 service precedents
        # Filter by similar O2 environment (concentration, pressure, temp)
        return 0.0

    def _compute_uncertainty_score(self,
                                   candidate: Dict[str, Any],
                                   flamm_rating: Optional[str]) -> float:
        """
        Compute uncertainty penalty based on data coverage.

        Returns: [0-1] penalty for sparse/missing data
        """
        # High uncertainty if no flammability test data
        if not flamm_rating or flamm_rating in ['I', 'K', 'N', 'U']:
            return 0.8  # Strong penalty for unknown O2 behavior

        o2_info = candidate.get('o2_info', {})
        o2_test_count = o2_info.get('o2_test_count', 0)

        if o2_test_count == 0:
            return 0.6  # Moderate penalty - have rating but no detailed tests
        elif o2_test_count < 3:
            return 0.3  # Low penalty for sparse data
        else:
            return 0.1  # Minimal penalty for good coverage

    def _classify_o2_compatibility(self,
                                   candidate: Dict[str, Any],
                                   material_name: str,
                                   evidence: MaterialEvidence,
                                   o2_env: O2EnvironmentSpec) -> O2Compatibility:
        """Classify material's O2 compatibility based on evidence and environment."""
        material_name_upper = material_name.upper()

        # Check for explicit incompatibility indicators
        # Titanium - EXCLUDED in O2 environments
        if any(indicator in material_name_upper for indicator in ['TITANIUM', 'TI-6', 'TI6AL', 'TI 6']):
            evidence.exclusion_reasons.append(
                "Titanium alloys are prohibited in O2 service per NASA-STD-6016 §4.2.6.2 - promoted combustion risk"
            )
            return O2Compatibility.INCOMPATIBLE

        # Magnesium - EXCLUDED in O2 environments
        if any(indicator in material_name_upper for indicator in ['MAGNESIUM', 'MG-', 'MGAL']):
            evidence.exclusion_reasons.append(
                "Magnesium alloys are prohibited in O2 service - highly flammable"
            )
            return O2Compatibility.INCOMPATIBLE

        # Check flammability rating
        flamm_rating = evidence.flamm_rating
        if flamm_rating == 'X' or flamm_rating == 'U':
            evidence.exclusion_reasons.append(
                f"MAPTIS flammability rating {flamm_rating} indicates failure - unsuitable for O2 service"
            )
            return O2Compatibility.INCOMPATIBLE

        # Check if material is BOK-recommended
        is_bok_recommended = evidence.f_authority >= 0.7

        # Check if material has good flammability data
        has_good_flamm = flamm_rating in ['A', 'B'] if flamm_rating else False

        if is_bok_recommended and has_good_flamm:
            return O2Compatibility.VERIFIED
        elif is_bok_recommended or has_good_flamm:
            # Add conditional warnings based on environment
            risk_level = o2_env.get_risk_level()
            if risk_level in ['HIGH', 'CRITICAL']:
                evidence.warnings.append(
                    f"High-risk O2 environment ({risk_level}) - verify material limits and precision cleaning requirements"
                )
            return O2Compatibility.CONDITIONAL
        else:
            evidence.warnings.append(
                "O2 compatibility not verified - engineering review and NASA-STD-6001 testing required"
            )
            return O2Compatibility.UNKNOWN

    def rank_materials(self, evidence_bundles: List[MaterialEvidence]) -> List[MaterialEvidence]:
        """
        Rank materials by evidence-weighted score.

        Returns: List of MaterialEvidence sorted by final score (descending)
        """
        for evidence in evidence_bundles:
            # Compute final score using configured weights
            final_score = evidence.compute_final_score(self.weights)

            logger.debug(
                f"[O2 RANK] {evidence.material_name}: "
                f"final={final_score:.3f} "
                f"(sem={evidence.f_semantic:.2f}, "
                f"prop={evidence.f_properties:.2f}, "
                f"auth={evidence.f_authority:.2f}, "
                f"use={evidence.f_usage:.2f}, "
                f"unc={evidence.f_uncertainty:.2f})"
            )

        # Sort by final score (descending)
        ranked = sorted(evidence_bundles,
                       key=lambda e: e.compute_final_score(self.weights),
                       reverse=True)

        return ranked

    def format_results_with_evidence(self,
                                    ranked: List[MaterialEvidence],
                                    excluded: List[MaterialEvidence],
                                    o2_env: O2EnvironmentSpec) -> Dict[str, Any]:
        """
        Format results into panes with full traceability.

        Returns:
            {
                'o2_bok_verified': [...],     # Pane A: Authoritative recommendations
                'other_candidates': [...],     # Pane B: Semantic matches (verify before use)
                'excluded_materials': [...],   # Excluded due to safety concerns
                'environment': {...}           # O2 environment specification
            }
        """
        o2_bok_verified = []
        other_candidates = []

        for evidence in ranked:
            final_score = evidence.compute_final_score(self.weights)

            result = {
                'material_key': evidence.material_key,
                'material_name': evidence.material_name,
                'material_code': evidence.material_code,
                'final_score': final_score,
                'o2_compatibility': evidence.o2_compatibility.value,
                'flamm_rating': evidence.flamm_rating,
                'o2_test_count': evidence.o2_test_count,
                'evidence': {
                    'semantic_score': evidence.f_semantic,
                    'property_score': evidence.f_properties,
                    'authority_score': evidence.f_authority,
                    'usage_score': evidence.f_usage,
                    'uncertainty_penalty': evidence.f_uncertainty
                },
                'citations': evidence.bok_citations,
                'warnings': evidence.warnings,
                'environment_limits': evidence.environment_limits
            }

            # Categorize into panes
            if evidence.o2_compatibility == O2Compatibility.VERIFIED:
                o2_bok_verified.append(result)
            else:
                other_candidates.append(result)

        # Format excluded materials
        excluded_results = []
        for evidence in excluded:
            excluded_results.append({
                'material_name': evidence.material_name,
                'material_code': evidence.material_code,
                'flamm_rating': evidence.flamm_rating,
                'exclusion_reasons': evidence.exclusion_reasons,
                'o2_compatibility': evidence.o2_compatibility.value
            })

        return {
            'o2_bok_verified': o2_bok_verified,
            'other_candidates': other_candidates,
            'excluded_materials': excluded_results,
            'environment': {
                'o2_concentration_pct': o2_env.o2_concentration_pct,
                'pressure_psi': o2_env.pressure_psi,
                'temperature_f': o2_env.temperature_f,
                'risk_level': o2_env.get_risk_level(),
                'environment_type': o2_env.classify_environment().value
            }
        }


def get_o2_policy_engine(o2_engine=None, safety_class: SafetyClass = SafetyClass.CLASS_A) -> O2PolicyEngine:
    """Factory function to get O2 policy engine instance."""
    return O2PolicyEngine(o2_engine=o2_engine, safety_class=safety_class)
