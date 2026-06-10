"""
Module: AM Knowledge Twin -- applicability engine (Rev 5 §6.1)
Purpose: Determine which frozen-pack requirements apply to a request, with a
         corpus-coverage statement. Class scoping is derived from the frozen
         requirement text itself -- never from a hand-maintained table.

BoundState AI 2026
Classification: BoundState Proprietary

Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: SWE-013, SWE-032, SWE-033, NASA-STD-8739.8B
Safety Critical: True

Scoping logic (text-derived, deterministic):
    NASA-STD-6030 expresses class scope in the requirement text with a
    small set of recurring phrasings ("For Class A and B parts, ...",
    "For Class C parts, ...", "All AM parts in Classes A1 through B2 ...").
    We parse those phrasings; a requirement with no recognized class scope
    applies to all classes. Absence of a requirement from the ingested
    corpus is NOT proof of non-applicability (Rev 5 §10) -- the coverage
    statement says exactly what was and was not consulted.
"""

from __future__ import annotations

__version__ = "0.1.0"
__safety_critical__ = True

import re
from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from mira.knowledge_twins.am.am_models import AccessContext, AMPartClass
from mira.knowledge_twins.am.content_store import AMContentStore
from mira.knowledge_twins.am.rule_pack_models import PackRequirement

# Demo Track required corpus families (Rev 5 §4.1): the two public anchors.
REQUIRED_DEMO_FAMILIES: tuple[str, ...] = ("NASA-STD-6030", "NASA-STD-6033")

_CLASS_LETTER = {"A": AMPartClass.CLASS_A, "B": AMPartClass.CLASS_B, "C": AMPartClass.CLASS_C}

# A class list as 6030 writes them: "A", "A and B", "A, B1, and B2",
# "Class A or Class B". Subclass digits are folded to their letter.
_CLASS_LIST = (
    r"(?P<list>[ABC]\d?(?:(?:\s*,\s*(?:and\s+|or\s+)?|\s+(?:and|or)\s+)"
    r"(?:Class\s+)?[ABC]\d?)*)"
)

# Recognized class-scope phrasings in 6030/6033 requirement text. Each
# pattern captures a 'list' group; letters are extracted from it. A range
# pattern ("Classes A1 through B2") is handled separately.
_SCOPE_PATTERNS: tuple[re.Pattern[str], ...] = (
    # "For Class A and B parts", "for metallic Class A, B1, and B2 part
    # production", "for Class B part production"
    re.compile(
        rf"\bfor\s+(?:\w+\s+)?Class(?:es)?\s+{_CLASS_LIST}\s+(?:\w+\s+)*?parts?\b",
        re.IGNORECASE,
    ),
    # "All Class A parts shall", "All Class A and B AM parts shall"
    re.compile(
        rf"\bAll\s+(?:\w+\s+)*?Class(?:es)?\s+{_CLASS_LIST}\s+(?:\w+\s+)*?parts?\b",
        re.IGNORECASE,
    ),
    # "Class A parts shall not", "Class B parts shall"
    re.compile(rf"^\s*Class\s+{_CLASS_LIST}\s+parts\s+shall", re.IGNORECASE),
)

# "All AM parts in Classes A1 through B2": alphabetic range.
_SCOPE_RANGE = re.compile(
    r"\bClasses\s+(?P<lo>[ABC])\d?\s+through\s+(?P<hi>[ABC])\d?", re.IGNORECASE
)

_LIST_LETTERS = re.compile(r"\b([ABC])\d?\b")


class CoverageLevel(str, Enum):
    FULL = "FULL"
    PARTIAL = "PARTIAL"
    INSUFFICIENT = "INSUFFICIENT"


class ScopedRequirement(BaseModel):
    """A requirement with its derived class scope and citation."""

    model_config = ConfigDict(extra="forbid")

    requirement_id: str
    standard_id: str
    section: str
    source_tag: str
    page: Optional[int]
    shall_text: str
    scoped_classes: list[AMPartClass]  # empty = applies to all classes
    rule_pack_id: str


class CoverageStatement(BaseModel):
    model_config = ConfigDict(extra="forbid")

    level: CoverageLevel
    families_present: list[str]
    families_missing: list[str]
    placeholder_families: list[str]
    statement: str


class ApplicabilityResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    applicable: list[ScopedRequirement]
    excluded_by_class: list[str]  # requirement_ids excluded for the declared class
    coverage: CoverageStatement
    rule_pack_ids: list[str]
    notes: list[str] = Field(default_factory=list)


def derive_class_scope(shall_text: str) -> list[AMPartClass]:
    """Parse the class scope a requirement states for itself. Empty list
    means the text declares no class restriction -> applies to all."""
    range_match = _SCOPE_RANGE.search(shall_text)
    if range_match:
        lo, hi = sorted(
            (range_match.group("lo").upper(), range_match.group("hi").upper())
        )
        return [_CLASS_LETTER[c] for c in "ABC" if lo <= c <= hi]
    for pattern in _SCOPE_PATTERNS:
        match = pattern.search(shall_text)
        if not match:
            continue
        letters = sorted(
            {m.group(1).upper() for m in _LIST_LETTERS.finditer(match.group("list"))}
        )
        if letters:
            return [_CLASS_LETTER[c] for c in letters]
    return []


# [AMR-11] p.39: an Exempt designation "exempts it from all other
# requirements in this NASA Technical Standard", while its rationale states
# "Every AM part requires evaluation for classification, and documentation
# thereof". So for Exempt parts only the classification requirements
# themselves remain applicable in the PART-level list.
#
# Deliberate interpretation (adversarial review 2026-06-09): NASA-STD-6033
# obligations are equipment/facility-scoped, not part-classification-scoped.
# They are OMITTED from an Exempt part's part-level applicability list (this
# list answers "what applies to THIS part"), but they are NOT vacated -- the
# producing facility's EFCP obligations stand regardless of part class. The
# result carries an explicit note saying so rather than dropping them
# silently.
_EXEMPT_SURVIVING_TAGS = frozenset({"AMR 5", "AMR 11"})
_EXEMPT_6033_NOTE = (
    "Exempt designation: NASA-STD-6033 equipment/facility obligations attach "
    "to the producing facility, not to part classification; they are omitted "
    "from this part-level list but are not vacated by [AMR-11]."
)


def _class_applies(
    scope: list[AMPartClass],
    declared: Optional[AMPartClass],
    source_tag: str,
) -> bool:
    if declared is AMPartClass.EXEMPT:
        return source_tag in _EXEMPT_SURVIVING_TAGS
    if not scope:
        return True
    if declared is None:
        # Unknown class: class-scoped requirements stay in view; the result
        # labels them rather than silently dropping them.
        return True
    return declared in scope


def evaluate_applicability(
    store: AMContentStore,
    access: Optional[AccessContext],
    declared_class: Optional[AMPartClass],
) -> ApplicabilityResult:
    """Engine 6.1: applicable requirements + corpus-coverage statement.

    Retrieval is deny-by-default: this function does not catch
    AccessDeniedError -- no access means no applicability answer.
    """
    available = set(store.available_standards(access))
    placeholders = [p.standard_id for p in store.get_placeholders(access)]

    present = [f for f in REQUIRED_DEMO_FAMILIES if f in available]
    missing = [f for f in REQUIRED_DEMO_FAMILIES if f not in available]
    if not present:
        level = CoverageLevel.INSUFFICIENT
    elif missing:
        level = CoverageLevel.PARTIAL
    else:
        level = CoverageLevel.FULL

    coverage = CoverageStatement(
        level=level,
        families_present=present,
        families_missing=missing,
        placeholder_families=placeholders,
        statement=(
            f"Corpus consulted: {', '.join(present) or 'none'}. "
            + (f"Required families missing: {', '.join(missing)}. " if missing else "")
            + (
                f"Controlled families present as inert name-only placeholders "
                f"(not consulted): {', '.join(placeholders)}. "
                if placeholders
                else ""
            )
            + "Absence of a requirement from the ingested corpus is not proof "
            "of non-applicability (Rev 5 §10)."
        ),
    )

    applicable: list[ScopedRequirement] = []
    excluded: list[str] = []
    pack_ids: list[str] = []
    for family in present:
        pack = store.load_pack(family, access)
        pack_ids.append(pack.rule_pack_id)
        for req in pack.requirements:
            scope = derive_class_scope(req.shall_text)
            if _class_applies(scope, declared_class, req.source_tag):
                applicable.append(_scoped(req, pack.standard_id, pack.rule_pack_id, scope))
            else:
                excluded.append(req.requirement_id)

    notes: list[str] = []
    if declared_class is AMPartClass.EXEMPT:
        notes.append(_EXEMPT_6033_NOTE)

    return ApplicabilityResult(
        applicable=applicable,
        excluded_by_class=excluded,
        coverage=coverage,
        rule_pack_ids=pack_ids,
        notes=notes,
    )


def _scoped(
    req: PackRequirement, standard_id: str, rule_pack_id: str, scope: list[AMPartClass]
) -> ScopedRequirement:
    return ScopedRequirement(
        requirement_id=req.requirement_id,
        standard_id=standard_id,
        section=req.section,
        source_tag=req.source_tag,
        page=req.page,
        shall_text=req.shall_text,
        scoped_classes=scope,
        rule_pack_id=rule_pack_id,
    )
