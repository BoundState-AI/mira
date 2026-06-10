"""
Module: AM Knowledge Twin -- classification validator engine (Rev 5 §6.3)
Purpose: Validate the engineer's declared class against declared consequence
         and hazard inputs using the validator selected by
         classification_framework. Never invents a verdict for an
         unsupported framework; never generates a class from material+process.

BoundState AI 2026
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: SWE-013, SWE-032, SWE-033, NASA-STD-8739.8B
Safety Critical: True
"""

from __future__ import annotations

__version__ = "0.1.0"
__safety_critical__ = True

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from mira.knowledge_twins.am.am_models import (
    AMPartClass,
    AMProcess,
    ClassificationInput,
    MaterialType,
)
from mira.knowledge_twins.am.classification_model import (
    ClassificationVerdict,
    SecondaryInputs,
    assess_secondary_classification,
    validate_primary_class,
)

# Frameworks with a loaded validator. The 6030 decision model (PR-0) is the
# demo default; customer schemes are Product Track (Rev 5 §6.3, §12).
SUPPORTED_FRAMEWORKS: tuple[str, ...] = ("NASA-STD-6030",)


class ClassificationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    verdict: str  # MATCHES | MISMATCH | CANNOT_VALIDATE
    framework: str
    framework_supported: bool
    declared_class: Optional[AMPartClass]
    expected_class: Optional[AMPartClass]
    reason: str
    citations: list[str] = Field(default_factory=list)
    missing_inputs: list[str] = Field(default_factory=list)
    surfaced_factors: list[str] = Field(default_factory=list)
    subclass: Optional[int] = None
    subclass_rationale: Optional[str] = None


def _format_citation(standard_id: str, section: Optional[str], tag: Optional[str], page: Optional[int]) -> str:
    parts = [standard_id]
    if section:
        parts.append(f"§{section}")
    if tag:
        parts.append(f"[{tag}]")
    if page:
        parts.append(f"p.{page}")
    return " ".join(parts)


def evaluate_classification(
    classification: ClassificationInput,
    material_type: Optional[MaterialType] = None,
    am_process: Optional[AMProcess] = None,
    secondary_inputs: Optional[SecondaryInputs] = None,
) -> ClassificationResult:
    """Engine 6.3: framework-explicit classification validation.

    Safety gate: callers must already hold engineer confirmation
    (safety_critical_confirmed) before evaluation; the orchestrator enforces
    it. This engine additionally surfaces, never resolves, judgment calls.
    """
    framework = classification.classification_framework
    factors = [
        f"consequence_of_failure={classification.consequence_of_failure.value}",
        *(f"hazard:{flag.value}" for flag in classification.hazard_context),
        *(
            [f"fluid_service={classification.fluid_service}"]
            if classification.fluid_service
            else []
        ),
        *(
            [f"redundancy={classification.redundancy}"]
            if classification.redundancy
            else []
        ),
    ]

    if framework not in SUPPORTED_FRAMEWORKS:
        # Rev 5 §6.3 / Golden Test 6: no loaded validator -> no invented
        # verdict. Surface the factors and decline.
        return ClassificationResult(
            verdict="CANNOT_VALIDATE",
            framework=framework,
            framework_supported=False,
            declared_class=classification.intended_class,
            expected_class=None,
            reason=(
                f"No classification validator is loaded for framework "
                f"{framework!r}; supported: {', '.join(SUPPORTED_FRAMEWORKS)}. "
                "Consequence and hazard factors are surfaced for engineer "
                "judgment; no verdict is invented (Rev 5 §6.3)."
            ),
            surfaced_factors=factors,
        )

    finding = validate_primary_class(
        classification.intended_class,
        classification.consequence_of_failure,
        classification.hazard_context,
        classification.mission_critical,
        classification.class_c_criteria_confirmed,
        material_type=material_type,
    )
    citations = [
        _format_citation(c.standard_id, c.section, c.requirement_tag, c.page)
        for c in finding.citations
    ]

    result = ClassificationResult(
        verdict=finding.verdict.value,
        framework=framework,
        framework_supported=True,
        declared_class=finding.declared_class,
        expected_class=finding.expected_class,
        reason=finding.rationale,
        citations=citations,
        missing_inputs=list(finding.missing_inputs),
        surfaced_factors=factors,
    )

    # Secondary classification only when the primary verdict stands and the
    # declared class carries a subclass ([AMR-12]: Class A and B).
    if (
        finding.verdict is ClassificationVerdict.MATCHES
        and finding.declared_class in (AMPartClass.CLASS_A, AMPartClass.CLASS_B)
        and secondary_inputs is not None
    ):
        secondary = assess_secondary_classification(
            finding.declared_class, material_type, am_process, secondary_inputs
        )
        result = result.model_copy(
            update={
                "subclass": secondary.subclass,
                "subclass_rationale": secondary.rationale,
                "missing_inputs": sorted(
                    set(result.missing_inputs) | set(secondary.missing_inputs)
                ),
            }
        )
    return result
