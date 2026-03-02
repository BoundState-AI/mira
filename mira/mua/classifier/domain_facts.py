"""Domain Facts Registry — BS-SPEC-MUA-003 Section 6.

12 curated domain facts. Not a database. Not an LLM knowledge base.
A lookup table. Each entry answers one question that Step 4 needs.

Every fact traces to a specific standard section. No LLM interpolation.

BoundState AI 2026
Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: NASA-STD-6016C w/Change 2, JSC-27301 Rev J
Safety Critical: True
"""

from __future__ import annotations

from pydantic import BaseModel


class DomainFact(BaseModel):
    """A single curated domain fact with provenance."""

    key: str
    fact: str
    source: str
    used_in: str


DOMAIN_FACTS: dict[str, DomainFact] = {
    "FS_TEST_SCOPE": DomainFact(
        key="FS_TEST_SCOPE",
        fact=(
            "Test 15 evaluates compatibility with hydrazine (N2H4), "
            "monomethylhydrazine (MMH), and nitrogen tetroxide (N2O4)."
        ),
        source="JSC-27301 §5.1.3, NASA-STD-6016C §4.2.1.3",
        used_in="Step 4 — determining if FS screening applies to service media",
    ),
    "FLAM_TEST_SCOPE": DomainFact(
        key="FLAM_TEST_SCOPE",
        fact=(
            "Promoted ignition testing per NHB 8060.1C evaluates combustion "
            "behavior in oxygen-enriched environments."
        ),
        source="NHB 8060.1C, NASA-STD-6001B Test 17",
        used_in="Step 4 — determining if FLAM screening applies to service media",
    ),
    "TOX_APPLICABILITY": DomainFact(
        key="TOX_APPLICABILITY",
        fact=(
            "Offgassing requirements per Test 7 apply to nonmetallic materials "
            "in habitable flight compartments only."
        ),
        source="NASA-STD-6016C §4.2.1.2 [MPR 45]",
        used_in="Step 3 — material class gate for TOX flags",
    ),
    "TVS_APPLICABILITY": DomainFact(
        key="TVS_APPLICABILITY",
        fact=(
            "Thermal vacuum stability per ASTM E595 applies to nonmetallic "
            "materials only. Measures outgassing (TML, CVCM, WVR)."
        ),
        source="NASA-STD-6016C §4.2.3.6",
        used_in="Step 3 — material class gate for TVS flags",
    ),
    "H2_IS_HAZARDOUS_FLUID": DomainFact(
        key="H2_IS_HAZARDOUS_FLUID",
        fact=(
            "Hydrogen qualifies as hazardous fluid per footnote 1: fuels that "
            "are critical or catastrophic hazards due to physical degradation."
        ),
        source="NASA-STD-6016C §4.2.1.3 footnote 1",
        used_in="Triggering H2COMPAT companion MUA requirement",
    ),
    "H2_EMBRITTLEMENT_MUA_REQUIRED": DomainFact(
        key="H2_EMBRITTLEMENT_MUA_REQUIRED",
        fact=(
            "MUA SHALL be written rationalizing metallic material selection for "
            "H2 systems to preclude cracking."
        ),
        source="NASA-STD-6016C §4.2.6.4 [MPR 193]",
        used_in="Cross-reference in all screening MUAs for metals in H2 service",
    ),
    "CAT_I_DEFINITION": DomainFact(
        key="CAT_I_DEFINITION",
        fact=(
            "Category I: M&P usage that could affect safety of mission/crew/"
            "vehicle or mission success BUT HAVE TO BE USED for functional "
            "reasons. Two conditions, both required."
        ),
        source="NASA-STD-6016C §4.1.6.1.1",
        used_in="Step 6 — category never applies to screening artifacts",
    ),
    "CAT_II_DEFINITION": DomainFact(
        key="CAT_II_DEFINITION",
        fact=(
            "Category II: M&P usage that fails a screening and is NOT considered "
            "a hazard in its use application."
        ),
        source="NASA-STD-6016C §4.1.6.1.2",
        used_in="Step 6 — all automatable MUAs are Cat II by definition",
    ),
    "FLAM_I_DEFINITION": DomainFact(
        key="FLAM_I_DEFINITION",
        fact=(
            "Rating I = Less than 5 standard samples with burn length of "
            "6.0 inches or less. Incomplete pass, not failure."
        ),
        source="NHB 8060.1C rating criteria (MAPTIS tooltip)",
        used_in="Step 2 — distinguishing I from C",
    ),
    "FLAM_C_DEFINITION": DomainFact(
        key="FLAM_C_DEFINITION",
        fact=(
            "Rating C = Materials that have a burn length greater than "
            "6.0 inches. Actual test failure."
        ),
        source="NHB 8060.1C rating criteria (MAPTIS tooltip)",
        used_in="Step 2 — distinguishing C from I",
    ),
    "B_RATING_MEANING": DomainFact(
        key="B_RATING_MEANING",
        fact=(
            "B = batch/lot testing required. Per retired codes 303/406, "
            "material CAN pass if specific batch is verified. Not automatic pass."
        ),
        source="NASA-STD-6016C Appendix C (retired codes 303, 406)",
        used_in="Step 2 — B-rating handling",
    ),
    "CAT_III_RETIRED": DomainFact(
        key="CAT_III_RETIRED",
        fact=(
            "Category III MUA codes retired as of 6016C Rev A and "
            "JSC-27301 Rev G. Not used for new hardware."
        ),
        source="NASA-STD-6016C §4.1.6.1.3",
        used_in="Historical context for B-rating disposition",
    ),
}


def get_fact(key: str) -> DomainFact:
    """Retrieve a domain fact by key. Raises KeyError if not found."""
    return DOMAIN_FACTS[key]


def get_fact_text(key: str) -> str:
    """Retrieve just the fact text by key. Raises KeyError if not found."""
    return DOMAIN_FACTS[key].fact
