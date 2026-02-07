#!/usr/bin/env python3
"""
Module: Unit Normalizer
Purpose: Unit conversion and normalization for material properties.

BoundState AI 2025
Version: 1.0.0
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Fran OpenAI 5 <noreply@openai.com>
Co-Authored-By: Grok 4.0 <noreply@x.ai>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: SWE-032 (Data validation), SWE-033 (Requirements Traceability)
Safety Critical: True
"""

import re
import logging
import uuid

logger = logging.getLogger(__name__)

__safety_critical__ = True
__all__ = ['parse_and_normalize']

def mil_to_mm(value_mil: float) -> float:
    """Convert mil to mm.
    
    Args:
        value_mil: Value in mil.
        
    Returns:
        Value in mm.
        
    Compliance: SWE-032
    """
    return value_mil * 0.0254

def v_per_mil_to_kv_per_mm(vpm: float) -> float:
    """Convert V/mil to kV/mm.
    
    Args:
        vpm: Value in V/mil.
        
    Returns:
        Value in kV/mm.
        
    Compliance: SWE-032
    """
    # Round to 5 decimals for stable comparisons in tests
    return round(vpm * 0.03937, 5)

def mg_to_percent(mg_loss: float, basis_mg: float = 1000.0) -> float:
    """Convert mg loss to percent.
    
    Args:
        mg_loss: Loss in mg.
        basis_mg: Basis mass in mg (default 1000).
        
    Returns:
        Percent value.
        
    Compliance: SWE-032
    """
    return (mg_loss / basis_mg) * 100.0

def parse_and_normalize(prop: str, raw_val: str, raw_unit: str) -> float:
    """Parse and normalize value with unit for property.
    
    Args:
        prop: Property name.
        raw_val: Raw numeric string.
        raw_unit: Raw unit string.
        
    Returns:
        Normalized float value.
        
    Compliance: SWE-032, SWE-134
    """
    try:
        val = float(raw_val)
        u = raw_unit.lower().strip()
    except ValueError as e:
        logger.warning(f"Invalid numeric value '{raw_val}' for {prop}: {e}")
        raise ValueError(f"Invalid value for {prop}")
    
    if prop == "dielectric_strength_kv_mm":
        if u in ("v/mil", "vpm", "v per mil"):
            return v_per_mil_to_kv_per_mm(val)
        elif u in ("kv/mm", "kv per mm", ""):
            return val
        else:
            logger.warning(f"[Unverified] Unknown unit '{u}' for {prop}, assuming kV/mm")
            return val
    elif prop in ("tml_pct", "cvcm_pct"):
        if u in ("mg", "milligrams"):
            return mg_to_percent(val)
        elif u in ("%", "percent", "pct", ""):
            return val
        else:
            logger.warning(f"[Unverified] Unknown unit '{u}' for {prop}, assuming %")
            return val
    elif prop == "density_g_cm3":
        if u in ("g/cm3", "g/cm³", "gcc", ""):
            return val
        else:
            logger.warning(f"[Unverified] Unknown unit '{u}' for {prop}, assuming g/cm³")
            return val
    else:
        logger.info(f"No normalization needed for {prop}")
        return val
