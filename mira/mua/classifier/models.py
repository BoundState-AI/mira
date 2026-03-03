"""MUA Classifier Data Models — BS-SPEC-MUA-003.

Flag-first stepwise data models for the deterministic MUA classifier.
An MUA is a response to a FLAG, not to a material. MAPTIS raised a flag.
The MUA answers: is that flag valid in this application?

Encodes:
- FlagType intermediate taxonomy (REAL_FAIL, ADMIN_GAP, NO_DATA, etc.)
- Material class distinctions (metal vs nonmetallic)
- MUA type taxonomy (THIN_SCREENING, ANTI_RULE, INCOMPLETE_PASS, REAL_PROBLEM, REAL_GAP)
- Category definitions per 6016C section 4.1.6.1
- MAPTIS rating semantics per column (FLAM, FS, TOX, SCC, CORR, TVS)
- MSFC Form 551 field structure

Supersedes: BS-SPEC-MUA-002 models (architecture was material-first instead of flag-first)

BoundState AI 2026
Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: NASA-STD-6016C w/Change 2, JSC-27301 Rev J
Safety Critical: True
"""

from __future__ import annotations

from enum import Enum
from typing import TYPE_CHECKING, Any, Optional

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from mira.mua.precedent.models import PrecedentSummary
    from mira.mua.evidence.models import EvidenceBundle
    from mira.mua.synthesis.models import SynthesisResult
else:
    PrecedentSummary = Any
    EvidenceBundle = Any
    SynthesisResult = Any


# ---------------------------------------------------------------------------
# Material Classification
# ---------------------------------------------------------------------------


class MaterialClassEnum(str, Enum):
    """High-level material class for screening applicability.

    The classifier only needs to distinguish metal from nonmetallic
    for the material-class gate. Finer distinctions (polymer, elastomer,
    etc.) are handled downstream.
    """

    METAL = "metal"
    NONMETALLIC = "nonmetallic"


# ---------------------------------------------------------------------------
# Flag Type — Step 2 output (BS-SPEC-MUA-003 Section 3, Step 2)
# ---------------------------------------------------------------------------


class FlagType(str, Enum):
    """Intermediate flag taxonomy from decoding a MAPTIS rating.

    Step 2 of the pipeline decodes each (column, rating) pair into
    a FlagType using the column-specific dictionary. This is the
    intermediate representation between "what letter is it?" and
    "what type of MUA does it need?"
    """

    NO_FLAG = "NO_FLAG"
    """Rating A or N — pass. No MUA needed for this column."""

    REAL_FAIL = "REAL_FAIL"
    """Material actually failed the test (e.g., FLAM=C burn >6 inches).
    Needs environment check to determine if failure mode is credible."""

    ADMIN_GAP = "ADMIN_GAP"
    """Favorable data exists but is administratively insufficient
    (e.g., FLAM=I — <5 samples, all passing)."""

    NO_DATA = "NO_DATA"
    """No test data exists (e.g., FS=U — never tested against hydrazine).
    Needs environment check to determine if the test is even relevant."""

    BATCH_REQUIRED = "BATCH_REQUIRED"
    """Rating B — batch/lot testing required. If batch verified, no MUA.
    If not verified, route to human."""

    BAD_DATA = "BAD_DATA"
    """Rating is undocumented/corrupt (e.g., TOX=K). MIUL builder artifact.
    Route to human immediately. Tool cannot proceed."""

    MISSING_DATA = "MISSING_DATA"
    """No entry in MAPTIS (blank/None). Unknown status.
    Route to human immediately."""

    NEEDS_REVIEW = "NEEDS_REVIEW"
    """Special test or context-dependent rating (e.g., FLAM=S).
    Need to review actual test report. Route to human."""


# ---------------------------------------------------------------------------
# MUA Type — The classifier output (Step 5)
# ---------------------------------------------------------------------------


class MUAType(str, Enum):
    """MUA type as determined by the flag_type + hazard_applies matrix.

    Per BS-SPEC-MUA-003 Section 3, Step 5:
    - Three automatable types (THIN_SCREENING, ANTI_RULE, INCOMPLETE_PASS)
    - Two human-required types (REAL_PROBLEM, REAL_GAP)
    - One non-MUA type (STANDARD)
    - Legacy FLAG_FOR_HUMAN retained for B-rating / BAD_DATA / MISSING_DATA
    """

    THIN_SCREENING = "THIN_SCREENING"
    """flag_type=NO_DATA + hazard_applies=False.
    E.g., FS=U in H2 service (Test 15 covers hydrazine, not H2).
    Category II. Automatable."""

    ANTI_RULE = "ANTI_RULE"
    """flag_type=REAL_FAIL + hazard_applies=False.
    E.g., FLAM=C in H2 with no O2 enrichment.
    Category II. Automatable."""

    INCOMPLETE_PASS = "INCOMPLETE_PASS"
    """flag_type=ADMIN_GAP (regardless of hazard_applies).
    E.g., FLAM=I — <5 samples, all passing.
    Category II. Automatable."""

    REAL_PROBLEM = "REAL_PROBLEM"
    """flag_type=REAL_FAIL + hazard_applies=True.
    Material actually fails a relevant screening. Needs engineer.
    Category I. NOT automatable."""

    REAL_GAP = "REAL_GAP"
    """flag_type=NO_DATA + hazard_applies=True.
    No test data and the test is actually relevant. Needs test plan.
    Category I or II (engineer determines). NOT automatable."""

    # --- Non-MUA / routing types ---

    STANDARD = "STANDARD"
    """Rating=A (pass) or B with batch verification, or screening
    not applicable. No MUA needed."""

    FLAG_FOR_HUMAN = "FLAG_FOR_HUMAN"
    """Unknown/ambiguous rating (K, S, N, blank), unverified B-rating,
    or material class unknown. Route to human with explanation."""


# ---------------------------------------------------------------------------
# MUA Category — per 6016C section 4.1.6.1
# ---------------------------------------------------------------------------


class MUACategorySpec(str, Enum):
    """MUA category per NASA-STD-6016C section 4.1.6.1.

    Category applies to the DEVIATION, not the hardware criticality.
    Cat III is RETIRED as of 6016C Rev A / JSC-27301 Rev G.

    Cat I: Could affect safety AND has to be used for functional reasons
           (known risk accepted). 3 signatures.
    Cat II: Fails screening but not a hazard in this application,
            and no Cat III code exists. 2 signatures.
    """

    I = "I"
    II = "II"


# ---------------------------------------------------------------------------
# MAPTIS Rating Semantics — Column-specific (spec Section 4)
# ---------------------------------------------------------------------------


class RatingSemantics(BaseModel):
    """Column-specific rating interpretation.

    CRITICAL: Same letter means different things in different columns.
    This model captures the column-specific meaning.
    """

    issue_key: str
    rating: str
    meaning: str
    mua_required: bool
    severity: str  # "none", "administrative", "real_failure", "real_gap", "unknown"


# Pre-built rating semantics lookup
RATING_SEMANTICS: dict[tuple[str, str], RatingSemantics] = {
    # FLAM ratings
    ("FLAM", "A"): RatingSemantics(
        issue_key="FLAM", rating="A",
        meaning=">=5 standard samples, burn length <=6.0 inches. Pass.",
        mua_required=False, severity="none",
    ),
    ("FLAM", "C"): RatingSemantics(
        issue_key="FLAM", rating="C",
        meaning="Burn length >6.0 inches. Real failure.",
        mua_required=True, severity="real_failure",
    ),
    ("FLAM", "I"): RatingSemantics(
        issue_key="FLAM", rating="I",
        meaning="<5 standard samples, burn length <=6.0 inches. "
                "Incomplete pass — data favorable, sample count insufficient.",
        mua_required=True, severity="administrative",
    ),
    ("FLAM", "S"): RatingSemantics(
        issue_key="FLAM", rating="S",
        meaning="Special test conducted. Requires review of actual test report.",
        mua_required=True, severity="unknown",
    ),
    ("FLAM", "U"): RatingSemantics(
        issue_key="FLAM", rating="U",
        meaning="Unacceptable data.",
        mua_required=True, severity="real_gap",
    ),
    # FS ratings
    ("FS", "A"): RatingSemantics(
        issue_key="FS", rating="A",
        meaning="Passes 48-hour screening in test fluid (hydrazine/MMH/N2O4).",
        mua_required=False, severity="none",
    ),
    ("FS", "U"): RatingSemantics(
        issue_key="FS", rating="U",
        meaning="Untested — no Test 15 data exists. "
                "Test 15 is specific to hydrazine/MMH/N2O4 class propellants.",
        mua_required=True, severity="real_gap",
    ),
    # TOX ratings
    ("TOX", "A"): RatingSemantics(
        issue_key="TOX", rating="A",
        meaning="Passes TML <=1.0%, CVCM <=0.1%.",
        mua_required=False, severity="none",
    ),
    ("TOX", "U"): RatingSemantics(
        issue_key="TOX", rating="U",
        meaning="Untested for offgassing.",
        mua_required=True, severity="real_gap",
    ),
    ("TOX", "K"): RatingSemantics(
        issue_key="TOX", rating="K",
        meaning="Unknown — not in standard documentation. MIUL builder artifact.",
        mua_required=True, severity="unknown",
    ),
    # SCC ratings
    ("SCC", "A"): RatingSemantics(
        issue_key="SCC", rating="A",
        meaning="Resistant to stress corrosion cracking.",
        mua_required=False, severity="none",
    ),
    ("SCC", "B"): RatingSemantics(
        issue_key="SCC", rating="B",
        meaning="Conditional — batch/lot dependent.",
        mua_required=True, severity="administrative",
    ),
    ("SCC", "C"): RatingSemantics(
        issue_key="SCC", rating="C",
        meaning="Susceptible under certain conditions.",
        mua_required=True, severity="real_failure",
    ),
    ("SCC", "N"): RatingSemantics(
        issue_key="SCC", rating="N",
        meaning="Not applicable.",
        mua_required=False, severity="none",
    ),
    # CORR ratings
    ("CORR", "A"): RatingSemantics(
        issue_key="CORR", rating="A",
        meaning="Acceptable corrosion resistance.",
        mua_required=False, severity="none",
    ),
    ("CORR", "B"): RatingSemantics(
        issue_key="CORR", rating="B",
        meaning="Conditional — batch/lot dependent.",
        mua_required=True, severity="administrative",
    ),
    # TVS ratings
    ("TVS", "A"): RatingSemantics(
        issue_key="TVS", rating="A",
        meaning="Passes ASTM E595 outgassing criteria.",
        mua_required=False, severity="none",
    ),
    ("TVS", "C"): RatingSemantics(
        issue_key="TVS", rating="C",
        meaning="Fails ASTM E595 outgassing criteria.",
        mua_required=True, severity="real_failure",
    ),
    ("TVS", "U"): RatingSemantics(
        issue_key="TVS", rating="U",
        meaning="Not tested for thermal vacuum stability.",
        mua_required=True, severity="real_gap",
    ),
    ("CORR", "U"): RatingSemantics(
        issue_key="CORR", rating="U",
        meaning="Not tested for corrosion resistance.",
        mua_required=True, severity="real_gap",
    ),
    ("SCC", "U"): RatingSemantics(
        issue_key="SCC", rating="U",
        meaning="Not tested for stress corrosion cracking.",
        mua_required=True, severity="real_gap",
    ),
    ("FLAM", "N"): RatingSemantics(
        issue_key="FLAM", rating="N",
        meaning="Not applicable or not tested. Context-dependent.",
        mua_required=True, severity="unknown",
    ),
}


# ---------------------------------------------------------------------------
# Column-Specific Flag Dictionaries (BS-SPEC-MUA-003 Section 3, Step 2)
# ---------------------------------------------------------------------------
# Each column in MAPTIS has its own dictionary. The same letter means
# different things in different columns. These dictionaries map
# (column, rating) -> FlagType.

COLUMN_FLAG_DICT: dict[str, dict[str, FlagType]] = {
    "FLAM": {
        "A": FlagType.NO_FLAG,
        "C": FlagType.REAL_FAIL,
        "I": FlagType.ADMIN_GAP,
        "S": FlagType.NEEDS_REVIEW,
        "U": FlagType.NO_DATA,
        "N": FlagType.NEEDS_REVIEW,
    },
    "FS": {
        "A": FlagType.NO_FLAG,
        "U": FlagType.NO_DATA,
    },
    "TOX": {
        "A": FlagType.NO_FLAG,
        "U": FlagType.NO_DATA,
        "K": FlagType.BAD_DATA,
    },
    "TVS": {
        "A": FlagType.NO_FLAG,
        "C": FlagType.REAL_FAIL,
        "U": FlagType.NO_DATA,
    },
    "SCC": {
        "A": FlagType.NO_FLAG,
        "B": FlagType.BATCH_REQUIRED,
        "C": FlagType.REAL_FAIL,
        "N": FlagType.NO_FLAG,
        "U": FlagType.NO_DATA,
    },
    "CORR": {
        "A": FlagType.NO_FLAG,
        "B": FlagType.BATCH_REQUIRED,
        "U": FlagType.NO_DATA,
    },
}


# ---------------------------------------------------------------------------
# Decoded Flag — Step 2 output
# ---------------------------------------------------------------------------


class DecodedFlag(BaseModel):
    """Result of decoding a MAPTIS rating via the column-specific dictionary.

    Produced by Step 2 of the pipeline. Contains the flag_type that
    drives all subsequent classification decisions.
    """

    column: str  # FLAM, FS, TOX, TVS, SCC, CORR
    rating: str  # The raw rating letter
    flag_type: FlagType
    decoded_meaning: str  # Human-readable explanation
    source: str = ""  # Standard/section reference for the decoding


# ---------------------------------------------------------------------------
# Screening Result
# ---------------------------------------------------------------------------


class ScreeningResult(BaseModel):
    """Result of the material-class pre-filter gate (spec Section 5).

    If applicable=False, no MUA is needed for this screening+material
    combination regardless of what MAPTIS says.
    """

    issue_key: str
    material_class: MaterialClassEnum
    environment: str  # "habitable" or "non-habitable"
    applicable: bool
    reason: str


# ---------------------------------------------------------------------------
# Classifier Result
# ---------------------------------------------------------------------------


class ClassifierResult(BaseModel):
    """Result of MUA type classification (Steps 1-6 of pipeline).

    Contains the deterministic classification, category assignment,
    confidence, and all decision trace information needed for audit.
    """

    # Input echo
    maptis_code: str
    issue_key: str
    rating: str
    material_class: MaterialClassEnum
    media: str
    environment: str  # "habitable" or "non-habitable"

    # Step 2 output: flag decoding
    flag_type: Optional[FlagType] = None

    # Step 4 output: hazard check
    hazard_applies: Optional[bool] = None

    # Step 5 output: classification
    mua_type: MUAType
    category: Optional[MUACategorySpec] = None
    confidence: float = Field(0.0, ge=0.0, le=1.0)
    automatable: bool = False  # True for THIN_SCREENING, ANTI_RULE, INCOMPLETE_PASS

    # Decision trace
    screening_applicable: bool = True
    screening_reason: str = ""
    classification_reason: str = ""
    rating_semantics: Optional[RatingSemantics] = None

    # Cross-references
    companion_mua_ref: Optional[str] = None  # e.g., "H2COMPAT TBD"
    precedents_needed: int = 0
    precedent: Optional["PrecedentSummary"] = None
    precedent_ring: Optional[str] = None  # "exact", "family", or "broad"
    synthesis: Optional["SynthesisResult"] = None
    evidence_bundle: Optional["EvidenceBundle"] = None

    # B-rating flag
    requires_batch_verification: bool = False


# ---------------------------------------------------------------------------
# MUA Grouping
# ---------------------------------------------------------------------------


class MUAGroup(BaseModel):
    """A group of parts sharing the same MAPTIS code + issue key (spec Section 9).

    One MUA is generated per group. All parts in the group share
    identical rationale because the physics don't change between
    parts made of the same alloy in the same environment.
    """

    maptis_code: str
    issue_key: str
    material_designation: str  # Human-readable name
    material_class: MaterialClassEnum
    rating: str
    mua_type: MUAType
    category: Optional[MUACategorySpec] = None
    confidence: float = 0.0

    # Aggregated part information
    part_numbers: list[str] = Field(default_factory=list)
    part_count: int = 0

    # Environment (from MIUL)
    media: str = ""
    pressure_range: Optional[str] = None
    temp_range: Optional[str] = None
    location: str = "non-habitable"
    application: str = ""

    # Material specification
    material_specification: Optional[str] = None

    # Companion reference
    companion_mua_ref: Optional[str] = None


# ---------------------------------------------------------------------------
# MSFC Form 551 Fields (spec Section 8.1)
# ---------------------------------------------------------------------------


class Form551Fields(BaseModel):
    """MSFC Form 551 fields per Appendix B of NASA-STD-6016C.

    This is the actual form structure — NOT a seven-section report,
    NOT a narrative document. It's a form with fields.
    """

    mua_number: str = ""
    category: str = ""  # "I" or "II"
    date: str = ""
    governing_standard: str = "NASA-STD-6016C"
    project: str = ""
    system: str = ""

    # Material
    material_designation: str = ""
    maptis_code: str = ""
    material_specification: str = ""
    material_class: str = ""

    # Issue
    issue: str = ""  # Screening category (FLAM, FS, TOX, etc.)
    rating: str = ""

    # Parts
    part_numbers: list[str] = Field(default_factory=list)
    part_count: int = 0

    # Operating environment
    media: str = ""
    pressure: str = ""
    temperature: str = ""
    location: str = ""  # habitable/non-habitable

    # Content
    application: str = ""
    rationale: str = ""
    disposition: str = ""

    # Approval
    approval_signatures: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Pipeline Result — Full output of Steps 1-8
# ---------------------------------------------------------------------------


class PipelineResult(BaseModel):
    """Complete pipeline output for one MAPTIS code across all flags.

    Produced by running a grouped set of MIUL rows (same MAPTIS code)
    through the full pipeline. Contains all flags identified, their
    classifications, and any generated Form 551 documents.
    """

    maptis_code: str
    material_designation: str = ""
    material_class: MaterialClassEnum = MaterialClassEnum.METAL

    # Step 1 output: all flags identified
    flags_identified: list[DecodedFlag] = Field(default_factory=list)

    # Steps 2-6 output: classification per flag
    classifications: list[ClassifierResult] = Field(default_factory=list)

    # Steps 7-8 output: generated forms (automatable flags only)
    forms: list[Form551Fields] = Field(default_factory=list)

    # Human routing
    human_required: list[ClassifierResult] = Field(default_factory=list)
    human_required_reasons: list[str] = Field(default_factory=list)

    # Summary
    total_flags: int = 0
    automatable_count: int = 0
    human_required_count: int = 0
    no_mua_needed_count: int = 0
