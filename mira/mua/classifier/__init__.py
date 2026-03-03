"""MUA Classifier — BS-SPEC-MUA-003 Implementation.

Flag-first deterministic MUA classification per NASA-STD-6016C w/Change 2
and JSC-27301 Rev J. An MUA is a response to a FLAG, not to a material.

Pipeline: MIUL Row → Step 1-8 → Form 551
Supersedes: BS-SPEC-MUA-002 (architecture was material-first)

Modules
-------
models
    Data models: FlagType, MUAType, ClassifierResult, PipelineResult, Form551Fields.
screening
    Material-class pre-filter gate (Step 3).
classifier
    Step functions (Steps 1-6) and integrated classify_mua.
domain_facts
    12 curated domain facts with provenance (Step 4).
grouping
    MAPTIS code + issue key grouping logic.
rationale
    Rationale & disposition template engine (Steps 7-8).
pipeline
    Full pipeline orchestration (Steps 1-8).

BoundState AI 2026
Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: NASA-STD-6016C w/Change 2, JSC-27301 Rev J
Safety Critical: True
"""

from .models import (
    MaterialClassEnum,
    FlagType,
    MUAType,
    MUACategorySpec,
    RatingSemantics,
    RATING_SEMANTICS,
    COLUMN_FLAG_DICT,
    DecodedFlag,
    ScreeningResult,
    ClassifierResult,
    MUAGroup,
    Form551Fields,
    PipelineResult,
)
from .screening import (
    is_screening_applicable,
    material_class_from_miul,
    SCREENING_APPLICABILITY,
)
from .classifier import (
    classify_mua,
    classify_mua_batch,
    step1_identify_flags,
    step2_decode_flag,
    step3_should_flag_exist,
    step4_hazard_applies,
    step5_classify_type,
    step6_assign_category,
)
from .domain_facts import DomainFact, DOMAIN_FACTS, get_fact, get_fact_text
from .grouping import group_by_maptis_issue
from .rationale import render_rationale, render_disposition
from .pipeline import process_single_flag, process_miul_row, process_miul_batch

__all__ = [
    # Models
    "MaterialClassEnum",
    "FlagType",
    "MUAType",
    "MUACategorySpec",
    "RatingSemantics",
    "RATING_SEMANTICS",
    "COLUMN_FLAG_DICT",
    "DecodedFlag",
    "ScreeningResult",
    "ClassifierResult",
    "MUAGroup",
    "Form551Fields",
    "PipelineResult",
    # Screening
    "is_screening_applicable",
    "material_class_from_miul",
    "SCREENING_APPLICABILITY",
    # Classifier step functions
    "classify_mua",
    "classify_mua_batch",
    "step1_identify_flags",
    "step2_decode_flag",
    "step3_should_flag_exist",
    "step4_hazard_applies",
    "step5_classify_type",
    "step6_assign_category",
    # Domain facts
    "DomainFact",
    "DOMAIN_FACTS",
    "get_fact",
    "get_fact_text",
    # Grouping
    "group_by_maptis_issue",
    # Rationale
    "render_rationale",
    "render_disposition",
    # Pipeline
    "process_single_flag",
    "process_miul_row",
    "process_miul_batch",
]
