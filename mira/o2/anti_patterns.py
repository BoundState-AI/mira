#!/usr/bin/env python3
"""
Module: Anti Patterns
Purpose: Material Anti-Patterns Engine - Safety guard rails

BoundState AI 2025
Version: 1.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Fran OpenAI 5 <noreply@openai.com>
Co-Authored-By: Grok 4.0 <noreply@x.ai>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: NASA-STD-8739.8B, SWE-055
Safety Critical: True
"""

# Copyright © 2025 BoundState AI. All Rights Reserved.
# Classification: BoundState Proprietary
# License: Evaluation Use Only - Authorized Pilot Program
"""
Material Anti-Patterns Engine - Safety guard rails

Defines patterns that trigger warnings or blocks when recommending material
substitutions in aerospace applications. Prevents dangerous combinations
based on known failure modes and aerospace incident history.

Compliance: NASA-STD-8739.8B, SWE-055

Author: BoundState Team
Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Fran OpenAI <noreply@openai.com>
Co-Authored-By: Grok <noreply@x.ai>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI
"""

__version__ = "1.0.0"
__safety_critical__ = True  # Prevents dangerous material substitutions

from typing import Dict, List, Any, Optional
from dataclasses import dataclass, field
import uuid


@dataclass
class AntiPattern:
    """Definition of a material substitution anti-pattern.

    Backwards-compatible fields:
    - original_condition / forbidden_condition: used by tests and simple validation
    - from_material / to_material / conditions / message: used by runtime checker
    """

    name: str
    description: str
    # Test-oriented fields
    original_condition: Dict[str, Any] = field(default_factory=dict)
    forbidden_condition: Dict[str, Any] = field(default_factory=dict)
    severity: str = "warning"  # one of: info, warning, high, critical

    # Runtime-oriented fields (optional)
    from_material: List[str] = field(default_factory=list)
    to_material: List[str] = field(default_factory=list)
    conditions: Dict[str, Any] = field(default_factory=dict)
    message: str = ""
    source: str = ""  # NASA SWE-013 traceability


    def __post_init__(self) -> None:
        # Normalize legacy/alias severities
        alias_map = {
            "block": "critical",
            "warn": "warning",
            "medium": "high",
        }
        if self.severity in alias_map:
            self.severity = alias_map[self.severity]

        allowed = {"info", "warning", "high", "critical"}
        if self.severity not in allowed:
            raise ValueError(f"Invalid severity '{self.severity}' (allowed: {sorted(allowed)})")


# Define known anti-patterns
MATERIAL_ANTI_PATTERNS = [
    # PFAS -> PFAS (critical)
    AntiPattern(
        name="pfas_to_pfas",
        description="Replacing one PFAS with another PFAS",
        original_condition={"contains_pfas": True},
        forbidden_condition={"contains_pfas": True},
        severity="critical",
        from_material=["PTFE", "PVDF", "FEP", "PFA", "ETFE", "VITON", "FKM"],
        to_material=["PTFE", "PVDF", "FEP", "PFA", "ETFE", "VITON", "FKM"],
        conditions={},
        message="Cannot recommend replacing one PFAS material with another PFAS material",
    ),

    # High outgassing (critical per NASA screening threshold)
    AntiPattern(
        name="high_outgassing",
        description="Outgassing exceeds NASA screening threshold (ASTM E595)",
        original_condition={"outgassing_tml_pct": {"op": ">=", "value": 1.0}},
        forbidden_condition={"outgassing_tml_pct": {"op": ">=", "value": 1.0}},
        severity="critical",
    ),

    # Radiation resistance (low)
    AntiPattern(
        name="low_radiation_resistance",
        description="Material exhibits low radiation resistance for space environment",
        original_condition={"radiation_resistance": {"op": "<", "value": 1.0}},
        forbidden_condition={"radiation_resistance": {"op": "<", "value": 1.0}},
        severity="warning",
    ),
    
    AntiPattern(
        name="aluminum_to_steel_galvanic",
        description="Galvanic corrosion risk",
        severity="warning",
        from_material=["aluminum", "Al"],
        to_material=["steel", "stainless steel"],
        conditions={"environment": "marine", "contact": "direct"},
        message="Risk of galvanic corrosion between aluminum and steel in marine environments"
    ),
    
    AntiPattern(
        name="titanium_oxygen_ignition",
        description="Titanium ignition risk in oxygen",
        severity="critical",
        from_material=["*"],
        to_material=["titanium", "Ti"],
        conditions={"service": "oxygen", "pressure": "high"},
        message="Titanium can ignite in high-pressure oxygen service"
    ),
    
    AntiPattern(
        name="lead_replacement_density",
        description="Lead replacement without considering density",
        from_material=["lead", "Pb"],
        to_material=["aluminum", "plastic"],
        conditions={"function": "radiation_shielding"},
        severity="block",
        message="Cannot replace lead with low-density materials for radiation shielding"
    ),
    
    AntiPattern(
        name="ceramic_brittleness",
        description="Replacing ductile with brittle",
        from_material=["metal", "polymer"],
        to_material=["ceramic", "glass"],
        conditions={"loading": "impact", "vibration": "high"},
        severity="warning",
        message="Ceramic/glass materials may fail under impact or vibration"
    ),
    
    AntiPattern(
        name="temperature_mismatch",
        description="Insufficient temperature resistance",
        from_material=["*"],
        to_material=["*"],
        conditions={"temperature_delta": -100},  # Replacement has 100°C lower rating
        severity="block",
        message="Replacement material has insufficient temperature resistance"
    ),
    
    # NASA-STD-6001 Section 4.5.11 - Mercury Contamination
    AntiPattern(
        name="mercury_contamination",
        description="Mercury causes liquid metal embrittlement - can destroy spacecraft structure",
        from_material=["*"],
        to_material=["aluminum", "Al", "titanium", "Ti", "magnesium", "Mg"],
        conditions={"contains_mercury": True},
        severity="block",
        message="Mercury causes liquid metal embrittlement in aluminum, titanium, and magnesium - prohibited in spacecraft"
    ),
    
    AntiPattern(
        name="mercury_exposure",
        description="Mercury contamination risk",
        from_material=["aluminum", "titanium", "magnesium"],
        to_material=["mercury", "Hg", "mercury-containing"],
        conditions={},
        severity="block",
        message="Mercury exposure can cause catastrophic embrittlement of structural metals"
    ),
    
    # NASA-STD-6001 Section 4.4.11 - Stress Corrosion Cracking
    AntiPattern(
        name="titanium_stress_corrosion",
        description="Titanium alloys subject to stress corrosion cracking",
        from_material=["*"],
        to_material=["titanium", "Ti", "Ti-6Al-4V"],
        conditions={"environment": ["methanol", "nitrogen_tetroxide", "red_fuming_nitric_acid"]},
        severity="block",
        message="Titanium alloys are susceptible to stress corrosion cracking in methanol and nitrogen tetroxide environments"
    ),
    
    AntiPattern(
        name="aluminum_stress_corrosion",
        description="Aluminum alloys subject to stress corrosion cracking",
        from_material=["*"],
        to_material=["aluminum", "Al", "aluminum_alloy"],
        conditions={"environment": ["mercury", "gallium", "high_stress"]},
        severity="block",
        message="Aluminum alloys are susceptible to stress corrosion cracking when exposed to mercury or gallium"
    ),
    
    AntiPattern(
        name="stainless_steel_stress_corrosion",
        description="Stainless steel chloride stress corrosion",
        from_material=["*"],
        to_material=["stainless steel", "stainless", "SS"],
        conditions={"environment": ["chlorides", "high_stress"]},
        severity="warning",
        message="Stainless steel is susceptible to chloride stress corrosion cracking under high stress"
    ),
    
    # NASA-STD-6001 Section 4.4.12 - Tin Whiskers
    AntiPattern(
        name="tin_whiskers",
        description="Pure tin develops conductive whiskers that can cause short circuits",
        from_material=["*"],
        to_material=["pure_tin", "tin_plating", "tin", "Sn"],
        conditions={"pure_tin": True},
        severity="block",
        message="Pure tin plating develops whiskers that cause electrical shorts - use tin-lead alloy or conformal coating"
    ),
    
    # NASA-STD-6001 Section 4.5.4 - Cadmium Restrictions
    AntiPattern(
        name="cadmium_ban",
        description="Cadmium plating restriction due to vacuum instability and toxicity",
        from_material=["*"],
        to_material=["cadmium", "Cd", "cadmium_plating"],
        conditions={},
        severity="block",
        message="Cadmium plating prohibited due to vacuum instability, hydrogen embrittlement, and toxicity - use zinc-nickel or ion vapor aluminum"
    ),
    
    # NASA-STD-6001 Section 4.5.15 - Zinc Embrittlement
    AntiPattern(
        name="zinc_embrittlement",
        description="Zinc embrittlement of high-strength steels and titanium",
        from_material=["*"],
        to_material=["stainless_steel", "titanium", "high_strength_steel"],
        conditions={"zinc_exposure": True, "temperature": ">230C"},
        severity="block",
        message="Zinc exposure above 230°C causes embrittlement of stainless steel and titanium"
    ),
    
    # NASA-STD-6001 Section 4.5.6 - Dissimilar Metals Galvanic Corrosion
    AntiPattern(
        name="galvanic_corrosion_magnesium_steel",
        description="High galvanic potential difference - magnesium to stainless steel",
        from_material=["magnesium", "Mg"],
        to_material=["stainless_steel", "stainless", "steel"],
        conditions={"moisture_present": True},
        severity="block",
        message="Galvanic potential difference of 0.85V between magnesium and stainless steel causes severe corrosion"
    ),
    
    AntiPattern(
        name="galvanic_corrosion_aluminum_copper",
        description="High galvanic potential difference - aluminum to copper",
        from_material=["aluminum", "Al"],
        to_material=["copper", "Cu", "brass", "bronze"],
        conditions={"moisture_present": True},
        severity="warning",
        message="Galvanic potential difference of 0.62V between aluminum and copper causes corrosion - use isolation"
    ),
    
    AntiPattern(
        name="galvanic_corrosion_titanium_aluminum",
        description="Moderate galvanic potential difference - titanium to aluminum",
        from_material=["titanium", "Ti"],
        to_material=["aluminum", "Al"],
        conditions={"moisture_present": True},
        severity="warning",
        message="Galvanic potential difference of 0.53V between titanium and aluminum - monitor for corrosion"
    ),
    
    # NASA-STD-6001 Section 4.4.6 - Fungus Growth
    AntiPattern(
        name="fungus_nutrients",
        description="Materials that support fungal growth",
        from_material=["*"],
        to_material=["cellulose", "leather", "natural_rubber", "cotton", "wool"],
        conditions={"hermetically_sealed": False},
        severity="warning",
        message="Cellulose, leather, and natural rubber support fungal growth unless hermetically sealed"
    ),
    
    # NASA-STD-6001 Section 4.4.9 - Oxygen Compatibility (Enhanced)
    AntiPattern(
        name="aluminum_powder_oxygen",
        description="Aluminum powder ignition risk in oxygen",
        from_material=["*"],
        to_material=["aluminum_powder", "Al_powder"],
        conditions={"service": "oxygen"},
        severity="block",
        message="Aluminum powder is highly combustible in oxygen service - prohibited"
    ),
    
    AntiPattern(
        name="magnesium_oxygen",
        description="Magnesium alloys in oxygen service",
        from_material=["*"],
        to_material=["magnesium", "Mg", "magnesium_alloy"],
        conditions={"service": "oxygen"},
        severity="block",
        message="Magnesium alloys are incompatible with oxygen service due to combustion risk"
    ),
    
    AntiPattern(
        name="thin_titanium_oxygen",
        description="Thin titanium sections in oxygen",
        from_material=["*"],
        to_material=["titanium", "Ti"],
        conditions={"service": "oxygen", "thickness": "<0.1mm"},
        severity="block",
        message="Titanium sections less than 0.1mm thick are combustible in oxygen service"
    ),
    
    AntiPattern(
        name="hydrocarbon_lubricants_oxygen",
        description="Hydrocarbon lubricants in oxygen",
        from_material=["*"],
        to_material=["hydrocarbon_lubricant", "petroleum_lubricant", "oil", "grease"],
        conditions={"service": "oxygen"},
        severity="block",
        message="Hydrocarbon lubricants are combustible in oxygen service - use oxygen-compatible alternatives"
    ),
    
    # Temperature Service Limits
    AntiPattern(
        name="ptfe_temperature_limit",
        description="PTFE degradation above 260°C",
        from_material=["*"],
        to_material=["PTFE", "Teflon"],
        conditions={"temperature": ">260C"},
        severity="block",
        message="PTFE degrades above 260°C releasing toxic fluorine compounds"
    ),
    
    AntiPattern(
        name="pvc_temperature_limit",
        description="PVC releases HCl above 60°C",
        from_material=["*"],
        to_material=["PVC", "polyvinyl_chloride"],
        conditions={"temperature": ">60C"},
        severity="warning",
        message="PVC releases corrosive HCl above 60°C - consider alternative"
    ),
    
    AntiPattern(
        name="polycarbonate_temperature_limit",
        description="Polycarbonate degradation above 120°C",
        from_material=["*"],
        to_material=["polycarbonate", "PC"],
        conditions={"temperature": ">120C"},
        severity="warning",
        message="Polycarbonate degrades above 120°C losing mechanical properties"
    )
]


def check_anti_patterns(
    original_material: Dict[str, Any],
    replacement_material: Dict[str, Any],
    context: Any
) -> List[Dict[str, Any]]:
    """
    Check for anti-patterns in material substitution.
    
    Args:
        original_material: Material being replaced
        replacement_material: Proposed replacement
        context: Application context
        
    Returns:
        List of triggered anti-patterns with details
    """
    triggered_patterns = []
    
    # Get material compositions
    orig_comp = original_material.get("Composition", "").lower()
    repl_comp = replacement_material.get("Composition", "").lower()
    
    for pattern in MATERIAL_ANTI_PATTERNS:
        # Check if materials match the pattern
        from_match = check_material_match(orig_comp, pattern.from_material)
        to_match = check_material_match(repl_comp, pattern.to_material)
        
        if from_match and to_match:
            # Check conditions
            if check_conditions(pattern.conditions, context, 
                              original_material, replacement_material):
                triggered_patterns.append({
                    "name": pattern.name,
                    "severity": pattern.severity,
                    "message": pattern.message,
                    "description": pattern.description
                })
    
    return triggered_patterns


def check_material_match(composition: str, pattern_materials: List[str]) -> bool:
    """Check if composition matches any pattern materials."""
    
    if "*" in pattern_materials:
        return True
    
    for pattern_mat in pattern_materials:
        if pattern_mat.lower() in composition:
            return True
    
    return False


def check_conditions(
    conditions: Dict[str, Any],
    context: Any,
    original: Dict,
    replacement: Dict
) -> bool:
    """Check if pattern conditions are met."""
    
    if not conditions:
        return True
    
    for key, value in conditions.items():
        # Environment conditions
        if key == "environment":
            if hasattr(context, "environmental_conditions"):
                if isinstance(value, list):
                    if any(env in context.environmental_conditions.environment_type for env in value):
                        return True
                elif value in context.environmental_conditions.environment_type:
                    return True
            # Check composition for environmental indicators
            repl_comp = replacement.get("Composition", "").lower()
            if isinstance(value, list):
                if any(env.lower() in repl_comp for env in value):
                    return True
            elif value.lower() in repl_comp:
                return True
                
        # Service type conditions
        elif key == "service":
            if hasattr(context, "primary_function"):
                if value in context.primary_function.lower():
                    return True
            # Check for oxygen service indicators
            if value == "oxygen":
                if hasattr(context, "primary_function") and "oxygen" in context.primary_function.lower():
                    return True
                # Check test reports for oxygen service
                for report in replacement.get("TestReports", []):
                    test_type = report.get("TestType", "").lower()
                    if "oxygen" in test_type or "combustion" in test_type:
                        return True
                        
        # Temperature conditions
        elif key == "temperature_delta":
            orig_temp = extract_max_temperature(original)
            repl_temp = extract_max_temperature(replacement)
            if orig_temp and repl_temp:
                if (repl_temp - orig_temp) <= value:
                    return True
                    
        elif key == "temperature":
            # Handle temperature thresholds like ">260C"
            if isinstance(value, str) and value.startswith(">"):
                threshold = float(value[1:-1])  # Remove > and C
                repl_temp = extract_max_temperature(replacement)
                if repl_temp and repl_temp > threshold:
                    return True
            elif isinstance(value, str) and value.startswith("<"):
                threshold = float(value[1:-1])  # Remove < and C
                repl_temp = extract_max_temperature(replacement)
                if repl_temp and repl_temp < threshold:
                    return True
                    
        # Material-specific conditions
        elif key == "contains_mercury":
            repl_comp = replacement.get("Composition", "").lower()
            if value and ("mercury" in repl_comp or "hg" in repl_comp):
                return True
                
        elif key == "pure_tin":
            repl_comp = replacement.get("Composition", "").lower()
            if value and ("pure tin" in repl_comp or "tin plating" in repl_comp):
                return True
                
        elif key == "zinc_exposure":
            repl_comp = replacement.get("Composition", "").lower()
            if value and ("zinc" in repl_comp or "zn" in repl_comp):
                return True
                
        elif key == "moisture_present":
            # Assume moisture present unless explicitly in dry/vacuum environment
            if hasattr(context, "environmental_conditions"):
                env_type = context.environmental_conditions.environment_type.lower()
                if value and "vacuum" not in env_type and "dry" not in env_type:
                    return True
            else:
                return value  # Default assumption
                
        elif key == "hermetically_sealed":
            if hasattr(context, "packaging") and context.packaging:
                return context.packaging.sealed == value
            else:
                return not value  # Default assumption is not sealed
                
        elif key == "thickness":
            # Handle thickness conditions like "<0.1mm"
            if isinstance(value, str) and value.startswith("<"):
                threshold = float(value[1:-2])  # Remove < and mm
                # Check material properties for thickness
                thickness = None
                for prop in ["thickness", "wall_thickness", "Thickness"]:
                    if prop in replacement:
                        try:
                            thickness = float(replacement[prop])
                            break
                        except (ValueError, TypeError):
                            pass
                if thickness and thickness < threshold:
                    return True
    
    return False


def extract_max_temperature(material: Dict) -> float:
    """Extract maximum operating temperature from material data."""
    
    # Check test reports
    for report in material.get("TestReports", []):
        if "temperature" in report.get("TestType", "").lower():
            try:
                return float(report.get("Result", 0))
            except (ValueError, TypeError):
                pass
    
    # Check direct properties
    for key in ["MaxTemperature", "max_temperature", "MaxTemp"]:
        if key in material:
            try:
                return float(material[key])
            except (ValueError, TypeError):
                pass
    
    return None
