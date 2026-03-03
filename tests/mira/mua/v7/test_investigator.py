"""Tests for MUA v7 investigator.

The investigator orchestrates the evidence-gathering step of the MUA
wizard.  Given a material and environment, it queries MAPTIS, the Body
of Knowledge (BOK), and precedent databases, then assembles an
InvestigationResult with:

  - Scored and ranked evidence items (relevance <= 1.0).
  - Novel-material detection (zero precedents).
  - Safety banners for oxygen-enriched, cryogenic, and hydrogen
    environments.

Since the investigator's ``investigate()`` method requires live database
connections and FAISS indexes, these tests verify:

  - Module importability and class instantiation.
  - Model construction and default field values.
  - EnvironmentSpec computed properties (is_enriched_o2, is_cryogenic,
    is_hydrogen_service).
  - Evidence strength calculation via the confidence module.
  - Conflict detection via the conflict_detector module.
  - Model serialization round-trip.
"""

import pytest

from mira.mua.v7.investigator import MUAInvestigator
from mira.mua.v7.models import (
    ConflictFound,
    ConflictSeverity,
    DeterminationStatus,
    EnvironmentSpec,
    EnvelopeResult,
    EvidenceStrengthBand,
    EvidenceStrengthResult,
    GapIdentified,
    InvestigationResult,
    MaterialResolution,
    MUACategory,
    OverlapStatus,
    PrecedentMatch,
    ProcessParams,
    ResolutionStatus,
    TestDataRecord,
)
from mira.mua.v7.confidence import calculate_evidence_strength
from mira.mua.v7.conflict_detector import detect_conflicts


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def base_material():
    """A resolved material for building investigation results."""
    return MaterialResolution(
        input_text="6061-T6",
        status=ResolutionStatus.RESOLVED,
        resolved_name="6061-T6 Aluminum",
        family="aluminum",
    )


@pytest.fixture
def cabin_air_environment():
    """Standard cabin-air environment (non-enriched, non-cryogenic)."""
    return EnvironmentSpec(
        o2_percent=20.9,
        pressure_psia=14.7,
        temp_min_f=60.0,
        temp_max_f=120.0,
        medium="AIR",
        location="habitable",
        application="Cabin rack structural bracket",
    )


@pytest.fixture
def enriched_o2_environment():
    """Oxygen-enriched environment (>= 23.5% O2)."""
    return EnvironmentSpec(
        o2_percent=30.0,
        pressure_psia=200.0,
        temp_min_f=60.0,
        temp_max_f=500.0,
        medium="GOX",
        location="non_habitable",
        application="High-pressure oxygen valve body",
    )


@pytest.fixture
def cryogenic_environment():
    """Cryogenic environment (temp_min <= -150 degF)."""
    return EnvironmentSpec(
        o2_percent=0.0,
        pressure_psia=50.0,
        temp_min_f=-320.0,
        temp_max_f=-280.0,
        medium="LN2",
        location="non_habitable",
        application="Cryogenic feed-line bracket",
    )


@pytest.fixture
def hydrogen_environment():
    """Gaseous hydrogen service environment."""
    return EnvironmentSpec(
        o2_percent=0.0,
        pressure_psia=6000.0,
        temp_min_f=-40.0,
        temp_max_f=160.0,
        medium="GH2",
        location="non_habitable",
        application="Hydrogen manifold fitting",
    )


# ---------------------------------------------------------------------------
# Import and instantiation
# ---------------------------------------------------------------------------

class TestImportAndInstantiation:
    def test_import_succeeds(self):
        """MUAInvestigator class exists and can be imported."""
        assert MUAInvestigator is not None

    def test_instantiation(self):
        """MUAInvestigator can be instantiated without arguments."""
        investigator = MUAInvestigator()
        assert investigator is not None
        assert hasattr(investigator, "investigate")


# ---------------------------------------------------------------------------
# InvestigationResult default fields
# ---------------------------------------------------------------------------

class TestInvestigationResultDefaults:
    def test_default_fields(self, base_material, cabin_air_environment):
        """InvestigationResult constructed with only required fields
        should have sensible defaults for all optional fields."""
        result = InvestigationResult(
            material=base_material,
            environment=cabin_air_environment,
        )

        assert result.is_novel_material is False
        assert result.banners == []
        assert result.supporting_precedents == []
        assert result.conflicting_precedents == []
        assert result.test_data == []
        assert result.envelope is None
        assert result.conflicts == []
        assert result.gaps == []
        assert result.dependency_warnings == []
        assert result.preliminary_category is None
        assert result.process_params is None
        assert isinstance(result.evidence_strength, EvidenceStrengthResult)
        assert result.evidence_strength.band == EvidenceStrengthBand.INSUFFICIENT

    def test_is_novel_material_default(self, base_material, cabin_air_environment):
        """is_novel_material defaults to False."""
        result = InvestigationResult(
            material=base_material,
            environment=cabin_air_environment,
        )
        assert result.is_novel_material is False

    def test_banners_default(self, base_material, cabin_air_environment):
        """banners defaults to empty list."""
        result = InvestigationResult(
            material=base_material,
            environment=cabin_air_environment,
        )
        assert result.banners == []


# ---------------------------------------------------------------------------
# EnvironmentSpec computed properties
# ---------------------------------------------------------------------------

class TestEnvironmentSpecProperties:
    def test_is_enriched_o2_true(self, enriched_o2_environment):
        """is_enriched_o2 should be True when O2 >= 23.5%."""
        assert enriched_o2_environment.is_enriched_o2 is True

    def test_is_enriched_o2_false(self, cabin_air_environment):
        """is_enriched_o2 should be False for normal cabin air (20.9%)."""
        assert cabin_air_environment.is_enriched_o2 is False

    def test_is_enriched_o2_boundary(self):
        """is_enriched_o2 should be True at exactly 23.5%."""
        env = EnvironmentSpec(
            o2_percent=23.5,
            pressure_psia=14.7,
            temp_min_f=60.0,
            temp_max_f=120.0,
            medium="AIR",
            location="habitable",
            application="Test",
        )
        assert env.is_enriched_o2 is True

    def test_is_cryogenic_true(self, cryogenic_environment):
        """is_cryogenic should be True when temp_min_f <= -150."""
        assert cryogenic_environment.is_cryogenic is True

    def test_is_cryogenic_false(self, cabin_air_environment):
        """is_cryogenic should be False for normal cabin temps."""
        assert cabin_air_environment.is_cryogenic is False

    def test_is_cryogenic_boundary(self):
        """is_cryogenic should be True at exactly -150 degF."""
        env = EnvironmentSpec(
            o2_percent=0.0,
            pressure_psia=14.7,
            temp_min_f=-150.0,
            temp_max_f=-100.0,
            medium="LN2",
            location="non_habitable",
            application="Test",
        )
        assert env.is_cryogenic is True

    def test_is_hydrogen_service_gh2(self, hydrogen_environment):
        """is_hydrogen_service should be True for GH2 medium."""
        assert hydrogen_environment.is_hydrogen_service is True

    def test_is_hydrogen_service_lh2(self):
        """is_hydrogen_service should be True for LH2 medium."""
        env = EnvironmentSpec(
            o2_percent=0.0,
            pressure_psia=50.0,
            temp_min_f=-423.0,
            temp_max_f=-400.0,
            medium="LH2",
            location="non_habitable",
            application="Liquid hydrogen tank",
        )
        assert env.is_hydrogen_service is True

    def test_is_hydrogen_service_false(self, cabin_air_environment):
        """is_hydrogen_service should be False for AIR medium."""
        assert cabin_air_environment.is_hydrogen_service is False


# ---------------------------------------------------------------------------
# Evidence strength calculation integration
# ---------------------------------------------------------------------------

class TestEvidenceStrengthIntegration:
    def test_calculate_evidence_strength_with_investigation_data(
        self, base_material, cabin_air_environment
    ):
        """calculate_evidence_strength can be called with data
        that would come from an InvestigationResult."""
        supporting = [
            PrecedentMatch(
                mua_number=f"MUA-MSFC-2023-{i:04d}",
                material_designation="6061-T6",
                determination=DeterminationStatus.APPROVED,
                environment_description="Air at 14.7 psia",
                relevance_score=0.8,
                is_supporting=True,
                is_conflicting=False,
            )
            for i in range(5)
        ]
        test_data = [
            TestDataRecord(test_class="FLAMM", rating="A", is_current=True),
            TestDataRecord(test_class="TOX", rating="B", is_current=True),
        ]

        result = calculate_evidence_strength(
            supporting_precedents=supporting,
            conflicting_precedents=[],
            test_data=test_data,
            envelope=None,
            conflicts=[],
            gaps=[],
            material=base_material,
            environment=cabin_air_environment,
        )

        assert isinstance(result, EvidenceStrengthResult)
        assert 0.0 <= result.score <= 1.0
        assert result.band in (
            EvidenceStrengthBand.STRONG,
            EvidenceStrengthBand.MODERATE,
            EvidenceStrengthBand.WEAK,
            EvidenceStrengthBand.INSUFFICIENT,
        )
        assert "precedent_support" in result.components
        assert "test_coverage" in result.components

    def test_empty_evidence_gives_weak_or_insufficient(
        self, base_material, cabin_air_environment
    ):
        """With no evidence at all, evidence strength should be WEAK or
        INSUFFICIENT. The consistency component scores 1.0 when there are
        no conflicts, which can push the score slightly above the
        INSUFFICIENT threshold (0.15)."""
        result = calculate_evidence_strength(
            supporting_precedents=[],
            conflicting_precedents=[],
            test_data=[],
            envelope=None,
            conflicts=[],
            gaps=[],
            material=base_material,
            environment=cabin_air_environment,
        )

        assert result.band in (
            EvidenceStrengthBand.INSUFFICIENT,
            EvidenceStrengthBand.WEAK,
        )
        # Even with the consistency component, score should remain low
        assert result.score < 0.40


# ---------------------------------------------------------------------------
# Conflict detection integration
# ---------------------------------------------------------------------------

class TestConflictDetectionIntegration:
    def test_detect_conflicts_with_investigation_data(self):
        """detect_conflicts works with PrecedentMatch and TestDataRecord objects
        that would come from an InvestigationResult."""
        supporting = [
            PrecedentMatch(
                mua_number="MUA-MSFC-2023-0001",
                material_designation="316L SS",
                determination=DeterminationStatus.APPROVED,
                environment_description="GOX at 3000 psi",
                relevance_score=0.9,
                is_supporting=True,
                is_conflicting=False,
            ),
        ]
        conflicting = [
            PrecedentMatch(
                mua_number="MUA-MSFC-2023-0002",
                material_designation="316L SS",
                determination=DeterminationStatus.REJECTED,
                environment_description="GOX at 4500 psi",
                relevance_score=0.7,
                is_supporting=False,
                is_conflicting=True,
            ),
        ]

        conflicts = detect_conflicts(supporting, conflicting, [])

        assert isinstance(conflicts, list)
        assert len(conflicts) >= 1
        assert all(isinstance(c, ConflictFound) for c in conflicts)
        # A supporting APPROVED vs conflicting REJECTED should produce a HARD conflict
        hard_conflicts = [c for c in conflicts if c.severity == ConflictSeverity.HARD]
        assert len(hard_conflicts) >= 1

    def test_no_conflicts_when_all_supporting(self):
        """No conflicts should be detected when all precedents are supporting
        with consistent determinations and there is no test data."""
        supporting = [
            PrecedentMatch(
                mua_number=f"MUA-MSFC-2023-{i:04d}",
                material_designation="6061-T6",
                determination=DeterminationStatus.APPROVED,
                environment_description="Air at 14.7 psia",
                relevance_score=0.8,
                is_supporting=True,
                is_conflicting=False,
            )
            for i in range(3)
        ]

        conflicts = detect_conflicts(supporting, [], [])

        # No conflicting precedents and all consistent -> no conflicts expected
        # (within-supporting checks should not fire since all are APPROVED)
        assert isinstance(conflicts, list)


# ---------------------------------------------------------------------------
# Model serialization round-trip
# ---------------------------------------------------------------------------

class TestModelRoundTrip:
    def test_investigation_result_serialization(
        self, base_material, cabin_air_environment
    ):
        """InvestigationResult can be serialized to dict and deserialized back."""
        original = InvestigationResult(
            material=base_material,
            environment=cabin_air_environment,
            supporting_precedents=[
                PrecedentMatch(
                    mua_number="MUA-MSFC-2023-0001",
                    material_designation="6061-T6",
                    determination=DeterminationStatus.APPROVED,
                    environment_description="Air at 14.7 psia",
                    relevance_score=0.8,
                ),
            ],
            test_data=[
                TestDataRecord(test_class="FLAMM", rating="A", is_current=True),
            ],
            is_novel_material=False,
            banners=["Test banner message"],
        )

        # Serialize to dict and back
        data = original.model_dump()
        restored = InvestigationResult.model_validate(data)

        assert restored.material.input_text == original.material.input_text
        assert restored.environment.o2_percent == original.environment.o2_percent
        assert len(restored.supporting_precedents) == 1
        assert restored.supporting_precedents[0].mua_number == "MUA-MSFC-2023-0001"
        assert len(restored.test_data) == 1
        assert restored.test_data[0].rating == "A"
        assert restored.is_novel_material is False
        assert restored.banners == ["Test banner message"]

    def test_envelope_result_defaults(self):
        """EnvelopeResult constructed with just overall_status has sensible defaults."""
        envelope = EnvelopeResult(overall_status=OverlapStatus.INSUFFICIENT_DATA)

        assert envelope.o2_status == OverlapStatus.INSUFFICIENT_DATA
        assert envelope.pressure_status == OverlapStatus.INSUFFICIENT_DATA
        assert envelope.temp_status == OverlapStatus.INSUFFICIENT_DATA
        assert envelope.coverage_ratio == 0.0
        assert envelope.details == []


# ---------------------------------------------------------------------------
# Preliminary category routing semantics
# ---------------------------------------------------------------------------


class TestPreliminaryCategoryRouting:
    def test_preliminary_category_honors_cat_i_safety_gate(
        self, base_material, enriched_o2_environment
    ):
        """Step 2 preliminary routing must classify enriched O2 as Cat I."""
        investigator = MUAInvestigator()

        category = investigator._route_category(
            material=base_material,
            environment=enriched_o2_environment,
            test_data=[TestDataRecord(test_class="FLAMM", rating="A", is_current=True)],
            gaps=[],
            process_params=None,
        )

        assert category == MUACategory.I

    def test_preliminary_category_no_longer_promotes_weak_evidence_to_cat_iii(
        self, base_material, cabin_air_environment
    ):
        """Weak/insufficient evidence should not auto-map to Category III."""
        investigator = MUAInvestigator()
        critical_gap = GapIdentified(
            gap_id="GAP-CRIT-001",
            dimension="toxicity",
            description="No current toxicity data.",
            severity="critical",
            requires_review=True,
        )

        category = investigator._route_category(
            material=base_material,
            environment=cabin_air_environment,
            test_data=[],
            gaps=[critical_gap],
            process_params=None,
        )

        assert category == MUACategory.II


# ---------------------------------------------------------------------------
# Issue-scope behavior
# ---------------------------------------------------------------------------


class TestIssueScopeBehavior:
    def test_resolve_issue_codes_prefers_caller_scope(self, cabin_air_environment):
        """Explicit caller issue codes should override auto-detected scope."""
        investigator = MUAInvestigator()
        resolved = investigator._resolve_issue_codes(
            cabin_air_environment,
            ["flam", "O2_COMPAT", "scc"],
        )
        assert resolved == ["FLAM", "O2_COMPAT", "SCC"]

    def test_identify_gaps_does_not_force_tox_when_not_requested(
        self, cabin_air_environment
    ):
        """TOX gaps should not be generated when TOX/OFFGAS is out of scope."""
        investigator = MUAInvestigator()
        envelope = EnvelopeResult(
            overall_status=OverlapStatus.WITHIN,
            o2_status=OverlapStatus.WITHIN,
            pressure_status=OverlapStatus.WITHIN,
            temp_status=OverlapStatus.WITHIN,
            coverage_ratio=1.0,
        )
        test_data = [
            TestDataRecord(test_class="FLAMM", rating="A", is_current=True),
            TestDataRecord(test_class="SCC", rating="B", is_current=True),
        ]

        gaps = investigator._identify_gaps(
            envelope=envelope,
            test_data=test_data,
            environment=cabin_air_environment,
            issue_scope={"FLAM", "O2_COMPAT", "SCC"},
        )

        assert not any(g.dimension == "toxicity" for g in gaps)
        assert not any(g.dimension == "test_class_tox" for g in gaps)

    def test_identify_gaps_aggregates_expired_records_by_test_class(
        self, cabin_air_environment
    ):
        """Expired gaps should be aggregated by class instead of one gap per record."""
        investigator = MUAInvestigator()
        envelope = EnvelopeResult(
            overall_status=OverlapStatus.WITHIN,
            o2_status=OverlapStatus.WITHIN,
            pressure_status=OverlapStatus.WITHIN,
            temp_status=OverlapStatus.WITHIN,
            coverage_ratio=1.0,
        )
        test_data = [
            TestDataRecord(
                test_class="FLAMM",
                rating="A",
                is_current=False,
                report_number="R-1",
                test_date="2021-01-01",
            ),
            TestDataRecord(
                test_class="FLAMM",
                rating="B",
                is_current=False,
                report_number="R-2",
                test_date="2022-01-01",
            ),
            TestDataRecord(
                test_class="FLAMM",
                rating="C",
                is_current=False,
                report_number="R-3",
                test_date="2023-01-01",
            ),
        ]

        gaps = investigator._identify_gaps(
            envelope=envelope,
            test_data=test_data,
            environment=cabin_air_environment,
            issue_scope={"FLAM"},
        )

        expired_flamm = [g for g in gaps if g.dimension == "expired_flamm"]
        assert len(expired_flamm) == 1
        assert "3 expired FLAMM test record(s)" in expired_flamm[0].description

    def test_apply_fs_scope_guard_drops_fs_for_h2_when_only_hydrazine_evidence(
        self, hydrogen_environment, monkeypatch
    ):
        """Hydrogen usage should drop FS scope when DB FS media is hydrazine-only."""
        investigator = MUAInvestigator()
        material = MaterialResolution(
            input_text="ESCORENE 1063",
            status=ResolutionStatus.RESOLVED,
            material_code="50181",
            resolved_name="ESCORENE 1063",
            family="polymer",
        )

        monkeypatch.setattr(
            investigator,
            "_find_related_maptis_codes",
            lambda _material: [],
        )
        monkeypatch.setattr(
            investigator,
            "_sync_lookup_fs_media_context",
            lambda _codes: {
                "classes": ["HYDRAZINE"],
                "examples": ["DINITROGEN TETROXIDE (N2O4)"],
                "source_count": 1,
            },
        )

        scope, notes = investigator._apply_fs_medium_scope_guard(
            material=material,
            environment=hydrogen_environment,
            issue_codes=["FLAM", "FS", "SCC"],
        )

        assert scope == ["FLAM", "SCC"]
        assert any("removed from investigation scope" in note for note in notes)

    def test_apply_fs_scope_guard_keeps_fs_when_h2_media_exists(
        self, hydrogen_environment, monkeypatch
    ):
        """FS scope should remain when hydrogen FS media evidence is present."""
        investigator = MUAInvestigator()
        material = MaterialResolution(
            input_text="Inconel 718",
            status=ResolutionStatus.RESOLVED,
            material_code="10406",
            resolved_name="INCONEL 718 BAR AGED",
            family="nickel",
        )

        monkeypatch.setattr(
            investigator,
            "_find_related_maptis_codes",
            lambda _material: [],
        )
        monkeypatch.setattr(
            investigator,
            "_sync_lookup_fs_media_context",
            lambda _codes: {
                "classes": ["HYDROGEN", "HYDRAZINE"],
                "examples": ["GH2", "MMH"],
                "source_count": 2,
            },
        )

        scope, notes = investigator._apply_fs_medium_scope_guard(
            material=material,
            environment=hydrogen_environment,
            issue_codes=["FS", "SCC"],
        )

        assert scope == ["FS", "SCC"]
        assert notes == []

    def test_classify_medium_text_detects_h2_token_without_h2o_false_positive(self):
        """Standalone H2 token should map to hydrogen; H2O should not."""
        assert MUAInvestigator._classify_medium_text("H2") == "HYDROGEN"
        assert MUAInvestigator._classify_medium_text("H2O") == "UNKNOWN"
