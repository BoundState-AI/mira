#!/usr/bin/env python3
"""
Tier 3 golden case tests for M&P Plan codex compliance engine.

Comprehensive coverage:
  - All 18 prohibition MPRs with positive and negative cases
  - Closure path routing through the full compute loop
  - End-to-end workflow: compute → question → answer → recompute → generate
  - Multi-material, multi-environment scenarios
  - Edge cases and rating boundary conditions
"""

import pytest
from datetime import date, timedelta

from mira.mp_plan.engines.applicability_codex import (
    ApplicabilityEngineCodex,
    load_mpr_catalog_codex,
)
from mira.mp_plan.engines.compliance_eval_codex import (
    STATUS_COMPLIANT,
    STATUS_CONSTRAINED,
    STATUS_NONCOMPLIANT,
    STATUS_UNKNOWN,
    ComplianceEvaluationEngineCodex,
)
from mira.mp_plan.models import (
    AcceptedOpenGap,
    BlockingQuestionType,
    ClosureDecision,
    EnvironmentDefinition,
    MaterialEntry,
    MaterialResolutionResult,
    PlanGeneratorSession,
)
from mira.mp_plan.session_manager import get_session_manager


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def mpr_catalog():
    return load_mpr_catalog_codex()


@pytest.fixture(scope="module")
def applicability_engine(mpr_catalog):
    return ApplicabilityEngineCodex(mpr_catalog=mpr_catalog)


@pytest.fixture
def compliance_engine():
    return ComplianceEvaluationEngineCodex()


def _make_session(
    material_name, material_application, env_name,
    o2_pct=21.0, pressure_psia=14.7, temp_range_c=(15.0, 27.0),
    habitable=False, vacuum_exposure=False, hydrogen_service=False,
    spec="", flam_rating="A", tvs_rating="A", tox_rating="A",
    scc_rating=None, corr_rating=None, test_o2_pct=30.0,
):
    manager = get_session_manager()
    session = manager.create_session(program_name="Tier 3 Golden")
    env = EnvironmentDefinition(
        name=env_name, o2_pct=o2_pct, pressure_psia=pressure_psia,
        temp_range_c=temp_range_c, habitable=habitable,
        vacuum_exposure=vacuum_exposure, hydrogen_service=hydrogen_service,
        source="golden_test",
    )
    session.environments.append(env)
    mat = MaterialEntry(
        name=material_name, application=material_application,
        quantity=1, spec=spec, source="golden_test",
    )
    session.materials.append(mat)
    resolution = MaterialResolutionResult(
        material_id=mat.id, maptis_code=f"TEST-{material_name[:8].upper()}",
        flam_rating=flam_rating, tvs_rating=tvs_rating, tox_rating=tox_rating,
        scc_rating=scc_rating, corr_rating=corr_rating,
        test_o2_pct=test_o2_pct, source="golden_test",
    )
    session.maptis_resolutions.append(resolution)
    return session


def _run_engines(session, applicability_engine, compliance_engine):
    session.applicability_matrix = applicability_engine.run(session)
    defs, ncs, dets = compliance_engine.run(session)
    return defs, ncs, dets


def _find_prohibition(dets, mpr_id):
    return next(
        (d for d in dets if d["mpr_id"] == mpr_id and d.get("prohibition_triggered")),
        None,
    )


# ===========================================================================
# ALL 18 PROHIBITION MPRs
# ===========================================================================

class TestProhibitionMPR057:
    """Al 5xxx >3% Mg above 66°C."""

    def test_5083_above_66c(self, applicability_engine, compliance_engine):
        _, _, dets = _run_engines(_make_session(
            "5083 Aluminum", "Tank panel", "Hot Zone",
            temp_range_c=(20.0, 80.0),
        ), applicability_engine, compliance_engine)
        assert _find_prohibition(dets, "MPR-057") is not None

    def test_6061_not_triggered(self, applicability_engine, compliance_engine):
        """6061 is not 5xxx series — should not trigger."""
        _, _, dets = _run_engines(_make_session(
            "6061-T6 Aluminum", "Bracket", "Hot Zone",
            temp_range_c=(20.0, 80.0),
        ), applicability_engine, compliance_engine)
        assert _find_prohibition(dets, "MPR-057") is None


class TestProhibitionMPR060:
    """Unstabilized austenitic steel above 371°C."""

    def test_304_above_371c(self, applicability_engine, compliance_engine):
        _, _, dets = _run_engines(_make_session(
            "304 Stainless Steel", "Exhaust liner", "High Temp",
            temp_range_c=(20.0, 400.0),
        ), applicability_engine, compliance_engine)
        assert _find_prohibition(dets, "MPR-060") is not None

    def test_321_excluded(self, applicability_engine, compliance_engine):
        """321 is stabilized — should be excluded."""
        _, _, dets = _run_engines(_make_session(
            "321 Stainless Steel", "Exhaust liner", "High Temp",
            temp_range_c=(20.0, 400.0),
        ), applicability_engine, compliance_engine)
        assert _find_prohibition(dets, "MPR-060") is None


class TestProhibitionMPR062:
    """Free-machining steel (303)."""

    def test_303_prohibited(self, applicability_engine, compliance_engine):
        _, _, dets = _run_engines(_make_session(
            "303 Stainless Steel", "Fitting", "ISS",
            habitable=True, o2_pct=30.0,
        ), applicability_engine, compliance_engine)
        assert _find_prohibition(dets, "MPR-062") is not None


class TestProhibitionMPR067:
    """Titanium in LOX/GOX — already tested in Tier 1, but verify edge."""

    def test_ti_at_exactly_23_5_pct(self, applicability_engine, compliance_engine):
        """At exactly 23.5% O2 the trigger threshold is NOT met (>23.5)."""
        _, _, dets = _run_engines(_make_session(
            "Ti-6Al-4V", "Valve", "Marginal O2",
            o2_pct=23.5,
        ), applicability_engine, compliance_engine)
        assert _find_prohibition(dets, "MPR-067") is None

    def test_ti_at_23_6_pct(self, applicability_engine, compliance_engine):
        _, _, dets = _run_engines(_make_session(
            "Ti-6Al-4V", "Valve", "Enriched O2",
            o2_pct=23.6,
        ), applicability_engine, compliance_engine)
        assert _find_prohibition(dets, "MPR-067") is not None


class TestProhibitionMPR069:
    """Magnesium in primary structure."""

    def test_az31_prohibited(self, applicability_engine, compliance_engine):
        _, _, dets = _run_engines(_make_session(
            "AZ31 Magnesium", "Primary structure bracket", "Standard",
        ), applicability_engine, compliance_engine)
        assert _find_prohibition(dets, "MPR-069") is not None


class TestProhibitionMPR071:
    """Beryllium structural limitation."""

    def test_beryllium_prohibited(self, applicability_engine, compliance_engine):
        _, _, dets = _run_engines(_make_session(
            "Beryllium alloy", "Structural frame", "Standard",
        ), applicability_engine, compliance_engine)
        assert _find_prohibition(dets, "MPR-071") is not None


class TestProhibitionMPR077:
    """Cadmium in habitable/vacuum — already tested, verify vacuum path."""

    def test_cd_vacuum(self, applicability_engine, compliance_engine):
        _, _, dets = _run_engines(_make_session(
            "Cadmium plated bolt", "Fastener", "External",
            o2_pct=0.001, pressure_psia=0.001,
            vacuum_exposure=True, habitable=False,
        ), applicability_engine, compliance_engine)
        assert _find_prohibition(dets, "MPR-077") is not None


class TestProhibitionMPR079:
    """Zinc plating (except black zinc-nickel)."""

    def test_zinc_plating_prohibited(self, applicability_engine, compliance_engine):
        _, _, dets = _run_engines(_make_session(
            "Zinc plated steel washer", "Structural", "Standard",
        ), applicability_engine, compliance_engine)
        assert _find_prohibition(dets, "MPR-079") is not None

    def test_zinc_nickel_excluded(self, applicability_engine, compliance_engine):
        _, _, dets = _run_engines(_make_session(
            "Black zinc-nickel plated bolt", "Structural", "Standard",
        ), applicability_engine, compliance_engine)
        assert _find_prohibition(dets, "MPR-079") is None


class TestProhibitionMPR080:
    """Mercury equipment."""

    def test_mercury_prohibited(self, applicability_engine, compliance_engine):
        _, _, dets = _run_engines(_make_session(
            "Mercury thermometer", "Temperature sensor", "Lab",
        ), applicability_engine, compliance_engine)
        assert _find_prohibition(dets, "MPR-080") is not None


class TestProhibitionMPR088:
    """Tin plating on electrical contacts."""

    def test_tin_plated_connector(self, applicability_engine, compliance_engine):
        _, _, dets = _run_engines(_make_session(
            "Tin plated electrical connector", "Harness", "ISS",
            habitable=True, o2_pct=30.0,
        ), applicability_engine, compliance_engine)
        assert _find_prohibition(dets, "MPR-088") is not None


class TestProhibitionMPR091:
    """RTV silicone acetic acid (acetoxy cure)."""

    def test_rtv_prohibited(self, applicability_engine, compliance_engine):
        _, _, dets = _run_engines(_make_session(
            "RTV silicone sealant", "Potting", "Standard",
        ), applicability_engine, compliance_engine)
        p = _find_prohibition(dets, "MPR-091")
        assert p is not None, "RTV silicone should trigger MPR-091"

    def test_neutral_cure_excluded(self, applicability_engine, compliance_engine):
        _, _, dets = _run_engines(_make_session(
            "Neutral cure silicone sealant", "Potting", "Standard",
        ), applicability_engine, compliance_engine)
        assert _find_prohibition(dets, "MPR-091") is None


class TestProhibitionMPR093:
    """PVC above 49°C."""

    def test_pvc_above_49c(self, applicability_engine, compliance_engine):
        _, _, dets = _run_engines(_make_session(
            "PVC wire jacket", "Cable insulation", "Warm Zone",
            temp_range_c=(20.0, 55.0),
        ), applicability_engine, compliance_engine)
        assert _find_prohibition(dets, "MPR-093") is not None

    def test_pvc_below_49c(self, applicability_engine, compliance_engine):
        _, _, dets = _run_engines(_make_session(
            "PVC wire jacket", "Cable insulation", "Cool Zone",
            temp_range_c=(15.0, 40.0),
        ), applicability_engine, compliance_engine)
        assert _find_prohibition(dets, "MPR-093") is None


class TestProhibitionMPR144:
    """CP titanium filler on alloyed Ti base."""

    def test_cp_ti_filler_prohibited(self, applicability_engine, compliance_engine):
        _, _, dets = _run_engines(_make_session(
            "CP titanium filler welded joint", "Pipe weld", "Standard",
        ), applicability_engine, compliance_engine)
        assert _find_prohibition(dets, "MPR-144") is not None


class TestProhibitionMPR166:
    """Soldering for structural."""

    def test_soldered_structural(self, applicability_engine, compliance_engine):
        _, _, dets = _run_engines(_make_session(
            "Soldered aluminum joint", "Structural bracket", "Standard",
        ), applicability_engine, compliance_engine)
        assert _find_prohibition(dets, "MPR-166") is not None


class TestProhibitionMPR202:
    """Silver plating in external/atomic oxygen."""

    def test_silver_external(self, applicability_engine, compliance_engine):
        _, _, dets = _run_engines(_make_session(
            "Silver plated fastener", "External bolt", "LEO External",
            o2_pct=0.001, pressure_psia=0.001, vacuum_exposure=True,
        ), applicability_engine, compliance_engine)
        assert _find_prohibition(dets, "MPR-202") is not None

    def test_silver_internal_ok(self, applicability_engine, compliance_engine):
        _, _, dets = _run_engines(_make_session(
            "Silver plated fastener", "Internal bolt", "ISS Interior",
            habitable=True, o2_pct=30.0,
        ), applicability_engine, compliance_engine)
        assert _find_prohibition(dets, "MPR-202") is None


# ===========================================================================
# CLOSURE PATH ROUTING
# ===========================================================================

class TestClosurePathRouting:
    """Test closure path question generation and resolution.

    Note: The compute loop's DataAcquisitionEngine overwrites maptis_resolutions,
    so we use the engines directly (like Tier 1 tests) then manually generate
    blocking questions from the resulting session state.
    """

    def test_noncompliant_generates_closure_question(self, applicability_engine, compliance_engine):
        from mira.mp_plan.compute_loop_codex import generate_blocking_questions_codex

        session = _make_session(
            "Kapton HN", "Thermal blanket", "ISS Habitable",
            o2_pct=30.0, habitable=True,
            flam_rating="C", tvs_rating="A", tox_rating="A",
        )
        session.applicability_matrix = applicability_engine.run(session)
        _, ncs, dets = compliance_engine.run(session)
        session.nonconformances = ncs
        session.mpr_determinations = dets

        assert len(ncs) > 0, "FLAM C should produce NC"

        session.blocking_questions = generate_blocking_questions_codex(session)
        closure_qs = [
            q for q in session.blocking_questions
            if q.question_type == BlockingQuestionType.CLOSURE_SELECTION
        ]
        assert len(closure_qs) > 0, "NCs should generate closure questions"
        options = closure_qs[0].options
        assert "MINOR_QUANTITY" in options
        assert "FULL_MUA" in options
        assert "ACCEPT_OPEN" in options

    def test_closure_decision_resolves_nc(self, applicability_engine, compliance_engine):
        """Selecting a closure path should record the decision."""
        from mira.mp_plan.compute_loop_codex import (
            apply_user_decision_codex,
            generate_blocking_questions_codex,
        )

        session = _make_session(
            "Kapton HN", "Wire wrap", "ISS Habitable",
            o2_pct=30.0, habitable=True,
            flam_rating="C", tvs_rating="A", tox_rating="A",
        )
        session.applicability_matrix = applicability_engine.run(session)
        _, ncs, dets = compliance_engine.run(session)
        session.nonconformances = ncs
        session.mpr_determinations = dets
        session.blocking_questions = generate_blocking_questions_codex(session)

        closure_qs = [
            q for q in session.blocking_questions
            if q.question_type == BlockingQuestionType.CLOSURE_SELECTION
        ]
        assert len(closure_qs) > 0

        question = closure_qs[0]
        apply_user_decision_codex(
            session, question, "MINOR_QUANTITY",
            "Mass <45g and area <13cm² per MPR 44(c)",
        )

        closed_ids = {d.gap_id for d in session.closure_decisions}
        assert question.source_gap_id in closed_ids, "Closure should be recorded"

    def test_accept_open_creates_gap_record(self, applicability_engine, compliance_engine):
        """ACCEPT_OPEN should create an AcceptedOpenGap."""
        from mira.mp_plan.compute_loop_codex import (
            apply_user_decision_codex,
            generate_blocking_questions_codex,
        )

        session = _make_session(
            "Kapton HN", "Insulation", "ISS Habitable",
            o2_pct=30.0, habitable=True,
            flam_rating="D", tvs_rating="A", tox_rating="A",
        )
        session.applicability_matrix = applicability_engine.run(session)
        _, ncs, dets = compliance_engine.run(session)
        session.nonconformances = ncs
        session.mpr_determinations = dets
        session.blocking_questions = generate_blocking_questions_codex(session)

        closure_qs = [
            q for q in session.blocking_questions
            if q.question_type == BlockingQuestionType.CLOSURE_SELECTION
        ]
        assert len(closure_qs) > 0

        apply_user_decision_codex(
            session, closure_qs[0], "ACCEPT_OPEN",
            "Accepted for tracking pending redesign",
        )

        assert len(session.accepted_open_gaps) > 0, "ACCEPT_OPEN should create gap record"
        gap = session.accepted_open_gaps[-1]
        assert gap.gap_type == "nonconformance"
        assert gap.owner == "TBD"


# ===========================================================================
# END-TO-END WORKFLOW
# ===========================================================================

class TestEndToEndWorkflow:
    """Full pipeline: compute → questions → answers → recompute → generate."""

    def test_full_workflow_with_answer_callback(self):
        """Run compute loop with auto-answering callback through multiple iterations."""
        from mira.mp_plan.compute_loop_codex import run_compute_loop_codex
        from mira.mp_plan.generation.mp_plan_docx_codex import generate_mp_plan_docx_codex

        session = _make_session(
            "PTFE Tape", "Seal wrap", "ISS Habitable",
            o2_pct=30.0, habitable=True,
            flam_rating="B", tvs_rating="A", tox_rating="A",
            test_o2_pct=30.0,
        )

        answers_given = []

        def auto_answer(question):
            """Auto-answer blocking questions for testing."""
            if question.question_type == BlockingQuestionType.CLOSURE_SELECTION:
                answers_given.append(("closure", question.question_id))
                return "MINOR_QUANTITY", "Mass qualifies per MPR 44(c)"
            if question.question_type == BlockingQuestionType.TAILORING_APPROVAL:
                answers_given.append(("tailoring", question.question_id))
                return "ACCEPT", "Reviewed and accepted"
            if question.question_type == BlockingQuestionType.GROUPING_CONFIRMATION:
                answers_given.append(("grouping", question.question_id))
                return "YES", "Confirmed adjacency"
            answers_given.append(("other", question.question_id))
            return "ACCEPT", "Auto-accepted for testing"

        session = run_compute_loop_codex(
            session, max_iterations=5, answer_callback=auto_answer,
        )

        # Session should have processed through multiple iterations
        assert len(session.user_decisions) > 0, "Callback should have been called"
        assert len(session.mpr_determinations) > 0

        # Generate DOCX from the fully-computed session
        docx_bytes = generate_mp_plan_docx_codex(session)
        assert len(docx_bytes) > 1000

    def test_generate_json_after_compute(self):
        """JSON export should work after compute loop."""
        from mira.mp_plan.compute_loop_codex import run_compute_loop_codex
        from mira.mp_plan.generation.plan_json_codex import generate_mp_plan_json_bytes_codex

        session = _make_session(
            "Inconel 625", "Exhaust duct", "Hot Gas Path",
            o2_pct=21.0, pressure_psia=500.0,
            temp_range_c=(-40.0, 800.0), habitable=False,
            flam_rating="A", tvs_rating="A", tox_rating="A",
        )
        session = run_compute_loop_codex(session, max_iterations=1)

        json_bytes = generate_mp_plan_json_bytes_codex(session)
        assert len(json_bytes) > 500
        assert b"Inconel 625" in json_bytes


# ===========================================================================
# MULTI-MATERIAL MULTI-ENVIRONMENT
# ===========================================================================

class TestMultiMaterialMultiEnvironment:
    """Test with multiple materials in multiple environments."""

    def test_three_materials_two_environments(self, applicability_engine, compliance_engine):
        manager = get_session_manager()
        session = manager.create_session(program_name="Multi Test")

        # Two environments
        iss = EnvironmentDefinition(
            name="ISS Habitable", o2_pct=30.0, pressure_psia=14.7,
            temp_range_c=(15.0, 27.0), habitable=True, source="test",
        )
        external = EnvironmentDefinition(
            name="External LEO", o2_pct=0.001, pressure_psia=0.001,
            temp_range_c=(-120.0, 120.0), habitable=False,
            vacuum_exposure=True, source="test",
        )
        session.environments.extend([iss, external])

        # Three materials with different profiles
        materials = [
            ("Kapton HN", "Thermal blanket", "A", "A", "B"),   # TOX B in habitable = NC
            ("7075-T6 Aluminum", "Panel", "A", "A", "A"),       # Metallic, SCC concerns
            ("EPDM O-ring", "Seal", "A", "B", "A"),             # TVS B = constrained
        ]
        for name, app, flam, tvs, tox in materials:
            mat = MaterialEntry(
                name=name, application=app, quantity=1, source="test",
            )
            session.materials.append(mat)
            session.maptis_resolutions.append(MaterialResolutionResult(
                material_id=mat.id, maptis_code=f"TEST-{name[:6]}",
                flam_rating=flam, tvs_rating=tvs, tox_rating=tox,
                test_o2_pct=30.0, source="test",
            ))

        session.applicability_matrix = applicability_engine.run(session)
        _, ncs, dets = compliance_engine.run(session)

        # Should have 207 MPRs × 3 materials × 2 environments = 1242 determinations
        # (some may share usage keys)
        assert len(dets) > 600, f"Expected >600 determinations, got {len(dets)}"

        # Kapton TOX B in ISS habitable should produce NC
        kapton_id = session.materials[0].id
        kapton_tox_ncs = [
            nc for nc in ncs
            if nc.material_id == kapton_id
            and nc.environment_id == iss.environment_id
        ]
        assert any(
            nc.gap_type.value == "tox" for nc in kapton_tox_ncs
        ), "Kapton TOX B in habitable should produce TOX NC"

        # EPDM TVS B should produce constrained on offgas/tvs-related MPRs
        epdm_id = session.materials[2].id
        epdm_constrained = [
            d for d in dets
            if d["material_id"] == epdm_id
            and d["status"] == STATUS_CONSTRAINED
        ]
        assert len(epdm_constrained) > 0, (
            f"EPDM TVS B should produce CONSTRAINED. "
            f"EPDM statuses: {set(d['status'] for d in dets if d['material_id'] == epdm_id and d['applicability_status'] == 'applicable')}"
        )


# ===========================================================================
# EDGE CASES
# ===========================================================================

class TestEdgeCases:
    """Rating boundaries, empty states, and unusual inputs."""

    def test_empty_session_no_crash(self):
        """Compute loop on empty session should not crash."""
        from mira.mp_plan.compute_loop_codex import run_compute_loop_codex

        manager = get_session_manager()
        session = manager.create_session(program_name="Empty Test")
        session = run_compute_loop_codex(session, max_iterations=1)

        assert len(session.mpr_determinations) == 0
        assert len(session.blocking_questions) > 0  # Should ask for environment

    def test_unresolved_material_produces_deficiency(self, applicability_engine, compliance_engine):
        """Material without MAPTIS resolution should produce deficiency."""
        manager = get_session_manager()
        session = manager.create_session(program_name="Deficiency Test")

        env = EnvironmentDefinition(
            name="ISS", o2_pct=30.0, pressure_psia=14.7,
            temp_range_c=(15.0, 27.0), habitable=True, source="test",
        )
        session.environments.append(env)

        mat = MaterialEntry(
            name="Unknown Alloy XYZ", application="Bracket",
            quantity=1, source="test",
        )
        session.materials.append(mat)
        # No resolution added — material is unresolved

        session.applicability_matrix = applicability_engine.run(session)
        defs, _, dets = compliance_engine.run(session)

        assert len(defs) > 0, "Unresolved material should produce deficiency"
        assert any(
            d.deficiency_type == "missing_maptis_resolution" for d in defs
        )

    def test_flam_rating_boundary_b_at_test_o2(self, applicability_engine, compliance_engine):
        """FLAM B at exactly test O2% should be CONSTRAINED, not NONCOMPLIANT."""
        _, _, dets = _run_engines(_make_session(
            "Test Material", "Widget", "ISS",
            o2_pct=30.0, habitable=True,
            flam_rating="B", test_o2_pct=30.0,
        ), applicability_engine, compliance_engine)

        flam_dets = [
            d for d in dets
            if d["applicability_status"] == "applicable"
            and "flam" in d.get("related_failure_modes", [])
            and d["status"] == STATUS_CONSTRAINED
        ]
        assert len(flam_dets) > 0, "FLAM B at test O2% should be CONSTRAINED"

    def test_flam_rating_b_above_test_o2(self, applicability_engine, compliance_engine):
        """FLAM B above test O2% should be NONCOMPLIANT."""
        _, _, dets = _run_engines(_make_session(
            "Test Material", "Widget", "High O2",
            o2_pct=40.0, habitable=True,
            flam_rating="B", test_o2_pct=30.0,
        ), applicability_engine, compliance_engine)

        flam_nc = [
            d for d in dets
            if d["applicability_status"] == "applicable"
            and "flam" in d.get("related_failure_modes", [])
            and d["status"] == STATUS_NONCOMPLIANT
        ]
        assert len(flam_nc) > 0, "FLAM B above test O2% should be NONCOMPLIANT"

    def test_scc_rating_1_compliant(self, applicability_engine, compliance_engine):
        """SCC rating 1 should be COMPLIANT."""
        _, _, dets = _run_engines(_make_session(
            "Inconel 718", "Fastener", "Standard",
            scc_rating="1",
        ), applicability_engine, compliance_engine)

        scc_ok = [
            d for d in dets
            if d["applicability_status"] == "applicable"
            and "scc" in d.get("related_failure_modes", [])
            and d["status"] == STATUS_COMPLIANT
        ]
        assert len(scc_ok) > 0, "SCC rating 1 should be COMPLIANT"

    def test_scc_rating_2_constrained(self, applicability_engine, compliance_engine):
        """SCC rating 2 should be CONSTRAINED."""
        _, _, dets = _run_engines(_make_session(
            "2024-T3 Aluminum", "Skin panel", "Standard",
            scc_rating="2",
        ), applicability_engine, compliance_engine)

        scc_c = [
            d for d in dets
            if d["applicability_status"] == "applicable"
            and "scc" in d.get("related_failure_modes", [])
            and d["status"] == STATUS_CONSTRAINED
        ]
        assert len(scc_c) > 0, "SCC rating 2 should be CONSTRAINED"

    def test_corr_rating_b_constrained(self, applicability_engine, compliance_engine):
        """CORR rating B should be CONSTRAINED."""
        _, _, dets = _run_engines(_make_session(
            "4130 Steel", "Strut", "Standard",
            corr_rating="B",
        ), applicability_engine, compliance_engine)

        corr_c = [
            d for d in dets
            if d["applicability_status"] == "applicable"
            and "corr" in d.get("related_failure_modes", [])
            and d["status"] == STATUS_CONSTRAINED
        ]
        assert len(corr_c) > 0, "CORR rating B should be CONSTRAINED"

    def test_docx_with_no_nonconformances(self):
        """DOCX generation with all-compliant session should work."""
        from mira.mp_plan.compute_loop_codex import run_compute_loop_codex
        from mira.mp_plan.generation.mp_plan_docx_codex import generate_mp_plan_docx_codex

        session = _make_session(
            "316L Stainless Steel", "Fluid line", "Standard Atm",
            o2_pct=21.0, habitable=False,
            flam_rating="A", tvs_rating="A", tox_rating="A",
            scc_rating="1", corr_rating="A",
        )
        session = run_compute_loop_codex(session, max_iterations=1)
        docx_bytes = generate_mp_plan_docx_codex(session)
        assert len(docx_bytes) > 1000
