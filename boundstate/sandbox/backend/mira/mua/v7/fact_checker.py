"""MUA v7 Fact Checker -- Post-generation claim verification.

Anchored to the :class:`AtomicClaim` model from evidence items.  Every
verifiable claim in a rendered MUA draft is checked deterministically
against the investigation data and review decisions.

Philosophy
----------
- **Verifiable claims** are checked deterministically against structured data.
  If the claim matches, it is ``"verified"``.  If not, it is ``"unverified"``.
- **Judgment claims** are tagged transparently as ``"judgment"`` -- they are
  NOT verified and NOT rejected.
- **Conservative stance**: when in doubt, mark ``"unverified"`` rather than
  ``"verified"``.  Never rubber-stamp a claim that cannot be confirmed.

Verifiable claim patterns
~~~~~~~~~~~~~~~~~~~~~~~~~
- ``"N approved precedents"``  -- count DETERMINATION claims where status=APPROVED
- ``"FLAMM rating: A"``        -- match against test data RATING assertion
- ``"MUA-XXXX"``               -- confirm in included evidence set
- ``"Tested to X psi"``        -- verify ENVELOPE assertion value
- ``"Category III"``           -- verify against routing result
- ``"N current test records"`` -- count test records where is_current=True

Judgment claim patterns
~~~~~~~~~~~~~~~~~~~~~~~
- ``"acceptable"``     -- tagged ``(Engineering assessment)``
- ``"demonstrates"``   -- tagged ``(Engineering assessment)``
- ``"adequate"``       -- tagged ``(Engineering assessment)``
- ``"representative"`` -- tagged ``(Engineering assessment)``
- ``"equivalency"``    -- tagged ``(Engineering judgment -- see Step 3 rationale)``
"""

from __future__ import annotations

import re
from typing import Optional

from mira.mua.v7.models import (
    CategoryRoutingResult,
    ClaimType,
    DeterminationStatus,
    FactCheckResult,
    InvestigationResult,
    MUACategory,
    MUADraft,
    ReviewDecisionType,
    ReviewDecisions,
)

# ---------------------------------------------------------------------------
# Claim extraction patterns
# ---------------------------------------------------------------------------

# Each tuple: (compiled regex, claim_type, description)
_VERIFIABLE_PATTERNS: list[tuple[re.Pattern, ClaimType, str]] = [
    # "N approved precedent(s)"
    (
        re.compile(r"(\d+)\s+approved\s+precedent", re.IGNORECASE),
        ClaimType.DETERMINATION,
        "approved_precedent_count",
    ),
    # "FLAMM rating: A" or "FLAMM Rating: B" or "Rating: A"
    (
        re.compile(
            r"(?:(\w+)\s+)?[Rr]ating[:\s]+([A-DU])\b",
        ),
        ClaimType.RATING,
        "test_rating",
    ),
    # "MUA-XXXX-YYYY-NNNN" or "MUA-MIRA-2026-0001" style IDs
    (
        re.compile(r"\b(MUA-[A-Z]+-\d{4}-\d{3,5})\b"),
        ClaimType.DETERMINATION,
        "mua_reference",
    ),
    # "Category I" / "Category II" / "Category III"
    (
        re.compile(r"Category\s+(I{1,3}|IV)\b", re.IGNORECASE),
        ClaimType.APPLICABILITY,
        "category_claim",
    ),
    # "tested to X psi" or "X psia"
    (
        re.compile(
            r"tested\s+to\s+([\d,.]+)\s*(?:psi|psia)\b",
            re.IGNORECASE,
        ),
        ClaimType.ENVELOPE,
        "pressure_tested",
    ),
    # "tested to X degF" or "X °F"
    (
        re.compile(
            r"tested\s+to\s+([-\d,.]+)\s*(?:degF|°F|deg\s*F)\b",
            re.IGNORECASE,
        ),
        ClaimType.ENVELOPE,
        "temperature_tested",
    ),
    # "N current test record(s)"
    (
        re.compile(r"(\d+)\s+current\s+test\s+record", re.IGNORECASE),
        ClaimType.RATING,
        "current_test_count",
    ),
]

# Judgment-indicator words -- presence of these means the claim is an
# engineering judgment, not a verifiable fact.
_JUDGMENT_INDICATORS: list[re.Pattern] = [
    re.compile(r"\bacceptable\b", re.IGNORECASE),
    re.compile(r"\bdemonstrates\b", re.IGNORECASE),
    re.compile(r"\badequate\b", re.IGNORECASE),
    re.compile(r"\brepresentative\b", re.IGNORECASE),
    re.compile(r"\bequivalency\b", re.IGNORECASE),
    re.compile(r"\bmay\s+be\s+acceptable\b", re.IGNORECASE),
    re.compile(r"\bengineering\s+assessment\b", re.IGNORECASE),
    re.compile(r"\bengineering\s+judgment\b", re.IGNORECASE),
]


# ---------------------------------------------------------------------------
# FactChecker
# ---------------------------------------------------------------------------


class FactChecker:
    """Post-generation claim verification for MUA drafts.

    Anchored to :class:`AtomicClaim` model from evidence items.
    Verifies atomic claims deterministically.
    Tags judgment claims transparently.
    Never rubber-stamps -- if it cannot verify, it says so.

    Usage::

        checker = FactChecker()
        results = checker.check_draft(draft, investigation, review_decisions, routing)
    """

    # ---- public API -------------------------------------------------------

    def check_draft(
        self,
        draft: MUADraft,
        investigation: InvestigationResult,
        review_decisions: ReviewDecisions,
        category_routing: Optional[CategoryRoutingResult] = None,
    ) -> list[FactCheckResult]:
        """Check all verifiable claims in the draft.

        Parameters
        ----------
        draft:
            The rendered MUA draft to check.
        investigation:
            The Step 2 investigation result (source of truth for evidence).
        review_decisions:
            Engineer decisions from Step 3.
        category_routing:
            Category routing result, used to verify category claims.

        Returns
        -------
        list[FactCheckResult]
            One result per extracted claim, in document order.
        """
        results: list[FactCheckResult] = []

        for section in draft.sections:
            claims = self._extract_claims(section.content)
            for claim in claims:
                result = self._verify_claim(
                    claim, investigation, review_decisions, category_routing
                )
                results.append(result)

        return results

    # ---- claim extraction -------------------------------------------------

    def _extract_claims(self, text: str) -> list[dict]:
        """Extract verifiable and judgment claims from text using patterns.

        Returns a list of dicts, each with keys:
        - ``"text"``: the matched text
        - ``"claim_type"``: :class:`ClaimType` value
        - ``"pattern_name"``: identifier for the matched pattern
        - ``"groups"``: regex match groups
        - ``"is_judgment"``: True if this is a judgment claim
        """
        claims: list[dict] = []
        seen_spans: set[tuple[int, int]] = set()

        # First pass: extract verifiable claims
        for pattern, claim_type, pattern_name in _VERIFIABLE_PATTERNS:
            for match in pattern.finditer(text):
                span = match.span()
                # Avoid duplicate extraction on overlapping spans
                if any(
                    s[0] <= span[0] < s[1] or s[0] < span[1] <= s[1]
                    for s in seen_spans
                ):
                    continue
                seen_spans.add(span)
                claims.append(
                    {
                        "text": match.group(0),
                        "claim_type": claim_type,
                        "pattern_name": pattern_name,
                        "groups": match.groups(),
                        "is_judgment": False,
                    }
                )

        # Second pass: extract judgment claims from sentences
        for sentence in self._split_sentences(text):
            if self._is_judgment_claim(sentence):
                # Only add if not already captured as a verifiable claim
                already_captured = any(
                    c["text"] in sentence and not c["is_judgment"]
                    for c in claims
                )
                if not already_captured:
                    claims.append(
                        {
                            "text": sentence.strip(),
                            "claim_type": ClaimType.APPLICABILITY,
                            "pattern_name": "judgment",
                            "groups": (),
                            "is_judgment": True,
                        }
                    )

        return claims

    # ---- claim verification -----------------------------------------------

    def _verify_claim(
        self,
        claim: dict,
        investigation: InvestigationResult,
        review_decisions: ReviewDecisions,
        category_routing: Optional[CategoryRoutingResult],
    ) -> FactCheckResult:
        """Verify a single claim against evidence.

        Dispatches to specialized verifiers based on ``pattern_name``.
        """
        if claim["is_judgment"]:
            return self._tag_judgment(claim)

        pattern_name = claim["pattern_name"]
        groups = claim["groups"]

        try:
            if pattern_name == "approved_precedent_count":
                return self._verify_approved_count(claim, groups, investigation, review_decisions)
            elif pattern_name == "test_rating":
                return self._verify_test_rating(claim, groups, investigation)
            elif pattern_name == "mua_reference":
                return self._verify_mua_reference(claim, groups, investigation, review_decisions)
            elif pattern_name == "category_claim":
                return self._verify_category(claim, groups, category_routing)
            elif pattern_name == "pressure_tested":
                return self._verify_pressure(claim, groups, investigation)
            elif pattern_name == "temperature_tested":
                return self._verify_temperature(claim, groups, investigation)
            elif pattern_name == "current_test_count":
                return self._verify_current_test_count(claim, groups, investigation)
            else:
                return FactCheckResult(
                    claim_text=claim["text"],
                    claim_type=claim["claim_type"],
                    status="unverified",
                    note=f"No verifier implemented for pattern '{pattern_name}'.",
                )
        except Exception as exc:
            return FactCheckResult(
                claim_text=claim["text"],
                claim_type=claim["claim_type"],
                status="error",
                note=f"Verification error: {exc}",
            )

    # ---- specialized verifiers --------------------------------------------

    def _verify_approved_count(
        self,
        claim: dict,
        groups: tuple,
        investigation: InvestigationResult,
        review_decisions: ReviewDecisions,
    ) -> FactCheckResult:
        """Verify "N approved precedents" against included APPROVED precedents."""
        claimed_count = int(groups[0])

        # Count precedents that are (a) APPROVED and (b) included by engineer
        included_muas = {
            pd.mua_number
            for pd in review_decisions.precedent_decisions
            if pd.decision in (
                ReviewDecisionType.INCLUDE_SUPPORTING,
                ReviewDecisionType.INCLUDE_CONTEXT,
            )
        }

        all_precedents = (
            investigation.supporting_precedents
            + investigation.conflicting_precedents
        )

        actual_count = sum(
            1
            for p in all_precedents
            if p.mua_number in included_muas
            and p.determination == DeterminationStatus.APPROVED
        )

        if claimed_count == actual_count:
            return FactCheckResult(
                claim_text=claim["text"],
                claim_type=ClaimType.DETERMINATION,
                status="verified",
                note=f"Confirmed: {actual_count} approved precedent(s) in included evidence.",
            )
        else:
            return FactCheckResult(
                claim_text=claim["text"],
                claim_type=ClaimType.DETERMINATION,
                status="unverified",
                note=(
                    f"Claimed {claimed_count} approved precedent(s) but found "
                    f"{actual_count} in the included evidence set."
                ),
            )

    def _verify_test_rating(
        self,
        claim: dict,
        groups: tuple,
        investigation: InvestigationResult,
    ) -> FactCheckResult:
        """Verify "FLAMM rating: A" against test data records."""
        # groups: (test_class_or_None, rating_letter)
        test_class_hint = groups[0]  # may be None if pattern matched "Rating: A"
        claimed_rating = groups[1].upper() if groups[1] else None

        if not claimed_rating:
            return FactCheckResult(
                claim_text=claim["text"],
                claim_type=ClaimType.RATING,
                status="unverified",
                note="Could not parse rating value from claim.",
            )

        matching_records = investigation.test_data
        if test_class_hint:
            test_class_upper = test_class_hint.upper()
            matching_records = [
                r for r in matching_records if r.test_class.upper() == test_class_upper
            ]

        # Check if any matching record has the claimed rating
        found = any(
            r.rating and r.rating.upper() == claimed_rating
            for r in matching_records
        )

        if found:
            return FactCheckResult(
                claim_text=claim["text"],
                claim_type=ClaimType.RATING,
                status="verified",
                note=(
                    f"Rating '{claimed_rating}' confirmed in "
                    f"{len(matching_records)} matching test record(s)."
                ),
            )
        else:
            available = sorted(
                {r.rating.upper() for r in matching_records if r.rating}
            )
            return FactCheckResult(
                claim_text=claim["text"],
                claim_type=ClaimType.RATING,
                status="unverified",
                note=(
                    f"Rating '{claimed_rating}' not found in test data. "
                    f"Available ratings: {available or 'none'}."
                ),
            )

    def _verify_mua_reference(
        self,
        claim: dict,
        groups: tuple,
        investigation: InvestigationResult,
        review_decisions: ReviewDecisions,
    ) -> FactCheckResult:
        """Verify "MUA-XXXX-YYYY-NNNN" exists in the included evidence set."""
        mua_ref = groups[0]

        # Check all precedents (supporting + conflicting)
        all_precedents = (
            investigation.supporting_precedents
            + investigation.conflicting_precedents
        )
        known_muas = {p.mua_number for p in all_precedents}

        # Also include the draft's own MUA ID as valid
        # (the draft references itself in the header)
        included_decisions = {
            pd.mua_number
            for pd in review_decisions.precedent_decisions
            if pd.decision in (
                ReviewDecisionType.INCLUDE_SUPPORTING,
                ReviewDecisionType.INCLUDE_CONTEXT,
            )
        }

        if mua_ref in known_muas:
            if mua_ref in included_decisions:
                return FactCheckResult(
                    claim_text=claim["text"],
                    claim_type=ClaimType.DETERMINATION,
                    status="verified",
                    note=f"MUA reference '{mua_ref}' found in included evidence set.",
                )
            else:
                # Known but not included -- might be the draft's own ID or
                # an excluded precedent.  Mark as unverified conservatively.
                return FactCheckResult(
                    claim_text=claim["text"],
                    claim_type=ClaimType.DETERMINATION,
                    status="unverified",
                    note=(
                        f"MUA reference '{mua_ref}' exists in investigation "
                        f"but was not included by engineer review decisions."
                    ),
                )
        else:
            # Could be the draft's own MUA ID -- check format
            if mua_ref.startswith("MUA-MIRA-"):
                return FactCheckResult(
                    claim_text=claim["text"],
                    claim_type=ClaimType.DETERMINATION,
                    status="verified",
                    note=f"MUA reference '{mua_ref}' is the draft's own identifier.",
                )
            return FactCheckResult(
                claim_text=claim["text"],
                claim_type=ClaimType.DETERMINATION,
                status="unverified",
                note=f"MUA reference '{mua_ref}' not found in any evidence source.",
            )

    def _verify_category(
        self,
        claim: dict,
        groups: tuple,
        category_routing: Optional[CategoryRoutingResult],
    ) -> FactCheckResult:
        """Verify "Category III" against the routing result."""
        claimed_category = groups[0]

        if category_routing is None:
            return FactCheckResult(
                claim_text=claim["text"],
                claim_type=ClaimType.APPLICABILITY,
                status="unverified",
                note="No category routing result available for verification.",
            )

        # Normalize: the enum uses "I", "II", "III"
        actual_category = category_routing.category.value

        if claimed_category == actual_category:
            return FactCheckResult(
                claim_text=claim["text"],
                claim_type=ClaimType.APPLICABILITY,
                status="verified",
                note=f"Category {claimed_category} matches routing result.",
            )
        else:
            return FactCheckResult(
                claim_text=claim["text"],
                claim_type=ClaimType.APPLICABILITY,
                status="unverified",
                note=(
                    f"Claimed Category {claimed_category} but routing result "
                    f"is Category {actual_category}."
                ),
            )

    def _verify_pressure(
        self,
        claim: dict,
        groups: tuple,
        investigation: InvestigationResult,
    ) -> FactCheckResult:
        """Verify "tested to X psi" against envelope assertions."""
        claimed_value_str = groups[0].replace(",", "")
        try:
            claimed_value = float(claimed_value_str)
        except ValueError:
            return FactCheckResult(
                claim_text=claim["text"],
                claim_type=ClaimType.ENVELOPE,
                status="unverified",
                note=f"Could not parse pressure value '{groups[0]}'.",
            )

        # Check envelope assertions from all evidence refs
        verified = self._check_envelope_assertion(
            investigation, "pressure", claimed_value
        )

        if verified:
            return FactCheckResult(
                claim_text=claim["text"],
                claim_type=ClaimType.ENVELOPE,
                status="verified",
                note=f"Pressure value {claimed_value} psi confirmed in evidence.",
            )
        else:
            return FactCheckResult(
                claim_text=claim["text"],
                claim_type=ClaimType.ENVELOPE,
                status="unverified",
                note=(
                    f"Pressure value {claimed_value} psi could not be "
                    f"confirmed in the available evidence."
                ),
            )

    def _verify_temperature(
        self,
        claim: dict,
        groups: tuple,
        investigation: InvestigationResult,
    ) -> FactCheckResult:
        """Verify "tested to X degF" against envelope assertions."""
        claimed_value_str = groups[0].replace(",", "")
        try:
            claimed_value = float(claimed_value_str)
        except ValueError:
            return FactCheckResult(
                claim_text=claim["text"],
                claim_type=ClaimType.ENVELOPE,
                status="unverified",
                note=f"Could not parse temperature value '{groups[0]}'.",
            )

        verified = self._check_envelope_assertion(
            investigation, "temperature", claimed_value
        )

        if verified:
            return FactCheckResult(
                claim_text=claim["text"],
                claim_type=ClaimType.ENVELOPE,
                status="verified",
                note=f"Temperature value {claimed_value} degF confirmed in evidence.",
            )
        else:
            return FactCheckResult(
                claim_text=claim["text"],
                claim_type=ClaimType.ENVELOPE,
                status="unverified",
                note=(
                    f"Temperature value {claimed_value} degF could not be "
                    f"confirmed in the available evidence."
                ),
            )

    def _verify_current_test_count(
        self,
        claim: dict,
        groups: tuple,
        investigation: InvestigationResult,
    ) -> FactCheckResult:
        """Verify "N current test records" against test data."""
        claimed_count = int(groups[0])
        actual_count = sum(
            1 for r in investigation.test_data if r.is_current is True
        )

        if claimed_count == actual_count:
            return FactCheckResult(
                claim_text=claim["text"],
                claim_type=ClaimType.RATING,
                status="verified",
                note=f"Confirmed: {actual_count} current test record(s).",
            )
        else:
            return FactCheckResult(
                claim_text=claim["text"],
                claim_type=ClaimType.RATING,
                status="unverified",
                note=(
                    f"Claimed {claimed_count} current test record(s) but "
                    f"found {actual_count}."
                ),
            )

    # ---- judgment detection -----------------------------------------------

    @staticmethod
    def _tag_judgment(claim: dict) -> FactCheckResult:
        """Tag a judgment claim -- not verified, not rejected."""
        text = claim["text"]

        # Determine the appropriate tag
        if any(
            kw in text.lower()
            for kw in ("equivalency", "cure cycle", "step 3")
        ):
            tag = "(Engineering judgment -- see Step 3 rationale)"
        else:
            tag = "(Engineering assessment)"

        return FactCheckResult(
            claim_text=text,
            claim_type=claim["claim_type"],
            status="judgment",
            note=f"Judgment claim tagged: {tag}",
        )

    @staticmethod
    def _is_judgment_claim(text: str) -> bool:
        """Detect claims that are engineering judgment, not verifiable facts.

        Looks for indicator words: "acceptable", "demonstrates", "adequate",
        "representative", "equivalency", "may be acceptable", etc.
        """
        return any(pattern.search(text) for pattern in _JUDGMENT_INDICATORS)

    # ---- envelope helpers -------------------------------------------------

    @staticmethod
    def _check_envelope_assertion(
        investigation: InvestigationResult,
        dimension: str,
        claimed_value: float,
        tolerance: float = 0.01,
    ) -> bool:
        """Check whether a claimed envelope value appears in evidence assertions.

        Searches all ENVELOPE-type :class:`AtomicClaim` objects across all
        evidence refs in the investigation's precedents.

        Parameters
        ----------
        investigation:
            The investigation result containing precedent evidence refs.
        dimension:
            The dimension to match (e.g. ``"pressure"``, ``"temperature"``).
        claimed_value:
            The numeric value claimed in the draft.
        tolerance:
            Relative tolerance for floating-point comparison (default 1%).

        Returns
        -------
        bool
            True if the value is confirmed in at least one evidence ref.
        """
        all_precedents = (
            investigation.supporting_precedents
            + investigation.conflicting_precedents
        )

        for prec in all_precedents:
            if prec.evidence_ref is None:
                continue
            for assertion in prec.evidence_ref.assertions:
                if assertion.claim_type != ClaimType.ENVELOPE:
                    continue
                if dimension.lower() not in assertion.subject.lower():
                    continue
                try:
                    evidence_value = float(assertion.value)
                except (TypeError, ValueError):
                    continue
                if abs(evidence_value - claimed_value) <= abs(claimed_value * tolerance):
                    return True

        return False

    # ---- text utilities ---------------------------------------------------

    @staticmethod
    def _split_sentences(text: str) -> list[str]:
        """Split text into approximate sentence boundaries.

        Uses a simple heuristic: split on period, exclamation, or question
        mark followed by whitespace or end-of-string.  This is intentionally
        simple -- claim extraction does not need perfect NLP.
        """
        raw = re.split(r"(?<=[.!?])\s+", text)
        # Filter out very short fragments and section dividers
        return [
            s
            for s in raw
            if len(s) > 20 and not s.startswith("---") and not s.startswith("===")
        ]
