#!/usr/bin/env python3
"""
Module: M&P Plan Generator Engines
Purpose: Engine exports for M&P Plan Generator V2

BoundState AI 2026
Version: 2.0.0
Classification: BoundState Proprietary

Engines:
- Engine A: DataAcquisitionEngine - Material data acquisition and normalization
- Engine B: ApplicabilityEngine - MPR applicability determination
- Engine C: ComplianceEvaluationEngine - Gap detection and compliance evaluation
- MinorQuantityEngine - Zone-based minor quantity aggregation

Compliance: NASA-STD-8739.8B, SWE-013, SWE-033
Safety Critical: False
"""

from .applicability import ApplicabilityEngine, get_applicability_engine
from .compliance_eval import ComplianceEvaluationEngine, get_compliance_eval_engine
from .data_acquisition import DataAcquisitionEngine, get_data_acquisition_engine
from .minor_quantity import MinorQuantityEngine, get_minor_quantity_engine

__all__ = [
    # Engine A
    "DataAcquisitionEngine",
    "get_data_acquisition_engine",
    # Engine B
    "ApplicabilityEngine",
    "get_applicability_engine",
    # Engine C
    "ComplianceEvaluationEngine",
    "get_compliance_eval_engine",
    # Minor Quantity
    "MinorQuantityEngine",
    "get_minor_quantity_engine",
]

__version__ = "2.0.0"
__safety_critical__ = False
