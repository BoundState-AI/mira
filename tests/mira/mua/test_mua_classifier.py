"""Tests for MUA Classifier — BS-SPEC-MUA-003 Implementation.

Tests the flag-first deterministic MUA classifier against the specification's
requirements and the 11 known-correct MUA classifications from the
DMLLV 10-inch H2 valve (in-space refueling system).

Test organization mirrors the spec steps:
- Step 1: Flag identification
- Step 2: Flag decoding (FlagType, COLUMN_FLAG_DICT)
- Step 3: Material-class pre-filter gate
- Step 4: Hazard applicability
- Step 5: MUA type classification matrix
- Step 6: Category assignment
- Steps 7-8: Rationale & Form 551
- Grouping logic
- Pipeline orchestration
- Known MUA validation & old system error prevention

BoundState AI 2026
Co-Authored-By: Claude "Beth" <noreply@anthropic.com>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: NASA-STD-6016C w/Change 2, JSC-27301 Rev J
Safety Critical: True
"""

import pytest

from mira.mua.classifier.models import (
    COLUMN_FLAG_DICT,
    ClassifierResult,
    DecodedFlag,
    FlagType,
    Form551Fields,
    MaterialClassEnum,
    MUACategorySpec,
    MUAGroup,
    MUAType,
    PipelineResult,
    RATING_SEMANTICS,
    ScreeningResult,
)
from mira.mua.classifier.screening import (
    ENVIRONMENT_APPLICABILITY,
    SCREENING_APPLICABILITY,
    is_screening_applicable,
    material_class_from_miul,
)
from mira.mua.classifier.classifier import (
    classify_mua,
    classify_mua_batch,
    step1_identify_flags,
    step2_decode_flag,
    step3_should_flag_exist,
    step4_hazard_applies,
    step5_classify_type,
    step6_assign_category,
)
from mira.mua.classifier.grouping import group_by_maptis_issue
from mira.mua.classifier.rationale import (
    render_rationale,
    render_disposition,
)
from mira.mua.classifier.domain_facts import (
    DOMAIN_FACTS,
    DomainFact,
    get_fact,
    get_fact_text,
)
from mira.mua.classifier.pipeline import (
    process_miul_row,
    process_single_flag,
    process_miul_batch,
)


# =========================================================================
# Step 1: Flag Identification
# =========================================================================


class TestStep1IdentifyFlags:
    """Tests for step1_identify_flags — Step 1: WHAT FLAG?"""

    def test_all_a_no_flags(self):
        """All A ratings = no flags. No MUAs needed."""
        ratings = {"FLAM": "A", "FS": "A", "SCC": "A", "CORR": "A", "TVS": "A", "TOX": "A"}
        flags = step1_identify_flags(ratings)
        assert flags == []

    def test_single_non_passing_flag(self):
        """One non-passing rating produces one flag."""
        ratings = {"FLAM": "A", "FS": "U", "SCC": "A", "CORR": "A", "TVS": "A", "TOX": "A"}
        flags = step1_identify_flags(ratings)
        assert len(flags) == 1
        assert flags[0] == ("FS", "U")

    def test_multiple_flags(self):
        """Multiple non-passing ratings produce multiple flags."""
        ratings = {"FLAM": "C", "FS": "U", "SCC": "A", "CORR": "A", "TVS": "A", "TOX": "A"}
        flags = step1_identify_flags(ratings)
        assert len(flags) == 2
        columns = {f[0] for f in flags}
        assert columns == {"FLAM", "FS"}

    def test_missing_column_is_ignored(self):
        """Blank/omitted ratings are ignored (not auto-flagged)."""
        ratings = {"FLAM": "A", "FS": None, "SCC": "A", "CORR": "A", "TVS": "A", "TOX": "A"}
        flags = step1_identify_flags(ratings)
        assert flags == []

    def test_n_rating_skipped(self):
        """N (not applicable) should be treated as pass — no flag."""
        ratings = {"FLAM": "A", "FS": "A", "SCC": "N", "CORR": "A", "TVS": "A", "TOX": "A"}
        flags = step1_identify_flags(ratings)
        assert flags == []

    def test_dmllv_h2_valve_flags(self):
        """DMLLV H2 valve typical row: FS=U, FLAM=C, rest pass."""
        ratings = {"FLAM": "C", "FS": "U", "SCC": "A", "CORR": "A", "TVS": "A", "TOX": "A"}
        flags = step1_identify_flags(ratings)
        assert len(flags) == 2


# =========================================================================
# Step 2: Flag Decoding
# =========================================================================


class TestStep2DecodeFlag:
    """Tests for step2_decode_flag — Step 2: WHAT DOES IT MEAN?"""

    def test_flam_c_is_real_fail(self):
        """FLAM=C → REAL_FAIL (actual burn >6 inches)."""
        decoded = step2_decode_flag("FLAM", "C")
        assert decoded.flag_type == FlagType.REAL_FAIL
        assert decoded.column == "FLAM"
        assert decoded.rating == "C"

    def test_flam_i_is_admin_gap(self):
        """FLAM=I → ADMIN_GAP (<5 samples, all passing)."""
        decoded = step2_decode_flag("FLAM", "I")
        assert decoded.flag_type == FlagType.ADMIN_GAP

    def test_fs_u_is_no_data(self):
        """FS=U → NO_DATA (never tested against hydrazine)."""
        decoded = step2_decode_flag("FS", "U")
        assert decoded.flag_type == FlagType.NO_DATA

    def test_scc_b_is_batch_required(self):
        """SCC=B → BATCH_REQUIRED."""
        decoded = step2_decode_flag("SCC", "B")
        assert decoded.flag_type == FlagType.BATCH_REQUIRED

    def test_tox_k_is_bad_data(self):
        """TOX=K → BAD_DATA (undocumented rating)."""
        decoded = step2_decode_flag("TOX", "K")
        assert decoded.flag_type == FlagType.BAD_DATA

    def test_flam_s_needs_review(self):
        """FLAM=S → NEEDS_REVIEW (special test)."""
        decoded = step2_decode_flag("FLAM", "S")
        assert decoded.flag_type == FlagType.NEEDS_REVIEW

    def test_blank_rating_is_missing_data(self):
        """Blank rating → MISSING_DATA."""
        decoded = step2_decode_flag("FS", "")
        assert decoded.flag_type == FlagType.MISSING_DATA

    def test_unknown_letter_is_bad_data(self):
        """Unrecognized letter in a column → BAD_DATA."""
        decoded = step2_decode_flag("FS", "X")
        assert decoded.flag_type == FlagType.BAD_DATA

    def test_column_flag_dict_completeness(self):
        """Every column in COLUMN_FLAG_DICT has an A entry (NO_FLAG)."""
        for column, ratings in COLUMN_FLAG_DICT.items():
            assert "A" in ratings, f"Column {column} missing A rating"
            assert ratings["A"] == FlagType.NO_FLAG

    def test_same_letter_different_meaning(self):
        """CRITICAL: Same letter means different things in different columns.
        C in FLAM = REAL_FAIL, C in TVS = REAL_FAIL, but I only exists in FLAM."""
        flam_c = step2_decode_flag("FLAM", "C")
        tvs_c = step2_decode_flag("TVS", "C")
        assert flam_c.flag_type == FlagType.REAL_FAIL
        assert tvs_c.flag_type == FlagType.REAL_FAIL

        flam_i = step2_decode_flag("FLAM", "I")
        assert flam_i.flag_type == FlagType.ADMIN_GAP
        # I is not defined for TVS
        tvs_i = step2_decode_flag("TVS", "I")
        assert tvs_i.flag_type == FlagType.BAD_DATA


# =========================================================================
# Step 3: Material-Class Pre-Filter Gate
# =========================================================================


class TestStep3ScreeningApplicability:
    """Tests for the material-class gate (Step 3: SHOULD THIS FLAG EXIST?)."""

    # --- TOX screening ---

    def test_tox_not_applicable_to_metal(self):
        """TOX (MPR 45) applies to nonmetallic materials ONLY."""
        result = is_screening_applicable("TOX", "metal", "habitable")
        assert result.applicable is False

    def test_tox_applicable_to_nonmetallic_habitable(self):
        """TOX applies to nonmetallics in habitable compartments."""
        result = is_screening_applicable("TOX", "nonmetallic", "habitable")
        assert result.applicable is True

    def test_tox_not_applicable_in_non_habitable(self):
        """TOX does not apply in non-habitable environments."""
        result = is_screening_applicable("TOX", "nonmetallic", "non-habitable")
        assert result.applicable is False

    # --- TVS screening ---

    def test_tvs_not_applicable_to_metal(self):
        """TVS (ASTM E595) applies to nonmetallic materials ONLY."""
        result = is_screening_applicable("TVS", "metal")
        assert result.applicable is False

    def test_tvs_applicable_to_nonmetallic(self):
        """TVS applies to nonmetallic materials."""
        result = is_screening_applicable("TVS", "nonmetallic")
        assert result.applicable is True

    # --- SCC screening ---

    def test_scc_not_applicable_to_nonmetallic(self):
        """SCC applies to metals ONLY."""
        result = is_screening_applicable("SCC", "nonmetallic")
        assert result.applicable is False

    def test_scc_applicable_to_metal(self):
        """SCC applies to metals."""
        result = is_screening_applicable("SCC", "metal")
        assert result.applicable is True

    # --- CORR screening ---

    def test_corr_not_applicable_to_nonmetallic(self):
        """CORR applies to metals ONLY."""
        result = is_screening_applicable("CORR", "nonmetallic")
        assert result.applicable is False

    def test_corr_applicable_to_metal(self):
        """CORR applies to metals."""
        result = is_screening_applicable("CORR", "metal")
        assert result.applicable is True

    # --- FLAM screening ---

    def test_flam_applicable_to_all(self):
        """FLAM applies to all material classes."""
        assert is_screening_applicable("FLAM", "metal").applicable is True
        assert is_screening_applicable("FLAM", "nonmetallic").applicable is True

    # --- FS screening ---

    def test_fs_applicable_to_all(self):
        """FS applies to all material classes."""
        assert is_screening_applicable("FS", "metal").applicable is True
        assert is_screening_applicable("FS", "nonmetallic").applicable is True

    # --- H2COMPAT screening ---

    def test_h2compat_applicable_to_metal_only(self):
        """H2COMPAT (MPR 192/193) applies to metals in H2 systems."""
        assert is_screening_applicable("H2COMPAT", "metal").applicable is True
        assert is_screening_applicable("H2COMPAT", "nonmetallic").applicable is False

    # --- Step 3 via step function ---

    def test_step3_function_delegates_correctly(self):
        """step3_should_flag_exist delegates to is_screening_applicable."""
        assert step3_should_flag_exist("TOX", "metal", "habitable") is False
        assert step3_should_flag_exist("TOX", "nonmetallic", "habitable") is True
        assert step3_should_flag_exist("SCC", "metal") is True
        assert step3_should_flag_exist("SCC", "nonmetallic") is False

    # --- Input normalization ---

    def test_case_insensitive_issue_key(self):
        """Issue keys should be case-insensitive."""
        r1 = is_screening_applicable("tox", "metal")
        r2 = is_screening_applicable("TOX", "metal")
        r3 = is_screening_applicable("Tox", "metal")
        assert r1.applicable == r2.applicable == r3.applicable

    def test_environment_normalization(self):
        """Various environment string formats should normalize correctly."""
        r1 = is_screening_applicable("TOX", "nonmetallic", "non-habitable")
        r2 = is_screening_applicable("TOX", "nonmetallic", "non_habitable")
        r3 = is_screening_applicable("TOX", "nonmetallic", "nonhabitable")
        assert r1.applicable == r2.applicable == r3.applicable is False

    def test_enum_input(self):
        """Should accept MaterialClassEnum directly."""
        result = is_screening_applicable("TOX", MaterialClassEnum.METAL)
        assert result.applicable is False


# =========================================================================
# Step 3b: Material Class Inference from MIUL
# =========================================================================


class TestMaterialClassFromMIUL:
    """Tests for material_class_from_miul() — Step 3 inference."""

    def test_metal_keywords(self):
        """Common metal designations correctly identified."""
        assert material_class_from_miul("A286 CRES") == MaterialClassEnum.METAL
        assert material_class_from_miul("7075-T651 AL") == MaterialClassEnum.METAL
        assert material_class_from_miul("Inconel 718") == MaterialClassEnum.METAL
        assert material_class_from_miul("302/304 SST") == MaterialClassEnum.METAL
        assert material_class_from_miul("Hastelloy C-276") == MaterialClassEnum.METAL

    def test_nonmetallic_keywords(self):
        """Common nonmetallic designations correctly identified."""
        assert material_class_from_miul("Vespel SP-3") == MaterialClassEnum.NONMETALLIC
        assert material_class_from_miul("PTFE Teflon") == MaterialClassEnum.NONMETALLIC
        assert material_class_from_miul("Kapton Film") == MaterialClassEnum.NONMETALLIC
        assert material_class_from_miul("Viton O-Ring") == MaterialClassEnum.NONMETALLIC

    def test_unknown_returns_none(self):
        """Unrecognizable designation returns None (route to human)."""
        assert material_class_from_miul("UNKNOWN-123") is None
        assert material_class_from_miul("") is None

    def test_case_insensitive(self):
        """Designation matching is case-insensitive."""
        assert material_class_from_miul("a286 cres") == MaterialClassEnum.METAL
        assert material_class_from_miul("VESPEL SP-3") == MaterialClassEnum.NONMETALLIC


# =========================================================================
# Step 4: Hazard Applicability
# =========================================================================


class TestStep4HazardApplies:
    """Tests for step4_hazard_applies — Step 4: DOES THE HAZARD APPLY?"""

    def test_flam_not_credible_in_h2(self):
        """FLAM hazard (promoted ignition) NOT credible in H2 — no O2."""
        assert step4_hazard_applies("FLAM", "GH2") is False
        assert step4_hazard_applies("FLAM", "LH2") is False

    def test_flam_credible_in_gox(self):
        """FLAM hazard IS credible in GOX/LOX."""
        assert step4_hazard_applies("FLAM", "GOX") is True
        assert step4_hazard_applies("FLAM", "LOX") is True

    def test_flam_credible_at_enriched_o2(self):
        """FLAM hazard IS credible at >= 23.5% O2."""
        assert step4_hazard_applies("FLAM", "AIR", o2_percent=23.5) is True
        assert step4_hazard_applies("FLAM", "AIR", o2_percent=30.0) is True

    def test_flam_not_credible_at_normal_o2(self):
        """FLAM hazard NOT credible at normal O2 (20.9%)."""
        assert step4_hazard_applies("FLAM", "AIR", o2_percent=20.9) is False

    def test_fs_not_relevant_in_h2(self):
        """FS Test 15 covers hydrazine/N2O4, NOT H2."""
        assert step4_hazard_applies("FS", "GH2") is False
        assert step4_hazard_applies("FS", "LH2") is False

    def test_fs_relevant_in_hydrazine(self):
        """FS Test 15 IS relevant for hydrazine."""
        assert step4_hazard_applies("FS", "N2H4") is True
        assert step4_hazard_applies("FS", "MMH") is True
        assert step4_hazard_applies("FS", "N2O4") is True

    def test_scc_suppressed_in_h2(self):
        """SCC suppressed in cryogenic H2 (no aqueous environment)."""
        assert step4_hazard_applies("SCC", "GH2") is False
        assert step4_hazard_applies("SCC", "LH2") is False

    def test_scc_credible_in_other_media(self):
        """SCC credible in non-H2 media (potential aqueous environments)."""
        assert step4_hazard_applies("SCC", "AIR") is True

    def test_tox_always_credible_if_reached(self):
        """TOX — if Step 3 passed (nonmetallic + habitable), hazard applies."""
        assert step4_hazard_applies("TOX", "AIR") is True

    def test_tvs_always_credible_if_reached(self):
        """TVS — if Step 3 passed (nonmetallic), hazard applies."""
        assert step4_hazard_applies("TVS", "GH2") is True


# =========================================================================
# Step 5: MUA Type Classification Matrix
# =========================================================================


class TestStep5ClassifyType:
    """Tests for step5_classify_type — the 2x3 matrix."""

    def test_real_fail_no_hazard_is_anti_rule(self):
        """REAL_FAIL + hazard=False → ANTI_RULE (automatable)."""
        assert step5_classify_type(FlagType.REAL_FAIL, False) == MUAType.ANTI_RULE

    def test_real_fail_with_hazard_is_real_problem(self):
        """REAL_FAIL + hazard=True → REAL_PROBLEM (needs engineer)."""
        assert step5_classify_type(FlagType.REAL_FAIL, True) == MUAType.REAL_PROBLEM

    def test_admin_gap_no_hazard_is_incomplete_pass(self):
        """ADMIN_GAP + hazard=False → INCOMPLETE_PASS (automatable)."""
        assert step5_classify_type(FlagType.ADMIN_GAP, False) == MUAType.INCOMPLETE_PASS

    def test_admin_gap_with_hazard_is_incomplete_pass(self):
        """ADMIN_GAP + hazard=True → INCOMPLETE_PASS (always automatable, data favorable)."""
        assert step5_classify_type(FlagType.ADMIN_GAP, True) == MUAType.INCOMPLETE_PASS

    def test_no_data_no_hazard_is_thin_screening(self):
        """NO_DATA + hazard=False → THIN_SCREENING (automatable)."""
        assert step5_classify_type(FlagType.NO_DATA, False) == MUAType.THIN_SCREENING

    def test_no_data_with_hazard_is_real_gap(self):
        """NO_DATA + hazard=True → REAL_GAP (needs test plan)."""
        assert step5_classify_type(FlagType.NO_DATA, True) == MUAType.REAL_GAP


# =========================================================================
# Step 6: Category Assignment
# =========================================================================


class TestStep6AssignCategory:
    """Tests for step6_assign_category."""

    def test_automatable_types_are_cat_ii(self):
        """All automatable MUA types are Category II by definition."""
        assert step6_assign_category(MUAType.THIN_SCREENING) == MUACategorySpec.II
        assert step6_assign_category(MUAType.ANTI_RULE) == MUACategorySpec.II
        assert step6_assign_category(MUAType.INCOMPLETE_PASS) == MUACategorySpec.II

    def test_real_problem_is_cat_i(self):
        """REAL_PROBLEM requires Cat I (known risk accepted)."""
        assert step6_assign_category(MUAType.REAL_PROBLEM) == MUACategorySpec.I

    def test_real_gap_is_cat_ii(self):
        """REAL_GAP defaults to Cat II (engineer may elevate)."""
        assert step6_assign_category(MUAType.REAL_GAP) == MUACategorySpec.II

    def test_standard_has_no_category(self):
        """STANDARD (no MUA needed) has no category."""
        assert step6_assign_category(MUAType.STANDARD) is None


# =========================================================================
# Integrated Classifier (Steps 2-6)
# =========================================================================


class TestClassifierDecisionTree:
    """Tests for the integrated classify_mua function."""

    # --- Screening gate integration ---

    def test_tox_on_metal_skipped(self):
        """TOX on metal should not generate MUA — screening gate catches it."""
        result = classify_mua(
            maptis_code="51382", issue_key="TOX", rating="U",
            material_class="metal", media="GH2", environment="non-habitable",
        )
        assert result.screening_applicable is False
        assert result.mua_type == MUAType.STANDARD

    def test_tvs_on_metal_skipped(self):
        """TVS on metal should not generate MUA."""
        result = classify_mua(
            maptis_code="55750", issue_key="TVS", rating="C",
            material_class="metal", media="GH2",
        )
        assert result.screening_applicable is False
        assert result.mua_type == MUAType.STANDARD

    # --- Rating A ---

    def test_rating_a_is_standard(self):
        """Rating A = pass. No MUA needed."""
        result = classify_mua(
            maptis_code="10392", issue_key="FLAM", rating="A",
            material_class="metal", media="GH2",
        )
        assert result.mua_type == MUAType.STANDARD
        assert result.flag_type == FlagType.NO_FLAG
        assert result.category is None
        assert result.confidence == 1.0

    # --- Rating B ---

    def test_rating_b_with_batch_is_standard(self):
        """Rating B with batch verification = treated as pass."""
        result = classify_mua(
            maptis_code="10392", issue_key="CORR", rating="B",
            material_class="metal", media="GH2", batch_verified=True,
        )
        assert result.mua_type == MUAType.STANDARD
        assert result.flag_type == FlagType.BATCH_REQUIRED

    def test_rating_b_without_batch_flags_human(self):
        """Rating B without batch verification = flag for human."""
        result = classify_mua(
            maptis_code="10392", issue_key="CORR", rating="B",
            material_class="metal", media="GH2", batch_verified=False,
        )
        assert result.mua_type == MUAType.FLAG_FOR_HUMAN
        assert result.requires_batch_verification is True

    # --- Rating I (ADMIN_GAP) ---

    def test_rating_i_is_incomplete_pass(self):
        """Rating I = incomplete pass (favorable data, insufficient samples)."""
        result = classify_mua(
            maptis_code="55962", issue_key="FLAM", rating="I",
            material_class="metal", media="GH2",
        )
        assert result.mua_type == MUAType.INCOMPLETE_PASS
        assert result.flag_type == FlagType.ADMIN_GAP
        assert result.category == MUACategorySpec.II
        assert result.confidence == 0.95
        assert result.automatable is True

    # --- Rating U (NO_DATA) ---

    def test_fs_u_in_h2_is_thin_screening(self):
        """FS=U in H2 service = THIN_SCREENING.
        Test 15 covers hydrazine/N2O4, not H2."""
        result = classify_mua(
            maptis_code="10392", issue_key="FS", rating="U",
            material_class="metal", media="GH2",
        )
        assert result.mua_type == MUAType.THIN_SCREENING
        assert result.flag_type == FlagType.NO_DATA
        assert result.hazard_applies is False
        assert result.category == MUACategorySpec.II
        assert result.confidence == 0.90
        assert result.automatable is True
        assert result.companion_mua_ref is not None
        assert "H2COMPAT" in result.companion_mua_ref

    def test_fs_u_in_hydrazine_is_real_gap(self):
        """FS=U in actual hydrazine service = REAL_GAP."""
        result = classify_mua(
            maptis_code="10392", issue_key="FS", rating="U",
            material_class="metal", media="N2H4",
        )
        assert result.mua_type == MUAType.REAL_GAP
        assert result.flag_type == FlagType.NO_DATA
        assert result.hazard_applies is True
        assert result.category == MUACategorySpec.II
        assert result.confidence == 0.40
        assert result.automatable is False

    def test_fs_u_in_lh2_is_thin_screening(self):
        """FS=U in LH2 service = THIN_SCREENING (same logic as GH2)."""
        result = classify_mua(
            maptis_code="10392", issue_key="FS", rating="U",
            material_class="metal", media="LH2",
        )
        assert result.mua_type == MUAType.THIN_SCREENING

    # --- Rating C (REAL_FAIL) ---

    def test_flam_c_in_h2_no_o2_is_anti_rule(self):
        """FLAM=C in H2 service with no O2 enrichment = ANTI_RULE."""
        result = classify_mua(
            maptis_code="54223", issue_key="FLAM", rating="C",
            material_class="metal", media="GH2",
        )
        assert result.mua_type == MUAType.ANTI_RULE
        assert result.flag_type == FlagType.REAL_FAIL
        assert result.hazard_applies is False
        assert result.category == MUACategorySpec.II
        assert result.automatable is True
        assert result.companion_mua_ref is not None

    def test_flam_c_in_gox_is_real_problem(self):
        """FLAM=C in GOX service = REAL_PROBLEM.
        The failure mode IS credible in O2 service."""
        result = classify_mua(
            maptis_code="54223", issue_key="FLAM", rating="C",
            material_class="metal", media="GOX",
        )
        assert result.mua_type == MUAType.REAL_PROBLEM
        assert result.flag_type == FlagType.REAL_FAIL
        assert result.hazard_applies is True
        assert result.automatable is False

    def test_flam_c_in_enriched_o2_is_real_problem(self):
        """FLAM=C with >= 23.5% O2 = REAL_PROBLEM (credible)."""
        result = classify_mua(
            maptis_code="54223", issue_key="FLAM", rating="C",
            material_class="metal", media="AIR", o2_percent=30.0,
        )
        assert result.mua_type == MUAType.REAL_PROBLEM

    def test_scc_c_in_h2_is_anti_rule(self):
        """SCC=C in H2 service = ANTI_RULE.
        Cryogenic H2 suppresses aqueous SCC mechanisms."""
        result = classify_mua(
            maptis_code="50181", issue_key="SCC", rating="C",
            material_class="metal", media="GH2",
        )
        assert result.mua_type == MUAType.ANTI_RULE
        assert result.flag_type == FlagType.REAL_FAIL

    # --- Unknown/problematic ratings ---

    def test_unknown_rating_k_flags_human(self):
        """Rating K (unknown, undocumented) = FLAG_FOR_HUMAN."""
        result = classify_mua(
            maptis_code="05057", issue_key="TOX", rating="K",
            material_class="nonmetallic", media="GH2", environment="habitable",
        )
        assert result.mua_type == MUAType.FLAG_FOR_HUMAN
        assert result.flag_type == FlagType.BAD_DATA

    def test_unknown_rating_s_flags_human(self):
        """Rating S (special test) = FLAG_FOR_HUMAN."""
        result = classify_mua(
            maptis_code="12345", issue_key="FLAM", rating="S",
            material_class="metal", media="GH2",
        )
        assert result.mua_type == MUAType.FLAG_FOR_HUMAN
        assert result.flag_type == FlagType.NEEDS_REVIEW

    def test_blank_rating_flags_human(self):
        """Blank rating = FLAG_FOR_HUMAN."""
        result = classify_mua(
            maptis_code="12345", issue_key="FS", rating="",
            material_class="metal", media="GH2",
        )
        assert result.mua_type == MUAType.FLAG_FOR_HUMAN
        assert result.flag_type == FlagType.MISSING_DATA


# =========================================================================
# Validation Against Known-Correct MUAs (11 DMLLV H2 Valve MUAs)
# =========================================================================


class TestKnownMUAs:
    """Validate classifier against the 11 MUAs generated to date
    for the DMLLV 10-inch H2 valve."""

    @pytest.mark.parametrize(
        "maptis_code,material_name,issue,rating,expected_type",
        [
            # MUA #1-6: FS=U THIN_SCREENING
            ("10392", "A286 CRES", "FS", "U", MUAType.THIN_SCREENING),
            ("10520", "302/304 SST", "FS", "U", MUAType.THIN_SCREENING),
            ("50769", "302/304 SST", "FS", "U", MUAType.THIN_SCREENING),
            ("50768", "302 SST", "FS", "U", MUAType.THIN_SCREENING),
            ("50784", "304 CRES", "FS", "U", MUAType.THIN_SCREENING),
            ("50181", "7075-T651 AL", "FS", "U", MUAType.THIN_SCREENING),
            # MUA #7-8,10: FLAM=C ANTI_RULE
            ("54223", "7075 AL", "FLAM", "C", MUAType.ANTI_RULE),
            ("10727", "Inconel 625", "FLAM", "C", MUAType.ANTI_RULE),
            ("50678", "Al Bronze", "FLAM", "C", MUAType.ANTI_RULE),
            # MUA #9: FS=U THIN_SCREENING
            ("10727", "Inconel 625", "FS", "U", MUAType.THIN_SCREENING),
            # MUA #11: FLAM=I INCOMPLETE_PASS
            ("55962", "Inconel 718", "FLAM", "I", MUAType.INCOMPLETE_PASS),
        ],
    )
    def test_known_mua_classification(
        self, maptis_code, material_name, issue, rating, expected_type
    ):
        """Each of the 11 known MUAs should classify correctly."""
        result = classify_mua(
            maptis_code=maptis_code, issue_key=issue, rating=rating,
            material_class="metal", media="GH2",
        )
        assert result.mua_type == expected_type, (
            f"MUA for {material_name} ({maptis_code}) {issue}={rating}: "
            f"expected {expected_type}, got {result.mua_type}"
        )
        assert result.category == MUACategorySpec.II, (
            f"MUA for {material_name}: expected Cat II, got {result.category}"
        )
        assert result.automatable is True, (
            f"MUA for {material_name}: all 11 known MUAs should be automatable"
        )


# =========================================================================
# Old System Error Prevention
# =========================================================================


class TestOldSystemErrors:
    """Verify the classifier prevents the 11 documented errors."""

    def test_no_tox_on_metal(self):
        """Old error: 'Flagged aluminum for offgassing'."""
        result = classify_mua(
            maptis_code="51382", issue_key="TOX", rating="U",
            material_class="metal", media="GH2",
        )
        assert result.screening_applicable is False
        assert result.mua_type == MUAType.STANDARD

    def test_no_tvs_on_metal(self):
        """Old error: 'Flagged aluminum for thermal vacuum stability'."""
        result = classify_mua(
            maptis_code="51382", issue_key="TVS", rating="C",
            material_class="metal", media="GH2",
        )
        assert result.screening_applicable is False

    def test_fs_u_not_real_gap_in_h2(self):
        """Old error: FS=U treated as real gap when in H2 service.
        Test 15 covers hydrazine, not H2."""
        result = classify_mua(
            maptis_code="10392", issue_key="FS", rating="U",
            material_class="metal", media="GH2",
        )
        assert result.mua_type == MUAType.THIN_SCREENING
        assert result.mua_type != MUAType.REAL_GAP

    def test_screening_artifacts_are_cat_ii_not_cat_i(self):
        """Old error: 'Cat I for screening artifacts'.
        Category applies to the DEVIATION, not the hardware."""
        for issue, rating in [("FS", "U"), ("FLAM", "C"), ("FLAM", "I")]:
            result = classify_mua(
                maptis_code="10392", issue_key=issue, rating=rating,
                material_class="metal", media="GH2",
            )
            assert result.category == MUACategorySpec.II, (
                f"{issue}={rating} should be Cat II, got {result.category}"
            )

    def test_confidence_not_1_on_u_rated_real_gap(self):
        """Old error: 'Confidence 1.0 on U-rated' (no deficiencies -> perfect).
        REAL_GAP confidence is hard-capped at 0.40."""
        result = classify_mua(
            maptis_code="10392", issue_key="FS", rating="U",
            material_class="metal", media="N2H4",
        )
        assert result.mua_type == MUAType.REAL_GAP
        assert result.confidence <= 0.40

    def test_b_rating_flagged(self):
        """Old error: 'CORR=B listed but not flagged'."""
        result = classify_mua(
            maptis_code="51382", issue_key="CORR", rating="B",
            material_class="metal", media="GH2", batch_verified=False,
        )
        assert result.requires_batch_verification is True


# =========================================================================
# MAPTIS Rating Semantics
# =========================================================================


class TestRatingSemantics:
    """Verify column-specific rating semantics."""

    def test_flam_c_vs_i_distinguished(self):
        """C = real failure. I = administrative gap. Fundamentally different."""
        c_semantics = RATING_SEMANTICS.get(("FLAM", "C"))
        i_semantics = RATING_SEMANTICS.get(("FLAM", "I"))
        assert c_semantics is not None
        assert i_semantics is not None
        assert c_semantics.severity == "real_failure"
        assert i_semantics.severity == "administrative"

    def test_fs_u_means_untested(self):
        """FS=U means 'nobody tested this against hydrazine'."""
        semantics = RATING_SEMANTICS.get(("FS", "U"))
        assert semantics is not None
        assert semantics.mua_required is True

    def test_tox_k_is_unknown(self):
        """TOX=K is undocumented. MIUL builder artifact."""
        semantics = RATING_SEMANTICS.get(("TOX", "K"))
        assert semantics is not None
        assert semantics.severity == "unknown"


# =========================================================================
# Domain Facts
# =========================================================================


class TestDomainFacts:
    """Tests for the 12 curated domain facts."""

    def test_twelve_facts_exist(self):
        """Exactly 12 domain facts per MUA-003 Section 6."""
        assert len(DOMAIN_FACTS) == 12

    def test_all_facts_have_provenance(self):
        """Every fact must trace to a standard section."""
        for key, fact in DOMAIN_FACTS.items():
            assert fact.source, f"Fact {key} has no source"
            assert fact.used_in, f"Fact {key} has no used_in"

    def test_get_fact_by_key(self):
        """get_fact retrieves correct fact."""
        fact = get_fact("FS_TEST_SCOPE")
        assert "hydrazine" in fact.fact.lower() or "N2H4" in fact.fact

    def test_get_fact_text_by_key(self):
        """get_fact_text returns just the text."""
        text = get_fact_text("FLAM_TEST_SCOPE")
        assert isinstance(text, str)
        assert len(text) > 0

    def test_missing_key_raises(self):
        """Missing key should raise KeyError."""
        with pytest.raises(KeyError):
            get_fact("NONEXISTENT_KEY")

    def test_key_facts_for_pipeline(self):
        """Key facts used by Steps 3-4 exist and are meaningful."""
        # Step 3 facts
        assert "TOX_APPLICABILITY" in DOMAIN_FACTS
        assert "TVS_APPLICABILITY" in DOMAIN_FACTS
        # Step 4 facts
        assert "FS_TEST_SCOPE" in DOMAIN_FACTS
        assert "FLAM_TEST_SCOPE" in DOMAIN_FACTS
        # H2 facts
        assert "H2_IS_HAZARDOUS_FLUID" in DOMAIN_FACTS
        assert "H2_EMBRITTLEMENT_MUA_REQUIRED" in DOMAIN_FACTS
        # Category facts
        assert "CAT_I_DEFINITION" in DOMAIN_FACTS
        assert "CAT_II_DEFINITION" in DOMAIN_FACTS


# =========================================================================
# Rationale Generation (Steps 7-8)
# =========================================================================


class TestRationaleGeneration:
    """Tests for template-based rationale rendering."""

    def test_thin_screening_rationale_structure(self):
        """THIN_SCREENING rationale mentions gap and why it doesn't matter."""
        result = classify_mua(
            maptis_code="10392", issue_key="FS", rating="U",
            material_class="metal", media="GH2",
        )
        rationale = render_rationale(result, material_name="A286 CRES")
        assert "U" in rationale or "untested" in rationale.lower()
        assert "GH2" in rationale or "hydrogen" in rationale.lower()
        assert "H2COMPAT" in rationale or "companion" in rationale.lower() or "MPR" in rationale

    def test_anti_rule_rationale_structure(self):
        """ANTI_RULE rationale mentions failure mode and why not credible."""
        result = classify_mua(
            maptis_code="54223", issue_key="FLAM", rating="C",
            material_class="metal", media="GH2",
        )
        rationale = render_rationale(result, material_name="7075 AL")
        assert "C" in rationale
        assert "oxygen" in rationale.lower() or "O2" in rationale or "not credible" in rationale.lower()

    def test_incomplete_pass_rationale_structure(self):
        """INCOMPLETE_PASS rationale mentions favorable data and admin nature."""
        result = classify_mua(
            maptis_code="55962", issue_key="FLAM", rating="I",
            material_class="metal", media="GH2",
        )
        rationale = render_rationale(result, material_name="Inconel 718")
        assert "favorable" in rationale.lower() or "acceptance criteria" in rationale.lower()
        assert "administrative" in rationale.lower() or "sample count" in rationale.lower()

    def test_real_gap_rationale_mentions_testing(self):
        """REAL_GAP rationale must propose testing/qualification."""
        result = classify_mua(
            maptis_code="10392", issue_key="FS", rating="U",
            material_class="metal", media="N2H4",
        )
        rationale = render_rationale(result, material_name="A286 CRES")
        assert "test" in rationale.lower() or "qualification" in rationale.lower()

    def test_real_problem_rationale_mentions_credible(self):
        """REAL_PROBLEM rationale must state the failure mode IS credible."""
        result = classify_mua(
            maptis_code="54223", issue_key="FLAM", rating="C",
            material_class="metal", media="GOX",
        )
        rationale = render_rationale(result, material_name="7075 AL")
        assert "credible" in rationale.lower() or "engineering judgment" in rationale.lower()

    def test_rationale_not_self_referential(self):
        """Rationale must never cite system-generated text as evidence."""
        result = classify_mua(
            maptis_code="10392", issue_key="FS", rating="U",
            material_class="metal", media="GH2",
        )
        rationale = render_rationale(result, material_name="A286 CRES")
        assert "this system" not in rationale.lower()
        assert "our analysis" not in rationale.lower()
        assert "we determined" not in rationale.lower()

    def test_disposition_text_per_type(self):
        """Disposition text should be appropriate for each type."""
        thin = classify_mua("10392", "FS", "U", "metal", "GH2")
        assert "Accepted" in render_disposition(thin)

        anti = classify_mua("54223", "FLAM", "C", "metal", "GH2")
        assert "Accepted" in render_disposition(anti)

        real_gap = classify_mua("10392", "FS", "U", "metal", "N2H4")
        assert "DEFERRED" in render_disposition(real_gap)

        real_problem = classify_mua("54223", "FLAM", "C", "metal", "GOX")
        assert "PENDING" in render_disposition(real_problem)

        standard = classify_mua("10392", "FLAM", "A", "metal", "GH2")
        assert "NO MUA REQUIRED" in render_disposition(standard)


# =========================================================================
# Grouping Logic
# =========================================================================


class TestGroupingLogic:
    """Tests for MAPTIS code + issue key grouping."""

    def test_same_code_same_issue_grouped(self):
        """Multiple parts with same MAPTIS code + issue = one MUA group."""
        rows = [
            {"maptis_code": "10392", "issue_key": "FS", "rating": "U",
             "material_class": "metal", "media": "GH2",
             "designation": "A286 CRES", "part_number": "PN-001"},
            {"maptis_code": "10392", "issue_key": "FS", "rating": "U",
             "material_class": "metal", "media": "GH2",
             "designation": "A286 CRES", "part_number": "PN-002"},
            {"maptis_code": "10392", "issue_key": "FS", "rating": "U",
             "material_class": "metal", "media": "GH2",
             "designation": "A286 CRES", "part_number": "PN-003"},
        ]
        groups = group_by_maptis_issue(rows)
        assert len(groups) == 1
        assert groups[0].maptis_code == "10392"
        assert groups[0].part_count == 3
        assert set(groups[0].part_numbers) == {"PN-001", "PN-002", "PN-003"}

    def test_different_issues_separate_groups(self):
        """Same MAPTIS code but different issues = separate MUA groups."""
        rows = [
            {"maptis_code": "10727", "issue_key": "FLAM", "rating": "C",
             "material_class": "metal", "media": "GH2",
             "designation": "Inconel 625", "part_number": "PN-001"},
            {"maptis_code": "10727", "issue_key": "FS", "rating": "U",
             "material_class": "metal", "media": "GH2",
             "designation": "Inconel 625", "part_number": "PN-001"},
        ]
        groups = group_by_maptis_issue(rows)
        assert len(groups) == 2
        issue_keys = {g.issue_key for g in groups}
        assert issue_keys == {"FLAM", "FS"}

    def test_different_codes_separate_groups(self):
        """Different MAPTIS codes with same issue = separate MUA groups."""
        rows = [
            {"maptis_code": "10520", "issue_key": "FS", "rating": "U",
             "material_class": "metal", "media": "GH2",
             "designation": "302/304 SST"},
            {"maptis_code": "50769", "issue_key": "FS", "rating": "U",
             "material_class": "metal", "media": "GH2",
             "designation": "302/304 SST"},
        ]
        groups = group_by_maptis_issue(rows)
        assert len(groups) == 2

    def test_many_parts_reduce_to_few_groups(self):
        """130 line items reduce to few MUAs."""
        rows = []
        for i in range(50):
            rows.append({
                "maptis_code": "10392", "issue_key": "FS", "rating": "U",
                "material_class": "metal", "media": "GH2",
                "designation": "A286 CRES", "part_number": f"A286-{i:03d}",
            })
        for i in range(30):
            rows.append({
                "maptis_code": "50784", "issue_key": "FS", "rating": "U",
                "material_class": "metal", "media": "GH2",
                "designation": "304 CRES", "part_number": f"304-{i:03d}",
            })
        for i in range(20):
            rows.append({
                "maptis_code": "10727", "issue_key": "FLAM", "rating": "C",
                "material_class": "metal", "media": "GH2",
                "designation": "Inconel 625", "part_number": f"INC-{i:03d}",
            })
        groups = group_by_maptis_issue(rows)
        assert len(groups) == 3
        total_parts = sum(g.part_count for g in groups)
        assert total_parts == 100

    def test_standard_rating_excluded(self):
        """Inapplicable screening groups should be excluded."""
        rows = [
            {"maptis_code": "10392", "issue_key": "TOX", "rating": "U",
             "material_class": "metal", "media": "GH2",
             "designation": "A286 CRES", "part_number": "PN-001"},
        ]
        groups = group_by_maptis_issue(rows)
        assert len(groups) == 0


# =========================================================================
# Pipeline Orchestration
# =========================================================================


class TestPipeline:
    """Tests for the full pipeline orchestration (Steps 1-8)."""

    def test_process_single_flag_automatable(self):
        """Single automatable flag produces ClassifierResult + Form 551."""
        result, form = process_single_flag(
            maptis_code="10392", issue_key="FS", rating="U",
            material_class="metal", media="GH2",
            material_designation="A286 CRES",
        )
        assert result.mua_type == MUAType.THIN_SCREENING
        assert result.automatable is True
        assert form is not None
        assert form.issue == "FS"
        assert form.rating == "U"
        assert form.rationale != ""
        assert form.disposition != ""
        assert form.category == "II"

    def test_process_single_flag_not_automatable(self):
        """Non-automatable flag produces ClassifierResult but no Form 551."""
        result, form = process_single_flag(
            maptis_code="54223", issue_key="FLAM", rating="C",
            material_class="metal", media="GOX",
            material_designation="7075 AL",
        )
        assert result.mua_type == MUAType.REAL_PROBLEM
        assert result.automatable is False
        assert form is None

    def test_process_miul_row_multiple_flags(self):
        """MIUL row with multiple non-passing ratings produces multiple flags."""
        ratings = {
            "FLAM": "C", "FS": "U", "SCC": "A",
            "CORR": "A", "TVS": "A", "TOX": "A",
        }
        pipeline_result = process_miul_row(
            ratings=ratings, maptis_code="54223",
            material_designation="7075 AL", material_class="metal",
            media="GH2",
        )
        assert isinstance(pipeline_result, PipelineResult)
        assert pipeline_result.total_flags == 2
        assert pipeline_result.automatable_count == 2  # Both ANTI_RULE and THIN_SCREENING
        assert len(pipeline_result.forms) == 2
        assert pipeline_result.human_required_count == 0

    def test_process_miul_row_all_pass(self):
        """MIUL row with all A ratings produces no flags."""
        ratings = {
            "FLAM": "A", "FS": "A", "SCC": "A",
            "CORR": "A", "TVS": "A", "TOX": "A",
        }
        pipeline_result = process_miul_row(
            ratings=ratings, maptis_code="10392",
            material_designation="A286 CRES", material_class="metal",
            media="GH2",
        )
        assert pipeline_result.total_flags == 0
        assert pipeline_result.automatable_count == 0

    def test_process_miul_row_human_required(self):
        """MIUL row with credible failure produces human-required flag."""
        ratings = {
            "FLAM": "C", "FS": "A", "SCC": "A",
            "CORR": "A", "TVS": "A", "TOX": "A",
        }
        pipeline_result = process_miul_row(
            ratings=ratings, maptis_code="54223",
            material_designation="7075 AL", material_class="metal",
            media="GOX",
        )
        assert pipeline_result.total_flags == 1
        assert pipeline_result.human_required_count == 1
        assert len(pipeline_result.human_required) == 1
        assert pipeline_result.human_required[0].mua_type == MUAType.REAL_PROBLEM

    def test_process_miul_row_infers_material_class(self):
        """Pipeline infers material class from designation if not provided."""
        ratings = {"FLAM": "C", "FS": "U", "SCC": "A", "CORR": "A", "TVS": "A", "TOX": "A"}
        pipeline_result = process_miul_row(
            ratings=ratings, maptis_code="54223",
            material_designation="7075-T651 AL",
            material_class=None,  # Should infer METAL
            media="GH2",
        )
        assert pipeline_result.material_class == MaterialClassEnum.METAL
        assert pipeline_result.total_flags == 2

    def test_process_miul_batch(self):
        """Batch processing of multiple MIUL rows."""
        rows = [
            {
                "maptis_code": "10392",
                "designation": "A286 CRES",
                "material_class": "metal",
                "media": "GH2",
                "FLAM": "A", "FS": "U", "SCC": "A",
                "CORR": "A", "TVS": "A", "TOX": "A",
            },
            {
                "maptis_code": "54223",
                "designation": "7075 AL",
                "material_class": "metal",
                "media": "GH2",
                "FLAM": "C", "FS": "A", "SCC": "A",
                "CORR": "A", "TVS": "A", "TOX": "A",
            },
        ]
        results = process_miul_batch(rows)
        assert len(results) == 2
        assert results[0].total_flags == 1  # FS=U
        assert results[1].total_flags == 1  # FLAM=C

    def test_form_551_fields_populated(self):
        """Form 551 fields are correctly populated."""
        result, form = process_single_flag(
            maptis_code="10392", issue_key="FS", rating="U",
            material_class="metal", media="GH2",
            material_designation="A286 CRES",
            material_specification="AMS 5731",
            part_numbers=["PN-001", "PN-002"],
            part_count=2,
            project="DMLLV",
            system="10-Inch H2 Valve",
        )
        assert form is not None
        assert form.material_designation == "A286 CRES"
        assert form.maptis_code == "10392"
        assert form.material_specification == "AMS 5731"
        assert form.project == "DMLLV"
        assert form.system == "10-Inch H2 Valve"
        assert form.part_count == 2
        assert "PN-001" in form.part_numbers
        assert form.governing_standard == "NASA-STD-6016C"


# =========================================================================
# H2COMPAT and B-Rating
# =========================================================================


class TestH2CompatAndBRating:
    """Tests for H2COMPAT and B-rating handling."""

    def test_h2compat_screening_metal_only(self):
        """H2COMPAT applies to metals only per MPR 192/193."""
        assert is_screening_applicable("H2COMPAT", "metal").applicable is True
        assert is_screening_applicable("H2COMPAT", "nonmetallic").applicable is False

    def test_companion_ref_set_for_h2_thin_screening(self):
        """THIN_SCREENING in H2 must reference H2COMPAT companion MUA."""
        result = classify_mua(
            maptis_code="10392", issue_key="FS", rating="U",
            material_class="metal", media="GH2",
        )
        assert result.companion_mua_ref is not None
        assert "H2COMPAT" in result.companion_mua_ref or "MPR" in result.companion_mua_ref

    def test_companion_ref_set_for_h2_anti_rule(self):
        """ANTI_RULE in H2 must reference H2COMPAT companion MUA."""
        result = classify_mua(
            maptis_code="54223", issue_key="FLAM", rating="C",
            material_class="metal", media="GH2",
        )
        assert result.companion_mua_ref is not None

    def test_companion_ref_set_for_h2_incomplete_pass(self):
        """INCOMPLETE_PASS in H2 should reference companion."""
        result = classify_mua(
            maptis_code="55962", issue_key="FLAM", rating="I",
            material_class="metal", media="GH2",
        )
        assert result.companion_mua_ref is not None

    def test_no_companion_ref_for_non_h2(self):
        """Non-H2 service should not reference H2COMPAT."""
        result = classify_mua(
            maptis_code="10392", issue_key="FLAM", rating="C",
            material_class="metal", media="AIR",
        )
        assert result.companion_mua_ref is None


# =========================================================================
# Batch Classification
# =========================================================================


class TestBatchClassification:
    """Tests for batch classification API."""

    def test_batch_preserves_order(self):
        """Batch results must match input order."""
        items = [
            {"maptis_code": "10392", "issue_key": "FS", "rating": "U",
             "material_class": "metal", "media": "GH2"},
            {"maptis_code": "54223", "issue_key": "FLAM", "rating": "C",
             "material_class": "metal", "media": "GH2"},
            {"maptis_code": "55962", "issue_key": "FLAM", "rating": "I",
             "material_class": "metal", "media": "GH2"},
        ]
        results = classify_mua_batch(items)
        assert len(results) == 3
        assert results[0].mua_type == MUAType.THIN_SCREENING
        assert results[1].mua_type == MUAType.ANTI_RULE
        assert results[2].mua_type == MUAType.INCOMPLETE_PASS

    def test_batch_handles_mixed_types(self):
        """Batch should handle a mix of types."""
        items = [
            {"maptis_code": "10392", "issue_key": "FS", "rating": "A",
             "material_class": "metal", "media": "GH2"},
            {"maptis_code": "51382", "issue_key": "TOX", "rating": "U",
             "material_class": "metal", "media": "GH2"},
            {"maptis_code": "10392", "issue_key": "FS", "rating": "U",
             "material_class": "metal", "media": "N2H4"},
        ]
        results = classify_mua_batch(items)
        assert results[0].mua_type == MUAType.STANDARD       # A rating
        assert results[1].screening_applicable is False        # TOX on metal
        assert results[2].mua_type == MUAType.REAL_GAP        # FS=U in hydrazine


# =========================================================================
# Edge Cases
# =========================================================================


class TestEdgeCases:
    """Edge cases and boundary conditions."""

    def test_flam_c_in_air_normal_o2_is_anti_rule(self):
        """FLAM=C in air at normal O2 (20.9%) — below enrichment → ANTI_RULE."""
        result = classify_mua(
            maptis_code="54223", issue_key="FLAM", rating="C",
            material_class="metal", media="AIR", o2_percent=20.9,
        )
        assert result.mua_type == MUAType.ANTI_RULE

    def test_flam_c_at_threshold_o2(self):
        """FLAM=C at exactly 23.5% O2 = enriched = REAL_PROBLEM."""
        result = classify_mua(
            maptis_code="54223", issue_key="FLAM", rating="C",
            material_class="metal", media="AIR", o2_percent=23.5,
        )
        assert result.mua_type == MUAType.REAL_PROBLEM

    def test_unknown_issue_key_handled(self):
        """Unknown issue key should still run through the decision tree."""
        result = classify_mua(
            maptis_code="12345", issue_key="UNKNOWN", rating="C",
            material_class="metal", media="GH2",
        )
        assert result.mua_type in (MUAType.ANTI_RULE, MUAType.REAL_PROBLEM, MUAType.FLAG_FOR_HUMAN)

    def test_rating_case_insensitive(self):
        """Ratings should be case-insensitive."""
        r1 = classify_mua("10392", "FS", "u", "metal", "GH2")
        r2 = classify_mua("10392", "FS", "U", "metal", "GH2")
        assert r1.mua_type == r2.mua_type

    def test_classifier_result_serializable(self):
        """ClassifierResult should be JSON-serializable via Pydantic."""
        result = classify_mua(
            maptis_code="10392", issue_key="FS", rating="U",
            material_class="metal", media="GH2",
        )
        data = result.model_dump()
        assert isinstance(data, dict)
        assert data["mua_type"] == "THIN_SCREENING"
        assert data["category"] == "II"
        assert data["flag_type"] == "NO_DATA"
        assert data["hazard_applies"] is False
        assert data["automatable"] is True

    def test_pipeline_result_serializable(self):
        """PipelineResult should be JSON-serializable via Pydantic."""
        ratings = {"FLAM": "C", "FS": "U", "SCC": "A", "CORR": "A", "TVS": "A", "TOX": "A"}
        pipeline_result = process_miul_row(
            ratings=ratings, maptis_code="54223",
            material_designation="7075 AL", material_class="metal",
            media="GH2",
        )
        data = pipeline_result.model_dump()
        assert isinstance(data, dict)
        assert data["total_flags"] == 2

    def test_form551_fields_model(self):
        """Form551Fields model should accept all required fields."""
        form = Form551Fields(
            mua_number="MUA-DMLLV-001",
            category="II",
            date="2026-02-28",
            project="DMLLV",
            system="10-Inch H2 Valve, In-Space Refueling",
            material_designation="A286 CRES",
            maptis_code="10392",
            issue="FS",
            rating="U",
            part_numbers=["PN-001", "PN-002", "PN-003"],
            part_count=3,
            media="GH2",
            location="non-habitable",
            rationale="Test rationale text.",
            disposition="ACCEPTED",
        )
        assert form.mua_number == "MUA-DMLLV-001"
        assert form.part_count == 3
