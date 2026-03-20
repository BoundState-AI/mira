"""Rationale & Disposition Template Engine — BS-SPEC-MUA-003 Steps 7-8.

Template-based rationale and disposition generation. Each MUA type has
a fixed sentence structure. Templates take the decoded flag meaning
from Step 2 and the environment facts from Step 4 and combine them.

Rules (from spec):
1. Never self-referential. Every claim traces to a standard section.
2. State the gap, then close the gap.
3. Cross-reference companion MUAs for H2 hardware.
4. Use correct rating definitions per column.
5. Terse. The reviewer reads dozens of these — respect their time.

BoundState AI 2026
Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: NASA-STD-6016C w/Change 2, JSC-27301 Rev J
Safety Critical: True
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING, Optional

from .domain_facts import DOMAIN_FACTS
from .models import (
    ClassifierResult,
    MUAGroup,
    MUAType,
    RATING_SEMANTICS,
)

if TYPE_CHECKING:
    from mira.mua.precedent.models import PrecedentSummary
    from mira.mua.evidence.models import EvidenceBundle
    from mira.mua.synthesis.models import Claim, SynthesisResult

LOGGER = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Decoded meaning lookups (precise per-column wording)
# ---------------------------------------------------------------------------

_DECODED_MEANINGS: dict[tuple[str, str], str] = {
    # FLAM
    ("FLAM", "C"): (
        "test specimens exhibited a burn length greater than 6.0 inches "
        "under standard promoted combustion conditions in oxygen-enriched "
        "environments per NHB 8060.1C"
    ),
    ("FLAM", "I"): (
        "fewer than 5 standard samples were tested, but all tested samples "
        "had burn length at or below 6.0 inches. The I designation reflects "
        "incomplete sample count, not a test failure"
    ),
    ("FLAM", "U"): "no usable test data exists per NHB 8060.1C",
    # FS
    ("FS", "U"): (
        "no test data exists in MAPTIS for the NASA-STD-6001B Test 15 screening"
    ),
    # TOX
    ("TOX", "U"): "untested for offgassing per NASA-STD-6001B Test 7",
    # SCC
    ("SCC", "C"): (
        "susceptibility to stress corrosion cracking under certain conditions"
    ),
    # TVS
    ("TVS", "C"): "failure to meet ASTM E595 outgassing criteria",
}


def _get_decoded_meaning(column: str, rating: str) -> str:
    """Get precise decoded meaning for rationale text."""
    key = (column.upper(), rating.upper())
    meaning = _DECODED_MEANINGS.get(key)
    if meaning:
        return meaning
    semantics = RATING_SEMANTICS.get(key)
    if semantics:
        return semantics.meaning
    return f"rating {rating} for {column}"


# ---------------------------------------------------------------------------
# Test scope facts (used in THIN_SCREENING template)
# ---------------------------------------------------------------------------

_TEST_SCOPE_FACTS: dict[str, str] = {
    "FS": (
        "Test 15 is a 48-hour screening test designed to evaluate material "
        "compatibility with hydrazine (N2H4), monomethylhydrazine (MMH), "
        "and nitrogen tetroxide (N2O4) class propellants"
    ),
    "FLAM": (
        "Promoted ignition testing per NHB 8060.1C evaluates combustion "
        "behavior in oxygen-enriched environments"
    ),
    "TOX": (
        "Test 7 (offgassing) per NASA-STD-6001B applies to nonmetallic "
        "materials in habitable flight compartments per MPR 45"
    ),
    "TVS": (
        "ASTM E595 thermal vacuum stability testing applies to nonmetallic "
        "materials for outgassing evaluation"
    ),
}

# Failure mode descriptions (used in ANTI_RULE template)
_FAILURE_MODES: dict[str, str] = {
    "FLAM": "promoted ignition and sustained combustion propagation in enriched oxygen",
    "SCC": "stress corrosion cracking in aqueous or corrosive environments",
    "TVS": "outgassing exceeding ASTM E595 criteria under vacuum",
    "CORR": "corrosion in the presence of moisture or reactive media",
}

# Column to standard/MPR mapping
_COLUMN_STANDARD_REF: dict[str, str] = {
    "FLAM": "NASA-STD-6016C §4.2.1.1 [MPR 44]",
    "FS": "NASA-STD-6016C §4.2.1.3 [MPR 47]",
    "TOX": "NASA-STD-6016C §4.2.1.2 [MPR 45]",
    "TVS": "NASA-STD-6016C §4.2.3.6",
    "SCC": "NASA-STD-6016C §4.2.6.3",
    "CORR": "NASA-STD-6016C §4.2.6.2",
}

# Column display name helper
_COLUMN_DISPLAY_NAMES: dict[str, str] = {
    "FLAM": "promoted ignition",
    "FS": "fluid system compatibility",
    "TOX": "offgassing",
    "TVS": "thermal vacuum stability",
    "SCC": "stress corrosion cracking",
    "CORR": "corrosion",
}


def _column_display_name(column: str) -> str:
    return _COLUMN_DISPLAY_NAMES.get(column.upper(), column)


def precedent_suffix(precedent: Optional["PrecedentSummary"]) -> str:
    """One-sentence precedent citation to append to rationale text."""
    if precedent is None or precedent.total_count < 5 or precedent.approved_count <= 0:
        return ""

    issue_name = _column_display_name(precedent.issue)
    if precedent.alloy_family:
        family_text = precedent.alloy_family.replace("_", " ")
        subject = family_text
    elif precedent.material_class == "metal":
        subject = "metals"
    elif precedent.material_class == "nonmetallic":
        subject = "nonmetallic materials"
    else:
        subject = "similar materials"

    if precedent.media_category and precedent.media_category != "any":
        media_phrase = f"in {precedent.media_category} service"
    else:
        media_phrase = "across comparable service environments"

    if precedent.has_strong_precedent and precedent.most_common_category:
        return (
            f"This disposition is consistent with {precedent.approved_count} prior approved "
            f"Category {precedent.most_common_category} MUAs for {issue_name} screening of "
            f"{subject} {media_phrase}."
        )
    return (
        f"This disposition is consistent with {precedent.approved_count} prior approved MUAs "
        f"for {issue_name} screening of {subject} {media_phrase}."
    )


_STANDARD_REF_PATTERN = re.compile(
    r"(NASA-STD-\d+[A-Z]?|NHB\s*\d+\.\d+[A-Z]?|ASTM\s*[A-Z]\d+|JSC-\d+)",
    flags=re.IGNORECASE,
)


def _known_standard_refs() -> set[str]:
    refs: set[str] = set()
    for fact in DOMAIN_FACTS.values():
        for text in (fact.source, fact.fact):
            for match in _STANDARD_REF_PATTERN.findall(text):
                refs.add(match.upper().replace(" ", ""))
    return refs


def verify_claims(
    synthesis: "SynthesisResult",
    evidence: "EvidenceBundle",
) -> tuple[list["Claim"], list["Claim"]]:
    """Verify each claim in the synthesis traces to evidence.

    Returns (verified_claims, blocked_claims).
    """
    exemplar_ids = {ex.mua_number for ex in (evidence.exemplars or [])}
    domain_fact_keys = set(DOMAIN_FACTS.keys())
    standard_refs = _known_standard_refs()

    verified: list["Claim"] = []
    blocked: list["Claim"] = []

    for claim in synthesis.claims:
        source_type = str(claim.source_type or "").strip().lower()
        source_mua = str(claim.source_mua or "").strip()
        claim_text = str(claim.text or "")

        if source_type == "precedent":
            if source_mua in exemplar_ids:
                verified.append(claim)
            else:
                blocked.append(claim)
            continue

        if source_type == "template":
            verified.append(claim)
            continue

        if source_type == "domain_fact":
            if source_mua in domain_fact_keys:
                verified.append(claim)
            else:
                blocked.append(claim)
            continue

        if source_type == "standard":
            normalized = (f"{claim_text} {source_mua}").upper().replace(" ", "")
            if any(ref in normalized for ref in standard_refs):
                verified.append(claim)
            else:
                blocked.append(claim)
            continue

        blocked.append(claim)

    if blocked:
        LOGGER.warning(
            "Claim verification blocked %d claim(s): %s",
            len(blocked),
            ", ".join(f"{c.source_type}:{c.source_mua}" for c in blocked[:5]),
        )

    return verified, blocked


# ---------------------------------------------------------------------------
# Template: THIN_SCREENING (NO_DATA + hazard_applies=False)
# ---------------------------------------------------------------------------

def _render_thin_screening(
    material_name: str,
    maptis_code: str,
    column: str,
    rating: str,
    media: str,
    companion_ref: str | None = None,
) -> str:
    meaning = _get_decoded_meaning(column, rating)
    test_scope = _TEST_SCOPE_FACTS.get(column.upper(), f"the applicable screening test for {column}")
    col_upper = column.upper()

    lines = [
        f"{material_name} (MAPTIS {maptis_code}) has a {_column_display_name(col_upper)} "
        f"rating of {rating}, indicating {meaning}.",
        f"{test_scope}. This material is not in service with the fluids "
        f"for which this screening was designed; the operating medium is {media}.",
    ]

    if companion_ref:
        lines.append(
            f"{media} compatibility is addressed under {companion_ref}."
        )
    else:
        lines.append(
            f"The {col_upper}={rating} rating does not represent a deficiency "
            f"for {media} service."
        )

    return " ".join(lines)


# ---------------------------------------------------------------------------
# Template: ANTI_RULE (REAL_FAIL + hazard_applies=False)
# ---------------------------------------------------------------------------

def _render_anti_rule(
    material_name: str,
    maptis_code: str,
    column: str,
    rating: str,
    media: str,
    companion_ref: str | None = None,
) -> str:
    meaning = _get_decoded_meaning(column, rating)
    col_upper = column.upper()
    failure_mode = _FAILURE_MODES.get(col_upper, f"the failure mode for {col_upper}")
    standard_ref = _COLUMN_STANDARD_REF.get(col_upper, "NASA-STD-6016C")

    lines = [
        f"{material_name} (MAPTIS {maptis_code}) carries a "
        f"{_column_display_name(col_upper)} rating of {rating}, indicating {meaning}.",
    ]

    if col_upper == "FLAM":
        lines.append(
            f"This rating is not applicable to the actual service environment. "
            f"The material operates exclusively in {media} media with no "
            f"oxygen-enriched atmosphere. The failure mode underlying the {rating} "
            f"rating — {failure_mode} — is not credible in a {media} fluid system. "
            f"The flammability screening requirement per {standard_ref} is satisfied "
            f"because the hazard condition does not exist at the point of use."
        )
    elif col_upper == "SCC":
        lines.append(
            f"This rating is not applicable to the actual service environment. "
            f"The material operates in {media} service. {failure_mode.capitalize()} "
            f"requires aqueous environment or specific corrodents, which are not "
            f"present in clean {media} systems."
        )
    else:
        lines.append(
            f"The failure mode underlying the {rating} rating — {failure_mode} — "
            f"is not credible in {media} service for this application."
        )

    if companion_ref:
        lines.append(
            f"{media} compatibility is addressed under {companion_ref}."
        )

    return " ".join(lines)


# ---------------------------------------------------------------------------
# Template: INCOMPLETE_PASS (ADMIN_GAP, any hazard_applies)
# ---------------------------------------------------------------------------

def _render_incomplete_pass(
    material_name: str,
    maptis_code: str,
    column: str,
    rating: str,
    media: str,
    companion_ref: str | None = None,
    hazard_applies: bool | None = None,
) -> str:
    meaning = _get_decoded_meaning(column, rating)
    col_upper = column.upper()

    lines = [
        f"{material_name} (MAPTIS {maptis_code}) carries a "
        f"{_column_display_name(col_upper)} rating of {rating}. "
        f"{meaning[0].upper() + meaning[1:]}.",
        f"The existing test data is favorable. All tested specimens met "
        f"acceptance criteria. The rating deficiency is administrative "
        f"rather than technical.",
    ]

    if col_upper == "FLAM":
        if hazard_applies:
            # Hazard IS present — incompleteness is the point, don't deny O2.
            # Per Beth's review: say "insufficient", not just "favorable".
            lines.append(
                f"Fewer than 5 standard samples have been tested per "
                f"NHB 8060.1C. While all tested specimens met acceptance "
                f"criteria, the sample count is insufficient to confirm "
                f"oxygen compatibility per NASA-STD-6016C §4.2.1.4. M&P "
                f"engineer review is required to determine whether "
                f"additional promoted ignition testing is warranted for "
                f"this oxygen-enriched application."
            )
        else:
            lines.append(
                f"Furthermore, promoted ignition is not applicable to the "
                f"actual service environment. The material operates in "
                f"{media} media with no oxygen-enriched atmosphere."
            )
    else:
        lines.append(
            f"The screening condition assessed by this test is not the primary "
            f"concern for {media} service."
        )

    if companion_ref:
        lines.append(
            f"{media} compatibility is addressed under {companion_ref}."
        )

    return " ".join(lines)


# ---------------------------------------------------------------------------
# Template: REAL_PROBLEM / REAL_GAP (human-required types)
# ---------------------------------------------------------------------------

def _render_human_required(
    material_name: str,
    maptis_code: str,
    column: str,
    rating: str,
    media: str,
    mua_type: MUAType,
) -> str:
    meaning = _get_decoded_meaning(column, rating)
    col_upper = column.upper()

    if mua_type == MUAType.REAL_PROBLEM:
        return (
            f"{material_name} (MAPTIS {maptis_code}): {col_upper}={rating}, "
            f"indicating {meaning}. The failure mode IS credible in {media} service. "
            f"Requires engineering judgment for disposition. "
            f"Cannot generate rationale automatically."
        )
    else:  # REAL_GAP
        return (
            f"{material_name} (MAPTIS {maptis_code}): {col_upper}={rating}, "
            f"indicating {meaning}. This gap is relevant to the actual service "
            f"environment ({media}). No existing test data addresses this "
            f"compatibility concern. Testing per the applicable standard is "
            f"recommended. Conditional acceptance pending qualification testing."
        )


# ---------------------------------------------------------------------------
# Template: STANDARD (no MUA needed)
# ---------------------------------------------------------------------------

def _render_standard(
    material_name: str,
    maptis_code: str,
    column: str,
    rating: str,
) -> str:
    if rating.upper() == "A":
        return (
            f"{material_name} (MAPTIS {maptis_code}) has a {column} rating of A, "
            f"indicating full compliance with screening requirements. No MUA required."
        )
    if rating.upper() == "B":
        return (
            f"{material_name} (MAPTIS {maptis_code}) has a {column} rating of B "
            f"with documented batch/lot verification. Material meets requirements "
            f"for the verified batch."
        )
    return f"{material_name} (MAPTIS {maptis_code}): {column}={rating}. Standard disposition."


# ---------------------------------------------------------------------------
# Public API: render_rationale
# ---------------------------------------------------------------------------


def render_rationale(
    result: ClassifierResult | MUAGroup,
    material_name: str | None = None,
) -> str:
    """Render the rationale text for a classified MUA (Step 7).

    Parameters
    ----------
    result
        Either a ClassifierResult or an MUAGroup.
    material_name
        Override for human-readable material name.

    Returns
    -------
    str
        Rationale text suitable for the Form 551 rationale field.
    """
    if isinstance(result, MUAGroup):
        name = material_name or result.material_designation
        maptis_code = result.maptis_code
        column = result.issue_key
        rating = result.rating
        media = result.media
        mua_type = result.mua_type
        companion_ref = result.companion_mua_ref
        precedent = None
        hazard_applies = None
    else:
        name = material_name or result.maptis_code
        maptis_code = result.maptis_code
        column = result.issue_key
        rating = result.rating
        media = result.media
        mua_type = result.mua_type
        companion_ref = result.companion_mua_ref
        precedent = result.precedent
        hazard_applies = result.hazard_applies

    if mua_type == MUAType.THIN_SCREENING:
        rationale_text = _render_thin_screening(name, maptis_code, column, rating, media, companion_ref)
    elif mua_type == MUAType.ANTI_RULE:
        rationale_text = _render_anti_rule(name, maptis_code, column, rating, media, companion_ref)
    elif mua_type == MUAType.INCOMPLETE_PASS:
        rationale_text = _render_incomplete_pass(name, maptis_code, column, rating, media, companion_ref, hazard_applies)
    elif mua_type in (MUAType.REAL_PROBLEM, MUAType.REAL_GAP):
        rationale_text = _render_human_required(name, maptis_code, column, rating, media, mua_type)
    elif mua_type == MUAType.STANDARD:
        rationale_text = _render_standard(name, maptis_code, column, rating)
    else:
        rationale_text = (
            f"{name} (MAPTIS {maptis_code}): {column}={rating}. "
            f"Requires engineering judgment. Cannot generate rationale automatically."
        )

    suffix = precedent_suffix(precedent)
    if suffix:
        return f"{rationale_text} {suffix}"
    return rationale_text


# ---------------------------------------------------------------------------
# Public API: render_disposition (Step 8 — disposition field)
# ---------------------------------------------------------------------------


def render_disposition(
    result: ClassifierResult | MUAGroup,
) -> str:
    """Render the disposition text for the Form 551 disposition field.

    Per BS-SPEC-MUA-003 Section 3, Step 8.
    """
    if isinstance(result, MUAGroup):
        mua_type = result.mua_type
        column = result.issue_key
        rating = result.rating
        media = result.media
        companion_ref = result.companion_mua_ref
    else:
        mua_type = result.mua_type
        column = result.issue_key
        rating = result.rating
        media = result.media
        companion_ref = result.companion_mua_ref

    if mua_type == MUAType.THIN_SCREENING:
        base = (
            f"Accepted. {column}={rating} reflects absence of screening data "
            f"for fluids not present in this application. Material is not in "
            f"contact with those fluids."
        )
        if companion_ref:
            return f"{base} Actual service compatibility addressed under companion MUA. No additional testing required."
        else:
            return f"{base} No additional testing required."
    elif mua_type == MUAType.ANTI_RULE:
        return (
            f"Accepted. The screening failure does not constitute a hazard in "
            f"this application. Material operates in {media} with no conditions "
            f"that would activate the failure mode. No additional testing or "
            f"controls required for this screening deficiency."
        )
    elif mua_type == MUAType.INCOMPLETE_PASS:
        return (
            f"Accepted. {column}={rating} reflects incomplete sample count, "
            f"not a test failure; all tested specimens passed with results "
            f"within acceptance criteria. No additional testing required."
        )
    elif mua_type == MUAType.REAL_PROBLEM:
        return (
            "PENDING ENGINEERING REVIEW — Material fails relevant screening "
            "and hazard is credible in this application. Requires engineer "
            "disposition."
        )
    elif mua_type == MUAType.REAL_GAP:
        return (
            "DEFERRED — Real gap requiring testing/qualification plan. "
            "No test data exists for a relevant screening."
        )
    elif mua_type == MUAType.STANDARD:
        return "NO MUA REQUIRED — Material meets screening requirements."
    else:
        return "PENDING ENGINEERING REVIEW — Cannot disposition automatically."
